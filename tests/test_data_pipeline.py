"""Unit tests for labelling, duplicate grouping and leakage-free splitting.

Uses small synthetic images in a temp folder; no real dataset needed.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from fruitvision.data.dedupe import assign_duplicate_groups, conflicting_groups
from fruitvision.data.manifest import build_source_manifest
from fruitvision.data.split import assert_no_leakage, stratified_group_split

FRUITS = ["apple", "banana"]
CONDS = ["fresh", "spoiled"]


def _img(path: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    # Low-frequency random pattern so pHash differs between seeds.
    small = rng.integers(0, 255, (8, 8, 3), dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(small).resize((64, 64), Image.NEAREST).save(path)


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    root = tmp_path / "raw" / "src"
    seed = 0
    for d in ["Apple_Good", "Apple_Bad", "Banana_Good", "Banana_Bad", "Mystery"]:
        for i in range(20):
            _img(root / "set" / d / f"{i}.jpg", seed)
            seed += 1
    # Exact duplicate inside the same class, and one across classes (conflict).
    (root / "set" / "Apple_Good" / "dup.jpg").write_bytes((root / "set" / "Apple_Good" / "0.jpg").read_bytes())
    (root / "set" / "Apple_Bad" / "conflict.jpg").write_bytes((root / "set" / "Apple_Good" / "1.jpg").read_bytes())
    (root / "set" / "Apple_Good" / "broken.jpg").write_bytes(b"not an image")
    return tmp_path / "raw"


SPEC = {
    "root": "src",
    "class_dirs": {
        "Apple_Good": {"fruit": "apple", "condition": "fresh", "condition_raw": "good"},
        "Apple_Bad": {"fruit": "apple", "condition": "spoiled", "condition_raw": "bad"},
        "Banana_Good": {"fruit": "banana", "condition": "fresh", "condition_raw": "good"},
        "Banana_Bad": {"fruit": "banana", "condition": "spoiled", "condition_raw": "bad"},
    },
}


def test_manifest_only_labels_mapped_dirs(raw):
    df = build_source_manifest(raw, "src", SPEC, FRUITS, CONDS)
    assert (df[df.path.str.contains("/Mystery/")].status == "unmapped").all()
    assert df[df.path.str.endswith("broken.jpg")].status.item() == "corrupt"
    ok = df[df.status == "ok"]
    assert set(ok.fruit) == {"apple", "banana"}
    assert ok.loc[ok.path.str.contains("Apple_Bad"), "condition"].eq("spoiled").all()


def test_invalid_mapping_rejected(raw):
    bad = {"root": "src", "class_dirs": {"Apple_Good": {"fruit": "mango", "condition": "fresh"}}}
    with pytest.raises(ValueError):
        build_source_manifest(raw, "src", bad, FRUITS, CONDS)


def test_duplicates_grouped_and_conflicts_found(raw):
    df = build_source_manifest(raw, "src", SPEC, FRUITS, CONDS)
    df = assign_duplicate_groups(df[df.status == "ok"], max_distance=0)
    g = df.set_index("path")["group_id"]
    assert g["src/set/Apple_Good/dup.jpg"] == g["src/set/Apple_Good/0.jpg"]
    conflicts = conflicting_groups(df)
    assert "src/set/Apple_Bad/conflict.jpg" in set(conflicts.path)


def test_split_has_no_leakage_and_is_reproducible(raw):
    df = build_source_manifest(raw, "src", SPEC, FRUITS, CONDS)
    df = assign_duplicate_groups(df[df.status == "ok"], max_distance=0)
    df = df[~df.group_id.isin(conflicting_groups(df).group_id)]
    fr = {"train": 0.7, "val": 0.15, "test": 0.15}
    s1 = stratified_group_split(df, fr, seed=1)
    s2 = stratified_group_split(df, fr, seed=1)
    pd.testing.assert_series_equal(s1, s2)
    df = df.assign(split=s1)
    assert_no_leakage(df)
    # Every fruit/condition cell is present in every split.
    cells = df.groupby(["fruit", "condition"])["split"].nunique()
    assert (cells == 3).all()


def test_leakage_detected():
    df = pd.DataFrame({"group_id": [0, 0, 1], "sha256": ["a", "b", "c"], "split": ["train", "test", "val"]})
    with pytest.raises(AssertionError):
        assert_no_leakage(df)


def test_sessions_grouped_and_aug_files_excluded(tmp_path):
    root = tmp_path / "raw" / "src" / "Apple_Good"
    names = ["IMG_20250101_100000.jpg", "IMG_20250101_100010.jpg",
             "IMG_20250102_090000.jpg", "aug_1_apple.jpg", "IMG_0100.JPG",
             "IMG_0101.JPG", "IMG_0200.JPG", "notime.jpg"]
    for i, n in enumerate(names):
        _img(root / n, 100 + i)
    spec = {
        "root": "src",
        "class_dirs": {"Apple_Good": {"fruit": "apple", "condition": "fresh"}},
        "exclude_file_patterns": ["/aug_[^/]*$"],
        "session": {"gap_seconds": 20, "counter_gap": 3, "fallback": "none"},
    }
    df = build_source_manifest(tmp_path / "raw", "src", spec, FRUITS, CONDS)
    by = df.set_index(df.path.str.rsplit("/", n=1).str[-1])
    assert by.loc["aug_1_apple.jpg", "status"] == "excluded"
    assert by.loc["notime.jpg", "session"] == ""
    assert by.loc["IMG_20250101_100000.jpg", "time_source"] == "filename"
    ok = assign_duplicate_groups(df[df.status == "ok"], max_distance=0)
    g = ok.set_index(ok.path.str.rsplit("/", n=1).str[-1])["group_id"]
    assert g["IMG_20250101_100000.jpg"] == g["IMG_20250101_100010.jpg"]
    assert g["IMG_20250101_100000.jpg"] != g["IMG_20250102_090000.jpg"]
    assert g["IMG_0100.JPG"] == g["IMG_0101.JPG"] != g["IMG_0200.JPG"]
    # 7 ok images -> 5 groups: 2 time bursts, 2 counter runs, notime.jpg on its own
    assert g.nunique() == 5
    no_sess = assign_duplicate_groups(df[df.status == "ok"], max_distance=0, use_session=False)
    assert no_sess["group_id"].nunique() == 7
