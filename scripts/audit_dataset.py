"""Post-mapping dataset audit (run after prepare_dataset.py).

Produces, under reports/dataset_audit/_combined/:
  counts.csv / counts.txt      images per source x fruit x condition x split
  sheets/<fruit>__<cond>__<source>.jpg   random sample sheets for visual label checks
  sheets/*.txt                 the file paths shown on each sheet, in order
  near_dups/*.jpg              example near-duplicate pairs (within/cross class/source)
  near_duplicates.csv          every duplicate group with size > 1
  image_stats.csv              per-image size, aspect, border colour, brightness
  bias_probe.json              how well TRIVIAL features predict the labels

Bias probe: a logistic regression on hand-made, non-semantic features
(image size, aspect ratio, border colour statistics, coarse colour histogram)
evaluated with group-aware cross-validation. If such features predict the
condition or the source far above chance, the CNN can take the same shortcut.
This is a data diagnostic; it is NOT the fruit model.

Usage:
  python scripts/audit_dataset.py
"""

from __future__ import annotations

import argparse
import json
import random

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageOps
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from tqdm import tqdm

from fruitvision.config import load_config, resolve


def sheet(paths, raw_dir, out, title, thumb=112, cols=8, labels=None):
    rows = (len(paths) + cols - 1) // cols
    head = 22
    img = Image.new("RGB", (cols * thumb, rows * (thumb + (14 if labels else 0)) + head), "white")
    d = ImageDraw.Draw(img)
    d.text((4, 4), title, fill="black")
    cell_h = thumb + (14 if labels else 0)
    for i, p in enumerate(paths):
        try:
            with Image.open(raw_dir / p) as im:
                t = ImageOps.fit(im.convert("RGB"), (thumb, thumb))
        except OSError:
            continue
        x, y = (i % cols) * thumb, head + (i // cols) * cell_h
        img.paste(t, (x, y))
        d.text((x + 2, y + 2), str(i), fill="yellow")
        if labels:
            d.text((x + 2, y + thumb), labels[i][:18], fill="black")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=88)


def image_features(path, border=6):
    with Image.open(path) as im:
        w, h = im.size
        small = im.convert("RGB").resize((64, 64))
    a = np.asarray(small, dtype=np.float32) / 255.0
    b = np.concatenate([a[:border].reshape(-1, 3), a[-border:].reshape(-1, 3),
                        a[:, :border].reshape(-1, 3), a[:, -border:].reshape(-1, 3)])
    hist = np.concatenate([np.histogram(a[..., c], bins=4, range=(0, 1))[0] / a[..., c].size
                           for c in range(3)])
    return {
        "width": w, "height": h, "aspect": w / h,
        "border_r": b[:, 0].mean(), "border_g": b[:, 1].mean(), "border_b": b[:, 2].mean(),
        "border_std": b.std(), "brightness": a.mean(), "contrast": a.std(),
        **{f"hist{i}": v for i, v in enumerate(hist)},
    }


