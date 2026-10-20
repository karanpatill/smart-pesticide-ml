"""Non-destructive evaluation of the FROZEN deployed INT8 model (models/experimental/tflite/combined_int8.tflite).
No training, no model or firmware change. Output: reports/experiments/device_domain_<UTC>/ (metrics.json, log.txt, CSVs).

Experiments
  A  no-fruit rejection: real device frames, held-out TEST background patches, synthetic empty scenes
  C  camera-domain robustness: M1 TEST through the exact device path (+ measured OV2640 vignetting / blue cast / defocus)
  D  temperature scaling + per-class thresholds (fit on VAL, evaluated on TEST and on negatives)
  B  banana_guava_quality grade set: provenance-related checks (pHash overlap with M1 splits) + frozen-model routing
  E  M3 stage heads (tomato / brinjal / banana): ordinal error structure on TEST from recorded predictions
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/firmware"))
from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes  # noqa: E402
import calibrate_presence_gate as cpg  # noqa: E402  (frame_160x120 / model_input / detail: same as the presence-gate study)

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
COND = ["fresh", "spoiled"]
GATE = json.loads((ROOT / "configs/presence_gate.json").read_text())
MIN_DETAIL, R1 = GATE["min_detail_laplacian_var"], GATE["fruit_confidence_threshold"]
OUT = ROOT / "reports/experiments" / ("device_domain_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
OUT.mkdir(parents=True)
LOG = open(OUT / "log.txt", "w", encoding="utf-8")


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n"); LOG.flush()


class Net:
    """Frozen INT8 model. Default (optimised) kernels for speed; agreement with BUILTIN_REF is checked on a sample."""

    def __init__(self, ref=False):
        import tensorflow as tf
        kw = {"experimental_op_resolver_type": tf.lite.experimental.OpResolverType.BUILTIN_REF} if ref else {}
        it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"), **kw)
        it.allocate_tensors()
        self.run = it.get_signature_runner()
        self.iname = list(self.run.get_input_details())[0]

    def __call__(self, x: np.ndarray):
        o = self.run(**{self.iname: x.reshape(1, 80, 80, 3)})
        return ((o["fruit"][0].astype(np.float64) + 128) / 256, (o["condition"][0].astype(np.float64) + 128) / 256,
                o["fruit"][0].astype(np.int16).tolist())


# ------------------------------------------------------------------ device-path variants (all end in the C-exact preprocessing)
def vignette_gain(corner_ratio=0.44):
    """Radial gain on the 160x120 frame; the 120x120 crop corners (r = 84.85 px from centre) get corner_ratio
    (measured on the device: corner/centre luminance 0.43-0.45 of the 80x80 input on near-uniform scenes)."""
    yy, xx = np.mgrid[0:120, 0:160]
    r = np.hypot(xx - 79.5, yy - 59.5) / 84.85
    return np.clip(1 - (1 - corner_ratio) * r ** 2, 0.15, 1.0)[..., None]


VIG = vignette_gain()


def variant(frame: np.ndarray, name: str) -> np.ndarray:
    f = frame.astype(np.float64)
    if "vig" in name:
        f = f * VIG
    if "cast" in name:                     # measured on white background: B/G +5..10 %, R/G 0.994
        f[..., 2] *= 1.075
    f = np.clip(f + 0.5, 0, 255).astype(np.uint8)
    for s in ("blur1", "blur3"):
        if s in name:
            f = np.asarray(Image.fromarray(f).filter(ImageFilter.GaussianBlur(int(s[-1]))), np.uint8)
    return cpg.model_input(f)


def clean_training_input(path: Path) -> np.ndarray:
    import tensorflow as tf
    from fruitvision.data.pipeline import decode_and_resize
    x = np.clip(decode_and_resize(tf.constant(str(path)), 80).numpy(), 0, 255)
    return (np.round(x).astype(np.int16) - 128).astype(np.int8)


def f1_macro(y, p, labels):
    from sklearn.metrics import f1_score
    return float(f1_score(y, p, labels=labels, average="macro", zero_division=0))


def ece(conf, correct, bins=15):
    conf, correct = np.asarray(conf), np.asarray(correct, float)
    e = 0.0
    for lo in np.linspace(0, 1, bins, endpoint=False):
        m = (conf > lo) & (conf <= lo + 1 / bins)
        if m.any():
            e += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(e)


def summarise(df: pd.DataFrame, thr: dict | None = None) -> dict:
    ok = df.pred == df.fruit
    shown = (df.detail >= MIN_DETAIL) & (df.conf >= R1) if thr is None else \
        (df.detail >= MIN_DETAIL) & (df.conf >= df.pred.map(thr))
    return {"n": int(len(df)), "fruit_acc": round(float(ok.mean()), 4), "fruit_macro_f1": round(f1_macro(df.fruit, df.pred, FRUITS), 4),
            "per_fruit_recall": {f: round(float(ok[df.fruit == f].mean()), 3) for f in FRUITS},
            "cond_macro_f1": round(f1_macro(df.condition, df.cpred, COND), 4),
            "shown_rate": round(float(shown.mean()), 4), "acc_when_shown": round(float(ok[shown].mean()), 4) if shown.any() else None,
            "per_fruit_shown": {f: round(float(shown[df.fruit == f].mean()), 3) for f in FRUITS},
            "median_detail": round(float(df.detail.median()), 1), "ece_fruit": round(ece(df.conf, ok), 4)}


def run_split(net, name, variants):
    d = cpg.split_images(name)
    rows = {v: [] for v in variants}
    t0 = time.time()
    for i, (p, fr, co) in enumerate(zip(d.path, d.fruit, d.condition)):
        with Image.open(ROOT / "data/raw" / p) as im:
            rgb = im.convert("RGB")
            frame = cpg.frame_160x120(rgb)
        for v in variants:
            x = clean_training_input(ROOT / "data/raw" / p) if v == "clean_training_preproc" else variant(frame, v)
            pf, pc, q = net(x)
            rows[v].append({"path": p, "fruit": fr, "condition": co, "pred": FRUITS[int(pf.argmax())], "conf": float(pf.max()),
                            "cpred": COND[int(pc.argmax())], "detail": cpg.detail(x), "q": q})
        if i % 200 == 0:
            log(f"  {name} {i}/{len(d)} {time.time() - t0:.0f}s")
    return {v: pd.DataFrame(r) for v, r in rows.items()}


def main() -> int:
    log("frozen model sha256:", __import__("hashlib").sha256((ROOT / "models/experimental/tflite/combined_int8.tflite").read_bytes()).hexdigest())
    log("gate:", MIN_DETAIL, R1)
    net, fast = Net(ref=True), Net()          # all results use BUILTIN_REF (the STM32-parity kernels)
    res = {"label": "Frozen deployed INT8 model; evaluation only (no training). Public-image results are a PROXY for the device "
                    "camera (images converted through the exact firmware preprocessing); real device frames are listed separately."}

    # ---------------- kernel agreement (optimised vs BUILTIN_REF used on the STM32-parity tests)
    te0 = cpg.split_images("test").head(150)
    agree = agree_arg = 0
    for p in te0.path:
        with Image.open(ROOT / "data/raw" / p) as im:
            x = cpg.model_input(cpg.frame_160x120(im.convert("RGB")))
        a, b = net(x), fast(x)
        agree += a[2] == b[2]; agree_arg += int(np.argmax(a[2]) == np.argmax(b[2]))
    res["kernel_agreement_opt_vs_ref"] = f"{agree}/{len(te0)} identical int8 outputs, {agree_arg}/{len(te0)} same argmax (XNNPACK vs REF); REF used for all results"
    log("kernel agreement", res["kernel_agreement_opt_vs_ref"])

    # ---------------- C: camera-domain robustness on held-out TEST
    variants = ["clean_training_preproc", "dev_base", "dev_vig", "dev_cast", "dev_vig_cast", "dev_blur1", "dev_blur3", "dev_vig_cast_blur1"]
    test = run_split(net, "test", variants)
    for v, df in test.items():
        df.drop(columns="q").to_csv(OUT / f"test_{v}.csv", index=False)
    res["C_domain_robustness_TEST"] = {v: summarise(df) for v, df in test.items()}
    for v, s in res["C_domain_robustness_TEST"].items():
        log(f"C {v:24s} fruitF1 {s['fruit_macro_f1']} condF1 {s['cond_macro_f1']} shown {s['shown_rate']} accShown {s['acc_when_shown']} "
            f"recall {s['per_fruit_recall']}")

    # ---------------- D: calibration on VAL (device path), evaluated on TEST
    val = run_split(net, "val", ["dev_base", "dev_vig_cast"])
    calib = {}
    for v in ["dev_base", "dev_vig_cast"]:
        vq, tq = np.array(val[v].q.tolist()), np.array(test[v].q.tolist())
        vy = np.array([FRUITS.index(f) for f in val[v].fruit]); ty = np.array([FRUITS.index(f) for f in test[v].fruit])
        lp = lambda q: np.log(np.clip((q + 128) / 256, 1 / 512, 1))
        def probs(q, T):
            z = lp(q) / T; z -= z.max(1, keepdims=True); e = np.exp(z); return e / e.sum(1, keepdims=True)
        Ts = np.linspace(0.5, 4, 71)
        nll = [-np.mean(np.log(probs(vq, T)[np.arange(len(vy)), vy] + 1e-12)) for T in Ts]
        T = float(Ts[int(np.argmin(nll))])
        pt = probs(tq, T)
        calib[v] = {"temperature_fit_on_VAL": T, "TEST_ece_before": round(ece(test[v].conf, test[v].pred == test[v].fruit), 4),
                    "TEST_ece_after": round(ece(pt.max(1), pt.argmax(1) == ty), 4),
                    "note": "temperature scaling does not change argmax; with INT8 outputs (1/256 steps) it only re-maps thresholds"}
        # per-class thresholds on VAL: smallest raw-confidence threshold with accuracy-when-shown >= 0.97 and >= 15 kept
        thr = {}
        vd = val[v]
        for f in FRUITS:
            sub = vd[(vd.pred == f) & (vd.detail >= MIN_DETAIL)]
            best = R1
            for t in sorted(set(np.round(sub.conf, 6))):
                k = sub[sub.conf >= t]
                if len(k) >= 15 and (k.fruit == f).mean() >= 0.97:
                    best = float(t); break
            thr[f] = best
        calib[v]["per_class_threshold_VAL"] = thr
        calib[v]["TEST_global_R1"] = summarise(test[v])
        calib[v]["TEST_per_class"] = summarise(test[v], thr)
        log(f"D {v}: T={T} ece {calib[v]['TEST_ece_before']}->{calib[v]['TEST_ece_after']} thr {thr}")
        log(f"   global: shown {calib[v]['TEST_global_R1']['shown_rate']} acc {calib[v]['TEST_global_R1']['acc_when_shown']} | "
            f"per-class: shown {calib[v]['TEST_per_class']['shown_rate']} acc {calib[v]['TEST_per_class']['acc_when_shown']}")
    res["D_calibration"] = calib

    # ---------------- A: no-fruit rejection (negatives) under global R1 vs per-class thresholds
    negs = []
    dev_dir = ROOT / "reports/firmware/device_capture"
    for d in sorted(dev_dir.iterdir()):
        x = np.fromfile(d / "model_input.int8", np.int8).reshape(80, 80, 3)
        sharp_banana = "reposition" in d.name or "focus_loop_12" in d.name
        negs.append({"set": "device_frame", "id": d.name, "x": x, "is_fruit": sharp_banana,
                     "content": "banana, sharp" if sharp_banana else "defocused/unrecognisable scene"})
    for d, desc, fr in (("20261017T092139Z", "scene without fruit (blurry)", False), ("20261017T092315Z", "apple, strongly defocused", False),
                        ("20261017T094631Z", "apple, refocused", True)):
        fb = (ROOT / "reports/firmware/live_capture" / d / "frame_a.bin").read_bytes()[:38400]
        negs.append({"set": "device_frame_entc", "id": d,
                     "x": rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True).reshape(80, 80, 3),
                     "is_fruit": fr, "content": desc})
    rng = np.random.default_rng(0)
    te = cpg.split_images("test").merge(pd.read_csv(ROOT / "data/interim/masks/masks.csv"), on="path", how="left")
    for p, mf in zip(te.path.sample(250, random_state=0), te.set_index("path").loc[te.path.sample(250, random_state=0), "mask"]):
        with Image.open(ROOT / "data/raw" / p) as im, Image.open(ROOT / "data/interim/masks" / mf) as mk:
            rgb = im.convert("RGB"); w, h = rgb.size; s = int(0.35 * min(w, h))
            mask = np.asarray(mk.convert("L").resize((w, h), Image.NEAREST)) > 127
            for cx, cy in ((0, 0), (w - s, 0), (0, h - s), (w - s, h - s)):
                patch = rgb.crop((cx, cy, cx + s, cy + s))
                fg = float(mask[cy:cy + s, cx:cx + s].mean())
                clean = fg < 0.02
                negs.append({"set": "test_background_patch_clean" if clean else "test_patch_with_fruit_parts",
                             "id": f"{p}@{cx},{cy}", "x": cpg.model_input(cpg.frame_160x120(patch)),
                             "is_fruit": False if clean else None,
                             "content": f"TEST corner patch, rembg fruit fraction {fg:.3f}"})
    yy, xx = np.mgrid[0:120, 0:160]
    for i in range(60):                                                  # synthetic featureless / smooth scenes
        a = rng.uniform(0, 255, 3); b = rng.uniform(0, 255, 3); t = (xx / 160 * rng.uniform(0, 1) + yy / 120 * rng.uniform(0, 1))[..., None]
        img = np.clip(a * (1 - t) + b * t + rng.normal(0, 2, (120, 160, 3)), 0, 255).astype(np.uint8)
        negs.append({"set": "synthetic_smooth", "id": f"syn{i}", "x": cpg.model_input(img), "is_fruit": False, "content": "smooth colour field"})
    nrows = []
    for n in negs:
        pf, _pc, _q = net(n["x"])
        nrows.append({k: n[k] for k in ("set", "id", "is_fruit", "content")} | {"pred": FRUITS[int(pf.argmax())], "conf": float(pf.max()),
                                                                                  "detail": cpg.detail(n["x"])})
    nd = pd.DataFrame(nrows)
    thr = calib["dev_base"]["per_class_threshold_VAL"]
    nd["shown_R1_only"] = nd.conf >= R1
    nd["shown_gate_v5"] = (nd.detail >= MIN_DETAIL) & (nd.conf >= R1)
    nd["shown_gate_perclass"] = (nd.detail >= MIN_DETAIL) & (nd.conf >= nd.pred.map(thr))
    nd.to_csv(OUT / "A_negatives.csv", index=False)
    A = {}
    for s, g in nd.groupby("set"):
        neg = g[g.is_fruit != True]  # noqa: E712
        A[s] = {"n_negative": int(len(neg)), "false_show_R1_only": round(float(neg.shown_R1_only.mean()), 4),
                "false_show_v5_gate": round(float(neg.shown_gate_v5.mean()), 4),
                "false_show_perclass_gate": round(float(neg.shown_gate_perclass.mean()), 4),
                "pred_counts": neg.pred.value_counts().to_dict(), "median_detail": round(float(neg.detail.median()), 1)}
        pos = g[g.is_fruit == True]  # noqa: E712
        if len(pos):
            A[s]["positives"] = pos[["id", "content", "pred", "conf", "detail", "shown_gate_v5", "shown_gate_perclass"]].round(4).to_dict("records")
        log(f"A {s}: {A[s]['n_negative']} neg | false show R1-only {A[s]['false_show_R1_only']} v5 {A[s]['false_show_v5_gate']} "
            f"per-class {A[s]['false_show_perclass_gate']} | preds {A[s]['pred_counts']}")
    res["A_no_fruit_rejection"] = A

    # ---------------- B: banana_guava_quality (56td5w4wz2) grade set
    man = pd.read_csv(ROOT / "data/model3/manifest.csv")
    gq = man[man.source == "banana_guava_quality"].reset_index(drop=True)
    m1 = pd.concat([pd.read_csv(ROOT / f"data/splits/{s}.csv") for s in ("train", "val", "test")])
    bits = lambda hx: np.unpackbits(np.frombuffer(bytes.fromhex(hx), np.uint8))
    G = np.stack([bits(h) for h in gq.phash]); M = np.stack([bits(h) for h in m1.phash])
    mind = np.array([np.min(np.count_nonzero(G[i] != M, axis=1)) for i in range(len(G))])
    brow = []
    for p, fr, sp, lab in zip(gq.path, gq.fruit, gq.split, gq.label):
        with Image.open(ROOT / "data/raw" / p) as im:
            x = cpg.model_input(cpg.frame_160x120(im.convert("RGB")))
        pf, _pc, _q = net(x)
        brow.append({"path": p, "fruit": fr, "split": sp, "grade": lab, "pred": FRUITS[int(pf.argmax())], "conf": float(pf.max()),
                     "detail": cpg.detail(x)})
    bd = pd.DataFrame(brow); bd["min_phash_dist_to_M1"] = mind
    bd.to_csv(OUT / "B_grade_set_routing.csv", index=False)
    B = {"provenance": "Mendeley 56td5w4wz2 v2, CC BY 4.0 (docs/MODEL3_DATASET_INSPECTION.md); fruit identity = dataset folder "
                       "(Banana/Guava); grade = Class_A/Class_B/Defect; 76 conflicting duplicates already removed (docs/MODEL3.md)",
         "n": {f: int((bd.fruit == f).sum()) for f in ("banana", "guava")},
         "near_duplicates_with_M1_splits_(pHash<=16_bits)": int((mind <= 16).sum()),
         "min_phash_distance_quantiles": {q: int(np.quantile(mind, q)) for q in (0.0, 0.01, 0.5)},
         "routing_device_path": {f: {"correct_rate": round(float((bd[bd.fruit == f].pred == f).mean()), 4),
                                     "pred_counts": bd[bd.fruit == f].pred.value_counts().to_dict(),
                                     "shown_v5_gate": round(float(((bd.fruit == f) & (bd.detail >= MIN_DETAIL) & (bd.conf >= R1)).sum()
                                                                  / (bd.fruit == f).sum()), 4),
                                     "by_split": {s: round(float((g.pred == f).mean()), 4) for s, g in bd[bd.fruit == f].groupby("split")},
                                     "by_grade": {s: round(float((g.pred == f).mean()), 4) for s, g in bd[bd.fruit == f].groupby("grade")}}
                                 for f in ("banana", "guava")}}
    res["B_grade_set"] = B
    log("B", json.dumps(B["routing_device_path"]), "near-dups:", B["near_duplicates_with_M1_splits_(pHash<=16_bits)"])

    # ---------------- E: stage heads from recorded TEST predictions (M3 frozen)
    pr = pd.read_csv(ROOT / "reports/model3/predictions_val_test.csv")
    order = {"Fresh": 0, "Semi-fresh": 1, "Rotten": 2}
    E = {}
    for task in ("stage_tomato", "stage_brinjal", "stage_banana"):
        t = pr[(pr.task == task) & (pr.split == "test") & pr.pred_label.notna()]
        d = (t.label.map(order) - t.pred_label.map(order)).abs()
        routed = t.m1_pred_fruit == t.fruit
        E[task] = {"n_test": int(len(t)), "exact": round(float((d == 0).mean()), 4), "off_by_1": round(float((d == 1).mean()), 4),
                   "off_by_2": round(float((d == 2).mean()), 4),
                   "rotten_predicted_fresh": int(((t.label == "Rotten") & (t.pred_label == "Fresh")).sum()),
                   "fresh_predicted_rotten": int(((t.label == "Fresh") & (t.pred_label == "Rotten")).sum()),
                   "exact_when_M1_routes_correctly": round(float((d[routed] == 0).mean()), 4),
                   "shelf_band_correct": "== exact stage (shelf band is a fixed lookup of the stage)"}
        log("E", task, E[task])
    res["E_stage_heads_TEST"] = E

    (OUT / "metrics.json").write_text(json.dumps(res, indent=1, default=str))
    log("saved", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
