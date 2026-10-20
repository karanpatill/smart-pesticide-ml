"""WSL host check: per-output TFLM vs host-TFLite comparison, matching each TFLM output to the
reference output with the same shape and smallest difference (output order is not assumed)."""
import json, sys
import numpy as np
from tflite_micro.python.tflite_micro import runtime
model, data = sys.argv[1], np.load(sys.argv[2])
arena = int(sys.argv[3])
refs = [k for k in data.files if k.startswith("out")]
it = runtime.Interpreter.from_file(model, arena_size=arena)
X = data["x"]
outs = None
for i in range(len(X)):
    it.set_input(X[i:i + 1], 0); it.invoke()
    o = [it.get_output(j)[0].copy() for j in range(len(refs))]
    outs = [[a] for a in o] if outs is None else [p + [a] for p, a in zip(outs, o)]
outs = [np.stack(o) for o in outs]
report = []
for j, o in enumerate(outs):
    cands = [(k, np.abs(o.astype(int) - data[k].astype(int)).max()) for k in refs if data[k].shape == o.shape]
    k, d = min(cands, key=lambda t: t[1])
    report.append({"tflm_output": j, "matched_ref": k, "max_abs_int8_diff": int(d),
                   "argmax_agreement": float((o.argmax(1) == data[k].argmax(1)).mean())})
print(json.dumps(report, indent=1))
