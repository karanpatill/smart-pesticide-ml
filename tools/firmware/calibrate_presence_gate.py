"""Calibrate and evaluate the fruit-PRESENCE gate (offline, PC only, frozen model unchanged).

The frozen fruit model has no background / not-a-fruit class, so it always outputs one of 5 fruits. The gate decides
whether the device may show a fruit at all. Two independent conditions, BOTH required to show a fruit:
  1. image detail:  variance of the 3x3 Laplacian of the luminance of the 80x80 model input >= MIN_DETAIL
                    (an empty / defocused / featureless scene has little fine structure)
  2. confidence:    top fruit softmax >= 0.976 (existing R1 threshold, calibrated on VAL to separate correct from
                    incorrect fruit predictions; configs/model3_postprocess.json)
MIN_DETAIL rule (same style as configs/image_checks.json): 0.5 x the 0.5th percentile of the VAL split, measured through
the device camera format (centre 4:3 crop -> 160x120 RGB565 big-endian -> firmware preprocessing).
Evaluation (TEST split, real SWD camera frames, synthetic empty scenes, degraded variants) -> reports/firmware/presence_gate_eval.json
Writes configs/presence_gate.json. LIMITATION: no real photos of NON-fruit objects exist in this project.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/firmware"))
from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes  # noqa: E402
import image_quality as iq  # noqa: E402

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
R1 = json.loads((ROOT / "configs/model3_postprocess.json").read_text())["fruit_confidence_threshold"]


def frame_160x120(im: Image.Image) -> np.ndarray:
    w, h = im.size
    cw, ch = (h * 4 // 3, h) if w * 3 >= h * 4 else (w, w * 3 // 4)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return np.asarray(im.crop((x0, y0, x0 + cw, y0 + ch)).resize((160, 120), Image.BILINEAR), np.uint8)


def model_input(rgb160: np.ndarray) -> np.ndarray:
    return rgb565_to_input_int8(rgb888_to_rgb565_bytes(rgb160, big_endian=True), 160, 120, True)


def detail(x: np.ndarray) -> float:
    return iq.laplacian_var(iq.luminance(x.astype(np.float64) + 128.0))


class Model:
    def __init__(self):
        import tensorflow as tf
        it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                                 experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
        it.allocate_tensors()
        self.run = it.get_signature_runner()
        self.iname = list(self.run.get_input_details())[0]

    def fruit(self, x: np.ndarray):
        o = self.run(**{self.iname: x.reshape(1, 80, 80, 3)})
        p = (o["fruit"][0].astype(np.float64) + 128) / 256
        return FRUITS[int(np.argmax(p))], float(p.max())


def split_images(name: str) -> pd.DataFrame:
    d = pd.read_csv(ROOT / f"data/splits/{name}.csv")
    return d[[(ROOT / "data/raw" / p).exists() for p in d.path]].reset_index(drop=True)


def main() -> int:
    m = Model()
    # ---------------- calibration on VAL (device camera format)
    val = split_images("val")
    vdet = []
    for p in val.path:
        with Image.open(ROOT / "data/raw" / p) as im:
            vdet.append(detail(model_input(frame_160x120(im.convert("RGB")))))
    vdet = np.array(vdet)
    p05 = float(np.percentile(vdet, 0.5))
    min_detail = round(0.5 * p05, 2)
    gate = lambda d, c: d >= min_detail and c >= R1

    # ---------------- TEST evaluation: clean, blurred, dark
    te = split_images("test")
    rows = {"clean": [], "blur_r2": [], "dark_x0.25": []}
    for p, fr in zip(te.path, te.fruit):
        with Image.open(ROOT / "data/raw" / p) as im:
            base = frame_160x120(im.convert("RGB"))
        for k, img in (("clean", base),
                       ("blur_r2", np.asarray(Image.fromarray(base).filter(ImageFilter.GaussianBlur(2)), np.uint8)),
                       ("dark_x0.25", np.asarray(ImageEnhance.Brightness(Image.fromarray(base)).enhance(0.25), np.uint8))):
            x = model_input(img)
            lab, conf = m.fruit(x)
            rows[k].append({"fruit": fr, "pred": lab, "conf": conf, "detail": detail(x)})

    def summ(rs):
        n = len(rs)
        acc_det = sum(r["detail"] >= min_detail for r in rs) / n
        acc_r1 = sum(r["conf"] >= R1 for r in rs) / n
        shown = [r for r in rs if gate(r["detail"], r["conf"])]
        return {"n": n, "pass_detail": round(acc_det, 4), "pass_r1": round(acc_r1, 4), "fruit_shown_rate": round(len(shown) / n, 4),
                "accuracy_when_shown": round(sum(r["pred"] == r["fruit"] for r in shown) / len(shown), 4) if shown else None,
                "per_fruit_shown_rate": {f: round(sum(gate(r["detail"], r["conf"]) for r in rs if r["fruit"] == f) /
                                                   max(1, sum(r["fruit"] == f for r in rs)), 4) for f in FRUITS}}

    # ---------------- real SWD camera frames (labels from the user's description)
    real = []
    for d, desc in (("20261017T092139Z", "scene without recognizable fruit (blurry)"),
                    ("20261017T092315Z", "apple, strongly defocused"), ("20261017T094631Z", "apple, after refocus")):
        fb = (ROOT / "reports/firmware/live_capture" / d / "frame_a.bin").read_bytes()[:38400]
        x = rgb565_to_input_int8(np.frombuffer(fb, np.uint8), 160, 120, True)
        lab, conf = m.fruit(x)
        de = detail(x)
        real.append({"capture": d, "content": desc, "pred": lab, "conf": round(conf, 4), "detail": round(de, 2),
                     "pass_detail": de >= min_detail, "pass_r1": conf >= R1, "fruit_shown": gate(de, conf)})

    # ---------------- synthetic empty / featureless scenes (no fruit by construction)
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:120, 0:160]
    synth = {"uniform_grey": np.full((120, 160, 3), 128, np.uint8),
             "dark_frame": np.full((120, 160, 3), 8, np.uint8),
             "smooth_gradient": np.stack([xx * 1.5, yy * 2.0, xx + yy], -1).clip(0, 255).astype(np.uint8),
             "smooth_gradient_with_sensor_noise": (np.stack([xx * 1.5, yy * 2.0, xx + yy], -1) + rng.normal(0, 2, (120, 160, 3))).clip(0, 255).astype(np.uint8),
             "blurred_wall_like": np.asarray(Image.fromarray((rng.uniform(80, 200, (120, 160, 3))).astype(np.uint8)).filter(ImageFilter.GaussianBlur(8)), np.uint8)}
    syn = []
    for k, img in synth.items():
        x = model_input(img)
        lab, conf = m.fruit(x)
        de = detail(x)
        syn.append({"scene": k, "pred": lab, "conf": round(conf, 4), "detail": round(de, 3), "fruit_shown": gate(de, conf)})

    out = {"LABEL": "Offline evaluation of a presence gate for the frozen 5-class fruit model. Proxy frames = public test images converted "
                    "to the device camera format; real frames = 3 SWD captures. NOT a trained not-a-fruit detector.",
           "rule": {"min_detail": min_detail, "min_detail_rule": "0.5 x 0.5th percentile of VAL (camera-format) Laplacian variance",
                    "val_n": int(len(vdet)), "val_detail_p0_5": round(p05, 2), "val_detail_median": round(float(np.median(vdet)), 2),
                    "r1_threshold": R1, "fruit_shown_if": "detail >= min_detail AND confidence >= r1_threshold"},
           "test_proxy": {k: summ(v) for k, v in rows.items()}, "real_camera_frames": real, "synthetic_empty_scenes": syn,
           "missing_evidence": ["no real photos of non-fruit objects", "only 3 real camera frames (1 without fruit, 2 apple)",
                                "no real frames of banana, guava, tomato, brinjal from the device camera"]}
    (ROOT / "reports/firmware/presence_gate_eval.json").write_text(json.dumps(out, indent=1))
    (ROOT / "configs/presence_gate.json").write_text(json.dumps({
        "version": 1, "min_detail_laplacian_var": min_detail, "fruit_confidence_threshold": R1,
        "detail_definition": "variance of [[0,1,0],[1,-4,1],[0,1,0]] Laplacian of luminance (0.299R+0.587G+0.114B) of the 80x80 model input, valid region",
        "derivation": out["rule"], "evaluation": "reports/firmware/presence_gate_eval.json"}, indent=1))
    print(json.dumps({"rule": out["rule"], "test_proxy": {k: {kk: vv for kk, vv in v.items() if kk != "per_fruit_shown_rate"} for k, v in out["test_proxy"].items()},
                      "real": real, "synthetic": syn}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
