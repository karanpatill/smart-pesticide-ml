"""Evaluation metrics broken down by fruit, source and class.

Every function takes a predictions DataFrame with columns
  fruit, condition, source, pred_fruit, pred_condition
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (ConfusionMatrixDisplay, confusion_matrix, f1_score,
                             precision_recall_fscore_support)


def _f1(y, p, labels):
    return float(f1_score(y, p, labels=labels, average="macro", zero_division=0))


def per_class_table(y, p, labels) -> pd.DataFrame:
    pr, rc, f1, n = precision_recall_fscore_support(y, p, labels=labels, zero_division=0)
    return pd.DataFrame({"precision": pr, "recall": rc, "f1": f1, "support": n}, index=labels).round(4)


def summarize(df: pd.DataFrame, fruits: list[str], conditions: list[str]) -> dict:
    """Headline numbers: fruit macro-F1, condition macro-F1 overall / per fruit /
    per source / per source x fruit, plus image counts."""
    out = {
        "n": int(len(df)),
        "fruit_macro_f1": _f1(df.fruit, df.pred_fruit, fruits),
        "fruit_acc": float((df.fruit == df.pred_fruit).mean()),
        "condition_macro_f1": _f1(df.condition, df.pred_condition, conditions),
        "condition_acc": float((df.condition == df.pred_condition).mean()),
        "condition_f1_by_fruit": {},
        "fruit_f1_by_source": {},
        "condition_f1_by_source": {},
        "condition_f1_by_source_fruit": {},
    }
    for f, g in df.groupby("fruit"):
        out["condition_f1_by_fruit"][f] = {"f1": _f1(g.condition, g.pred_condition, conditions), "n": len(g)}
    for s, g in df.groupby("source"):
        present = [f for f in fruits if f in set(g.fruit)]
        out["fruit_f1_by_source"][s] = {"f1": _f1(g.fruit, g.pred_fruit, present), "n": len(g)}
        out["condition_f1_by_source"][s] = {"f1": _f1(g.condition, g.pred_condition, conditions), "n": len(g)}
    for (s, f), g in df.groupby(["source", "fruit"]):
        out["condition_f1_by_source_fruit"][f"{s}/{f}"] = {
            "f1": _f1(g.condition, g.pred_condition, conditions), "n": len(g)}
    return out


def write_report(df: pd.DataFrame, fruits, conditions, out_dir: Path, title: str) -> dict:
    """Per-class P/R/F1 tables and confusion matrices (overall and per fruit)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]
    lines += ["## Fruit head (all)", per_class_table(df.fruit, df.pred_fruit, fruits).to_string(), ""]
    lines += ["## Condition head (all)", per_class_table(df.condition, df.pred_condition, conditions).to_string(), ""]
    for s, g in df.groupby("source"):
        lines += [f"## Condition head — source {s}",
                  per_class_table(g.condition, g.pred_condition, conditions).to_string(), ""]
    for f, g in df.groupby("fruit"):
        lines += [f"## Condition head — fruit {f}",
                  per_class_table(g.condition, g.pred_condition, conditions).to_string(), ""]
    (out_dir / "per_class.txt").write_text("\n".join(lines), encoding="utf-8")

    panels = [("fruit (all)", df.fruit, df.pred_fruit, fruits),
              ("condition (all)", df.condition, df.pred_condition, conditions)]
    panels += [(f"condition — {f}", g.condition, g.pred_condition, conditions) for f, g in df.groupby("fruit")]
    panels += [(f"condition — {s}", g.condition, g.pred_condition, conditions) for s, g in df.groupby("source")]
    cols = 3
    rows = int(np.ceil(len(panels) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4.3 * rows))
    for ax, (name, y, p, labs) in zip(axes.flat, panels):
        cm = confusion_matrix(y, p, labels=labs)
        ConfusionMatrixDisplay(cm, display_labels=labs).plot(ax=ax, colorbar=False, cmap="Blues",
                                                             xticks_rotation=45)
        ax.set_title(name)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis("off")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrices.png", dpi=110)
    plt.close(fig)
    return summarize(df, fruits, conditions)
