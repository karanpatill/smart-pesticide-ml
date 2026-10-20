"""fv_app_v9_demo (-DFV_DEMO_PROTO_RISK): risk shown as a PROTOTYPE category only for uncalibrated device readings that
pass every sensor check and lie inside the strict synthetic training range; otherwise "Risk:OUT-RANGE" / UNCERTAIN /
UNAVAILABLE. Apple/guava shelf shows "no data". The default (v5) build must behave exactly as before."""
import json
import re
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from test_fw_stm32_app import APP_C, FORBIDDEN, FW, INC, ROOT, ZIG, _c_line, _need_zig

SPEC = json.loads((ROOT / "models/model2_export/model2_logreg.json").read_text())
RAW = ["tcs_r", "tcs_g", "tcs_b", "tcs_c", "mq135", "ph", "temp_c", "humidity_pct"]
MIN = np.array([SPEC["synthetic_training_ranges_trainval"]["sensor_" + k]["min"] for k in RAW])
MAX = np.array([SPEC["synthetic_training_ranges_trainval"]["sensor_" + k]["max"] for k in RAW])
CATS = ["LOW", "MEDIUM", "HIGH"]


def _py_m2(v):
    r, g, b, c, mq = v[:5]
    x = np.array(list(v) + [r / c, g / c, b / c, np.log(mq)], float)
    z = (x - np.array(SPEC["scaler_mean"])) / np.array(SPEC["scaler_scale"])
    lg = np.array(SPEC["coef"]) @ z + np.array(SPEC["intercept"])
    p = np.exp(lg - lg.max())
    return p / p.sum()


def _build(tmp, flags):
    exe = tmp / ("h_demo.exe" if flags else "h_v5.exe")
    r = subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *flags, *INC, "-o", str(exe),
                              str(FW / "tests/fw_host_harness.c"), str(FW / "tests/fv_vision_host_stub.c"),
                              str(FW / "platform/fv_platform_stm32_pending.c"), *map(str, APP_C)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(lines):
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return [l for l in p.stdout.splitlines() if l.strip()]
    return run


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    _need_zig()
    return _build(tmp_path_factory.mktemp("demo"), ["-DFV_DEMO_PROTO_RISK"])


@pytest.fixture(scope="module")
def v5(tmp_path_factory):
    _need_zig()
    return _build(tmp_path_factory.mktemp("v5"), [])


def _rec(v, origin=0, unit=1, warm=600.0, calib=0, **kw):
    d = dict(has_tcs=1, has_mq=1, has_ph=1, has_temp=1, has_rh=1, r=int(v[0]), g=int(v[1]), b=int(v[2]), c=int(v[3]),
             atime=-1, mq=float(v[4]), unit=unit, warm=warm, ph=float(v[5]), t=float(v[6]), rh=float(v[7]),
             origin=origin, calib=calib, null=0)
    d.update(kw)
    return d


BOARD = [989, 1874, 1959, 5108, 324.0, 9.35, 33.0, 51.0]          # fv_app_v5 diagnostics, 2026-10-17


def _inrange_per_class():
    """One synthetic row per predicted class with all 8 inputs strictly inside the training range (TCS as integers)."""
    df = pd.read_csv(ROOT / "data/synthetic/model2/model2_synthetic_v1.csv")
    out = {}
    for _, row in df.iterrows():
        v = np.array([round(row["sensor_" + k]) if k.startswith("tcs") else np.float32(row["sensor_" + k]) for k in
                      ["tcs_r", "tcs_g", "tcs_b", "tcs_c", "mq135", "ph", "temp_c", "humidity_pct"]], float)
        if not ((v >= MIN) & (v <= MAX)).all() or v[1] >= v[3] or v[2] >= v[3]:
            continue
        p = _py_m2(v)
        k = int(np.argmax(p))
        if k not in out and p[k] > 0.6:
            out[k] = (v, p)
        if len(out) == 3:
            break
    assert len(out) == 3, out.keys()
    return out


def _risk(run, rec):
    err, warn, ood, _vm, state, cat, p0, p1, p2, reasons = run([_c_line(rec)])[0].split()
    return int(err), int(warn), int(state), int(cat), [float(p0), float(p1), float(p2)], int(reasons)


