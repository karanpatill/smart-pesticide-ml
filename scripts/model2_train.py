"""Model 2 prototype experiments on SYNTHETIC data.

ALL RESULTS ARE SYNTHETIC / PROTOTYPE PERFORMANCE. They measure how well each
model recovers the generator's own assumptions (configs/model2_synthetic.yaml).
They are NOT real pesticide-residue detection performance.

Protocol
  * Session-based split (meta_session_id): 70% / 15% / 15% of sessions ->
    train / val / test. Sessions never span two splits.
  * Feature sets:
      S   = sensor features (+ ratios/log derived ONLY from sensor features)
      S+A = S + Model 1 auxiliary features (fruit one-hot, condition one-hot, P(spoiled))
  * Models: Logistic Regression, SVM (linear and RBF), Random Forest, XGBoost.
    Small hyper-parameter grids chosen on VAL (fit on TRAIN).
  * 5-fold StratifiedGroupKFold CV (groups = sessions) on TRAIN+VAL with the
    chosen hyper-parameters -> mean ± sd.
  * Final refit on TRAIN+VAL, evaluated ONCE on TEST.
  * Baselines: majority class, Model 1 aux-only, strip-only (TCS features) LR.
  * Pre-registered selection rule (fixed before results): among S+A and S
    models, take those whose CV macro-F1 is within 0.02 of the best, then
    choose the smallest estimated MCU footprint.

Usage:
  python scripts/model2_train.py
"""

from __future__ import annotations

import json
import time

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             confusion_matrix, f1_score, precision_recall_fscore_support)
from sklearn.model_selection import GroupShuffleSplit, ParameterGrid, StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.svm import SVC
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from fruitvision.config import load_yaml, resolve
from fruitvision.sensor.synthetic import AUX_COLS, GROUP_COL, SENSOR_COLS, TARGET_COL

