# Model 2 prototype: estimated residue-RISK on SYNTHETIC data (2026-10-09)

> **⚠ SYNTHETIC / PROTOTYPE PERFORMANCE ONLY.** Every number below comes from
> data generated from our own assumptions (`configs/model2_synthetic.yaml`).
> It shows how well each model **recovers those assumptions**. It is **not**
> real pesticide-residue detection performance, and it says nothing about
> concentration, ppm or MRL compliance. A real Model 2 needs measured sensor
> data with reference labels.

Decisions applied: TCS34725 = **AChE enzyme-inhibition test-strip reader**.
Target = LOW / MEDIUM / HIGH **inhibition/risk bands**, replaceable by real
reference labels. Model 1 outputs are auxiliary features. Model 1 artifacts
are untouched. No STM32 work.

Reproduce:
```
python scripts/model2_generate.py   # data/synthetic/model2/model2_synthetic_v1.csv + datacard_v1.json
python scripts/model2_audit.py      # reports/model2/audit/
python scripts/model2_train.py      # reports/model2/experiments/, models/model2_prototype/
```

## 1. Data and column roles
3,646 synthetic samples, 120 measurement sessions, 3 simulated device units.

| Role | Columns |
|---|---|
| **Sensor features** | `sensor_tcs_r/g/b/c` (AChE strip colour), `sensor_mq135`, `sensor_ph`, `sensor_temp_c`, `sensor_humidity_pct`; derived only from these: `drv_tcs_{r,g,b}_over_c`, `drv_log_mq135` |
| **Model 1 auxiliary features** | `aux_m1_fruit`, `aux_m1_condition`, `aux_m1_p_spoiled`, sampled from Model 1's **real** test-set predictions for the sample's true fruit and freshness, so they carry Model 1's real error rates |
| **Synthetic target** | `target_risk` (LOW/MEDIUM/HIGH, with 7% neighbour-class label noise) |
| Split groups only | `meta_session_id`, `meta_device_unit` |
| Generator truth (never features) | `latent_*` (clean label, risk score, inhibition, true fruit/freshness/storage day) |

By design the latent risk is **independent of fruit and freshness**, so
Model 1 outputs cannot predict risk by themselves.

## 2. Realism / data-quality audit (`reports/model2/audit/`)
| Check | Result |
|---|---|
| Class balance (label / clean) | 47.7 / 33.6 / 18.7% · 50.5 / 30.8 / 18.7%; realised label noise 7.65% |
| MQ135 drift vs real e-nose data (median, day d / day 1) | banana: real 1.30 / 1.52 / 2.02 / 2.17, synthetic 1.26 / 1.54 / 2.02 / 2.58 · tomato: real 1.40 / 1.78 / 2.06 / 2.50, synthetic 1.25 / 1.54 / 1.98 / 2.51 (day-5 banana somewhat high) |
| Spoilage vs risk effect on MQ135 | spoiled / fresh median 1.69× vs HIGH / LOW 1.05×, so spoilage dominates as intended |
| Spearman correlation with target | strip R 0.73, G 0.63, C 0.60, B 0.11; MQ135 0.07; pH 0.04; T −0.03; RH −0.01; aux P(spoiled) 0.01 |
| Single-feature separability (depth-2 tree, session-grouped CV; flag > 0.80) | best: R/C ratio 0.73, B/C ratio 0.71, R 0.69. MQ135, pH, T, RH 0.46–0.48 (majority baseline 0.477). **No flags.** |
| Model 1 aux-only proxy check (flag macro-F1 > 0.40) | macro-F1 0.30 (≈ chance). **No proxy.** |
| Leakage | no target, latent or meta column in the features; 0 duplicate feature rows; no session in more than one split (asserted) |
| Label-noise ceiling | 92.4% overall (92.8% on TEST): the best achievable accuracy against noisy labels |

Histograms and the correlation heatmap are in `reports/model2/audit/`. The
classes overlap substantially on the strip channels and are indistinguishable
on MQ135, pH, T and RH alone.

## 3. Session-based split
| | Sessions | Rows | LOW / MED / HIGH |
|---|---|---|---|
| Train | 84 | 2,523 | 47.8 / 33.5 / 18.7% |
| Val | 18 | 580 | 45.2 / 35.3 / 19.5% |
| Test | 18 | 543 | 49.9 / 32.2 / 17.9% |

Hyper-parameters were chosen on VAL. 5-fold session-grouped CV ran on
TRAIN+VAL, then a final refit on TRAIN+VAL and **one** evaluation on TEST.

## 4. Results: SYNTHETIC / PROTOTYPE (macro averages)
**S = sensor features only · S+A = sensor + Model 1 auxiliary features**

