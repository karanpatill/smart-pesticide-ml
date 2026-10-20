"""Prepare Model 3 data: Quality Grade + shelf-life stage, with leakage-safe splits.

Tasks (one label scheme per fruit, never mixed):
  quality_banana   56td5w4wz2 Class_A / Class_B / Defect -> Good / Average / Poor
  quality_guava    56td5w4wz2 Class_A / Class_B / Defect -> Good / Average / Poor
  quality_apple    FruitNet Apple Good / Bad             -> Good / Poor (binary)
  stage_tomato     AgriFreshNET Fresh / Semi-fresh / Rotten (= tomato Quality Grade)
  stage_brinjal    AgriFreshNET Fresh / Semi-fresh / Rotten (= brinjal Quality Grade)
  stage_banana     AgriFreshNET Fresh / Semi-fresh / Rotten (banana shelf-life range only)

Leakage rules
  * Images Model 1 was trained on (its TRAIN/VAL split: FruitNet apple, AgriFreshNET
    banana/tomato/brinjal fresh & rotten) INHERIT Model 1's split, so Model 3 TEST
    never contains an image the frozen feature extractor saw in training.
  * Images Model 1 never saw (semi-fresh folders, 56td5w4wz2) get a new stratified,
    group-aware 70/15/15 split. Groups = capture bursts (AgriFreshNET filename time)
    + 256-bit pHash near-duplicates (<= 16 bits).
  * A new image grouped with inherited images follows their split.
  * Byte-identical images with conflicting labels are dropped (all copies); same-label
    copies are collapsed to one. `aug_*` files are excluded.

Output: data/model3/manifest.csv, data/model3/prepare_summary.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import imagehash
import numpy as np
import pandas as pd
from PIL import Image

from fruitvision.config import resolve
from fruitvision.data.dedupe import assign_duplicate_groups
from fruitvision.data.sessions import assign_bursts, filename_time
from fruitvision.data.split import assert_no_leakage, stratified_group_split

RAW = resolve("data/raw")
OUT = resolve("data/model3")
GRADE_MAP = {"Class_A": "Good", "Class_B": "Average", "Defect": "Poor"}
AGRI = {  # folder -> (fruit, stage)
    "Fresh Banana(1-4)": ("banana", "Fresh"), "Semi fresh banana(4-7)": ("banana", "Semi-fresh"),
    "Rotten banana(7-13)": ("banana", "Rotten"),
    "Fresh Tomato(1-10)": ("tomato", "Fresh"), "Semi fresh Tomato(10-24)": ("tomato", "Semi-fresh"),
    "Rotten Tomato(24-35)": ("tomato", "Rotten"),
    "Fresh eggplant(1-4)": ("brinjal", "Fresh"), "Semi_Fresh eggplant(4-8)": ("brinjal", "Semi-fresh"),
    "Rotten eggplant(8-15)": ("brinjal", "Rotten"),
}


def file_info(rel: str) -> dict:
    p = RAW / rel
    with Image.open(p) as im:
        ph = str(imagehash.phash(im.convert("RGB"), hash_size=16))
    return {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "phash": ph}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    m1 = pd.concat([pd.read_csv(resolve(f"data/splits/{s}.csv")).assign(m1_split=s) for s in ("train", "val", "test")])
    m1_split = dict(zip(m1.path, m1.m1_split))
    rows = []

    # ---- 56td5w4wz2 grades (never seen by Model 1) ----
    for p in sorted((RAW / "banana_guava_quality/extracted/Fruits_Data").rglob("*.jpg")):
        fruit, cls = p.parent.parent.name.lower(), p.parent.name
        rows.append({"path": p.relative_to(RAW).as_posix(), "source": "banana_guava_quality",
                     "task": f"quality_{fruit}", "fruit": fruit, "label_raw": cls, "label": GRADE_MAP[cls]})

    # ---- AgriFreshNET stages ----
    for folder, (fruit, stage) in AGRI.items():
        for p in sorted((RAW / "agrifreshnet/Processed Data" / folder).iterdir()):
            if p.name.startswith("aug_") or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            rows.append({"path": p.relative_to(RAW).as_posix(), "source": "agrifreshnet",
                         "task": f"stage_{fruit}", "fruit": fruit, "label_raw": folder, "label": stage,
                         "class_dir": folder})

    # ---- FruitNet apple (binary) — exactly Model 1's apple rows ----
    for r in m1[m1.fruit == "apple"].itertuples():
        rows.append({"path": r.path, "source": "fruitnet", "task": "quality_apple", "fruit": "apple",
                     "label_raw": "Good" if r.condition == "fresh" else "Bad",
                     "label": "Good" if r.condition == "fresh" else "Poor"})

    df = pd.DataFrame(rows)
    df = pd.concat([df, pd.DataFrame([file_info(p) for p in df.path])], axis=1)
    df["m1_split"] = df.path.map(m1_split)            # NaN = never seen by Model 1

    # Capture bursts (AgriFreshNET filenames carry timestamps; grade set has none)
    df["capture_time"] = pd.to_datetime([filename_time(Path(p).name) for p in df.path])
    df["session"] = ""
    agri = df.source == "agrifreshnet"
    df.loc[agri, "session"] = assign_bursts(df[agri].assign(class_dir=df.loc[agri, "class_dir"]),
                                            gap_seconds=20, counter_gap=3, fallback="class")

    log = {}
    parts = []
    for task, t in df.groupby("task"):
        t = t.copy()
        n0 = len(t)
        # exact duplicates: drop label conflicts entirely, collapse same-label copies
        lab_per_hash = t.groupby("sha256").label.nunique()
        conflict = t.sha256.isin(lab_per_hash[lab_per_hash > 1].index)
        n_conflict = int(conflict.sum())
        t = t[~conflict].drop_duplicates("sha256")
        # groups: near-duplicates + sessions (all rows, so new rows join inherited groups)
        t = assign_duplicate_groups(t, max_distance=16, use_session=True)
        # near-dup groups mixing labels -> drop (label noise)
        mixed = t.groupby("group_id").label.nunique()
        t_mixed = t.group_id.isin(mixed[mixed > 1].index) & (t.groupby("group_id").session.transform("nunique") <= 1) \
            & (t.source != "agrifreshnet")
        n_mixed = int(t_mixed.sum())
        t = t[~t_mixed]
        # split
        inherited = t.groupby("group_id").m1_split.agg(lambda s: set(s.dropna()))
        bad = inherited[inherited.map(len) > 1].index      # group spans Model 1 splits: cannot place safely
        t = t[~t.group_id.isin(bad)]
        fixed = inherited[inherited.map(len) == 1].map(lambda s: next(iter(s)))
        t["split"] = t.group_id.map(fixed).astype(object)
        t["split_origin"] = np.where(t.split.notna(), "inherited_model1", "new_group_split")
        free = t[t.split.isna()]
        if len(free):
            t.loc[free.index, "split"] = stratified_group_split(
                free, {"train": 0.70, "val": 0.15, "test": 0.15}, seed=42, strata_cols=("label",)).to_numpy(object)
        assert_no_leakage(t)
        log[task] = {"rows_in": n0, "dropped_conflicting_exact_dups": n_conflict,
                     "dropped_mixed_label_neardup_groups": n_mixed,
                     "dropped_groups_spanning_model1_splits": int(len(bad)),
                     "rows_out": len(t), "groups": int(t.group_id.nunique()),
                     "counts": t.groupby(["label", "split"]).size().unstack(fill_value=0).to_dict(orient="index"),
                     "split_origin": t.split_origin.value_counts().to_dict()}
        parts.append(t)

    out = pd.concat(parts, ignore_index=True)
    keep = ["path", "source", "task", "fruit", "label_raw", "label", "split", "split_origin", "group_id",
            "session", "m1_split", "sha256", "phash"]
    out[keep].to_csv(OUT / "manifest.csv", index=False)
    (OUT / "prepare_summary.json").write_text(json.dumps(log, indent=2, default=str))
    for k, v in log.items():
        print(k, {a: v[a] for a in ("rows_in", "dropped_conflicting_exact_dups", "dropped_mixed_label_neardup_groups",
                                    "dropped_groups_spanning_model1_splits", "rows_out", "groups")})
        print("   ", v["counts"], v["split_origin"])


if __name__ == "__main__":
    main()
