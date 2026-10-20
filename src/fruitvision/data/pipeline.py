"""tf.data input pipeline driven by split CSVs.

Images are fed to the model as raw uint8-range float pixels [0, 255]. The
MobileNetV2 normalisation ([-1, 1]) lives *inside* the model, so the exact
same preprocessing runs on the PC and on the STM32 after INT8 conversion.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import tensorflow as tf

AUTOTUNE = tf.data.AUTOTUNE


def load_split(splits_dir: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(splits_dir / f"{name}.csv")


def decode_and_resize(path: tf.Tensor, size: int) -> tf.Tensor:
    data = tf.io.read_file(path)
    img = tf.io.decode_image(data, channels=3, expand_animations=False)
    img.set_shape([None, None, 3])
    return resize_image(img, size)


def resize_image(img: tf.Tensor, size: int) -> tf.Tensor:
    """Aspect-preserving resize + centre crop/pad (avoids distorting fruit shape).

    Shared by images, crops and masks so all stay pixel-aligned.
    """
    img = tf.image.resize(img, [size, size], preserve_aspect_ratio=True, antialias=True)
    img = tf.image.resize_with_crop_or_pad(img, size, size)
    return tf.cast(img, tf.float32)


def build_augmenter(aug_cfg: dict) -> tf.keras.Sequential:
    layers = []
    if aug_cfg.get("flip"):
        layers.append(tf.keras.layers.RandomFlip("horizontal_and_vertical"))
    if aug_cfg.get("rotation"):
        layers.append(tf.keras.layers.RandomRotation(aug_cfg["rotation"], fill_mode="reflect"))
    if aug_cfg.get("zoom"):
        layers.append(tf.keras.layers.RandomZoom(aug_cfg["zoom"], fill_mode="reflect"))
    if aug_cfg.get("brightness"):
        layers.append(tf.keras.layers.RandomBrightness(aug_cfg["brightness"], value_range=(0, 255)))
    if aug_cfg.get("contrast"):
        layers.append(tf.keras.layers.RandomContrast(aug_cfg["contrast"]))
    return tf.keras.Sequential(layers, name="augment")


def make_dataset(
    df: pd.DataFrame,
    raw_dir: Path,
    fruits: list[str],
    conditions: list[str],
    image_size: int,
    batch_size: int,
    training: bool,
    aug_cfg: dict | None = None,
    seed: int = 42,
    balance: bool = False,
) -> tf.data.Dataset:
    """Build a batched dataset yielding (image, {fruit, condition}[, weight]).

    With `balance=True` each sample gets weight N / (K * n_k), where n_k is
    the size of its (fruit, condition) cell and K the number of cells.
    Keras 3 does not support `class_weight` for multi-output models, so
    balancing is done with one sample weight shared by both heads.
    """
    paths = [str(raw_dir / p) for p in df["path"]]
    fruit_idx = df["fruit"].map({f: i for i, f in enumerate(fruits)}).to_numpy()
    cond_idx = df["condition"].map({c: i for i, c in enumerate(conditions)}).to_numpy()
    if pd.isna(fruit_idx).any() or pd.isna(cond_idx).any():
        raise ValueError("split CSV contains labels not present in config")

    labels = {"fruit": fruit_idx.astype("int32"), "condition": cond_idx.astype("int32")}
    if balance:
        cell = df["fruit"].astype(str) + "/" + df["condition"].astype(str)
        counts = cell.map(cell.value_counts())
        weights = (len(df) / (cell.nunique() * counts)).to_numpy("float32")
        ds = tf.data.Dataset.from_tensor_slices((paths, labels, weights))
    else:
        ds = tf.data.Dataset.from_tensor_slices((paths, labels))

    if training:
        ds = ds.shuffle(len(paths), seed=seed, reshuffle_each_iteration=True)
    ds = ds.map(
        lambda p, *rest: (decode_and_resize(p, image_size), *rest),
        num_parallel_calls=AUTOTUNE,
    )
    ds = ds.batch(batch_size)
    if training and aug_cfg:
        augmenter = build_augmenter(aug_cfg)
        ds = ds.map(
            lambda x, *rest: (tf.clip_by_value(augmenter(x, training=True), 0.0, 255.0), *rest),
            num_parallel_calls=AUTOTUNE,
        )
    return ds.prefetch(AUTOTUNE)
