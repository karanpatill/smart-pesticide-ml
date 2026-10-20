"""160x120 RGB565 camera-format tests (host only; no hardware, no camera).

The format (OV2640 QQVGA RGB565, row-major, high byte first, 38,400 B, 40,448 B DMA buffer) is STATIC evidence
from the ENTC firmware binary (docs/CAMERA_ML_INTEGRATION_PLAN.md), not an observation of the real camera.
Frames here are synthesised from public-dataset images: these are offline tests, not real-camera validation.
"""

import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/stm32f407"
W, H = 160, 120
FRAME, SLACK = W * H * 2, 2048
ZIG = [sys.executable, "-m", "ziglang"]


def _need_zig():
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")


def frame_160x120(path: Path) -> np.ndarray:
    """Public image -> centre 4:3 crop -> 160x120 (PIL bilinear, stand-in for the OV2640 scaler) RGB888."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w * 3 >= h * 4:
            cw, ch = h * 4 // 3, h
        else:
            cw, ch = w, w * 3 // 4
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        return np.asarray(im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR), np.uint8)


def _images(n=40):
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    paths = [ROOT / "data/raw" / p for p in te.path]
    paths = [p for p in paths if p.exists()]
    if len(paths) < n:
        pytest.skip("public test images not available")
    idx = np.linspace(0, len(paths) - 1, n).astype(int)   # spread over fruits/sources
    return [paths[i] for i in idx]


def test_camera_geometry_header_matches_evidence():
    h = (FW / "app/fv_app.h").read_text(encoding="utf-8")
    assert re.search(r"#define FV_CAMERA_W 160\b", h) and re.search(r"#define FV_CAMERA_H 120\b", h)
    assert re.search(r"#define FV_CAMERA_BIG_ENDIAN 1\b", h) and re.search(r"FV_CAMERA_SLACK_BYTES 2048u", h)
    assert FRAME + SLACK == 40448   # ENTC DMA buffer: NDTR 10,112 words


@pytest.fixture(scope="module")
def pp_exe(tmp_path_factory):
    _need_zig()
    out = tmp_path_factory.mktemp("pp160") / "pp.exe"
    subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(out),
                          str(ROOT / "firmware/image/preprocess_rgb565.c"), str(ROOT / "firmware/image/tests/preprocess_main.c")],
                   check=True, capture_output=True)
    return out


def test_c_python_preprocess_identical_on_real_images_160x120(pp_exe):
    n_eq = 0
    for p in _images():
        src = rgb888_to_rgb565_bytes(frame_160x120(p), big_endian=True)
        assert src.size == FRAME
        r = subprocess.run([str(pp_exe)], input=f"{W} {H} 1\n".encode() + src.tobytes(), capture_output=True, check=True)
        c = np.frombuffer(r.stdout, np.int8).reshape(80, 80, 3)
        py = rgb565_to_input_int8(src, W, H, True)
        assert np.array_equal(c, py), p
        n_eq += 1
    assert n_eq == 40


def test_byte_order_matters_160x120(pp_exe):
    """Guard: decoding with the wrong byte order gives a different tensor (so the BE choice is load-bearing)."""
    src = rgb888_to_rgb565_bytes(frame_160x120(_images(1)[0]), big_endian=True)
    assert not np.array_equal(rgb565_to_input_int8(src, W, H, True), rgb565_to_input_int8(src, W, H, False))


def _busy_from_host32():
    rec = ROOT / "reports/firmware/host32_fv_vision_raw.txt"
    if not rec.exists():
        pytest.skip("host32 TFLM layout not recorded")
    busy = [tuple(map(int, l.split()[1:3])) for l in rec.read_text().splitlines() if l.startswith("BUSY")]
    used = int(re.search(r"used=(\d+)", rec.read_text()).group(1))
    np_bytes = int(re.search(r"np=(\d+)", rec.read_text()).group(1))
    return busy, used, np_bytes


def test_capture_window_fits_measured_tflm_layout(tmp_path):
    """Run the REAL C window selector (firmware/memory/fv_arena_reuse.c) on the TFLM non-persistent layout measured
    on the host (reports/firmware/host32_fv_vision_raw.txt) for the 40,448 B capture buffer."""
    _need_zig()
    busy, used, np_bytes = _busy_from_host32()
    assert np_bytes == 97280 and busy[0] == (0, 19200)
    ranges = ",".join(f"{{arena + {o}, {n}}}" for o, n in busy)
    src = tmp_path / "fit.c"
    src.write_text(f"""#include <stdio.h>
