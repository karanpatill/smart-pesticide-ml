"""Unified inference for Keras (.keras) and TFLite (.tflite, float or INT8).

Both predictors take raw RGB images resized to the model input size with
pixel values 0..255 and return per-head probability arrays.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tensorflow as tf


class KerasPredictor:
    def __init__(self, path: str | Path):
        self.model = tf.keras.models.load_model(path)
        self.input_size = int(self.model.input_shape[1])

    def predict(self, images: np.ndarray) -> dict[str, np.ndarray]:
        out = self.model.predict(images.astype("float32"), verbose=0)
        return {k: np.asarray(v) for k, v in out.items()}


class TFLitePredictor:
    """Runs a TFLite model, handling int8/uint8 (de)quantisation."""

    def __init__(self, path: str | Path, head_names: dict[str, int] | None = None):
        self.interp = tf.lite.Interpreter(model_path=str(path))
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.outs = self.interp.get_output_details()
        self.input_size = int(self.inp["shape"][1])
        # Map outputs to heads by number of classes (fruit vs condition),
        # since TFLite output tensor names are not stable across converters.
        self.head_names = head_names or {}

    def _quant_in(self, x: np.ndarray) -> np.ndarray:
        dtype = self.inp["dtype"]
        if dtype == np.float32:
            return x.astype(np.float32)
        scale, zero = self.inp["quantization"]
        q = np.round(x / scale + zero)
        info = np.iinfo(dtype)
        return np.clip(q, info.min, info.max).astype(dtype)

    @staticmethod
    def _dequant(detail, y: np.ndarray) -> np.ndarray:
        if detail["dtype"] == np.float32:
            return y
        scale, zero = detail["quantization"]
        return (y.astype(np.float32) - zero) * scale

    def predict(self, images: np.ndarray) -> dict[str, np.ndarray]:
        results: dict[str, list[np.ndarray]] = {}
        for img in images:
            self.interp.set_tensor(self.inp["index"], self._quant_in(img[None]))
            self.interp.invoke()
            for d in self.outs:
                y = self._dequant(d, self.interp.get_tensor(d["index"]))[0]
                name = self.head_names.get(len(y), d["name"])
                results.setdefault(name, []).append(y)
        return {k: np.stack(v) for k, v in results.items()}


def load_predictor(path: str | Path, fruits: list[str], conditions: list[str]):
    path = Path(path)
    if path.suffix == ".tflite":
        if len(fruits) == len(conditions):
            raise ValueError("cannot map TFLite outputs when heads have equal sizes")
        return TFLitePredictor(path, {len(fruits): "fruit", len(conditions): "condition"})
    return KerasPredictor(path)


def load_image(path: str | Path, size: int) -> np.ndarray:
    """Same resize/crop as the training pipeline; returns float32 0..255."""
    from fruitvision.data.pipeline import decode_and_resize

    return decode_and_resize(tf.constant(str(path)), size).numpy()
