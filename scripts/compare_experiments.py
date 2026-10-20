"""Collect experiment results into one comparison (reads only; never retrains).

Sources:
  reports/final/final_80_b15/           provisional baseline (TEST), read-only
  reports/experiments/<variant>/results_*.json

Writes reports/experiments/comparison.csv and prints a markdown table.
"""

from __future__ import annotations

import json

import pandas as pd

from fruitvision.config import load_config, resolve

VARIANTS = ["baseline", "crop", "composite", "crop_composite"]


def spoiled_recall(df):
    s = df[df.condition == "spoiled"]
    return float((s.pred_condition == "spoiled").mean()) if len(s) else float("nan")


def flat(prefix: str, s: dict) -> dict:
    if not s:
        return {}
    r = {f"{prefix}fruit_f1": s.get("fruit_macro_f1"), f"{prefix}cond_f1": s.get("condition_macro_f1"),
         f"{prefix}spoiled_recall": s.get("spoiled_recall")}
    for f, v in s.get("condition_f1_by_fruit", {}).items():
        r[f"{prefix}cond_f1_{f}"] = v["f1"]
    for src, v in s.get("condition_f1_by_source", {}).items():
        r[f"{prefix}cond_f1_src_{src}"] = v["f1"]
    for src, v in s.get("fruit_f1_by_source", {}).items():
        r[f"{prefix}fruit_f1_src_{src}"] = v["f1"]
    for src, v in s.get("banana_fruit_recall_by_source", {}).items():
        r[f"{prefix}banana_recall_{src}"] = v
    for k, v in s.get("brinjal_by_variety_tag", {}).items():
        r[f"{prefix}brinjal_{k}_acc"] = v["acc"]
    return r


def main() -> None:
    cfg = load_config()
    rep = resolve(cfg["paths"]["reports_dir"])
    rows = []
    for v in VARIANTS:
        res = {}
        for f in sorted((rep / "experiments" / v).glob("results_*.json")):
            res.update(json.loads(f.read_text()))
        row = {"variant": v}
        if v == "baseline":
            base = json.loads((rep / "final" / "final_80_b15" / "results.json").read_text())
            tp = pd.read_csv(rep / "final" / "final_80_b15" / "test_predictions.csv")
            t = base["test"] | {"spoiled_recall": spoiled_recall(tp),
                                "brinjal_by_variety_tag": base.get("test_brinjal_by_variety_tag", {}),
                                "banana_fruit_recall_by_source": {
                                    k: float((g.pred_fruit == "banana").mean())
                                    for k, g in tp[tp.fruit == "banana"].groupby("source")}}
            row |= flat("test_", t)
            row["test_masked_cond_f1"] = base["test_fruit_masked"]["condition_macro_f1"]
        else:
            row |= flat("test_", res.get("test", {}))
            row["test_masked_cond_f1"] = res.get("test_fruit_masked", {}).get("condition_macro_f1")
        # For LOSO / AgriFreshNET-only, macro-F1 over all 5 fruits would count
        # absent fruits as 0; use F1 over the fruits present in that source.
        for held, s in res.get("loso", {}).items():
            row |= flat(f"loso_{held}_", s)
            row[f"loso_{held}_fruit_f1"] = s["fruit_f1_by_source"][held]["f1"]
        row |= flat("agri_", res.get("agri_only", {}))
        if "agri_only" in res:
            row["agri_fruit_f1"] = res["agri_only"]["fruit_f1_by_source"]["agrifreshnet"]["f1"]
        row["agri_masked_cond_f1"] = res.get("agri_only_fruit_masked", {}).get("condition_macro_f1")
        rows.append(row)

    df = pd.DataFrame(rows).set_index("variant").T
    out = rep / "experiments" / "comparison.csv"
    df.to_csv(out)
    with pd.option_context("display.max_rows", 300, "display.float_format", "{:.3f}".format):
        print(df.to_string())
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
