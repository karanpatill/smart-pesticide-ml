"""Sensor validation rules (constructed records; no hardware readings involved)."""

import copy
import json
import math
from pathlib import Path

import pytest

from fruitvision.sensor.validation import validate_sensors

ROOT = Path(__file__).resolve().parents[1]
RANGES = json.loads((ROOT / "models/model2_export/model2_logreg.json").read_text())["synthetic_training_ranges_trainval"]
FX = json.loads((ROOT / "data/fixtures/sensor_records.json").read_text())["records"]
GOOD = FX["synthetic_medium"]["record"]


def v(rec):
    return validate_sensors(rec, RANGES)


def with_(path, value):
    d = copy.deepcopy(GOOD)
    g, k = path.split(".")
    d[g][k] = value
    return d


def test_valid_synthetic_record():
    r = v(GOOD)
    assert r["status"] == "valid" and not r["errors"] and not r["out_of_training_range"]


@pytest.mark.parametrize("path,value,msg", [
    ("dht22.temperature_c", float("nan"), "non-finite"),
    ("dht22.temperature_c", float("inf"), "non-finite"),
    ("dht22.temperature_c", 95.0, "outside -40..80"),
    ("dht22.humidity_pct", 120.0, "outside 0..100"),
    ("ph.value", 14.0, "outside (0, 14)"),
    ("ph.value", -1.0, "outside (0, 14)"),
    ("ph.value", "7.0", "not a number"),
    ("ph.value", True, "not a number"),
    ("mq135.value", 0.0, "must be > 0"),
    ("tcs34725.c", 65535, "saturated"),
    ("tcs34725.r", -5, "non-negative integers"),
    ("tcs34725.r", 10.5, "non-negative integers"),
])
def test_invalid_values(path, value, msg):
    r = v(with_(path, value))
    assert r["status"] == "invalid" and any(msg in e for e in r["errors"]), r["errors"]


def test_disconnected_tcs_and_missing_blocks():
    d = copy.deepcopy(GOOD)
    d["tcs34725"].update(r=0, g=0, b=0, c=0)
    assert any("all channels 0" in e for e in v(d)["errors"])
    d = copy.deepcopy(GOOD)
    d.pop("mq135")
    assert any("MQ135: missing" in e for e in v(d)["errors"])
    assert v(None)["status"] == "invalid" and v({})["status"] == "invalid"


def test_adc_rails_and_units():
    d = with_("mq135.unit", "adc_counts_12bit")
    d["mq135"]["value"] = 4095
    assert any("rail" in e for e in v(d)["errors"])
    assert any("unit must be" in e for e in v(with_("mq135.unit", "volts"))["errors"])


def test_tcs_saturation_respects_atime():
    d = copy.deepcopy(GOOD)
    d["tcs34725"]["atime"] = 255          # 1 cycle -> max count 1024
    d["tcs34725"]["c"] = 1024
    assert any("saturated" in e for e in v(d)["errors"])


def test_warnings_and_out_of_range():
    d = copy.deepcopy(GOOD)
    d["mq135"].pop("warmup_s")
    assert any("warm-up time unknown" in w for w in v(d)["warnings"])
    assert any("only 30 s" in w for w in v(with_("mq135.warmup_s", 30))["warnings"])
    assert v(with_("mq135.value", 9000.0))["out_of_training_range"]
    d = copy.deepcopy(GOOD)
    d["tcs34725"]["c"] = d["tcs34725"]["r"] - 1
    assert any("clear channel below" in w for w in v(d)["warnings"])


def test_fixture_nan_parses_as_nonfinite():
    assert math.isnan(FX["invalid_dht22_nan"]["record"]["dht22"]["temperature_c"])
    assert v(FX["invalid_dht22_nan"]["record"])["status"] == "invalid"
