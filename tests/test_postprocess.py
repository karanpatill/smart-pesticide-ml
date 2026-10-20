"""Rule tests for the Model 3 post-processing layer (constructed raw outputs; no models)."""

import json
from pathlib import Path

import pytest

from fruitvision.postprocess import postprocess

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "configs/model3_postprocess.json").read_text())
SHELF = json.loads((ROOT / "models/model3/shelf_life_ranges.json").read_text())
THR = CFG["fruit_confidence_threshold"]

HEADS = {
    "quality_banana": {"Good": 0.1, "Average": 0.1, "Poor": 0.8},
    "quality_guava": {"Good": 0.7, "Average": 0.2, "Poor": 0.1},
    "quality_apple": {"Good": 0.9, "Poor": 0.1},
    "stage_tomato": {"Fresh": 0.1, "Semi-fresh": 0.8, "Rotten": 0.1},
    "stage_brinjal": {"Fresh": 0.8, "Semi-fresh": 0.1, "Rotten": 0.1},
    "stage_banana": {"Fresh": 0.9, "Semi-fresh": 0.05, "Rotten": 0.05},
}


def raw(fruit, conf, cond="spoiled", heads=None):
    others = [f for f in ["apple", "banana", "guava", "tomato", "brinjal"] if f != fruit]
    fp = {fruit: conf, **{f: (1 - conf) / 4 for f in others}}
    cp = {"fresh": 0.3, "spoiled": 0.7} if cond == "spoiled" else {"fresh": 0.7, "spoiled": 0.3}
    return {"fruit": fp, "condition": cp, "heads": {**HEADS, **(heads or {})}}


def test_low_fruit_confidence_withholds_outputs_but_keeps_raw():
    r = postprocess(raw("guava", 0.40), CFG, SHELF)
    assert {k: r["fruit"][k] for k in ("label", "confidence", "source")} == {"label": "guava", "confidence": 0.4, "source": "Model 1"}
    assert r["quality_grade"]["label"] == "Uncertain" and r["quality_grade"]["confidence"] is None
    assert r["shelf_life"]["status"] == "not_available" and "below the threshold" in r["shelf_life"]["reason"]
    assert r["consistency"]["status"] == "uncertain"
    assert r["raw"]["routed_outputs_used_in_final"] is False
    assert r["raw"]["head_probabilities"]["quality_guava"]["Good"] == 0.7   # raw preserved


def test_threshold_boundary_is_inclusive():
    assert postprocess(raw("apple", THR), CFG, SHELF)["quality_grade"]["label"] != "Uncertain"
    assert postprocess(raw("apple", THR - 1e-4), CFG, SHELF)["quality_grade"]["label"] == "Uncertain"


def test_banana_contradiction_warns_without_altering():
    r = postprocess(raw("banana", 0.99), CFG, SHELF)        # grade Poor vs stage Fresh
    assert r["quality_grade"]["label"] == "Poor"
    assert r["shelf_life"]["stage"] == "Fresh" and r["shelf_life"]["range_days"] == [3, 6]
    w = [x for x in r["consistency"]["warnings"] if x["rule"] == "R2_grade_vs_stage"]
    assert w and w[0]["severity"] == "contradiction" and w[0]["details"]["ordinal_distance"] == 2
    assert r["consistency"]["status"] == "warning"


def test_banana_minor_mismatch():
    r = postprocess(raw("banana", 0.99, heads={"stage_banana": {"Fresh": .1, "Semi-fresh": .8, "Rotten": .1}}), CFG, SHELF)
    w = [x for x in r["consistency"]["warnings"] if x["rule"] == "R2_grade_vs_stage"]
    assert w[0]["severity"] == "minor_mismatch"


def test_banana_consistent_has_no_r2_warning():
    r = postprocess(raw("banana", 0.99, heads={"stage_banana": {"Fresh": .05, "Semi-fresh": .05, "Rotten": .9}}),
                    CFG, SHELF)
    assert not [x for x in r["consistency"]["warnings"] if x["rule"] == "R2_grade_vs_stage"]
    assert r["consistency"]["status"] == "ok"


def test_condition_vs_grade_conflict():
    r = postprocess(raw("guava", 0.99, cond="spoiled"), CFG, SHELF)     # spoiled + Good
    assert [x for x in r["consistency"]["warnings"] if x["rule"] == "R3_condition_vs_grade"]
    assert r["quality_grade"]["label"] == "Good" and r["condition"]["label"] == "spoiled"


@pytest.mark.parametrize("fruit", ["tomato", "brinjal"])
def test_tomato_brinjal_grade_equals_stage_no_r2(fruit):
    r = postprocess(raw(fruit, 0.99, cond="fresh"), CFG, SHELF)
    assert r["quality_grade"]["head"] == r["shelf_life"]["head"]
    assert "grade = freshness stage" in r["quality_grade"]["basis"]
    assert not [x for x in r["consistency"]["warnings"] if x["rule"] == "R2_grade_vs_stage"]


@pytest.mark.parametrize("fruit", ["apple", "guava"])
def test_no_shelf_life_for_apple_guava(fruit):
    r = postprocess(raw(fruit, 0.99, cond="fresh"), CFG, SHELF)
    assert r["shelf_life"]["status"] == "not_available" and r["shelf_life"]["range_days"] is None


def test_apple_is_binary():
    r = postprocess(raw("apple", 0.99, cond="fresh"), CFG, SHELF)
    assert r["quality_grade"]["scale"].startswith("binary") and r["quality_grade"]["label"] in ("Good", "Poor")


def test_state_field_distinguishes_predicted_uncertain_unavailable():
    low = postprocess(raw("guava", 0.40), CFG, SHELF)
    assert low["quality_grade"]["state"] == "uncertain" and low["shelf_life"]["state"] == "uncertain"
    assert low["fruit"]["state"] == "predicted"
    g = postprocess(raw("guava", 0.99, cond="fresh"), CFG, SHELF)
    assert g["quality_grade"]["state"] == "predicted" and g["shelf_life"]["state"] == "unavailable"
    b = postprocess(raw("banana", 0.99), CFG, SHELF)
    assert b["shelf_life"]["state"] == "predicted"
