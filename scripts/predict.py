"""Run the image model on one image or a folder of images.

Output reports ONLY what the model was trained on: fruit type and visual
condition (fresh / spoiled), each with the model's softmax confidence.
The confidence is NOT a calibrated "freshness percentage" and the image
model does NOT detect pesticide residue.

Usage:
  python scripts/predict.py --model models/runs/<run>/best.keras --image path/to/img.jpg
  python scripts/predict.py --model models/tflite/<run>_int8.tflite --image folder/
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from fruitvision.config import load_config, resolve
from fruitvision.data.manifest import IMAGE_EXTS
from fruitvision.inference import load_image, load_predictor


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", required=True, help="image file or folder")
    args = ap.parse_args()

    cfg = load_config(args.config)
    fruits, conditions = cfg["fruits"], cfg["conditions"]
    pred = load_predictor(resolve(args.model), fruits, conditions)

    target = Path(args.image)
    files = ([p for p in sorted(target.iterdir()) if p.suffix.lower() in IMAGE_EXTS]
             if target.is_dir() else [target])

    for f in files:
        out = pred.predict(load_image(f, pred.input_size)[None])
        fp, cp = out["fruit"][0], out["condition"][0]
        fi, ci = int(np.argmax(fp)), int(np.argmax(cp))
        print(f"{f.name}")
        print(f"  Fruit:     {fruits[fi].capitalize()}  (confidence {fp[fi]:.0%})")
        print(f"  Condition: {conditions[ci].capitalize()}  (confidence {cp[ci]:.0%})")


if __name__ == "__main__":
    main()
