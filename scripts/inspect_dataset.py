"""Audit a downloaded raw dataset BEFORE any labels are mapped.

Produces, under reports/dataset_audit/<source>/:
  - tree.csv          image count / formats / size stats per directory
  - summary.txt       totals, corrupt files, exact duplicates (incl. cross-dir)
  - samples/<dir>.jpg contact sheet of random images from every leaf dir,
                      so a human can confirm what each folder really contains.

Usage:
  python scripts/inspect_dataset.py --source fruitnet
  python scripts/inspect_dataset.py --path data/raw/some_folder --name tmp
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections import defaultdict
from pathlib import Path

import pandas as pd
from PIL import Image, ImageOps, UnidentifiedImageError
from tqdm import tqdm

from fruitvision.config import load_config, load_yaml, resolve
from fruitvision.data.manifest import iter_images


def contact_sheet(paths: list[Path], out: Path, thumb: int = 128, cols: int = 6) -> None:
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb, rows * thumb), "white")
    for i, p in enumerate(paths):
        try:
            with Image.open(p) as im:
                t = ImageOps.fit(im.convert("RGB"), (thumb, thumb))
            sheet.paste(t, ((i % cols) * thumb, (i // cols) * thumb))
        except (UnidentifiedImageError, OSError):
            pass
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=85)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="source name from configs/datasets.yaml")
    ap.add_argument("--path", help="explicit folder to inspect (instead of --source)")
    ap.add_argument("--name", help="report name when using --path")
    ap.add_argument("--samples", type=int, default=24, help="images per contact sheet")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cfg = load_config()
    if args.source:
        spec = load_yaml(cfg["datasets_config"])["sources"][args.source]
        root = resolve(cfg["paths"]["raw_dir"]) / spec["root"]
        name = args.source
    elif args.path:
        root = resolve(args.path)
        name = args.name or root.name
    else:
        ap.error("give --source or --path")
    if not root.is_dir():
        raise SystemExit(f"Folder not found: {root}")

    out_dir = resolve(cfg["paths"]["reports_dir"]) / "dataset_audit" / name
    rng = random.Random(args.seed)

    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for p in iter_images(root):
        by_dir[p.parent].append(p)

    rows, corrupt = [], []
    hashes: dict[str, list[Path]] = defaultdict(list)
    for d, files in tqdm(sorted(by_dir.items()), desc="dirs"):
        widths, heights, exts = [], [], defaultdict(int)
        for f in files:
            exts[f.suffix.lower()] += 1
            try:
                with Image.open(f) as im:
                    w, h = im.size
                widths.append(w)
                heights.append(h)
            except (UnidentifiedImageError, OSError):
                corrupt.append(f)
            hashes[hashlib.sha256(f.read_bytes()).hexdigest()].append(f)
        rel = d.relative_to(root).as_posix()
        rows.append({
            "dir": rel,
            "images": len(files),
            "formats": dict(exts),
            "w_min": min(widths, default=0), "w_max": max(widths, default=0),
            "h_min": min(heights, default=0), "h_max": max(heights, default=0),
        })
        sample = rng.sample(files, min(args.samples, len(files)))
        sheet_name = (rel.replace("/", "__") if rel != "." else "_root") + ".jpg"
        contact_sheet(sample, out_dir / "samples" / sheet_name)

    out_dir.mkdir(parents=True, exist_ok=True)
    tree = pd.DataFrame(rows)
    tree.to_csv(out_dir / "tree.csv", index=False)

    dup_sets = [v for v in hashes.values() if len(v) > 1]
    cross_dir = [v for v in dup_sets if len({p.parent for p in v}) > 1]
    lines = [
        f"root: {root}",
        f"directories with images: {len(by_dir)}",
        f"total images: {int(tree['images'].sum()) if len(tree) else 0}",
        f"corrupt/unreadable: {len(corrupt)}",
        f"exact-duplicate sets: {len(dup_sets)} "
        f"({sum(len(v) - 1 for v in dup_sets)} redundant files)",
        f"exact-duplicate sets spanning >1 directory: {len(cross_dir)}",
        "",
        "Examples of cross-directory duplicates (possible label conflicts):",
        *[" | ".join(p.relative_to(root).as_posix() for p in v) for v in cross_dir[:20]],
        "",
        "Corrupt files:",
        *[p.relative_to(root).as_posix() for p in corrupt[:50]],
    ]
    (out_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")

    with pd.option_context("display.max_rows", 500, "display.width", 200):
        print(tree.to_string(index=False))
    print("\n".join(lines[:6]))
    print(f"\nReport written to {out_dir}")


if __name__ == "__main__":
    main()
