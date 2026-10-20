# Engineering audit and robustness work (2026-10-09)

Evidence labels used throughout:
- **[MEASURED]**: produced in this environment by a script named here.
- **[PUBLIC DATA]**: metric on public-dataset images.
- **[SYNTHETIC]**: on synthetic data.
- **[ASSUMPTION]**: hardware/datasheet assumption, not tested.

**No hardware was available. No firmware was built or run on an STM32.**

## 1. What was inspected
- **Repository:** `src/fruitvision/**` (16 modules), 31 scripts, 6 configs,
  13 docs, 32 model artifacts, data/split manifests, existing tests (17,
  all passing at start).
- **Model hashes:** SHA-256 of every model file recorded *before* any change →
  `reports/audit/model_hashes_baseline.sha256`.
- **Clean-process model audit** (`python -I scripts/audit_models.py` →
  `reports/audit/model_audit.json`):
  - Model 1 and Model 3 (`.keras`) and Model 2 (`.joblib`) load;
  - input `[None, 80, 80, 3]`; output shapes as documented;
  - fruit order `apple, banana, guava, tomato, brinjal` and condition order
    `fresh, spoiled` are identical in `models/model1/labels.json`,
    `configs/config.yaml` and `postprocess.FRUITS`;
  - Model 3 head label orders match the post-processing routing;
  - `models/model3/postprocess_config.json` equals
    `configs/model3_postprocess.json`;
  - Model 2 feature order and class order (0 = LOW, 1 = MEDIUM, 2 = HIGH)
    match the training code.
- **Metric reproduction [MEASURED]:** recomputed from the saved artifacts.

  | Model | Metric | Reported | Recomputed |
  |---|---|---|---|
  | Model 1 | test fruit F1 [PUBLIC DATA] | 0.822 | 0.822 |
  | Model 1 | test condition F1 [PUBLIC DATA] | 0.6785 | 0.6785 |
  | Model 2 | test macro F1 [SYNTHETIC] | 0.7716 | 0.7716 |

  The Model 3 combined graph reproduces Model 1's outputs exactly.
- **Wording audit:** grep for ppm / pesticide-free / safe-to-eat /
  regulatory / MRL in docs and code found no over-claims. The only hits
  are explicit disclaimers or literature descriptions.
- **Toolchains:** no C compiler, no `arm-none-eabi-gcc`, no
  STM32Cube.AI / CubeIDE / CubeMX. WSL Ubuntu (Python 3.12, no pip at start).

### Findings
| # | Finding | Severity | Action |
|---|---|---|---|
| F1 | No input validation: corrupted, empty, grayscale, uniform and noise images reached the models; non-fruit inputs got ~1.0 confidence | High | Fixed (§2.1) |
| F2 | No sensor validation; no Model 2 inference interface outside the training script | High | Fixed (§2.2, §3) |
| F3 | Model 2 is fitted on synthetic scales (TCS counts at full-scale 1000, MQ135 Zenodo-like raw scale); real device units have **no calibration mapping** | High (scientific) | Enforced: device readings without a calibration profile → risk `uncertain` |
| F4 | Model 1 was trained mostly on square images (81.2% exactly square); an OV2640 4:3 frame is letterboxed (12.5% black bars per side) | Medium | Warning added; firmware must centre-square-crop (checklist) |
| F5 | `pyproject.toml` lacked `xgboost` (needed to load 5 Model 2 comparison joblibs) and `rembg`/`onnxruntime` (mask regeneration) | Low | Declared as optional extras |
| F6 | Output fields did not uniformly distinguish predicted / uncertain / unavailable | Medium | Additive `state` field on every output |
| F7 | **INT8 + TFLite-Micro arena = 155,740 B > 128 KB contiguous main SRAM** of the F407 [MEASURED, host] | **Blocker** for on-device Model 1/3 | Documented (§4); needs a decision |
| F8 | Post-processing threshold 0.976 was derived on float Keras outputs; INT8 outputs have 1/256 resolution | Medium | Must be re-derived on the deployed INT8 runtime (checklist) |

## 2. Robustness changes (no retraining)
### 2.1 Image checks (`src/fruitvision/validation/image_checks.py`, `configs/image_checks.json`)
- **Rejects:**
  - missing / empty / corrupted / truncated files;
  - unsupported formats (TIFF etc.) and animated images;
  - single-channel images;
  - images with a side < 32 px or > 12000 px;
  - near-uniform, noise-like or grayscale-content images.
- **Content thresholds:** placed at **½ of the minimum observed over 10,869
  real public-dataset images** (`scripts/calibrate_image_checks.py`), so
  none of those images is rejected:
  - luminance std < 8.37;
  - neighbour-pixel correlation < 0.378;
  - chroma < 0.893.
- **Warnings:** small images, alpha channels, aspect ratio > 1.1, dark /
  bright / clipped images.
- **This is a generic sanity check, not a trained not-a-fruit detector.**
  Ordinary photos of non-fruit objects still pass.

### 2.2 Sensor checks (`src/fruitvision/sensor/validation.py`)
- **Invalid (risk becomes `unavailable`):**
  - missing values, non-numbers, booleans, NaN/Inf (DHT22 read failure);
  - TCS34725 all-zero (disconnected), saturation (respects ATIME),
    negative or non-integer counts;
  - MQ135 at the 12-bit ADC rails or with an unknown unit;
  - pH outside (0, 14);
  - DHT22 outside −40..80 °C / 0..100 %RH.
- **Uncertain (category withheld; raw probabilities kept internally):**
  - device data without a calibration profile;
  - a feature outside the synthetic training range ± 10%;
  - MQ135 warm-up < 180 s.
