"""End-to-end interface tests (real public-dataset images + labelled fixtures)."""

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "models/model3/model3_combined.keras").exists(), reason="models absent")
FX = json.loads((ROOT / "data/fixtures/sensor_records.json").read_text())["records"]


@pytest.fixture(scope="module")
def system():
    from fruitvision.system import SmartPesticideSystem
    return SmartPesticideSystem(ROOT)


@pytest.fixture(scope="module")
def banana_img():
    p = pd.read_csv(ROOT / "reports/model3/postprocess/fruit_confidence_test.csv")
    p = p[(p.fruit == "banana") & p.correct & (p.conf > 0.99)].iloc[0].path
    return ROOT / "data/raw" / p


STATES = {"predicted", "uncertain", "unavailable"}


def test_full_result_schema(system, banana_img):
    r = system.analyze(image=banana_img, sensors=FX["synthetic_medium"]["record"])
    for k in ("fruit", "condition", "quality_grade", "shelf_life", "pesticide_risk"):
        assert r[k]["state"] in STATES, k
    assert r["fruit"]["label"] == "banana"
    assert r["pesticide_risk"]["state"] == "predicted"
    assert "SYNTHETIC" in r["pesticide_risk"]["evidence_level"]
    assert r["pesticide_risk"]["category"] in ("LOW", "MEDIUM", "HIGH")
    assert "score" not in json.dumps(r).lower().replace("spoilage score", "")
    assert r["limitations"] and r["recommendation"]["text"]


def test_rejected_image_makes_image_outputs_unavailable(system):
    b = io.BytesIO()
    Image.fromarray(np.full((200, 200, 3), 128, np.uint8)).save(b, format="PNG")
    r = system.analyze(image=b.getvalue(), sensors=None)
    assert r["input_checks"]["image"]["status"] == "rejected"
    for k in ("fruit", "condition", "quality_grade", "shelf_life"):
        assert r[k]["state"] == "unavailable"
    assert r["pesticide_risk"]["state"] == "unavailable"
    assert any("Retake the image" in t for t in r["recommendation"]["text"])


def test_noise_image_rejected_before_model(system):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (200, 200, 3), dtype=np.uint8)).save(b, format="PNG")
    assert system.analyze(image=b.getvalue())["fruit"]["state"] == "unavailable"


@pytest.mark.parametrize("name", ["invalid_dht22_nan", "invalid_tcs_disconnected", "invalid_tcs_saturated",
                                  "invalid_ph_rail", "invalid_missing_mq135"])
def test_invalid_sensors_never_produce_risk(system, name):
    r = system.analyze(sensors=FX[name]["record"])
    assert r["pesticide_risk"]["state"] == "unavailable" and r["pesticide_risk"]["category"] is None


def test_uncalibrated_device_and_out_of_range_are_uncertain(system):
    for name in ("device_like_uncalibrated", "out_of_range_mq135"):
        r = system.analyze(sensors=FX[name]["record"])
        assert r["pesticide_risk"]["state"] == "uncertain" and r["pesticide_risk"]["category"] is None
        assert r["raw"]["model2_probabilities_withheld"] is not None


def test_low_is_not_reported_as_pesticide_free(system):
    r = system.analyze(sensors=FX["synthetic_low"]["record"])
    if r["pesticide_risk"]["category"] == "LOW":
        assert any("NOT evidence" in t for t in r["recommendation"]["text"])
    assert "pesticide-free" in r["pesticide_risk"]["interpretation"]


def test_no_inputs(system):
    r = system.analyze()
    assert r["fruit"]["state"] == "unavailable" and r["pesticide_risk"]["state"] == "unavailable"
