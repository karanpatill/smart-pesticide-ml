"""Host tests for firmware memory helpers (compiled C, no hardware)."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_arena_reuse_selector(tmp_path):
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")
    exe = tmp_path / "arena_reuse_test.exe"
    subprocess.run([sys.executable, "-m", "ziglang", "cc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-o", str(exe), str(ROOT / "firmware/memory/fv_arena_reuse.c"),
                    str(ROOT / "firmware/memory/tests/arena_reuse_test.c")], check=True, capture_output=True)
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "FAIL" not in r.stdout


def test_firmware_c_compiles_for_cortex_m4f(tmp_path):
    """Compile-only check of every firmware C file for the target ISA (no link, no hardware)."""
    try:
        import ziglang  # noqa: F401
    except ImportError:
        pytest.skip("ziglang not installed")
    srcs = ["firmware/model2/model2_infer.c", "firmware/image/preprocess_rgb565.c", "firmware/memory/fv_arena_reuse.c"]
    for s in srcs:
        subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "thumb-linux-musleabihf", "-mcpu=cortex_m4",
                        "-mfloat-abi=hard", "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror",
                        f"-I{ROOT / 'models/model2_export'}", "-c", str(ROOT / s),
                        "-o", str(tmp_path / (Path(s).stem + ".o"))], check=True, capture_output=True)
        assert (tmp_path / (Path(s).stem + ".o")).stat().st_size > 0
