# STM32F407VET6 deployment budget

| Resource | Total | Notes |
|---|---|---|
| Flash | 512 KB | Shared with firmware, TFLM/X-CUBE-AI runtime, sensor model |
| SRAM | 128 KB main + 64 KB CCM | CCM is not DMA-accessible and is a separate region. The tensor arena realistically has to fit in the **128 KB** main SRAM alongside the camera frame buffer and stack |
| CPU | Cortex-M4F @ 168 MHz | CMSIS-NN int8 kernels; no NPU |

## Measured INT8 footprints

Measured on 2026-10-08 with `scripts/model_budget.py` (TF 2.18.1). Two-head
model (5 fruits + 2 conditions), full-INT8 with int8 I/O, **untrained weights,
random calibration data**. These numbers describe **size only, not accuracy**.

| Input | α | Backbone cut | Params | INT8 .tflite | % of flash | Peak activations* |
|---|---|---|---|---|---|---|
| 96 | 0.35 | none (full) | 419,175 | 589 KB | 115% ❌ | 135 KB |
| 96 | 0.50 | none | 715,191 | 923 KB | 180% ❌ | 135 KB |
| 128 | 0.35 | none | 419,175 | 589 KB | 115% ❌ | 240 KB ❌ |
| 96 | 0.35 | block_16_project_BN | 262,519 | 404 KB | 79% | 135 KB |
| 96 | 0.35 | block_15_add | 199,519 | 326 KB | 64% | 135 KB |
| 96 | 0.35 | block_13_expand_relu | 99,863 | 189 KB | 37% | 135 KB |
| 96 | 0.35 | block_12_add | 91,831 | 177 KB | 35% | 135 KB |
| 80 | 0.35 | block_15_add | 199,519 | 326 KB | 64% | 94 KB |
| 80 | 0.35 | block_13_expand_relu | 99,863 | 189 KB | 37% | 94 KB |
| 64 | 0.35 | block_15_add | 199,519 | 326 KB | 64% | 60 KB |
| 64 | 0.35 | block_13_expand_relu | 99,863 | 189 KB | 37% | 60 KB |

\* Lower bound: the largest single op's input + output activations. The real
arena is larger (scratch buffers, alignment). Peak activations depend on input
size, not on the cut, because the peak occurs in the early high-resolution blocks.

## Conclusions

1. **The full MobileNetV2 does not fit in flash** even at the smallest width
   (α = 0.35) that has ImageNet weights. Truncating the backbone is required.
2. **96×96 input does not fit the 128 KB main SRAM** (≥ 135 KB of activations
   before any frame buffer). **80×80** (≥ 94 KB) is the largest plausible size.
   **64×64** (≥ 60 KB) leaves room for a frame buffer.
3. **Current default:** 80×80, α = 0.35, cut after `block_15_add` (326 KB).
   This is a starting point. The final choice (64 vs 80 px, cut point) must be
   made from **measured validation accuracy** together with STM32Cube.AI's
   reported flash/RAM, not from these numbers alone.
4. Fallbacks if it still does not fit: a deeper cut (`block_13_expand_relu`,
   189 KB), 64 px input, external QSPI flash for weights, or a smaller
   non-MobileNet backbone (would need justification).

## Required firmware-side preprocessing (must match training)

- RGB888, aspect-preserving resize to the input size, then centre crop or pad.
- Feed raw pixel values quantised with the input tensor's scale and zero point
  from `models/tflite/<run>_int8.json`. Normalisation is inside the model.