| Features | Model | CV macro-F1 (±sd) | TEST acc | TEST macro-P | TEST macro-R | TEST macro-F1 | F1 LOW / MED / HIGH | est. MCU size |
|---|---|---|---|---|---|---|---|---|
| S | Logistic Regression | 0.767 ± 0.016 | 0.786 | 0.766 | 0.778 | 0.772 | 0.86 / 0.67 / 0.78 | ~252 B |
| S | SVM linear | 0.768 ± 0.012 | 0.788 | 0.769 | 0.778 | 0.773 | 0.87 / 0.67 / 0.79 | ~252 B |
| S | SVM RBF | 0.768 ± 0.020 | 0.772 | 0.750 | 0.749 | 0.749 | 0.86 / 0.64 / 0.75 | ~100 KB (1,832 SVs) |
| S | Random Forest | 0.757 ± 0.016 | 0.785 | 0.775 | 0.759 | 0.766 | 0.86 / 0.66 / 0.77 | ~1.9 MB |
| S | XGBoost | 0.762 ± 0.011 | 0.777 | 0.769 | 0.753 | 0.760 | 0.86 / 0.66 / 0.76 | ~340 KB |
| S+A | Logistic Regression | 0.764 ± 0.014 | 0.781 | 0.760 | 0.767 | 0.763 | 0.86 / 0.66 / 0.76 | ~412 B |
| S+A | SVM linear | 0.768 ± 0.014 | 0.792 | 0.773 | 0.780 | 0.776 | 0.87 / 0.68 / 0.78 | ~412 B |
| S+A | SVM RBF | 0.767 ± 0.015 | 0.766 | 0.744 | 0.739 | 0.741 | 0.86 / 0.63 / 0.73 | ~160 KB |
| S+A | Random Forest | 0.758 ± 0.019 | 0.770 | 0.759 | 0.746 | 0.752 | 0.85 / 0.64 / 0.76 | ~670 KB |
| S+A | XGBoost | 0.761 ± 0.009 | 0.785 | 0.765 | 0.762 | 0.763 | 0.87 / 0.66 / 0.76 | ~110 KB |

Baselines (same split and folds): majority class macro-F1 0.22 · Model 1
aux-only 0.29 · strip-only logistic regression 0.72.

Confusion matrix, selected model (S / Logistic Regression), TEST, rows = true:

| true \ pred | LOW | MEDIUM | HIGH |
|---|---|---|---|
| LOW | 232 | 38 | 1 |
| MEDIUM | 34 | 116 | 25 |
| HIGH | 0 | 18 | 79 |

Per-class (same model): LOW P 0.87 / R 0.86 · MEDIUM P 0.67 / R 0.66 · HIGH P
0.75 / R 0.81. Errors are almost all between neighbouring bands; LOW↔HIGH
confusions: 1. All confusion matrices and per-class reports:
`reports/model2/experiments/{S,S_plus_A}/<model>/`.

Feature importance (permutation on TEST, drop in macro-F1), consistent across
models: strip **R/C ratio** (0.11–0.26), **R** and **B/C** ratio,
**temperature** (0.05–0.08, because the generator makes strip colour
development temperature-dependent), small MQ135 (≤ 0.02) and pH (≤ 0.01).
Model 1 aux features ≤ 0.004.

## 5. Interpretation (synthetic only)
- **Model differences are within noise.** All CV macro-F1 values lie within
  0.011 of each other with fold sd 0.01–0.02. Non-linear models gain nothing
  because the generator's effects are close to linear once the
  lighting-invariant strip ratios are used.
- **Model 1 auxiliary features add nothing** (S+A vs S: −0.003 to +0.001 CV
  macro-F1). That is expected: risk is independent of fruit and freshness
  here, and the MQ135/pH risk effects that aux could help separate from
  spoilage are deliberately tiny. The proxy guard holds (aux-only ≈ chance).
- **The strip carries almost all the signal (by assumption).** Strip-only
  0.72 vs all sensors 0.77. The scores therefore mostly reflect the assumed
  strip band overlap (jitter sd 0.08) and lighting/temperature variation.
  Real strip behaviour must be measured.
- **MEDIUM is the hardest class** (F1 ≈ 0.67), as expected for a middle band
  with neighbour label noise.
- Tree models were searched without any MCU size constraint; size-constrained
  trees were not tried (no extra search, per instructions).

## 6. Selected prototype model
**Logistic Regression on sensor features only (S), C = 0.1, class-balanced.**
File: `models/model2_prototype/S__logreg.joblib`.

- The pre-registered rule (CV macro-F1 within 0.02 of best, then smallest
  footprint) leaves a tie at ~252 B between linear SVM and logistic
  regression; the linear SVM's tie-break edge is 0.0007 CV macro-F1, well
  inside fold sd 0.015. **Logistic regression is chosen** because it outputs
  class probabilities natively, needed to report an estimated-risk confidence,
  and is equally small.
- **Sensor-only (S)** because the aux features gave no benefit and leaving
  them out removes any proxy risk and the dependency on Model 1 at inference.
  The S+A pipeline is kept for re-testing on real data, where fruit and
  freshness may matter for MQ135/pH compensation.
- **STM32 feasibility (estimate, not measured on device):**
  - 12 standardised inputs × 3 classes: 36 weights + 3 biases + 24 scaler
    values, about 63 floats (~252 B) and a few hundred FLOPs, so negligible
    beside Model 1.
  - RBF-SVM (~100–160 KB), XGBoost (~110–340 KB) and the unconstrained
    Random Forest (~0.7–1.9 MB) would compete with Model 1's ~326 KB for the
    512 KB flash.

**This selection is a pipeline choice, not evidence that the approach detects
pesticide residue.** Selection will be repeated on real reference-labelled data.

## 7. What must replace the synthetic assumptions
Real measurements of: strip RGB vs reference inhibition (or lab
residue-referenced bands) under the device's LED and enclosure; strip
timing/temperature effects; MQ135 and pH on the real sample protocol;
session and device-unit variation. Re-run `model2_audit.py`-style checks and
the same session-grouped protocol on that data.
