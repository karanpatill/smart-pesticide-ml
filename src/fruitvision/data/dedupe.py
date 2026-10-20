"""Exact and near-duplicate grouping.

Many public fruit datasets contain duplicated or augmented copies of the same
photo (sometimes across classes or across datasets). If copies end up in
different splits, test accuracy is inflated. We assign every image a
`group_id`; images in the same group always go to the same split.
"""

from __future__ import annotations

import imagehash
import numpy as np
import pandas as pd


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def assign_duplicate_groups(
    df: pd.DataFrame, max_distance: int, use_session: bool = True
) -> pd.DataFrame:
    """Add `group_id` and `group_size` columns.

    Rows sharing a capture `session` key are grouped too (if the column exists).
    Exact duplicates are found via SHA-256. Near duplicates via pHash Hamming
    distance <= max_distance (any hash size; O(n^2), fine for ~20k images).
    """
    df = df.reset_index(drop=True).copy()
    n = len(df)
    uf = _UnionFind(n)

    keys = ["sha256"] + (["session"] if use_session and "session" in df else [])
    for key in keys:
        for k, idx in df.groupby(key).groups.items():
            if key == "session" and (not isinstance(k, str) or not k):
                continue  # no session information
            idx = list(idx)
            for j in idx[1:]:
                uf.union(idx[0], j)

    if max_distance > 0 and n > 1:
        bits = np.stack(
            [imagehash.hex_to_hash(h).hash.flatten() for h in df["phash"]]
        ).astype(np.uint8)
        packed = np.packbits(bits, axis=1)  # (n, bits/8) bytes
        popcount = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(1)
        for i in range(n - 1):
            xor = np.bitwise_xor(packed[i + 1 :], packed[i])
            dist = popcount[xor].sum(axis=1)
            for j in np.nonzero(dist <= max_distance)[0]:
                uf.union(i, i + 1 + int(j))

    roots = [uf.find(i) for i in range(n)]
    df["group_id"] = pd.factorize(pd.Series(roots))[0]
    df["group_size"] = df.groupby("group_id")["group_id"].transform("size")
    return df


def conflicting_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Duplicate groups whose members carry different labels.

    These indicate label noise (same photo, different class) and must be
    reviewed by a human; prepare_dataset drops them by default.
    """
    labels = df["fruit"].astype(str) + "/" + df["condition"].astype(str)
    n_labels = labels.groupby(df["group_id"]).nunique()
    bad = n_labels[n_labels > 1].index
    return df[df["group_id"].isin(bad)].sort_values("group_id")
