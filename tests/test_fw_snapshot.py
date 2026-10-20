"""Write-once diagnostic snapshot (fv_app_v7_diag, -DFV_DIAG_CAPTURE): host C test of app/fv_capture.c, Cortex-M4 compile,
reader acceptance/rejection on synthetic SWD dumps, and memory placement of the built ELF (skipped until built)."""

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/stm32f407"
GCC = ROOT / "reports/firmware/gcc"
sys.path.insert(0, str(ROOT / "tools/firmware"))
INC = [f"-I{p}" for p in (FW / "app", FW / "platform", FW / "vision", FW / "generated", ROOT / "firmware/model2",
                           ROOT / "models/model2_export", ROOT / "firmware/image", ROOT / "firmware/memory")]


def _zig():
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")


def test_snapshot_host_consistency_and_bounds(tmp_path):
    _zig()
    exe = tmp_path / "snap.exe"
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", *INC,
                        "-o", str(exe), str(FW / "tests/fv_snapshot_host_test.c"), str(FW / "app/fv_capture.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    lines = p.stdout.split()
    assert p.returncode == 0 and "FAIL" not in lines and lines[-1] == "END", p.stdout
    assert p.stdout.count("PASS") == 12


def test_snapshot_compiles_for_cortex_m4f(tmp_path):
    _zig()
    for src in ("fv_capture.c", "fv_app.c"):
        r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4",
                            "-mfloat-abi=hard", "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion",
                            "-DFV_DIAG_CAPTURE", *INC, "-c", str(FW / "app" / src), "-o", str(tmp_path / "a.o")],
                           capture_output=True, text=True)
        assert r.returncode == 0, (src, r.stderr)


def _dump(addr, magic, seq, raw, x):
    import read_capture as rc
    b = bytearray(rc.SIZE)
    struct.pack_into("<IIIiIi", b, 0, magic, seq, 1234, 361, 4096, 0)
    struct.pack_into("<40b", b, 24, *raw)
    b[64:] = x.astype(np.int8).tobytes()
    w = struct.unpack(f"<{rc.SIZE // 4}I", bytes(b))
    return "\n".join(f"0x{addr + 16 * i:08X} : " + " ".join(f"{v:08X}" for v in w[4 * i:4 * i + 4]) for i in range((len(w) + 3) // 4))


def _run(a, b, elf):
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/read_capture.py"), "--elf", str(elf), "--dump", str(a), str(b)],
                       capture_output=True, text=True, timeout=300)
    return r.returncode, json.loads(r.stdout[r.stdout.index("{"):])


def test_reader_accepts_ready_snapshot_rejects_not_ready_or_changed(tmp_path):
    pytest.importorskip("elftools"); pytest.importorskip("tensorflow")
    import read_capture as rc
    import read_selftest as rs
    elf = next((GCC / n for n in ("fv_app_v7_diag.elf", "fv_app_v6_diag.elf") if (GCC / n).exists()), None)
    if elf is None:
        pytest.skip("diagnostic build not present")
    addr, _ = rs.symbol(elf, "g_fv_capture")
    x = np.random.default_rng(0).integers(-128, 128, 19200).astype(np.int8)
    raw = rc.python_raw(x)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(_dump(addr, rc.READY, 6, raw, x)); b.write_text(_dump(addr, rc.READY, 6, raw, x))
    code, rep = _run(a, b, elf)
    assert code == 0 and rep["write_once_snapshot"] and rep["stable_complete_read"] and rep["python_equals_device_bit_exact"]
    b.write_text(_dump(addr, 0, 6, raw, x))                      # not ready -> reject
    assert _run(a, b, elf)[0] == 1
    x2 = x.copy(); x2[100] ^= 1
    b.write_text(_dump(addr, rc.READY, 6, raw, x2))              # contents changed between reads -> reject
    assert _run(a, b, elf)[0] == 1


def test_v7_diag_memory_placement():
    pytest.importorskip("elftools")
    import read_selftest as rs
    elf = GCC / "fv_app_v7_diag.elf"
    if not elf.exists():
        pytest.skip("fv_app_v7_diag not built")
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        e = ELFFile(f)
        syms = {s.name: (s["st_value"], s["st_size"]) for s in e.get_section_by_name(".symtab").iter_symbols()}
        bss = e.get_section_by_name(".bss")
        bss_lo, bss_hi = bss["sh_addr"], bss["sh_addr"] + bss["sh_size"]
    cap, size = syms["g_fv_capture"]
    assert size == 19264 and cap % 4 == 0 and bss_lo <= cap and cap + size <= bss_hi <= 0x20020000
    for other in ("g_arena_nonpersistent", "g_fv_diag", "g_cycle"):
        lo, n = next(v for k, v in syms.items() if k == other or k.startswith(other + "."))
        assert cap + size <= lo or lo + n <= cap, other                  # no overlap with arena / diag / cycle state
    assert "s_snap_cycle" in syms and "fv_snapshot_stage" in syms and "fv_snapshot_commit" in syms
    assert rs.symbol(elf, "g_fv_capture") == (cap, size)


def test_preserved_artifacts_untouched():
    h = lambda p: hashlib.sha256((GCC / p).read_bytes()).hexdigest()
    assert h("fv_app_v4.elf").startswith("b18b2a29") and h("fv_app_v4.bin").startswith("9cd1191e")
    assert h("fv_app_v5.elf").startswith("2a72f1b9")
    assert h("fv_app_v6_diag.elf").startswith("a0ab54b4") and h("fv_app_v6_diag.bin").startswith("b6ceb4cc")
    bk = ROOT / "backups/board_original_firmware/board_flash_0x08000000_512K.bin"
    if bk.exists():
        assert hashlib.sha256(bk.read_bytes()).hexdigest().startswith("1590cd4e")


# --------------------------------------------------------------------------- v8_diag camera tuning (rolling capture)
def test_cam_tune_and_rolling_capture_host(tmp_path):
    _zig()
    exe = tmp_path / "tune.exe"
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-DFV_DIAG_ROLLING",
                        *INC, f"-I{FW / 'drivers'}", "-o", str(exe), str(FW / "tests/fv_cam_tune_host_test.c"),
                        str(FW / "drivers/fv_cam_tune.c"), str(FW / "app/fv_capture.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    lines = p.stdout.split()
    assert p.returncode == 0 and "FAIL" not in lines and lines[-1] == "END", p.stdout
    assert p.stdout.count("PASS") == 14


def test_v8_sources_compile_for_cortex_m4f(tmp_path):
    _zig()
    flags = ["-DFV_DIAG_CAPTURE", "-DFV_DIAG_ROLLING", "-DFV_DIAG_CAM_TUNE"]
    for src in (FW / "drivers/fv_cam_tune.c", FW / "app/fv_capture.c", FW / "app/fv_app.c"):
        r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4",
                            "-mfloat-abi=hard", "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion", *flags,
                            *INC, f"-I{FW / 'drivers'}", "-c", str(src), "-o", str(tmp_path / "a.o")], capture_output=True, text=True)
        assert r.returncode == 0, (src.name, r.stderr)


