"""Shortcut baselines and brinjal-variety analysis.

1. `features`: logistic regression on NON-semantic image statistics (border
   colour, global brightness/contrast, coarse colour histogram) using exactly
   the same capture-group folds as scripts/sweep.py. Whatever this baseline
   achieves can be achieved without understanding the fruit. Image size is
   excluded because every image is resized before the CNN sees it.

2. `brinjal`: a heuristic purple/green tag for brinjal images (fraction of
   strongly purple pixels in the image centre). This tag is an ANALYSIS
   attribute only, never a training label; a contact sheet is written so the
   heuristic itself can be checked. If a sweep run is given, CNN condition
   accuracy is broken down by tag.

Usage:
  python scripts/shortcut_baselines.py features
  python scripts/shortcut_baselines.py brinjal --oof reports/sweep/main/80px_block_15_add/oof_predictions.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from audit_dataset import sheet  # noqa: E402
from sweep import group_folds  # noqa: E402

from fruitvision.config import load_config, resolve  # noqa: E402
from fruitvision.data.pipeline import load_split  # noqa: E402
from fruitvision.metrics import write_report  # noqa: E402

NON_SEMANTIC = ["border_r", "border_g", "border_b", "border_std", "brightness", "contrast",
                *[f"hist{i}" for i in range(12)]]


def run_features(cfg, out_root: Path) -> None:
    fruits, conds = cfg["fruits"], cfg["conditions"]
    splits = resolve(cfg["paths"]["splits_dir"])
    pool = pd.concat([load_split(splits, "train"), load_split(splits, "val")], ignore_index=True)
    stats = pd.read_csv(resolve(cfg["paths"]["reports_dir"]) / "dataset_audit" / "_combined" / "image_stats.csv")
    pool = pool.merge(stats[["path", *NON_SEMANTIC]], on="path", how="left")
    assert pool[NON_SEMANTIC].notna().all().all(), "image_stats.csv out of date: rerun audit_dataset.py"
    X = pool[NON_SEMANTIC].to_numpy()

    oof = []
    for fi, (tr, te) in enumerate(group_folds(pool, 3, cfg["seed"])):
        d = pool.iloc[te][["path", "source", "fruit", "condition", "group_id"]].copy()
        d["fold"] = fi
        for head in ("fruit", "condition"):
            clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced"))
            clf.fit(X[tr], pool[head].iloc[tr])
            d[f"pred_{head}"] = clf.predict(X[te])
        # Condition within each fruit, given the true fruit (like a per-fruit specialist).
        d["pred_condition_given_fruit"] = None
        for f in fruits:
            m_tr = (pool.fruit.iloc[tr] == f).to_numpy()
            m_te = (pool.fruit.iloc[te] == f).to_numpy()
            if m_tr.sum() and m_te.sum() and pool.condition.iloc[tr][m_tr].nunique() == 2:
                clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced"))
                clf.fit(X[tr][m_tr], pool.condition.iloc[tr][m_tr])
                d.loc[d.index[m_te], "pred_condition_given_fruit"] = clf.predict(X[te][m_te])
        oof.append(d)
    oof = pd.concat(oof)
    out = out_root / "baseline_features"
    s1 = write_report(oof, fruits, conds, out, "Non-semantic colour/background features — logistic regression")
    oof2 = oof.assign(pred_condition=oof.pred_condition_given_fruit)
    s2 = write_report(oof2, fruits, conds, out / "condition_given_fruit",
                      "Features baseline — per-fruit condition models")
    oof.to_csv(out / "oof_predictions.csv", index=False)
    (out / "summary.json").write_text(json.dumps({"joint": s1, "per_fruit_models": s2}, indent=2))
    print(json.dumps({"fruit_f1": s1["fruit_macro_f1"], "cond_f1": s1["condition_macro_f1"],
                      "cond_f1_by_fruit(per-fruit models)": {k: round(v["f1"], 3) for k, v in
                                                             s2["condition_f1_by_fruit"].items()},
                      "fruit_f1_by_source": s1["fruit_f1_by_source"]}, indent=2))


def purple_fraction(path: Path) -> float:
    with Image.open(path) as im:
        hsv = np.asarray(im.convert("RGB").resize((96, 96)).convert("HSV"), dtype=np.float32)
    c = hsv[24:72, 24:72]
    hue = c[..., 0] * 360 / 255
    purple = (hue >= 260) & (hue <= 345) & (c[..., 1] > 60) & (c[..., 2] > 40)
    return float(purple.mean())


def run_brinjal(cfg, out_root: Path, oof_path: str | None, thresh: float) -> None:
    raw = resolve(cfg["paths"]["raw_dir"])
    d = pd.read_csv(resolve(cfg["paths"]["interim_dir"]) / "manifest_clean.csv")
    b = d[d.fruit == "brinjal"].copy()
    b["purple_frac"] = [purple_fraction(raw / p) for p in b.path]
    b["variety_tag"] = np.where(b.purple_frac > thresh, "purple", "green")
    out = out_root / "brinjal_variety"
    out.mkdir(parents=True, exist_ok=True)
    b.to_csv(out / "brinjal_variety_tags.csv", index=False)
    table = b.groupby(["condition", "variety_tag"]).size().unstack(fill_value=0)
    print("Heuristic variety tag x condition:\n", table)
    for tag, g in b.groupby("variety_tag"):
        smp = g.sample(min(40, len(g)), random_state=0)
        sheet(list(smp.path), raw, out / f"tag_{tag}.jpg", f"brinjal heuristic tag = {tag} (n={len(g)})",
              labels=[f"{r.condition[:5]} {r.purple_frac:.2f}" for r in smp.itertuples()])
    res = {"tag_by_condition": table.to_dict(), "threshold": thresh}
    if oof_path:
        o = pd.read_csv(oof_path).merge(b[["path", "variety_tag"]], on="path")
        res["cnn_condition_accuracy_by_tag_and_condition"] = {
            f"{t}/{c}": {"acc": round(float((g.condition == g.pred_condition).mean()), 4), "n": len(g)}
            for (t, c), g in o.groupby(["variety_tag", "condition"])}
        print(json.dumps(res["cnn_condition_accuracy_by_tag_and_condition"], indent=2))
    (out / "summary.json").write_text(json.dumps(res, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["features", "brinjal"])
    ap.add_argument("--oof", help="sweep oof_predictions.csv (for brinjal breakdown)")
    ap.add_argument("--purple-threshold", type=float, default=0.15)
    args = ap.parse_args()
    cfg = load_config()
    out_root = resolve(cfg["paths"]["reports_dir"]) / "shortcut"
    if args.what == "features":
        run_features(cfg, out_root)
    else:
        run_brinjal(cfg, out_root, args.oof, args.purple_threshold)


if __name__ == "__main__":
    main()
