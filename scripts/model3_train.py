"""Train Model 3 heads (Quality Grade + shelf-life stage) on Model 1's FROZEN features.

* Feature extractor: Model 1 (models/model1/model1_final.keras) up to layer `gap`
  (56-d). Loaded read-only; its weights are never trained or re-saved in place.
* One small head per task (see model3_prepare.py). Candidates per head:
    linear  : Dense(n_classes, softmax)                        (~57*k params)
    mlp16   : Dense(16, relu) -> Dropout(0.3) -> Dense(k)      (~0.9k-1k params)
  Pre-registered choice: linear unless mlp16 beats it by > 0.02 VAL macro-F1.
* Train features: original image + 4 augmented views (Model 1's augmentation config).
  VAL/TEST: original image only. Class-balanced weights, early stopping on VAL loss.
* Evaluation: VAL and TEST per task (oracle routing = true fruit), plus an
  end-to-end TEST check where Model 1's predicted fruit selects the head.
* Shelf life is NOT regressed: the stage head output maps to the documented
  AgriFreshNET range table (configs/model3_shelf_life.yaml).

Artifacts -> models/model3/ ; reports -> reports/model3/
"""

from __future__ import annotations

import hashlib
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.metrics import (ConfusionMatrixDisplay, classification_report, confusion_matrix, f1_score,
                             precision_recall_fscore_support)

from fruitvision.config import load_yaml, resolve
from fruitvision.data.pipeline import build_augmenter
from fruitvision.model3 import build_combined
from fruitvision.training import cached_images

SIZE, SEED, N_AUG = 80, 42, 4
TASK_CLASSES = {
    "quality_banana": ["Good", "Average", "Poor"], "quality_guava": ["Good", "Average", "Poor"],
    "quality_apple": ["Good", "Poor"],
    "stage_tomato": ["Fresh", "Semi-fresh", "Rotten"], "stage_brinjal": ["Fresh", "Semi-fresh", "Rotten"],
    "stage_banana": ["Fresh", "Semi-fresh", "Rotten"],
}
FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]   # Model 1 fruit head order


def sha(p) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def build_head(kind: str, k: int, name: str) -> tf.keras.Model:
    inp = tf.keras.Input((56,), name=f"{name}_features")
    x = inp
    if kind == "mlp16":
        x = tf.keras.layers.Dense(16, activation="relu", kernel_regularizer=tf.keras.regularizers.l2(1e-4))(x)
        x = tf.keras.layers.Dropout(0.3)(x)
    out = tf.keras.layers.Dense(k, activation="softmax", kernel_regularizer=tf.keras.regularizers.l2(1e-4),
                                name=name)(x)
    return tf.keras.Model(inp, out, name=f"head_{name}_{kind}")


def train_head(kind, Xtr, ytr, Xva, yva, k, name):
    tf.keras.utils.set_random_seed(SEED)
    h = build_head(kind, k, name)
    h.compile(tf.keras.optimizers.Adam(3e-3), "sparse_categorical_crossentropy", metrics=["accuracy"])
    cw = len(ytr) / (k * np.bincount(ytr, minlength=k).clip(1))
    hist = h.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=300, batch_size=64, verbose=0,
                 class_weight=dict(enumerate(cw)),
                 callbacks=[tf.keras.callbacks.EarlyStopping(patience=25, restore_best_weights=True)])
    return h, hist.history


def metrics(y, p, classes):
    pr, rc, f1, n = precision_recall_fscore_support(y, p, labels=range(len(classes)), zero_division=0)
    return {"accuracy": round(float((y == p).mean()), 4),
            "macro_f1": round(float(f1_score(y, p, average="macro", labels=range(len(classes)), zero_division=0)), 4),
            "per_class": {c: {"precision": round(float(a), 4), "recall": round(float(b), 4),
                              "f1": round(float(d), 4), "support": int(e)}
                          for c, a, b, d, e in zip(classes, pr, rc, f1, n)},
            "confusion": confusion_matrix(y, p, labels=range(len(classes))).tolist()}


