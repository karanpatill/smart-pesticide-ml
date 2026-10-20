"""Training-side shortcut-mitigation experiments (80 px, MobileNetV2-0.35, block_15).

Variants (preprocessing / augmentation):
  baseline   full image (same as the provisional baseline model)
  crop       image cropped to the fruit bbox from the rembg mask (train AND test)
  composite  full image at test; in training, the background is replaced with
             probability 0.7 by a random texture from another training image's
             corner (70%) or a random solid colour (30%), using the fruit mask
  crop_composite  crop (train AND test) + compositing in training, with masks
             cropped by the same box and textures taken from cropped images

Suites:
  main   train on TRAIN (early stop on VAL), evaluate on TEST + fruit-masked TEST
         + brinjal variety tags. (Not run for `baseline`: the provisional
         baseline results in reports/final/final_80_b15 are reused, untouched.)
  loso   leave-one-source-out: train on one source's TRAIN (early stop on its
         VAL), evaluate on ALL images of the other source (never seen).
  agri   AgriFreshNET-only benchmark: train/val/test restricted to AgriFreshNET.

Outputs: reports/experiments/<variant>/<suite...>/ (never writes elsewhere).

Usage:
  python scripts/experiments.py --variant crop --suites main loso agri
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.metrics import write_report
from fruitvision.training import (background_bank, balance_weights, cached_crops, cached_images,
                                  cached_mask_crops, cached_masks, fit, labels, mask_center, predict)

SIZE, CUT = 80, "block_15_add"


def pred_frame(df, p, fruits, conds):
    d = df[["path", "source", "fruit", "condition", "group_id"]].copy()
    d["pred_fruit"] = [fruits[i] for i in p["fruit"].argmax(1)]
    d["pred_condition"] = [conds[i] for i in p["condition"].argmax(1)]
    d["p_fresh"] = p["condition"][:, conds.index("fresh")]
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", choices=["baseline", "crop", "composite", "crop_composite"], required=True)
    ap.add_argument("--suites", nargs="+", choices=["main", "loso", "agri"], required=True)
    ap.add_argument("--head-epochs", type=int, default=8)
    ap.add_argument("--ft-epochs", type=int, default=15)
    ap.add_argument("--composite-p", type=float, default=0.7)
    args = ap.parse_args()

    cfg = load_config()
    fruits, conds, seed = cfg["fruits"], cfg["conditions"], cfg["seed"]
    splits = resolve(cfg["paths"]["splits_dir"])
    raw = resolve(cfg["paths"]["raw_dir"])
    interim = resolve(cfg["paths"]["interim_dir"])
    cache = interim / "cache"
    out_root = resolve(cfg["paths"]["reports_dir"]) / "experiments" / args.variant

    parts = {s: load_split(splits, s).assign(split=s) for s in ("train", "val", "test")}
    allx = pd.concat(parts.values(), ignore_index=True)

    meta = None
    if args.variant != "baseline":
        meta = pd.read_csv(interim / "masks" / "masks.csv")
        allx = allx.merge(meta, on="path", how="left", validate="1:1")
        assert allx["mask"].notna().all(), "run scripts/make_fruit_masks.py first"

    if args.variant in ("crop", "crop_composite"):
        # make_fruit_masks.py already stores the full-image box (0,0,1,1) when a mask failed.
        boxes = allx[["x0", "y0", "x1", "y1"]].to_numpy()
        x_all = cached_crops(list(allx.path), boxes, raw, SIZE, cache)
    else:
        x_all = cached_images(list(allx.path), raw, SIZE, cache)
    m_all = None
    if args.variant == "composite":
        m_all = cached_masks(list(allx["mask"]), interim / "masks", SIZE, cache)
    elif args.variant == "crop_composite":
        m_all = cached_mask_crops(list(allx["mask"]), boxes, interim / "masks", SIZE, cache)

    tags_f = resolve(cfg["paths"]["reports_dir"]) / "shortcut" / "brinjal_variety" / "brinjal_variety_tags.csv"
    tags = pd.read_csv(tags_f)[["path", "variety_tag"]] if tags_f.exists() else None

    def train(idx_tr, idx_va):
        comp = None
        if m_all is not None:
            comp = {"masks": m_all[idx_tr], "bank": background_bank(x_all[idx_tr], 1500, seed),
                    "p": args.composite_p}
        d_tr, d_va = allx.iloc[idx_tr], allx.iloc[idx_va]
        return fit(x_all[idx_tr], labels(d_tr, fruits, conds), balance_weights(d_tr),
                   x_all[idx_va], labels(d_va, fruits, conds), cfg, SIZE, CUT,
                   args.head_epochs, args.ft_epochs, seed, composite=comp)

    def evaluate(model, idx, out_dir, title, masked=False):
        x = mask_center(x_all[idx]) if masked else x_all[idx]
        d = pred_frame(allx.iloc[idx], predict(model, x), fruits, conds)
        out_dir.mkdir(parents=True, exist_ok=True)
        d.to_csv(out_dir / "predictions.csv", index=False)
        s = write_report(d, fruits, conds, out_dir, title)
        s["spoiled_recall"] = float(((d.condition == "spoiled") & (d.pred_condition == "spoiled")).sum()
                                    / max(1, (d.condition == "spoiled").sum()))
        if tags is not None:
            t = d.merge(tags, on="path")
            s["brinjal_by_variety_tag"] = {
                f"{v}/{c}": {"acc": round(float((g.condition == g.pred_condition).mean()), 4), "n": len(g)}
                for (v, c), g in t.groupby(["variety_tag", "condition"])}
        if "banana" in set(d.fruit):
            b = d[d.fruit == "banana"]
            s["banana_fruit_recall_by_source"] = {k: round(float((g.pred_fruit == "banana").mean()), 4)
                                                  for k, g in b.groupby("source")}
        return s

    sel = lambda m: np.flatnonzero(m.to_numpy())  # noqa: E731
    results = {"variant": args.variant, "size": SIZE, "cut": CUT}

    if "main" in args.suites:
        if args.variant == "baseline":
            print("main/baseline: reusing reports/final/final_80_b15 (untouched)")
        else:
            model = train(sel(allx.split == "train"), sel(allx.split == "val"))
            te = sel(allx.split == "test")
            results["test"] = evaluate(model, te, out_root / "main" / "test", f"{args.variant} — TEST")
            results["test_fruit_masked"] = evaluate(model, te, out_root / "main" / "test_maskcenter",
                                                    f"{args.variant} — TEST, fruit region masked", masked=True)

    if "loso" in args.suites:
        results["loso"] = {}
        for held in ("fruitnet", "agrifreshnet"):
            keep = allx.source != held
            model = train(sel(keep & (allx.split == "train")), sel(keep & (allx.split == "val")))
            results["loso"][held] = evaluate(
                model, sel(allx.source == held), out_root / f"loso_heldout_{held}",
                f"{args.variant} — trained WITHOUT {held}, evaluated on all {held} images")

    if "agri" in args.suites:
        a = allx.source == "agrifreshnet"
        model = train(sel(a & (allx.split == "train")), sel(a & (allx.split == "val")))
        te = sel(a & (allx.split == "test"))
        results["agri_only"] = evaluate(model, te, out_root / "agri_only" / "test",
                                        f"{args.variant} — AgriFreshNET-only, AgriFreshNET TEST")
        results["agri_only_fruit_masked"] = evaluate(
            model, te, out_root / "agri_only" / "test_maskcenter",
            f"{args.variant} — AgriFreshNET-only, fruit region masked", masked=True)

    out_root.mkdir(parents=True, exist_ok=True)
    f = out_root / f"results_{'_'.join(args.suites)}.json"
    f.write_text(json.dumps(results, indent=2))
    print(f"wrote {f}")


if __name__ == "__main__":
    main()
