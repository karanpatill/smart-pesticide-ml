# Training report 01: architecture sweep and shortcut analysis (2026-10-09)

**Status: NOT a usable spoilage detector.** The results below show strong
session/source dependence and background/variety shortcuts. Nothing here
supports a claim of robust spoilage detection.

All numbers are measured, not estimated. Reproduce with:
```
python scripts/sweep.py --tag main --head-epochs 5 --ft-epochs 8 --configs <9 configs>
python scripts/sweep.py --tag baseline_bgonly --mask-center --head-epochs 5 --ft-epochs 8 --configs 80:block_15_add
python scripts/shortcut_baselines.py features
python scripts/shortcut_baselines.py brinjal --oof reports/sweep/main/80px_block_15_add/oof_predictions.csv
python scripts/final_eval.py --size 80 --cut block_15_add --run-name final_80_b15
```

## Protocol

- **Sweep:** train+val pool (7,445 images), 3-fold `StratifiedGroupKFold` over
  capture-burst groups, stratified by source × fruit × condition. Early
  stopping uses an inner group-separated split of each training fold; the
  evaluated fold is predicted once. Metrics are pooled out-of-fold
  predictions, plus the std across folds.
- **Final:** the chosen config is trained on TRAIN with early stopping on VAL,
  then evaluated **once** on TEST (1,012 images, capture groups never seen).
- CPU training, MobileNetV2 α 0.35, ImageNet init, class-balanced sample weights.

## 1. Architecture sweep (group-CV, out-of-fold)

| Input | Cut | INT8 KB† | Fruit F1 (±fold sd) | Condition F1 (±fold sd) | Cond F1 AgriFreshNET | Cond F1 FruitNet | Fruit F1 AgriFreshNET | Fruit F1 FruitNet |
|---|---|---|---|---|---|---|---|---|
| 64 | block_13 | 189 | 0.632 ± 0.075 | 0.768 ± 0.081 | 0.845 | 0.750 | 0.839 | 0.645 |
| 64 | block_15 | 326 | 0.670 ± 0.015 | 0.851 ± 0.027 | 0.865 | 0.848 | 0.917 | 0.634 |
| 64 | block_16 | 404 | 0.676 ± 0.022 | 0.826 ± 0.084 | 0.861 | 0.817 | 0.939 | 0.610 |
| 80 | block_13 | 189 | 0.736 ± 0.032 | 0.790 ± 0.124 | 0.872 | 0.771 | 0.896 | 0.719 |
| **80** | **block_15** | **326** | **0.806 ± 0.021** | 0.852 ± 0.051 | 0.895 | 0.842 | 0.954 | 0.747 |
| 80 | block_16 | 404 | 0.755 ± 0.053 | 0.871 ± 0.060 | 0.897 | 0.865 | 0.973 | 0.747 |
| 96‡ | block_13 | 189 | 0.774 ± 0.043 | 0.873 ± 0.023 | 0.873 | 0.873 | 0.923 | 0.725 |
| 96‡ | block_15 | 326 | 0.761 ± 0.082 | 0.895 ± 0.021 | 0.874 | 0.899 | 0.959 | 0.732 |
| 96‡ | block_16 | 404 | 0.766 ± 0.072 | 0.878 ± 0.031 | 0.866 | 0.880 | 0.963 | 0.721 |

† Measured INT8 size (docs/DEPLOYMENT_BUDGET.md). ‡ 96 px exceeds the
128 KB main SRAM (≥ 135 KB activations): reference only.

Condition F1 per fruit (out-of-fold): see `reports/sweep/main/*/summary.json`
→ `condition_f1_by_fruit`.

**Selected for the final run: 80 px, block_15_add.** It has the best fruit F1
with low fold variance and fits the device. 96 px block_15 is about 4 points
better on condition but does not fit. Fold standard deviations are large
(up to 0.12), so differences of a few points between configs are not reliable.
**The architecture is not locked.**

## 2. Held-out TEST (final_80_b15)

| Metric | Group-CV (OOF) | **TEST** |
|---|---|---|
| Fruit macro-F1 | 0.806 | **0.805** |
| Condition macro-F1 | 0.852 | **0.687** |

Condition F1 on TEST by source × fruit:

| Source / fruit | n | Condition F1 (TEST) | Condition F1 (OOF) |
|---|---|---|---|
| AgriFreshNET banana | 64 | 0.963 | 0.862 |
| AgriFreshNET tomato | 123 | 0.780 | 0.899 |
| AgriFreshNET brinjal | 57 | 0.737 | 0.864 |
| FruitNet banana | 167 | 0.718 | 0.841 |
| FruitNet guava | 326 | 0.611 | 0.830 |
| FruitNet apple | 275 | **0.575** | 0.852 |

