"""Evaluate a trained model (Keras or TFLite) on a held-out split.

Writes to reports/eval/<tag>/:
  metrics.json                 accuracy + macro-F1 per head, overall and per source
  <head>_report.txt            per-class precision / recall / F1
  <head>_confusion.png         confusion matrix
  predictions.csv              per-image predictions (for error analysis)

Usage:
  python scripts/evaluate.py --run <run-name>                 # best.keras
  python scripts/evaluate.py --model models/tflite/x.tflite --tag int8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score,
                             classification_report, confusion_matrix, f1_score)
from tqdm import tqdm

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.inference import load_image, load_predictor


def head_metrics(y_true, y_pred) -> dict:
    return {
        "n": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="run name under models/runs (uses best.keras)")
    g.add_argument("--model", help="path to .keras or .tflite model")
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--tag", help="report folder name (default: run name or model stem)")
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()

    cfg = load_config(args.config)
    fruits, conditions = cfg["fruits"], cfg["conditions"]
    model_path = (resolve(cfg["paths"]["models_dir"]) / "runs" / args.run / "best.keras"
                  if args.run else resolve(args.model))
    tag = args.tag or args.run or Path(model_path).stem
    out_dir = resolve(cfg["paths"]["reports_dir"]) / "eval" / f"{tag}_{args.split}"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_split(resolve(cfg["paths"]["splits_dir"]), args.split)
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    pred = load_predictor(model_path, fruits, conditions)

    probs: dict[str, list] = {"fruit": [], "condition": []}
    for i in tqdm(range(0, len(df), args.batch), desc="predict"):
        batch = np.stack([load_image(raw_dir / p, pred.input_size) for p in df["path"][i:i + args.batch]])
        out = pred.predict(batch)
        for k in probs:
            probs[k].append(out[k])

    heads = {"fruit": fruits, "condition": conditions}
    metrics: dict = {"model": str(model_path), "split": args.split}
    for head, names in heads.items():
        p = np.concatenate(probs[head])
        y_true = df[head].map({n: i for i, n in enumerate(names)}).to_numpy()
        y_pred = p.argmax(1)
        df[f"pred_{head}"] = [names[i] for i in y_pred]
        df[f"conf_{head}"] = p.max(1)

        metrics[head] = head_metrics(y_true, y_pred)
        metrics[head]["per_source"] = {
            s: head_metrics(y_true[m], y_pred[m]) for s, m in
            ((s, (df["source"] == s).to_numpy()) for s in df["source"].unique())
        }
        labels = list(range(len(names)))
        (out_dir / f"{head}_report.txt").write_text(classification_report(
            y_true, y_pred, labels=labels, target_names=names, zero_division=0, digits=4))
        cm = confusion_matrix(y_true, y_pred, labels=labels)
        fig, ax = plt.subplots(figsize=(1.2 * len(names) + 3, 1.2 * len(names) + 2))
        ConfusionMatrixDisplay(cm, display_labels=names).plot(ax=ax, colorbar=False, cmap="Blues")
        ax.set_title(f"{head} — {tag} ({args.split})")
        fig.tight_layout()
        fig.savefig(out_dir / f"{head}_confusion.png", dpi=120)
        plt.close(fig)

    # Condition accuracy broken down by fruit (are some fruits much harder?).
    metrics["condition_by_fruit"] = {
        f: head_metrics(g["condition"], g["pred_condition"]) for f, g in df.groupby("fruit")
    }

    df.to_csv(out_dir / "predictions.csv", index=False)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: v for k, v in metrics.items() if k != "condition_by_fruit"}, indent=2))
    print(f"\nReports in {out_dir}")


if __name__ == "__main__":
    main()
