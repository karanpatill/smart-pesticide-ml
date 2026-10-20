"""Build the labelled manifest, remove duplicate leakage, and write splits.

Steps:
  1. For each enabled source with `labels_verified: true`, scan images and
     label them ONLY via the explicit `class_dirs` mapping.
  2. Drop corrupt, unmapped and excluded images (all are logged).
  3. Group exact + near duplicates across ALL sources (pHash).
  4. Drop duplicate groups with conflicting labels (logged for review).
  5. Stratified, group-aware split -> data/splits/{train,val,test}.csv
  6. Assert no group / file hash spans two splits.

Usage:
  python scripts/prepare_dataset.py
"""

from __future__ import annotations

import argparse
import json

import pandas as pd

from fruitvision.config import load_config, load_yaml, resolve
from fruitvision.data.dedupe import assign_duplicate_groups, conflicting_groups
from fruitvision.data.manifest import build_source_manifest
from fruitvision.data.split import assert_no_leakage, stratified_group_split


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    sources = load_yaml(cfg["datasets_config"])["sources"]
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    interim = resolve(cfg["paths"]["interim_dir"])
    splits_dir = resolve(cfg["paths"]["splits_dir"])
    interim.mkdir(parents=True, exist_ok=True)
    splits_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for name, spec in sources.items():
        if not spec.get("enabled"):
            continue
        if not spec.get("labels_verified"):
            raise SystemExit(
                f"Source '{name}' is enabled but labels_verified is false.\n"
                f"Run scripts/inspect_dataset.py --source {name}, review the "
                f"contact sheets, fill in class_dirs, then set labels_verified: true."
            )
        frames.append(build_source_manifest(raw_dir, name, spec, cfg["fruits"], cfg["conditions"],
                                            cfg["split"].get("phash_size", 16)))
    if not frames:
        raise SystemExit("No enabled sources.")

    manifest = pd.concat(frames, ignore_index=True)
    manifest.to_csv(interim / "manifest_full.csv", index=False)

    status_counts = manifest.groupby(["source", "status"]).size().unstack(fill_value=0)
    print("Status per source:\n", status_counts, "\n")
    unmapped_dirs = (
        manifest[manifest.status == "unmapped"]["path"].map(lambda p: p.rsplit("/", 1)[0]).value_counts()
    )
    if len(unmapped_dirs):
        print("Unmapped directories (ignored):\n", unmapped_dirs.head(30), "\n")

    usable = manifest[manifest.status == "ok"].copy()
    max_dist = cfg["split"]["phash_max_distance"]

    # Pass 1: image-level duplicates only (no sessions), so one false pHash
    # match cannot drag whole capture sessions into a label conflict.
    dup = assign_duplicate_groups(usable, max_dist, use_session=False)
    conflicts = conflicting_groups(dup)
    conflicts.to_csv(interim / "duplicate_label_conflicts.csv", index=False)
    dup.to_csv(interim / "duplicate_groups_imagelevel.csv", index=False)
    usable = dup[~dup["group_id"].isin(conflicts["group_id"])]

    # Keep one image per *exact* duplicate set.
    n_before = len(usable)
    usable = usable.drop_duplicates("sha256")
    n_exact_dups = n_before - len(usable)
    n_near_dup_images = int((usable["group_size"] > 1).sum())

    # Pass 2: final split groups = near duplicates + capture sessions.
    usable = assign_duplicate_groups(
        usable.drop(columns=["group_id", "group_size"]), max_dist, use_session=True
    )

    fractions = {k: cfg["split"][k] for k in ("train", "val", "test")}
    usable["split"] = stratified_group_split(usable, fractions, cfg["seed"])
    assert_no_leakage(usable)

    usable.to_csv(interim / "manifest_clean.csv", index=False)
    for split in ("train", "val", "test"):
        usable[usable.split == split].to_csv(splits_dir / f"{split}.csv", index=False)

    table = usable.groupby(["fruit", "condition", "split"]).size().unstack(fill_value=0)
    by_source = usable.groupby(["source", "fruit", "condition"]).size()
    summary = {
        "total_scanned": int(len(manifest)),
        "usable_after_cleaning": int(len(usable)),
        "exact_duplicates_removed": int(n_exact_dups),
        "conflicting_label_groups_dropped": int(conflicts["group_id"].nunique()),
        "images_in_conflicting_groups": int(len(conflicts)),
        "images_in_near_duplicate_sets": n_near_dup_images,
        "split_groups": int(usable["group_id"].nunique()),
        "largest_split_group": int(usable["group_size"].max()),
        "split_sizes": usable["split"].value_counts().to_dict(),
    }
    (interim / "prepare_summary.json").write_text(json.dumps(summary, indent=2))
    print("Counts (fruit x condition x split):\n", table, "\n")
    print("Counts per source:\n", by_source, "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
