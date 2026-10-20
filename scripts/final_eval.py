"""Train the selected configuration and run the held-out and shortcut tests.

1. Train on the TRAIN split (early stopping on the group-separated VAL split),
   save models/runs/<run>/best.keras.
2. Evaluate once on the untouched TEST split: per-class P/R/F1, confusion
   matrices, F1 per fruit and per source.
3. Fruit-masked test: the same model on test images with the central 60%
   greyed out. Scores that stay high indicate background reliance.
4. Banana cross-source transfer: banana is the only fruit in both datasets.
   Train with all banana images of source A removed, then evaluate condition
   on ALL banana images of A (never seen; different photographer/background).
   Done in both directions.
5. Brinjal: test predictions broken down by the heuristic variety tag
   (run `shortcut_baselines.py brinjal` first).

Usage:
  python scripts/final_eval.py --size 80 --cut block_15_add --run-name final_80_b15
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.metrics import write_report
from fruitvision.training import balance_weights, cached_images, fit, labels, mask_center, predict


def pred_frame(df, p, fruits, conds):
    d = df[["path", "source", "fruit", "condition", "group_id"]].copy()
    d["pred_fruit"] = [fruits[i] for i in p["fruit"].argmax(1)]
    d["pred_condition"] = [conds[i] for i in p["condition"].argmax(1)]
    d["p_fresh"] = p["condition"][:, conds.index("fresh")]
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--cut", required=True, help="cut layer or 'none'")
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--head-epochs", type=int, default=8)
    ap.add_argument("--ft-epochs", type=int, default=15)
    ap.add_argument("--skip-cross-source", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    fruits, conds, seed = cfg["fruits"], cfg["conditions"], cfg["seed"]
    cut = None if args.cut == "none" else args.cut
    splits = resolve(cfg["paths"]["splits_dir"])
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    cache = resolve(cfg["paths"]["interim_dir"]) / "cache"
    out = resolve(cfg["paths"]["reports_dir"]) / "final" / args.run_name
    run_dir = resolve(cfg["paths"]["models_dir"]) / "runs" / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    tr, va, te = (load_split(splits, s) for s in ("train", "val", "test"))
    allx = pd.concat([tr, va, te], ignore_index=True)
    x_all = cached_images(list(allx.path), raw_dir, args.size, cache)
    n_tr, n_va = len(tr), len(va)
    x_tr, x_va, x_te = x_all[:n_tr], x_all[n_tr:n_tr + n_va], x_all[n_tr + n_va:]
    results = {"config": {"size": args.size, "cut": args.cut}}

    # 1-2. Main model, held-out test.
    model = fit(x_tr, labels(tr, fruits, conds), balance_weights(tr), x_va, labels(va, fruits, conds),
                cfg, args.size, cut, args.head_epochs, args.ft_epochs, seed, verbose=2)
    model.save(run_dir / "best.keras")
    (run_dir / "labels.json").write_text(json.dumps({"fruits": fruits, "conditions": conds}))
    out.mkdir(parents=True, exist_ok=True)
    test_pred = pred_frame(te, predict(model, x_te), fruits, conds)
    test_pred.to_csv(out / "test_predictions.csv", index=False)
    results["test"] = write_report(test_pred, fruits, conds, out / "test", f"{args.run_name} — held-out TEST")

    # 3. Fruit-masked test.
    masked = pred_frame(te, predict(model, mask_center(x_te)), fruits, conds)
    masked.to_csv(out / "test_maskcenter_predictions.csv", index=False)
    results["test_fruit_masked"] = write_report(masked, fruits, conds, out / "test_maskcenter",
                                                f"{args.run_name} — TEST with fruit region masked")

    # 5. Brinjal by heuristic variety tag.
    tags_f = resolve(cfg["paths"]["reports_dir"]) / "shortcut" / "brinjal_variety" / "brinjal_variety_tags.csv"
    if tags_f.exists():
        t = test_pred.merge(pd.read_csv(tags_f)[["path", "variety_tag"]], on="path")
        results["test_brinjal_by_variety_tag"] = {
            f"{v}/{c}": {"acc": round(float((g.condition == g.pred_condition).mean()), 4), "n": len(g)}
            for (v, c), g in t.groupby(["variety_tag", "condition"])}

    # 4. Banana cross-source transfer.
    if not args.skip_cross_source:
        results["banana_cross_source"] = {}
        idx_tr = np.arange(n_tr)
        idx_va = np.arange(n_tr, n_tr + n_va)
        for held in ("agrifreshnet", "fruitnet"):
            is_held = ((allx.fruit == "banana") & (allx.source == held)).to_numpy()
            itr, iva = idx_tr[~is_held[idx_tr]], idx_va[~is_held[idx_va]]
            sub_tr, sub_va = allx.iloc[itr], allx.iloc[iva]
            m2 = fit(x_all[itr], labels(sub_tr, fruits, conds), balance_weights(sub_tr),
                     x_all[iva], labels(sub_va, fruits, conds), cfg, args.size, cut,
                     args.head_epochs, args.ft_epochs, seed)
            ev = allx[is_held]
            d = pred_frame(ev, predict(m2, x_all[is_held]), fruits, conds)
            d.to_csv(out / f"banana_heldout_{held}_predictions.csv", index=False)
            s = write_report(d, fruits, conds, out / f"banana_heldout_{held}",
                             f"banana condition, trained WITHOUT {held} banana, evaluated on all {held} banana")
            results["banana_cross_source"][held] = {
                "n": s["n"], "condition_macro_f1": s["condition_macro_f1"],
                "condition_acc": s["condition_acc"], "fruit_acc": s["fruit_acc"]}

    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
