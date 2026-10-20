# Experiment summary, 2026-10-17 (evening): PC only, frozen models untouched

**What was used:**
* Every frozen-model result uses the deployed INT8 `combined_int8.tflite` (sha256 1af166f0…) with **BUILTIN_REF** kernels, which are the STM32-parity kernels.
* XNNPACK was rejected for these runs: only 18/150 outputs were identical to REF, and 142/150 had the same argmax.
* Public-image results are a **proxy**: each image is converted through the exact firmware path (crop 4:3 → 160×120 → RGB565 BE → centre 120×120 → bilinear 80×80).
* Real device frames: 23 SWD captures (6 sharp fruit, 17 defocused/empty).

**Evidence:**

| Run folder | Content |
|---|---|
| `reports/experiments/device_domain_20261017T152226Z/` | metrics.json, log.txt, stdout.txt, per-image CSVs |
| `reports/experiments/background_head_20261017T152313Z/` | Background-head candidate |
| `reports/experiments/fruit_head_guava_20261017T152628Z/` | Fruit-head candidate |

Scripts: `scripts/exp_device_domain_eval.py`, `scripts/exp_background_head.py`, `scripts/exp_fruit_head_guava.py` (all new).

## A. No-fruit rejection (held out)

v5 gate = detail ≥ 43.96 AND confidence ≥ 0.976.

| Negative set | n | False "fruit" shown, conf only | **False shown, v5 gate** | Predicted as |
|---|---|---|---|---|
| Real device, defocused/empty | 17 | 0 % | 0 % | guava 17/17 |
| Synthetic smooth fields | 60 | 66.7 % | 0 % | guava |
| **TEST background patches** (rembg fruit < 2 %) | 743 | 67.6 % | **26.9 %** | guava 707, banana 29, apple 5, brinjal 2 |

* The v5 gate stops defocus and flat scenes. It does **not** stop sharp textured backgrounds.

**CANDIDATE** fruit-vs-background logistic head on frozen M1 `gap` features (float):
* Location: `models/candidates/background_head_20261017T152313Z/`.
* Trained on TRAIN fruit images plus TRAIN patches. The threshold was chosen on VAL (≤ 2 % VAL false accept).

Held-out TEST results:

| Metric | Value |
|---|---|
| Fruit images accepted | 1,012/1,012 (100 %) |
| Clean background patches accepted, head alone | 2.4 % of 3,023 |
| Clean background patches accepted, head + detail gate | **2.25 %** |
| Synthetic fields accepted | 0 % |
| Real device frames, head + detail gate | 6/6 sharp fruit accepted (incl. the focused apple that v5 rejects, p = 0.50); 17/17 defocused/empty rejected |

Head alone accepted 5 defocused frames (p 0.017–0.026); the detail gate removes them.

**Limits:**
* The negatives are dataset backgrounds plus 17 device frames. **Real non-fruit objects are still unmeasured.**
* The candidate is evaluated with float features. It is not yet INT8 and not deployed.

## C. Camera-domain robustness

M1 TEST, held out, n = 1,012. Fruit macro-F1 / condition macro-F1:

| Path | Fruit F1 | Cond F1 | Shown (v5 gate) | Accuracy when shown |
|---|---|---|---|---|
| Training preprocessing (reference) | 0.813 | 0.681 | 46.1 % | 0.916 |
| Device path | 0.814 | 0.752 | 48.9 % | 0.964 |
| + measured vignetting (corner 0.44) | 0.814 | 0.772 | 47.3 % | 0.973 |
| + measured blue cast (B ×1.075) | 0.812 | 0.752 | 48.9 % | 0.970 |
| + vignetting + cast | 0.827 | 0.770 | 48.6 % | 0.974 |
| + mild blur (σ 1) | 0.808 | 0.746 | 44.7 % | 0.967 |
| + strong blur (σ 3) | **0.713** | 0.615 | **0.4 %** | 1.0 |
| vignetting + cast + blur σ 1 | 0.800 | 0.757 | 42.2 % | 0.979 |

* The measured colour cast and vignetting do **not** reduce accuracy. Defocus does.
* Colour/vignetting augmentation is therefore low value. Focus and framing are what matter (consistent with the board evidence).
* Not covered: OV2640 sensor noise, AWB/exposure changes and lens distortion. These need the real device test set (D1).

## D. Calibration and thresholds

Fit on VAL (device path), evaluated on TEST:

* **Temperature scaling:** T = 1.40 reduces ECE from 0.070 to 0.053. Argmax is unchanged, so it only re-maps thresholds.
* **Per-class thresholds** (lowest per-class threshold with ≥ 97 % VAL accuracy): TEST shown rate 48.9 % → 56.1 %, but **accuracy when shown 0.964 → 0.903**. The VAL-selected thresholds do not transfer, so they were **rejected as unsafe**. The global 0.976 stays.

## B. banana_guava_quality grade set (Mendeley 56td5w4wz2 v2, CC BY 4.0)

* Fruit identity comes from the dataset folder (Banana/Guava). Grade is Class_A/B/Defect.
* **0 images** within 16 pHash bits of any M1 train/val/test image, so there is no leakage if it is used for fruit ID.

Frozen model routing (device path):
* Banana: 99.6 % correct.
* **Guava: 56.3 %** (apple 143, banana 63, brinjal 27).
* Guava by grade: Good 26.7 %, Average 77.1 %, Poor 61.5 %.
* Only 16.9 % of guava pass the v5 gate.

**CANDIDATE** fruit head retrained on frozen features with the grade-set TRAIN images added:
* Location: `models/candidates/fruit_head_guava_20261017T152628Z/`.
* Grade-set TEST guava recall: 0.463 → **0.915**.
* M1 TEST macro-F1: 0.794 → **0.784**. Apple recall 0.727 → 0.625; banana 0.900 → 0.818.
* **Not acceptable as is:** a head-only retrain trades apple/banana for guava. Fixing guava needs fine-tuning of the backbone (a new Model 1 candidate), with an acceptance check on every fruit.

## E. M3 stage heads

Recorded TEST predictions, held out. Shelf band = a fixed lookup of the stage, so shelf-band accuracy = stage accuracy.

| Head | n | Exact | Off by 1 | Off by 2 | Rotten → Fresh | Fresh → Rotten |
|---|---|---|---|---|---|---|
| tomato | 167 | 0.569 | 0.293 | 0.138 | 1 | 22 |
| brinjal | 96 | 0.552 | 0.323 | 0.125 | 0 | 12 |
| banana | 91 | 0.956 | 0.044 | 0 | 0 | 0 |

* Tomato/brinjal errors are mostly conservative: Fresh is called Rotten, so shelf life is under-stated. Dangerous over-statements are rare.
* Accuracy is still only ~0.55. There is no existing-data fix without new grouped data or backbone fine-tuning.
* Apple/guava shelf life: no labels exist (unchanged).

## Pesticide risk

No experiment is possible with the existing data. The requirements are unchanged (`docs/SENSOR_CALIBRATION_PROTOCOL.md`):
* AChE strip reader;
* pH 3-point buffers;
* MQ135 Rs/R0 after burn-in;
* lab LC-MS/MS or GC-MS reference labels.

Out-of-range device inputs remain UNCERTAIN.

## Integrity

* Hashes of 77 protected files (all models, all firmware builds, original backup) are identical before and after.
* Model files match the snapshot manifest `backups/final_handover_20261017T150157Z`.
* v5 ELF 2a72f1b9…, BIN a48db157…; the board was not touched.
* The 172-test suite was **not** re-run: no production source or test changed in this session. Only new scripts and new candidate/report files were added.
