"""WSL host: run the INT8 model through TFLite-Micro (reference kernels) on the full Model 1
TEST split and compute fruit/condition macro-F1. Output tensors follow the alphabetical signature
keys: condition (:0, 2 classes), fruit (:1, 5 classes), quality_apple (:2, 2 classes), ...
TFLM output j0 = condition, j6 = fruit (order verified in tflm_parity_detail.py).
Host run, not an STM32 run."""
import json, sys
import numpy as np
from tflite_micro.python.tflite_micro import runtime
d = np.load(sys.argv[2]); it = runtime.Interpreter.from_file(sys.argv[1], arena_size=int(sys.argv[3]))
pf, pc = [], []
for i in range(len(d["x"])):
    it.set_input(d["x"][i:i + 1], 0); it.invoke()
    outs = [it.get_output(j)[0] for j in range(8)]
    assert outs[6].shape == (5,) and outs[0].shape == (2,)
    pf.append(outs[6].argmax())
    pc.append(outs[0].argmax())
def f1(y, p, k):
    s = []
    for c in range(k):
        tp = ((p == c) & (y == c)).sum(); fp = ((p == c) & (y != c)).sum(); fn = ((p != c) & (y == c)).sum()
        s.append(0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(s))
pf, pc = np.array(pf), np.array(pc)
print(json.dumps({"runtime": "TFLite-Micro (host, reference kernels)", "n": len(pf),
                  "fruit_macro_f1": round(f1(d["fruit"], pf, 5), 4), "condition_macro_f1": round(f1(d["condition"], pc, 2), 4)}))
