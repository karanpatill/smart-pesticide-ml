"""Realism / data-quality audit of the SYNTHETIC Model 2 dataset (before training).

Checks:
  1. class balance (overall and per session)
  2. feature distributions by class (+ histograms)
  3. MQ135 realism vs the real Zenodo 17285312 e-nose data (storage-day drift)
  4. correlations (Spearman) between features, target and latent truth
  5. leakage: column roles, duplicates, aux/meta association with the target
  6. single-feature separability (grouped CV, depth-2 tree), flag > config limit
  7. Model 1 aux-only proxy check (grouped CV), flag > config limit

Writes reports/model2/audit/. All results describe SYNTHETIC data.

Usage:
  python scripts/model2_audit.py
"""

from __future__ import annotations

import glob
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import make_column_transformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

from fruitvision.config import load_yaml, resolve
from fruitvision.sensor.synthetic import AUX_COLS, GROUP_COL, SENSOR_COLS, TARGET_COL

CLASSES = ["LOW", "MEDIUM", "HIGH"]


def grouped_cv(model, X, y, groups, seed=42):
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    p = cross_val_predict(model, X, y, groups=groups, cv=cv)
    return {"accuracy": round(float(accuracy_score(y, p)), 4),
            "macro_f1": round(float(f1_score(y, p, average="macro")), 4)}


