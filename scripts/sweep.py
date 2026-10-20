"""Architecture sweep with capture-group-aware cross-validation.

Pool = train + val splits (the test split is never touched here).
Folds: StratifiedGroupKFold on capture/duplicate groups (`group_id`), stratified
by source x fruit x condition, so no capture burst spans train and evaluation.
Inside each fold, an inner group-aware split of the TRAINING part is used for
early stopping; the held-out fold is only predicted once at the end.

Per config, writes reports/sweep/<tag>/<config>/:
  oof_predictions.csv, summary.json (pooled + per-fold), per_class.txt,
  confusion_matrices.png
and reports/sweep/<tag>/sweep_summary.csv.

`--mask-center` trains/evaluates on images whose central 60% is greyed out
(background-only baseline: how much can be learned WITHOUT the fruit?).

Usage:
  python scripts/sweep.py --configs 64:block_13_expand_relu 80:block_15_add ...
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.metrics import summarize, write_report
from fruitvision.training import balance_weights, cached_images, fit, labels, mask_center, predict


def group_folds(df: pd.DataFrame, k: int, seed: int):
    strat = df.source + "|" + df.fruit + "|" + df.condition
    return list(StratifiedGroupKFold(n_splits=k, shuffle=True, random_state=seed)
                .split(df, strat, groups=df.group_id))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--configs", nargs="+", required=True, help="size:cut_layer (cut 'none' = full)")
    ap.add_argument("--folds", type=int, default=3)
    ap.add_argument("--head-epochs", type=int, default=6)
    ap.add_argument("--ft-epochs", type=int, default=10)
    ap.add_argument("--mask-center", action="store_true")
    ap.add_argument("--max-folds", type=int, default=None, help="run only the first N folds (timing)")
    ap.add_argument("--tag", default="sweep")
    args = ap.parse_args()

    cfg = load_config(args.config)
    fruits, conds, seed = cfg["fruits"], cfg["conditions"], cfg["seed"]
    splits = resolve(cfg["paths"]["splits_dir"])
    pool = pd.concat([load_split(splits, "train"), load_split(splits, "val")], ignore_index=True)
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    cache_dir = resolve(cfg["paths"]["interim_dir"]) / "cache"
    out_root = resolve(cfg["paths"]["reports_dir"]) / "sweep" / args.tag
    folds = group_folds(pool, args.folds, seed)[: args.max_folds]

    rows = []
    for spec in args.configs:
        size_s, cut = spec.split(":")
        size, cut = int(size_s), (None if cut == "none" else cut)
        name = f"{size}px_{cut or 'full'}" + ("_maskcenter" if args.mask_center else "")
        x_all = cached_images(list(pool.path), raw_dir, size, cache_dir)
        if args.mask_center:
            x_all = mask_center(x_all)
        y_all = labels(pool, fruits, conds)
        oof, fold_metrics, t0 = [], [], time.time()

        for fi, (tr_idx, te_idx) in enumerate(folds):
            tr_df = pool.iloc[tr_idx]
            inner_tr, inner_va = group_folds(tr_df, 6, seed + fi)[0]
            itr, iva = tr_idx[inner_tr], tr_idx[inner_va]
            sel = lambda idx: {k: v[idx] for k, v in y_all.items()}  # noqa: E731
            model = fit(x_all[itr], sel(itr), balance_weights(pool.iloc[itr]),
                        x_all[iva], sel(iva), cfg, size, cut,
                        args.head_epochs, args.ft_epochs, seed + fi)
            p = predict(model, x_all[te_idx])
            fold_df = pool.iloc[te_idx][["path", "source", "fruit", "condition", "group_id"]].copy()
            fold_df["fold"] = fi
            fold_df["pred_fruit"] = [fruits[i] for i in p["fruit"].argmax(1)]
            fold_df["pred_condition"] = [conds[i] for i in p["condition"].argmax(1)]
            fold_df["p_fresh"] = p["condition"][:, conds.index("fresh")]
            oof.append(fold_df)
            fold_metrics.append(summarize(fold_df, fruits, conds))
            print(f"[{name}] fold {fi}: fruit F1 {fold_metrics[-1]['fruit_macro_f1']:.3f} "
                  f"condition F1 {fold_metrics[-1]['condition_macro_f1']:.3f} "
                  f"({time.time() - t0:.0f}s)", flush=True)

        oof = pd.concat(oof)
        out_dir = out_root / name
        pooled = write_report(oof, fruits, conds, out_dir, f"{name} — out-of-fold ({len(folds)} group folds)")
        oof.to_csv(out_dir / "oof_predictions.csv", index=False)
        (out_dir / "summary.json").write_text(json.dumps({"pooled": pooled, "folds": fold_metrics}, indent=2))

        def fstd(key, sub=None):
            v = [m[key][sub]["f1"] if sub else m[key] for m in fold_metrics if (sub is None or sub in m[key])]
            return float(np.std(v)) if len(v) > 1 else float("nan")

        row = {"config": name, "size": size, "cut": cut or "full", "minutes": round((time.time() - t0) / 60, 1),
               "fruit_f1": round(pooled["fruit_macro_f1"], 4), "fruit_f1_fold_std": round(fstd("fruit_macro_f1"), 4),
               "cond_f1": round(pooled["condition_macro_f1"], 4), "cond_f1_fold_std": round(fstd("condition_macro_f1"), 4)}
        for f, v in pooled["condition_f1_by_fruit"].items():
            row[f"cond_f1_{f}"] = round(v["f1"], 4)
        for s, v in pooled["condition_f1_by_source"].items():
            row[f"cond_f1_{s}"] = round(v["f1"], 4)
        for s, v in pooled["fruit_f1_by_source"].items():
            row[f"fruit_f1_{s}"] = round(v["f1"], 4)
        rows.append(row)
        pd.DataFrame(rows).to_csv(out_root / "sweep_summary.csv", index=False)

    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
