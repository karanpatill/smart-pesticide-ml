"""CANDIDATE experiment (new artifact only): retrain ONLY the 5-class fruit head (Dense on the frozen Model 1 56-d `gap`
features) with the banana_guava_quality grade images added to training. Frozen Model 1 is read-only.

Data (device preprocessing path, frozen float extractor):
  train: M1 TRAIN split + grade-set rows with split == train   (grade set: 0 pHash near-duplicates with M1 splits)
  select: M1 VAL + grade-set VAL (L2 C chosen on VAL macro-F1)
  report: M1 TEST and grade-set TEST (held out). Baseline = the frozen Model 1 fruit head on the same features.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/firmware"))
import calibrate_presence_gate as cpg  # noqa: E402

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
TS = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
REP = ROOT / "reports/experiments" / f"fruit_head_guava_{TS}"; REP.mkdir(parents=True)
CAND = ROOT / "models/candidates" / f"fruit_head_guava_{TS}"; CAND.mkdir(parents=True)
LOG = open(REP / "log.txt", "w", encoding="utf-8")


def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()


def render(paths):
    out = []
    for p in paths:
        with Image.open(ROOT / "data/raw" / p) as im:
            out.append(cpg.model_input(cpg.frame_160x120(im.convert("RGB"))))
    return np.stack(out)


def main() -> int:
    import tensorflow as tf
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix, f1_score
    src = ROOT / "models/model1/model1_final.keras"
    log("frozen extractor sha256 (read-only):", hashlib.sha256(src.read_bytes()).hexdigest())
    m = tf.keras.models.load_model(src, compile=False)
    feat = tf.keras.Model(m.inputs, [m.get_layer("gap").output, m.get_layer("fruit").output])
    man = pd.read_csv(ROOT / "data/model3/manifest.csv")
    gq = man[man.source == "banana_guava_quality"]
    sets = {}
    for s in ("train", "val", "test"):
        m1 = cpg.split_images(s)
        g = gq[gq.split == s]
        for name, d in ((f"m1_{s}", m1), (f"grade_{s}", g)):
            X = render(d.path)
            f, pf = feat.predict(X.astype(np.float32) + 128.0, batch_size=256, verbose=0)
            sets[name] = (f, np.array([FRUITS.index(x) for x in d.fruit]), pf.argmax(1))
            log(name, len(d))
    ftr = np.concatenate([sets["m1_train"][0], sets["grade_train"][0]])
    ytr = np.concatenate([sets["m1_train"][1], sets["grade_train"][1]])
    fva = np.concatenate([sets["m1_val"][0], sets["grade_val"][0]]); yva = np.concatenate([sets["m1_val"][1], sets["grade_val"][1]])
    mu, sd = ftr.mean(0), ftr.std(0) + 1e-6
    z = lambda f: (f - mu) / sd
    best = None
    for C in (0.01, 0.03, 0.1, 0.3, 1.0, 3.0):
        clf = LogisticRegression(C=C, class_weight="balanced", max_iter=5000).fit(z(ftr), ytr)
        f1 = f1_score(yva, clf.predict(z(fva)), average="macro")
        log(f"C={C}: VAL macro-F1 {f1:.4f}")
        if best is None or f1 > best[0]:
            best = (f1, C, clf)
    _, C, clf = best
    res = {"label": "CANDIDATE fruit head (logistic regression on frozen Model 1 gap features, float); NOT deployed, NOT INT8",
           "C_selected_on_VAL": C, "train_n": int(len(ytr))}
    for name in ("m1_test", "grade_test", "m1_val", "grade_val"):
        f, y, base = sets[name]
        cand = clf.predict(z(f))
        r = {}
        for tag, pr in (("baseline_frozen_head", base), ("candidate_head", cand)):
            r[tag] = {"macro_f1": round(float(f1_score(y, pr, labels=range(5), average="macro", zero_division=0)), 4),
                      "acc": round(float((pr == y).mean()), 4),
                      "recall": {FRUITS[k]: round(float((pr[y == k] == k).mean()), 3) for k in range(5) if (y == k).any()},
                      "confusion": confusion_matrix(y, pr, labels=range(5)).tolist()}
        res[name] = r
        log(name, "baseline", r["baseline_frozen_head"]["macro_f1"], r["baseline_frozen_head"]["recall"],
            "| candidate", r["candidate_head"]["macro_f1"], r["candidate_head"]["recall"])
    np.savez(CAND / "fruit_head.npz", mean=mu, scale=sd, coef=clf.coef_, intercept=clf.intercept_)
    (CAND / "README.json").write_text(json.dumps({"what": "candidate 5-class fruit head on Model 1 gap (56-d) + grade-set images",
                                                  "status": "CANDIDATE, not deployed", "report": str(REP.relative_to(ROOT))}, indent=1))
    (REP / "metrics.json").write_text(json.dumps(res, indent=1))
    log("saved", REP, CAND)
    return 0


if __name__ == "__main__":
    sys.exit(main())
