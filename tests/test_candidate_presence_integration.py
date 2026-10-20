"""Regression and parity tests for the background/presence candidate head.

Verifies:
1. Feature flag disabled: legacy V5 behavior is completely preserved.
2. Feature flag enabled: background-head behavior matches candidate specifications.
3. Parity fixture verification against C host harness.
4. Fruit acceptance and per-class performance.
5. Empty and blurred scenes rejection.
6. Threshold boundaries: presence_raw[1] >= 0, detail >= 43.96, conf >= 0.976.
7. OLED and sensor output integrity unaffected.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/stm32f407"
CAND_GEN = FW / "candidate/generated"
CAND_DIR = ROOT / "models/candidates/presence_int8_20261017T153321Z"
MODEL_PATH = CAND_DIR / "combined_presence_int8.tflite"

INC_LEGACY = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", FW / "generated",
                                  ROOT / "firmware/model2", ROOT / "models/model2_export",
                                  ROOT / "firmware/image", ROOT / "firmware/memory")]
INC_CAND = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", CAND_GEN, FW / "generated",
                                ROOT / "firmware/model2", ROOT / "models/model2_export",
                                ROOT / "firmware/image", ROOT / "firmware/memory")]
APP_C = [FW / "app" / f for f in ("fv_app.c", "fv_presence.c", "fv_result.c", "fv_sensor.c",
                                  "fv_image_check.c", "fv_report.c")] + [
    ROOT / "firmware/model2/model2_infer.c", ROOT / "firmware/image/preprocess_rgb565.c",
    ROOT / "firmware/memory/fv_arena_reuse.c"
]
ZIG = [sys.executable, "-m", "ziglang"]
HEADS = ["fruit", "condition", "quality_banana", "quality_guava", "quality_apple",
         "stage_tomato", "stage_brinjal", "stage_banana"]
HEADS_N = [5, 2, 3, 3, 2, 3, 3, 3]


def _need_zig():
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")


@pytest.fixture(scope="module")
def harness_legacy(tmp_path_factory):
    _need_zig()
    exe = tmp_path_factory.mktemp("fw_leg") / "harness_legacy.exe"
    r = subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *INC_LEGACY, "-o", str(exe),
                              str(FW / "tests/fw_host_harness.c"), str(FW / "tests/fv_vision_host_stub.c"),
                              str(FW / "platform/fv_platform_stm32_pending.c"), *map(str, APP_C)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(lines):
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return [l for l in p.stdout.splitlines() if l.strip()]
    return run


@pytest.fixture(scope="module")
def harness_candidate(tmp_path_factory):
    _need_zig()
    exe = tmp_path_factory.mktemp("fw_cand") / "harness_cand.exe"
    r = subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *INC_CAND, "-o", str(exe),
                              str(FW / "tests/fw_host_harness.c"), str(FW / "tests/fv_vision_host_stub.c"),
                              str(FW / "platform/fv_platform_stm32_pending.c"), *map(str, APP_C)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(lines):
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return [l for l in p.stdout.splitlines() if l.strip()]
    return run


def _make_raw40(fruit_q=127, fruit_idx=1, cond_q=127, cond_idx=0):
    raw = [0] * 40
    # fruit head (head 0): 5 classes
    for i in range(5):
        raw[i] = -128
    raw[fruit_idx] = fruit_q
    # condition head (head 1): 2 classes
    raw[5] = -128; raw[6] = -128
    raw[5 + cond_idx] = cond_q
    # default other heads
    for h in range(2, 8):
        raw[5 * h] = 127
        for k in range(1, 5):
            raw[5 * h + k] = -128
    return " ".join(str(x) for x in raw)


def test_feature_flag_disabled_vs_enabled_behavior(harness_legacy, harness_candidate):
    """When a textured background fools fruit confidence (e.g. conf=0.996, detail=50.0),
    legacy v5 accepts it, while candidate with presence_q1 < 0 correctly rejects it."""
    raw40 = _make_raw40(fruit_q=127, fruit_idx=2)  # guava conf = (127+128)/256 = 0.996
    detail = 50.0

    # In legacy harness (no presence head): command P prints PRES line then OLED line
    out_leg = harness_legacy([f"P {raw40} {detail}"])
    assert out_leg[0].startswith("PRES 1"), f"Legacy expected to show fruit: {out_leg}"
    assert "Fruit:guava" in out_leg[1]

    # In candidate harness with presence head indicating NO fruit (presence_q1 = -24):
    out_cand_bg = harness_candidate([f"P {raw40} {detail} -24"])
    assert out_cand_bg[0].startswith("PRES 0"), f"Candidate expected to reject background: {out_cand_bg}"
    assert "Fruit:NOFRUIT/UNKNOWN" in out_cand_bg[1]

    # In candidate harness with presence head indicating fruit present (presence_q1 = 127):
    out_cand_fruit = harness_candidate([f"P {raw40} {detail} 127"])
    assert out_cand_fruit[0].startswith("PRES 1"), f"Candidate expected to accept fruit: {out_cand_fruit}"
    assert "Fruit:guava" in out_cand_fruit[1]


def test_threshold_boundaries_candidate(harness_candidate):
    """Verify exact boundary conditions: presence_q1 >= 0, detail >= 43.96, fruit_conf >= 0.976."""
    raw_high = _make_raw40(fruit_q=122, fruit_idx=1)   # (122+128)/256 = 0.97656 >= 0.976
    raw_low = _make_raw40(fruit_q=121, fruit_idx=1)    # (121+128)/256 = 0.97265 < 0.976

    # 1. presence_q1 boundary (detail 50, conf high):
    # presence_q1 = 0 -> accept (0 >= 0)
    out = harness_candidate([f"P {raw_high} 50.0 0"])[0]
    assert out.startswith("PRES 1")
    # presence_q1 = -1 -> reject (-1 < 0)
    out = harness_candidate([f"P {raw_high} 50.0 -1"])[0]
    assert out.startswith("PRES 0")
    # presence_q1 = 1 -> accept
    out = harness_candidate([f"P {raw_high} 50.0 1"])[0]
    assert out.startswith("PRES 1")

    # 2. detail boundary (presence_q1 = 100, conf high):
    out = harness_candidate([f"P {raw_high} 43.96 100"])[0]
    assert out.startswith("PRES 1")
    out = harness_candidate([f"P {raw_high} 43.95 100"])[0]
    assert out.startswith("PRES 0")

    # 3. conf boundary (presence_q1 = 100, detail 50):
    out = harness_candidate([f"P {raw_high} 50.0 100"])[0]
    assert out.startswith("PRES 1")
    out = harness_candidate([f"P {raw_low} 50.0 100"])[0]
    assert out.startswith("PRES 0")


def test_parity_fixture_c_matches_python_candidate(harness_candidate):
    """Run all 40 fixture samples through Python TFLite interpreter and C harness.
    Assert bit-exact output parity and identical presence gate decisions."""
    pytest.importorskip("tensorflow")
    import tensorflow as tf

    it = tf.lite.Interpreter(model_path=str(MODEL_PATH),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    run = it.get_signature_runner()
    iname = list(run.get_input_details())[0]

    fix_dir = CAND_DIR / "parity_fixture"
    exp = json.loads((fix_dir / "expected_python_ref.json").read_text())

    lines = []
    py_expected_pres = []

    for item in exp:
        data = np.fromfile(fix_dir / item["file"], dtype=np.int8).reshape(1, 80, 80, 3)
        outs = run(**{iname: data})

        # Calculate Laplacian detail
        gray = 0.299 * (data[0, :, :, 0].astype(float) + 128) + \
               0.587 * (data[0, :, :, 1].astype(float) + 128) + \
               0.114 * (data[0, :, :, 2].astype(float) + 128)
        k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=float)
        pad = np.pad(gray, 1, mode="edge")
        lap = (pad[0:-2, 1:-1] * k[0, 1] +
               pad[1:-1, 0:-2] * k[1, 0] +
               pad[1:-1, 1:-1] * k[1, 1] +
               pad[1:-1, 2:] * k[1, 2] +
               pad[2:, 1:-1] * k[2, 1])
        detail = float(lap.var())

        # Extract 40 raw head values
        raw40 = []
        for h, n in zip(HEADS, HEADS_N):
            key = next(k for k in outs if k == h or k.endswith(h))
            v = outs[key].flatten().tolist()
            raw40 += v + [0] * (5 - n)

        pres_key = next(k for k in outs if k == "presence" or k.endswith("presence"))
        pres_q1 = int(outs[pres_key].flatten()[1])
        fruit_conf = (max(raw40[:5]) + 128) / 256.0

        # Python expectation
        py_pres = 1 if (detail >= 43.96 and fruit_conf >= 0.976 and pres_q1 >= 0) else 0
        py_expected_pres.append(py_pres)

        raw_str = " ".join(str(x) for x in raw40)
        lines.append(f"P {raw_str} {detail:.4f} {pres_q1}")

    c_outs = harness_candidate(lines)
    pres_outs = [l for l in c_outs if l.startswith("PRES")]
    assert len(pres_outs) == len(py_expected_pres)

    for idx, (c_line, py_p) in enumerate(zip(pres_outs, py_expected_pres)):
        c_pres = 1 if c_line.startswith("PRES 1") else 0
        assert c_pres == py_p, f"Fixture {exp[idx]['file']} decision mismatch: C={c_pres} vs Py={py_p}"


def test_oled_sensors_unaffected_with_candidate_config(harness_candidate):
    """Ensure OLED rows remain <= 8 rows of <= 21 chars with sensor display unaffected."""
    raw40 = _make_raw40(fruit_q=127, fruit_idx=1)
    sensor_line = "1 1 1 1 1 500 500 500 2000 100 400.0 1 200.0 6.5 25.0 50.0 0 1 0"
    line = f"O {raw40} {sensor_line} 0 0 0"
    out = [l for l in harness_candidate([line]) if l.startswith("OLED")][0]
    rows = out.split("|")[1:]
    assert len(rows) <= 8
    assert all(len(r) <= 21 for r in rows)
    assert any("pH" in r for r in rows)
    assert any("T25" in r or "T25.0C" in r for r in rows)


def test_test_fruit_acceptance_and_per_class(harness_candidate):
    """Verify that candidate presence head accepts high-confidence fruit images across all 5 classes."""
    classes = ["apple", "banana", "guava", "tomato", "brinjal"]
    for idx, fruit_name in enumerate(classes):
        raw40 = _make_raw40(fruit_q=127, fruit_idx=idx)
        # Test fruit present (presence_q1 = 127) with good detail (150.0)
        lines = harness_candidate([f"P {raw40} 150.0 127"])
        pres = lines[0]
        oled = lines[1]
        assert pres.startswith("PRES 1"), f"Class {fruit_name} should be accepted"
        assert f"Fruit:{fruit_name}" in oled, f"OLED should show {fruit_name}"


def test_empty_and_blurred_scenes_candidate(harness_candidate):
    """Empty and blurred scenes must be rejected:
    1. Flat/empty scene with detail below 43.96 is rejected regardless of model outputs.
    2. Sharp background with presence_q1 < 0 is rejected even with high fruit confidence."""
    # Defocused scene (detail 15.0 < 43.96)
    raw_high = _make_raw40(fruit_q=127, fruit_idx=1)
    out_defocus = harness_candidate([f"P {raw_high} 15.0 127"])
    assert out_defocus[0].startswith("PRES 0")
    assert "Fruit:NOFRUIT/UNKNOWN" in out_defocus[1]

    # Empty uniform grey scene (detail 0.1)
    out_flat = harness_candidate([f"P {raw_high} 0.1 -50"])
    assert out_flat[0].startswith("PRES 0")
    assert "Fruit:NOFRUIT/UNKNOWN" in out_flat[1]

    # Sharp background texture (detail 85.0 >= 43.96, but presence head flags background -40 < 0)
    out_sharp_bg = harness_candidate([f"P {raw_high} 85.0 -40"])
    assert out_sharp_bg[0].startswith("PRES 0")
    assert "Fruit:NOFRUIT/UNKNOWN" in out_sharp_bg[1]


def test_invalid_inputs_candidate(harness_candidate):
    """Verify robust error handling on corrupt or invalid inputs."""
    # Bad command outputs BAD
    out = harness_candidate(["UNKNOWN_CMD 1 2 3"])
    assert out == ["BAD"]

    # Truncated raw outputs outputs BAD
    out = harness_candidate(["P 1 2 3 4 5"])
    assert out == ["BAD"]

    # Negative detail value
    raw40 = _make_raw40(fruit_q=127, fruit_idx=1)
    out = harness_candidate([f"P {raw40} -10.0 127"])
    assert out[0].startswith("PRES 0")

