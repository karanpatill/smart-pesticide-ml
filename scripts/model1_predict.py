"""Model 1 inference: fruit class + fresh/spoiled condition with confidences.

Self-contained: needs only TensorFlow/numpy and the artifact folder
(models/model1/). Preprocessing follows models/model1/preprocessing.json:
full frame, aspect-preserving resize + centre crop/pad to 80x80, RGB 0..255.
Normalisation is inside the model, so it is NOT applied here.

Confidences are the model's softmax probabilities. They are not a freshness
percentage, and the image model does not detect pesticide residue.

Usage:
  python scripts/model1_predict.py IMAGE [IMAGE ...]
  python scripts/model1_predict.py --json IMAGE ...
  python scripts/model1_predict.py --model-dir models/model1 --weights best_checkpoint.keras IMAGE
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "models" / "model1"


def load(model_dir: Path, weights: str):
    model = tf.keras.models.load_model(model_dir / weights)
    lab = json.loads((model_dir / "labels.json").read_text())["outputs"]
    pre = json.loads((model_dir / "preprocessing.json").read_text())
    fruits = [lab["fruit"][str(i)] for i in range(len(lab["fruit"]))]
    conds = [lab["condition"][str(i)] for i in range(len(lab["condition"]))]
    return model, fruits, conds, int(pre["input"]["shape"][1])


def preprocess(path: Path, size: int) -> np.ndarray:
    img = tf.io.decode_image(tf.io.read_file(str(path)), channels=3, expand_animations=False)
    img = tf.image.resize(img, [size, size], preserve_aspect_ratio=True, antialias=True)
    img = tf.image.resize_with_crop_or_pad(img, size, size)
    return tf.cast(img, tf.float32).numpy()  # RGB, 0..255


def predict(model, fruits, conds, size, paths: list[Path]) -> list[dict]:
    x = np.stack([preprocess(p, size) for p in paths])
    out = model.predict(x, verbose=0)
    results = []
    for i, p in enumerate(paths):
        fp, cp = out["fruit"][i], out["condition"][i]
        results.append({
            "image": str(p),
            "fruit": fruits[int(fp.argmax())], "fruit_confidence": round(float(fp.max()), 4),
            "condition": conds[int(cp.argmax())], "condition_confidence": round(float(cp.max()), 4),
            "fruit_probabilities": {f: round(float(v), 4) for f, v in zip(fruits, fp)},
            "condition_probabilities": {c: round(float(v), 4) for c, v in zip(conds, cp)},
        })
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--model-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--weights", default="model1_final.keras")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    model, fruits, conds, size = load(args.model_dir, args.weights)
    res = predict(model, fruits, conds, size, args.images)
    if args.json:
        print(json.dumps(res, indent=2))
        return
    for r in res:
        print(r["image"])
        print(f"  Fruit:     {r['fruit'].capitalize():8s} (confidence {r['fruit_confidence']:.1%})")
        print(f"  Condition: {r['condition'].capitalize():8s} (confidence {r['condition_confidence']:.1%})")


if __name__ == "__main__":
    main()
