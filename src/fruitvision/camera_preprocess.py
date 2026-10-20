"""Bit-exact Python reference of firmware/image/preprocess_rgb565.c (camera frame -> int8 input).

Also provides RGB888 -> RGB565 packing so public-dataset images can be pushed through the
same path as a HOST PROXY of the camera pipeline (the real OV2640 ISP/scaler is not simulated).
"""

from __future__ import annotations

import numpy as np

IN_W = IN_H = 80


def rgb888_to_rgb565_bytes(rgb: np.ndarray, big_endian: bool = True) -> np.ndarray:
    r, g, b = (rgb[..., 0].astype(np.uint16) >> 3, rgb[..., 1].astype(np.uint16) >> 2,
               rgb[..., 2].astype(np.uint16) >> 3)
    v = (r << 11) | (g << 5) | b
    hi, lo = (v >> 8).astype(np.uint8), (v & 0xFF).astype(np.uint8)
    return np.stack([hi, lo] if big_endian else [lo, hi], -1).reshape(rgb.shape[0], -1)


def _unpack(src: np.ndarray, w: int, h: int, be: bool) -> np.ndarray:
    b = src.reshape(h, w, 2).astype(np.uint32)
    v = (b[..., 0] << 8) | b[..., 1] if be else (b[..., 1] << 8) | b[..., 0]
    r5, g6, b5 = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F
    return np.stack([(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)], -1).astype(np.int64)


def rgb565_to_input_int8(src: np.ndarray, w: int, h: int, big_endian: bool = True) -> np.ndarray:
    """Exact integer mirror of fv_rgb565_to_input_int8 (Q16 bilinear, centre-square crop)."""
    img = _unpack(np.asarray(src, np.uint8), w, h, big_endian)
    side = min(w, h)
    x0, y0 = (w - side) // 2, (h - side) // 2
    img = img[y0:y0 + side, x0:x0 + side]
    step = (side << 16) // IN_W

    def coords(n):
        s = ((2 * np.arange(n, dtype=np.int64) + 1) * step) // 2 - (1 << 15)
        s = np.maximum(s, 0)
        i, f = s >> 16, s & 0xFFFF
        return i, np.minimum(i + 1, side - 1), f

    yi, yi1, fy = coords(IN_H)
    xi, xi1, fx = coords(IN_W)
    c0 = img[yi][:, xi]; c1 = img[yi][:, xi1]; c2 = img[yi1][:, xi]; c3 = img[yi1][:, xi1]
    fxb, fyb = fx[None, :, None], fy[:, None, None]
    top = c0 * (65536 - fxb) + c1 * fxb
    bot = c2 * (65536 - fxb) + c3 * fxb
    v = (top * (65536 - fyb) + bot * fyb + (1 << 31)) >> 32
    return (np.minimum(v, 255) - 128).astype(np.int8)
