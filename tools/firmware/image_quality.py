"""OFFLINE image-quality measurements for saved OV2640 live captures (no board access, read-only on the inputs).

For each capture folder (reports/firmware/live_capture/<UTC>/frame_a.bin, 160x120 RGB565 big-endian, the format
confirmed on the real board) it measures, on the MODEL'S CENTRE CROP (the 120x120 centre square that the firmware
preprocessing resizes to 80x80, i.e. x 20..139, y 0..119):
  * sharpness_laplacian_var   variance of the 3x3 Laplacian of the luminance (higher = more fine detail / sharper)
  * sharpness_model_input     the same measure on the 80x80 int8 model input (what the model actually sees)
  * brightness_mean           mean luminance 0..255 (Y = 0.299 R + 0.587 G + 0.114 B)
  * clipped_highlight_pct     % pixels with any channel at full scale (255 after RGB565 expansion)
  * clipped_shadow_pct        % pixels with all channels at 0
IMPORTANT: these are COMPARATIVE measurements for comparing captures of the same camera/scene setup (e.g. before and
after refocusing). They are not universal pass/fail thresholds: the Laplacian variance also depends on scene content,
texture, noise and exposure (noise raises it, a plain fruit surface lowers it).

Inputs are only read; results go to a NEW file reports/firmware/image_quality/<UTC>.json (never overwritten).
Usage:  python tools/firmware/image_quality.py                       # all folders under reports/firmware/live_capture
        python tools/firmware/image_quality.py <capture_dir> [...]   # specific folders
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))
import capture_live_frame as cl  # noqa: E402  (confirmed decode: 160x120 RGB565 big-endian)

W, H = cl.W, cl.H
NOTE = ("Comparative measurements only (same camera/scene setup). Not universal pass/fail thresholds; Laplacian "
        "variance depends on scene content, texture, noise and exposure.")


def centre_crop(rgb: np.ndarray) -> np.ndarray:
    """The square the firmware preprocessing uses: side = min(W, H), centred (same as camera_preprocess)."""
    h, w = rgb.shape[:2]
    side = min(w, h)
    x0, y0 = (w - side) // 2, (h - side) // 2
    return rgb[y0:y0 + side, x0:x0 + side]


def luminance(rgb: np.ndarray) -> np.ndarray:
    x = rgb.astype(np.float64)
    return 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]


def laplacian_var(y: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian [[0,1,0],[1,-4,1],[0,1,0]] over the valid (non-border) region."""
    lap = y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:] - 4.0 * y[1:-1, 1:-1]
    return float(lap.var())


def metrics_rgb(rgb: np.ndarray) -> dict:
    c = centre_crop(rgb)
    y = luminance(c)
    n = c.shape[0] * c.shape[1]
    return {"crop_px": [int(c.shape[1]), int(c.shape[0])],
            "sharpness_laplacian_var": round(laplacian_var(y), 2),
            "brightness_mean": round(float(y.mean()), 2),
            "clipped_highlight_pct": round(100.0 * float((c >= 255).any(axis=-1).sum()) / n, 3),
            "clipped_shadow_pct": round(100.0 * float((c <= 0).all(axis=-1).sum()) / n, 3)}


def metrics_frame(frame: bytes) -> dict:
    """160x120 RGB565 BE frame -> metrics on the centre crop + sharpness of the 80x80 model input."""
    from fruitvision.camera_preprocess import rgb565_to_input_int8
    if len(frame) < cl.FRAME:
        raise ValueError(f"frame too short: {len(frame)} B")
    m = metrics_rgb(cl.to_rgb888(cl.decode_be(frame[:cl.FRAME])))
    x = rgb565_to_input_int8(np.frombuffer(frame[:cl.FRAME], np.uint8), W, H, True).astype(np.float64) + 128.0
    m["sharpness_model_input"] = round(laplacian_var(luminance(x)), 2)
    return m


def analyze_capture(d: Path) -> dict:
    f = d / "frame_a.bin"
    data = f.read_bytes()
    rec = {"capture": d.name, "file": str(f), "frame_sha256": hashlib.sha256(data[:cl.FRAME]).hexdigest()}
    rec.update(metrics_frame(data))
    a = d / "analysis.json"
    if a.exists():                                   # carry over the capture's own validity verdict (read-only)
        j = json.loads(a.read_text())
        rec["capture_valid"] = j.get("valid_capture")
        rec["format_confirmed"] = j.get("format_confirmed_by_entc_stats")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", type=Path)
    ap.add_argument("--out-dir", type=Path, default=ROOT / "reports/firmware/image_quality")
    a = ap.parse_args()
    dirs = a.dirs or sorted(p for p in (ROOT / "reports/firmware/live_capture").glob("*") if (p / "frame_a.bin").exists())
    if not dirs:
        print("no capture folders with frame_a.bin found"); return 1
    rows = [analyze_capture(d) for d in dirs]
    out = a.out_dir / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + ".json")
    if out.exists():
        print(f"refusing to overwrite {out}"); return 2
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"NOTE": NOTE, "crop": "centre 120x120 of 160x120 (model centre crop)", "captures": rows}, indent=1))
    print(NOTE)
    print(f"{'capture':18s} {'sharp(crop)':>11s} {'sharp(80x80)':>12s} {'bright':>7s} {'hi-clip%':>8s} {'lo-clip%':>8s}  valid")
    for r in rows:
        print(f"{r['capture']:18s} {r['sharpness_laplacian_var']:11.2f} {r['sharpness_model_input']:12.2f} {r['brightness_mean']:7.2f} "
              f"{r['clipped_highlight_pct']:8.3f} {r['clipped_shadow_pct']:8.3f}  {r.get('capture_valid')}")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
