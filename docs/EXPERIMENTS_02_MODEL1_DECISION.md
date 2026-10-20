# Experiments 02: crop + composite, and the Model 1 decision (2026-10-09)

Same 80×80 MobileNetV2-0.35 / `block_15_add` network, same splits, epochs
and seed as docs/EXPERIMENTS_01.md (that document and all earlier reports are
unchanged). **Single training run per variant**: differences of a few
points are within run-to-run noise. No INT8 conversion, architecture search
or seed repeats.

`crop_composite` = fruit crop (rembg box, train **and** test) + background
compositing in training (masks cropped with the same box; background textures
taken from corners of cropped training images, so they contain more fruit
edge than in `composite`).

Raw table: `reports/experiments/comparison.csv` · Details:
`reports/experiments/crop_composite/`.

## Public TEST split
| | baseline | crop | composite | **crop+composite** |
|---|---|---|---|---|
| Fruit F1 | 0.805 | 0.846 | 0.790 | **0.870** |
| Fresh/spoiled F1 | 0.687 | **0.803** | 0.664 | 0.751 |
| Spoiled recall | 0.556 | **0.776** | 0.543 | 0.607 |
| Cond F1 apple | 0.575 | **0.643** | 0.573 | 0.596 |
| Cond F1 banana | 0.786 | 0.917 | 0.679 | **0.926** |
| Cond F1 guava | 0.611 | **0.869** | 0.642 | 0.768 |
| Cond F1 tomato | 0.780 | **0.811** | 0.667 | 0.643 |
| Cond F1 brinjal | 0.737 | 0.663 | **0.754** | **0.754** |
| Cond F1 AgriFreshNET / FruitNet | **0.828** / 0.635 | 0.803 / **0.802** | 0.786 / 0.620 | 0.777 / 0.741 |
| Fruit F1 AgriFreshNET / FruitNet | 0.951 / 0.704 | 0.927 / 0.816 | **0.985** / 0.704 | 0.962 / **0.867** |
| Cond F1, fruit region masked (lower = less background use) | 0.480 | 0.550* | **0.343** | 0.376* |
| Fresh purple brinjal correct | 0/12 | 0/12 | **2/12** | 1/12 |

\* Masking the centre of a crop still leaves fruit edges, so these are not comparable.

## Leave-one-source-out
| | baseline | crop | composite | crop+composite |
|---|---|---|---|---|
| Train FruitNet → AgriFreshNET: cond F1 | 0.703 | 0.763 | **0.809** | 0.755 |
| spoiled recall | 0.573 | 0.573 | **0.765** | 0.588 |
| cond F1 banana / tomato / brinjal | 0.71 / 0.72 / 0.52 | **0.78** / 0.78 / 0.53 | 0.74 / 0.80 / **0.78** | 0.68 / 0.80 / 0.61 |
| banana recognised | 0.705 | 0.534 | **0.857** | 0.627 |
| Train AgriFreshNET → FruitNet: cond F1 | 0.740 | 0.727 | 0.724 | **0.756** |
| spoiled recall | 0.797 | **0.911** | 0.829 | 0.811 |
| cond F1 apple / banana / guava | 0.73 / 0.83 / 0.66 | 0.74 / 0.74 / **0.70** | **0.75** / 0.81 / 0.62 | 0.74 / **0.87** / 0.66 |
| banana recognised | 0.838 | 0.850 | 0.919 | **0.947** |

## AgriFreshNET-only benchmark
| | baseline | crop | composite | crop+composite |
|---|---|---|---|---|
| Fruit F1 | 0.976 | **0.977** | 0.957 | 0.971 |
| Fresh/spoiled F1 | **0.815** | 0.799 | 0.786 | 0.758 |
| Spoiled recall | **0.922** | 0.893 | 0.854 | 0.893 |
| Cond F1 banana / tomato / brinjal | 1.00 / **0.75** / 0.70 | 1.00 / 0.73 / 0.66 | 1.00 / 0.66 / **0.74** | 1.00 / 0.67 / 0.62 |
| Fresh purple brinjal correct | 0/12 | 0/12 | 0/12 | 0/12 |

## STM32F407VET6 deployment implications
All four variants use the **same network**: 199,519 params; ~326 KB INT8
and ≥ 94 KB peak activations (measured earlier on this architecture with
untrained weights; not re-measured, no conversion done).

| Variant | Runtime pipeline on the MCU | Deployable now? |
|---|---|---|
| baseline | camera → resize 80×80 → CNN | Yes (subject to STM32Cube.AI check) |
| composite | identical to baseline; compositing is training-only | **Yes**, same cost as baseline |
| crop | camera → **fruit localiser** → crop → CNN | **No.** The localiser used (u2netp) is ~4.7 MB float32 and needs a 320×320 input; far beyond 512 KB flash / 192 KB SRAM. No small on-device localiser has been built or validated. |
| crop+composite | same as crop | **No**, same reason |

A crop-trained model run on un-cropped frames would see a different input
distribution from training. That was not evaluated and should not be assumed
to work.

## Model 1 selection

**Selected: full-frame 80×80 MobileNetV2-0.35, cut at `block_15_add`,
trained with background compositing (`composite`).**

Reasons, given the priority of STM32 deployability plus generalisation:
1. **Deployable with no extra runtime component.** Same network, size and
   pipeline as the baseline; masks are used only offline during training.
2. **Best measured generalisation to an unseen source:** FruitNet →
   AgriFreshNET condition F1 0.809 (baseline 0.703), spoiled recall 0.765
   (0.573), brinjal 0.78 (0.52), and the best cross-source banana recognition
   (0.857 / 0.919).
3. **Least reliance on background:** lowest fruit-masked score (0.343).

Costs, stated plainly:
- On the in-distribution public test it is the **weakest** variant
  (cond F1 0.664, spoiled recall 0.543, FruitNet apple 0.573).
- Crop and crop+composite score higher there (0.803 / 0.751) but cannot run
  on the target as-is.
- The brinjal variety confound remains (fresh purple brinjal 2/12).
- Every comparison above rests on one training run per variant.

**This does not establish a robust spoilage detector.** Model 1 is the most
practical starting point for the device phase, not a validated product model.

### Recipe (for the next phase)
- Training: `scripts/experiments.py --variant composite` settings: 80 px,
  α 0.35, `block_15_add`, head 8 + fine-tune 15 epochs, early stopping on VAL,
  compositing p = 0.7 (70% textures from other training images, 30% solid
  colours), class-balanced sample weights, seed 42.
- Inference: full frame, aspect-preserving resize + centre crop to 80×80,
  normalisation inside the model.
- `experiments.py` does not save weights, so the Model 1 `.keras` artifact
  must be produced with one training run of this recipe before conversion.
  (That is not done here, per instructions.)

### Upgrade path (no new decision needed now)
If the device's capture framing makes the fruit fill a consistent central
region (for example a fixed jig), the crop variants' advantage may become
reachable without a localiser. That can only be checked with device images.

## Update 2026-10-09: Model 1 approved, locked and produced
Model 1 was approved as selected above (no changes to architecture or split).
The artifacts were produced by `scripts/train_model1.py` and are in
`models/model1/`. Full artifact list, exact training configuration, metrics
and inference verification: **docs/MODEL1.md**. The "Recipe" section above is
superseded by docs/MODEL1.md (`model1_final.keras` now exists).