CLASSES = ["LOW", "MEDIUM", "HIGH"]
DERIVED = ["drv_tcs_r_over_c", "drv_tcs_g_over_c", "drv_tcs_b_over_c", "drv_log_mq135"]
TAG = "SYNTHETIC/PROTOTYPE"


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Derived features computed ONLY from sensor columns (lighting-invariant ratios, log gas)."""
    d = df.copy()
    for ch in "rgb":
        d[f"drv_tcs_{ch}_over_c"] = d[f"sensor_tcs_{ch}"] / d["sensor_tcs_c"]
    d["drv_log_mq135"] = np.log(d["sensor_mq135"])
    return d


def preprocessor(feature_set: str) -> ColumnTransformer:
    num = SENSOR_COLS + DERIVED
    parts = [("num", StandardScaler(), num)]
    if feature_set == "S+A":
        parts += [("aux_cat", OneHotEncoder(handle_unknown="ignore"), ["aux_m1_fruit", "aux_m1_condition"]),
                  ("aux_num", StandardScaler(), ["aux_m1_p_spoiled"])]
    return ColumnTransformer(parts)


def input_cols(feature_set: str) -> list[str]:
    return SENSOR_COLS + DERIVED + (AUX_COLS if feature_set == "S+A" else [])


MODELS = {
    "logreg": (LogisticRegression(max_iter=5000, class_weight="balanced"), {"C": [0.1, 1.0, 10.0]}),
    "svm_linear": (SVC(kernel="linear", class_weight="balanced", probability=False), {"C": [0.1, 1.0, 10.0]}),
    "svm_rbf": (SVC(kernel="rbf", class_weight="balanced"), {"C": [1.0, 10.0], "gamma": ["scale", 0.05]}),
    "random_forest": (RandomForestClassifier(class_weight="balanced", min_samples_leaf=2, n_jobs=-1, random_state=42),
                      {"n_estimators": [100, 300], "max_depth": [6, 10, None]}),
    "xgboost": (XGBClassifier(objective="multi:softprob", subsample=0.8, colsample_bytree=0.8, n_jobs=4,
                              random_state=42, eval_metric="mlogloss", tree_method="hist"),
                {"n_estimators": [300], "max_depth": [3, 5], "learning_rate": [0.05, 0.1]}),
}
NEEDS_SAMPLE_WEIGHT = {"xgboost"}


def make_pipe(name, feature_set, params):
    est = clone(MODELS[name][0]).set_params(**params)
    return Pipeline([("pre", preprocessor(feature_set)), ("clf", est)])


def fit(pipe, X, y, name):
    yi = y.map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
    kw = {"clf__sample_weight": compute_sample_weight("balanced", yi)} if name in NEEDS_SAMPLE_WEIGHT else {}
    return pipe.fit(X, yi, **kw)


def pred(pipe, X):
    return np.array(CLASSES)[np.asarray(pipe.predict(X)).astype(int)]


def scores(y, p) -> dict:
    pr, rc, f1, _ = precision_recall_fscore_support(y, p, labels=CLASSES, average="macro", zero_division=0)
    return {"accuracy": round(float(accuracy_score(y, p)), 4), "macro_precision": round(float(pr), 4),
            "macro_recall": round(float(rc), 4), "macro_f1": round(float(f1), 4)}


def footprint(pipe, name, n_in) -> dict:
    """Rough parameter / byte estimate for a C implementation on a Cortex-M4 (float32)."""
    clf = pipe.named_steps["clf"]
    n_feat = pipe.named_steps["pre"].transform(pd.DataFrame(columns=[], index=[])).shape[1] \
        if False else len(pipe.named_steps["pre"].get_feature_names_out())
    scaler = 2 * n_feat
    if name in ("logreg", "svm_linear"):
        k = clf.coef_.size + clf.intercept_.size
        return {"kind": "linear", "params": int(k + scaler), "approx_bytes": int(4 * (k + scaler))}
    if name == "svm_rbf":
        k = clf.support_vectors_.size + clf.dual_coef_.size + clf.intercept_.size
        return {"kind": "kernel", "support_vectors": int(len(clf.support_vectors_)),
                "params": int(k + scaler), "approx_bytes": int(4 * (k + scaler))}
    if name == "random_forest":
        nodes = sum(t.tree_.node_count for t in clf.estimators_)
        # internal: feature u8 + threshold f32 + 2 child idx u16; leaves: class u8 -> ~9 B/node
        return {"kind": "trees", "trees": len(clf.estimators_), "nodes": int(nodes), "approx_bytes": int(9 * nodes)}
    if name == "xgboost":
        dump = clf.get_booster().get_dump()
        nodes = sum(t.count("\n") for t in dump)
        return {"kind": "boosted_trees", "trees": len(dump), "nodes": int(nodes), "approx_bytes": int(9 * nodes)}
    return {}


def save_confusion(y, p, out, title):
    cm = confusion_matrix(y, p, labels=CLASSES)
    fig, ax = plt.subplots(figsize=(4.6, 4))
    ConfusionMatrixDisplay(cm, display_labels=CLASSES).plot(ax=ax, colorbar=False, cmap="Blues")
    ax.set_title(title, fontsize=8)
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)
    return cm.tolist()


def main() -> None:
    cfg = load_yaml("configs/model2_synthetic.yaml")
    df = add_derived(pd.read_csv(resolve(f"data/synthetic/model2/model2_synthetic_v{cfg['version']}.csv")))
    out_root = resolve("reports/model2/experiments")
    model_dir = resolve("models/model2_prototype")
    out_root.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    # ---- session-based split ----
    g = df[GROUP_COL]
    gss = GroupShuffleSplit(n_splits=1, test_size=0.15, random_state=42)
    trval_idx, te_idx = next(gss.split(df, groups=g))
    trval = df.iloc[trval_idx]
    gss2 = GroupShuffleSplit(n_splits=1, test_size=0.15 / 0.85, random_state=43)
    tr_i, va_i = next(gss2.split(trval, groups=trval[GROUP_COL]))
    split = pd.Series("train", index=df.index)
    split.iloc[trval.index[va_i]] = "val"
    split.iloc[te_idx] = "test"
    df["split"] = split
    sess_sets = {s: set(df.loc[df.split == s, GROUP_COL]) for s in ("train", "val", "test")}
    assert not (sess_sets["train"] & sess_sets["val"]) and not (sess_sets["train"] & sess_sets["test"]) \
        and not (sess_sets["val"] & sess_sets["test"]), "session leakage"
    df[["meta_sample_id", GROUP_COL, "split"]].to_csv(
        resolve(f"data/synthetic/model2/splits_v{cfg['version']}.csv"), index=False)
    TR, VA, TE, TV = (df[df.split == "train"], df[df.split == "val"], df[df.split == "test"],
                      df[df.split != "test"])
    split_info = {s: {"rows": int((df.split == s).sum()), "sessions": len(sess_sets[s]),
                      "class_share": df.loc[df.split == s, TARGET_COL].value_counts(normalize=True).round(3).to_dict()}
                  for s in ("train", "val", "test")}
    print(json.dumps(split_info, indent=1))

    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    folds = list(cv.split(TV, TV[TARGET_COL], groups=TV[GROUP_COL]))
    results, rows = {"TAG": TAG, "split": split_info}, []

    for fs in ("S", "S+A"):
        cols = input_cols(fs)
        for name, (_, grid) in MODELS.items():
            t0 = time.time()
            # hyper-parameters on VAL
            best, best_f1 = None, -1
            for params in ParameterGrid(grid):
                p = fit(make_pipe(name, fs, params), TR[cols], TR[TARGET_COL], name)
                f = f1_score(VA[TARGET_COL], pred(p, VA[cols]), average="macro")
                if f > best_f1:
                    best, best_f1 = params, f
            # grouped CV on TRAIN+VAL
            fold_scores = []
            for a, b in folds:
                p = fit(make_pipe(name, fs, best), TV.iloc[a][cols], TV.iloc[a][TARGET_COL], name)
                fold_scores.append(scores(TV.iloc[b][TARGET_COL], pred(p, TV.iloc[b][cols])))
            cvm = {k: round(float(np.mean([s[k] for s in fold_scores])), 4) for k in fold_scores[0]}
            cvs = {k: round(float(np.std([s[k] for s in fold_scores])), 4) for k in fold_scores[0]}
            # final fit on TRAIN+VAL, TEST once
            final = fit(make_pipe(name, fs, best), TV[cols], TV[TARGET_COL], name)
            yp = pred(final, TE[cols])
            out = out_root / fs.replace("+", "_plus_") / name
            out.mkdir(parents=True, exist_ok=True)
            test = scores(TE[TARGET_COL], yp)
            test_clean = scores(TE["latent_risk_clean"], yp)   # diagnostic only
            report = classification_report(TE[TARGET_COL], yp, labels=CLASSES, digits=4, zero_division=0,
                                           output_dict=True)
            cm = save_confusion(TE[TARGET_COL], yp, out / "confusion_test.png",
                                f"{TAG} — {name} [{fs}] TEST")
            (out / "classification_report_test.txt").write_text(
                f"{TAG} — NOT real pesticide detection performance\n\n"
                + classification_report(TE[TARGET_COL], yp, labels=CLASSES, digits=4, zero_division=0))
            # feature importance: permutation (model-agnostic) on TEST, scored by macro-F1
            yi_te = TE[TARGET_COL].map({c: i for i, c in enumerate(CLASSES)}).to_numpy()
            pi = permutation_importance(final, TE[cols], yi_te, scoring="f1_macro", n_repeats=10,
                                        random_state=42, n_jobs=-1)
            perm = pd.Series(pi.importances_mean, index=cols).sort_values(ascending=False).round(4)
            native = {}
            clf = final.named_steps["clf"]
            fnames = final.named_steps["pre"].get_feature_names_out()
            if hasattr(clf, "feature_importances_"):
                native = pd.Series(clf.feature_importances_, index=fnames).sort_values(ascending=False).round(4).to_dict()
            elif hasattr(clf, "coef_"):
                native = pd.Series(np.abs(clf.coef_).mean(0), index=fnames).sort_values(ascending=False).round(4).to_dict()
            fp = footprint(final, name, len(cols))
            joblib.dump(final, model_dir / f"{fs.replace('+', '_plus_')}__{name}.joblib")
            r = {"feature_set": fs, "model": name, "best_params": best, "val_macro_f1": round(float(best_f1), 4),
                 "cv_mean": cvm, "cv_sd": cvs, "cv_folds": fold_scores, "test": test,
                 "test_vs_clean_labels_diagnostic": test_clean,
                 "test_per_class": {c: {k: round(v, 4) for k, v in report[c].items()} for c in CLASSES},
                 "test_confusion": cm, "permutation_importance_test": perm.to_dict(),
                 "native_importance": native, "mcu_footprint_estimate": fp,
                 "train_seconds": round(time.time() - t0, 1)}
            (out / "result.json").write_text(json.dumps(r, indent=2, default=str))
            results[f"{fs}/{name}"] = r
            rows.append({"feature_set": fs, "model": name, "cv_macro_f1": cvm["macro_f1"],
                         "cv_sd": cvs["macro_f1"], "cv_acc": cvm["accuracy"],
                         "test_acc": test["accuracy"], "test_macro_p": test["macro_precision"],
                         "test_macro_r": test["macro_recall"], "test_macro_f1": test["macro_f1"],
                         "test_f1_LOW": round(report["LOW"]["f1-score"], 4),
                         "test_f1_MEDIUM": round(report["MEDIUM"]["f1-score"], 4),
                         "test_f1_HIGH": round(report["HIGH"]["f1-score"], 4),
                         "test_macro_f1_vs_clean": test_clean["macro_f1"],
                         "mcu_bytes_est": fp.get("approx_bytes"), "params": json.dumps(best)})
            print(f"[{TAG}] {fs:4s} {name:14s} CV F1 {cvm['macro_f1']:.3f}±{cvs['macro_f1']:.3f} "
                  f"TEST F1 {test['macro_f1']:.3f} acc {test['accuracy']:.3f} ~{fp.get('approx_bytes')} B", flush=True)

    # ---- baselines (same split / folds) ----
    base = {}
    for bname, cols, est in [
        ("majority", SENSOR_COLS, DummyClassifier(strategy="most_frequent")),
        ("aux_only_logreg", AUX_COLS, None),
        ("strip_only_logreg", ["sensor_tcs_r", "sensor_tcs_g", "sensor_tcs_b", "sensor_tcs_c",
                               "drv_tcs_r_over_c", "drv_tcs_g_over_c", "drv_tcs_b_over_c"], None),
    ]:
        if bname == "aux_only_logreg":
            pipe = Pipeline([("pre", ColumnTransformer([
                ("c", OneHotEncoder(handle_unknown="ignore"), ["aux_m1_fruit", "aux_m1_condition"]),
                ("n", StandardScaler(), ["aux_m1_p_spoiled"])])),
                ("clf", LogisticRegression(max_iter=5000, class_weight="balanced"))])
        elif bname == "strip_only_logreg":
            pipe = Pipeline([("pre", StandardScaler()), ("clf", LogisticRegression(max_iter=5000, class_weight="balanced"))])
        else:
            pipe = Pipeline([("pre", FunctionTransformer()), ("clf", est)])
        fs_ = [scores(TV.iloc[b][TARGET_COL], pipe.fit(TV.iloc[a][cols], TV.iloc[a][TARGET_COL]).predict(TV.iloc[b][cols]))
               for a, b in folds]
        pipe.fit(TV[cols], TV[TARGET_COL])
        yp = pipe.predict(TE[cols])
        base[bname] = {"cv_macro_f1": round(float(np.mean([s["macro_f1"] for s in fs_])), 4),
                       "cv_sd": round(float(np.std([s["macro_f1"] for s in fs_])), 4),
                       "test": scores(TE[TARGET_COL], yp)}
    results["baselines"] = base
    results["label_noise_ceiling_test_accuracy"] = round(float((TE[TARGET_COL] == TE.latent_risk_clean).mean()), 4)

    # ---- pre-registered selection ----
    tab = pd.DataFrame(rows)
    best_cv = tab.cv_macro_f1.max()
    cand = tab[tab.cv_macro_f1 >= best_cv - 0.02].sort_values(["mcu_bytes_est", "cv_macro_f1"],
                                                              ascending=[True, False])
    sel = cand.iloc[0].to_dict()
    results["selection"] = {"rule": "CV macro-F1 within 0.02 of best, then smallest MCU footprint",
                            "best_cv_macro_f1": float(best_cv), "candidates": cand[["feature_set", "model", "cv_macro_f1",
                                                                                     "mcu_bytes_est"]].to_dict("records"),
                            "selected": sel}
    tab.to_csv(out_root / "summary.csv", index=False)
    (out_root / "results.json").write_text(json.dumps(results, indent=2, default=str))
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(f"\n=== {TAG} RESULTS (not real pesticide detection) ===")
        print(tab.drop(columns="params").to_string(index=False))
        print("\nbaselines:", json.dumps(base, indent=1))
        print("label-noise ceiling (test acc vs clean):", results["label_noise_ceiling_test_accuracy"])
        print("\nSELECTED:", sel["feature_set"], sel["model"])


if __name__ == "__main__":
    main()
