"""HOST PROXY: accuracy impact of the planned camera preprocessing path on the INT8 model.

Variants on the Model 1 TEST split (public-dataset images, INT8 TFLite, builtin kernels):
  A  training preprocessing (TF decode, aspect-preserving antialiased resize to 80, centre crop/pad)
  C  A + RGB565 colour quantisation (isolates the 5/6/5-bit effect)
  B  firmware path: PIL decode -> centre-square crop -> PIL bilinear resize to 96x96 (stand-in for the
     OV2640 DSP scaler) -> RGB565 -> firmware/image/preprocess_rgb565.c logic (96->80, Q16 bilinear)
The OV2640 optics, ISP, noise and its actual scaler filter are NOT simulated: this is a proxy only.

Usage: python tools/stm32_memory/camera_pipeline_proxy.py
"""

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


def q565(x: np.ndarray) -> np.ndarray:
    """RGB888 -> RGB565 -> RGB888 (bit replication), same expansion as the firmware."""
    x = x.astype(np.uint16)
    r, g, b = x[..., 0] >> 3, x[..., 1] >> 2, x[..., 2] >> 3
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)


def main() -> None:
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    xa = cached_images(list(te.path), ROOT / "data/raw", 80, ROOT / "data/interim/cache").astype(np.float32)
    xb = []
    for p in te.path:
        with Image.open(ROOT / "data/raw" / p) as im:
            im = im.convert("RGB")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((96, 96), Image.BILINEAR)
            src = rgb888_to_rgb565_bytes(np.asarray(im, np.uint8))
        xb.append(rgb565_to_input_int8(src, 96, 96).astype(np.float32) + 128.0)
    variants = {"A_training_preprocessing": xa, "C_training_plus_rgb565": q565(np.clip(np.round(xa), 0, 255)),
                "B_firmware_camera_proxy_96_rgb565": np.stack(xb)}

    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    run = it.get_signature_runner()
    iname = list(run.get_input_details())[0]
    s, z = run.get_input_details()[iname]["quantization"]
    res = {"NOTE": "HOST PROXY on public-dataset test images; OV2640 optics/ISP/scaler not simulated.",
           "n": len(te), "model": "models/experimental/tflite/combined_int8.tflite"}
    base = None
    for name, x in variants.items():
        pf, pc = [], []
        for i in range(len(x)):
            q = np.clip(np.round(x[i:i + 1] / s + z), -128, 127).astype(np.int8)
            o = run(**{iname: q})
            pf.append(int(np.argmax(o["fruit"][0]))); pc.append(int(np.argmax(o["condition"][0])))
        pf, pc = np.array(pf), np.array(pc)
        r = {"fruit_macro_f1": round(float(f1_score(te.fruit, np.array(FRUITS)[pf], average="macro")), 4),
             "condition_macro_f1": round(float(f1_score(te.condition, np.array(CONDS)[pc], average="macro")), 4)}
        if base is None:
            base = (pf, pc)
        else:
            r["fruit_agreement_with_A"] = round(float((pf == base[0]).mean()), 4)
            r["condition_agreement_with_A"] = round(float((pc == base[1]).mean()), 4)
        res[name] = r
        print(name, r, flush=True)
    out = ROOT / "reports/stm32_memory/camera_pipeline_proxy.json"
    out.write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
