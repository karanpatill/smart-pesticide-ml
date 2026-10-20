"""Regression guard: every field present in the frozen v1 post-processing output must
remain byte-for-byte identical. New fields may be ADDED; nothing existing may change.
Golden file created before any Phase-2 change (tests/golden/postprocess_v1.json)."""

import json
from pathlib import Path

import pytest

from fruitvision.postprocess import postprocess

ROOT = Path(__file__).resolve().parents[1]
GOLD = json.loads((ROOT / "tests/golden/postprocess_v1.json").read_text())
CFG = json.loads((ROOT / "configs/model3_postprocess.json").read_text())
SHELF = json.loads((ROOT / "models/model3/shelf_life_ranges.json").read_text())


def assert_superset(old, new, path="$"):
    if isinstance(old, dict):
        assert isinstance(new, dict), f"{path}: type changed"
        for k, v in old.items():
            assert k in new, f"{path}.{k} removed"
            assert_superset(v, new[k], f"{path}.{k}")
    elif isinstance(old, list) and old and isinstance(old[0], dict):
        assert len(old) == len(new), f"{path}: list length changed"
        for i, (a, b) in enumerate(zip(old, new)):
            assert_superset(a, b, f"{path}[{i}]")
    else:
        assert old == new, f"{path}: {old!r} -> {new!r}"


@pytest.mark.parametrize("case", sorted(GOLD))
def test_postprocess_v1_fields_unchanged(case):
    assert_superset(GOLD[case]["output"], postprocess(GOLD[case]["input"], CFG, SHELF))
