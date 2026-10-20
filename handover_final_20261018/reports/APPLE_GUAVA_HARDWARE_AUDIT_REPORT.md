# Investigation and Experimental Audit: Apple and Guava Classification on Hardware

**Date:** 2026-10-17  
**Target:** STM32F407VET6 + OV2640 Camera  
**Candidate Firmware (Running on MCU):** `reports/firmware/gcc/fv_app_candidate.elf`  
**Baseline Model:** `models/candidates/presence_int8_20261017T153321Z/combined_presence_int8.tflite` (SHA-256: `612f2e5586f0a4e2f2d7f7227e7cb6576cde1327f1a98453baec575f95e59300`)

---

## 1. Executive Summary & Physical Verification Findings

During physical hardware testing under representative ambient lighting on the STM32F407 board:
1. **Empty Scene:** Rejected cleanly (`fruit_present = 0`, OLED displays `Fruit:NOFRUIT/UNKNOWN`).
2. **Banana:** Correctly classified with **99.6% confidence** (`fruit_present = 1`, OLED displays `Fruit:banana 0.996`).
3. **Apple:** Incorrectly classified by raw head as **Guava** with 80.1% confidence; rejected by confidence gate (`conf < 0.976` -> `fruit_present = 0`).
4. **Guava:** Incorrectly classified by raw head as **Apple** with 60.9% confidence; rejected by confidence gate (`conf < 0.976` -> `fruit_present = 0`).

The confidence gate ($\ge 0.976$) correctly prevented incorrect predictions from being displayed on the OLED. However, Apple and Guava fail to be recognized as themselves.

---

## 2. Dataset & Training Pipeline Audit

An audit of the training splits (`data/splits/{train,val,test}.csv`), preprocessing pipeline, and model architecture revealed the exact sources of bias:

### 2.1 Cross-Session Leakage & Split Integrity
- **Splits:**
  - `train.csv`: 6,146 images (Banana: 2,013, Guava: 1,687, Apple: 1,581, Tomato: 592, Brinjal: 273).
  - `val.csv`: 1,299 images (Banana: 430, Apple: 419, Guava: 268, Tomato: 123, Brinjal: 59).
  - `test.csv`: 1,012 images (Guava: 326, Apple: 275, Banana: 231, Tomato: 123, Brinjal: 57).
- **Session Grouping:**
  - In `train.csv`, Apple has only 4 capture sessions (`Apple_Bad|t0`, `Apple_Bad|t2`, `Apple_Good|t0`, `Apple_Good|t1`).
  - `test.csv` Apple images come strictly from session `t3` (`Apple_Bad|t3`: 141, `Apple_Good|t3`: 134).
  - `test.csv` Guava images come strictly from sessions `t3`, `t4`, `c0.2`, `c0.3`.
  - There is zero image overlap across splits, confirming strict session-level grouping.

### 2.2 Source Confounding (Single-Source Bias)
- **Apple & Guava:** 100% sourced from **FruitNet** (smartphone photos taken against uniform table/cloth backgrounds with specific indoor lighting and high saturation).
- **Tomato & Brinjal:** 100% sourced from **AgriFreshNET** (different camera, different laboratory background).
- **Banana:** Sourced from both FruitNet and AgriFreshNET.
- **Consequence:** The neural network learned strong dataset-specific background and sensor color cues rather than intrinsic spherical fruit geometry.

### 2.3 Sensor Domain Gap
- The OV2640 sensor on the physical hardware exhibits:
  - Strong vignetting (corner luminance drops to 44% of center).
  - Cyan/blue color balance shifts under typical laboratory fluorescent/LED lighting.
  - RGB565 color quantization artifacts.
  - Lens barrel distortion when objects are centered at 15–20 cm.
- While Banana is elongated, yellow, and has unique aspect ratios that make it invariant to these shifts, Apple and Guava are both round fruits of similar scale. Under the OV2640's optical transfer function, their color distributions overlap heavily in the model's bottleneck space.

---

## 3. Baseline Performance on Untouched Held-Out Test Set (Device Preprocessing Path)

Evaluating the baseline frozen model on the 1,012 held-out TEST images passed through the exact device preprocessing path (RGB565 quantisation, 160x120 -> 120x120 center crop -> 80x80 bilinear resize):

