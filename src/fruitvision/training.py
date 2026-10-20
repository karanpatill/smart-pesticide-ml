"""In-memory training utilities shared by the sweep and shortcut experiments.

Images are decoded once with the SAME `decode_and_resize` used everywhere else
and cached as uint8 arrays per input size, so repeated cross-validation runs
do not re-decode JPEGs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from PIL import Image
from tqdm import tqdm

from fruitvision.data.pipeline import build_augmenter, decode_and_resize, resize_image
from fruitvision.models.mobilenet import build_model, compile_model, unfreeze_top

AUTOTUNE = tf.data.AUTOTUNE


def cached_images(paths: list[str], raw_dir: Path, size: int, cache_dir: Path) -> np.ndarray:
    key = hashlib.sha1(("\n".join(paths) + f"|{size}").encode()).hexdigest()[:12]
    f = cache_dir / f"images_{size}px_{key}.npy"
    if f.exists():
        return np.load(f)
    arr = np.zeros((len(paths), size, size, 3), np.uint8)
    for i, p in enumerate(tqdm(paths, desc=f"cache {size}px", mininterval=10)):
        arr[i] = np.clip(decode_and_resize(tf.constant(str(raw_dir / p)), size).numpy(), 0, 255)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(f, arr)
    return arr


def _cache(key_parts: str, prefix: str, size: int, cache_dir: Path, build) -> np.ndarray:
    key = hashlib.sha1((key_parts + f"|{size}").encode()).hexdigest()[:12]
    f = cache_dir / f"{prefix}_{size}px_{key}.npy"
    if f.exists():
        return np.load(f)
    arr = build()
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(f, arr)
    return arr


def square_crop_box(x0, y0, x1, y1, w, h, pad=0.15):
    """Square box around a normalised bbox, padded, clipped to the image."""
    cx, cy = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h
    side = max((x1 - x0) * w, (y1 - y0) * h) * (1 + 2 * pad)
    side = max(side, 0.2 * min(w, h))
    left, top = max(0, cx - side / 2), max(0, cy - side / 2)
    right, bottom = min(w, cx + side / 2), min(h, cy + side / 2)
    return int(left), int(top), int(round(right)), int(round(bottom))


def cached_crops(paths, boxes, raw_dir: Path, size: int, cache_dir: Path) -> np.ndarray:
    """Fruit-crop variant: crop each image to its (padded, square) fruit bbox,
    then apply the standard resize. `boxes` = (x0, y0, x1, y1) normalised."""
    boxes = [tuple(map(float, b)) for b in boxes]

    def build():
        arr = np.zeros((len(paths), size, size, 3), np.uint8)
        for i, (p, b) in enumerate(tqdm(list(zip(paths, boxes)), desc=f"crops {size}px", mininterval=10)):
            with Image.open(raw_dir / p) as im:
                im = im.convert("RGB")
                crop = np.asarray(im.crop(square_crop_box(*b, *im.size)))
            arr[i] = np.clip(resize_image(tf.constant(crop), size).numpy(), 0, 255)
        return arr

    return _cache("\n".join(paths) + str(boxes), "crops", size, cache_dir, build)


def cached_masks(mask_files, mask_dir: Path, size: int, cache_dir: Path) -> np.ndarray:
    """Masks resized exactly like the images (aligned), shape (N, size, size, 1)."""
    def build():
        arr = np.zeros((len(mask_files), size, size, 1), np.uint8)
        for i, f in enumerate(tqdm(mask_files, desc=f"masks {size}px", mininterval=10)):
            m = np.asarray(Image.open(mask_dir / f).convert("L"))[..., None]
            arr[i] = np.clip(resize_image(tf.constant(m), size).numpy(), 0, 255)
        return arr

    return _cache("\n".join(mask_files), "masks", size, cache_dir, build)


def cached_mask_crops(mask_files, boxes, mask_dir: Path, size: int, cache_dir: Path) -> np.ndarray:
    """Masks cropped with the SAME square box as `cached_crops`, so they stay
    aligned with the cropped images. Shape (N, size, size, 1)."""
    boxes = [tuple(map(float, b)) for b in boxes]

    def build():
        arr = np.zeros((len(mask_files), size, size, 1), np.uint8)
        for i, (f, b) in enumerate(tqdm(list(zip(mask_files, boxes)), desc=f"mask crops {size}px",
                                        mininterval=10)):
            with Image.open(mask_dir / f) as m:
                m = m.convert("L")
                crop = np.asarray(m.crop(square_crop_box(*b, *m.size)))[..., None]
            arr[i] = np.clip(resize_image(tf.constant(crop), size).numpy(), 0, 255)
        return arr

    return _cache("\n".join(mask_files) + str(boxes), "maskcrops", size, cache_dir, build)


def background_bank(x: np.ndarray, n: int, seed: int, frac: float = 0.35) -> np.ndarray:
    """Background textures: corner patches (mostly background) of random
    TRAINING images, upscaled to full size. Mixing backgrounds across
    classes/sources decorrelates background from label."""
    rng = np.random.default_rng(seed)
    size = x.shape[1]
    c = max(4, int(size * frac))
    out = np.zeros((n, size, size, 3), np.uint8)
    for k in range(n):
        img = x[rng.integers(len(x))]
        oy, ox = rng.choice([0, size - c]), rng.choice([0, size - c])
        patch = img[oy:oy + c, ox:ox + c]
        out[k] = np.asarray(Image.fromarray(patch).resize((size, size), Image.BILINEAR))
    return out


def mask_center(x: np.ndarray, frac: float = 0.6, value: int = 127) -> np.ndarray:
    """Grey out the central frac x frac square (where the fruit usually is)."""
    x = x.copy()
    s = x.shape[1]
    a, b = int(s * (1 - frac) / 2), int(s * (1 + frac) / 2)
    x[:, a:b, a:b, :] = value
    return x


def labels(df: pd.DataFrame, fruits: list[str], conditions: list[str]) -> dict[str, np.ndarray]:
    return {
        "fruit": df["fruit"].map({f: i for i, f in enumerate(fruits)}).to_numpy("int32"),
        "condition": df["condition"].map({c: i for i, c in enumerate(conditions)}).to_numpy("int32"),
    }


def balance_weights(df: pd.DataFrame) -> np.ndarray:
    cell = df["fruit"].astype(str) + "/" + df["condition"].astype(str)
    return (len(df) / (cell.nunique() * cell.map(cell.value_counts()))).to_numpy("float32")


def _ds(x, y, w=None, batch=32, training=False, aug=None, seed=0, composite=None):
    """composite = {"masks": (N,H,W,1) uint8, "bank": (K,H,W,3) uint8, "p": float}:
    with probability p, replace the background by a random bank texture
    (70%) or a random solid colour (30%) using the fruit mask."""
    t = (x, y) if w is None else (x, y, w)
    if composite is not None:
        t = (x, composite["masks"], *t[1:])
    ds = tf.data.Dataset.from_tensor_slices(t)
    if training:
        ds = ds.shuffle(len(x), seed=seed, reshuffle_each_iteration=True)
    if composite is not None:
        bank = tf.constant(composite["bank"])
        p = composite["p"]

        def comp(img, m, *rest):
            img, m = tf.cast(img, tf.float32), tf.cast(m, tf.float32) / 255.0
            k = tf.random.uniform([], 0, tf.shape(bank)[0], dtype=tf.int32)
            tex = tf.cast(bank[k], tf.float32)
            solid = tf.ones_like(img) * tf.random.uniform([1, 1, 3], 0, 255)
            bg = tf.where(tf.random.uniform([]) < 0.7, tex, solid)
            mixed = m * img + (1 - m) * bg
            return (tf.where(tf.random.uniform([]) < p, mixed, img), *rest)

        ds = ds.map(comp, num_parallel_calls=AUTOTUNE)
    ds = ds.batch(batch).map(lambda a, *r: (tf.cast(a, tf.float32), *r), num_parallel_calls=AUTOTUNE)
    if aug is not None:
        ds = ds.map(lambda a, *r: (tf.clip_by_value(aug(a, training=True), 0, 255), *r),
                    num_parallel_calls=AUTOTUNE)
    return ds.prefetch(AUTOTUNE)


def fit(
    x_tr, y_tr, w_tr, x_va, y_va, cfg: dict, size: int, cut: str | None,
    head_epochs: int, ft_epochs: int, seed: int, verbose: int = 0, composite: dict | None = None,
    callbacks: list | None = None,
) -> tf.keras.Model:
    """Two-stage transfer learning; returns the model with best val-loss weights
    (of the last stage, restored by early stopping).

    `callbacks` are added to BOTH stages (e.g. one shared ModelCheckpoint);
    they only observe training. Per-stage Keras histories are attached as
    `model.stage_histories` = [stage1_history_dict, stage2_history_dict].
    """
    tf.keras.backend.clear_session()
    tf.keras.utils.set_random_seed(seed)
    m, tr = cfg["model"], cfg["train"]
    model = build_model(len(cfg["fruits"]), len(cfg["conditions"]), size, m["alpha"],
                        m["dropout"], m["head_units"], cut_layer=cut)
    aug = build_augmenter(cfg["augment"])
    tr_ds = _ds(x_tr, y_tr, w_tr, tr["batch_size"], True, aug, seed, composite)
    va_ds = _ds(x_va, y_va, None, 128)
    es = lambda: tf.keras.callbacks.EarlyStopping(  # noqa: E731
        monitor="val_loss", patience=tr["early_stopping_patience"], restore_best_weights=True)

    compile_model(model, tr["head_lr"], m["loss_weights"])
    extra = list(callbacks or [])
    hist = [model.fit(tr_ds, validation_data=va_ds, epochs=head_epochs, callbacks=[es(), *extra],
                      verbose=verbose).history]
    if ft_epochs > 0:
        unfreeze_top(model, tr["finetune_unfreeze_layers"])
        compile_model(model, tr["finetune_lr"], m["loss_weights"])
        hist.append(model.fit(tr_ds, validation_data=va_ds, epochs=ft_epochs, callbacks=[es(), *extra],
                              verbose=verbose).history)
    model.stage_histories = hist
    return model


def predict(model: tf.keras.Model, x: np.ndarray) -> dict[str, np.ndarray]:
    out = model.predict(_ds(x, np.zeros(len(x)), None, 256), verbose=0)
    return {k: np.asarray(v) for k, v in out.items()}
