"""Run in WSL (Linux x86_64) with the tflite-micro Python package. HOST measurement of the
TFLite-Micro interpreter (reference kernels): minimum tensor-arena size that allocates, and
output parity vs host TFLite. Not an STM32 measurement (CMSIS-NN kernels/alignment may differ)."""
import json, sys
import numpy as np
from tflite_micro.python.tflite_micro import runtime

model = sys.argv[1]; data = np.load(sys.argv[2])
def try_arena(n):
    try:
        it = runtime.Interpreter.from_file(model, arena_size=n)
        it.set_input(data["x"][0:1], 0); it.invoke(); return it
    except Exception:
        return None
lo, hi = 16 * 1024, 1024 * 1024
assert try_arena(hi) is not None, "model does not run even with 1 MiB arena"
while hi - lo > 256:
    mid = (lo + hi) // 2
    if try_arena(mid): hi = mid
    else: lo = mid
it = runtime.Interpreter.from_file(model, arena_size=hi)
refs = sorted([k for k in data.files if k.startswith("out")], key=lambda k: int(k[3:].split("_")[0]))
n_out = len(refs)
maxdiff, argmax_agree = 0, []
for i in range(len(data["x"])):
    it.set_input(data["x"][i:i + 1], 0); it.invoke()
    outs = [it.get_output(j)[0] for j in range(n_out)]
    # match outputs to references by shape+values (TFLM output order = model output order)
    for j, o in enumerate(outs):
        r = data[refs[j]][i] if data[refs[j]][i].shape == o.shape else None
        if r is None: continue
        maxdiff = max(maxdiff, int(np.abs(o.astype(int) - r.astype(int)).max()))
        argmax_agree.append(int(o.argmax() == r.argmax()))
print(json.dumps({"tflm_min_arena_bytes_found": hi, "search_resolution_bytes": 256,
                  "outputs_compared": len(argmax_agree), "argmax_agreement_vs_host_tflite": float(np.mean(argmax_agree)),
                  "max_abs_int8_diff_vs_host_tflite": maxdiff}, indent=1))