def test_inrange_device_reading_gives_prototype_category(demo):
    for k, (v, p) in _inrange_per_class().items():
        err, warn, state, cat, probs, reasons = _risk(demo, _rec(v))
        assert err == 0 and warn == 0 and state == 3 and cat == k, (v, state, cat)
        assert reasons == 4                                        # UNCALIBRATED stays recorded
        assert np.allclose(probs, p, atol=2e-4)


def test_board_readings_out_of_range_never_get_a_category(demo):
    err, _w, state, cat, probs, reasons = _risk(demo, _rec(BOARD))
    assert err == 0 and state == 1 and cat == -1 and probs == [0.0, 0.0, 0.0] and reasons & 8


def test_strict_range_inside_ood_margin_is_out_of_range(demo):
    v = _inrange_per_class()[0][0].copy()
    v[5] = 6.30                                                   # pH: above train max 6.21, inside the 10 % margin
    _e, _w, state, cat, _p, reasons = _risk(demo, _rec(v))
    assert state == 1 and cat == -1 and reasons & 8


def test_warmup_warning_and_missing_sensor_never_get_a_category(demo):
    v = _inrange_per_class()[0][0]
    assert _risk(demo, _rec(v, warm=30.0))[2:4] == (1, -1)          # MQ135 warm-up -> UNCERTAIN
    assert _risk(demo, _rec(v, warm=float("nan")))[2:4] == (1, -1)  # warning (warm-up unknown) -> UNCERTAIN
    assert _risk(demo, _rec(v, has_ph=0))[2:4] == (2, -1)           # sensor missing -> UNAVAILABLE


def test_synthetic_fixture_path_unchanged(demo, v5):
    v = _inrange_per_class()[1][0]
    rec = _rec(v, origin=1, unit=2)
    assert _risk(demo, rec) == _risk(v5, rec) and _risk(v5, rec)[2] == 0


def _raw(fruit):
    head = [-128] * 5
    head[fruit] = 127
    return " ".join(map(str, head + [127, -128, -128, -128, -128] + [0] * 30))


def _oled(run, fruit, rec):
    out = run([f"O {_raw(fruit)} {_c_line(rec)[2:]} 0 0 0"])
    rows = out[0].split("|")[1:]
    assert len(rows) <= 8 and all(len(r) <= 21 for r in rows) and rows[-1] == "*proto, not lab test", rows
    assert not any(w in (out[0] + out[1]).lower() for w in FORBIDDEN), out
    return rows, out[1]


def test_oled_strings(demo):
    cls = _inrange_per_class()
    for k, (v, _p) in cls.items():
        rows, serial = _oled(demo, 1, _rec(v))
        assert f"Risk:{CATS[k]} proto" in rows and f"risk={CATS[k]},risk_st=PROTOTYPE" in serial
    rows, _ = _oled(demo, 1, _rec(BOARD))
    assert "Risk:OUT-RANGE" in rows and not any(c in " ".join(rows) for c in ("LOW", "MEDIUM", "HIGH"))
    assert "Risk:UNCERTAIN" in _oled(demo, 1, _rec(cls[0][0], warm=30.0))[0]
    assert "Risk:UNAVAILABLE" in _oled(demo, 1, _rec(cls[0][0], has_ph=0))[0]
    assert "Shelf:no data" in _oled(demo, 0, _rec(BOARD))[0]       # apple
    assert "Shelf:no data" in _oled(demo, 2, _rec(BOARD))[0]       # guava
    assert any(re.fullmatch(r"Shelf:\d+-\d+d \w+", r) for r in _oled(demo, 1, _rec(BOARD))[0])   # banana unchanged


def test_default_build_behaviour_unchanged(v5):
    rows, serial = _oled(v5, 1, _rec(_inrange_per_class()[2][0]))
    assert "Risk:UNCERTAIN" in rows and "risk=-,risk_st=UNCERTAIN" in serial
    assert "Shelf:N/A" in _oled(v5, 0, _rec(BOARD))[0]
    assert "Risk:UNCERTAIN" in _oled(v5, 1, _rec(BOARD))[0]


def test_pb14_alert_only_for_predicted_risk():
    src = (FW / "app/fv_app.c").read_text()
    assert "(c->risk.state == FV_STATE_PREDICTED && c->risk.category == 2)" in src
    assert "FV_STATE_PROTOTYPE" not in src                        # prototype HIGH cannot reach the alert expression
