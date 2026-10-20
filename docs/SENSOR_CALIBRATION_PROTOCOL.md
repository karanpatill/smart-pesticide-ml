# Sensor calibration and reference-measurement protocol

**Purpose:** collect the real data that Model 2 currently lacks. Until this
protocol produces reference-labelled data, every pesticide-risk output from
real device readings is `uncertain` by design.

## 1. Per-sensor calibration (before any sample measurement)
| Sensor | Procedure | Record |
|---|---|---|
| pH | 3-point calibration with certified buffers (4.01, 6.86, 9.18) at a recorded temperature; repeat daily; reject a session if the slope is < 90% of Nernstian | buffer readings (mV/ADC), slope, offset, temperature |
| TCS34725 (strip reader) | Fixed LED + dark enclosure + strip holder. Fixed ATIME/AGAIN. Read a white reference card and a dark reference each session. Store counts normalised to the white reference | ATIME, AGAIN, white/dark counts, LED current |
| MQ135 | ≥ 24 h initial burn-in (datasheet). Per session: ≥ 3 min warm-up; baseline R0 in clean air at recorded T/RH. Report Rs/R0, not raw ADC | load resistor, supply voltage, R0, T, RH, warm-up time |
| DHT22 | Spot-check against a reference thermometer/hygrometer; record offsets | reference values, offsets |

These produce a **calibration profile**: a named JSON mapping device units to
normalised quantities. That profile becomes `meta.calibration_profile` in the
sensor record. The current model's synthetic scales can only be used if the
profile maps onto them. A model retrained on real normalised data is
preferable.

## 2. Reference-labelled sample measurements
- **Reference method (ground truth):** an accredited laboratory
  multi-residue analysis (LC-MS/MS and/or GC-MS, e.g. QuEChERS extraction)
  on the *same* produce lot, giving mg/kg per pesticide. Alternatively,
  as a lower tier explicitly labelled as such, a commercial AChE rapid
  test kit read per its instructions. Then the label is "inhibition band",
  not residue.
- **Risk bands** must be defined *before* data collection, e.g. relative
  to an MRL or to rapid-test inhibition thresholds, and recorded in the
  protocol version.
- **Design:**
  - **Lots:** ≥ 3 pesticide treatments (including untreated controls) × the
    5 fruits.
  - **Sessions:** ≥ 2 sessions per lot (different days).
  - **Repeats:** ≥ 3 replicate strip / sensor readings per sample.
  - **Splits:** by lot and session, never by reading.
  - **Blinding:** the operator taking device readings does not know the
    lab result.
- **Per reading, log:** timestamp, device unit ID, calibration-profile
  version, all raw readings (TCS with ATIME/AGAIN, MQ135 ADC + Rs/R0,
  pH mV + calibrated pH, T, RH), fruit, lot, session, operator, strip lot,
  reaction time, ambient light.
- **Safety:** handle pesticide-treated produce per the product label and
  institutional rules; no consumption of samples.

## 3. Acceptance before any claim
- Grouped (by lot and session) cross-validation on real data, with
  per-class precision and recall and confidence intervals.
- A comparison with trivial baselines (e.g. condition-only, MQ135-only) to
  show which sensors carry information.
- Report agreement with the reference method. **Never report synthetic-data
  metrics as device performance.**

## 4. Image camera validation
Capture ≥ 30 photos per fruit and condition with the OV2640 under the demo
enclosure lighting. Label them by inspection with a written protocol and
evaluate Model 1/3 as-is before any retraining. These would be the first
on-device image results.
