# Model 1: locked image model (artifacts produced 2026-10-09)

**Approved and locked:** MobileNetV2-0.35 · 80×80 input · backbone cut at
`block_15_add` · full-frame camera input · trained with background
compositing · no on-device cropping or segmentation.
Selection rationale: docs/EXPERIMENTS_02_MODEL1_DECISION.md.

Model 1 classifies **fruit type** (apple, banana, guava, tomato, brinjal) and
**visual condition** (fresh / spoiled). It does not detect pesticide
residue, and its confidences are softmax probabilities, not a freshness
percentage. It is **not** a validated robust spoilage detector (see "Known
limitations").

## Artifacts (`models/model1/`)
| # | Item | Path |
|---|---|---|
| 1 | Best checkpoint (lowest val loss over both stages) | `models/model1/best_checkpoint.keras` |
| 2 | Final model / final weights | `models/model1/model1_final.keras`, `models/model1/model1_final.weights.h5` |
| 3 | Training configuration (recipe, data hashes, environment, config snapshot) | `models/model1/training_config.json` |
| 4 | Label mapping | `models/model1/labels.json` |
| 5 | Preprocessing configuration | `models/model1/preprocessing.json` |
| 6 | Normalisation parameters | `models/model1/preprocessing.json` → `normalization` |
| 7 | Architecture | `models/model1/model_architecture.json`, `model_summary.txt`, `model_info.json` |
| 8 | Training metrics (per epoch, both stages) | `models/model1/training_history.csv` |
| 9 | Validation (+ test) metrics | `models/model1/metrics.json`; per-class P/R/F1 and confusion matrices in `reports/model1/final/{val,test}/` |
| 10 | Inference script | `scripts/model1_predict.py` |
| – | Inference verification | `reports/model1/inference_verification.{txt,json}` |
| – | Training script that produced these | `scripts/train_model1.py` (refuses to overwrite existing artifacts) |

The best checkpoint and the final model are the **same weights**. The lowest
validation loss (0.653) came at fine-tuning epoch 7 of 12, which early
stopping restored. Both give identical metrics.

## Label mapping
- `fruit` output (softmax, 5): 0 apple · 1 banana · 2 guava · 3 tomato · 4 brinjal
- `condition` output (softmax, 2): 0 fresh · 1 spoiled

## Preprocessing and normalisation
- Input: one RGB image, full frame, values 0–255, float32, NHWC `[1, 80, 80, 3]`.
- Resize: aspect-preserving bilinear resize with antialiasing (longer side → 80),
  then centre crop/zero-pad to 80×80
  (`tf.image.resize(..., preserve_aspect_ratio=True, antialias=True)` +
  `tf.image.resize_with_crop_or_pad`).
- Normalisation: **inside the model** (layer `normalize`): `x / 127.5 − 1`.
  The caller must not normalise.
- No cropping, segmentation or masking at inference.

## Architecture
MobileNetV2 (α 0.35, ImageNet init; Keras loads the 224-px weights for 80-px
input), truncated at `block_15_add` → GlobalAveragePooling → Dropout 0.2 →
two dense softmax heads. **199,519 parameters** (120,495 trainable at the end
of fine-tuning). The INT8 size measured earlier for this architecture is
~326 KB with ≥ 94 KB peak activations; it has **not** been re-measured for
these weights, and no INT8 conversion has been done.

## Final training configuration (exact)
| Setting | Value |
|---|---|
| Data | TRAIN 6,146 / VAL 1,299 / TEST 1,012 images; unchanged split (SHA-256 of each split CSV in `training_config.json`) |
| Stage 1 | frozen backbone, Adam lr 1e-3, max 8 epochs (ran 8) |
| Stage 2 | last 40 backbone layers unfrozen (BatchNorm frozen), Adam lr 1e-4, max 15 epochs (stopped after 12) |
| Early stopping | val_loss, patience 5, restore best weights |
| Batch | 32 |
| Loss | sparse categorical cross-entropy per head, weights 1.0 / 1.0 |
| Class balance | sample weight N / (K · n_cell) over fruit × condition cells |
| Augmentation | flips, rotation 0.1, zoom 0.1, brightness 0.15, contrast 0.15 |
| Background compositing | p = 0.7 per training image; background = 70% random texture (35% corner patches of TRAIN images, 1,500-texture bank) / 30% random solid colour; fruit masks from rembg u2netp (training only) |
| Seed | 42 |
| Environment | Python 3.12.7, TensorFlow 2.18.1, Keras 3.15.1, NumPy 2.0.2, Windows 11, CPU |

Reproduce: `python scripts/train_model1.py`. CPU training is not bit-exact
between runs. The same recipe in docs/EXPERIMENTS_02 gave test fresh/spoiled
F1 0.664 vs 0.679 here.

## Metrics of these artifacts
| | VAL (used for early stopping, so optimistic) | TEST (held out) |
|---|---|---|
| Fruit macro-F1 | 0.890 | 0.822 |
| Fresh/spoiled macro-F1 | 0.935 | 0.679 |
| Spoiled recall | 0.987 | 0.662 |
| Cond F1 apple / banana / guava | 0.83 / 1.00 / 1.00 | 0.59 / 0.63 / 0.69 |
| Cond F1 tomato / brinjal | 0.84 / 0.93 | 0.76 / 0.70 |
| Cond F1 AgriFreshNET / FruitNet | 0.92 / 0.94 | 0.81 / 0.64 |
| Fruit F1 AgriFreshNET / FruitNet | 0.98 / 0.86 | 0.97 / 0.75 |

The VAL–TEST gap reflects capture-session dependence (docs/TRAINING_REPORT_01.md).
**TEST is the number to quote.**

## Inference
```
python scripts/model1_predict.py path/to/image.jpg [more images]
python scripts/model1_predict.py --json path/to/image.jpg
```
Output: fruit, fruit confidence, condition, condition confidence, and both
full probability vectors.

**Verification (clean process):** `python -I` from a different working
directory, with no project package on the path, on 10 held-out TEST images
(one per fruit × condition). The predicted classes matched the training-time
predictions for **10 / 10** images, with max probability difference 0.0095.
The difference arises because training-time evaluation used images cached as
uint8 after resizing, while the script keeps float values. 7 / 10 of those
images were classified fully correctly (fruit and condition). See
`reports/model1/inference_verification.txt`.

## Known limitations (carried forward)
- Held-out fresh/spoiled F1 is 0.68, and FruitNet apple/banana/guava are
  0.59–0.69. This is **not** robust spoilage detection.
- Background/source shortcuts are reduced but not removed. The brinjal
  purple/green variety confound is not resolved.
- Trained only on public phone photos; not validated on the device camera.
- Not done (per instructions): INT8 conversion and STM32 integration.
