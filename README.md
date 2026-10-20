# Smart Pesticide Residue Detection: Image Model

This repository holds the **image** part of the Smart Pesticide Residue Detection
System. A MobileNetV2 transfer-learning model is developed on a PC and later
deployed as an INT8 TFLite model on an **STM32F407VET6**.

> **Scope.** The image model classifies **fruit type** and **visible
> condition** (fresh vs spoiled). It does **not** detect pesticide residue.
> Residue is invisible to an RGB camera; detecting it is the job of the separate
> sensor model, which is out of scope here. Hardware integration is also out of scope for now.

Target fruits: **apple, banana, guava, tomato, brinjal**.

## Status

| Step | State |
|---|---|
| Environment and project structure | done |
| Dataset research and recommendation | done, see [docs/DATASETS.md](docs/DATASETS.md) |
| Deployment footprint measurement | done, see [docs/DEPLOYMENT_BUDGET.md](docs/DEPLOYMENT_BUDGET.md) |
| Dataset download | done (FruitNet + AgriFreshNET, checksums verified) |
| Label inspection and verification | done, see [docs/DATASET_AUDIT.md](docs/DATASET_AUDIT.md); **user visual sign-off pending** |
| Splits | done: 8,457 images, grouped by capture burst |
| Training / evaluation | sweep + final run done, see [docs/TRAINING_REPORT_01.md](docs/TRAINING_REPORT_01.md). **Not robust: shortcuts confirmed** |
| Shortcut-mitigation experiments | done, see [docs/EXPERIMENTS_01.md](docs/EXPERIMENTS_01.md) |
| Crop+composite and Model 1 selection | done, see [docs/EXPERIMENTS_02_MODEL1_DECISION.md](docs/EXPERIMENTS_02_MODEL1_DECISION.md): **Model 1 = full-frame 80 px / block_15 trained with background compositing** |
| Model 1 artifacts | done, see [docs/MODEL1.md](docs/MODEL1.md) (`models/model1/`, inference: `scripts/model1_predict.py`) |
| TFLite INT8 | not run (on hold by decision) |
| Model 2 (sensor risk) | research: [docs/MODEL2_DATA_RESEARCH.md](docs/MODEL2_DATA_RESEARCH.md) (no compatible public dataset). **SYNTHETIC prototype** results: [docs/MODEL2_PROTOTYPE_RESULTS.md](docs/MODEL2_PROTOTYPE_RESULTS.md). Not real pesticide-detection performance |
| Model 3 (quality grade + shelf-life range) | trained on frozen Model 1 features, artifacts in `models/model3/`, see [docs/MODEL3.md](docs/MODEL3.md). Natural Growth removed. Apple/tomato/brinjal heads weak; guava limited by Model 1 routing. Post-processing layer added (fruit-confidence threshold 0.976 and consistency rules R1-R3), no retraining |

A first model has been trained; it is **not** a robust spoilage detector (see the training report).

## Output limitation (read this first)

The target UI output was:

```
Fruit: Apple
Freshness: 92%
Quality: Excellent
```

After surveying the public datasets ([docs/DATASETS.md](docs/DATASETS.md)):

- **Fruit**: supported. All five fruits have labelled images.
- **Freshness %**: **not supported by any dataset.** No dataset found has a
  continuous freshness score. Reporting the softmax probability of "fresh" as
  a "freshness %" would be misleading. That number is model *confidence*, not a
  measured or calibrated freshness level.
- **Quality grade (Excellent/Good/...)**: **not supported.** The only condition
  label that exists for all five fruits is binary (FruitNet Good/Bad,
  AgriFreshNET Fresh/Rotten). AgriFreshNET also has *Semi-fresh*, but only for
  banana, tomato and brinjal, not apple or guava.

So the model currently produces:

```
Fruit:     Apple   (confidence 97%)
Condition: Fresh   (confidence 88%)
```

Ways to get a real freshness % or quality grade later (each needs a decision):

1. **Collect our own labelled data**: photograph the same fruits daily from
   purchase until spoilage and record days-since-harvest/purchase. That gives a
   genuine time-to-spoilage target (regression or ordinal classes).
2. **Use AgriFreshNET's 3 stages + shelf-life ranges** for banana, tomato and
   brinjal only, with an ordinal head. Apple and guava would still be binary.
3. **Probability calibration** (temperature scaling on the val set) can make
   the condition confidence statistically meaningful, but it is still
   P(fresh | image), not "% fresh".

## Engineering audit, robustness and deployment status (2026-10-09)
- Audit, findings and measured results: [docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md)
- End-to-end interface and schema: [docs/END_TO_END.md](docs/END_TO_END.md). Run `python scripts/analyze.py --image X --sensors Y.json`
- Repeatable demo: `python scripts/demo.py` produces [docs/DEMO_REPORT.md](docs/DEMO_REPORT.md)
- Checklists: [STM32 deployment](docs/STM32_DEPLOYMENT_CHECKLIST.md), [hardware integration](docs/HARDWARE_INTEGRATION_CHECKLIST.md), [sensor calibration protocol](docs/SENSOR_CALIBRATION_PROTOCOL.md), [viva preparation](docs/VIVA_PREPARATION.md)
- Model 2 C export: `firmware/model2/` + `models/model2_export/` (parity with Python: max |dp| 4.8e-7)
- **STM32 status:** nothing built or run on hardware. Memory plan with split TFLM arenas (CCM + SRAM1), camera-buffer reuse and int8-only kernels fits by host and cross-compile measurement: [docs/STM32_MEMORY_PLAN.md](docs/STM32_MEMORY_PLAN.md).
- **Firmware skeleton:** [firmware/stm32f407/README.md](firmware/stm32f407/README.md) — application modules, TFLM integration, linker script and startup; host-tested and lld link-checked only. Board drivers pending; no target build yet.

