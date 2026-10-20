# Experiments 01: shortcut mitigations (2026-10-09)

Provisional baseline: 80×80, MobileNetV2-0.35, cut at `block_15_add`
(`reports/final/final_80_b15`, unchanged). Every variant uses the **same
architecture, splits, epochs and seed**; only preprocessing/augmentation
differ. **Each number is a single training run**: differences of a few
points are within run-to-run noise (group-CV fold sd was up to 0.05–0.12).
No INT8 conversion was done.

Raw table: `reports/experiments/comparison.csv` (`python scripts/compare_experiments.py`).
Per-class P/R and confusion matrices: `reports/experiments/<variant>/<suite>/`.

## Variants
| Variant | What changes | Test-time requirement |
|---|---|---|
| baseline | full image | none |
| crop | image cropped to fruit bbox (rembg u2netp mask, 15% pad) for train **and** test | a fruit localiser at inference |
| composite | training only: background replaced (p = 0.7) by random textures from other training images or solid colours, using the mask | none |

Masks: `scripts/make_fruit_masks.py` (pretrained salient-object model, no
training on our labels); 1 of 8,457 failed and falls back to the full image.
Hands are sometimes kept as foreground. Overlays:
`reports/experiments/masks/`.

## 1. Same public TEST split (as the baseline; split unchanged)
| | baseline | crop | composite |
|---|---|---|---|
| Fruit F1 | 0.805 | **0.846** | 0.790 |
| Fresh/spoiled F1 | 0.687 | **0.803** | 0.664 |
| Spoiled recall | 0.556 | **0.776** | 0.543 |
| Cond F1 apple | 0.575 | 0.643 | 0.573 |
| Cond F1 banana | 0.786 | 0.917 | 0.679 |
| Cond F1 guava | 0.611 | **0.869** | 0.642 |
| Cond F1 tomato | 0.780 | 0.811 | 0.667 |
| Cond F1 brinjal | 0.737 | 0.663 | 0.754 |
| Cond F1 AgriFreshNET / FruitNet | 0.828 / 0.635 | 0.803 / **0.802** | 0.786 / 0.620 |
| Fruit F1 AgriFreshNET / FruitNet | 0.951 / 0.704 | 0.927 / **0.816** | 0.985 / 0.704 |
| Cond F1 with fruit region masked (lower = less background use)* | 0.480 | 0.550 | **0.343** |

\* For `crop`, masking the centre of a crop still leaves fruit edges, so its
masked score is not directly comparable.

## 2. Leave-one-source-out (train on one source, test on ALL of the other)
| | baseline | crop | composite |
|---|---|---|---|
| **Train FruitNet → test AgriFreshNET**: cond F1 | 0.703 | 0.763 | **0.809** |
| spoiled recall | 0.573 | 0.573 | **0.765** |
| cond F1 banana / tomato / brinjal | 0.71 / 0.72 / 0.52 | 0.78 / 0.78 / 0.53 | 0.74 / **0.80** / **0.78** |
| banana recognised as banana | 0.705 | 0.534 | **0.857** |
| **Train AgriFreshNET → test FruitNet**: cond F1 | 0.740 | 0.727 | 0.724 |
| spoiled recall | 0.797 | **0.911** | 0.829 |
| cond F1 apple / banana / guava | 0.73 / 0.83 / 0.66 | 0.74 / 0.74 / 0.70 | 0.75 / 0.81 / 0.62 |
| banana recognised as banana | 0.838 | 0.850 | **0.919** |

Tomato and brinjal (AgriFreshNET) and apple and guava (FruitNet) are never
seen as fruit types in these runs, so condition is tested as a cross-fruit,
cross-source concept. Fruit F1 is meaningful only through banana recall.

## 3. AgriFreshNET-only benchmark (AgriFreshNET train/val → AgriFreshNET test, 244 images)
| | baseline | crop | composite |
|---|---|---|---|
| Fruit F1 | 0.976 | 0.977 | 0.957 |
| Fresh/spoiled F1 | **0.815** | 0.799 | 0.786 |
| Spoiled recall | **0.922** | 0.893 | 0.854 |
| Cond F1 banana / tomato / brinjal | 1.00 / 0.75 / 0.70 | 1.00 / 0.73 / 0.66 | 1.00 / 0.66 / 0.74 |
| Cond F1, fruit masked | 0.335 | 0.328 | 0.341 |

Within one source with a uniform background, masking the fruit drops
performance to about chance. Predictions there depend on fruit pixels. The
banana test set is only 64 images from few sessions.

## 4. Brinjal variety confound (heuristic purple tag)
| Accuracy on **fresh purple brinjal** | baseline | crop | composite |
|---|---|---|---|
| Public TEST (n = 12) | 0 / 12 | 0 / 12 | 2 / 12 |
| AgriFreshNET-only TEST (n = 12) | 0 / 12 | 0 / 12 | 0 / 12 |
| LOSO, trained on FruitNet only (n = 12)† | 9 / 12 | 7 / 12 | 5 / 12 |

† A FruitNet-trained model has never seen brinjal, so this does not reflect
learned brinjal knowledge. **The confound is not reduced** by any variant: all
12 fresh purple brinjal are in the same capture groups, and no fresh purple
brinjal exists in any training split. Only new data can fix this.

## 5. Model size / STM32F407VET6 feasibility
All variants use the same network: 199,519 params; INT8 size **326 KB**
(64% of 512 KB flash) and ≥ 94 KB peak activations (lower bound), from
the earlier measurement on the identical architecture. **Not re-measured;
no conversion done.**

| Variant | Extra runtime cost | Feasible on F407 as-is? |
|---|---|---|
| baseline | none | plausible (needs STM32Cube.AI check) |
| composite | none (training-only) | plausible, same as baseline |
| crop | needs a fruit localiser before the classifier. u2netp is ~4.7 MB float. | **No** with u2netp. Would need fixed capture framing (a jig/guide on the device) or a tiny detector (unmeasured) |

## Assessment (measured, single runs)
- **Background shortcut.** Composite gives the clearest reduction on the
  tests designed for it: lowest fruit-masked score (0.34), best FruitNet →
  AgriFreshNET transfer (0.81 F1, spoiled recall 0.77), and best cross-source
  banana recognition. It does **not** improve the in-distribution test (0.66).
  Crop gives the largest in-distribution gain (0.80 F1, guava 0.87, spoiled
  recall 0.78) and helps FruitNet → AgriFreshNET transfer partly (0.76). It
  needs a localiser that does not exist on the device.
- **Brinjal variety confound: not reduced** (0 / 12 fresh purple in both
  in-distribution tests for all variants except composite at 2 / 12).
- **No variant is a robust spoilage detector.** FruitNet apple stays at
  0.57–0.64 F1, and all numbers come from public data, not the device camera.
- Not run (it was asked to test the experiments separately): crop +
  composite combined, and multiple seeds per variant.
