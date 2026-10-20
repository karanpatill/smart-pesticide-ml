"""Capture-burst grouping to prevent same-specimen leakage across splits.

Public fruit datasets are shot as bursts: many near-identical frames of the
same fruit (FruitNet median gap between frames is 1 s). Perceptual hashing
does not catch rotated or re-framed shots of the same fruit, so images are
additionally grouped by capture time:

  1. EXIF DateTimeOriginal / DateTime, else
  2. a timestamp in the filename (YYYYMMDD[_-]HHMMSS), else
  3. a trailing camera counter in the filename (IMG_1234, IMG-20251122-WA0012),
     compared only among files with the same name pattern, else
  4. no time: all such files of a class folder form one group (`fallback: class`)
     or stay ungrouped (`fallback: none`).

Within one class folder and one time source, a new burst starts whenever the
gap exceeds `gap_seconds` (times) or `counter_gap` (counters).
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
from PIL import Image

_NAME_TS = re.compile(r"(20\d{2}[01]\d[0-3]\d)[_-]?([0-2]\d[0-5]\d[0-5]\d)")
_COUNTER = re.compile(r"(\d+)(?=\D*$)")


def exif_time(im: Image.Image) -> datetime | None:
    try:
        ex = im.getexif()
        v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
        return datetime.strptime(str(v).strip("\x00 "), "%Y:%m:%d %H:%M:%S") if v else None
    except (ValueError, KeyError, AttributeError, OSError):
        return None


def filename_time(name: str) -> datetime | None:
    m = _NAME_TS.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def filename_counter(name: str) -> tuple[str, int] | None:
    """(pattern with the counter masked, counter) or None."""
    m = _COUNTER.search(name)
    if not m:
        return None
    return name[: m.start()] + "#" + name[m.end():], int(m[1])


def assign_bursts(
    df: pd.DataFrame, gap_seconds: float, counter_gap: int, fallback: str = "class"
) -> pd.Series:
    """Return a `session` key per row of df.

    df needs columns: source, class_dir, path, capture_time (datetime or NaT).
    """
    out = pd.Series("", index=df.index, dtype=object)
    for (source, cdir), g in df.groupby(["source", "class_dir"]):
        prefix = f"{source}|{cdir}"
        names = g["path"].str.rsplit("/", n=1).str[-1]

        timed = g[g["capture_time"].notna()].sort_values("capture_time")
        if len(timed):
            secs = timed["capture_time"].astype("int64") // 10**9
            burst = (secs.diff().fillna(0) > gap_seconds).cumsum()
            out[timed.index] = [f"{prefix}|t{b}" for b in burst]

        untimed = g[g["capture_time"].isna()]
        counters = names[untimed.index].map(filename_counter)
        with_ctr = counters.dropna()
        if len(with_ctr):
            c = pd.DataFrame(with_ctr.tolist(), index=with_ctr.index, columns=["pat", "n"])
            for pat_i, (pat, cg) in enumerate(c.groupby("pat")):
                cg = cg.sort_values("n")
                burst = (cg["n"].diff().fillna(0) > counter_gap).cumsum()
                out[cg.index] = [f"{prefix}|c{pat_i}.{b}" for b in burst]

        rest = untimed.index.difference(with_ctr.index)
        if fallback == "class":
            out[rest] = f"{prefix}|notime"
    return out
