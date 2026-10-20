"""Host tests for the STM32F407 firmware application modules (firmware/stm32f407/).

Everything here runs on the PC (zig/clang). Nothing in this file is evidence of an STM32 build or
of hardware behaviour. C outputs are compared against the Python reference implementations:
  fv_result      <-> fruitvision.postprocess.postprocess          (Model 1 + Model 3 outputs)
  fv_sensor      <-> SmartPesticideSystem._risk / validate_sensors (Model 2 applicability)
  fv_image_check <-> fruitvision.validation.image_checks           (content stats + dimensions)
"""

import json
import math
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
FW = ROOT / "firmware/stm32f407"
INC = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", FW / "generated", ROOT / "firmware/model2",
                          ROOT / "models/model2_export", ROOT / "firmware/image", ROOT / "firmware/memory")]
APP_C = [FW / "app" / f for f in ("fv_app.c", "fv_presence.c", "fv_result.c", "fv_sensor.c", "fv_image_check.c", "fv_report.c")] + [
    ROOT / "firmware/model2/model2_infer.c", ROOT / "firmware/image/preprocess_rgb565.c",
    ROOT / "firmware/memory/fv_arena_reuse.c"]
ZIG = [sys.executable, "-m", "ziglang"]
HEADS = ["fruit", "condition", "quality_banana", "quality_guava", "quality_apple", "stage_tomato", "stage_brinjal",
         "stage_banana"]
NCL = [5, 2, 3, 3, 2, 3, 3, 3]
FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]


def _need_zig():
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    _need_zig()
    exe = tmp_path_factory.mktemp("fw") / "fw_host_harness.exe"
    r = subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *INC, "-o", str(exe),
                              str(FW / "tests/fw_host_harness.c"), str(FW / "tests/fv_vision_host_stub.c"),
                              str(FW / "platform/fv_platform_stm32_pending.c"), *map(str, APP_C)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(lines):
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return p.stdout.splitlines()
    return run


# --------------------------------------------------------------------------- error handling
def test_error_handling_and_pending_platform(harness):
    out = harness(["E"])
    assert out[-1] == "END"
    fails = [l for l in out if not l.startswith("PASS") and l != "END"]
    assert not fails, fails
    assert len(out) >= 20


# --------------------------------------------------------------------------- Model 1 + 3 outputs
def _q_from_probs(p):
    q = np.clip(np.round(np.asarray(p) * 256) - 128, -128, 127).astype(int)
    return q


def _cases(n=400, seed=0):
    rng = np.random.default_rng(seed)
    cases = []
    for i in range(n):
        heads = []
        for h, k in enumerate(NCL):
            if h == 0 and i % 3 == 0:          # confident fruit (exercise routed branch)
                p = np.full(k, 0.002); p[rng.integers(k)] = 1 - 0.002 * (k - 1)
                p = p + rng.uniform(0, 0.03, k) * (rng.random() < 0.5)
                p = p / p.sum()
            else:
                p = rng.dirichlet(np.full(k, rng.choice([0.2, 1.0, 5.0])))
            heads.append(_q_from_probs(p))
        cases.append(heads)
    # edge cases: argmax ties, exact threshold neighbourhood, all -128
    tie = [np.full(k, -128) for k in NCL]
    tie[0][:] = 127; tie[1][:] = 0; tie[2][:] = 10; tie[7][:] = 10
    cases.append(tie)
    for qf in (121, 122, 123):                # (q+128)/256 = 0.9726.., 0.9765.., 0.9804..  vs threshold 0.976
        c = [np.full(k, -128) for k in NCL]
        c[0][1] = qf; c[1][1] = 100; c[2][2] = 100; c[7][0] = 100
        cases.append(c)
    cases.append([np.full(k, -128) for k in NCL])
    return cases


def _py_post(heads_q):
    from fruitvision.postprocess import postprocess
    cfg = json.loads((ROOT / "configs/model3_postprocess.json").read_text())
    shelf = json.loads((ROOT / "models/model3/shelf_life_ranges.json").read_text())
    labels = json.loads((ROOT / "models/model3/labels.json").read_text())
    deq = [(np.asarray(q, float) + 128) / 256 for q in heads_q]
    raw = {"fruit": dict(zip(FRUITS, deq[0])), "condition": dict(zip(["fresh", "spoiled"], deq[1])),
           "heads": {h: {labels[h][str(i)]: float(v) for i, v in enumerate(deq[j + 2])} for j, h in enumerate(HEADS[2:])}}
    return postprocess(raw, cfg, shelf)


