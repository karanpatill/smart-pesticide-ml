"""Offline tests of tools/firmware/live_preview.py: simulated frame data only, no board, no SWD, no window."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import capture_live_frame as cl  # noqa: E402
import live_preview as lp  # noqa: E402
from fruitvision.camera_preprocess import rgb888_to_rgb565_bytes  # noqa: E402


def _frame(seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:120, 0:160]
    rgb = np.stack([(xx * 1.5 + seed) % 256, (yy * 2) % 256, ((xx + yy) * 0.8) % 256], -1) + rng.normal(0, 4, (120, 160, 3))
    return rgb888_to_rgb565_bytes(np.clip(rgb, 0, 255).astype(np.uint8), big_endian=True).tobytes()


def _status(frame, ok=1, err=0, stats=None):
    s = stats or cl.entc_stats(cl.decode_be(frame))
    return bytes([ok, err, s["meanR"], s["meanG"], s["meanB"], s["dark_pct"]]) + bytes(10)


def _good(seed=0):
    f = _frame(seed)
    return lp.ReadResult(True, _status(f), f, _status(f))


class FakeSource:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def read(self):
        self.calls += 1
        return self.results.pop(0)

    def close(self):
        pass


# ----------------------------------------------------------------------------- command safety
def test_preview_command_is_read_only_hotplug(tmp_path):
    cmd = lp.build_preview_command(tmp_path, 1000)
    assert cmd[0] == cl.CLI and cmd[1:5] == ["-c", "port=SWD", "freq=1000", "mode=HOTPLUG"]
    assert [c for c in cmd if c.startswith("-")] == ["-c", "-u", "-u", "-u", "-u"]
    assert [(cmd[i + 1], cmd[i + 2]) for i, c in enumerate(cmd) if c == "-u"] == [
        ("0x20000008", "16"), ("0x2000055C", "38400"), ("0x2000055C", "38400"), ("0x20000008", "16")]
    assert not cl.FORBIDDEN & set(cmd)
    for i, c in enumerate(cmd):     # every read path is inside the private temp folder
        if c == "-u":
            assert Path(cmd[i + 3]).parent == tmp_path


def test_preview_allowlist_rejects_extra_operations(tmp_path):
    cmd = lp.build_preview_command(tmp_path, 1000)
    for bad in (cmd + ["-rst"], cmd[:4] + ["mode=NORMAL"] + cmd[5:], cmd[:5] + ["-w", "a.bin", "0x08000000"] + cmd[5:],
                cmd[:-1] + ["C:/elsewhere/status_b.bin"], cmd[:6] + ["0x20000000"] + cmd[7:]):
        with pytest.raises(AssertionError):
            lp.check_preview_allowlist(bad, tmp_path)


def test_print_command_connects_to_nothing():
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/live_preview.py"), "--print-command"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "mode=HOTPLUG" in r.stdout and "Nothing executed" in r.stdout
    assert "-w" not in r.stdout.split() and "-rst" not in r.stdout.split()


def test_swd_source_does_not_run_on_import_or_construction():
    """Creating the source only makes a temp folder; no subprocess call happens until read()."""
    src = lp.SwdSource(1000)
    try:
        assert src.tmp.exists() and not list(src.tmp.iterdir())
    finally:
        src.close()
    assert not src.tmp.exists()


# ----------------------------------------------------------------------------- validation
def test_validate_accepts_good_frame():
    assert lp.validate(_good()) == (True, "ok")


@pytest.mark.parametrize("case", ["torn", "status_changed", "entc_err", "short", "read_failed", "little_endian"])
def test_validate_rejects_bad_frames(case):
    f = _frame()
    if case == "torn":                      # second read differs (DMA writing during the read)
        g = bytearray(f); g[5000:9000] = bytes(4000)
        r = lp.ReadResult(True, _status(f), f, _status(f), frame_b=bytes(g))
    elif case == "status_changed":
        r = lp.ReadResult(True, _status(f), f, _status(_frame(7)))
    elif case == "entc_err":
        r = lp.ReadResult(True, _status(f, ok=0, err=3), f, _status(f, ok=0, err=3))
    elif case == "short":
        r = lp.ReadResult(True, _status(f), f[:-2], _status(f))
    elif case == "read_failed":
        r = lp.ReadResult(False, error="CLI exit 1")
    else:   # status computed from a little-endian decode: BE check must fail
        s = cl.entc_stats(cl.decode_le(f))
        r = lp.ReadResult(True, _status(f, stats=s), f, _status(f, stats=s))
    ok, reason = lp.validate(r)
    assert not ok and reason


def test_render_is_4x_rgb():
    img = lp.render(_frame())
    assert img.shape == (480, 640, 3) and img.dtype == np.uint8
    assert np.array_equal(img[::4, ::4], cl.to_rgb888(cl.decode_be(_frame())))


# ----------------------------------------------------------------------------- controller behaviour
def test_controller_shows_valid_and_skips_invalid():
    f = _frame()
    torn = bytearray(f); torn[100:4000] = bytes(3900)
    src = FakeSource([_good(1), lp.ReadResult(True, _status(f), f, _status(f), frame_b=bytes(torn)), _good(1), _good(2)])
    c = lp.PreviewController(src, interval_s=2.0)
    delays = [c.poll_once() for _ in range(4)]
    assert delays == [2.0, 2.0, 2.0, 2.0]
    assert (c.st.shown, c.st.skipped, c.st.failures) == (3, 1, 0)
    assert [e[0] for e in c.st.log] == ["show", "skip", "show", "show"]
    assert [e[1] for e in c.st.log if e[0] == "show"] == ["changed", "same", "changed"]
    assert c.st.last_frame == _good(2).frame              # last GOOD frame stays on screen


def test_controller_backs_off_and_pauses_on_failures():
    fail = lp.ReadResult(False, error="CLI exit 1: no ST-LINK")
    src = FakeSource([_good(), fail, fail, fail, _good(3)])
    c = lp.PreviewController(src, interval_s=2.0, max_failures=3)
    assert c.poll_once() == 2.0
    assert c.poll_once() == lp.FAIL_BACKOFF_S >= 10.0       # no rapid retry after a failure
    assert c.poll_once() == lp.FAIL_BACKOFF_S
    assert c.poll_once() is None and c.st.paused            # paused after 3 consecutive failures
    assert c.poll_once() is None and src.calls == 4         # paused: no further reads at all
    assert c.st.last_frame == _good().frame                 # last good frame still displayed
    c.resume()
    assert c.poll_once() == 2.0 and c.st.shown == 2 and src.calls == 5


def test_interval_has_a_floor():
    assert lp.PreviewController(FakeSource([]), interval_s=0.01).interval == lp.MIN_INTERVAL_S


def test_no_automatic_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "SAVE_DIR", tmp_path / "saves")
    c = lp.PreviewController(FakeSource([_good(i) for i in range(5)]), interval_s=2.0)
    for _ in range(5):
        c.poll_once()
    assert not (tmp_path / "saves").exists()               # nothing written by polling
    p = c.save_current(tmp_path / "saves")                  # only the explicit Save action writes
    assert p.exists() and len(list((tmp_path / "saves").glob("*.png"))) == 1
    assert len(list((tmp_path / "saves").glob("*.rgb565be.bin"))) == 1


def test_demo_source_frames_validate():
    d = lp.DemoSource()
    for _ in range(3):
        assert lp.validate(d.read())[0]


def test_source_reuses_reviewed_capture_module():
    src = (ROOT / "tools/firmware/live_preview.py").read_text()
    assert "import capture_live_frame as cl" in src and src.count("subprocess.run(") == 1
    assert "cl.entc_stats" in src and "cl.decode_be" in src and "cl.CLI" in src


def test_tear_outside_entc_roi_is_caught_by_double_read():
    """ENTC statistics cover only x 40-119, y 30-89. A tear in the top rows passes the statistics check, so the
    double read (frame_a == frame_b) is what catches it."""
    f = _frame()
    g = bytearray(f); g[0:5000] = bytes(5000)            # rows 0..15 only: outside the ROI
    assert cl.entc_stats(cl.decode_be(bytes(g))) == cl.entc_stats(cl.decode_be(f))   # statistics alone miss it
    ok, reason = lp.validate(lp.ReadResult(True, _status(f), f, _status(f), frame_b=bytes(g)))
    assert not ok and "two reads" in reason


# --------------------------------------------------------------------------- --firmware diag (fv_app_v6/v7/v8_diag)
def _diag_src():
    pytest.importorskip("elftools")
    elf = ROOT / "reports/firmware/gcc/fv_app_v8_diag.elf"
    if not elf.exists():
        pytest.skip("fv_app_v8_diag not built")
    return lp.DiagSource(elf)


def _block(magic, seq):
    import struct as st
    import read_capture as rc
    b = bytearray(rc.SIZE)
    st.pack_into("<IIIiIi", b, 0, magic, seq, 1000, 3507, 4096, 0)
    st.pack_into("<5b", b, 24, -128, 61, -66, -128, -128)
    b[64:] = (np.arange(19200) % 256 - 128).astype(np.int8).tobytes()
    return bytes(b)


def test_diag_command_is_read_only_hotplug():
    s = _diag_src()
    cmd = s.command()
    assert cmd[0] == cl.CLI and "mode=HOTPLUG" in cmd and not (cl.FORBIDDEN & set(cmd))
    assert [c for c in cmd if c.startswith("-")] == ["-c", "-r32", "-r32"]
    with pytest.raises(AssertionError):
        lp.run_cli(cmd + ["-w32", "0x20000000", "0x0"])


def test_diag_validate_accepts_complete_rejects_torn():
    import struct as st
    import read_capture as rc
    s = _diag_src()
    good = _block(rc.MAGIC, 10)
    ok, why = s.validate(lp.ReadResult(True, good[:8], good, good[:8]))
    assert ok and "detail 350.7" in why and "banana" in why
    assert s.render(good).shape == (480, 480, 3)
    odd = _block(rc.MAGIC, 11)
    assert not s.validate(lp.ReadResult(True, odd[:8], odd, odd[:8]))[0]                     # being written
    assert not s.validate(lp.ReadResult(True, good[:8], good, st.pack("<II", rc.MAGIC, 12)))[0]  # changed during read
    zero = _block(0, 0)
    assert not s.validate(lp.ReadResult(True, zero[:8], zero, zero[:8]))[0]                  # no block / wrong firmware
    snap = _block(rc.READY, 6)
    assert s.validate(lp.ReadResult(True, snap[:8], snap, snap[:8]))[0]


def test_diag_print_command_connects_to_nothing():
    if not (ROOT / "reports/firmware/gcc/fv_app_v8_diag.elf").exists():
        pytest.skip("fv_app_v8_diag not built")
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/live_preview.py"), "--firmware", "diag", "--print-command"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "-r32" in r.stdout and "Nothing executed" in r.stdout
