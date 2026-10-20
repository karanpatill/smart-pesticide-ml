"""Collect calibrated OV2640 hardware captures per fruit class for model fine-tuning.

This workflow captures live 160x120 RGB565 frames directly from the STM32F407 hardware
over SWD (read-only), saves the raw frame, extracts the central 80x80 model input,
and organizes labeled datasets required to retrain/fine-tune the vision backbone
for Apple and Guava domain adaptation.

Usage:
  python tools/capture_hardware_dataset.py --fruit apple --label Good --samples 30 --execute
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import struct
import subprocess
import sys
import time

from PIL import Image
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI = r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
DATA_DIR = ROOT / "data" / "hardware_captures"

W, H = 160, 120
FRAME_BYTES = W * H * 2
DCMI_BUF_ADDR = 0x2000055C  # Hardware DMA frame buffer in SRAM1


def capture_frame_swd(out_bin: pathlib.Path) -> bool:
    """Read one 160x120 RGB565 frame directly from camera SRAM over SWD."""
    cmd = [
        CLI,
        "-c", "port=SWD", "freq=4000", "mode=HOTPLUG",
        "-u", hex(DCMI_BUF_ADDR), str(FRAME_BYTES), str(out_bin)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return res.returncode == 0 and out_bin.exists() and out_bin.stat().st_size >= FRAME_BYTES


def rgb565_to_rgb888(raw_bytes: bytes) -> Image.Image:
    """Decode raw big-endian RGB565 buffer to PIL RGB Image."""
    arr = np.frombuffer(raw_bytes[:FRAME_BYTES], dtype=">u2").reshape((H, W))
    r = ((arr >> 11) & 0x1F) * 255 // 31
    g = ((arr >> 5) & 0x3F) * 255 // 63
    b = (arr & 0x1F) * 255 // 31
    rgb = np.stack([r, g, b], axis=-1).astype(np.uint8)
    return Image.fromarray(rgb)


def extract_model_input(img: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """120x120 center crop -> 80x80 bilinear resize -> int8 model tensor."""
    left = (W - H) // 2
    crop = img.crop((left, 0, left + H, H))
    resized = crop.resize((80, 80), Image.BILINEAR)
    arr = np.asarray(resized, dtype=np.int32)
    int8_tensor = (arr - 128).astype(np.int8)
    return resized, int8_tensor


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture hardware training images via SWD")
    parser.add_argument("--fruit", required=True, choices=["apple", "banana", "guava", "tomato", "brinjal"])
    parser.add_argument("--label", default="fresh", choices=["fresh", "spoiled", "Good", "Average", "Poor"])
    parser.add_argument("--samples", type=int, default=10, help="Number of samples to capture")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between captures (for rotation/reposition)")
    parser.add_argument("--execute", action="store_true", help="Execute capture over SWD")
    args = parser.parse_args()

    session_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = DATA_DIR / args.fruit / f"{args.label}_{session_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Dataset Capture Target: {args.fruit} ({args.label})")
    print(f"Target Directory: {out_dir}")
    print(f"Requested Samples: {args.samples}")

    if not args.execute:
        print("[DRY-RUN] To start capture, provide --execute flag.")
        return 0

    manifest = []
    for i in range(args.samples):
        print(f"\n[{i+1}/{args.samples}] Place/rotate {args.fruit} in camera field of view...")
        time.sleep(args.interval)

        raw_path = out_dir / f"frame_{i:03d}.raw"
        png_path = out_dir / f"frame_{i:03d}.png"
        crop_path = out_dir / f"input_{i:03d}_80x80.png"
        int8_path = out_dir / f"input_{i:03d}.int8"

        ok = capture_frame_swd(raw_path)
        if not ok:
            print(f"Error capturing frame {i}. Retrying...")
            continue

        raw_bytes = raw_path.read_bytes()
        img = rgb565_to_rgb888(raw_bytes)
        img.save(png_path)

        crop_img, int8_tensor = extract_model_input(img)
        crop_img.save(crop_path)
        int8_path.write_bytes(int8_tensor.tobytes())

        manifest.append({
            "sample_index": i,
            "fruit": args.fruit,
            "label": args.label,
            "png": png_path.name,
            "input_80x80": crop_path.name
        })
        print(f"Captured: {png_path.name} (80x80 input extracted)")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nCapture complete! {len(manifest)} valid hardware samples saved to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