def test_result_parity_with_python_postprocess(harness):
    cases = _cases()
    lines = []
    for heads in cases:
        flat = []
        for q in heads:
            flat += list(q) + [0] * (5 - len(q))
        lines.append("R " + " ".join(map(str, flat)))
    out = harness(lines)
    assert len(out) == len(cases)
    st = {"predicted": 0, "uncertain": 1, "unavailable": 2}
    gmap = {"Good": 0, "Average": 1, "Poor": 2}
    smap = {"Fresh": 0, "Semi-fresh": 1, "Rotten": 2}
    n_routed = 0
    for heads, line in zip(cases, out):
        v = line.split()
        fs, fr, fc, cs, co, cc, qs, gr, gc, gb, qh, ss, sg, sc, lo, hi, sh, cons = v
        pp = _py_post(heads)
        assert FRUITS[int(fr)] == pp["fruit"]["label"]
        assert math.isclose(float(fc), pp["fruit"]["confidence"], abs_tol=6e-5)
        assert ["fresh", "spoiled"][int(co)] == pp["condition"]["label"]
        assert int(qs) == st[pp["quality_grade"]["state"]]
        assert int(ss) == st[pp["shelf_life"]["state"]]
        rules = {w["rule"] + ":" + w["severity"] for w in pp["consistency"]["warnings"]}
        cons = int(cons)
        assert bool(cons & 1) == ("R1_low_fruit_confidence:uncertain" in rules)
        assert bool(cons & 2) == ("R2_grade_vs_stage:minor_mismatch" in rules)
        assert bool(cons & 4) == ("R2_grade_vs_stage:contradiction" in rules)
        assert bool(cons & 8) == ("R3_condition_vs_grade:contradiction" in rules)
        if pp["quality_grade"]["state"] == "predicted":
            n_routed += 1
            assert int(gr) == gmap[pp["quality_grade"]["label"]]
            assert math.isclose(float(gc), pp["quality_grade"]["confidence"], abs_tol=6e-5)
            assert HEADS[int(qh)] == pp["raw"]["routed_quality_head"]
            assert int(gb) == (pp["fruit"]["label"] == "apple")
        if pp["shelf_life"]["state"] == "predicted":
            assert int(sg) == smap[pp["shelf_life"]["stage"]]
            assert [int(lo), int(hi)] == list(pp["shelf_life"]["range_days"])
            assert HEADS[int(sh)] == pp["raw"]["routed_stage_head"]
        else:
            assert (int(lo), int(hi)) == (-1, -1)
    assert n_routed > 50   # the routed (R1-passed) branch is really exercised


# --------------------------------------------------------------------------- sensors / Model 2
RAW_KEYS = ["tcs_r", "tcs_g", "tcs_b", "tcs_c", "mq135", "ph", "temp_c", "humidity_pct"]


def _f32(x):
    return float(np.float32(x))


def _sensor_cases(seed=1):
    spec = json.loads((ROOT / "models/model2_export/model2_logreg.json").read_text())
    rg = spec["synthetic_training_ranges_trainval"]
    rng = np.random.default_rng(seed)

    def inside(k):
        r = rg["sensor_" + k]
        return r["min"] + (0.1 + 0.8 * rng.random()) * (r["max"] - r["min"])

    def base():
        return dict(has_tcs=1, has_mq=1, has_ph=1, has_temp=1, has_rh=1,
                    r=int(inside("tcs_r")), g=int(inside("tcs_g")), b=int(inside("tcs_b")), c=int(inside("tcs_c")),
                    atime=-1, mq=_f32(inside("mq135")), unit=2, warm=600.0, ph=_f32(inside("ph")),
                    t=_f32(inside("temp_c")), rh=_f32(inside("humidity_pct")), origin=1, calib=0, null=0)
    cases = [base() for _ in range(60)]                          # valid synthetic fixtures -> predicted
    mods = [dict(origin=0), dict(unit=1, mq=2000.0, origin=0), dict(unit=1, mq=4095.0), dict(unit=1, mq=0.0),
            dict(unit=0), dict(mq=-5.0), dict(mq=float("nan")), dict(has_mq=0), dict(warm=60.0),
            dict(warm=float("nan")), dict(ph=0.0), dict(ph=14.5), dict(ph=float("nan")), dict(has_ph=0),
            dict(t=-45.0), dict(t=float("nan")), dict(has_temp=0), dict(rh=101.0), dict(rh=float("nan")),
            dict(has_rh=0), dict(has_temp=0, has_rh=0), dict(has_tcs=0), dict(r=0, g=0, b=0, c=0),
            dict(r=-1), dict(c=65535), dict(atime=255, c=1500), dict(atime=246, r=500, c=1200),
            dict(c=100, r=500), dict(r=5000, c=9000), dict(ph=10.0), dict(t=60.0), dict(origin=0, calib=1),
            dict(origin=0, calib=1, unit=1, mq=1000.0), dict(null=1)]
    for m in mods:
        c = base(); c.update(m); cases.append(c)
    return cases


