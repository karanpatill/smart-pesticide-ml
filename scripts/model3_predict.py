"""Model 1 + Model 3 inference with the post-processing / consistency layer.

Self-contained: needs TensorFlow/numpy and models/model3/ (model3_combined.keras,
labels.json, shelf_life_ranges.json, postprocess_config.json). The rules live in
src/fruitvision/postprocess.py; this script imports them from the project source
tree located next to it (no installed package required).

Preprocessing = Model 1's (full frame, aspect-preserving resize + centre crop to
80x80, RGB 0..255). No model is retrained or modified here.

Usage:
  python scripts/model3_predict.py IMAGE [IMAGE ...]            # final JSON records
  python scripts/model3_predict.py --no-raw IMAGE ...           # omit the raw block
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fruitvision.postprocess import FRUITS, postprocess  # noqa: E402

ART = ROOT / "models" / "model3"
CONDITIONS = ["fresh", "spoiled"]


def preprocess(path, size=80):
    img = tf.io.decode_image(tf.io.read_file(str(path)), channels=3, expand_animations=False)
    img = tf.image.resize(img, [size, size], preserve_aspect_ratio=True, antialias=True)
    return tf.cast(tf.image.resize_with_crop_or_pad(img, size, size), tf.float32).numpy()


def load(model_dir: Path):
    model = tf.keras.models.load_model(model_dir / "model3_combined.keras")
    labels = json.loads((model_dir / "labels.json").read_text())
    shelf = json.loads((model_dir / "shelf_life_ranges.json").read_text())
    cfg = json.loads((model_dir / "postprocess_config.json").read_text())
    return model, labels, shelf, cfg


def raw_outputs(o: dict, i: int, labels: dict) -> dict:
    return {"fruit": dict(zip(FRUITS, map(float, o["fruit"][i]))),
            "condition": dict(zip(CONDITIONS, map(float, o["condition"][i]))),
            "heads": {h: {labels[h][str(k)]: float(v) for k, v in enumerate(o[h][i])} for h in labels}}


def predict_arrays(model, labels, shelf, cfg, x: np.ndarray) -> list[dict]:
    o = {k: np.asarray(v) for k, v in model.predict(x, verbose=0).items()}
    return [postprocess(raw_outputs(o, i, labels), cfg, shelf) for i in range(len(x))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--model-dir", type=Path, default=ART)
    ap.add_argument("--no-raw", action="store_true")
    args = ap.parse_args()
    model, labels, shelf, cfg = load(args.model_dir)
    recs = predict_arrays(model, labels, shelf, cfg, np.stack([preprocess(p) for p in args.images]))
    out = []
    for p, r in zip(args.images, recs):
        if args.no_raw:
            r = {k: v for k, v in r.items() if k != "raw"}
        out.append({"image": str(p), **r})
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
