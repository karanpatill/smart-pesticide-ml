"""Calibrate image-check thresholds on REAL public-dataset images (no training).

Computes content statistics on the 80x80 model input for every image used by
Model 1 / Model 3 (data/splits/*.csv + data/model3/manifest.csv, deduplicated),
then places REJECT thresholds outside the observed real-image range:
    reject if stat < (observed minimum) * safety   (safety = 0.5)
so no calibration image is rejected by construction. WARN thresholds use the
0.5 / 99.5 percentiles (informational only, never reject).

Output: configs/image_checks.json, reports/audit/image_check_calibration.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fruitvision.training import cached_images  # noqa: E402
from fruitvision.validation.image_checks import content_stats  # noqa: E402

SAFETY = 0.5


def main() -> None:
    paths = pd.concat([pd.read_csv(ROOT / f"data/splits/{s}.csv").path for s in ("train", "val", "test")]
                      + [pd.read_csv(ROOT / "data/model3/manifest.csv").path]).drop_duplicates().tolist()
    x = cached_images(paths, ROOT / "data/raw", 80, ROOT / "data/interim/cache")
    st = pd.DataFrame([content_stats(a.astype(np.float32)) for a in x])
    desc = st.describe(percentiles=[0.001, 0.005, 0.01, 0.5, 0.99, 0.995, 0.999]).round(4)
    cfg = {
        "version": 1,
        "calibration": {"n_real_images": len(st), "safety_factor": SAFETY,
                        "rule": "reject threshold = observed real-image minimum x safety factor",
                        "script": "scripts/calibrate_image_checks.py"},
        "dimensions": {"reject_min_side": 32, "warn_min_side": 80, "reject_max_side": 12000,
                       "warn_aspect_ratio": 1.34,
                       "rationale": "32 px: below this a fruit cannot be represented; 80 px = model input; "
                                    "12000 px guards against decompression bombs; 1.34 ~ 4:3 camera frames"},
        "reject": {"lum_std_below": round(float(st.lum_std.min()) * SAFETY, 3),
                   "lag1_autocorr_below": round(float(st.lag1_autocorr.min()) * SAFETY, 3),
                   "chroma_below": round(float(st.chroma_mean_abs.min()) * SAFETY, 3)},
        "warn": {"lum_mean_below": round(float(st.lum_mean.quantile(0.005)), 2),
                 "lum_mean_above": round(float(st.lum_mean.quantile(0.995)), 2),
                 "clipped_fraction_above": round(max(0.25, float(st.clipped_fraction.quantile(0.995))), 3)},
        "observed_real": {c: {"min": float(st[c].min()), "p0.5": float(st[c].quantile(0.005)),
                              "median": float(st[c].median()), "max": float(st[c].max())} for c in st.columns},
    }
    (ROOT / "configs/image_checks.json").write_text(json.dumps(cfg, indent=2))
    (ROOT / "reports/audit").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports/audit/image_check_calibration.json").write_text(desc.to_json(indent=2))
    print(json.dumps({k: cfg[k] for k in ("calibration", "reject", "warn")}, indent=1))
    print(desc.to_string())


if __name__ == "__main__":
    main()
