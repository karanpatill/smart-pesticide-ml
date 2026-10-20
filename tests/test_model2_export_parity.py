"""Model 2 export parity: sklearn joblib vs exported-JSON numpy runtime vs compiled C.

All comparisons use the SAME raw feature vectors (the full synthetic dataset plus
edge cases). Agreement shows the export is faithful; it says nothing about real-world
pesticide detection (the model is a synthetic-data prototype).
"""

import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from fruitvision.sensor.risk_model import Model2

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "models/model2_export/model2_logreg.json"
RAW_COLS = ["sensor_tcs_r", "sensor_tcs_g", "sensor_tcs_b", "sensor_tcs_c",
            "sensor_mq135", "sensor_ph", "sensor_temp_c", "sensor_humidity_pct"]


@pytest.fixture(scope="module")
def data():
    syn = pd.read_csv(ROOT / "data/synthetic/model2/model2_synthetic_v1.csv")
    raw = syn[RAW_COLS].to_numpy(np.float64)
    df = syn[RAW_COLS].copy()
    for ch in "rgb":
        df[f"drv_tcs_{ch}_over_c"] = df[f"sensor_tcs_{ch}"] / df["sensor_tcs_c"]
    df["drv_log_mq135"] = np.log(df["sensor_mq135"])
    ref = joblib.load(ROOT / "models/model2_prototype/S__logreg.joblib").predict_proba(df)
    return raw, ref


def test_json_runtime_matches_sklearn(data):
    raw, ref = data
    p = Model2(SPEC).predict_proba(raw)
    assert np.abs(p - ref).max() < 1e-9
    assert (p.argmax(1) == ref.argmax(1)).all()


def _build_c(tmp_path):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang (C compiler) not installed")
    exe = tmp_path / "m2_parity.exe"
    cmd = [sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
           f"-I{ROOT / 'models/model2_export'}", "-o", str(exe),
           str(ROOT / "firmware/model2/model2_infer.c"), str(ROOT / "firmware/model2/tests/m2_parity_main.c")]
    subprocess.run(cmd, check=True, capture_output=True)
    return exe


def _run_c(exe, rows):
    txt = "\n".join(" ".join(f"{v:.9g}" for v in r) for r in rows) + "\n"
    out = subprocess.run([str(exe)], input=txt, capture_output=True, text=True, check=True).stdout.split("\n")
    return [o.split() for o in out if o.strip()]


def test_c_matches_sklearn(data, tmp_path):
    raw, ref = data
    res = _run_c(_build_c(tmp_path), raw)
    assert len(res) == len(raw)
    st = np.array([int(r[0]) for r in res])
    p = np.array([[float(x) for x in r[1:4]] for r in res])
    cls = np.array([int(r[4]) for r in res])
    assert (st == 0).all()
    assert np.abs(p - ref).max() < 1e-5          # float32 C vs float64 reference
    margin = np.sort(ref, 1)[:, -1] - np.sort(ref, 1)[:, -2]
    assert ((cls == ref.argmax(1)) | (margin < 1e-5)).all()
    assert np.allclose(p.sum(1), 1, atol=1e-6)


def test_c_error_codes(tmp_path):
    rows = [[float("nan"), 1, 1, 1, 900, 4, 25, 60],      # non-finite -> 2
            [300, 500, 800, float("inf"), 900, 4, 25, 60],
            [300, 500, 800, 0, 900, 4, 25, 60],          # tcs_c <= 0 -> 3
            [300, 500, 800, 1500, 0, 4, 25, 60]]         # mq135 <= 0 -> 3
    res = _run_c(_build_c(tmp_path), rows)
    assert [int(r[0]) for r in res] == [2, 2, 3, 3]
    assert all(int(r[4]) == -1 and float(r[1]) == 0 for r in res)


def test_export_records_class_and_feature_order():
    import json
    s = json.loads(SPEC.read_text())
    assert s["classes"] == ["LOW", "MEDIUM", "HIGH"]
    assert s["feature_order"][:8] == RAW_COLS and len(s["feature_order"]) == 12
    assert "SYNTHETIC" in s["evidence_level"]
