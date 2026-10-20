"""OFFLINE PROXY (not real-camera validation): accuracy of the INT8 model when public test images are pushed
through the 160x120 RGB565 camera format the ENTC firmware uses (STATIC evidence, docs/CAMERA_ML_INTEGRATION_PLAN.md).

Variants on the Model 1 TEST split (1,012 public images, INT8 TFLite):
  A   training preprocessing (reference; same as reports/stm32_memory/camera_pipeline_proxy.json variant A)
  B96 previous firmware proxy: centre square -> 96x96 -> RGB565 -> firmware preprocess (re-run here for comparison)
  D   ENTC format proxy: centre 4:3 crop -> 160x120 (PIL bilinear, stand-in for the OV2640 scaler)
      -> RGB565 big-endian -> firmware preprocess (centre 120x120 -> 80x80, Q16 bilinear)
Not simulated: OV2640 optics, exposure, white balance, ISP, noise, and its real scaler; lighting and backgrounds
of the actual device. Use only to compare preprocessing paths.
Output: reports/firmware/camera_proxy_160x120.json (does not overwrite the earlier proxy report)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from PIL import Image
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes  # noqa: E402
from fruitvision.training import cached_images  # noqa: E402

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
CONDS = ["fresh", "spoiled"]


def fw_96(im):
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((96, 96), Image.BILINEAR)
    return rgb565_to_input_int8(rgb888_to_rgb565_bytes(np.asarray(im, np.uint8)), 96, 96)


def fw_160x120(im):
    w, h = im.size
    cw, ch = (h * 4 // 3, h) if w * 3 >= h * 4 else (w, w * 3 // 4)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    rgb = np.asarray(im.crop((x0, y0, x0 + cw, y0 + ch)).resize((160, 120), Image.BILINEAR), np.uint8)
    return rgb565_to_input_int8(rgb888_to_rgb565_bytes(rgb, big_endian=True), 160, 120, True)


def main() -> None:
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    xa = cached_images(list(te.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype(np.float32)
    x96, x160 = [], []
    for p in te.path:
        with Image.open(ROOT / "data/raw" / p) as im:
            im = im.convert("RGB")
            x96.append(fw_96(im).astype(np.float32) + 128.0)
            x160.append(fw_160x120(im).astype(np.float32) + 128.0)
    variants = {"A_training_preprocessing": xa, "B96_firmware_proxy_96_rgb565": np.stack(x96),
                "D_entc_format_160x120_rgb565_be": np.stack(x160)}
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    run = it.get_signature_runner()
    iname = list(run.get_input_details())[0]
    s, z = run.get_input_details()[iname]["quantization"]
    res = {"LABEL": "OFFLINE PROXY on public-dataset test images - NOT real-camera validation. OV2640 optics/ISP/scaler, "
                    "exposure and device lighting are not simulated.",
           "format_source": "STATIC evidence from the ENTC firmware binary (160x120 RGB565 big-endian)",
           "n": len(te), "model": "models/experimental/tflite/combined_int8.tflite"}
    base = None
    per_fruit = {}
    for name, x in variants.items():
        pf, pc = [], []
        for i in range(len(x)):
            q = np.clip(np.round(x[i:i + 1] / s + z), -128, 127).astype(np.int8)
            o = run(**{iname: q})
            pf.append(int(np.argmax(o["fruit"][0])))
            pc.append(int(np.argmax(o["condition"][0])))
        pf, pc = np.array(pf), np.array(pc)
        r = {"fruit_macro_f1": round(float(f1_score(te.fruit, np.array(FRUITS)[pf], average="macro")), 4),
             "condition_macro_f1": round(float(f1_score(te.condition, np.array(CONDS)[pc], average="macro")), 4),
             "fruit_accuracy": round(float((np.array(FRUITS)[pf] == te.fruit.values).mean()), 4)}
        if base is None:
            base = (pf, pc)
        else:
            r["fruit_agreement_with_A"] = round(float((pf == base[0]).mean()), 4)
            r["condition_agreement_with_A"] = round(float((pc == base[1]).mean()), 4)
        per_fruit[name] = {f: round(float((np.array(FRUITS)[pf][te.fruit.values == f] == f).mean()), 4) for f in FRUITS}
        res[name] = r
        print(name, r, flush=True)
    res["fruit_recall_per_class"] = per_fruit
    out = ROOT / "reports/firmware/camera_proxy_160x120.json"
    out.write_text(json.dumps(res, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
