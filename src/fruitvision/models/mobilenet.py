"""MobileNetV2 transfer-learning model with two classification heads.

    input (H, W, 3) raw pixels 0..255
      -> Rescaling to [-1, 1]            (inside the graph -> same on MCU)
      -> MobileNetV2 backbone (ImageNet, alpha)
      -> GlobalAveragePooling -> Dropout
      -> fruit head      softmax(len(fruits))
      -> condition head  softmax(len(conditions))

Only standard ops (Conv2D, DepthwiseConv2D, ReLU6, Add, Mean, FullyConnected,
Softmax) are used so the INT8 model stays compatible with TFLite Micro and
STM32Cube.AI.
"""

from __future__ import annotations

import tensorflow as tf

BACKBONE_NAME = "mobilenetv2_backbone"


def build_model(
    num_fruits: int,
    num_conditions: int,
    image_size: int = 96,
    alpha: float = 0.35,
    dropout: float = 0.2,
    head_units: int = 0,
    weights: str | None = "imagenet",
    cut_layer: str | None = None,
) -> tf.keras.Model:
    """Build the two-head model.

    `cut_layer` truncates the backbone at the named MobileNetV2 layer (e.g.
    "block_16_project_BN"), dropping the later blocks. The full alpha=0.35
    backbone is ~590 KB as INT8, which does not fit in 512 KB of flash, so
    truncation is the main size lever (see docs/DEPLOYMENT_BUDGET.md).
    """
    inputs = tf.keras.Input(shape=(image_size, image_size, 3), name="image")
    x = tf.keras.layers.Rescaling(1.0 / 127.5, offset=-1.0, name="normalize")(inputs)

    backbone = tf.keras.applications.MobileNetV2(
        input_shape=(image_size, image_size, 3),
        alpha=alpha,
        include_top=False,
        weights=weights,
    )
    # Re-wrap so the backbone has a stable name (Keras 3 ignores `_name`).
    out = backbone.get_layer(cut_layer).output if cut_layer else backbone.output
    backbone = tf.keras.Model(backbone.input, out, name=BACKBONE_NAME)
    backbone.trainable = False

    # training=False keeps BatchNorm in inference mode even when fine-tuning,
    # which is the recommended practice for small datasets.
    x = backbone(x, training=False)
    x = tf.keras.layers.GlobalAveragePooling2D(name="gap")(x)
    x = tf.keras.layers.Dropout(dropout, name="dropout")(x)
    if head_units:
        x = tf.keras.layers.Dense(head_units, activation="relu", name="shared_dense")(x)

    fruit = tf.keras.layers.Dense(num_fruits, activation="softmax", name="fruit")(x)
    condition = tf.keras.layers.Dense(num_conditions, activation="softmax", name="condition")(x)
    return tf.keras.Model(inputs, {"fruit": fruit, "condition": condition}, name="fruitvision")


def get_backbone(model: tf.keras.Model) -> tf.keras.Model:
    return model.get_layer(BACKBONE_NAME)


def unfreeze_top(model: tf.keras.Model, n_layers: int) -> None:
    """Unfreeze the last `n_layers` of the backbone, keeping BatchNorm frozen."""
    backbone = get_backbone(model)
    backbone.trainable = True
    cutoff = len(backbone.layers) - n_layers
    for i, layer in enumerate(backbone.layers):
        trainable = i >= cutoff and not isinstance(layer, tf.keras.layers.BatchNormalization)
        layer.trainable = trainable


def compile_model(model: tf.keras.Model, lr: float, loss_weights: dict[str, float]) -> None:
    model.compile(
        optimizer=tf.keras.optimizers.Adam(lr),
        loss={
            "fruit": tf.keras.losses.SparseCategoricalCrossentropy(),
            "condition": tf.keras.losses.SparseCategoricalCrossentropy(),
        },
        loss_weights=loss_weights,
        metrics={
            "fruit": [tf.keras.metrics.SparseCategoricalAccuracy(name="acc")],
            "condition": [tf.keras.metrics.SparseCategoricalAccuracy(name="acc")],
        },
    )
