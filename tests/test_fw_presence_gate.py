"""Fruit-presence gate (firmware/stm32f407/app/fv_presence.{h,c}): host tests with real SWD camera frames, synthetic
empty/dark/blurred scenes and public fruit images in the device camera format. The frozen model is unchanged; the gate
only decides whether a fruit may be SHOWN. There are no real photos of non-fruit objects in this project."""

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/stm32f407"
sys.path.insert(0, str(ROOT / "tools/firmware"))
import calibrate_presence_gate as cg  # noqa: E402
import image_quality as iq  # noqa: E402
from fruitvision.camera_preprocess import rgb565_to_input_int8  # noqa: E402

CFG = json.loads((ROOT / "configs/presence_gate.json").read_text())
MIN_DETAIL = CFG["min_detail_laplacian_var"]
R1 = CFG["fruit_confidence_threshold"]
HEADS_N = [5, 2, 3, 3, 2, 3, 3, 3]
HEADS = ["fruit", "condition", "quality_banana", "quality_guava", "quality_apple", "stage_tomato", "stage_brinjal", "stage_banana"]


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")
    exe = tmp_path_factory.mktemp("pg") / "h.exe"
    inc = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", FW / "generated", ROOT / "firmware/model2",
                               ROOT / "models/model2_export", ROOT / "firmware/image", ROOT / "firmware/memory")]
    srcs = [FW / "tests/fw_host_harness.c", FW / "tests/fv_vision_host_stub.c", FW / "platform/fv_platform_stm32_pending.c"] + \
        [FW / "app" / f for f in ("fv_app.c", "fv_presence.c", "fv_result.c", "fv_sensor.c", "fv_image_check.c", "fv_report.c")] + \
        [ROOT / "firmware/model2/model2_infer.c", ROOT / "firmware/image/preprocess_rgb565.c", ROOT / "firmware/memory/fv_arena_reuse.c"]
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *inc, "-o", str(exe),
                        *map(str, srcs)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(lines):
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr
        return [l for l in p.stdout.splitlines() if l.strip()]
    return run


@pytest.fixture(scope="module")
def model():
    pytest.importorskip("tensorflow")
    import tensorflow as tf
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    run = it.get_signature_runner()
    iname = list(run.get_input_details())[0]

    def raw40(x):
        o = run(**{iname: x.reshape(1, 80, 80, 3)})
        key = {h: next(k for k in o if k == h or k.endswith(h)) for h in HEADS}
        flat = []
        for h, n in zip(HEADS, HEADS_N):
            v = [int(a) for a in o[key[h]].reshape(-1)]
            assert len(v) == n
            flat += v + [0] * (5 - n)
        conf = (max(flat[:5]) + 128) / 256
        return flat, conf
    return raw40


def _frames():
    """(name, kind, 80x80 int8 input, expected_fruit_or_None). kind: real_empty | real_fruit | synthetic_empty | public | degraded."""
    out = []
    for d, kind, fr in (("20261017T092139Z", "real_empty", None), ("20261017T092315Z", "real_fruit", "apple"),
                        ("20261017T094631Z", "real_fruit", "apple")):
        fb = (ROOT / "reports/firmware/live_capture" / d / "frame_a.bin").read_bytes()[:38400]
        out.append((d, kind, rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True), fr))
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:120, 0:160]
    synth = {"uniform_grey": np.full((120, 160, 3), 128, np.uint8), "black": np.zeros((120, 160, 3), np.uint8),
             "dark_noise": rng.integers(0, 12, (120, 160, 3)).astype(np.uint8),
             "gradient": np.stack([xx * 1.5, yy * 2.0, xx + yy], -1).clip(0, 255).astype(np.uint8),
             "blurred_wall": np.asarray(Image.fromarray(rng.uniform(80, 200, (120, 160, 3)).astype(np.uint8)).filter(ImageFilter.GaussianBlur(8)))}
    for k, img in synth.items():
        out.append((k, "synthetic_empty", cg.model_input(img), None))
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    te = te[[(ROOT / "data/raw" / p).exists() for p in te.path]].reset_index(drop=True)
    if len(te) == 0:
        return out
    for i in np.linspace(0, len(te) - 1, 60).astype(int):
        with Image.open(ROOT / "data/raw" / te.path[i]) as im:
            base = cg.frame_160x120(im.convert("RGB"))
        out.append((f"public_{i}", "public", cg.model_input(base), te.fruit[i]))
        if i % 3 == 0:
            blur = np.asarray(Image.fromarray(base).filter(ImageFilter.GaussianBlur(4)), np.uint8)
            out.append((f"blur4_{i}", "degraded", cg.model_input(blur), te.fruit[i]))
            dark = np.asarray(ImageEnhance.Brightness(Image.fromarray(base)).enhance(0.05), np.uint8)
            out.append((f"dark5pct_{i}", "degraded", cg.model_input(dark), te.fruit[i]))
    return out


