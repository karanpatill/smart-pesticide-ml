"""Two-stage transfer learning of the MobileNetV2 fruit/condition model.

Stage 1 trains only the heads on a frozen ImageNet backbone.
Stage 2 fine-tunes the last N backbone layers at a lower learning rate.
The best weights (lowest val loss) are saved as a .keras file.

Usage:
  python scripts/train.py [--config configs/config.yaml] [--run-name NAME]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import tensorflow as tf

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split, make_dataset
from fruitvision.models.mobilenet import build_model, compile_model, unfreeze_top
from fruitvision.utils.seed import set_global_seed


def callbacks(ckpt_cb, log_dir, patience):
    # The same ModelCheckpoint instance is shared by both stages so its
    # "best so far" carries over and stage 2 never overwrites a better stage-1 model.
    return [
        ckpt_cb,
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=patience, restore_best_weights=True),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=max(1, patience // 2)),
        tf.keras.callbacks.CSVLogger(str(log_dir / "history.csv"), append=True),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--run-name", default=datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    set_global_seed(cfg["seed"])
    splits_dir = resolve(cfg["paths"]["splits_dir"])
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    run_dir = resolve(cfg["paths"]["models_dir"]) / "runs" / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    fruits, conditions = cfg["fruits"], cfg["conditions"]
    size, bs, tr = cfg["image"]["size"], cfg["train"]["batch_size"], cfg["train"]

    train_df, val_df = load_split(splits_dir, "train"), load_split(splits_dir, "val")
    train_ds = make_dataset(train_df, raw_dir, fruits, conditions, size, bs, training=True,
                            aug_cfg=cfg["augment"], seed=cfg["seed"], balance=tr["class_weighting"])
    val_ds = make_dataset(val_df, raw_dir, fruits, conditions, size, bs, training=False)

    m = cfg["model"]
    model = build_model(len(fruits), len(conditions), size, m["alpha"], m["dropout"],
                        m["head_units"], cut_layer=m.get("cut_layer"))
    model.summary()

    ckpt = tf.keras.callbacks.ModelCheckpoint(
        str(run_dir / "best.keras"), monitor="val_loss", save_best_only=True)
    compile_model(model, tr["head_lr"], m["loss_weights"])
    model.fit(train_ds, validation_data=val_ds, epochs=tr["head_epochs"],
              callbacks=callbacks(ckpt, run_dir, tr["early_stopping_patience"]))

    if tr["finetune_epochs"] > 0:
        unfreeze_top(model, tr["finetune_unfreeze_layers"])
        compile_model(model, tr["finetune_lr"], m["loss_weights"])
        model.fit(train_ds, validation_data=val_ds,
                  epochs=tr["head_epochs"] + tr["finetune_epochs"],
                  initial_epoch=tr["head_epochs"],
                  callbacks=callbacks(ckpt, run_dir, tr["early_stopping_patience"]))

    model.save(run_dir / "final.keras")
    (run_dir / "labels.json").write_text(json.dumps({"fruits": fruits, "conditions": conditions}, indent=2))
    (run_dir / "config_snapshot.json").write_text(json.dumps(cfg, indent=2))
    print(f"Saved run to {run_dir}. Evaluate with: python scripts/evaluate.py --run {args.run_name}")


if __name__ == "__main__":
    main()
