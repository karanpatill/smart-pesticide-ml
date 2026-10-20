"""Post-processing / consistency layer for Model 1 + Model 3 (no ML, no weights).

Input: raw model outputs (probability dicts). Output: the final user-facing
record plus a `raw` block that preserves every model output unchanged.

Every output object carries "state": "predicted" (a model produced it),
"uncertain" (a model exists but its output was withheld, e.g. R1) or
"unavailable" (no model/data exists for this case, e.g. guava shelf life).

Rules (configs/model3_postprocess.json):
  R1 low fruit confidence  -> quality_grade "Uncertain", shelf_life not_available
  R2 grade vs stage        -> banana only; warning on mismatch, nothing altered
  R3 condition vs grade    -> warning on fresh+Poor / spoiled+Good, nothing altered
"""

from __future__ import annotations

FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]
QUALITY_HEAD = {"apple": "quality_apple", "banana": "quality_banana", "guava": "quality_guava",
                "tomato": "stage_tomato", "brinjal": "stage_brinjal"}
STAGE_HEAD = {"banana": "stage_banana", "tomato": "stage_tomato", "brinjal": "stage_brinjal"}
STAGE_TO_GRADE = {"Fresh": "Good", "Semi-fresh": "Average", "Rotten": "Poor"}
GRADE_BASIS = {
    "apple": "FruitNet Good/Bad label (binary; no 'Average' class exists for apple)",
    "banana": "Class A/B/Defect market grade (Mendeley 56td5w4wz2)",
    "guava": "Class A/B/Defect market grade (Mendeley 56td5w4wz2)",
    "tomato": "AgriFreshNET freshness stage (Fresh/Semi-fresh/Rotten) - grade = freshness stage",
    "brinjal": "AgriFreshNET freshness stage (Fresh/Semi-fresh/Rotten) - grade = freshness stage",
}
NOTES = ["Quality grade and shelf-life range are visual estimates from public-dataset labels.",
         "The image models do not detect pesticide residue.",
         "Shelf-life ranges reflect the source dataset's storage conditions; not a guarantee."]


def _top(p: dict[str, float]) -> tuple[str, float]:
    k = max(p, key=p.get)
    return k, float(p[k])


def postprocess(raw: dict, cfg: dict, shelf: dict) -> dict:
    """raw = {"fruit": {label: prob}, "condition": {label: prob}, "heads": {head: {label: prob}}}"""
    thr = float(cfg["fruit_confidence_threshold"])
    fruit, f_conf = _top(raw["fruit"])
    cond, c_conf = _top(raw["condition"])
    qh, sh = QUALITY_HEAD[fruit], STAGE_HEAD.get(fruit)
    out = {
        "fruit": {"label": fruit, "confidence": round(f_conf, 4), "source": "Model 1", "state": "predicted"},
        "condition": {"label": cond, "confidence": round(c_conf, 4), "source": "Model 1", "state": "predicted"},
    }
    warnings = []
    routed_ok = f_conf >= thr

    if not routed_ok:  # ---- R1 ----
        reason = (f"Fruit routing confidence {f_conf:.3f} is below the threshold {thr:.3f}; "
                  f"fruit-specific quality and shelf-life outputs are withheld.")
        out["quality_grade"] = {"label": "Uncertain", "confidence": None, "scale": None, "basis": None,
                                "head": None, "reason": reason, "source": "post-processing (R1)",
                                "state": "uncertain"}
        out["shelf_life"] = {"status": "not_available", "range_days": None, "reason": reason,
                             "source": "post-processing (R1)", "state": "uncertain"}
        warnings.append({"rule": "R1_low_fruit_confidence", "severity": "uncertain", "message": reason,
                         "details": {"fruit_confidence": round(f_conf, 4), "threshold": thr}})
        status = "uncertain"
    else:
        q_lab, q_conf = _top(raw["heads"][qh])
        grade = STAGE_TO_GRADE.get(q_lab, q_lab)
        out["quality_grade"] = {"label": grade, "confidence": round(q_conf, 4),
                                "scale": "binary (Good/Poor)" if fruit == "apple" else "3-level (Good/Average/Poor)",
                                "basis": GRADE_BASIS[fruit], "head": qh, "source": "Model 3",
                                "state": "predicted"}
        if sh:
            stage, s_conf = _top(raw["heads"][sh])
            lo, hi = shelf["ranges"][fruit][stage]
            out["shelf_life"] = {"status": "estimated_range", "range_days": [lo, hi], "stage": stage,
                                 "stage_confidence": round(s_conf, 4), "head": sh, "basis": shelf["source"],
                                 "disclaimer": shelf["disclaimer"].strip(),
                                 "source": "Model 3 stage head + fixed lookup (no regression)",
                                 "state": "predicted"}
            # ---- R2 (banana: grade and stage from different heads) ----
            if fruit in cfg["rules"]["R2_grade_vs_stage"]["applies_to"]:
                gi = cfg["grade_order"].index(grade)
                si = cfg["stage_order"].index(stage)
                d = abs(gi - si)
                if d:
                    sev = "contradiction" if d == 2 else "minor_mismatch"
                    warnings.append({
                        "rule": "R2_grade_vs_stage", "severity": sev,
                        "message": (f"Quality grade '{grade}' and shelf-life stage '{stage}' "
                                    f"{'contradict each other' if d == 2 else 'differ by one level'}. "
                                    "They come from different models trained on different datasets; "
                                    "treat both as uncertain. Neither output was altered."),
                        "details": {"grade": grade, "stage": stage, "ordinal_distance": d}})
        else:
            out["shelf_life"] = {"status": "not_available", "range_days": None,
                                 "reason": shelf["not_available"][fruit], "source": "Model 3",
                                 "state": "unavailable"}
        # ---- R3 ----
        if [cond, grade] in cfg["rules"]["R3_condition_vs_grade"]["conflicting_pairs"]:
            warnings.append({
                "rule": "R3_condition_vs_grade", "severity": "contradiction",
                "message": (f"Model 1 condition '{cond}' conflicts with quality grade '{grade}'. "
                            "Neither output was altered."),
                "details": {"condition": cond, "condition_confidence": round(c_conf, 4),
                            "grade": grade, "grade_confidence": round(q_conf, 4)}})
        status = "warning" if warnings else "ok"

    out["consistency"] = {"status": status, "warnings": warnings}
    out["raw"] = {
        "fruit_probabilities": {k: round(float(v), 4) for k, v in raw["fruit"].items()},
        "condition_probabilities": {k: round(float(v), 4) for k, v in raw["condition"].items()},
        "head_probabilities": {h: {k: round(float(v), 4) for k, v in p.items()} for h, p in raw["heads"].items()},
        "routed_quality_head": qh, "routed_stage_head": sh,
        "routed_outputs_used_in_final": routed_ok,
    }
    out["postprocess"] = {"version": cfg["version"], "fruit_confidence_threshold": thr}
    out["notes"] = NOTES
    return out
