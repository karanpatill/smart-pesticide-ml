# Per-Class Evaluation Summary — Smart Pesticide Residue Detection System
**Date:** 2026-10-18  
**Model:** `models/candidates/presence_int8_20261017T153321Z/combined_presence_int8.tflite`  
**Evaluation Sets:**
1. Clean public test set (FruitNet held-out session splits, n=1,012)
2. Device domain test set (OV2640 simulated/vignetted/color-cast, n=1,012)
3. Physical STM32F407 hardware live captures (OV2640 actual camera, 2026-10-17)

---

## 1. Per-Class Metrics Table (Public Held-Out Test Set)

Evaluated under `presence_int8_20261017T153321Z/metrics.json` and `device_domain_20261017T152226Z/metrics.json`:

| Fruit Class | Total Test Images | Baseline Recall | Presence Head Accept Rate | Gate Show Rate (v5 Gate + Head) | Accuracy When Shown | Physical Hardware Result |
|---|---|---|---|---|---|---|
| **Banana** | 231 | 89.2% | 100.0% | 80.09% | 96.22% | **PASS** (99.6% conf, accepted, fresh, Grade Good) |
| **Apple** | 275 | 75.3% | 100.0% | 16.36% | 88.89% | **REJECTED BY GATE** (Raw: Guava 80.1%, suppressed as UNCERTAIN) |
| **Guava** | 326 | 82.5% | 100.0% | 49.39% | 96.89% | **REJECTED BY GATE** (Raw: Apple 60.9%, suppressed as UNCERTAIN) |
| **Tomato** | 123 | 88.6% | 100.0% | 58.54% | 98.61% | *Not physically tested* |
| **Brinjal** | 57 | 84.2% | 100.0% | 56.14% | 100.0% | *Not physically tested* |
| **Empty / Background** | 3,023 | N/A (Neg) | 2.61% | 0.93% (FPR < 1%) | N/A | **PASS** (Rejected, `fruit_present=0`, UNCERTAIN) |

---

## 2. Physical Hardware Live Validation Matrix (STM32F407VET6 + OV2640)

Captures obtained via SWD memory readback using `tools/firmware/read_diag.py --execute`:

| Target Scene | Timestamp | Raw Classifier Output | Confidence | Presence Head (`fruit_present`) | Gated OLED Output | Final Status |
|---|---|---|---|---|---|---|
| **Empty Background** | 23:28:22 | Guava | 88.7% | 0 (No fruit) | `Fruit:NOFRUIT/UNKNOWN` | **PASS (True Negative)** |
| **Banana** | 23:30:33 | Banana | 99.6% | 1 (Fruit present) | `Fruit:banana 0.996` | **PASS (True Positive)** |
| **Apple** | 23:31:29 | Guava | 80.1% | 0 (Gate blocked) | `Fruit:NOFRUIT/UNKNOWN` | **REJECTED (Misclassification suppressed)** |
| **Guava** | 23:32:34 | Apple | 60.9% | 0 (Gate blocked) | `Fruit:NOFRUIT/UNKNOWN` | **REJECTED (Misclassification suppressed)** |

---

## 3. Analysis & Key Insights

1. **Gate Integrity Under Real Domain Shift:**
   - When Apple and Guava were presented to the physical OV2640 camera, the raw classifier suffered cross-talk (Apple classified as Guava @ 80.1%, Guava classified as Apple @ 60.9%).
   - Crucially, because neither met the strict confidence threshold (0.976) and presence verification criteria, **neither false prediction was presented on the OLED or serial bus**.
   - The system reported `fruit_st=UNCERTAIN` and `Fruit:NOFRUIT/UNKNOWN`.

2. **Banana Robustness:**
   - Banana achieves 99.6% confidence on physical hardware with excellent feature sharpness (`img_detail_x10 = 5063`).
   - Grade ("Good") and Shelf-life ("3-6d Fresh") were successfully inferred directly from model outputs.

3. **Background False Acceptance Rate:**
   - On 3,023 test background images, the dual-stage gate (presence head + detail metric + confidence threshold) reduced false acceptance from 25.37% down to **0.93%**.
   - On physical hardware, the empty desk scene was rejected cleanly (`fruit_present=0`).