def test_cam_tune_tool_writes_only_tune_block():
    pytest.importorskip("elftools")
    import cam_tune as ct
    import read_selftest as rs
    elf = GCC / "fv_app_v8_diag.elf"
    if not elf.exists():
        pytest.skip("fv_app_v8_diag not built")
    addr, size = rs.symbol(elf, "g_fv_cam_tune")
    assert size == ct.SIZE == 52
    cmd = ct.write_cmd(addr, {"lenc": 1, "awb": 5, "sat": 5, "ae": 5}, 7)
    ct.check_writes_confined(cmd, addr)
    assert cmd[-1] == "0x7" and cmd[-2] == hex(addr + 4)                       # req written last
    for bad in (["-w32", hex(addr + ct.OFF["applied"]), "0x0"], ["-w32", "0x8000000", "0x0"], ["-e", "all"], ["-rst"]):
        with pytest.raises(SystemExit):
            ct.check_writes_confined(cmd + bad, addr)


def test_v8_diag_memory_placement():
    pytest.importorskip("elftools")
    elf = GCC / "fv_app_v8_diag.elf"
    if not elf.exists():
        pytest.skip("fv_app_v8_diag not built")
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        e = ELFFile(f)
        syms = {s.name: (s["st_value"], s["st_size"]) for s in e.get_section_by_name(".symtab").iter_symbols()}
    for name, n in (("g_fv_capture", 19264), ("g_fv_cam_tune", 52)):
        lo, size = syms[name]
        assert size == n and 0x20000000 <= lo and lo + size <= 0x20020000 and lo % 4 == 0
    rep = json.loads((GCC / "fv_app_v8_diag_build_report.json").read_text())
    assert rep["all_checks_pass"] and rep["totals"]["ram_used_incl_stack_reserve"] <= 128 * 1024