def main() -> None:
    m1_path = resolve("models/model1/model1_final.keras")
    m1_hash_before = sha(m1_path)
    art, rep = resolve("models/model3"), resolve("reports/model3")
    if (art / "model3_combined.keras").exists():
        raise SystemExit("models/model3 already has artifacts; refusing to overwrite.")
    art.mkdir(parents=True, exist_ok=True); rep.mkdir(parents=True, exist_ok=True)

    cfg = load_yaml("configs/config.yaml")
    shelf = load_yaml("configs/model3_shelf_life.yaml")
    man = pd.read_csv(resolve("data/model3/manifest.csv"))
    x_all = cached_images(list(man.path), resolve("data/raw"), SIZE, resolve("data/interim/cache"))

    m1 = tf.keras.models.load_model(m1_path)
    m1.trainable = False
    extractor = tf.keras.Model(m1.input, m1.get_layer("gap").output, name="model1_frozen_extractor")
    aug = build_augmenter(cfg["augment"])

    def feats(x, augment=False):
        out = []
        for i in range(0, len(x), 256):
            b = tf.cast(x[i:i + 256], tf.float32)
            if augment:
                b = tf.clip_by_value(aug(b, training=True), 0, 255)
            out.append(extractor(b, training=False).numpy())
        return np.concatenate(out)

    tf.keras.utils.set_random_seed(SEED)
    F_clean = feats(x_all)
    m1_out = m1.predict(x_all.astype("float32"), verbose=0, batch_size=256)
    man["m1_pred_fruit"] = [FRUITS[i] for i in m1_out["fruit"].argmax(1)]

    heads, results, chosen = {}, {}, {}
    for task, classes in TASK_CLASSES.items():
        t = man[man.task == task]
        idx = {s: t.index[t.split == s].to_numpy() for s in ("train", "val", "test")}
        y = {s: t.loc[idx[s], "label"].map({c: i for i, c in enumerate(classes)}).to_numpy() for s in idx}
        # train features: clean + N_AUG augmented views
        Xtr = np.concatenate([F_clean[idx["train"]]] + [feats(x_all[idx["train"]], True) for _ in range(N_AUG)])
        ytr = np.tile(y["train"], N_AUG + 1)
        cand = {}
        for kind in ("linear", "mlp16"):
            h, hist = train_head(kind, Xtr, ytr, F_clean[idx["val"]], y["val"], len(classes), task)
            pv = h.predict(F_clean[idx["val"]], verbose=0).argmax(1)
            cand[kind] = (h, hist, f1_score(y["val"], pv, average="macro"))
        kind = "mlp16" if cand["mlp16"][2] > cand["linear"][2] + 0.02 else "linear"
        h, hist, _ = cand[kind]
        heads[task], chosen[task] = h, kind
        res = {"head": kind, "val_macro_f1_candidates": {k: round(float(v[2]), 4) for k, v in cand.items()},
               "params": int(h.count_params()), "epochs_trained": len(hist["loss"]),
               "n": {s: int(len(idx[s])) for s in idx},
               "split_origin": t.split_origin.value_counts().to_dict()}
        for s in ("val", "test"):
            p = h.predict(F_clean[idx[s]], verbose=0).argmax(1)
            res[s] = metrics(y[s], p, classes)
            man.loc[idx[s], "pred_label"] = [classes[i] for i in p]
            man.loc[idx[s], "pred_conf"] = h.predict(F_clean[idx[s]], verbose=0).max(1)
            cm = np.array(res[s]["confusion"])
            fig, ax = plt.subplots(figsize=(4.4, 4))
            ConfusionMatrixDisplay(cm, display_labels=classes).plot(ax=ax, colorbar=False, cmap="Blues")
            ax.set_title(f"Model 3 {task} — {s.upper()}", fontsize=9)
            fig.tight_layout(); (rep / task).mkdir(parents=True, exist_ok=True)
            fig.savefig(rep / task / f"confusion_{s}.png", dpi=110); plt.close(fig)
            (rep / task / f"classification_report_{s}.txt").write_text(classification_report(
                y[s], p, labels=range(len(classes)), target_names=classes, digits=4, zero_division=0))
        # end-to-end routing on TEST: Model 1's predicted fruit must select this head
        te = man.loc[idx["test"]]
        routed = (te.m1_pred_fruit == te.fruit).to_numpy()
        e2e_correct = routed & (te.pred_label == te.label).to_numpy()
        res["test_end_to_end"] = {"model1_routes_to_correct_head": round(float(routed.mean()), 4),
                                  "accuracy_including_routing_errors": round(float(e2e_correct.mean()), 4),
                                  "misrouted_to": te.loc[~routed, "m1_pred_fruit"].value_counts().to_dict()}
        results[task] = res
        print(f"{task:15s} head={kind:6s} params={res['params']:5d} VAL F1 {res['val']['macro_f1']:.3f} "
              f"TEST F1 {res['test']['macro_f1']:.3f} acc {res['test']['accuracy']:.3f} "
              f"| routed {res['test_end_to_end']['model1_routes_to_correct_head']:.2f} "
              f"e2e acc {res['test_end_to_end']['accuracy_including_routing_errors']:.3f}", flush=True)

    # ---- artifacts ----
    feat_in = tf.keras.Input((56,), name="model1_gap_features")
    heads_model = tf.keras.Model(feat_in, {t: heads[t](feat_in) for t in TASK_CLASSES}, name="model3_heads")
    heads_model.save(art / "model3_heads.keras")
    heads_model.save_weights(art / "model3_heads.weights.h5")
    combined = build_combined(m1, heads, SIZE)   # flat graph (reloadable), Model 1 layers shared + frozen
    combined.save(art / "model3_combined.keras")

    # combined model must reproduce Model 1 exactly
    chk = combined.predict(x_all[:256].astype("float32"), verbose=0)
    m1_same = float(max(np.abs(chk["fruit"] - m1_out["fruit"][:256]).max(),
                        np.abs(chk["condition"] - m1_out["condition"][:256]).max()))

    head_params = int(heads_model.count_params())
    size_info = {
        "head_params_total": head_params,
        "per_head_params": {t: int(heads[t].count_params()) for t in TASK_CLASSES},
        "flash_added_float32_bytes": head_params * 4,
        "flash_added_int8_bytes_estimate": head_params + 4 * sum(len(c) for c in TASK_CLASSES.values()),
        "ram_added_bytes_estimate": 4 * (56 + max(16 if chosen[t] == "mlp16" else 0 for t in chosen) + 3),
        "model1_params": int(m1.count_params()),
        "combined_params": int(combined.count_params()),
        "combined_max_abs_diff_vs_model1_outputs": m1_same,
        "note": "Heads read Model 1's 56-d GAP tensor; Model 1 runs once per image. Estimates, not device measurements.",
    }
    m1_hash_after = sha(m1_path)
    assert m1_hash_before == m1_hash_after, "Model 1 file changed!"

    (art / "labels.json").write_text(json.dumps({t: dict(enumerate(c)) for t, c in TASK_CLASSES.items()}, indent=2))
    (art / "heads_selected.json").write_text(json.dumps(chosen, indent=2))
    (art / "metrics.json").write_text(json.dumps({"tasks": results, "size": size_info}, indent=2, default=str))
    (art / "training_config.json").write_text(json.dumps({
        "feature_extractor": {"model": "models/model1/model1_final.keras", "layer": "gap", "dim": 56,
                              "frozen": True, "sha256": m1_hash_before},
        "input": {"size": SIZE, "preprocessing": "identical to Model 1 (models/model1/preprocessing.json)"},
        "heads": {"candidates": ["linear", "mlp16"], "rule": "linear unless mlp16 VAL macro-F1 > linear + 0.02",
                  "selected": chosen, "optimizer": "Adam 3e-3", "l2": 1e-4, "batch": 64,
                  "early_stopping": "val_loss patience 25 (max 300 epochs)", "class_weights": "balanced"},
        "train_augmentation": {"views": N_AUG, "config": cfg["augment"]},
        "data": {"manifest": "data/model3/manifest.csv",
                 "manifest_sha256": sha(resolve("data/model3/manifest.csv"))},
        "seed": SEED, "tensorflow": tf.__version__}, indent=2))
    (art / "shelf_life_ranges.json").write_text(json.dumps(shelf, indent=2))
    man.to_csv(rep / "predictions_val_test.csv", index=False)
    print(json.dumps(size_info, indent=2))
    print("Model 1 unchanged (sha256 verified).")


if __name__ == "__main__":
    main()