- **Warnings:** unknown warm-up; TCS clear channel below a colour channel.

### 2.3 Output states
Every output has `state ∈ {predicted, uncertain, unavailable}`. Existing
fields are unchanged, guarded by `tests/test_regression_golden.py` against
outputs frozen *before* the change.

## 3. Model 2 embedded export [SYNTHETIC model; export fidelity MEASURED]
- `scripts/model2_export.py` → `models/model2_export/model2_logreg.json`
  + `model2_logreg_params.h` (feature order, derived-feature formulas,
  scaler, coefficients, intercepts, class order, synthetic training ranges,
  source sha256).
- `firmware/model2/model2_infer.{h,c}`: C99, float32, no heap. Error codes
  for null, NaN/Inf, and zero denominators.
- **Parity on 3,646 identical vectors** (`reports/audit/model2_parity.json`):
  - JSON runtime vs sklearn: max |Δp| = **0.0**;
  - C float32 vs sklearn: max |Δp| = **4.8e-7**, **100%** class agreement.
- **Cortex-M4F compile-only check** (zig/clang, `-mcpu=cortex_m4
  -mfloat-abi=hard -Os`): **768 B** object (476 B code + 252 B parameters),
  excluding libm `expf`/`logf`. Compile-only; not linked, flashed or run on
  target.

## 4. Model 1 + Model 3 deployment feasibility [MEASURED on host, not on target]
`scripts/tflite_feasibility.py` → `models/experimental/tflite/` (new files;
frozen Keras untouched, hash checked):

| Item | Value |
|---|---|
| Float32 TFLite | 788,764 B |
| **INT8 TFLite** (full integer, int8 I/O, TRAIN-only representative set of 240 images) | **366,848 B** (70% of 512 KB flash) |
| Operators | ADD, CONV_2D, DEPTHWISE_CONV_2D, FULLY_CONNECTED, MEAN, MUL, SOFTMAX (all TFLM builtins) |
| Shared backbone | one graph, one invocation → 8 outputs (Model 1 fruit/condition + 6 Model 3 heads) |
| Activation lower bound (largest single op) | 96,000 B |
| **TFLite-Micro minimum arena** (WSL x86_64, `tflite-micro` reference kernels, binary search ±256 B) | **155,740 B** |
| Fruit F1 Keras → host TFLite INT8 → **TFLM INT8** (1,012 test images) | 0.8220 → 0.8212 → **0.8179** |
| Condition F1 Keras → host TFLite INT8 → **TFLM INT8** | 0.6785 → 0.6883 → **0.6896** |
| Model 3 heads, INT8 vs Keras argmax agreement (test) | 86–98%; macro-F1 change −0.038 … +0.011 |
| TFLM vs host TFLite per-output max int8 diff (20 images) | 12–91 (kernel rounding differences) |

**RAM budget [MEASURED arena + ASSUMPTION datasheet]:**
- The F407VET6 has 128 KB contiguous SRAM (SRAM1 112 KB + SRAM2 16 KB)
  plus 64 KB CCM, and DCMI DMA cannot write to CCM.
- A TFLM arena must be contiguous: 155.7 KB > 128 KB.
- An OV2640 QQVGA RGB565 frame (38.4 KB) must also sit in DMA-reachable
  SRAM.
- **The current INT8 model does not fit on the target as converted.**

Options, none executed without approval:
- (a) measure with STM32Cube.AI, whose memory planner may differ (tool not
  installed);
- (b) retrain at 64×64 input: activation lower bound ~60 KB, needs approval
  and re-evaluation;
- (c) a deeper backbone cut (smaller late tensors, but early-layer
  activations dominate);
- (d) external SRAM over FSMC (hardware change);
- (e) a two-board design with a camera-capable co-processor.

## 5. End-to-end software [MEASURED behaviour on public-data images and labelled fixtures]
- `fruitvision.system.SmartPesticideSystem.analyze(image, sensors)`.
- CLI `scripts/analyze.py`; demo `scripts/demo.py` → `docs/DEMO_REPORT.md`.
- No combined score. LOW / HIGH interpretation text is fixed and
  conservative.

## 6. Tests
- **At start:** 17 passed.
- **Now: 66 passed.** New tests:
  - golden regression (5);
  - image checks (10);
  - sensor validation (18);
  - Model 2 export parity incl. compiled C (4);
  - system end-to-end (11);
  - post-processing state field (1).
- Final model hash verification: see the end of this run
  (`reports/audit/model_hashes_after.sha256`).


## 7. Update 2026-10-12: STM32 memory plan
The 155.7 KB figure is the TOTAL single TFLM arena (96,000 B activations incl. I/O + 59,696 B persistent data on a 64-bit host). With TFLM split arenas (32-bit host measurement) the persistent part (53,120 B) goes to CCM and the non-persistent part (96,000 B; ~96,864 B DSP estimate) to SRAM1. The camera frame is reused inside the non-persistent arena, and int8-only kernels save 33,704 B of flash (427,660 B total). Details, evidence labels and remaining blockers: [STM32_MEMORY_PLAN.md](STM32_MEMORY_PLAN.md). Still no STM32 build or hardware run.

## Addendum 2026-10-13 — firmware skeleton
STM32F407 firmware skeleton added (`firmware/stm32f407/`). Host-only evidence: C ports of output validation,
sensor validation/Model 2 applicability and image checks match Python; real TFLM path matches TFLite 20/20 on x86;
full Cortex-M4F lld link fits (flash 86,752 B free, RAM 23,840 B free incl. 8K stack, CCM 12,288 B free).
No target GCC build, no hardware test, no drivers. Frozen model hashes unchanged (32/32 + 3 experimental).
