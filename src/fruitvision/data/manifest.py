"""Build an image manifest from raw dataset folders using explicit label maps.

Labels come only from `class_dirs` in configs/datasets.yaml. An image is
labelled only if one of its ancestor directory names matches a mapping
exactly (case-insensitive). Anything else is recorded as `unmapped` and
never used for training.

Optional per-source settings:
  exclude_file_patterns: [regex, ...]   filenames to drop (e.g. pre-augmented
                                        copies); recorded as status `excluded`.
  session:                              capture-burst grouping (see sessions.py)
    gap_seconds: 20                     new burst after a time gap > this
    counter_gap: 3                      ... or a filename-counter jump > this
    fallback: class | none              files with no time info: one group per
                                        class dir (conservative) or ungrouped
Images with the same session key are kept in the same split, because
consecutive shots of the same fruit are near-identical even when their
perceptual hashes differ.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import imagehash
import pandas as pd
from PIL import Image, UnidentifiedImageError
from tqdm import tqdm

from fruitvision.data.sessions import assign_bursts, exif_time, filename_time

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Record:
    path: str               # path relative to data/raw
    source: str
    class_dir: str | None   # the directory that produced the label
    fruit: str | None
    condition: str | None   # harmonised condition, None = not used
    condition_raw: str | None
    status: str             # ok | unmapped | excluded | corrupt
    width: int = 0
    height: int = 0
    sha256: str = ""
    phash: str = ""
    capture_time: str = ""  # ISO time from EXIF or filename ("" = unknown)
    time_source: str = ""   # exif | filename | ""
    session: str = ""       # capture-burst group key ("" = none)
    note: str = ""          # why an image was excluded, if it was


def iter_images(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def match_class_dir(rel_path: Path, class_dirs: dict[str, Any]) -> tuple[str | None, dict | None]:
    """Return the deepest ancestor directory that has a mapping."""
    lookup = {k.lower(): (k, v) for k, v in class_dirs.items()}
    for part in reversed(rel_path.parent.parts):
        hit = lookup.get(part.lower())
        if hit is not None:
            return hit
    return None, None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_source_manifest(
    raw_dir: Path,
    name: str,
    spec: dict[str, Any],
    fruits: list[str],
    conditions: list[str],
    phash_size: int = 16,
) -> pd.DataFrame:
    root = raw_dir / spec["root"]
    if not root.is_dir():
        raise FileNotFoundError(f"[{name}] raw folder not found: {root}")
    class_dirs = spec.get("class_dirs") or {}
    _check_mapping(name, class_dirs, fruits, conditions)
    exclude_res = [re.compile(r) for r in spec.get("exclude_file_patterns") or []]
    sess = spec.get("session")

    records: list[Record] = []
    for img_path in tqdm(list(iter_images(root)), desc=f"scan {name}"):
        rel_to_root = img_path.relative_to(root)
        class_dir, m = match_class_dir(rel_to_root, class_dirs)
        rec = Record(
            path=img_path.relative_to(raw_dir).as_posix(),
            source=name,
            class_dir=class_dir,
            fruit=None,
            condition=None,
            condition_raw=None,
            status="unmapped",
        )
        if m is not None:
            rec.fruit = m.get("fruit")
            rec.condition = m.get("condition")
            rec.condition_raw = m.get("condition_raw")
            rec.status = "excluded" if m.get("exclude") or rec.condition is None else "ok"
            if rec.status == "excluded":
                rec.note = "class excluded by mapping"
            hit = next((r.pattern for r in exclude_res if r.search(rel_to_root.as_posix())), None)
            if hit:
                rec.status, rec.note = "excluded", f"filename matches {hit}"

        if rec.status == "unmapped":
            records.append(rec)  # never used: skip the expensive decode/hash
            continue
        try:
            with Image.open(img_path) as im:
                im.load()
                rec.width, rec.height = im.size
                rec.phash = str(imagehash.phash(im.convert("RGB"), hash_size=phash_size))
                t, rec.time_source = exif_time(im), "exif"
            if t is None:
                t, rec.time_source = filename_time(img_path.name), "filename"
            if t is None:
                rec.time_source = ""
            rec.capture_time = t.isoformat() if t else ""
            rec.sha256 = file_sha256(img_path)
        except (UnidentifiedImageError, OSError) as e:
            rec.status = "corrupt"
            rec.condition_raw = f"{rec.condition_raw} | error: {e}"
        records.append(rec)

    df = pd.DataFrame([asdict(r) for r in records])
    if sess and len(df):
        mapped = df["class_dir"].notna()
        sub = df[mapped].assign(capture_time=pd.to_datetime(df.loc[mapped, "capture_time"].replace("", None)))
        df.loc[mapped, "session"] = assign_bursts(
            sub, sess.get("gap_seconds", 20), sess.get("counter_gap", 3), sess.get("fallback", "class")
        )
    return df


def _check_mapping(name: str, class_dirs: dict, fruits: list[str], conditions: list[str]) -> None:
    for d, m in class_dirs.items():
        if m.get("exclude"):
            continue
        if m.get("fruit") not in fruits:
            raise ValueError(f"[{name}] class_dir '{d}': fruit '{m.get('fruit')}' not in {fruits}")
        if m.get("condition") is not None and m["condition"] not in conditions:
            raise ValueError(
                f"[{name}] class_dir '{d}': condition '{m['condition']}' not in {conditions}"
            )