def _c_line(c):
    return "S " + " ".join(str(c[k]) for k in ("has_tcs", "has_mq", "has_ph", "has_temp", "has_rh", "r", "g", "b", "c",
                                                "atime", "mq", "unit", "warm", "ph", "t", "rh", "origin", "calib",
                                                "null"))


def _py_record(c):
    if c["null"]:
        return None
    rec = {}
    if c["has_tcs"]:
        rec["tcs34725"] = {"r": c["r"], "g": c["g"], "b": c["b"], "c": c["c"]}
        if c["atime"] >= 0:
            rec["tcs34725"]["atime"] = c["atime"]
    if c["has_mq"]:
        rec["mq135"] = {"value": c["mq"], "unit": {0: None, 1: "adc_counts_12bit", 2: "synthetic_scale"}[c["unit"]]}
        if not math.isnan(c["warm"]):
            rec["mq135"]["warmup_s"] = c["warm"]
    if c["has_ph"]:
        rec["ph"] = {"value": c["ph"]}
    if c["has_temp"] or c["has_rh"]:
        rec["dht22"] = {}
        if c["has_temp"]:
            rec["dht22"]["temperature_c"] = c["t"]
        if c["has_rh"]:
            rec["dht22"]["humidity_pct"] = c["rh"]
    rec["meta"] = {"data_origin": "synthetic_fixture" if c["origin"] else "device",
                   "calibration_profile": "profile-x" if c["calib"] else None}
    return rec


def _py_err_bits(errors):
    b = 0
    for e in errors:
        if e.startswith("TCS34725") and "missing" in e: b |= 1 << 0
        elif "non-negative" in e: b |= 1 << 1
        elif "all channels 0" in e: b |= 1 << 2
        elif e.startswith("TCS34725") and "saturated" in e: b |= 1 << 3
        elif e.startswith("MQ135: missing"): b |= 1 << 4
        elif e.startswith("MQ135: non-finite"): b |= 1 << 5
        elif e.startswith("MQ135: unit"): b |= 1 << 6
        elif "ADC at rail" in e: b |= 1 << 7
        elif e.startswith("MQ135: value must be > 0"): b |= 1 << 8
        elif e.startswith("pH: missing"): b |= 1 << 9
        elif e.startswith("pH: non-finite"): b |= 1 << 10
        elif e.startswith("pH:"): b |= 1 << 11
        elif e.startswith("DHT22 temperature: missing"): b |= 1 << 12
        elif e.startswith("DHT22 temperature: non-finite"): b |= 1 << 13
        elif e.startswith("DHT22 temperature"): b |= 1 << 14
        elif e.startswith("DHT22 humidity: missing"): b |= 1 << 15
        elif e.startswith("DHT22 humidity: non-finite"): b |= 1 << 16
        elif e.startswith("DHT22 humidity"): b |= 1 << 17
        elif e == "no sensor record supplied": b |= 0x9211   # all MISSING bits (C: NULL record)
        else: raise AssertionError(f"unmapped Python error: {e}")
    return b