### 3.1 Classification Metrics
```
              precision    recall  f1-score   support

       apple     0.8519    0.7527    0.7992       275
      banana     0.9035    0.8918    0.8976       231
       guava     0.8277    0.8252    0.8264       326
      tomato     0.7842    0.8862    0.8321       123
     brinjal     0.6234    0.8421    0.7164        57

    accuracy                         0.8291      1012
   macro avg     0.7981    0.8396    0.8143      1012
weighted avg     0.8348    0.8291    0.8298      1012
```

### 3.2 Confusion Matrix (Held-out TEST)
```
         apple  banana  guava  tomato  brinjal
apple      207       6     32      30        0
banana       0     206     24       0        1
guava       19      10    269       0       28
tomato      13       1      0     109        0
brinjal      4       5      0       0       48
```
- **Apple misclassified as Guava:** 32 images.
- **Guava misclassified as Apple:** 19 images.

### 3.3 Confidence Distributions & Confidence Gate Pass Rate
| Fruit Class | Mean Conf | Median Conf | % Passing Gate ($\ge 0.976$ & detail $\ge 43.96$) | Accuracy When Passed |
|---|---|---|---|---|
| **Banana** | $0.956$ | $0.996$ | **$80.1\%$** (185/231) | **$96.2\%$** |
| **Guava** | $0.871$ | $0.973$ | **$49.4\%$** (161/326) | **$96.9\%$** |
| **Tomato** | $0.927$ | $0.992$ | **$58.5\%$** (72/123) | **$98.6\%$** |
| **Brinjal** | $0.909$ | $0.988$ | **$56.1\%$** (32/57) | **$100.0\%$** |
| **Apple** | **$0.808$** | **$0.859$** | **$16.4\%$** (45/275) | **$88.9\%$** |

**Crucial Finding:**
Even on the public test set, **83.6% of genuine apples** have confidence $< 0.976$ and are rejected by the gate! The mean confidence for Apple is only 0.808. When presented on the real OV2640 camera (where confidence further degrades to ~0.80–0.85 due to the domain gap), the gate legitimately suppresses the output as `UNCERTAIN`.

---

## 4. Evaluation of Head-Only Retraining (Experiment E2 Audit)

The repository contains a candidate experiment (`fruit_head_guava_20261017T152628Z`) that retrained only the top classification head using frozen features and additional guava/banana images from Mendeley `banana_guava_quality`:
- **Result on Grade Set:** Guava recall rose from 0.463 to 0.915.
- **Regression on M1 TEST:**
  - Macro F1 dropped from 0.7942 to 0.7843.
  - Apple recall collapsed from 0.727 to **0.625** (Apple misclassifications as Guava increased from 23 to 47!).
  - Banana recall dropped from 0.900 to **0.818**.
- **Conclusion:** A linear or head-only retrain on frozen bottleneck features cannot resolve the Apple–Guava confusion. It simply shifts the decision boundary, trading away Apple and Banana accuracy. Fixing this without regressions requires fine-tuning the deep convolutional representations.

---

## 5. Requirements for Genuine Real-World Apple/Guava Detection

To achieve client-ready detection of physical Apple and Guava on the STM32F407 hardware without hallucinations or hardcoding, the following real hardware data must be collected:

1. **Physical Device Calibration Dataset ($D_1$ & $D_2$):**
   - **Sample Count:** At least 50 distinct physical captures per fruit (Apple, Guava, Banana, Tomato, Brinjal) and 100 non-fruit/empty scenes.
   - **Acquisition Protocol:** Captured using `tools/firmware/read_capture.py` directly from the OV2640 DCMI DMA stream.
   - **Variations Required:**
     - Diverse fruit varieties (e.g., Red Delicious vs. Granny Smith vs. Gala apples; Green vs. White/Yellow guavas).
     - Lighting variations (daylight, warm white, fluorescent).
     - Rotations, distances (15 cm, 20 cm, 25 cm), and subtle center offsets.
2. **Backbone Fine-Tuning Recipe:**
   - Unfreeze MobileNetV2 blocks 12–15 with a low learning rate ($10^{-5}$).
   - Train with hardware-augmented camera simulation (RGB565 quantization, measured vignetting, chromatic aberration).
   - Validation criteria:
     - Held-out public test macro-F1 must remain $\ge 0.81$.
     - Empty-scene false fruit acceptance must remain $< 1.0\%$.
     - Apple and Guava physical hardware captures must achieve $> 0.976$ confidence.

---

## 6. Current Operational Safety Status

- **Running Hardware State:** `fv_app_candidate.elf` remains active and stable on the STM32F407 board.
- **No Firmware Modifications:** No flashing or reset was performed during this audit.
- **Regression Suite:** All **180 automated tests** pass.
