"""Static memory analysis of a TFLite model (no execution of the target, no model changes).

For every operator: live activation bytes (tensors produced <= op <= last use; graph
input from the start, graph outputs to the end; constants excluded) and the CMSIS-NN
scratch buffer that the Cortex-M4 (ARM_MATH_DSP, GCC) code path would request,
using the formulas in CMSIS-NN (pinned commit 4ab83cc3):
  CONV_2D 1x1 stride1 pad0  : arm_convolve_1x1_s8_fast   -> 0 B (GCC; ARMCC 2*Cin*2)
  CONV_2D general           : arm_convolve_s8            -> 2*align4(Cin*Kh*Kw)*2 B
  DEPTHWISE_CONV_2D Cin=Cout: arm_depthwise_conv_s8_opt  -> Cin*Kh*Kw*2 B
  FULLY_CONNECTED           : 0 B (DSP)
Outputs a lower bound for any non-in-place planner and the per-op peak, for the
portable path (scratch 0) and the DSP path. ESTIMATE for DSP: must be confirmed on target.

Usage: python tools/stm32_memory/static_plan.py MODEL.tflite [OUT.json]
"""

from __future__ import annotations

import json
import sys

import numpy as np
import tensorflow as tf


def align(n, a=16):
    return (n + a - 1) // a * a


def main() -> None:
    path = sys.argv[1]
    it = tf.lite.Interpreter(model_path=path,
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    it.allocate_tensors()
    T = {d["index"]: d for d in it.get_tensor_details()}
    ops = it._get_ops_details()
    gin = [d["index"] for d in it.get_input_details()]
    gout = [d["index"] for d in it.get_output_details()]
    produced = {i: k for k, op in enumerate(ops) for i in op["outputs"]}
    nbytes = lambda i: int(np.prod(T[i]["shape"])) * np.dtype(T[i]["dtype"]).itemsize  # noqa: E731
    act = set(produced) | set(gin)
    first = {i: (produced[i] if i in produced else -1) for i in act}
    last = {i: first[i] for i in act}
    for k, op in enumerate(ops):
        for i in op["inputs"]:
            if i in act:
                last[i] = max(last[i], k)
    for i in gout:
        last[i] = len(ops)
    const_bytes = sum(nbytes(i) for i in T if i not in act and T[i]["shape"].size and nbytes(i) > 0)

    rows = []
    for k, op in enumerate(ops):
        live = [i for i in act if first[i] <= k <= last[i]]
        live_b = sum(align(nbytes(i)) for i in live)
        scratch = 0
        name = op["op_name"]
        if name in ("CONV_2D", "DEPTHWISE_CONV_2D"):
            x, w = T[op["inputs"][0]]["shape"], T[op["inputs"][1]]["shape"]
            cin = int(x[3])
            if name == "CONV_2D":
                kh, kw = int(w[1]), int(w[2])
                is_1x1 = kh == 1 and kw == 1
                out = T[op["outputs"][0]]["shape"]
                stride1 = int(out[1]) == int(x[1]) and int(out[2]) == int(x[2])
                scratch = 0 if (is_1x1 and stride1) else 2 * ((cin * kh * kw + 3) // 4 * 4) * 2
            else:
                kh, kw = int(w[1]), int(w[2])
                cout = int(w[3])
                scratch = cin * kh * kw * 2 if cin == cout else 0
        rows.append({"op": k, "name": name, "live_activation_bytes": live_b,
                     "dsp_scratch_bytes": scratch, "dsp_total": live_b + align(scratch) if scratch else live_b,
                     "out_shape": [int(s) for s in T[op["outputs"][0]]["shape"]]})
    peak_portable = max(r["live_activation_bytes"] for r in rows)
    peak_dsp = max(r["dsp_total"] for r in rows)
    top = sorted(rows, key=lambda r: -r["dsp_total"])[:5]
    res = {"model": path, "n_ops": len(ops), "n_tensors": len(T),
           "input": {"shape": [int(s) for s in T[gin[0]]["shape"]], "dtype": str(T[gin[0]]["dtype"].__name__),
                     "bytes": nbytes(gin[0]), "quantization": [float(T[gin[0]]["quantization"][0]),
                                                               int(T[gin[0]]["quantization"][1])]},
           "outputs": [{"index": i, "shape": [int(s) for s in T[i]["shape"]], "dtype": T[i]["dtype"].__name__,
                        "bytes": nbytes(i)} for i in gout],
           "constant_tensor_bytes": int(const_bytes),
           "peak_live_activations_portable_bytes": int(peak_portable),
           "peak_live_activations_plus_dsp_scratch_bytes_ESTIMATE": int(peak_dsp),
           "max_dsp_scratch_single_op_bytes": int(max(r["dsp_scratch_bytes"] for r in rows)),
           "top_ops_by_dsp_total": top}
    out = json.dumps(res, indent=1)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(out)
    print(out)


if __name__ == "__main__":
    main()
