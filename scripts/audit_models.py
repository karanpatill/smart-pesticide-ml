"""Audit: load every deployed model in a clean process, check interfaces and label
orders against the code, and re-compute headline TEST metrics from the saved
artifacts. Read-only: no model file is written.

Usage (clean process recommended):
  python -I scripts/audit_models.py
Output: reports/audit/model_audit.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import tensorflow as tf  # noqa: E402
from sklearn.metrics import f1_score  # noqa: E402

from fruitvision import postprocess as pp  # noqa: E402
from fruitvision.config import load_config  # noqa: E402
from fruitvision.sensor.synthetic import SENSOR_COLS  # noqa: E402
from fruitvision.training import cached_images  # noqa: E402


def main() -> None:
    res, issues = {}, []
    cfg = load_config()

    # ---- Model 1 ----
    m1 = tf.keras.models.load_model(ROOT / "models/model1/model1_final.keras")
    lab1 = json.loads((ROOT / "models/model1/labels.json").read_text())
    fr1 = [lab1["outputs"]["fruit"][str(i)] for i in range(len(lab1["outputs"]["fruit"]))]
    co1 = [lab1["outputs"]["condition"][str(i)] for i in range(len(lab1["outputs"]["condition"]))]
    out_shapes = {k: list(v.shape) for k, v in m1.output.items()}
    res["model1"] = {"input": list(m1.input_shape), "outputs": out_shapes, "fruit_order": fr1,
                     "condition_order": co1, "params": int(m1.count_params())}
    for name, order in [("configs/config.yaml fruits", cfg["fruits"]), ("postprocess.FRUITS", pp.FRUITS)]:
        if order != fr1:
            issues.append(f"fruit order mismatch: {name} {order} vs model1 labels {fr1}")
    if co1 != cfg["conditions"]:
        issues.append(f"condition order mismatch: config {cfg['conditions']} vs {co1}")

    te = pd.read_csv(ROOT / "data/splits/test.csv")
    x = cached_images(list(te.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype("float32")
    o = m1.predict(x, verbose=0, batch_size=256)
    pf = np.array(fr1)[o["fruit"].argmax(1)]
    pc = np.array(co1)[o["condition"].argmax(1)]
    res["model1"]["test_recomputed"] = {
        "n": len(te), "fruit_macro_f1": round(float(f1_score(te.fruit, pf, average="macro")), 4),
        "condition_macro_f1": round(float(f1_score(te.condition, pc, average="macro")), 4)}
    reported = json.loads((ROOT / "models/model1/metrics.json").read_text())["final/test"]
    res["model1"]["test_reported"] = {"fruit_macro_f1": round(reported["fruit_macro_f1"], 4),
                                      "condition_macro_f1": round(reported["condition_macro_f1"], 4)}

    # ---- Model 3 combined ----
    m3 = tf.keras.models.load_model(ROOT / "models/model3/model3_combined.keras")
    lab3 = json.loads((ROOT / "models/model3/labels.json").read_text())
    res["model3"] = {"input": list(m3.input_shape), "outputs": {k: list(v.shape) for k, v in m3.output.items()},
                     "heads": {h: [lab3[h][str(i)] for i in range(len(lab3[h]))] for h in lab3}}
    o3 = m3.predict(x[:256], verbose=0)
    res["model3"]["fruit_condition_identical_to_model1"] = bool(
        np.allclose(o3["fruit"], o["fruit"][:256], atol=1e-6) and np.allclose(o3["condition"], o["condition"][:256], atol=1e-6))
    for f, h in {**pp.QUALITY_HEAD, **pp.STAGE_HEAD}.items():
        if h not in lab3:
            issues.append(f"postprocess routes {f} to missing head {h}")
    pcfg = json.loads((ROOT / "models/model3/postprocess_config.json").read_text())
    ccfg = json.loads((ROOT / "configs/model3_postprocess.json").read_text())
    if pcfg != ccfg:
        issues.append("models/model3/postprocess_config.json differs from configs/model3_postprocess.json")

    # ---- Model 2 (selected prototype) ----
    m2 = joblib.load(ROOT / "models/model2_prototype/S__logreg.joblib")
    pre, clf = m2.named_steps["pre"], m2.named_steps["clf"]
    syn = pd.read_csv(ROOT / "data/synthetic/model2/model2_synthetic_v1.csv")
    split = pd.read_csv(ROOT / "data/synthetic/model2/splits_v1.csv")
    syn = syn.merge(split[["meta_sample_id", "split"]], on="meta_sample_id")
    t2 = syn[syn.split == "test"].copy()
    for ch in "rgb":
        t2[f"drv_tcs_{ch}_over_c"] = t2[f"sensor_tcs_{ch}"] / t2["sensor_tcs_c"]
    t2["drv_log_mq135"] = np.log(t2["sensor_mq135"])
    cls = ["LOW", "MEDIUM", "HIGH"]
    p2 = np.array(cls)[m2.predict(t2[list(pre.feature_names_in_)]).astype(int)]
    res["model2"] = {"pipeline": [s for s, _ in m2.steps], "features_in": list(pre.feature_names_in_),
                     "classes_": clf.classes_.tolist(), "class_meaning": "0=LOW 1=MEDIUM 2=HIGH (model2_train.py CLASSES)",
                     "coef_shape": list(clf.coef_.shape), "multi_class": "multinomial (lbfgs default)",
                     "test_recomputed_macro_f1_SYNTHETIC": round(float(f1_score(t2.target_risk, p2, average="macro")), 4),
                     "test_reported_macro_f1_SYNTHETIC": json.loads(
                         (ROOT / "reports/model2/experiments/S/logreg/result.json").read_text())["test"]["macro_f1"]}
    if list(pre.feature_names_in_)[:8] != SENSOR_COLS:
        issues.append("Model 2 feature order differs from SENSOR_COLS")

    res["issues"] = issues
    out = ROOT / "reports/audit/model_audit.json"
    out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