def test_sensor_and_risk_parity_with_python(harness):
    from fruitvision.sensor.risk_model import Model2
    from fruitvision.system import SmartPesticideSystem
    m2 = Model2(ROOT / "models/model2_export/model2_logreg.json")
    fake = types.SimpleNamespace(m2=m2, m2_ranges=m2.spec["synthetic_training_ranges_trainval"])
    cases = _sensor_cases()
    out = harness([_c_line(c) for c in cases])
    assert len(out) == len(cases)
    st = {"predicted": 0, "uncertain": 1, "unavailable": 2}
    seen = set()
    for c, line in zip(cases, out):
        err, warn, ood, _vm, state, cat, p0, p1, p2, reasons = line.split()
        v, risk = SmartPesticideSystem._risk(fake, _py_record(c))
        assert int(err) == _py_err_bits(v["errors"]), (c, v["errors"], err)
        wb = 0
        for w in v.get("warnings", []):
            wb |= 1 if "clear channel below" in w else 2 if "warm-up time unknown" in w else 4 if "only" in w else 0
        assert int(warn) == wb, (c, v.get("warnings"), warn)
        ob = 0
        for s in v.get("out_of_training_range", []):
            ob |= 1 << RAW_KEYS.index(s.split("=")[0])
        assert int(ood) == ob, (c, v.get("out_of_training_range"), ood)
        assert int(state) == st[risk["state"]], (c, risk)
        seen.add(risk["state"])
        rb = 0
        if risk["state"] == "uncertain":
            for r in risk["reasons"]:
                rb |= 4 if r.startswith("readings are not on") else 8 if "outside synthetic training range" in r else \
                    16 if r == "MQ135 not warmed up" else 0
            assert int(reasons) == rb, (c, risk["reasons"], reasons)
        if risk["state"] == "predicted":
            assert ["LOW", "MEDIUM", "HIGH"][int(cat)] == risk["category"]
            for k, pv in zip(["LOW", "MEDIUM", "HIGH"], (p0, p1, p2)):
                assert abs(float(pv) - risk["probabilities"][k]) < 2e-4
        else:
            assert int(cat) == -1 and float(p0) == float(p1) == float(p2) == 0.0   # never leaked
    assert seen == {"predicted", "uncertain", "unavailable"}


# --------------------------------------------------------------------------- image checks
def _images(seed=2):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:80, 0:80]
    ims = []
    for i in range(12):   # smooth coloured blobs (photo-like)
        cx, cy, rad = rng.uniform(20, 60), rng.uniform(20, 60), rng.uniform(10, 35)
        m = (((xx - cx) ** 2 + (yy - cy) ** 2) < rad ** 2)[..., None]
        bg, fg = rng.uniform(0, 255, 3), rng.uniform(0, 255, 3)
        im = np.where(m, fg, bg) + rng.normal(0, 3, (80, 80, 3)) + (xx[..., None] * rng.uniform(-1, 1))
        ims.append(np.clip(im, 0, 255))
    ims.append(np.full((80, 80, 3), 128.0))                                      # uniform -> reject
    ims.append(rng.uniform(0, 255, (80, 80, 3)))                                 # noise -> reject
    g = np.clip(yy * 3.0, 0, 255)[..., None].repeat(3, 2); ims.append(g)         # grayscale -> reject
    ims.append(np.clip(ims[0] * 0.2, 0, 255))                                    # dark
    ims.append(np.clip(ims[1] * 0.3 + 200, 0, 255))                              # bright
    c = ims[2].copy(); c[:50] = 255.0; ims.append(c)                             # clipped
    return [np.round(i).astype(np.int16) for i in ims]


def test_image_check_parity_with_python(harness):
    from fruitvision.validation.image_checks import content_stats
    cfg = json.loads((ROOT / "configs/image_checks.json").read_text())
    ims = _images()
    lines = ["I " + (im - 128).astype(np.int8).tobytes().hex() for im in ims]
    out = harness(lines)
    flags_seen = 0
    for im, line in zip(ims, out):
        v = line.split()
        f = int(v[0])
        s = content_stats(im.astype(np.float32))
        got = dict(zip(["lum_mean", "lum_std", "lag1_autocorr", "chroma_mean_abs", "clipped_fraction"], map(float, v[1:])))
        for k in got:
            assert math.isclose(got[k], s[k], rel_tol=1e-4, abs_tol=1e-4), (k, got[k], s[k])
        r, w = cfg["reject"], cfg["warn"]
        exp = (1 * (s["lum_std"] < r["lum_std_below"]) | 2 * (s["lag1_autocorr"] < r["lag1_autocorr_below"])
               | 4 * (s["chroma_mean_abs"] < r["chroma_below"]) | 256 * (s["lum_mean"] < w["lum_mean_below"])
               | 512 * (s["lum_mean"] > w["lum_mean_above"]) | 1024 * (s["clipped_fraction"] > w["clipped_fraction_above"]))
        assert f == exp, (f, exp, s)
        flags_seen |= f
    assert flags_seen & 0x7 == 0x7 and flags_seen & 0x700 == 0x700   # every reject + warn flag exercised


