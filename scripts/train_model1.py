"""Produce the locked Model 1 artifacts.

Model 1 (approved 2026-10-09): MobileNetV2 alpha 0.35, 80x80 input, backbone cut
at block_15_add, full-frame inference, trained with background compositing.
The recipe is IDENTICAL to `scripts/experiments.py --variant composite`
(suite `main`): same splits, caches, epochs, seed, compositing settings.

Artifacts -> models/model1/   Reports -> reports/model1/
See docs/MODEL1.md for the full list.

Usage:
  python scripts/train_model1.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import tensorflow as tf

from fruitvision.config import PROJECT_ROOT, load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.metrics import write_report
from fruitvision.training import (background_bank, balance_weights, cached_images, cached_masks, fit,
                                  labels, predict)

# ---- Locked Model 1 recipe (do not change; see docs/MODEL1.md) ----
SIZE, CUT = 80, "block_15_add"
HEAD_EPOCHS, FT_EPOCHS = 8, 15
COMPOSITE_P, BANK_SIZE = 0.7, 1500


def sha256(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main() -> None:
    cfg = load_config()
    fruits, conds, seed = cfg["fruits"], cfg["conditions"], cfg["seed"]
    splits = resolve(cfg["paths"]["splits_dir"])
    raw, interim = resolve(cfg["paths"]["raw_dir"]), resolve(cfg["paths"]["interim_dir"])
    cache = interim / "cache"
    art = resolve(cfg["paths"]["models_dir"]) / "model1"
    rep = resolve(cfg["paths"]["reports_dir"]) / "model1"
    if (art / "model1_final.keras").exists():
        raise SystemExit(f"{art} already contains Model 1 artifacts; refusing to overwrite.")
    art.mkdir(parents=True, exist_ok=True)
    rep.mkdir(parents=True, exist_ok=True)

    # Same row order as experiments.py so the cached arrays are reused exactly.
    parts = {s: load_split(splits, s).assign(split=s) for s in ("train", "val", "test")}
    allx = pd.concat(parts.values(), ignore_index=True)
    allx = allx.merge(pd.read_csv(interim / "masks" / "masks.csv"), on="path", how="left", validate="1:1")
    x_all = cached_images(list(allx.path), raw, SIZE, cache)
    m_all = cached_masks(list(allx["mask"]), interim / "masks", SIZE, cache)

    idx = {s: np.flatnonzero((allx.split == s).to_numpy()) for s in ("train", "val", "test")}
    d_tr, d_va = allx.iloc[idx["train"]], allx.iloc[idx["val"]]
    composite = {"masks": m_all[idx["train"]], "bank": background_bank(x_all[idx["train"]], BANK_SIZE, seed),
                 "p": COMPOSITE_P}

    ckpt = tf.keras.callbacks.ModelCheckpoint(str(art / "best_checkpoint.keras"),
                                              monitor="val_loss", save_best_only=True)
    model = fit(x_all[idx["train"]], labels(d_tr, fruits, conds), balance_weights(d_tr),
                x_all[idx["val"]], labels(d_va, fruits, conds), cfg, SIZE, CUT,
                HEAD_EPOCHS, FT_EPOCHS, seed, verbose=2, composite=composite, callbacks=[ckpt])

    # 1-2. Final model (best val-loss weights of the fine-tuning stage) + weights.
    model.save(art / "model1_final.keras")
    model.save_weights(art / "model1_final.weights.h5")

    # 8. Per-epoch training/validation curves.
    hist = pd.concat([pd.DataFrame(h).assign(stage=i + 1, epoch_in_stage=np.arange(1, len(h["loss"]) + 1))
                      for i, h in enumerate(model.stage_histories)], ignore_index=True)
    hist.to_csv(art / "training_history.csv", index=False)

    # 9. Validation (and held-out test) metrics for BOTH saved models.
    metrics = {}
    for name, mdl in (("final", model), ("best_checkpoint", tf.keras.models.load_model(art / "best_checkpoint.keras"))):
        for split in ("val", "test"):
            d = allx.iloc[idx[split]][["path", "source", "fruit", "condition"]].copy()
            p = predict(mdl, x_all[idx[split]])
            d["pred_fruit"] = [fruits[i] for i in p["fruit"].argmax(1)]
            d["pred_condition"] = [conds[i] for i in p["condition"].argmax(1)]
            for i, f in enumerate(fruits):
                d[f"p_fruit_{f}"] = p["fruit"][:, i]
            for i, c in enumerate(conds):
                d[f"p_condition_{c}"] = p["condition"][:, i]
            out = rep / name / split
            s = write_report(d, fruits, conds, out, f"Model 1 ({name}) — {split.upper()}")
            s["spoiled_recall"] = float(((d.condition == "spoiled") & (d.pred_condition == "spoiled")).sum()
                                        / max(1, (d.condition == "spoiled").sum()))
            d.to_csv(out / "predictions.csv", index=False)
            metrics[f"{name}/{split}"] = s
    last = {k: float(v[-1]) for k, v in model.stage_histories[-1].items()}
    metrics["final/last_epoch_train_history"] = last
    (art / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # 3. Training configuration (exact recipe + provenance).
    (art / "training_config.json").write_text(json.dumps({
        "model_name": "Model 1",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recipe": {"input_size": SIZE, "backbone": "MobileNetV2", "alpha": cfg["model"]["alpha"],
                   "cut_layer": CUT, "weights_init": "imagenet", "dropout": cfg["model"]["dropout"],
                   "head_units": cfg["model"]["head_units"], "loss_weights": cfg["model"]["loss_weights"],
                   "head_epochs": HEAD_EPOCHS, "finetune_epochs": FT_EPOCHS,
                   "head_lr": cfg["train"]["head_lr"], "finetune_lr": cfg["train"]["finetune_lr"],
                   "finetune_unfreeze_layers": cfg["train"]["finetune_unfreeze_layers"],
                   "batchnorm_frozen": True, "batch_size": cfg["train"]["batch_size"],
                   "early_stopping": {"monitor": "val_loss",
                                      "patience": cfg["train"]["early_stopping_patience"],
                                      "restore_best_weights": True},
                   "optimizer": "Adam", "class_balancing": "sample weights N/(K*n_cell) over fruit x condition",
                   "augment": cfg["augment"],
                   "background_compositing": {"p": COMPOSITE_P, "bank_size": BANK_SIZE,
                                              "bank_source": "corner patches (35%) of TRAIN images",
                                              "texture_vs_solid": "70% texture / 30% random solid colour",
                                              "masks": "rembg u2netp, data/interim/masks (training only)"},
                   "seed": seed},
        "data": {"train_images": len(idx["train"]), "val_images": len(idx["val"]), "test_images": len(idx["test"]),
                 "split_sha256": {s: sha256(splits / f"{s}.csv") for s in ("train", "val", "test")},
                 "sources": ["fruitnet (CC BY 4.0)", "agrifreshnet (CC BY 4.0)"]},
        "environment": {"python": sys.version.split()[0], "tensorflow": tf.__version__,
                        "keras": tf.keras.__version__, "numpy": np.__version__,
                        "platform": platform.platform()},
        "project_config_snapshot": cfg,
    }, indent=2))

    # 4. Labels.
    (art / "labels.json").write_text(json.dumps({
        "outputs": {"fruit": {str(i): f for i, f in enumerate(fruits)},
                    "condition": {str(i): c for i, c in enumerate(conds)}},
        "note": "condition is a binary visual label (fresh vs spoiled/rotten). "
                "Model 1 does not detect pesticide residue and does not output a freshness percentage."},
        indent=2))

    # 5-6. Preprocessing + normalisation.
    (art / "preprocessing.json").write_text(json.dumps({
        "input": {"shape": [1, SIZE, SIZE, 3], "channel_order": "RGB", "dtype": "float32",
                  "value_range": [0, 255], "layout": "NHWC"},
        "resize": {"method": "aspect-preserving bilinear resize with antialias so the longer side = "
                             f"{SIZE}, then centre crop/zero-pad to {SIZE}x{SIZE}",
                   "tf_ops": ["tf.image.resize(img, [S, S], preserve_aspect_ratio=True, antialias=True)",
                              "tf.image.resize_with_crop_or_pad(img, S, S)"],
                   "reference_impl": "src/fruitvision/data/pipeline.py: decode_and_resize / resize_image"},
        "full_frame": True, "cropping_or_segmentation": "none at inference",
        "normalization": {"location": "inside the model (layer 'normalize')",
                          "formula": "x_norm = x / 127.5 - 1.0", "scale": 1 / 127.5, "offset": -1.0,
                          "caller_must_not_normalize": True}}, indent=2))

    # 7. Architecture.
    (art / "model_architecture.json").write_text(model.to_json(indent=2))
    lines = []
    model.summary(print_fn=lambda s, **k: lines.append(s))
    (art / "model_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    (art / "model_info.json").write_text(json.dumps({
        "total_params": int(model.count_params()),
        "trainable_params_at_end": int(sum(np.prod(w.shape) for w in model.trainable_weights)),
        "inputs": {"image": [None, SIZE, SIZE, 3]},
        "outputs": {"fruit": [None, len(fruits)], "condition": [None, len(conds)]},
        "output_activation": "softmax"}, indent=2))

    print(json.dumps({k: {m: round(v[m], 4) for m in ("fruit_macro_f1", "condition_macro_f1", "spoiled_recall")}
                      for k, v in metrics.items() if "/" in k and "history" not in k}, indent=2))
    print(f"Artifacts: {art.relative_to(PROJECT_ROOT)}  Reports: {rep.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
