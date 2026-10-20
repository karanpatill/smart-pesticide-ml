"""Compare host32 fv_vision raw outputs (reports/firmware/host32_fv_vision_raw.txt) with the TFLite
interpreter (reference kernels) on the same 20 int8 inputs, through the generated head mapping."""
import json, pathlib, re, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load_header():
    h = (ROOT / "firmware/stm32f407/generated/fv_generated_config.h").read_text()
    idx = [int(x) for x in re.search(r"FV_HEAD_OUTPUT_INDEX\[\w*\]\s*=\s*\{([^}]*)\}", h).group(1).split(",")]
    ncl = [int(x) for x in re.search(r"FV_HEAD_N_CLASSES\[\w*\]\s*=\s*\{([^}]*)\}", h).group(1).split(",")]
    return idx, ncl


def reference(paths):
    import tensorflow as tf
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    inp, outs = it.get_input_details()[0], it.get_output_details()
    res = []
    for p in paths:
        it.set_tensor(inp["index"], np.fromfile(p, dtype=np.int8).reshape(inp["shape"]))
        it.invoke()
        res.append([it.get_tensor(o["index"]).reshape(-1) for o in outs])
    return res


def main():
    lines = (ROOT / "reports/firmware/host32_fv_vision_raw.txt").read_text().splitlines()
    raws = [list(map(int, l.split()[1:])) for l in lines if l.startswith("RAW")]
    paths = sorted((ROOT / "reports/stm32_memory/test_inputs").glob("in*.int8"))
    idx, ncl = load_header()
    ref = reference(paths)
    exact, maxdiff, argmax_same = 0, 0, 0
    for r, ro in zip(raws, ref):
        got = [np.array(r[5 * h:5 * h + ncl[h]]) for h in range(len(idx))]
        exp = [ro[idx[h]].astype(int) for h in range(len(idx))]
        d = max(int(np.abs(g - e).max()) for g, e in zip(got, exp))
        maxdiff = max(maxdiff, d); exact += d == 0
        argmax_same += all(int(g.argmax()) == int(e.argmax()) for g, e in zip(got, exp))
    out = {"n": len(raws), "exact_match": exact, "max_abs_int8_diff": maxdiff, "all_head_argmax_same": argmax_same,
           "device": "host32 x86 (zig), TFLM CMSIS-NN portable int8 kernels, split arenas -- NOT STM32",
           "reference": "tf.lite.Interpreter BUILTIN_REF kernels (Windows)"}
    (ROOT / "reports/firmware/host32_fv_vision_vs_tflite.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out))
    return 0 if len(raws) == len(paths) == 20 else 1


if __name__ == "__main__":
    sys.exit(main())