@pytest.fixture(scope="module")
def evaluated(harness, model):
    frames = _frames()
    lines_i = ["I " + x.astype(np.int8).tobytes().hex() for _, _, x, _ in frames]
    c_detail = [float(l.split()[6]) for l in harness(lines_i)]
    rows, plines = [], []
    for (name, kind, x, fr), det in zip(frames, c_detail):
        flat, conf = model(x)
        rows.append({"name": name, "kind": kind, "fruit": fr, "conf": conf, "c_detail": det,
                     "py_detail": iq.laplacian_var(iq.luminance(x.astype(np.float64) + 128.0)), "flat": flat})
        plines.append("P " + " ".join(map(str, flat)) + f" {det:.6f}")
    out = harness(plines)
    for r, a, b in zip(rows, out[0::2], out[1::2]):
        r["shown"] = int(a.split()[1])
        r["fruit_state"] = int(a.split()[2])
        r["oled"] = b.split("|")[1:]
    return rows


def test_detail_c_matches_python(evaluated):
    for r in evaluated:
        assert abs(r["c_detail"] - r["py_detail"]) <= 1e-3 * max(1.0, r["py_detail"]), r["name"]


def test_empty_and_featureless_scenes_never_show_a_fruit(evaluated):
    empty = [r for r in evaluated if r["kind"] in ("real_empty", "synthetic_empty")]
    assert len(empty) == 6
    for r in empty:
        assert r["shown"] == 0 and r["fruit_state"] == 1, r["name"]
        assert r["oled"][:4] == ["Fruit:NOFRUIT/UNKNOWN", "Cond:UNCERTAIN", "Grade:UNCERTAIN", "Shelf:UNCERTAIN"]
    # softmax alone is NOT enough: at least one empty scene is above the 0.976 confidence threshold
    assert any(r["conf"] >= R1 for r in empty)


def test_gate_decision_equals_documented_rule(evaluated):
    for r in evaluated:
        assert r["shown"] == int(r["c_detail"] >= MIN_DETAIL and r["conf"] >= R1), r["name"]


def test_valid_fruit_frames_are_shown_and_mostly_correct(evaluated):
    pub = [r for r in evaluated if r["kind"] == "public"]
    if not pub:
        pytest.skip("public images not available")
    shown = [r for r in pub if r["shown"]]
    assert all(r["c_detail"] >= MIN_DETAIL for r in pub)                  # clean fruit images are never rejected for detail
    assert len(shown) >= 0.3 * len(pub)                                      # the gate does not reject everything
    correct = sum(["apple", "banana", "guava", "tomato", "brinjal"][int(np.argmax(r["flat"][:5]))] == r["fruit"] for r in shown)
    assert correct / len(shown) >= 0.85
    for r in shown:
        assert r["oled"][0].startswith("Fruit:") and "NOFRUIT" not in r["oled"][0]


def test_blurred_and_very_dark_frames_mostly_rejected(evaluated):
    deg = [r for r in evaluated if r["kind"] == "degraded"]
    if not deg:
        pytest.skip("public images not available")
    assert sum(r["shown"] for r in deg) / len(deg) <= 0.2


