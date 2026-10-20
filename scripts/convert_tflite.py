"""Convert a trained Keras model to TFLite (float32 reference + full INT8).

INT8 conversion uses a representative dataset drawn from the TRAIN split
(never val/test) with the exact training preprocessing and no augmentation.
Input and output tensors are int8 so the STM32 can feed camera pixels
directly (quantised) with no float math in the pipeline.

After conversion, run scripts/evaluate.py on the .tflite file to measure the
accuracy drop caused by quantisation on the test split.

Usage:
  python scripts/convert_tflite.py --run <run-name>
"""

from __future__ import annotations

import argparse
import json
import tempfile

import numpy as np
import tensorflow as tf

from fruitvision.config import load_config, resolve
from fruitvision.data.pipeline import load_split
from fruitvision.inference import load_image

# STM32F407VET6 limits; the firmware itself also needs space, so these are
# upper bounds, not targets. Exact RAM use must be checked with STM32Cube.AI.
FLASH_BYTES = 512 * 1024
SRAM_BYTES = 192 * 1024


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/config.yaml")
    ap.add_argument("--run", required=True, help="run name under models/runs")
    ap.add_argument("--weights", default="best.keras")
    args = ap.parse_args()

    cfg = load_config(args.config)
    run_dir = resolve(cfg["paths"]["models_dir"]) / "runs" / args.run
    out_dir = resolve(cfg["paths"]["models_dir"]) / "tflite"
    out_dir.mkdir(parents=True, exist_ok=True)

    model = tf.keras.models.load_model(run_dir / args.weights)
    size = int(model.input_shape[1])

    train_df = load_split(resolve(cfg["paths"]["splits_dir"]), "train")
    n = min(cfg["tflite"]["representative_samples"], len(train_df))
    # Stratified sample so every fruit/condition calibrates the quantiser.
    rep_df = (train_df.groupby(["fruit", "condition"], group_keys=False)
              .apply(lambda g: g.sample(min(len(g), max(1, n // 10)), random_state=cfg["seed"])))
    raw_dir = resolve(cfg["paths"]["raw_dir"])

    def representative_dataset():
        for p in rep_df["path"]:
            yield [load_image(raw_dir / p, size)[None].astype(np.float32)]

    with tempfile.TemporaryDirectory() as tmp:
        model.export(tmp)  # SavedModel; the most reliable converter input under Keras 3

        conv = tf.lite.TFLiteConverter.from_saved_model(tmp)
        float_model = conv.convert()

        conv = tf.lite.TFLiteConverter.from_saved_model(tmp)
        conv.optimizations = [tf.lite.Optimize.DEFAULT]
        conv.representative_dataset = representative_dataset
        conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        conv.inference_input_type = tf.int8
        conv.inference_output_type = tf.int8
        int8_model = conv.convert()

    paths = {"float32": out_dir / f"{args.run}_float32.tflite",
             "int8": out_dir / f"{args.run}_int8.tflite"}
    paths["float32"].write_bytes(float_model)
    paths["int8"].write_bytes(int8_model)

    interp = tf.lite.Interpreter(model_content=int8_model)
    interp.allocate_tensors()
    ops = sorted({d["op_name"] for d in interp._get_ops_details()})
    info = {
        "run": args.run,
        "input": {k: str(v) for k, v in interp.get_input_details()[0].items()
                  if k in ("shape", "dtype", "quantization")},
        "outputs": [{k: str(v) for k, v in d.items() if k in ("name", "shape", "dtype", "quantization")}
                    for d in interp.get_output_details()],
        "size_bytes": {k: len(v) for k, v in (("float32", float_model), ("int8", int8_model))},
        "int8_ops": ops,
        "representative_samples": int(len(rep_df)),
        "stm32f407vet6_flash_fraction": round(len(int8_model) / FLASH_BYTES, 3),
    }
    (out_dir / f"{args.run}_int8.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))

    if len(int8_model) > 0.8 * FLASH_BYTES:
        print(f"\nWARNING: INT8 model is {len(int8_model)/1024:.0f} KB, more than 80% of the "
              f"{FLASH_BYTES//1024} KB flash. Reduce input size, truncate the backbone, "
              f"or consider external flash. See docs/DEPLOYMENT_BUDGET.md.")
    print("\nNext: python scripts/evaluate.py --model", paths["int8"], "--tag", f"{args.run}_int8")
    print("Then check RAM/flash in STM32Cube.AI (X-CUBE-AI) 'Analyze' before firmware work.")


if __name__ == "__main__":
    main()