Fruit F1 by source on TEST: AgriFreshNET 0.951, FruitNet 0.704.

Per-class precision/recall and confusion matrices:
`reports/final/final_80_b15/test/per_class.txt` and `confusion_matrices.png`.
Examples:
- Condition overall: fresh P 0.69 / R 0.82; spoiled P 0.71 / R **0.56**.
- Fruit: banana R 0.62, guava R 0.69 (banana and guava are confused with each other).

**The condition score drops from 0.85 (CV) to 0.69 (test).** The test set
contains whole capture sessions never seen in training, and FruitNet apple and
guava fall to 0.58–0.61. With only 4–8 sessions per FruitNet class, both CV and
test are high-variance. The gap itself is the main finding: the model does not
transfer well to new capture sessions.

## 3. Shortcut / bias evidence

### 3a. Non-semantic colour-feature baseline (same group folds)
Logistic regression on border colour, global brightness/contrast and a
12-bin colour histogram, with no CNN. Condition F1 with one model per fruit:

| Fruit | Features-only | CNN 80/b15 (OOF) |
|---|---|---|
| guava | **0.927** | 0.830 |
| tomato | 0.813 | 0.899 |
| banana | 0.721 | 0.849 |
| apple | 0.638 | 0.852 |
| brinjal | 0.525 | 0.864 |

For guava, simple colour statistics **beat the CNN**. Guava condition is
largely predictable from global colour and background.

### 3b. Background-only CNN (centre 60% greyed out, train and test, group-CV)
Condition F1: **FruitNet apple 0.808**, AgriFreshNET banana 0.634, others
0.40–0.59. Fruit F1 0.467.
→ **FruitNet background shortcut confirmed for apple:** fresh vs spoiled apple
is learnable from the surroundings alone (hand + cream floor vs outdoor
scenes).
Caveat: the mask does not remove every fruit pixel (elongated bananas extend
past it), so this is an upper bound on what the background alone gives.

### 3c. Final model on fruit-masked TEST images
Condition F1 drops to 0.480 (chance level) overall, but **AgriFreshNET banana
stays at 0.98** with the centre masked. That is consistent with the banana
being visible outside the masked square, or with background cues; it cannot
be separated further without segmentation.

### 3d. Banana cross-source transfer (strongest test)
Train with ALL banana images of one source removed, then evaluate on that source:

| Held-out banana source | n | Condition F1 | **Fruit = banana** |
|---|---|---|---|
| AgriFreshNET | 474 | 0.760 | **25.5%** (65.6% predicted *brinjal*) |
| FruitNet | 2,200 | 0.795 | 56.8% (40.9% predicted *guava*) |

→ **Source shortcut confirmed for the fruit head.** Bananas on AgriFreshNET's
white cloth are mostly called "brinjal", the other AgriFreshNET fruit with a
similar look on that background. The fruit head relies heavily on
source/background context. The condition head transfers partially
(0.76–0.80) but well below the in-source scores.

### 3e. Brinjal variety confound (heuristic purple tag, checked by eye)
Purple images in the data: 12 / 236 fresh vs 47 / 153 spoiled.

| Subset | OOF accuracy | TEST accuracy |
|---|---|---|
| green fresh | 0.90 (201) | 0.87 (23) |
| green spoiled | 0.78 (94) | 1.00 (12) |
| purple spoiled | 0.97 (37) | 1.00 (10) |
| **purple fresh** | n/a (all 12 in test) | **0.00 (0 / 12)** |

→ **Variety confound confirmed:** every fresh purple brinjal in the test set
was classified as spoiled. All purple spoiled images were kept, as instructed.

## Conclusions (measured)

1. Fruit classification is reasonable within a source (AgriFreshNET 0.95 F1)
   but depends on source context (3d) and is weaker in FruitNet (0.70).
2. Condition classification **does not generalise robustly** to unseen capture
   sessions (CV 0.85 → test 0.69), with FruitNet apple/guava near 0.6.
3. Evidence of shortcuts: guava (colour/background features beat the CNN),
   apple (background-only 0.81), brinjal (purple → spoiled, 0 / 12 fresh purple
   correct), and banana fruit identity across sources (3d).
4. INT8 conversion was **not** run for this model; it is not yet worth deploying.

## Options (decision needed)

- **Data:** capture our own images under the device camera and setup, with
  varied backgrounds for both conditions and fresh purple brinjal. This is
  the only direct fix for 3a–3e.
- **Training mitigations to test:** fruit-centred cropping or segmentation
  before classification, background randomisation (paste fruit onto random
  backgrounds), stronger colour jitter, and leave-one-source-out validation
  as the primary metric.
- **Scope:** evaluate condition only within AgriFreshNET (more sessions per
  class, a uniform background) as a cleaner but narrower benchmark.
