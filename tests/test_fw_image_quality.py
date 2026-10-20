"""Offline tests of tools/firmware/image_quality.py (synthetic images only; no board access)."""

import hashlib
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import image_quality as iq  # noqa: E402
from fruitvision.camera_preprocess import rgb888_to_rgb565_bytes  # noqa: E402


def _sharp(h=120, w=160):
    yy, xx = np.mgrid[0:h, 0:w]
    v = (((xx // 4) + (yy // 4)) % 2) * 200 + 28          # 4-px checkerboard: strong edges
    return np.stack([v, v, v], -1).astype(np.uint8)


def _blur(img, k=7):
    """Separable box blur (edge-padded)."""
    x = img.astype(np.float64)
    pad = k // 2
    x = np.pad(x, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    c = np.cumsum(np.pad(x, ((1, 0), (0, 0), (0, 0))), axis=0)
    x = (c[k:] - c[:-k]) / k
    c = np.cumsum(np.pad(x, ((0, 0), (1, 0), (0, 0))), axis=1)
    x = (c[:, k:] - c[:, :-k]) / k
    return np.clip(np.round(x), 0, 255).astype(np.uint8)


def _frame(rgb):
    return rgb888_to_rgb565_bytes(rgb, big_endian=True).tobytes()


def test_sharp_scores_higher_than_blurred():
    s, b = _sharp(), _blur(_sharp())
    ms, mb = iq.metrics_rgb(s), iq.metrics_rgb(b)
    assert ms["sharpness_laplacian_var"] > 10 * mb["sharpness_laplacian_var"] > 0
    assert abs(ms["brightness_mean"] - mb["brightness_mean"]) < 3        # same exposure, only blur differs


def test_more_blur_lowers_score_monotonically():
    scores = [iq.metrics_rgb(_blur(_sharp(), k))["sharpness_laplacian_var"] for k in (3, 5, 9, 15)]
    assert scores == sorted(scores, reverse=True)


def test_sharp_vs_blurred_through_rgb565_frame_and_model_input():
    ms, mb = iq.metrics_frame(_frame(_sharp())), iq.metrics_frame(_frame(_blur(_sharp())))
    assert ms["sharpness_laplacian_var"] > mb["sharpness_laplacian_var"]
    assert ms["sharpness_model_input"] > mb["sharpness_model_input"]
    assert ms["crop_px"] == [120, 120]


def test_uniform_image_has_zero_sharpness_and_known_brightness():
    m = iq.metrics_rgb(np.full((120, 160, 3), 100, np.uint8))
    assert m["sharpness_laplacian_var"] == 0.0 and m["brightness_mean"] == 100.0
    assert m["clipped_highlight_pct"] == 0.0 and m["clipped_shadow_pct"] == 0.0


def test_clipping_percentages():
    img = np.full((120, 160, 3), 128, np.uint8)
    c = iq.centre_crop(img)                      # view into img: modify the crop region only
    c[:12, :, :] = 255                           # 10 % of the 120x120 crop saturated
    c[12:18, :, 0] = 0; c[12:18, :, 1] = 0; c[12:18, :, 2] = 0   # 5 % black
    img[:, :20] = 255                            # outside the crop: must not count
    m = iq.metrics_rgb(img)
    assert m["clipped_highlight_pct"] == 10.0 and m["clipped_shadow_pct"] == 5.0


def test_centre_crop_matches_firmware_preprocessing_window():
    img = np.zeros((120, 160, 3), np.uint8)
    img[:, 20:140] = 7
    c = iq.centre_crop(img)
    assert c.shape == (120, 120, 3) and (c == 7).all()


def test_capture_dir_is_read_only_and_output_is_new(tmp_path):
    cap = tmp_path / "live_capture" / "20990101T000000Z"
    cap.mkdir(parents=True)
    fr = _frame(_sharp()) + bytes(40448 - 38400)
    (cap / "frame_a.bin").write_bytes(fr)
    before = hashlib.sha256((cap / "frame_a.bin").read_bytes()).hexdigest()
    out = tmp_path / "iq"
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/image_quality.py"), str(cap), "--out-dir", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "Comparative measurements only" in r.stdout
    assert hashlib.sha256((cap / "frame_a.bin").read_bytes()).hexdigest() == before
    assert sorted(p.name for p in cap.iterdir()) == ["frame_a.bin"]      # nothing written into the capture folder
    files = list(out.glob("*.json"))
    assert len(files) == 1
    r2 = subprocess.run([sys.executable, str(ROOT / "tools/firmware/image_quality.py"), str(cap), "--out-dir", str(out)],
                        capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0 and len(list(out.glob("*.json"))) == 2      # a second run adds a new file


def test_short_frame_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        iq.metrics_frame(bytes(100))
