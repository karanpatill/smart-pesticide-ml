"""Offline tests of tools/firmware/capture_live_frame.py (no board access, no SWD, synthetic capture directories)."""

import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import capture_live_frame as cl  # noqa: E402
from fruitvision.camera_preprocess import rgb888_to_rgb565_bytes  # noqa: E402


def _write_capture(d: Path, frame: bytes, stats: dict, vs=1, hs=0, count=38400, frame_b=None, ready=1):
    d.mkdir(parents=True, exist_ok=True)
    meta = bytes([ready, vs, hs, 0]) + struct.pack("<I", count)
    status = bytes([1, 0, stats["meanR"], stats["meanG"], stats["meanB"], stats["dark_pct"], 0, 0]) + struct.pack("<I", 0x0800ABCD) + bytes(4)
    buf = frame + bytes(40448 - len(frame))
    bufb = (frame_b or frame) + bytes(40448 - len(frame_b or frame))
    for name, data in [("meta_a.bin", meta), ("status_a.bin", status), ("frame_a.bin", buf), ("status_b.bin", status),
                       ("frame_b.bin", bufb), ("meta_b.bin", meta)]:
        (d / name).write_bytes(data)


def _frame():
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:120, 0:160]
    rgb = np.stack([(xx * 1.5) % 256, (yy * 2) % 256, ((xx + yy) * 0.8) % 256], -1) + rng.normal(0, 4, (120, 160, 3))
    return rgb888_to_rgb565_bytes(np.clip(rgb, 0, 255).astype(np.uint8), big_endian=True).tobytes()


def test_command_is_read_only_hotplug(tmp_path):
    cmd = cl.build_command(tmp_path, 1000)
    assert cmd[0].endswith("STM32_Programmer_CLI.exe")
    assert cmd[1:5] == ["-c", "port=SWD", "freq=1000", "mode=HOTPLUG"]
    ops = [c for c in cmd if c.startswith("-")]
    assert set(ops) == {"-c", "-u"} and ops.count("-u") == 6
    assert not cl.FORBIDDEN & set(cmd)
    addrs = [(cmd[i + 1], cmd[i + 2]) for i, c in enumerate(cmd) if c == "-u"]
    assert addrs == [("0x2000A35C", "8"), ("0x20000008", "16"), ("0x2000055C", "40448"), ("0x20000008", "16"),
                     ("0x2000055C", "40448"), ("0x2000A35C", "8")]
    for a, n in addrs:   # SRAM only, word aligned, inside 128 KB
        assert 0x20000000 <= int(a, 16) and int(a, 16) + int(n) <= 0x20020000 and int(a, 16) % 4 == 0 and int(n) % 4 == 0


def test_dry_run_connects_to_nothing():
    before = set((ROOT / "reports/firmware/live_capture").glob("*")) if (ROOT / "reports/firmware/live_capture").exists() else set()
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/capture_live_frame.py")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "DRY RUN" in r.stdout and "mode=HOTPLUG" in r.stdout
    after = set((ROOT / "reports/firmware/live_capture").glob("*")) if (ROOT / "reports/firmware/live_capture").exists() else set()
    assert after == before


def test_analyze_valid_capture_confirms_big_endian(tmp_path):
    f = _frame()
    stats = cl.entc_stats(cl.decode_be(f))
    _write_capture(tmp_path, f, stats)
    rep = cl.analyze(tmp_path, run_model=False)
    assert rep["valid_capture"] and rep["format_confirmed_by_entc_stats"]
    assert rep["checks"]["entc_stats_match_big_endian"] and not rep["entc_stats_match_little_endian"]
    assert (tmp_path / "frame_a_be.png").exists()


def test_analyze_detects_torn_frame_and_wrong_count(tmp_path):
    f = _frame()
    g = bytearray(f); g[1000:2000] = bytes(1000)
    stats = cl.entc_stats(cl.decode_be(f))
    _write_capture(tmp_path / "torn", f, stats, frame_b=bytes(g))
    rep = cl.analyze(tmp_path / "torn", run_model=False)
    assert not rep["checks"]["frame_stable_a_eq_b"] and not rep["format_confirmed_by_entc_stats"]
    _write_capture(tmp_path / "count", f, stats, count=38384)
    assert not cl.analyze(tmp_path / "count", run_model=False)["valid_capture"]
    _write_capture(tmp_path / "notready", f, stats, ready=0)
    assert not cl.analyze(tmp_path / "notready", run_model=False)["valid_capture"]


def test_analyze_little_endian_frame_is_not_confirmed(tmp_path):
    """If the firmware's statistics were computed on a little-endian frame, the BE check must fail."""
    f = _frame()
    stats_le = cl.entc_stats(cl.decode_le(f))
    _write_capture(tmp_path, f, stats_le)
    rep = cl.analyze(tmp_path, run_model=False)
    assert not rep["checks"]["entc_stats_match_big_endian"] and rep["entc_stats_match_little_endian"]


def test_entc_stats_matches_disassembled_formula():
    """Spot-check the integer formula on one hand-made pixel value: p = 0xF81F (R=31, G=0, B=31)."""
    p = np.full((120, 160), 0xF81F, np.uint16)
    s = cl.entc_stats(p)
    assert s == {"meanR": 248, "meanG": 0, "meanB": 248, "dark_pct": 0}
    p[:] = 0x0000
    assert cl.entc_stats(p)["dark_pct"] == 100


def test_allowlist_rejects_any_extra_operation(tmp_path):
    cmd = cl.build_command(tmp_path, 1000)
    cl.check_allowlist(cmd, tmp_path)
    for bad in (cmd + ["-rst"], cmd[:5] + ["-w", "x.bin", "0x08000000"] + cmd[5:], cmd[:4] + ["mode=UR"] + cmd[5:],
                cmd[:6] + ["0x20000000"] + cmd[7:], cmd[:-1] + [str(tmp_path.parent / "meta_b.bin")], cmd[:-4]):
        with pytest.raises(AssertionError):
            cl.check_allowlist(bad, tmp_path)


def test_partial_read_is_detected_and_stops(tmp_path):
    f = _frame()
    _write_capture(tmp_path, f, cl.entc_stats(cl.decode_be(f)))
    assert cl.incomplete_files(tmp_path) == []
    (tmp_path / "frame_b.bin").write_bytes(bytes(1000))        # short file
    (tmp_path / "meta_b.bin").unlink()                         # missing file
    bad = cl.incomplete_files(tmp_path)
    assert len(bad) == 2 and any("missing" in b for b in bad)
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/capture_live_frame.py"), "--analyze", str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 3 and "PARTIAL" in r.stdout


def test_no_retry_and_single_cli_call_in_source():
    src = (ROOT / "tools/firmware/capture_live_frame.py").read_text()
    assert src.count("subprocess.run(cmd") == 1
    import re
    body = src[src.index("def main"):]
    assert not re.search(r"^\s*while\b", body, re.M) and "for attempt" not in body and "retry(" not in body
