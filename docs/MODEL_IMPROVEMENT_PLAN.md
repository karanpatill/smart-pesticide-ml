# Model audit and evidence-based improvement plan (2026-10-17)

**Status: PLAN ONLY, awaiting approval.**
* No model, dataset, firmware or board was changed for this document.
* v5 remains the board firmware, and all backups are intact.
* The parked display-only patch (`reports/firmware/parked_v9_demo_display_patch/`) is NOT part of this plan.

**Sources for every number:**
* `docs/MODEL1.md`, `docs/MODEL3.md`, `docs/MODEL2_PROTOTYPE_RESULTS.md`, `docs/MODEL2_DATA_RESEARCH.md`
* `configs/model3_postprocess.json`
* `docs/PRESENCE_GATE_DECISION.md`, `reports/firmware/device_capture/`

**Update 2026-10-17 (evening):** measured results for A–E are in `reports/experiments/SUMMARY_20261017_evening.md`.
* **E1 (colour/vignetting augmentation):** low value. The measured cast and vignetting do not reduce TEST accuracy; defocus does.
* **E4:** per-class thresholds were rejected (TEST accuracy 0.964 → 0.903). Temperature T = 1.40 is noted.
* **E2:** a head-only retrain is insufficient. Guava recall rose 0.46 → 0.92, but apple and banana dropped.
* **E3 (no-fruit):** the v5 gate accepts 26.9 % of held-out background patches. A candidate background head reduces this to 2.25 % with 100 % TEST fruit acceptance. **This is the next step.**

## 1. Current performance

### 1.1 Public-photo held-out TEST (not device performance)

| Output | Model | TEST metric (held out) | Weakest part |
|---|---|---|---|
| Fruit type | M1 (MobileNetV2-0.35, 80×80) | macro-F1 **0.822**; FruitNet source 0.75, AgriFreshNET 0.97 | FruitNet fruits; yellow/ripe guava routed correctly only **45 %** |
| Fresh/spoiled | M1 condition head | macro-F1 **0.679**, spoiled recall 0.662 | apple 0.59 · banana 0.63 · guava 0.69 · tomato 0.76 · brinjal 0.70 |
| Quality grade | M3 heads on frozen M1 features | banana **0.822** · guava **0.870** (end-to-end 0.37 due to routing) · apple **0.456** (112/134 Good predicted Poor) · tomato 0.554 · brinjal 0.545 | apple does not generalise; tomato/brinjal "Semi-fresh" |
| Shelf-life band | M3 stage head + fixed day table | banana 0.955 (91 images, unstable) · tomato 0.554 · brinjal 0.545 · **apple, guava: no labelled data** | stage table = AgriFreshNET storage conditions only |
| Pesticide risk | M2 logistic regression | 0.772 macro-F1 **on synthetic data only**; no real-world metric exists | no real labels at all |

### 1.2 Real device camera (OV2640 → STM32, bit-exact with the PC)

| Evidence | What it shows |
|---|---|
| Banana | 4/4 captures correct, 0.988–0.996. This is **one banana, one position, one light**. It is an anecdote, not an accuracy figure. |
| Apple | 1 focused frame: confidence 0.852 (below 0.976, so rejected). 2 defocused frames rejected. |
| Empty / background scene | Predicted guava 0.80–0.99. M1 has no "no fruit" class. |
| Guava, tomato, brinjal | **0 device frames**. |
| Condition / grade / shelf on the device | **0 labelled device frames**. No device accuracy exists. |

### 1.3 Real sensors (board, 2026-10-17)

* **Board readings:**
  * TCS G/B/C 1874/1959/5108 vs a training max of 1027/1123/2877 (z-score 11–13).
  * pH 9.35 vs a training range of 2.9–6.2.
  * MQ135 raw ADC 324, on a different scale from the training "MQ" scale.
* The inputs are far out of distribution, and the sensors are not used the way Model 2 assumes:
  * TCS should read an **AChE test strip**, not ambient light or the fruit surface.
  * pH should be measured on a sample extract.
  * MQ135 should be expressed as Rs/R0 after burn-in.

### 1.4 Known failure modes

| Failure mode | Effect |
|---|---|
| Domain gap: public phone photos vs OV2640 | Colour cast, vignetting (corners at 44 %), RGB565, 160×120 → centre 120×120 → 80×80 without anti-aliasing |
| Defocus / framing | The presence gate rejects the image |
| No background class | Empty scenes look like guava |
| Source shortcuts | Apple/guava only in FruitNet; tomato/brinjal only in AgriFreshNET |
| Few capture sessions | The apple set has ~4 per class, so VAL ≫ TEST |
| Routing propagation | A misrouted fruit gets the wrong grade and shelf head |
| Label harmonisation | FruitNet "Bad" ≠ "Rotten" |
| Synthetic labels | Model 2 risk |

## 2. Data on disk

| Dataset | Images | Used by | Unused potential |
|---|---|---|---|
| FruitNet | 19,526 files | M1 (apple/banana/guava), M3 apple | "Mixed" class; more sessions limited |
| AgriFreshNET | 14,160 files | M1 (banana/tomato/brinjal), M3 stages | Semi-fresh rows already in M3 |
| banana_guava_quality (56td5w4wz2) | 1,748 files | M3 grade heads only | **Yellow/ripe guava + banana for the M1 fruit head** (fixes guava routing; never used for M1) |
| Zenodo e-nose 17285312 | MQ sensors | M2 synthetic realism | No pesticide labels |
| Device captures | 20 folders (80×80 model inputs) | Evaluation evidence | Seed of a device test set |
| Background texture bank (1,500, from M1 training) | — | M1 compositing | Negatives for a "no fruit" class |

## 3. What can be improved with EXISTING data (PC only; new artifacts under new names; frozen models untouched)