def test_frame_dimension_checks(harness):
    cfg = json.loads((ROOT / "configs/image_checks.json").read_text())["dimensions"]
    dims = [(96, 96), (96, 80), (88, 80), (160, 120), (31, 96), (32, 32), (79, 79), (80, 80), (0, 10)]
    out = harness([f"D {w} {h}" for w, h in dims])
    for (w, h), line in zip(dims, out):
        lo, hi = min(w, h), max(w, h)
        exp = 0
        if lo <= 0 or lo < cfg["reject_min_side"]:
            exp |= 1 << 3
        elif lo < cfg["warn_min_side"]:
            exp |= 1 << 11
        if lo > 0 and hi / lo > cfg["warn_aspect_ratio"]:
            exp |= 1 << 12
        assert int(line) == exp, (w, h, line)


# --------------------------------------------------------------------------- OLED / serial output
FORBIDDEN = ["ppm", "safe", "pesticide-free", "pesticide free", "compliant", "mrl", "detected", "certified", "residue"]


def test_report_output_structure(harness):
    good = _cases()[0]
    flat = " ".join(" ".join(map(str, list(q) + [0] * (5 - len(q)))) for q in good)
    sens = _sensor_cases()
    scen = [(flat, sens[0], 0, 0, 0), (flat, sens[0], 0x1, -7, 1), (flat, sens[-1], 0, -2, 1),
            (flat, sens[60], 0x1000, 0, 0), (flat, sens[0], 0x200, -5, 1)]
    lines = [f"O {f} {_c_line(s)[2:]} {fl} {stt} {un}" for f, s, fl, stt, un in scen]
    out = [l for l in harness(lines) if l.strip()]   # Windows text-mode stdout adds a blank line after CRLF
    assert len(out) == 2 * len(scen)
    for i in range(len(scen)):
        oled, serial = out[2 * i], out[2 * i + 1]
        parts = oled.split("|")
        n = int(parts[0].split()[1])
        rows = parts[1:]
        assert 1 <= n <= 8 and len(rows) == n
        assert all(len(r) <= 21 for r in rows), rows
        _, ln, text = serial.split(" ", 2)
        assert int(ln) > 0 and text.startswith("FV1,status=")
        assert int(ln) == len(text) + 2   # text excludes the CRLF terminator
        low = (oled + text).lower()
        assert not any(w in low for w in FORBIDDEN), low
        if scen[i][4]:   # image unavailable -> nothing reported as predicted
            assert "fruit=-," in text and "fruit_st=UNAVAILABLE" in text and "Fruit: UNAVAILABLE" in rows
    assert "Image REJECTED:retake" in out[2].split("|")


# --------------------------------------------------------------------------- generated config
def test_generated_config_has_no_drift(tmp_path):
    pytest.importorskip("tensorflow")
    tmp = tmp_path / "cfg.h"
    subprocess.run([sys.executable, str(ROOT / "tools/firmware/gen_firmware_config.py"), str(tmp)], check=True,
                   capture_output=True)
    assert tmp.read_text() == (FW / "generated/fv_generated_config.h").read_text(), \
        "fv_generated_config.h is stale: rerun tools/firmware/gen_firmware_config.py"


def test_generated_config_matches_tflite_model():
    tf = pytest.importorskip("tensorflow")
    import re
    h = (FW / "generated/fv_generated_config.h").read_text()
    idx = [int(x) for x in re.search(r"FV_HEAD_OUTPUT_INDEX\[\w*\]\s*=\s*\{([^}]*)\}", h).group(1).split(",")]
    ncl = [int(x) for x in re.search(r"FV_HEAD_N_CLASSES\[\w*\]\s*=\s*\{([^}]*)\}", h).group(1).split(",")]
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"))
    it.allocate_tensors()
    inp, outs = it.get_input_details()[0], it.get_output_details()
    assert list(inp["shape"]) == [1, 80, 80, 3] and inp["dtype"] == np.int8
    assert inp["quantization"] == (1.0, -128)
    assert sorted(idx) == list(range(len(outs))) and ncl == NCL
    for h_i, o_i in enumerate(idx):
        assert int(np.prod(outs[o_i]["shape"])) == ncl[h_i]
        assert outs[o_i]["dtype"] == np.int8 and outs[o_i]["quantization"] == (0.00390625, -128)
    # signature-name mapping (same source the generator uses)
    sig = it.get_signature_runner()
    names = list(sig.get_output_details())
    for h_i, head in enumerate(HEADS):
        nm = next(n for n in names if n == head or n.endswith(head))
        assert sig.get_output_details()[nm]["index"] == outs[idx[h_i]]["index"]
    assert f"FV_MODEL_BYTES {(ROOT / 'models/experimental/tflite/combined_int8.tflite').stat().st_size}u" in h


