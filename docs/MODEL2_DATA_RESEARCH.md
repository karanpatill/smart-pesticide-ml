# Model 2: sensor-based estimated residue-risk, data research (2026-10-09)

**Status: research complete. No model trained. Synthetic-data assumptions
below are a DRAFT awaiting approval.** Model 1 and its artifacts are untouched.

Target: an **estimated pesticide-residue RISK category** (LOW / MEDIUM /
HIGH) from TCS34725 (R, G, B, Clear), MQ135, pH and DHT22 (temperature,
humidity). This is **not** concentration or ppm measurement, and none of
these sensors can directly measure pesticide residue on produce.

## 1. Is there a compatible public dataset? No.

| Source | Sensors | Labels | Data public? | Usable for Model 2? |
|---|---|---|---|---|
| Tang et al. 2021, *RSC Adv.* 11:20874 ([PMC9034013](https://pubs.rsc.org/ra/article/11/34/20874/742885/A-novel-electronic-nose-for-the-detection-and)): e-nose, apples with cypermethrin / chlorpyrifos | PEN3, 10 lab MOS sensors | pesticide type and concentration | No dataset released | No: different sensors, no data |
| Cherry-tomato pesticide e-nose ([ScienceDirect S2772375526004855](https://www.sciencedirect.com/science/article/pii/S2772375526004855)) | 32 MOS sensors | pesticide treatments | Paywalled; data availability not confirmed (page blocked) | No (as far as could be checked) |
| MQ-135 organophosphate study, *Buletin Fisika* ([record](https://garuda.kemdiktisaintek.go.id/documents/detail/6023921)) | MQ-135 only | kanon / diazinon / curacron solutions, 0–100 ppm | No | No; but useful evidence (see §2) |
| IoT + ML pesticide detection, JETIR 2025 ([PDF](https://www.jetir.org/papers/JETIR2506132.pdf)) | pH, MQ135, temp/humidity, ESP32-CAM (**closest to our design**) | not described | No dataset, no label method, no quantitative results | No |
| EC + pH residue system, IJEM 2016 ([page](https://www.mecs-press.org/ijem/ijem-v6-n2/v6n2-2.html)) | EC, pH | chlorpyrifos vs pesticide-free vegetables | No | No; evidence only (EC deviations of 9–34% reported) |
| Zenodo 10947798 "Detection of Pesticide Residues in Commercially Available Fruits and Vegetables" | fertiliser sensor + IR | — | It is a **journal article PDF**, not a dataset | No |
| EU / FR / DE pesticide monitoring (Zenodo) | lab GC/LC-MS results | residue concentrations | Yes | No sensor readings; could inform *risk priors* only |
| **Food Freshness E-Nose Dataset**, Mahdian (Kaggle / [Zenodo 17285312](https://doi.org/10.5281/zenodo.17285312), CC BY 4.0) | MQ2–MQ9, **MQ135** | fruit type × storage day (1–5); **no pesticide labels** | **Yes**, downloaded and inspected (`data/raw/enose_freshness_zenodo/`, MD5 verified) | **Only to calibrate realistic MQ135 behaviour** (noise, freshness drift), not labels |
| Environmental DHT22 / IoT telemetry (Kaggle, Mendeley) | DHT22, gas, pH (soil) | none relevant | Yes | Only for realistic T/RH ranges |

**Conclusion:** no public dataset combines our sensor types (or close
equivalents) with pesticide-residue labels. A real Model 2 dataset can only
come from our own measurements with reference labels (e.g. lab LC-MS/GC-MS,
or at minimum a standardised enzyme-inhibition rapid test). Until then, any
Model 2 can only be a **synthetic pipeline prototype**.

## 2. What the evidence says each sensor can plausibly contribute

| Sensor | Plausible link to residue | Main confounders | Evidence |
|---|---|---|---|
| **MQ135** (broad-spectrum MOX) | Responds to volatiles from some organophosphate formulations and solvents. Shown with 10–100 ppm pesticide **solutions**, unstable at low concentration. Residues on produce are normally far lower. | **Fruit spoilage VOCs dominate.** Real data: MQ135 median rises ~2× over 4–5 days (banana 536 → 1,165; tomato 695 → 1,735; strawberry 637 → 2,861 raw units). Also temperature, humidity, sensor warm-up and drift, unit-to-unit variation. | Buletin Fisika study; Zenodo 17285312 (inspected) |
| **pH** | Weak, indirect: wash-water/extract pH (and EC) may shift with some formulations (chlorpyrifos study). Not specific to pesticides. | Fruit's own acidity (tomato vs banana), water source, washing protocol, probe calibration | IJEM 2016 (EC/pH) |
| **TCS34725** | **Depends on how it is used.** (a) Reading the fruit surface: no known residue signal; it mostly carries colour/ripeness/spoilage information (largely redundant with Model 1). (b) Reading an **acetylcholinesterase (AChE) enzyme-inhibition test strip/card**: the established low-cost colorimetric route for organophosphate and carbamate pesticides (RGB readings regressed against concentration in the literature). This is the only path where an RGB sensor carries a genuine residue signal. | Lighting, strip timing and temperature, enzyme batch; only OP/carbamate classes | AChE colorimetric literature ([PMC6651370](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6651370/), [ALS dipstick reader](https://rex.libraries.wsu.edu/esploro/outputs/journalArticle/Ambient-light-sensor-based-colorimetric-dipstick/99901227840501842)) |
| **DHT22** | None directly | Environmental covariate: needed to compensate MQ135 (and enzyme reaction speed) | — |

## 3. Proposed synthetic development dataset (DRAFT, requires approval)

Purpose: **build and test the ML pipeline only** (feature handling, splits,
model comparison, STM32-feasibility of model types). Any accuracy on this data
only measures how well models recover **our own assumptions**. It says nothing
about real pesticide detection.

Draft parameters: `configs/model2_synthetic_DRAFT.yaml`.

Generative structure (latent → observed):
1. **Latent variables per sample:** fruit type (Model 1's 5 classes),
   freshness state (fresh / spoiled, plus storage day 1–5 for MQ135 drift),
   ambient temperature and humidity, measurement session (batch), device
   unit offset, and a **latent residue-risk score** (unitless, 0–1).
2. **Risk label:** LOW / MEDIUM / HIGH from thresholds on the latent score.
   Draft prior 50 / 30 / 20%, then 5–10% label noise to imitate imperfect
   reference labels.
3. **Sensor models** (each with explicit, modest effect sizes):
   - **MQ135:** fruit baseline × storage-day drift calibrated to the real
     Zenodo e-nose medians/spreads, + temperature/humidity effect + session
     drift + noise, + a **small** risk-dependent increase (deliberately
     smaller than the spoilage effect).
   - **pH:** fruit-specific baseline (e.g. tomato acidic, banana near
     neutral) + probe offset + noise, + a small risk-dependent shift.
   - **TCS34725:** depends on decision D1 below.
   - **DHT22:** T 18–38 °C, RH 30–90%, sensor noise ±0.5 °C / ±2–5% RH; no
     direct label link.
4. **Leakage guard:** no feature is derived from the label; splits are by
   **session** (group-aware), so session offsets cannot leak.
5. **Realism checks before any training:** class balance; per-feature
   distributions vs references; correlations; a single-feature threshold
   check (no single sensor may separate the classes almost perfectly, which
   would be an unrealistic synthetic pattern); and a "freshness-only" baseline
   showing how much of the risk can be predicted from spoilage cues alone.

Training plan after approval: Random Forest, SVM (linear and RBF), XGBoost,
Logistic Regression; session-grouped train/val/test plus grouped k-fold CV;
accuracy, precision, recall, F1, per-class metrics, confusion matrices, feature
importances. Selection on grouped-CV generalisation **and STM32 feasibility**:
- logistic regression / linear SVM: tens of parameters;
- a small Random Forest or XGBoost: size depends on tree count and depth, and
  can be code-generated, e.g. emlearn / m2cgen;
- RBF-SVM: must store support vectors, usually the least MCU-friendly.

## 4. Decisions needed before generating data
- **D1: TCS34725 role.** (a) fruit-surface colour (expected to carry no
  residue signal; mostly a confounder), or (b) reader for an AChE rapid test
  strip (the only plausible genuine residue signal, but it requires a reagent
  strip in the eventual device protocol).
- **D2: Label semantics.** What should LOW / MEDIUM / HIGH mean once real data
  exists (e.g. relative to an MRL, or rapid-test inhibition-rate bands)? The
  synthetic thresholds should mirror that definition.
- **D3: Approve or adjust** the draft priors, effect sizes and noise in
  `configs/model2_synthetic_DRAFT.yaml`, especially that the residue signal
  is deliberately weak and overlapping.
- **D4: Freshness coupling.** Feed Model 1's condition output (or storage day)
  as an input to Model 2, so the spoilage effect on MQ135 can be separated
  from residue?
