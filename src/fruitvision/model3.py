"""Model 3 graph construction (shared by training and artifact rebuilding).

The combined model is built as ONE flat functional graph that reuses Model 1's
layers (normalize -> mobilenetv2_backbone -> gap -> dropout -> fruit/condition)
and attaches the Model 3 head layers to Model 1's `gap` tensor. Model 1's
weights are shared, frozen and not modified. A flat graph is required because
Keras 3 cannot reload models that nest a sub-model sharing layers with another.
"""

from __future__ import annotations

import tensorflow as tf


def apply_head(head: tf.keras.Model, x):
    """Apply a (Sequential-like functional) head's layers to tensor x."""
    for layer in head.layers:
        # Dropout is the identity at inference and has no weights; skipping it also
        # avoids a layer-name clash with Model 1's own `dropout` layer.
        if isinstance(layer, (tf.keras.layers.InputLayer, tf.keras.layers.Dropout)):
            continue
        x = layer(x)
    return x


def build_combined(model1: tf.keras.Model, heads: dict[str, tf.keras.Model], size: int = 80) -> tf.keras.Model:
    model1.trainable = False
    img = tf.keras.Input((size, size, 3), name="image")
    x = model1.get_layer("normalize")(img)
    x = model1.get_layer("mobilenetv2_backbone")(x, training=False)
    g = model1.get_layer("gap")(x)
    d = model1.get_layer("dropout")(g, training=False)
    outputs = {"fruit": model1.get_layer("fruit")(d), "condition": model1.get_layer("condition")(d)}
    for name, head in heads.items():
        outputs[name] = apply_head(head, g)
    return tf.keras.Model(img, outputs, name="model1_plus_model3")