def test_real_camera_frames_documented_behaviour(evaluated):
    real = {r["name"]: r for r in evaluated if r["kind"].startswith("real")}
    assert real["20261017T092139Z"]["shown"] == 0           # no fruit in view -> NO FRUIT/UNKNOWN
    # known false rejection: the refocused apple has enough detail but confidence 0.852 < 0.976
    a = real["20261017T094631Z"]
    assert a["c_detail"] >= MIN_DETAIL and a["conf"] < R1 and a["shown"] == 0


def test_oled_rows_fit(evaluated):
    for r in evaluated:
        assert len(r["oled"]) <= 8 and all(len(x) <= 21 for x in r["oled"])


def test_header_matches_config_and_evaluation():
    h = (FW / "app/fv_presence.h").read_text()
    assert re.search(r"#define FV_PRESENCE_MIN_DETAIL ([0-9.]+)f", h).group(1) == f"{MIN_DETAIL:.2f}"
    assert R1 == 0.976
    ev = json.loads((ROOT / "reports/firmware/presence_gate_eval.json").read_text())
    assert ev["rule"]["min_detail"] == MIN_DETAIL and not any(s["fruit_shown"] for s in ev["synthetic_empty_scenes"])
    assert "no real photos of non-fruit objects" in ev["missing_evidence"]


# --------------------------------------------------------------------------- diagnostic capture build (fv_app_v6_diag)
def test_diag_capture_compiles_for_cortex_m4f(tmp_path):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")
    inc = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", FW / "generated", ROOT / "firmware/model2",
                               ROOT / "models/model2_export", ROOT / "firmware/image", ROOT / "firmware/memory")]
    for flags in ([], ["-DFV_DIAG_CAPTURE"]):
        r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4",
                            "-mfloat-abi=hard", "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion", *flags, *inc,
                            "-c", str(FW / "app/fv_app.c"), "-o", str(tmp_path / "a.o")], capture_output=True, text=True)
        assert r.returncode == 0, (flags, r.stderr)


def test_capture_reader_bit_exact_and_torn_read_detection(tmp_path, model):
    pytest.importorskip("elftools")
    import struct as st
    import read_capture as rc
    import read_selftest as rs
    elf = ROOT / "reports/firmware/gcc/fv_app_v6_diag.elf"
    if not elf.exists():
        pytest.skip("diagnostic build not present")
    addr, size = rs.symbol(elf, "g_fv_capture")
    assert size == rc.SIZE == 19264 and 0x20000000 <= addr < 0x20020000
    fb = (ROOT / "reports/firmware/live_capture/20261017T094631Z/frame_a.bin").read_bytes()[:38400]
    x = rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True)
    flat, _ = model(x)

    def dump(seq, raw):
        b = bytearray(size)
        st.pack_into("<IIIiIi", b, 0, rc.MAGIC, seq, 1234, 841, 4096, 0)
        st.pack_into("<40b", b, 24, *raw)
        b[64:] = x.astype(np.int8).tobytes()
        w = st.unpack(f"<{size // 4}I", bytes(b))
        return "\n".join(f"0x{addr + 16 * i:08X} : " + " ".join(f"{v:08X}" for v in w[4 * i:4 * i + 4]) for i in range((len(w) + 3) // 4))
    a, b2 = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(dump(6, flat)); b2.write_text(dump(6, flat))
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/read_capture.py"), "--elf", str(elf), "--dump", str(a), str(b2)], capture_output=True, text=True, timeout=300)
    out = r.stdout[r.stdout.index("{"):]
    rep = json.loads(out)
    assert r.returncode == 0 and rep["stable_complete_read"] and rep["python_equals_device_bit_exact"] and rep["device_fruit"] == "apple"
    b2.write_text(dump(7, flat))                       # odd seq / changed -> torn read must be rejected
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/read_capture.py"), "--elf", str(elf), "--dump", str(a), str(b2)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 1 and json.loads(r.stdout[r.stdout.index("{"):])["stable_complete_read"] is False