| # | Work | Expected benefit | How it is validated |
|---|---|---|---|
| E1 | **Device-domain augmentation** for M1+M3 training: simulate the exact device path. Measured parameters: big-endian RGB565 quantisation, 160×120 capture, centre crop, bilinear 80×80 without anti-aliasing, vignetting (corner/centre 0.44), blue cast (B/G +5–10 %), mild defocus. | Narrows the domain gap without new photos. | Public TEST (must not drop by more than 0.02), plus the device test set (D1). |
| E2 | Add banana_guava_quality images to the **M1 fruit head** (grouped pHash split, no leakage with the M3 TEST). | Guava routing 45 % → measured. | Public TEST per source; end-to-end guava grade accuracy. |
| E3 | **"No fruit" 6th class** trained from the texture bank, background crops and the existing device empty frames. | Replaces the confidence-only fallback that maps empty scenes to guava. | False-fruit rate on held-out empty/background frames ≤ 2 % (from D1). |
| E4 | **Confidence calibration** (temperature scaling on VAL), then per-fruit thresholds instead of a single 0.976. | Fewer false rejections of real fruit at the same accuracy. | Reliability diagram and ECE on TEST; coverage vs accuracy per fruit. |
| E5 | **M3 fine-tuning** (partial backbone unfreeze for tomato/brinjal stage heads) instead of frozen features only. | Stage F1 0.55 → measured. | Grouped TEST. Report honestly if there is no gain. |
| E6 | Apple quality: re-split by capture session and report the true grouped estimate. | Honest number (likely ≈ 0.5). | — (needs new data to improve: D2) |

* **Deployment constraint for E1–E6:** same architecture, plus at most 1 class.
  * INT8 model ≈ 366,848 B + a few hundred bytes. v5 flash free is 83 KB.
  * Arena ≤ 148,896 B. RAM free is 22.9 KB.
  * Re-run the existing INT8 conversion, the 32-hash freeze check (new names) and the bit-exact C vs TFLite parity tests.
* **Estimated effort:** E1–E5 ≈ 1–2 days of CPU training plus evaluation.

## 4. What REQUIRES new data collection or experiments

| # | Data | Minimum | Tool (already working) | Purpose |
|---|---|---|---|---|
| D1 | **Device test set:** OV2640 frames of each fruit × condition under demo light, labelled by written inspection protocol | ≥ 30 per fruit × condition (≈ 300) + ≥ 50 empty/background | v8_diag + `read_capture.py` (saves the exact 80×80 input; about 3 s per capture) | First real accuracy figures; acceptance gate for every model change |
| D2 | **Device training set** (fine-tuning) | 200–300 per fruit, ≥ 500 no-fruit, several sessions, days and lights | same | Remove the domain gap; fix apple |
| D3 | **Longitudinal shelf-life study:** the same fruits photographed daily until spoiled, with recorded T/RH | ≥ 10 fruits per type, all 5 fruits, ≥ 2 batches | same + DHT11 | Real "days remaining" labels, including **apple and guava** (no data today) |
| D4 | **Sensor calibration** (`docs/SENSOR_CALIBRATION_PROTOCOL.md`) | pH 3-point buffers (4.01/6.86/9.18) daily; MQ135 24 h burn-in and R0; TCS white/dark reference with a fixed LED enclosure | firmware raw values already logged in `g_fv_diag` | Device units → physical units |
| D5 | **Pesticide reference data:** produce lots (untreated + ≥ 3 treatments) × 5 fruits, ≥ 2 sessions, ≥ 3 replicates; **AChE strip** read by the TCS in a fixed enclosure; **accredited LC-MS/MS or GC-MS** on the same lots | ≈ 90+ labelled readings minimum; more for confidence intervals | needs a strip-reader fixture + lab budget | The ONLY route to a real risk classifier. Without D5, risk stays UNCERTAIN. |

## 5. Plan per model and acceptance criteria (all evaluated on held-out REAL device data)

| Model | Work | Acceptance (proposed, on the D1 device test set; 95 % CI reported) |
|---|---|---|
| M1 fruit | E1 + E2 + E3 + E4, then fine-tune on D2 | macro-F1 ≥ 0.85 over 5 fruits; false fruit on empty ≤ 2 %; each fruit recall ≥ 0.75 |
| M1 condition | E1, then D2 | fresh/spoiled macro-F1 ≥ 0.75 on the device; otherwise shown as low confidence |
| M3 grade | E5, then D2 (graded by protocol) | per fruit macro-F1 reported; shown only for fruits that meet ≥ 0.70 |
| Shelf life | D3 → regression or ordinal "days remaining" per fruit with T/RH input | MAE in days reported per fruit; apple/guava only after D3 |
| M2 risk | D4 + D5 → retrain on real labelled data (logistic regression / small tree, ≤ 2 KB) | grouped-by-lot CV; per-class precision/recall vs lab reference; **no claim before this** |
| Deployment | INT8 re-conversion, parity tests, new firmware name (v9), flash only after approval | flash ≤ 512 KB, RAM within the current budget, inference ≤ 0.5 s, bit-exact parity |

## 6. Recommended order
1. **D1 first (1–2 h of capture, no firmware change):** it gives the first real device numbers for the CURRENT models. Without it, no improvement can be measured.
2. **E1–E5 on the PC** (existing data), evaluated on public TEST + D1.
3. **D2:** device fine-tuning set, then retrain.
4. **INT8 deployment** of the winner as a new firmware build (approval required).
5. **D3 shelf-life study** (multi-day) and **D4 calibration**, in parallel.
6. **D5 pesticide reference study:** depends on reagent strips and lab access. Until it is done, the risk output stays UNCERTAIN/UNAVAILABLE.
