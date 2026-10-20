"""Model 2 runtime from the exported JSON (pure numpy, no sklearn/joblib needed).

SYNTHETIC PROTOTYPE: fitted on synthetic data only. Outputs an estimated risk
category; it is not a pesticide measurement.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

RAW_KEYS = ["tcs_r", "tcs_g", "tcs_b", "tcs_c", "mq135", "ph", "temp_c", "humidity_pct"]


class Model2:
    def __init__(self, spec_path: str | Path):
        self.spec = json.loads(Path(spec_path).read_text())
        s = self.spec
        self.classes = s["classes"]
        self.mean, self.scale = np.array(s["scaler_mean"]), np.array(s["scaler_scale"])
        self.coef, self.intercept = np.array(s["coef"]), np.array(s["intercept"])

    @staticmethod
    def features(raw: np.ndarray) -> np.ndarray:
        """raw: (n, 8) in RAW_KEYS order -> (n, 12) in export feature order."""
        r, g, b, c, mq = raw[:, 0], raw[:, 1], raw[:, 2], raw[:, 3], raw[:, 4]
        return np.column_stack([raw, r / c, g / c, b / c, np.log(mq)])

    def predict_proba(self, raw: np.ndarray) -> np.ndarray:
        z = (self.features(np.atleast_2d(np.asarray(raw, dtype=np.float64))) - self.mean) / self.scale
        logits = z @ self.coef.T + self.intercept
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)