## Project layout

```
configs/
  config.yaml          experiment settings (classes, image size, model, training)
  datasets.yaml        dataset sources and EXPLICIT folder -> label mappings
data/
  raw/<source>/        downloaded datasets, untouched
  interim/             manifests, duplicate reports, prepare_summary.json
  splits/              train.csv / val.csv / test.csv
docs/                  dataset research, deployment budget
models/runs/<run>/     checkpoints, history, labels.json per training run
models/tflite/         float32 + INT8 .tflite and conversion reports
reports/               dataset audits, evaluation metrics and confusion matrices
scripts/               CLI entry points (below)
src/fruitvision/       reusable library code
tests/                 unit tests for labelling, dedupe and split leakage
```

## Pipeline

```
download -> inspect_dataset -> (human verifies labels) -> prepare_dataset -> train
        -> evaluate -> convert_tflite -> evaluate (int8) -> STM32Cube.AI analyze
```

| Script | Purpose |
|---|---|
| `scripts/download_datasets.py --source X` | Parallel download, SHA-256 check, safe extraction |
| `scripts/audit_dataset.py` | Per-class sample sheets, duplicate report, image stats, background-bias probe |
| `scripts/inspect_dataset.py --source X` | Folder tree, counts, image sizes, corrupt files, exact duplicates, and **contact sheets per folder** for visual label checking |
| `scripts/prepare_dataset.py` | Builds the manifest from explicit mappings, removes duplicates across all sources, drops label-conflicting duplicates, makes a stratified group split and asserts no leakage |
| `scripts/train.py` | Two-stage transfer learning (frozen backbone, then partial fine-tune) |
| `scripts/evaluate.py` | Accuracy, macro-F1, per-class report, confusion matrices, **per-source** and per-fruit breakdown |
| `scripts/convert_tflite.py` | Float32 + full-INT8 TFLite (int8 I/O), representative set from train only |
| `scripts/predict.py` | Inference on an image or folder with `.keras` or `.tflite` |
| `scripts/model_budget.py` | Measures INT8 size and estimates activation RAM for candidate configs (no data needed) |

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
```

Pinned versions of the working environment: `requirements.lock.txt`
(TensorFlow 2.18.1, Keras 3).

**GPU note:** TensorFlow ≥ 2.11 has no GPU support on native Windows, so this
venv trains on the CPU (i5-12450H). For the RTX 3050 (4 GB), use the existing
WSL2 Ubuntu with `pip install tensorflow[and-cuda]`. The model is small
(≈200k params at 80 px), so CPU training is workable for first experiments.

## Key decisions

| Decision | Reason |
|---|---|
| **Labels only from explicit folder mappings** (`datasets.yaml`) and a `labels_verified` gate | Prevents silently inventing or mis-assigning labels. Unmapped folders are reported and ignored |
| **Binary condition (fresh / spoiled)** | The only condition label all five fruits share (see above) |
| **Two heads (fruit, condition) on one backbone** | One forward pass on the MCU. The condition head generalises across fruits |
| **Group-aware split by capture burst + 256-bit pHash** | Both datasets are shot as bursts of near-identical frames. Grouping by EXIF/filename time (gap > 20 s starts a new group) keeps each burst in one split. The 64-bit pHash was rejected because it matched different fruits on plain backgrounds |
| **Exclude pre-augmented and mislabelled files** | AgriFreshNET `aug_*` padding copies and one mislabelled FruitNet burst (see audit) |
| **Stratify split by source × fruit × condition** | Keeps per-dataset evaluation possible and exposes source confounding |
| **Normalisation inside the model** (Rescaling layer) | The MCU feeds raw 0–255 pixels; PC and device preprocessing cannot drift apart |
| **Aspect-preserving resize + centre crop** | Keeps fruit shape undistorted. Must be replicated in firmware |
| **MobileNetV2 alpha 0.35, 80×80, truncated after `block_15_add`** | Measured: the full backbone is 589 KB as INT8 (> 512 KB flash) and 96 px needs ≥ 135 KB of activations (> 128 KB SRAM). The truncated 80 px model is 326 KB with ≥ 94 KB of activations. To be revisited with real accuracy data |
| **Full INT8 with int8 input/output** | Required for Cortex-M4 (no fast float NN, CMSIS-NN int8 kernels) |
| **Representative dataset from train split only** | Calibrating on val or test would leak information into the quantised model |
| **BatchNorm frozen during fine-tuning** | Standard practice for small datasets; avoids unstable statistics |

## Deployment budget (STM32F407VET6)

512 KB flash and 192 KB SRAM (128 KB main + 64 KB CCM; the tensor arena
normally fits only in the 128 KB main SRAM), both shared with the firmware,
camera frame buffer and the sensor model. Measured with `scripts/model_budget.py`
(untrained weights, so size only):

- The full MobileNetV2 (alpha 0.35) is **589 KB INT8 and does not fit**.
- Truncated after `block_15_add` it is **326 KB**. Peak activations are ≥ 94 KB at 80 px and ≥ 135 KB at 96 px.

Details and fallbacks: [docs/DEPLOYMENT_BUDGET.md](docs/DEPLOYMENT_BUDGET.md).

## Licences and attribution

The selected datasets are CC BY 4.0. Citations are in
[docs/DATASETS.md](docs/DATASETS.md#6-attribution-required-by-cc-by-40).