def main() -> None:
    cfg = load_yaml("configs/model2_synthetic.yaml")
    df = pd.read_csv(resolve(f"data/synthetic/model2/model2_synthetic_v{cfg['version']}.csv"))
    out = resolve("reports/model2/audit")
    out.mkdir(parents=True, exist_ok=True)
    y, g = df[TARGET_COL], df[GROUP_COL]
    res = {"SYNTHETIC": "All numbers describe synthetic prototype data, not real sensors or pesticides."}
    flags = []

    # 1. class balance
    res["class_balance"] = {"noisy_label": df[TARGET_COL].value_counts(normalize=True).round(4).to_dict(),
                            "clean_latent": df.latent_risk_clean.value_counts(normalize=True).round(4).to_dict(),
                            "label_noise_realised": round(float(df.latent_label_flipped.mean()), 4)}
    per_sess = df.groupby(GROUP_COL)[TARGET_COL].value_counts(normalize=True).unstack(fill_value=0)
    res["class_balance"]["per_session_share_p5_p95"] = {c: [round(float(per_sess[c].quantile(.05)), 3),
                                                            round(float(per_sess[c].quantile(.95)), 3)]
                                                        for c in CLASSES}

    # 2. distributions
    desc = df.groupby(TARGET_COL)[SENSOR_COLS + ["aux_m1_p_spoiled"]].describe().T.round(2)
    desc.to_csv(out / "feature_distributions_by_class.csv")
    fig, axes = plt.subplots(3, 3, figsize=(14, 11))
    for ax, c in zip(axes.flat, SENSOR_COLS + ["aux_m1_p_spoiled"]):
        for k, col in zip(CLASSES, ["tab:green", "tab:orange", "tab:red"]):
            ax.hist(df.loc[y == k, c], bins=40, alpha=0.5, density=True, label=k, color=col)
        ax.set_title(c)
    axes.flat[0].legend()
    fig.suptitle("SYNTHETIC Model 2 data — feature distributions by (noisy) risk label")
    fig.tight_layout(); fig.savefig(out / "feature_histograms.png", dpi=100); plt.close(fig)

    # 3. MQ135 realism vs real e-nose data (median ratio day d / day 1)
    real = {}
    for f in ("Banana", "Tomato"):
        meds = {}
        for path in glob.glob(str(resolve(f"data/raw/enose_freshness_zenodo/extracted/AllSmaples-Report/{f} D*.csv"))) + \
                glob.glob(str(resolve(f"data/raw/enose_freshness_zenodo/extracted/AllSmaples-Report/{f.lower()} D*.csv"))):
            d = int(path.rsplit("D", 1)[1].split(".")[0])
            meds[d] = float(pd.read_csv(path)["MQ135"].median())
        real[f.lower()] = {d: round(meds[d] / meds[1], 2) for d in sorted(meds)}
    syn = {}
    for f in ("banana", "tomato"):
        s = df[df.latent_fruit == f].groupby("latent_storage_day").sensor_mq135.median()
        syn[f] = {int(d): round(float(v / s.loc[1]), 2) for d, v in s.items()}
    res["mq135_day_ratio_real_vs_synthetic"] = {"real_zenodo": real, "synthetic": syn,
                                                 "note": "synthetic includes T/RH/session variation absent from the lab recordings"}
    res["mq135_spoilage_vs_risk_effect"] = {
        "median_ratio_spoiled_over_fresh": round(float(df[df.latent_spoiled].sensor_mq135.median()
                                                       / df[~df.latent_spoiled].sensor_mq135.median()), 3),
        "median_ratio_HIGH_over_LOW_clean": round(float(df[df.latent_risk_clean == "HIGH"].sensor_mq135.median()
                                                        / df[df.latent_risk_clean == "LOW"].sensor_mq135.median()), 3)}

    # 4. correlations
    num = df[SENSOR_COLS + ["aux_m1_p_spoiled"]].copy()
    num["target_ordinal"] = df[TARGET_COL].map({c: i for i, c in enumerate(CLASSES)})
    num["latent_risk_score"] = df.latent_risk_score
    num["latent_spoiled"] = df.latent_spoiled.astype(int)
    num["latent_storage_day"] = df.latent_storage_day
    corr = num.corr(method="spearman").round(3)
    corr.to_csv(out / "spearman_correlations.csv")
    fig, ax = plt.subplots(figsize=(11, 9))
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr)), corr.columns, rotation=60, ha="right"); ax.set_yticks(range(len(corr)), corr.index)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im); ax.set_title("SYNTHETIC — Spearman correlations"); fig.tight_layout()
    fig.savefig(out / "spearman_correlations.png", dpi=100); plt.close(fig)
    res["target_spearman"] = corr["target_ordinal"].drop("target_ordinal").round(3).to_dict()

    # 5. leakage
    feature_cols = SENSOR_COLS + AUX_COLS
    res["leakage"] = {
        "feature_columns": feature_cols,
        "no_target_or_latent_in_features": not any(c.startswith(("target_", "latent_", "meta_")) for c in feature_cols),
        "duplicate_feature_rows": int(df.duplicated(subset=feature_cols).sum()),
        "target_vs_device_unit_crosstab": pd.crosstab(df.meta_device_unit, df[TARGET_COL], normalize="index").round(3).to_dict(),
        "target_vs_aux_fruit_crosstab": pd.crosstab(df.aux_m1_fruit, df[TARGET_COL], normalize="index").round(3).to_dict(),
        "target_vs_aux_condition_crosstab": pd.crosstab(df.aux_m1_condition, df[TARGET_COL], normalize="index").round(3).to_dict(),
    }

    # 6. single-feature separability
    single = {}
    limit = cfg["checks"]["max_single_feature_accuracy"]
    extra = {"ratio_tcs_b_over_c": df.sensor_tcs_b / df.sensor_tcs_c,
             "ratio_tcs_r_over_c": df.sensor_tcs_r / df.sensor_tcs_c}
    for name, col in [(c, df[c]) for c in SENSOR_COLS + ["aux_m1_p_spoiled"]] + list(extra.items()):
        r = grouped_cv(DecisionTreeClassifier(max_depth=2, random_state=0), col.to_frame(), y, g)
        r["flag"] = r["accuracy"] > limit
        single[name] = r
        if r["flag"]:
            flags.append(f"single feature '{name}' grouped-CV accuracy {r['accuracy']} > {limit}")
    res["single_feature_depth2_tree_grouped_cv"] = single
    res["majority_baseline_accuracy"] = round(float(y.value_counts(normalize=True).max()), 4)

    # 7. aux-only proxy check
    pre = make_column_transformer((OneHotEncoder(handle_unknown="ignore"), ["aux_m1_fruit", "aux_m1_condition"]),
                                  (StandardScaler(), ["aux_m1_p_spoiled"]))
    aux = grouped_cv(make_pipeline(pre, LogisticRegression(max_iter=2000, class_weight="balanced")),
                     df[AUX_COLS], y, g)
    aux["flag"] = aux["macro_f1"] > cfg["checks"]["max_aux_only_macro_f1"]
    if aux["flag"]:
        flags.append(f"Model 1 aux features alone reach macro-F1 {aux['macro_f1']} (proxy risk)")
    res["aux_only_proxy_check_logreg_grouped_cv"] = aux
    res["clean_label_ceiling_accuracy"] = round(float((df[TARGET_COL] == df.latent_risk_clean).mean()), 4)

    res["flags"] = flags
    (out / "audit.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: res[k] for k in ("class_balance", "mq135_day_ratio_real_vs_synthetic",
                                           "mq135_spoilage_vs_risk_effect", "target_spearman",
                                           "single_feature_depth2_tree_grouped_cv", "majority_baseline_accuracy",
                                           "aux_only_proxy_check_logreg_grouped_cv", "clean_label_ceiling_accuracy",
                                           "flags")}, indent=1, default=str))
    print("duplicates:", res["leakage"]["duplicate_feature_rows"], "| no target/latent in features:",
          res["leakage"]["no_target_or_latent_in_features"])


if __name__ == "__main__":
    main()
