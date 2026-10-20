"""Measure INT8 TFLite size and estimate peak activation RAM for candidate
MobileNetV2 configurations — WITHOUT any training data.

The model is calibrated on random noise, so this measures FOOTPRINT ONLY
(flash size, tensor sizes). It says nothing about accuracy.

Peak RAM estimate = max over ops of (sum of input + output activation bytes).
This is a lower bound on the TFLM/X-CUBE-AI tensor arena; real arena use is
higher (scratch buffers, alignment, runtime). Treat as a screening tool and
confirm with STM32Cube.AI 'Analyze'.

Usage:
  python scripts/model_budget.py
  python scripts/model_budget.py --sizes 64 96 --alphas 0.35 0.5
"""

from __future__ import annotations

import argparse
import tempfile

import numpy as np
import tensorflow as tf

from fruitvision.models.mobilenet import build_model

FLASH_KB, SRAM_KB = 512, 192


def convert_int8(model: tf.keras.Model, size: int) -> bytes:
    rng = np.random.default_rng(0)

    def rep():
        for _ in range(20):
            yield [rng.uniform(0, 255, (1, size, size, 3)).astype(np.float32)]

    with tempfile.TemporaryDirectory() as tmp:
        model.export(tmp)
        conv = tf.lite.TFLiteConverter.from_saved_model(tmp)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = rep
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        return conv.convert()


def peak_activation_bytes(tflite_model: bytes) -> int:
    interp = tf.lite.Interpreter(model_content=tflite_model)
    interp.allocate_tensors()
    tensors = {t["index"]: t for t in interp.get_tensor_details()}
    # Activations = tensors produced by an op, plus the model input; the
    # remaining op inputs are constant weights/biases living in flash.
    produced = {i for op in interp._get_ops_details() for i in op["outputs"]}
    produced |= {d["index"] for d in interp.get_input_details()}
    peak = 0
    for op in interp._get_ops_details():
        ids = [i for i in list(op["inputs"]) + list(op["outputs"]) if i in produced]
        b = sum(int(np.prod(tensors[i]["shape"])) * np.dtype(tensors[i]["dtype"]).itemsize for i in ids)
        peak = max(peak, b)
    return peak


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="+", default=[96, 128])
    ap.add_argument("--alphas", type=float, nargs="+", default=[0.35, 0.5])
    ap.add_argument("--fruits", type=int, default=5)
    ap.add_argument("--conditions", type=int, default=2)
    ap.add_argument("--cuts", nargs="+", default=["none"],
                    help="backbone cut layers to try; 'none' = full backbone")
    args = ap.parse_args()

    rows = []
    for size in args.sizes:
        for alpha in args.alphas:
            for cut in args.cuts:
                # weights=None: footprint does not depend on weight values.
                model = build_model(args.fruits, args.conditions, size, alpha, weights=None,
                                    cut_layer=None if cut == "none" else cut)
                tfl = convert_int8(model, size)
                rows.append((size, alpha, cut, model.count_params(), len(tfl) / 1024,
                             peak_activation_bytes(tfl) / 1024))
                tf.keras.backend.clear_session()

    print(f"\nSTM32F407VET6: {FLASH_KB} KB flash, {SRAM_KB} KB SRAM (both shared with firmware)\n")
    print(f"{'input':>6} {'alpha':>6} {'cut':>22} {'params':>10} {'int8 KB':>9} {'flash %':>8} {'peak act KB*':>13} {'SRAM %':>7}")
    for size, alpha, cut, params, kb, act in rows:
        print(f"{size:>6} {alpha:>6} {cut:>22} {params:>10,} {kb:>9.0f} {kb / FLASH_KB:>8.0%} {act:>13.0f} {act / SRAM_KB:>7.0%}")
    print("\n* lower-bound estimate (largest single op's in+out activations). Confirm with STM32Cube.AI.")


if __name__ == "__main__":
    main()
