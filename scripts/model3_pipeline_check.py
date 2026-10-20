"""End-to-end check of the post-processing layer (no training, no model changes).

Runs scripts/model3_predict.py in a CLEAN process (python -I, other cwd) on:
  A. the 6 existing Model 3 test examples (reports/model3/inference_verification.json)
  B. real TEST images with low Model 1 fruit confidence (misrouted and correct)
  C. real banana TEST images where grade and stage heads contradict
  D. CONSTRUCTED degraded inputs (blur / dark / uniform grey / noise) written to the
     scratch folder reports/model3/postprocess/constructed_inputs/ (not datasets)
and tallies rule-trigger rates over the whole TEST pool (descriptive only).

Output: reports/model3/postprocess/pipeline_check.{json,txt}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
import tensorflow as tf
from PIL import Image, ImageEnhance, ImageFilter

from fruitvision.config import resolve
from fruitvision.training import cached_images

sys.path.insert(0, str(resolve("scripts")))
from model3_predict import load, predict_arrays  # noqa: E402

ROOT = resolve(".")
OUT = resolve("reports/model3/postprocess")


def clean_run(paths):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"} | {"TF_CPP_MIN_LOG_LEVEL": "2",
                                                                       "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "model3_predict.py"), *map(str, paths)],
                       capture_output=True, text=True, cwd=tempfile.gettempdir(), env=env)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return json.loads(r.stdout)


def line(case, truth, o):
    q, s, c = o["quality_grade"], o["shelf_life"], o["consistency"]
    shelf = f"{s['range_days']} ({s.get('stage')})" if s["status"] == "estimated_range" else "not_available"
    w = ", ".join(f"{x['rule'].split('_')[0]}:{x['severity']}" for x in c["warnings"]) or "-"
    return (f"[{case}] {truth:28s} fruit={o['fruit']['label']}({o['fruit']['confidence']:.3f}) "
            f"cond={o['condition']['label']} grade={q['label']} shelf={shelf} status={c['status']} warnings={w}")


def main() -> None:
    model, labels, shelf, cfg = load(resolve("models/model3"))
    raw = resolve("data/raw")
    cases, lines = [], []

    # A. existing examples
    prev = json.loads((resolve("reports/model3/inference_verification.json")).read_text())
    for o in prev:
        cases.append(("A_existing_test", o["image"], f"(prev) {o['fruit']['label']}"))

    # whole TEST pool in-process (for case selection + rule tallies)
    pool = pd.read_csv(OUT / "fruit_confidence_test.csv")
    x = cached_images(list(pool.path), raw, 80, resolve("data/interim/cache")).astype("float32")
    recs = predict_arrays(model, labels, shelf, cfg, x)
    pool["status"] = [r["consistency"]["status"] for r in recs]
    pool["rules"] = [",".join(w["rule"] for w in r["consistency"]["warnings"]) for r in recs]
    pool["grade"] = [r["quality_grade"]["label"] for r in recs]
    pool["stage"] = [r["shelf_life"].get("stage") for r in recs]

    # B. low confidence: 3 misrouted + 3 correct-but-low
    low = pool[pool.conf < cfg["fruit_confidence_threshold"]]
    for _, r in pd.concat([low[~low.correct].sample(3, random_state=0),
                           low[low.correct].sample(3, random_state=0)]).iterrows():
        cases.append(("B_low_conf_real", str(raw / r.path), f"true {r.fruit}"))
    # C. banana contradictions (high routing confidence, R2 contradiction)
    con = pool[pool.rules.str.contains("R2") & (pool.fruit == "banana")]
    con = con[[any(w["severity"] == "contradiction" for w in recs[i]["consistency"]["warnings"]) for i in con.index]]
    for _, r in con.sample(min(4, len(con)), random_state=0).iterrows():
        cases.append(("C_banana_contradiction_real", str(raw / r.path), f"true banana ({r.source})"))
    # D. constructed degraded inputs from one confident banana and one confident tomato test image
    cdir = OUT / "constructed_inputs"
    cdir.mkdir(parents=True, exist_ok=True)
    src = pool[(pool.status == "ok")].groupby("fruit").head(1).set_index("fruit")
    for f in ("banana", "tomato"):
        im = Image.open(raw / src.loc[f, "path"]).convert("RGB")
        variants = {"blur": im.filter(ImageFilter.GaussianBlur(12)),
                    "dark": ImageEnhance.Brightness(im).enhance(0.08)}
        for k, v in variants.items():
            p = cdir / f"{f}_{k}.jpg"; v.save(p, quality=92)
            cases.append(("D_constructed", str(p), f"{f} ({k}) - constructed"))
    for k, arr in {"uniform_grey": np.full((256, 256, 3), 128, np.uint8),
                   "random_noise": np.random.default_rng(0).integers(0, 256, (256, 256, 3), dtype=np.uint8)}.items():
        p = cdir / f"{k}.jpg"; Image.fromarray(arr).save(p, quality=92)
        cases.append(("D_constructed", str(p), f"{k} - constructed"))

    results = clean_run([c[1] for c in cases])
    for (case, path, truth), o in zip(cases, results):
        lines.append(line(case, truth, o))

    # checks
    thr = cfg["fruit_confidence_threshold"]
    checks = {
        "R1_applied_whenever_conf_below_threshold": all(
            (o["quality_grade"]["label"] == "Uncertain") == (o["fruit"]["confidence"] < thr) for o in results),
        "fruit_prediction_preserved_when_uncertain": all(
            o["fruit"]["label"] == max(o["raw"]["fruit_probabilities"], key=o["raw"]["fruit_probabilities"].get)
            for o in results),
        "no_routed_output_when_uncertain": all(
            o["shelf_life"]["status"] == "not_available" for o in results if o["consistency"]["status"] == "uncertain"),
        "raw_head_outputs_always_present": all(len(o["raw"]["head_probabilities"]) == 6 for o in results),
        "C_cases_flagged_R2": all(any(w["rule"] == "R2_grade_vs_stage" for w in o["consistency"]["warnings"])
                                  for (c, *_), o in zip(cases, results) if c.startswith("C_")),
        "C_cases_predictions_unaltered": all(
            o["quality_grade"]["label"] == max(o["raw"]["head_probabilities"]["quality_banana"],
                                               key=o["raw"]["head_probabilities"]["quality_banana"].get)
            and o["shelf_life"]["stage"] == max(o["raw"]["head_probabilities"]["stage_banana"],
                                                key=o["raw"]["head_probabilities"]["stage_banana"].get)
            for (c, *_), o in zip(cases, results) if c.startswith("C_")),
    }
    tally = {"n": len(pool),
             "status_share": pool.status.value_counts(normalize=True).round(4).to_dict(),
             "R2_share_banana_routed": round(float(pool[pool.rules.str.contains("R2")].shape[0] /
                                                  max(1, ((pool.status != "uncertain") & (pool.pred == "banana")).sum())), 4),
             "R3_share_routed": round(float(pool.rules.str.contains("R3").sum() / max(1, (pool.status != "uncertain").sum())), 4),
             "status_by_true_fruit": pd.crosstab(pool.fruit, pool.status, normalize="index").round(3).to_dict(orient="index")}
    rep = {"checks": checks, "test_pool_rule_tally": tally,
           "cases": [{"case": c, "image": p, "truth": t, "output": o} for (c, p, t), o in zip(cases, results)]}
    (OUT / "pipeline_check.json").write_text(json.dumps(rep, indent=2))
    txt = "\n".join(lines) + "\n\nchecks: " + json.dumps(checks, indent=1) + "\n\ntest-pool tally: " + json.dumps(tally, indent=1)
    (OUT / "pipeline_check.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
