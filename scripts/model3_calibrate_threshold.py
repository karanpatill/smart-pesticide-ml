"""Derive the fruit-routing confidence threshold from EXISTING validation data.

No model is trained or modified. Model 1 + Model 3 (models/model3/model3_combined.keras,
whose fruit output is identical to Model 1's) is only run in inference.

Validation pool (deduplicated by path):
  * Model 1 VAL split (data/splits/val.csv) - all five fruits, Model 1's domain
  * Model 3 VAL rows never seen by Model 1 (data/model3/manifest.csv,
    split_origin == new_group_split): grade-set banana/guava, semi-fresh images
Criterion (fixed before looking at results): choose the threshold t that maximises
Youden's J = P(conf >= t | fruit correct) - P(conf >= t | fruit wrong), i.e. the
best separation of correct from incorrect fruit predictions.
TEST pool (same construction from test splits) is used ONLY to report the effect.

Outputs: configs/model3_postprocess.json (threshold + rules), reports/model3/postprocess/
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tensorflow as tf

from fruitvision.config import resolve
from fruitvision.training import cached_images

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]


def pool(split: str) -> pd.DataFrame:
    m1 = pd.read_csv(resolve(f"data/splits/{split}.csv"))[["path", "fruit", "source"]].assign(origin="model1_split")
    m3 = pd.read_csv(resolve("data/model3/manifest.csv"))
    m3 = m3[(m3.split == split) & (m3.split_origin == "new_group_split")][["path", "fruit", "source"]]
    return pd.concat([m1, m3.assign(origin="model3_new_split")]).drop_duplicates("path").reset_index(drop=True)


def stats(conf, correct, t):
    keep = conf >= t
    return {"coverage": round(float(keep.mean()), 4),
            "accuracy_kept": round(float(correct[keep].mean()) if keep.any() else float("nan"), 4),
            "accuracy_all": round(float(correct.mean()), 4),
            "errors_flagged": round(float((~keep & ~correct).sum() / max(1, (~correct).sum())), 4),
            "correct_flagged": round(float((~keep & correct).sum() / max(1, correct.sum())), 4)}


def main() -> None:
    model = tf.keras.models.load_model(resolve("models/model3/model3_combined.keras"))
    out_dir = resolve("reports/model3/postprocess")
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {}
    for split in ("val", "test"):
        df = pool(split)
        x = cached_images(list(df.path), resolve("data/raw"), 80, resolve("data/interim/cache"))
        fp = model.predict(x.astype("float32"), verbose=0, batch_size=256)["fruit"]
        df["conf"], df["pred"] = fp.max(1), [FRUITS[i] for i in fp.argmax(1)]
        df["correct"] = df.pred == df.fruit
        df.to_csv(out_dir / f"fruit_confidence_{split}.csv", index=False)
        res[split] = df

    v = res["val"]
    conf, correct = v.conf.to_numpy(), v.correct.to_numpy()
    cands = np.unique(np.round(conf, 3))
    j = np.array([(conf[correct] >= t).mean() - (conf[~correct] >= t).mean() for t in cands])
    t_star = float(cands[int(j.argmax())])

    report = {"criterion": "max Youden's J on VAL pool (correct vs incorrect fruit predictions)",
              "threshold": t_star, "youden_j": round(float(j.max()), 4),
              "val_pool": {"n": len(v), "by_origin": v.origin.value_counts().to_dict(),
                           **stats(conf, correct, t_star)},
              "test_pool_report_only": {"n": len(res["test"]),
                                        **stats(res["test"].conf.to_numpy(), res["test"].correct.to_numpy(), t_star)},
              "val_by_fruit": {f: stats(g.conf.to_numpy(), g.correct.to_numpy(), t_star)
                               for f, g in v.groupby("fruit")},
              "test_by_fruit_report_only": {f: stats(g.conf.to_numpy(), g.correct.to_numpy(), t_star)
                                            for f, g in res["test"].groupby("fruit")},
              "test_by_origin_report_only": {o: stats(g.conf.to_numpy(), g.correct.to_numpy(), t_star)
                                             for o, g in res["test"].groupby("origin")}}
    (out_dir / "threshold_report.json").write_text(json.dumps(report, indent=2))

    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    bins = np.linspace(0, 1, 41)
    ax[0].hist(conf[correct], bins, alpha=.6, label="correct", density=True)
    ax[0].hist(conf[~correct], bins, alpha=.6, label="wrong", density=True)
    ax[0].axvline(t_star, color="k", ls="--", label=f"t = {t_star:.3f}"); ax[0].legend()
    ax[0].set_title("VAL: Model 1 fruit confidence"); ax[0].set_xlabel("max softmax")
    ax[1].plot(cands, j); ax[1].axvline(t_star, color="k", ls="--")
    ax[1].set_title("Youden's J vs threshold (VAL)"); ax[1].set_xlabel("threshold")
    fig.tight_layout(); fig.savefig(out_dir / "threshold_selection.png", dpi=110); plt.close(fig)
    print(json.dumps({k: report[k] for k in ("threshold", "youden_j", "val_pool", "test_pool_report_only",
                                             "test_by_fruit_report_only")}, indent=1))


if __name__ == "__main__":
    main()