#include "fv_arena_reuse.h"
static unsigned char arena[{np_bytes}] __attribute__((aligned(16)));
int main(void) {{
    fv_range_t busy[] = {{{ranges}}};
    unsigned char *w = fv_select_camera_window(arena, sizeof arena, busy, sizeof busy / sizeof busy[0], {FRAME + SLACK}, 16);
    if (!w) {{ puts("NONE"); return 1; }}
    printf("%ld\\n", (long)(w - arena));
    return 0;
}}
""")
    exe = tmp_path / "fit.exe"
    subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", f"-I{ROOT / 'firmware/memory'}", "-o", str(exe),
                          str(src), str(ROOT / "firmware/memory/fv_arena_reuse.c")], check=True, capture_output=True)
    off = int(subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout)
    end = off + FRAME + SLACK
    assert off % 16 == 0 and off >= 19200 and end <= np_bytes
    for o, n in busy:                                  # no overlap with input/output tensors
        assert end <= o or off >= o + n
    assert (off, end) == (19200, 59648)               # 37,632 B of the window remain free


def test_capture_window_does_not_fit_without_reuse():
    """Documents why the frame must live inside the arena: a separate 40,448 B buffer would not fit in SRAM."""
    import json
    rep = ROOT / "reports/firmware/gcc/gcc_build_report.json"
    if not rep.exists():
        pytest.skip("GCC build report missing")
    ram_free = json.loads(rep.read_text())["totals"]["ram_free"]
    assert ram_free < FRAME + SLACK, ram_free


def test_dcmi_capture_core_register_mock(tmp_path):
    _need_zig()
    exe = tmp_path / "dcmi.exe"
    subprocess.run(ZIG + ["cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", f"-I{FW / 'platform'}", f"-I{FW / 'app'}",
                          "-o", str(exe), str(FW / "platform/fv_dcmi_capture.c"), str(FW / "tests/fv_dcmi_mock_test.c")],
                   check=True, capture_output=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    lines = r.stdout.splitlines()
    assert r.returncode == 0 and lines[-1] == "END fails=0", r.stdout
    assert sum(l.startswith("PASS") for l in lines) == 26


def test_dcmi_capture_core_compiles_for_cortex_m4f(tmp_path):
    _need_zig()
    subprocess.run(ZIG + ["cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4", "-mfloat-abi=hard", "-std=c99", "-Os",
                          "-Wall", "-Wextra", "-Werror", "-Wdouble-promotion", f"-I{FW / 'platform'}", f"-I{FW / 'app'}", "-c",
                          str(FW / "platform/fv_dcmi_capture.c"), "-o", str(tmp_path / "dcmi.o")], check=True, capture_output=True)


def test_selftest_frame_host32_recorded_pass():
    rec = ROOT / "reports/firmware/selftest_frame_host32.txt"
    exp = ROOT / "reports/firmware/selftest_frame_expected.json"
    if not (rec.exists() and exp.exists()):
        pytest.skip("frame self-test not recorded")
    import json
    e = json.loads(exp.read_text())
    lines = rec.read_text().splitlines()
    assert "PASS=1" in lines[0]
    f = lines[1]
    assert f"hash={e['input_hash_fnv1a']}" in f and "hash_ok=1" in f and "mism=0" in f and "result_ok=1" in f
    assert "flags=4096" in f and e["image_flags"] == 4096          # aspect warning only (160/120 > 1.1)
    assert "OFFLINE" in e["frame"]


def test_selftest_frame_elf_layout_and_flash():
    pytest.importorskip("elftools")
    import json
    sys.path.insert(0, str(ROOT / "tools/firmware"))
    import read_selftest as rs
    elf = ROOT / "reports/firmware/gcc/fv_selftest_frame.elf"
    if not elf.exists():
        pytest.skip("frame self-test ELF not built")
    addr, size = rs.symbol(elf, "g_fv_selftest")
    assert size == rs.SIZE_V2 == 372 and 0x20000000 <= addr < 0x20020000
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as fh:
        e = ELFFile(fh)
        flash = sum(s["p_filesz"] for s in e.iter_segments() if s["p_type"] == "PT_LOAD" and 0x08000000 <= s["p_paddr"] < 0x08080000)
    assert flash <= 512 * 1024
    # the verified v1 image must still be the flashed/verified one (not overwritten)
    import hashlib
    assert hashlib.sha256((ROOT / "reports/firmware/gcc/fv_selftest.elf").read_bytes()).hexdigest().startswith("71253b93")


def test_selftest_v2_parser(tmp_path):
    import json
    import struct as st
    sys.path.insert(0, str(ROOT / "tools/firmware"))
    import read_selftest as rs
    b = bytearray(372)
    st.pack_into("<I", b, 0, rs.MAGIC_DONE)
    st.pack_into("<IiIIIIiIIiI", b, 288, 1, 0, 1000, 0x75A73113, 1, 4096, 0, 60000000, 0, 1, 1)
    words = st.unpack("<93I", bytes(b))
    lines = [f"0x{0x20000000 + 16 * i:08X} : " + " ".join(f"{w:08X}" for w in words[4 * i:4 * i + 4]) for i in range(24)]
    d = rs.decode(rs.parse_r32("\n".join(lines), 0x20000000, 372))
    assert d["frame_present"] == 1 and d["frame_input_hash"] == "0x75a73113" and d["frame_image_flags"] == 4096
    assert d["frame_fruit"] == 1 and d["frame_result_ok"] == 1


def test_proxy_160x120_report_is_labelled_offline():
    import json
    rep = ROOT / "reports/firmware/camera_proxy_160x120.json"
    if not rep.exists():
        pytest.skip("proxy not run")
    r = json.loads(rep.read_text())
    assert "OFFLINE PROXY" in r["LABEL"] and "NOT real-camera" in r["LABEL"] and r["n"] == 1012
    assert {"A_training_preprocessing", "B96_firmware_proxy_96_rgb565", "D_entc_format_160x120_rgb565_be"} <= set(r)
