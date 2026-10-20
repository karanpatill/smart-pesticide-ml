"""Leakage-free, stratified, group-aware train/val/test split."""

from __future__ import annotations

import numpy as np
import pandas as pd


def stratified_group_split(
    df: pd.DataFrame,
    fractions: dict[str, float],
    seed: int,
    strata_cols: tuple[str, ...] = ("source", "fruit", "condition"),
) -> pd.Series:
    """Return a Series of split names aligned with df.index.

    Whole duplicate groups (`group_id`) are assigned to one split. Within each
    stratum (source x fruit x condition) groups are shuffled and filled
    greedily so each split gets close to its target fraction of *images*.
    Stratifying by source keeps per-dataset evaluation possible.
    """
    names = list(fractions)
    targets = np.array([fractions[k] for k in names])
    rng = np.random.default_rng(seed)
    group_split: dict[int, str] = {}

    # A group is assigned to the stratum of its first member; groups are
    # label-consistent after conflict removal, so this is unambiguous.
    group_stratum = df.groupby("group_id")[list(strata_cols)].first()
    group_size = df.groupby("group_id").size()

    for _, gids in group_stratum.groupby(list(strata_cols)).groups.items():
        gids = np.array(list(gids))
        rng.shuffle(gids)
        # Larger groups first gives a tighter fit to the target ratios.
        # Stable sort keeps the shuffled order among equal-sized groups.
        gids = sorted(gids, key=lambda g: -group_size[g])
        total = group_size[gids].sum()
        filled = np.zeros(len(names))
        for g in gids:
            deficit = targets * total - filled
            k = int(np.argmax(deficit))
            filled[k] += group_size[g]
            group_split[g] = names[k]
    return df["group_id"].map(group_split)


def assert_no_leakage(df: pd.DataFrame, split_col: str = "split") -> None:
    """Raise if any duplicate group or identical file spans multiple splits."""
    for key in ("group_id", "sha256"):
        spans = df.groupby(key)[split_col].nunique()
        leaked = spans[spans > 1]
        if len(leaked):
            raise AssertionError(f"{len(leaked)} '{key}' values span multiple splits")
