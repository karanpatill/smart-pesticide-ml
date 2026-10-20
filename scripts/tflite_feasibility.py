"""EXPERIMENTAL TFLite conversion of the combined Model 1 + Model 3 graph.

* Reads models/model3/model3_combined.keras READ-ONLY (Model 1 weights inside are frozen).
* Writes NEW files only: models/experimental/tflite/{combined_float32,combined_int8}.tflite
* INT8: full-integer, int8 input/output, representative set = TRAIN images only
  (Model 1 train split + Model 3 new-split train images), stratified.
* Measures: file sizes, operator list, activation-memory lower bound, and the
  conversion error on held-out TEST images (agreement and macro-F1, INT8 vs Keras).

Nothing here is an STM32 measurement: no target build or hardware run is performed.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fruitvision.training import cached_images  # noqa: E402

OUT = ROOT / "models/experimental/tflite"
FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
CONDS = ["fresh", "spoiled"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


NO_DELEGATE = tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES


def peak_activation_bytes(model_bytes: bytes) -> int:
    it = tf.lite.Interpreter(model_content=model_bytes, experimental_op_resolver_type=NO_DELEGATE)
    it.allocate_tensors()
    t = {d["index"]: d for d in it.get_tensor_details()}
    produced = {i for op in it._get_ops_details() for i in op["outputs"]} | {d["index"] for d in it.get_input_details()}
    peak = 0
    for op in it._get_ops_details():
        ids = [i for i in list(op["inputs"]) + list(op["outputs"]) if i in produced]
        peak = max(peak, sum(int(np.prod(t[i]["shape"])) * np.dtype(t[i]["dtype"]).itemsize for i in ids))
    return peak


def run_tflite(model_bytes: bytes, x: np.ndarray) -> dict:
    it = tf.lite.Interpreter(model_content=model_bytes)
    runner = it.get_signature_runner()
    inp_name = list(runner.get_input_details())[0]
    ind = runner.get_input_details()[inp_name]
    outd = runner.get_output_details()
    res = {k: [] for k in outd}
    for i in range(len(x)):
        xi = x[i:i + 1].astype(np.float32)
        if ind["dtype"] == np.int8:
            s, z = ind["quantization"]
            xi = np.clip(np.round(xi / s + z), -128, 127).astype(np.int8)
        o = runner(**{inp_name: xi})
        for k, v in o.items():
            if outd[k]["dtype"] == np.int8:
                s, z = outd[k]["quantization"]
                v = (v.astype(np.float32) - z) * s
            res[k].append(v[0])
    return {k: np.stack(v) for k, v in res.items()}


def main() -> None:
    src = ROOT / "models/model3/model3_combined.keras"
    src_hash = sha(src)
    model = tf.keras.models.load_model(src)
    OUT.mkdir(parents=True, exist_ok=True)

    # representative TRAIN images (never val/test)
    m1tr = pd.read_csv(ROOT / "data/splits/train.csv")[["path", "fruit", "condition"]]
    man = pd.read_csv(ROOT / "data/model3/manifest.csv")
    m3tr = man[(man.split == "train") & (man.split_origin == "new_group_split")][["path", "task"]]
    rep = pd.concat([m1tr.groupby(["fruit", "condition"]).sample(30, random_state=0)[["path"]],
                     m3tr.groupby("task").sample(20, random_state=0)[["path"]]]).drop_duplicates("path")
    xr = cached_images(list(rep.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype(np.float32)

    def repgen():
        for i in range(len(xr)):
            yield [xr[i:i + 1]]

    with tempfile.TemporaryDirectory() as tmp:
        model.export(tmp)
        f32 = tf.lite.TFLiteConverter.from_saved_model(tmp).convert()
        conv = tf.lite.TFLiteConverter.from_saved_model(tmp)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = repgen
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        i8 = conv.convert()
    (OUT / "combined_float32.tflite").write_bytes(f32)
    (OUT / "combined_int8.tflite").write_bytes(i8)

    it = tf.lite.Interpreter(model_content=i8, experimental_op_resolver_type=NO_DELEGATE)  # list MODEL ops, not host delegates
    it.allocate_tensors()
    ops = sorted({d["op_name"] for d in it._get_ops_details()})

    # held-out TEST evaluation: Keras (reference) vs INT8
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    m3te = man[(man.split == "test")]
    allte = pd.concat([te[["path"]], m3te[["path"]]]).drop_duplicates("path").reset_index(drop=True)
    xt = cached_images(list(allte.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype(np.float32)
    ref = {k: np.asarray(v) for k, v in model.predict(xt, verbose=0, batch_size=256).items()}
    q = run_tflite(i8, xt)
    idx = {p: i for i, p in enumerate(allte.path)}
    labels = json.loads((ROOT / "models/model3/labels.json").read_text())

    ev = {}
    ti = te.path.map(idx).to_numpy()
    for head, names, ycol in (("fruit", FRUITS, "fruit"), ("condition", CONDS, "condition")):
        yk, yq = ref[head][ti].argmax(1), q[head][ti].argmax(1)
        ev[head] = {"n": len(ti), "argmax_agreement_int8_vs_keras": round(float((yk == yq).mean()), 4),
                    "macro_f1_keras": round(float(f1_score(te[ycol], np.array(names)[yk], average="macro")), 4),
                    "macro_f1_int8": round(float(f1_score(te[ycol], np.array(names)[yq], average="macro")), 4),
                    "max_abs_prob_diff": round(float(np.abs(ref[head][ti] - q[head][ti]).max()), 4)}
    for h in labels:
        rows = m3te[m3te.task == h]
        ii = rows.path.map(idx).to_numpy()
        names = [labels[h][str(k)] for k in range(len(labels[h]))]
        yk, yq = ref[h][ii].argmax(1), q[h][ii].argmax(1)
        ev[h] = {"n": len(ii), "argmax_agreement_int8_vs_keras": round(float((yk == yq).mean()), 4),
                 "macro_f1_keras": round(float(f1_score(rows.label, np.array(names)[yk], average="macro")), 4),
                 "macro_f1_int8": round(float(f1_score(rows.label, np.array(names)[yq], average="macro")), 4),
                 "max_abs_prob_diff": round(float(np.abs(ref[h][ii] - q[h][ii]).max()), 4)}

    report = {
        "EXPERIMENTAL": "Host-side TFLite conversion only. No STM32 build or hardware run was performed.",
        "source_keras": {"path": "models/model3/model3_combined.keras", "sha256": src_hash,
                         "sha256_after": sha(src)},
        "representative_images": {"n": len(xr), "origin": "TRAIN splits only"},
        "size_bytes": {"float32": len(f32), "int8": len(i8)},
        "int8_ops": ops,
        "int8_input": {k: str(v) for k, v in it.get_input_details()[0].items() if k in ("shape", "dtype", "quantization")},
        "activation_peak_lower_bound_bytes": peak_activation_bytes(i8),
        "single_backbone_inference": "one graph: shared backbone, 8 outputs (fruit, condition, 6 Model 3 heads)",
        "test_eval_int8_vs_keras": ev,
        "target": {"device": "STM32F407VET6", "flash_bytes": 512 * 1024, "sram_bytes": 192 * 1024,
                   "main_sram_bytes": 128 * 1024, "ccm_bytes": 64 * 1024},
    }
    (OUT / "conversion_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("size_bytes", "int8_ops", "activation_peak_lower_bound_bytes")}, indent=1))
    for k, v in ev.items():
        print(f"{k:15s} n={v['n']:5d} agree={v['argmax_agreement_int8_vs_keras']:.4f} "
              f"F1 keras {v['macro_f1_keras']:.4f} -> int8 {v['macro_f1_int8']:.4f} maxdiff {v['max_abs_prob_diff']}")
    assert report["source_keras"]["sha256"] == report["source_keras"]["sha256_after"]


if __name__ == "__main__":
    main()
