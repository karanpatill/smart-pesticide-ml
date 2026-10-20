"""Build the INT8 PRESENCE CANDIDATE: frozen combined graph (models/model3/model3_combined.keras, read-only) + a 9th
output `presence` = softmax([0, logit']) where logit' is the background-head logistic logit on the shared `gap`
features, standardisation folded into the weights and the VAL-selected threshold folded into the bias
(decision p_fruit >= 0.5  <=>  int8 q[1] >= 0). Conversion settings and representative set are IDENTICAL to
scripts/tflite_feasibility.py (which produced the frozen combined_int8.tflite).

Checks: the 8 existing outputs must be bit-identical to the frozen INT8 model (BUILTIN_REF) on held-out inputs;
presence evaluated on held-out TEST fruit images, TEST clean background patches, synthetic fields and real device frames.
Writes NEW files only: models/candidates/presence_int8_<UTC>/ and reports/experiments/presence_int8_<UTC>/.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "tools/firmware")); sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_presence_gate as cpg  # noqa: E402
from fruitvision.camera_preprocess import rgb565_to_input_int8  # noqa: E402
from fruitvision.training import cached_images  # noqa: E402

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
FROZEN = ROOT / "models/experimental/tflite/combined_int8.tflite"
HEAD = sorted((ROOT / "models/candidates").glob("background_head_*/background_head.npz"))[-1]
TS = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
CAND = ROOT / "models/candidates" / f"presence_int8_{TS}"; CAND.mkdir(parents=True)
REP = ROOT / "reports/experiments" / f"presence_int8_{TS}"; REP.mkdir(parents=True)
LOG = open(REP / "log.txt", "w", encoding="utf-8")
MIN_DETAIL = json.loads((ROOT / "configs/presence_gate.json").read_text())["min_detail_laplacian_var"]
R1 = 0.976


def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.write(s + "\n"); LOG.flush()


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Ref:
    def __init__(self, model_bytes):
        import tensorflow as tf
        it = tf.lite.Interpreter(model_content=model_bytes,
                                 experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
        it.allocate_tensors()
        self.run = it.get_signature_runner(); self.iname = list(self.run.get_input_details())[0]

    def __call__(self, x):
        return {k: v[0].astype(np.int16) for k, v in self.run(**{self.iname: x.reshape(1, 80, 80, 3)}).items()}


def main() -> int:
    import tensorflow as tf
    src = ROOT / "models/model3/model3_combined.keras"
    h0 = {p: sha(p) for p in (src, FROZEN, ROOT / "models/model1/model1_final.keras")}
    log("read-only sources:", {Path(k).name: v[:16] for k, v in h0.items()}, "head:", HEAD)
    hd = np.load(HEAD)
    mu, sd, coef, b, thr = hd["mean"], hd["scale"], hd["coef"], float(hd["intercept"][0]), float(hd["threshold"])
    w = coef / sd
    bias = b - float(np.sum(coef * mu / sd)) - float(np.log(thr / (1 - thr)))      # threshold folded: decision at p=0.5
    log(f"folded head: |w|max {np.abs(w).max():.4f} bias {bias:.4f} (VAL threshold {thr:.5f} -> 0.5)")

    base = tf.keras.models.load_model(src, compile=False)
    gap = base.get_layer("gap").output
    k = np.zeros((gap.shape[-1], 2), np.float32); k[:, 1] = w
    dense = tf.keras.layers.Dense(2, activation="softmax", name="presence")
    pres = dense(gap)
    outs = dict(base.output); outs["presence"] = pres
    cand = tf.keras.Model(base.inputs, outs, name="combined_presence")
    dense.set_weights([k, np.array([0.0, bias], np.float32)])

    # sanity: Keras presence == logistic head on model1_final gap features (same weights inside the combined graph)
    m1 = tf.keras.models.load_model(ROOT / "models/model1/model1_final.keras", compile=False)
    g1 = tf.keras.Model(m1.inputs, m1.get_layer("gap").output)
    xs = np.random.default_rng(0).uniform(0, 255, (8, 80, 80, 3)).astype(np.float32)
    gc = tf.keras.Model(base.inputs, gap).predict(xs, verbose=0)
    log("gap(model3_combined) vs gap(model1_final) max abs diff:", float(np.abs(gc - g1.predict(xs, verbose=0)).max()))

    # representative set: IDENTICAL to scripts/tflite_feasibility.py
    m1tr = pd.read_csv(ROOT / "data/splits/train.csv")[["path", "fruit", "condition"]]
    man = pd.read_csv(ROOT / "data/model3/manifest.csv")
    m3tr = man[(man.split == "train") & (man.split_origin == "new_group_split")][["path", "task"]]
    rep = pd.concat([m1tr.groupby(["fruit", "condition"]).sample(30, random_state=0)[["path"]],
                     m3tr.groupby("task").sample(20, random_state=0)[["path"]]]).drop_duplicates("path")
    xr = cached_images(list(rep.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype(np.float32)

    def repgen():
        for i in range(len(xr)):
            yield [xr[i:i + 1]]

    with tempfile.TemporaryDirectory() as tmp:
        cand.export(tmp)
        conv = tf.lite.TFLiteConverter.from_saved_model(tmp)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = repgen
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        i8 = conv.convert()
    out_model = CAND / "combined_presence_int8.tflite"
    out_model.write_bytes(i8)
    log("candidate tflite:", out_model, len(i8), "B", sha(out_model)[:16], "| frozen", FROZEN.stat().st_size, "B")

    frozen, cnd = Ref(FROZEN.read_bytes()), Ref(i8)
    it = tf.lite.Interpreter(model_content=i8); sig = it.get_signature_runner().get_output_details()
    log("presence output quantization:", sig["presence"]["quantization"], "| fruit:", sig["fruit"]["quantization"])

    # ---------------- held-out inputs (device path)
    te = cpg.split_images("test").merge(pd.read_csv(ROOT / "data/interim/masks/masks.csv"), on="path", how="left")
    X, kind, fruit, ids = [], [], [], []
    for p, f, mf in zip(te.path, te.fruit, te["mask"]):
        with Image.open(ROOT / "data/raw" / p) as im, Image.open(ROOT / "data/interim/masks" / mf) as mk:
            rgb = im.convert("RGB"); wd, ht = rgb.size
            X.append(cpg.model_input(cpg.frame_160x120(rgb))); kind.append("test_fruit"); fruit.append(f); ids.append(p)
            mask = np.asarray(mk.convert("L").resize((wd, ht), Image.NEAREST)) > 127
            s = int(0.35 * min(wd, ht))
            for cx, cy in ((0, 0), (wd - s, 0), (0, ht - s), (wd - s, ht - s)):
                if mask[cy:cy + s, cx:cx + s].mean() < 0.02:
                    X.append(cpg.model_input(cpg.frame_160x120(rgb.crop((cx, cy, cx + s, cy + s)))))
                    kind.append("test_background"); fruit.append(""); ids.append(f"{p}@{cx},{cy}")
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:120, 0:160]
    for i in range(100):
        a, c = rng.uniform(0, 255, 3), rng.uniform(0, 255, 3)
        t = (xx / 160 * rng.uniform(0, 1) + yy / 120 * rng.uniform(0, 1))[..., None]
        X.append(cpg.model_input(np.clip(a * (1 - t) + c * t + rng.normal(0, 2, (120, 160, 3)), 0, 255).astype(np.uint8)))
        kind.append("synthetic"); fruit.append(""); ids.append(f"syn{i}")
    for d in sorted((ROOT / "reports/firmware/device_capture").iterdir()):
        sharp = "reposition" in d.name or "focus_loop_12" in d.name
        X.append(np.fromfile(d / "model_input.int8", np.int8).reshape(80, 80, 3))
        kind.append("device_fruit" if sharp else "device_nofruit"); fruit.append("banana" if sharp else ""); ids.append(d.name)
    for d, sharp, f in (("20261017T092139Z", False, ""), ("20261017T092315Z", False, ""), ("20261017T094631Z", True, "apple")):
        fb = (ROOT / "reports/firmware/live_capture" / d / "frame_a.bin").read_bytes()[:38400]
        X.append(rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True).reshape(80, 80, 3))
        kind.append("device_fruit" if sharp else "device_nofruit"); fruit.append(f); ids.append(d)
    log("inputs:", pd.Series(kind).value_counts().to_dict())

    rows, mismatch = [], 0
    for x, kd, f, i in zip(X, kind, fruit, ids):
        a, c = frozen(x), cnd(x)
        same = all(np.array_equal(a[h], c[h]) for h in a)
        mismatch += not same
        pf = (c["fruit"] + 128) / 256
        rows.append({"id": i, "kind": kd, "fruit": f, "pred": FRUITS[int(np.argmax(pf))], "conf": float(pf.max()),
                     "presence_q1": int(c["presence"][1]), "p_fruit": float((c["presence"][1] + 128) / 256),
                     "detail": cpg.detail(x), "existing_8_outputs_identical": same})
    df = pd.DataFrame(rows)
    df["present_head"] = df.presence_q1 >= 0
    df["shown_v5"] = (df.detail >= MIN_DETAIL) & (df.conf >= R1)
    df["shown_cand"] = df.shown_v5 & df.present_head
    df.to_csv(REP / "presence_eval.csv", index=False)
    log(f"existing 8 outputs bit-identical to frozen INT8 (REF): {len(df) - mismatch}/{len(df)}")

    def rate(m, col):
        return round(float(df.loc[m, col].mean()), 4) if m.any() else None

    res = {"label": "INT8 presence candidate (BUILTIN_REF = STM32-parity kernels); NOT deployed", "candidate_model": str(out_model.relative_to(ROOT)),
           "candidate_sha256": sha(out_model), "size_bytes": len(i8), "frozen_size_bytes": FROZEN.stat().st_size,
           "existing_outputs_bit_identical": f"{len(df) - mismatch}/{len(df)}", "head_source": str(HEAD.relative_to(ROOT)),
           "decision": "present if int8 presence[1] >= 0 (p_fruit >= 0.5 after folding the VAL threshold)"}
    for kd in ("test_fruit", "test_background", "synthetic", "device_fruit", "device_nofruit"):
        m = df.kind == kd
        res[kd] = {"n": int(m.sum()), "head_accepts": rate(m, "present_head"), "shown_v5_gate": rate(m, "shown_v5"),
                   "shown_v5_gate_plus_head": rate(m, "shown_cand")}
    m = df.kind == "test_fruit"
    res["test_fruit_per_class"] = {f: {"n": int((m & (df.fruit == f)).sum()), "head_accepts": rate(m & (df.fruit == f), "present_head"),
                                       "shown_v5": rate(m & (df.fruit == f), "shown_v5"), "shown_cand": rate(m & (df.fruit == f), "shown_cand"),
                                       "acc_when_shown_cand": round(float((df[m & (df.fruit == f) & df.shown_cand].pred == f).mean()), 4)
                                       if (m & (df.fruit == f) & df.shown_cand).any() else None} for f in FRUITS}
    res["test_fruit_acc_when_shown"] = {"v5": round(float((df[m & df.shown_v5].pred == df[m & df.shown_v5].fruit).mean()), 4),
                                        "candidate": round(float((df[m & df.shown_cand].pred == df[m & df.shown_cand].fruit).mean()), 4)}
    res["device_frames"] = df[df.kind.str.startswith("device")][["id", "kind", "pred", "conf", "p_fruit", "detail", "shown_v5", "shown_cand"]].round(4).to_dict("records")
    for kd in ("test_fruit", "test_background", "synthetic", "device_fruit", "device_nofruit"):
        log(kd, res[kd])
    log("per-class", json.dumps(res["test_fruit_per_class"]))
    log("acc when shown", res["test_fruit_acc_when_shown"])

    # parity fixture for the C (TFLM host32) check: 40 held-out inputs + Python REF outputs of all 9 heads
    pick = pd.concat([df[df.kind == "test_fruit"].sample(20, random_state=0), df[df.kind == "test_background"].sample(10, random_state=0),
                      df[df.kind.str.startswith("device")]]).index[:40]
    fx = CAND / "parity_fixture"; fx.mkdir()
    exp = []
    for j, i in enumerate(pick):
        X[i].astype(np.int8).tofile(fx / f"in_{j:02d}.int8")
        o = cnd(X[i]); exp.append({"file": f"in_{j:02d}.int8", "id": ids[i], "outputs": {h: o[h].tolist() for h in o}})
    (fx / "expected_python_ref.json").write_text(json.dumps(exp))
    h1 = {p: sha(p) for p in h0}
    res["read_only_sources_unchanged"] = h0 == h1
    (REP / "metrics.json").write_text(json.dumps(res, indent=1))
    (CAND / "README.json").write_text(json.dumps({"what": "frozen combined INT8 graph + presence (background-rejection) output",
                                                  "status": "CANDIDATE, not deployed", "report": str(REP.relative_to(ROOT)),
                                                  "sha256": res["candidate_sha256"]}, indent=1))
    log("sources unchanged:", res["read_only_sources_unchanged"], "| saved", CAND, REP)
    return 0 if res["read_only_sources_unchanged"] else 1


if __name__ == "__main__":
    sys.exit(main())
