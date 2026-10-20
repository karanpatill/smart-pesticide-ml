"""Bit-exact parity: firmware C camera preprocessing vs Python reference (host-compiled C)."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")
    out = tmp_path_factory.mktemp("pp") / "pp.exe"
    subprocess.run([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-o", str(out), str(ROOT / "firmware/image/preprocess_rgb565.c"),
                    str(ROOT / "firmware/image/tests/preprocess_main.c")], check=True, capture_output=True)
    return out


def run_c(exe, src, w, h, be):
    data = f"{w} {h} {int(be)}\n".encode() + src.tobytes()
    r = subprocess.run([str(exe)], input=data, capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.int8).reshape(80, 80, 3)


@pytest.mark.parametrize("w,h,be", [(96, 96, True), (96, 96, False), (160, 120, True), (80, 80, True),
                                    (120, 120, False), (101, 77, True)])
def test_c_matches_python_bit_exact(exe, w, h, be):
    rng = np.random.default_rng(w * 1000 + h)
    rgb = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    src = rgb888_to_rgb565_bytes(rgb, be)
    assert np.array_equal(run_c(exe, src, w, h, be), rgb565_to_input_int8(src, w, h, be))


def test_identity_size_and_range():
    rgb = np.full((80, 80, 3), 255, np.uint8)
    out = rgb565_to_input_int8(rgb888_to_rgb565_bytes(rgb), 80, 80)
    assert out.shape == (80, 80, 3) and out.max() == 127          # 255 - 128
    blk = rgb565_to_input_int8(rgb888_to_rgb565_bytes(np.zeros((96, 96, 3), np.uint8)), 96, 96)
    assert blk.min() == -128


def test_rejects_bad_args(exe):
    r = subprocess.run([str(exe)], input=b"4 4 1\n" + bytes(32), capture_output=True)
    assert r.returncode == 4