def probe(X, y, groups, seed):
    """Group-aware 5-fold CV accuracy of a linear model vs. majority baseline."""
    y = np.asarray(y)
    n_splits = min(5, pd.Series(y).value_counts().min())
    if len(np.unique(y)) < 2 or n_splits < 2:
        return None
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    pred = cross_val_predict(clf, X, y, groups=groups, cv=cv)
    return {
        "n": int(len(y)),
        "accuracy": round(float((pred == y).mean()), 4),
        "majority_baseline": round(float(pd.Series(y).value_counts(normalize=True).iloc[0]), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--per-sheet", type=int, default=48)
    args = ap.parse_args()

    cfg = load_config(args.config)
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    interim = resolve(cfg["paths"]["interim_dir"])
    out = resolve(cfg["paths"]["reports_dir"]) / "dataset_audit" / "_combined"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(cfg["seed"])

    df = pd.read_csv(interim / "manifest_clean.csv")
    full = pd.read_csv(interim / "manifest_full.csv")

    # 1. Counts
    counts = df.groupby(["source", "fruit", "condition", "split"]).size().unstack(fill_value=0)
    counts["total"] = counts.sum(axis=1)
    counts.to_csv(out / "counts.csv")
    (out / "counts.txt").write_text(counts.to_string(), encoding="utf-8")

    # 2. Sample sheets per fruit x condition x source
    for (fruit, cond, src), g in df.groupby(["fruit", "condition", "source"]):
        paths = rng.sample(list(g["path"]), min(args.per_sheet, len(g)))
        name = f"{fruit}__{cond}__{src}"
        sheet(paths, raw_dir, out / "sheets" / f"{name}.jpg",
              f"{fruit} / {cond} / {src}  (n={len(g)}, showing {len(paths)})")
        (out / "sheets" / f"{name}.txt").write_text("\n".join(paths), encoding="utf-8")

    # 3. Near-duplicate groups (computed on ALL usable images before exact-dup removal)
    groups = df[df.group_size > 1].sort_values(["group_id", "path"])
    groups.to_csv(out / "near_duplicates.csv", index=False)
    kinds = {}
    for gid, g in groups.groupby("group_id"):
        kind = ("cross_source" if g.source.nunique() > 1 else
                "cross_class" if (g.fruit + g.condition).nunique() > 1 else "same_class")
        kinds.setdefault(kind, []).append(gid)
    for kind, gids in kinds.items():
        pick = rng.sample(gids, min(12, len(gids)))
        paths, labels = [], []
        for gid in pick:
            g = groups[groups.group_id == gid].head(4)
            paths += list(g.path)
            labels += [f"g{gid} {r.fruit[:3]}/{r.condition[:5]}" for r in g.itertuples()]
        sheet(paths, raw_dir, out / "near_dups" / f"{kind}.jpg",
              f"near-duplicate groups: {kind} ({len(gids)} groups)", cols=8, labels=labels)

    # 4. Per-image statistics
    feats = [image_features(raw_dir / p) for p in tqdm(df["path"], desc="features")]
    stats = pd.concat([df[["path", "source", "fruit", "condition", "group_id"]].reset_index(drop=True),
                       pd.DataFrame(feats)], axis=1)
    stats.to_csv(out / "image_stats.csv", index=False)
    summary_stats = stats.groupby(["source", "fruit", "condition"])[
        ["width", "height", "aspect", "border_r", "border_g", "border_b", "border_std", "brightness"]
    ].agg(["mean", "std"]).round(3)
    summary_stats.to_csv(out / "image_stats_by_class.csv")

    # 5. Shortcut / bias probe on trivial features
    fcols = [c for c in stats.columns if c not in ("path", "source", "fruit", "condition", "group_id")]
    X = stats[fcols].to_numpy()
    res = {"features": fcols, "condition_within_fruit": {}, "source": {}}
    for fruit, idx in stats.groupby("fruit").groups.items():
        s = stats.loc[idx]
        res["condition_within_fruit"][fruit] = probe(X[idx], s.condition, s.group_id, cfg["seed"])
    res["fruit_all"] = probe(X, stats.fruit, stats.group_id, cfg["seed"])
    res["source_all"] = probe(X, stats.source, stats.group_id, cfg["seed"])
    for fruit, idx in stats.groupby("fruit").groups.items():
        s = stats.loc[idx]
        if s.source.nunique() > 1:
            res["source"][fruit] = probe(X[idx], s.source, s.group_id, cfg["seed"])
    (out / "bias_probe.json").write_text(json.dumps(res, indent=2))

    status = full.groupby(["source", "status"]).size().unstack(fill_value=0)
    print("Status per source (full manifest):\n", status, "\n")
    print("Counts:\n", counts, "\n")
    print("Duplicate group kinds:", {k: len(v) for k, v in kinds.items()})
    print("Bias probe:", json.dumps({k: v for k, v in res.items() if k != "features"}, indent=2))
    print(f"\nAudit written to {out}")


if __name__ == "__main__":
    main()