# --------------------------------------------------------------------------- target compile + linker
def test_firmware_compiles_for_cortex_m4f_werror(tmp_path):
    _need_zig()
    srcs = APP_C + [FW / "app/main.c", FW / "platform/fv_platform_stm32_pending.c", FW / "startup/fv_startup.c",
                    FW / "startup/fv_syscalls.c", FW / "vision/fv_debug_log.c"]
    for s in srcs:
        r = subprocess.run(ZIG + ["cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard",
                                  "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion", *INC, "-c",
                                  str(s), "-o", str(tmp_path / (s.name + ".o"))], capture_output=True, text=True)
        assert r.returncode == 0, (s, r.stderr)


def test_linker_script_placement_lld(tmp_path):
    """Link firmware (TFLM replaced by the host stub) with the real linker script and check placement.
    The full TFLM link is done in WSL by tools/firmware/build_fw_check.sh (see recorded evidence test)."""
    _need_zig()
    pytest.importorskip("elftools")
    model_c = tmp_path / "fv_model_data.c"
    subprocess.run([sys.executable, str(ROOT / "tools/firmware/gen_model_data.py"), str(model_c)], check=True)
    objs = []
    srcs = APP_C + [FW / "app/main.c", FW / "platform/fv_platform_stm32_pending.c", FW / "startup/fv_startup.c",
                    FW / "tests/fv_vision_host_stub.c", FW / "app/fv_diag.c", model_c]
    for s in srcs:
        o = tmp_path / (s.name + ".o")
        subprocess.run(ZIG + ["cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard",
                              "-fno-pic", "-fno-pie", "-std=c99", "-Os", "-ffunction-sections", "-fdata-sections",
                              *INC, "-c", str(s), "-o", str(o)], check=True, capture_output=True)
        objs.append(str(o))
    st = tmp_path / "stubs.o"
    subprocess.run(ZIG + ["cc", "-target", "thumb-freestanding-eabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard", "-Os",
                          "-c", str(FW / "tests/fw_link_stubs.c"), "-o", str(st)], check=True, capture_output=True)
    elf = tmp_path / "fw.elf"
    r = subprocess.run(ZIG + ["cc", "-target", "thumb-freestanding-eabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard",
                              "-nostdlib", "-Wl,--gc-sections", "-Wl,-e,Reset_Handler", "-T",
                              str(FW / "linker/STM32F407VETX_FV.ld"), "-o", str(elf), *objs, str(st)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rep = tmp_path / "rep.json"
    p = subprocess.run([sys.executable, str(ROOT / "tools/firmware/fw_elf_report.py"), str(elf), str(rep)],
                       capture_output=True, text=True)
    d = json.loads(rep.read_text())
    assert p.returncode == 0 and d["all_checks_pass"], d["checks"]
    from elftools.elf.elffile import ELFFile
    e = ELFFile(open(elf, "rb"))
    assert e.get_section_by_name(".isr_vector")["sh_addr"] == 0x08000000
    vec = e.get_section_by_name(".isr_vector").data()
    assert int.from_bytes(vec[0:4], "little") == 0x20020000                # initial SP = top of SRAM
    sym = {s.name: s["st_value"] for s in e.get_section_by_name(".symtab").iter_symbols()}
    assert int.from_bytes(vec[4:8], "little") == sym["Reset_Handler"] | 1  # Thumb reset vector
    assert e.get_section_by_name(".isr_vector")["sh_size"] == 4 * (16 + 82)


def test_linker_script_rejects_ccm_dma_and_ram_overflow(tmp_path):
    """Negative tests: the ASSERTs must fail the link for RAM overflow and DMA buffers outside SRAM."""
    _need_zig()
    ld = (FW / "linker/STM32F407VETX_FV.ld").read_text()
    assert "*(.dma_buffers)" in ld and ">CCMRAM" in ld
    assert ld.count(">CCMRAM") == 1 and ".ccm_arena (NOLOAD)" in ld
    big = tmp_path / "big.c"
    big.write_text("unsigned char g_big[121*1024];\nvoid Reset_Handler(void){ g_big[0]=1; for(;;){} }\n"
                   "__attribute__((section(\".isr_vector\"),used)) void (*const v[2])(void)={0,Reset_Handler};\n")
    o = tmp_path / "big.o"
    subprocess.run(ZIG + ["cc", "-target", "thumb-freestanding-eabihf", "-mcpu=cortex_m4", "-c", str(big), "-o", str(o)],
                   check=True, capture_output=True)
    r = subprocess.run(ZIG + ["cc", "-target", "thumb-freestanding-eabihf", "-mcpu=cortex_m4", "-nostdlib",
                              "-Wl,-e,Reset_Handler", "-T", str(FW / "linker/STM32F407VETX_FV.ld"), "-o",
                              str(tmp_path / "big.elf"), str(o)], capture_output=True, text=True)
    assert r.returncode != 0, "121K .bss + 8K stack must overflow 128K SRAM"


# --------------------------------------------------------------------------- recorded WSL evidence
def test_recorded_host32_tflm_evidence():
    """Checks the RECORDED outputs of tools/firmware/build_fw_check.sh + compare/e2e scripts (WSL, x86 host).
    These are host results, not STM32 results."""
    v = ROOT / "reports/firmware/host32_fv_vision_vs_tflite.json"
    e = ROOT / "reports/firmware/host32_fv_app_e2e.json"
    c = ROOT / "reports/firmware/cm4_linkcheck_report.json"
    if not (v.exists() and e.exists() and c.exists()):
        pytest.skip("WSL evidence not generated")
    v, e, c = (json.loads(p.read_text()) for p in (v, e, c))
    assert v["n"] == 20 and v["exact_match"] == 20 and v["max_abs_int8_diff"] == 0
    assert e["agree"] == e["n"] and e["windows_outside_input"]
    assert c["all_checks_pass"] and "NOT flashable" in c["WARNING"]
    assert c["totals"]["flash_used"] <= 512 * 1024 and c["totals"]["ram_used_incl_stack_reserve"] <= 128 * 1024


def test_recorded_gcc_target_build():
    """RECORDED output of tools/firmware/build_gcc.sh (arm-none-eabi-gcc 13.2.1 + newlib-nano, WSL).
    A real target build; NOT flashed or run on hardware (drivers pending)."""
    rep = ROOT / "reports/firmware/gcc/gcc_build_report.json"
    if not rep.exists():
        pytest.skip("GCC build not recorded")
    d = json.loads(rep.read_text())
    assert d["all_checks_pass"], d["checks"]
    t = d["totals"]
    assert t["flash_used"] <= 512 * 1024 and t["ram_used_incl_stack_reserve"] <= 128 * 1024 and t["ccm_used"] <= 64 * 1024
    assert d["key_symbols"]["g_fv_model_data"]["size"] == 366848


# --------------------------------------------------------------------------- on-target self-test image
def test_selftest_sources_are_board_independent():
    """The self-test image must not touch GPIO or board peripherals (pins are not documented)."""
    import re
    srcs = [FW / "selftest/fv_selftest_main.c", FW / "selftest/fv_selftest_core.c", FW / "platform/fv_clock_stm32f4.c"]
    txt = "\n".join(p.read_text() for p in srcs)
    addrs = {int(a, 16) for a in re.findall(r"0x(4[0-9A-Fa-f]{7})u?", txt)}
    allowed = {0x40023800, 0x40023804, 0x40023808, 0x40023840, 0x40007000, 0x40023C00}
    assert addrs <= allowed, addrs - allowed
    assert "fv_platform" not in txt and "GPIO" not in txt.upper().replace("NO GPIO", "")


def test_selftest_host32_recorded_pass():
    rec = ROOT / "reports/firmware/selftest_host32.txt"
    if not rec.exists():
        pytest.skip("host32 self-test not recorded")
    line = rec.read_text().strip().splitlines()[-1]
    assert "PASS=1" in line and "mism=0,0,0" in line and "maxdiff=0" in line and "m2ok=1" in line


def test_selftest_readback_parser(tmp_path):
    pytest.importorskip("elftools")
    import struct as st
    sys.path.insert(0, str(ROOT / "tools/firmware"))
    import read_selftest as rs
    elf = ROOT / "reports/firmware/gcc/fv_selftest.elf"
    if not elf.exists():
        pytest.skip("self-test ELF not built")
    addr, size = rs.symbol(elf, "g_fv_selftest")
    assert size == rs.SIZE == 288 and 0x20000000 <= addr < 0x20020000   # SRAM, readable over SWD
    exp = json.loads((ROOT / "reports/firmware/selftest_expected.json").read_text())
    b = bytearray(288)
    st.pack_into("<IIiIiII", b, 0, rs.MAGIC_DONE, 1, 0, 2, 0, 149120, 3)
    st.pack_into("<I", b, 160, 1)
    for k in range(3):
        st.pack_into("<40b", b, 164 + 40 * k, *exp["inputs"][k]["raw"])
    st.pack_into("<fff", b, 140, *exp["m2_expected_probs"])
    words = st.unpack("<72I", bytes(b))
    lines = [f"0x{addr + 16 * i:08X} : " + " ".join(f"{w:08X}" for w in words[4 * i:4 * i + 4]) for i in range(18)]
    dump = tmp_path / "dump.txt"
    dump.write_text("header\n" + "\n".join(lines) + "\n")
    d = rs.decode(rs.parse_r32(dump.read_text(), addr, size))
    assert d["done"] and d["pass"] == 1 and d["arena_used_bytes"] == 149120 and d["sysclk_source"] == 2
    assert [d["raw"][k] == exp["inputs"][k]["raw"] for k in range(3)] == [True] * 3



def test_oled_sensor_rows_fit_without_breaking_layout(harness):
    """pH (ENTC calibration) / MQ135 / T / RH rows go into FREE rows only; footer stays last; <= 8 rows of <= 21 chars."""
    good = _cases()[0]
    flat = " ".join(" ".join(map(str, list(q) + [0] * (5 - len(q)))) for q in good)
    base = _sensor_cases()[0]
    dev = dict(base, origin=0, unit=1, mq=396.0, warm=200.0, ph=8.91, t=24.5, rh=55.0)
    nodht = dict(dev, has_temp=0, has_rh=0)
    scen = [(dev, 0, 0, 0), (nodht, 0, 0, 0), (dev, 0x1, -7, 1), (dev, 0x1, -5, 1)]
    lines = [f"O {flat} {_c_line(s)[2:]} {fl} {st} {un}" for s, fl, st, un in scen]
    out = [l for l in harness(lines) if l.strip()]
    olds = [l for l in out if l.startswith("OLED")]
    assert len(olds) == len(scen)
    for o in olds:
        rows = o.split("|")[1:]
        assert len(rows) <= 8 and all(len(r) <= 21 for r in rows)
        assert not any(w in o.lower() for w in FORBIDDEN)
    r0 = olds[0].split("|")[1:]
    assert "pH8.91 ENTC MQ396" in r0 and "T24.5C RH55%" in r0
    assert any(r.startswith("Fruit:") for r in r0) and any(r.startswith("Risk:") for r in r0)   # existing rows kept
    assert "T-- RH--" in olds[1].split("|")[1:]
    full = olds[3].split("|")[1:]                     # ERR row + rejected row + ...: only remaining free rows used
    assert full[0].startswith("ERR") and len(full) <= 8


def test_rejected_or_empty_frame_does_not_show_previous_fruit(harness):
    """A rejected or uncertain frame must immediately clear any previous fruit and never show stale fruit results."""
    good = _cases()[0]
    flat = " ".join(" ".join(map(str, list(q) + [0] * (5 - len(q)))) for q in good)
    base = _sensor_cases()[0]
    dev = dict(base, origin=0, unit=1, mq=396.0, warm=200.0, ph=8.91, t=24.5, rh=55.0)

    # Sequence of two consecutive cycles:
    # 1. Accepted fruit frame (fl=0, st=0, un=0)
    # 2. Frame rejected / unavailable (fl=0x1000, st=-7, un=1)
    scen = [(dev, 0, 0, 0), (dev, 0x1000, -7, 1)]
    lines = [f"O {flat} {_c_line(s)[2:]} {fl} {st} {un}" for s, fl, st, un in scen]
    out = [l for l in harness(lines) if l.strip()]

    # First cycle must display the predicted fruit (c0 argmax is brinjal)
    oled_cycle1 = [l for l in out[0:2] if l.startswith("OLED")][0]
    rows1 = oled_cycle1.split("|")[1:]
    assert any(r.startswith("Fruit:brinjal") for r in rows1)

    # Second cycle (rejected/unavailable) MUST NOT display brinjal or any previous fruit
    oled_cycle2 = [l for l in out[2:4] if l.startswith("OLED")][0]
    rows2 = oled_cycle2.split("|")[1:]
    assert "Fruit: UNAVAILABLE" in rows2
    assert not any(r.startswith("Fruit:brinjal") for r in rows2)
    assert not any(r.startswith("Cond:fresh") for r in rows2)
