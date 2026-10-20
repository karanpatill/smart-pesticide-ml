"""Conservative image input validation (no ML).

This is a GENERIC input sanity check. It is NOT a trained "not-a-fruit" detector:
an ordinary photo of a non-fruit object will usually pass. It rejects inputs that
are unusable (unreadable, empty, wrong channels, too small) or are statistically
unlike any real photograph in the training data (near-uniform frames, noise-like
frames, grayscale frames), using thresholds placed OUTSIDE the range observed on
~9.9k real public-dataset images (configs/image_checks.json,
scripts/calibrate_image_checks.py).

Statistics are computed on the 80x80 model input produced by the exact Model 1
preprocessing (aspect-preserving resize + centre crop/pad).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "BMP", "WEBP"}


def model_input_80(rgb: np.ndarray) -> np.ndarray:
    """Exact Model 1 preprocessing (TF ops) -> float32 80x80x3, values 0..255."""
    import tensorflow as tf
    from fruitvision.data.pipeline import resize_image
    return resize_image(tf.constant(rgb), 80).numpy()


def content_stats(x80: np.ndarray) -> dict:
    x = np.clip(x80, 0, 255).astype(np.float32)
    lum = 0.299 * x[..., 0] + 0.587 * x[..., 1] + 0.114 * x[..., 2]
    l0 = lum - lum.mean()
    denom = float((l0 ** 2).mean()) + 1e-9
    ac_h = float((l0[:, 1:] * l0[:, :-1]).mean() / denom)
    ac_v = float((l0[1:, :] * l0[:-1, :]).mean() / denom)
    chroma = float(np.abs(x - x.mean(axis=2, keepdims=True)).mean())
    return {"lum_mean": float(lum.mean()), "lum_std": float(lum.std()),
            "lag1_autocorr": (ac_h + ac_v) / 2, "chroma_mean_abs": chroma,
            "clipped_fraction": float(((x <= 1) | (x >= 254)).all(axis=2).mean())}


@dataclass
class ImageCheck:
    status: str                               # "ok" | "warning" | "rejected"
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    rgb: np.ndarray | None = None             # decoded RGB uint8 (None if rejected before decode)

    def as_dict(self) -> dict:
        return {"status": self.status, "reasons": self.reasons, "warnings": self.warnings,
                "stats": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.stats.items()},
                "note": "Generic input sanity check, not a trained not-a-fruit detector."}


def _decode(data: bytes) -> tuple[np.ndarray | None, list, list, dict]:
    reasons, warnings, info = [], [], {}
    try:
        with Image.open(io.BytesIO(data)) as im:
            info["format"] = im.format
            if im.format not in ALLOWED_FORMATS:
                return None, [f"unsupported image format {im.format!r} (allowed: {sorted(ALLOWED_FORMATS)})"], warnings, info
            if getattr(im, "n_frames", 1) > 1:
                return None, ["multi-frame/animated image; provide a single still frame"], warnings, info
            im.load()
            info["mode"], (info["width"], info["height"]) = im.mode, im.size
            if im.mode in ("L", "LA", "1", "I", "I;16", "F"):
                return None, [f"single-channel image (mode {im.mode}); colour is required"], warnings, info
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                warnings.append("alpha channel discarded (composited on black is NOT done; alpha simply dropped)")
            if im.mode != "RGB":
                warnings.append(f"converted from mode {im.mode} to RGB")
            rgb = np.asarray(im.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as e:
        return None, [f"unreadable/corrupted image: {type(e).__name__}: {e}"], warnings, info
    return rgb, reasons, warnings, info


def check_image(source, cfg: dict) -> ImageCheck:
    """source: path, bytes, or HxWx3 uint8 array."""
    if isinstance(source, np.ndarray):
        arr = source
        if arr.ndim != 3 or arr.shape[2] != 3:
            return ImageCheck("rejected", [f"array must be HxWx3, got shape {arr.shape}"])
        if arr.dtype != np.uint8:
            return ImageCheck("rejected", [f"array dtype must be uint8 (0..255), got {arr.dtype}"])
        rgb, reasons, warnings, info = arr, [], [], {"width": arr.shape[1], "height": arr.shape[0]}
    else:
        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.is_file():
                return ImageCheck("rejected", [f"file not found: {p}"])
            data = p.read_bytes()
        else:
            data = bytes(source)
        if len(data) == 0:
            return ImageCheck("rejected", ["empty input (0 bytes)"])
        rgb, reasons, warnings, info = _decode(data)
        if rgb is None:
            return ImageCheck("rejected", reasons, warnings, info)

    h, w = rgb.shape[:2]
    lim = cfg["dimensions"]
    if min(h, w) < lim["reject_min_side"]:
        return ImageCheck("rejected", [f"image too small ({w}x{h}); minimum side {lim['reject_min_side']} px"], warnings, info, rgb)
    if max(h, w) > lim["reject_max_side"]:
        return ImageCheck("rejected", [f"image too large ({w}x{h}); maximum side {lim['reject_max_side']} px"], warnings, info, rgb)
    if min(h, w) < lim["warn_min_side"]:
        warnings.append(f"small image ({w}x{h}); will be upsampled to the 80x80 model input")
    ar = max(h, w) / min(h, w)
    if ar > lim["warn_aspect_ratio"]:
        warnings.append(f"aspect ratio {ar:.2f} > {lim['warn_aspect_ratio']}; the model input will be letterboxed "
                        "with black bars (training images are mostly square). Prefer a centre-square crop.")

    stats = {**info, **content_stats(model_input_80(rgb))}
    r = cfg["reject"]
    if stats["lum_std"] < r["lum_std_below"]:
        reasons.append(f"near-uniform image (luminance std {stats['lum_std']:.2f} < {r['lum_std_below']}); "
                       "e.g. lens cap, blank frame or camera fault")
    if stats["lag1_autocorr"] < r["lag1_autocorr_below"]:
        reasons.append(f"noise-like image (neighbour-pixel correlation {stats['lag1_autocorr']:.3f} < "
                       f"{r['lag1_autocorr_below']}); not consistent with a camera photograph")
    if stats["chroma_mean_abs"] < r["chroma_below"]:
        reasons.append(f"grayscale content (mean |channel deviation| {stats['chroma_mean_abs']:.2f} < "
                       f"{r['chroma_below']}); colour is required")
    wv = cfg["warn"]
    if stats["lum_mean"] < wv["lum_mean_below"]:
        warnings.append(f"very dark image (mean luminance {stats['lum_mean']:.1f}); predictions may be unreliable")
    if stats["lum_mean"] > wv["lum_mean_above"]:
        warnings.append(f"very bright image (mean luminance {stats['lum_mean']:.1f}); predictions may be unreliable")
    if stats["clipped_fraction"] > wv["clipped_fraction_above"]:
        warnings.append(f"{stats['clipped_fraction']:.0%} of pixels clipped to black/white; exposure problem")

    status = "rejected" if reasons else ("warning" if warnings else "ok")
    return ImageCheck(status, reasons, warnings, stats, rgb)
