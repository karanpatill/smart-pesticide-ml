"""Generate the SYNTHETIC Model 2 development dataset (pipeline prototype only).

Output: data/synthetic/model2/model2_synthetic_v1.csv  (+ datacard.json)
Refuses to overwrite an existing version: bump `version` in the config instead.

Usage:
  python scripts/model2_generate.py
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from fruitvision.config import load_yaml, resolve
from fruitvision.sensor.synthetic import AUX_COLS, GROUP_COL, SENSOR_COLS, TARGET_COL, generate


def main() -> None:
    cfg = load_yaml("configs/model2_synthetic.yaml")
    assert cfg["status"] == "approved_synthetic_prototype"
    out_dir = resolve("data/synthetic/model2")
    out = out_dir / f"model2_synthetic_v{cfg['version']}.csv"
    if out.exists():
        raise SystemExit(f"{out} exists; bump `version` in configs/model2_synthetic.yaml to regenerate.")
    out_dir.mkdir(parents=True, exist_ok=True)

    m1 = pd.read_csv(resolve(cfg["model1_aux"]["source"]))
    df = generate(cfg, m1)
    df.to_csv(out, index=False)
    card = {
        "SYNTHETIC": "Prototype development data. NOT real sensor readings. NOT pesticide measurements.",
        "file": str(out.relative_to(resolve("."))), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "rows": len(df), "sessions": int(df[GROUP_COL].nunique()),
        "columns": {"sensor_features": SENSOR_COLS, "model1_aux_features": AUX_COLS,
                    "target": TARGET_COL, "group": GROUP_COL,
                    "latent_diagnostics_never_features": [c for c in df if c.startswith("latent_")]},
        "target_distribution_noisy": df[TARGET_COL].value_counts().to_dict(),
        "target_distribution_clean": df["latent_risk_clean"].value_counts().to_dict(),
        "label_noise_realised": float(df.latent_label_flipped.mean()),
        "config": cfg,
    }
    (out_dir / f"datacard_v{cfg['version']}.json").write_text(json.dumps(card, indent=2, default=str))
    print(json.dumps({k: card[k] for k in ("rows", "sessions", "target_distribution_noisy",
                                            "target_distribution_clean", "label_noise_realised")}, indent=2))


if __name__ == "__main__":
    main()
