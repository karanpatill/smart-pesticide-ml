"""CANDIDATE experiment (new artifact only; frozen models untouched): fruit-vs-background logistic head on the frozen
Model 1 56-d `gap` features (float Keras model, read-only), inputs rendered through the exact device preprocessing.

Train: TRAIN-split fruit images (positives) + TRAIN corner patches with rembg fruit fraction < 2 % + synthetic smooth fields.
Select C and the decision threshold on VAL only (target: <= 2 % of VAL background patches accepted).
Report on held-out TEST (fruit images, clean background patches, synthetic fields) and on real device frames (never used
for training or selection). Output: models/candidates/background_head_<UTC>/ and reports/experiments/background_head_<UTC>/.
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
from fruitvision.camera_preprocess import rgb565_to_input_int8  # noqa: E402

TS = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
REP = ROOT / "reports/experiments" / f"background_head_{TS}"
CAND = ROOT / "models/candidates" / f"background_head_{TS}"
REP.mkdir(parents=True); CAND.mkdir(parents=True)
GATE = json.loads((ROOT / "configs/presence_gate.json").read_text())
MIN_DETAIL = GATE["min_detail_laplacian_var"]
LOG = open(REP / "log.txt", "w", encoding="utf-8")
MASKS = pd.read_csv(ROOT / "data/interim/masks/masks.csv")


def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()


def split_rows(name, n_img, seed):
    d = cpg.split_images(name).merge(MASKS, on="path", how="left")
    return d.sample(min(n_img, len(d)), random_state=seed).reset_index(drop=True)


def render(name, d, rng):
    """Return (inputs int8 [N,80,80,3], labels 1=fruit 0=background, kind, detail)."""
    X, y, kind = [], [], []
    for p, mf in zip(d.path, d["mask"]):
        with Image.open(ROOT / "data/raw" / p) as im, Image.open(ROOT / "data/interim/masks" / mf) as mk:
            rgb = im.convert("RGB"); w, h = rgb.size
            X.append(cpg.model_input(cpg.frame_160x120(rgb))); y.append(1); kind.append("fruit_image")
            mask = np.asarray(mk.convert("L").resize((w, h), Image.NEAREST)) > 127
            s = int(0.35 * min(w, h))
            for cx, cy in ((0, 0), (w - s, 0), (0, h - s), (w - s, h - s)):
                if mask[cy:cy + s, cx:cx + s].mean() < 0.02:
                    X.append(cpg.model_input(cpg.frame_160x120(rgb.crop((cx, cy, cx + s, cy + s))))); y.append(0)
                    kind.append("background_patch")
    yy, xx = np.mgrid[0:120, 0:160]
    for _ in range(len(d) // 10):
        a, b = rng.uniform(0, 255, 3), rng.uniform(0, 255, 3)
        t = (xx / 160 * rng.uniform(0, 1) + yy / 120 * rng.uniform(0, 1))[..., None]
        X.append(cpg.model_input(np.clip(a * (1 - t) + b * t + rng.normal(0, 2, (120, 160, 3)), 0, 255).astype(np.uint8)))
        y.append(0); kind.append("synthetic_smooth")
    X = np.stack(X)
    log(f"{name}: {np.sum(np.array(y) == 1)} fruit, {np.sum(np.array(kind) == 'background_patch')} background patches, "
        f"{np.sum(np.array(kind) == 'synthetic_smooth')} synthetic")
    return X, np.array(y), np.array(kind), np.array([cpg.detail(x) for x in X])


def main() -> int:
    import tensorflow as tf
    from sklearn.linear_model import LogisticRegression
    src = ROOT / "models/model1/model1_final.keras"
    log("frozen extractor sha256 (read-only):", hashlib.sha256(src.read_bytes()).hexdigest())
    m = tf.keras.models.load_model(src, compile=False)
    feat = tf.keras.Model(m.inputs, m.get_layer("gap").output)
    F = lambda X: feat.predict(X.astype(np.float32) + 128.0, batch_size=256, verbose=0)
    rng = np.random.default_rng(0)
    data = {}
    for name, n in (("train", 2500), ("val", 1299), ("test", 1012)):
        X, y, k, de = render(name, split_rows(name, n, 0), rng)
        data[name] = (F(X), y, k, de)

    ftr, ytr, _, _ = data["train"]; fva, yva, kva, dva = data["val"]
    mu, sd = ftr.mean(0), ftr.std(0) + 1e-6
    z = lambda f: (f - mu) / sd
    best = None
    for C in (0.01, 0.03, 0.1, 0.3, 1.0):
        clf = LogisticRegression(C=C, class_weight="balanced", max_iter=5000).fit(z(ftr), ytr)
        pv = clf.predict_proba(z(fva))[:, 1]
        bg = pv[(yva == 0) & (kva == "background_patch")]
        thr = float(np.quantile(bg, 0.98))                    # <= 2 % of VAL background patches accepted
        tpr = float((pv[yva == 1] >= thr).mean())
        log(f"C={C}: VAL thr {thr:.4f} fruit accept {tpr:.4f}")
        if best is None or tpr > best[0]:
            best = (tpr, C, thr, clf)
    _, C, thr, clf = best
    log(f"selected on VAL: C={C} thr={thr:.4f}")

    def evaluate(f, y, k, de, name):
        p = clf.predict_proba(z(f))[:, 1]
        acc = p >= thr
        out = {"n_fruit": int((y == 1).sum()), "fruit_accept_head": round(float(acc[y == 1].mean()), 4),
               "fruit_accept_head_and_detail": round(float((acc & (de >= MIN_DETAIL))[y == 1].mean()), 4)}
        for kk in ("background_patch", "synthetic_smooth"):
            mm = (y == 0) & (k == kk)
            out[f"{kk}_n"] = int(mm.sum())
            out[f"{kk}_false_accept_head"] = round(float(acc[mm].mean()), 4)
            out[f"{kk}_false_accept_head_and_detail"] = round(float((acc & (de >= MIN_DETAIL))[mm].mean()), 4)
        log(name, json.dumps(out))
        return out, p

    res = {"label": "CANDIDATE background-rejection head; frozen Model 1 features (float Keras); NOT deployed, NOT INT8; "
                    "real device frames only for reporting", "C": C, "threshold_VAL": thr}
    res["VAL"], _ = evaluate(*data["val"], "VAL")
    res["TEST_heldout"], ptest = evaluate(*data["test"], "TEST")

    dev = []
    for d in sorted((ROOT / "reports/firmware/device_capture").iterdir()):
        x = np.fromfile(d / "model_input.int8", np.int8).reshape(80, 80, 3)
        dev.append((d.name, x, "reposition" in d.name or "focus_loop_12" in d.name))
    for d, fr in (("20261017T092139Z", False), ("20261017T092315Z", False), ("20261017T094631Z", True)):
        fb = (ROOT / "reports/firmware/live_capture" / d / "frame_a.bin").read_bytes()[:38400]
        dev.append((d, rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True).reshape(80, 80, 3), fr))
    pd_ = clf.predict_proba(z(F(np.stack([x for _, x, _ in dev]))))[:, 1]
    res["device_frames"] = [{"id": i, "sharp_fruit": fr, "p_fruit": round(float(p), 4), "accepted_head": bool(p >= thr),
                             "detail": round(cpg.detail(x), 1)} for (i, x, fr), p in zip(dev, pd_)]
    for r in res["device_frames"]:
        log("device", r)
    np.savez(CAND / "background_head.npz", mean=mu, scale=sd, coef=clf.coef_[0], intercept=clf.intercept_, threshold=thr)
    (CAND / "README.json").write_text(json.dumps({"what": "candidate fruit-vs-background logistic head on Model 1 gap (56-d)",
                                                  "status": "CANDIDATE, not deployed", "extractor": str(src.relative_to(ROOT)),
                                                  "report": str(REP.relative_to(ROOT))}, indent=1))
    (REP / "metrics.json").write_text(json.dumps(res, indent=1))
    log("saved", REP, CAND)
    return 0


if __name__ == "__main__":
    sys.exit(main())
