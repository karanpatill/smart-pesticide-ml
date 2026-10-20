"""Generate foreground (fruit) masks for every usable image.

Uses rembg's u2netp (a pretrained salient-object segmentation model; no
training on our labels). Masks are an EXPERIMENTAL preprocessing aid for the
fruit-crop and background-compositing experiments; they are not labels.

Outputs (data/interim/masks/):
  <id>.png       8-bit mask at the original image resolution
  masks.csv      path, mask file, fg_fraction, bbox (normalised x0,y0,x1,y1),
                 n_components, ok flag (False = empty/degenerate mask)
  reports/experiments/masks/overlay_*.jpg   visual check sheets

Known limitation: salient-object segmentation also keeps hands and other
salient objects (FruitNet "Bad" images are mostly hand-held).

Usage:
  python scripts/make_fruit_masks.py
"""

from __future__ import annotations

import argparse
import hashlib

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from scipy import ndimage
from tqdm import tqdm

from fruitvision.config import load_config, resolve


def mask_id(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def bbox_from_mask(m: np.ndarray, min_rel_area: float = 0.1):
    """Union bbox of components >= min_rel_area of the largest one."""
    fg = m > 127
    if fg.mean() < 0.01:
        return None, 0
    lab, n = ndimage.label(fg)
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= min_rel_area * sizes.max()]
    ys, xs = np.nonzero(np.isin(lab, keep))
    h, w = m.shape
    return (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h), len(keep)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="u2netp")
    args = ap.parse_args()

    from rembg import new_session, remove

    cfg = load_config()
    raw = resolve(cfg["paths"]["raw_dir"])
    out = resolve(cfg["paths"]["interim_dir"]) / "masks"
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(resolve(cfg["paths"]["interim_dir"]) / "manifest_clean.csv")
    session = new_session(args.model)

    rows = []
    for p in tqdm(df.path, mininterval=20):
        f = out / f"{mask_id(p)}.png"
        if f.exists():
            m = np.asarray(Image.open(f))
        else:
            with Image.open(raw / p) as im:
                m = np.asarray(remove(im.convert("RGB"), session=session, only_mask=True))
            Image.fromarray(m).save(f)
        bb, ncomp = bbox_from_mask(m)
        rows.append({"path": p, "mask": f.name, "fg_fraction": round(float((m > 127).mean()), 4),
                     "x0": bb[0] if bb else 0.0, "y0": bb[1] if bb else 0.0,
                     "x1": bb[2] if bb else 1.0, "y1": bb[3] if bb else 1.0,
                     "n_components": ncomp, "ok": bb is not None})
    meta = pd.DataFrame(rows)
    meta.to_csv(out / "masks.csv", index=False)

    # Visual check sheets: image with mask tinted + bbox, per source x condition.
    sheet_dir = resolve(cfg["paths"]["reports_dir"]) / "experiments" / "masks"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    full = df.merge(meta, on="path")
    for (src, cond), g in full.groupby(["source", "condition"]):
        smp = g.sample(min(32, len(g)), random_state=0)
        t, cols = 112, 8
        sheet = Image.new("RGB", (cols * t, ((len(smp) + cols - 1) // cols) * t), "white")
        for i, r in enumerate(smp.itertuples()):
            im = Image.open(raw / r.path).convert("RGB").resize((t, t))
            mk = Image.open(out / r.mask).convert("L").resize((t, t))
            red = Image.new("RGB", (t, t), (255, 0, 0))
            im = Image.composite(Image.blend(im, red, 0.35), im, mk)
            ImageDraw.Draw(im).rectangle([r.x0 * t, r.y0 * t, r.x1 * t - 1, r.y1 * t - 1], outline=(0, 255, 0))
            sheet.paste(im, ((i % cols) * t, (i // cols) * t))
        sheet.save(sheet_dir / f"overlay_{src}_{cond}.jpg", quality=85)

    print(meta.ok.value_counts().to_dict())
    print(full.groupby(["source", "condition"]).agg(fg=("fg_fraction", "median"),
                                                    failed=("ok", lambda s: int((~s).sum()))).to_string())


if __name__ == "__main__":
    main()
