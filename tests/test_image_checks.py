"""Regression tests for the generic image input checks (no model involved)."""

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from fruitvision.validation.image_checks import check_image

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "configs/image_checks.json").read_text())


def jpeg(arr, mode=None, fmt="JPEG"):
    b = io.BytesIO()
    im = Image.fromarray(arr) if mode is None else Image.fromarray(arr).convert(mode)
    im.save(b, format=fmt)
    return b.getvalue()


def natural(h=200, w=200, seed=0):
    """Smooth coloured gradient + blob: statistically photo-like, deterministic."""
    yy, xx = np.mgrid[0:h, 0:w] / max(h, w)
    blob = np.exp(-((xx - .5) ** 2 + (yy - .5) ** 2) / .05)
    return np.stack([80 + 150 * blob, 60 + 120 * xx, 40 + 60 * yy], -1).clip(0, 255).astype(np.uint8)


def test_uniform_grey_rejected():
    r = check_image(jpeg(np.full((200, 200, 3), 128, np.uint8)), CFG)
    assert r.status == "rejected" and any("near-uniform" in x for x in r.reasons)


def test_random_noise_rejected():
    arr = np.random.default_rng(0).integers(0, 256, (200, 200, 3), dtype=np.uint8)
    r = check_image(jpeg(arr, fmt="PNG"), CFG)
    assert r.status == "rejected" and any("noise-like" in x for x in r.reasons)


def test_grayscale_file_rejected():
    r = check_image(jpeg(natural(), mode="L"), CFG)
    assert r.status == "rejected" and "single-channel" in r.reasons[0]


def test_grayscale_content_in_rgb_rejected():
    g = natural()[..., :1].repeat(3, axis=2)
    r = check_image(jpeg(g, fmt="PNG"), CFG)
    assert r.status == "rejected" and any("grayscale content" in x for x in r.reasons)


def test_corrupted_and_empty_rejected(tmp_path):
    assert check_image(b"", CFG).status == "rejected"
    assert "unreadable" in check_image(b"\xff\xd8\xff\xe0garbage", CFG).reasons[0]
    p = tmp_path / "trunc.jpg"
    p.write_bytes(jpeg(natural())[:300])
    assert check_image(p, CFG).status == "rejected"
    assert check_image(tmp_path / "missing.jpg", CFG).reasons[0].startswith("file not found")


def test_tiny_image_rejected_and_small_warned():
    assert check_image(jpeg(natural(20, 20)), CFG).status == "rejected"
    r = check_image(jpeg(natural(60, 60)), CFG)
    assert r.status == "warning" and any("upsampled" in w for w in r.warnings)


def test_rgba_warns_and_aspect_ratio_warns():
    rgba = np.dstack([natural(), np.full((200, 200), 255, np.uint8)])
    r = check_image(jpeg(rgba, fmt="PNG"), CFG)
    assert r.status in ("ok", "warning") and any("alpha" in w for w in r.warnings)
    r2 = check_image(jpeg(natural(120, 160)), CFG)          # 4:3 camera frame
    assert any("letterboxed" in w for w in r2.warnings)


def test_array_input_validation():
    assert check_image(np.zeros((10, 10)), CFG).status == "rejected"
    assert check_image(natural().astype(np.float32), CFG).status == "rejected"
    assert check_image(natural(), CFG).status in ("ok", "warning")


def test_unsupported_format_rejected():
    assert check_image(jpeg(natural(), fmt="TIFF"), CFG).status == "rejected"


@pytest.mark.skipif(not (ROOT / "data/splits/test.csv").exists(), reason="dataset not present")
def test_real_dataset_images_not_rejected():
    paths = pd.read_csv(ROOT / "data/splits/test.csv").sample(40, random_state=0).path
    res = [check_image(ROOT / "data/raw" / p, CFG) for p in paths]
    assert all(r.status != "rejected" for r in res)
