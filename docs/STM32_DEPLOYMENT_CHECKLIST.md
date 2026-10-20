# STM32F407VET6 deployment checklist

Status legend:
- ✅ done in this repo;
- 🟡 measured on the host only;
- ⛔ blocked (needs hardware, a tool or a decision);
- ☐ not started.

**No STM32 build or hardware run has been performed.**

## A. Toolchain
- ⛔ Install `arm-none-eabi-gcc` or STM32CubeIDE + STM32CubeMX. Neither is
  present on the development PC.
- ⛔ Install X-CUBE-AI (STM32Cube.AI) to get the vendor memory report.
  Not installed; proprietary download.
- ☐ Create a CubeMX project:
  - SYSCLK 168 MHz;
  - DCMI + DMA2 for the OV2640;
  - I2C1 for TCS34725 + SSD1306;
  - ADC1 for MQ135 / pH;
  - GPIO for DHT22, buzzer, LED;
  - FPU hard-float ABI.

## B. Model 2 (sensor risk; SYNTHETIC PROTOTYPE)
- ✅ C99 inference `firmware/model2/model2_infer.{h,c}`; generated parameters
  in `models/model2_export/model2_logreg_params.h`.
- ✅ Parity vs sklearn on 3,646 vectors: max |Δp| 4.8e-7, 100% class agreement
  (host-compiled).
- 🟡 Cortex-M4F compile-only object: 768 B (+ libm `expf`/`logf`).
- ☐ Link into the firmware and run the same parity vectors on the target
  over UART.
- ⛔ A calibration profile mapping device units to the model scale. Needs
  real reference measurements (see `SENSOR_CALIBRATION_PROTOCOL.md`).

## C. Model 1 + Model 3 (image)
- 🟡 INT8 TFLite (`models/experimental/tflite/combined_int8.tflite`):
  366,848 B, int8 I/O.
- 🟡 Operators: ADD, CONV_2D, DEPTHWISE_CONV_2D, FULLY_CONNECTED, MEAN, MUL,
  SOFTMAX (all TFLite-Micro builtins with CMSIS-NN variants for
  conv / depthwise / FC / add / mul).
- 🟡 Single shared backbone: one `Invoke()` yields all 8 outputs.
  - **TFLM output index** (what firmware uses, `interpreter.output(j)`), derived from the model's
    signature names by `tools/firmware/gen_firmware_config.py`: condition 0, stage_banana 1,
    quality_guava 2, stage_brinjal 3, quality_banana 4, stage_tomato 5, fruit 6, quality_apple 7.
  - (Correction 2026-10-12: the previous `:0 … :7` list was the TENSOR-NAME suffix order, not the
    output index. Use `FV_HEAD_OUTPUT_INDEX` from the generated header; the firmware also checks
    output sizes at init.)
- 🟡 TFLite-Micro arena (host, reference kernels): **155,740 B**.
- 🟡 **RAM plan (2026-10-12, see `STM32_MEMORY_PLAN.md`):** split TFLM arenas fit by host/cross-compile measurement: persistent 53,120 B → CCM, non-persistent 96,000 B (+~864 B DSP scratch est.) → SRAM1, camera frame reused inside the non-persistent arena, int8-only kernels (flash 427,660 B). Must be confirmed on target.
- (superseded) **RAM blocker:** 155.7 KB arena > 128 KB contiguous main SRAM
  (SRAM1 + SRAM2). CCM (64 KB) is not DMA-reachable and not contiguous with
  main SRAM. Decide one of:
  - (a) measure with STM32Cube.AI;
  - (b) retrain at 64×64 (approval needed);
  - (c) external SRAM over FSMC;
  - (d) a different MCU or co-processor for vision.
- ☐ Flash budget, after a real link (`arm-none-eabi-size`):
  - model 358 KB + TFLM runtime + HAL + drivers + UI must fit in 512 KB;
  - the TFLM runtime size is not measured.
- ☐ Re-derive the post-processing threshold (currently 0.976, derived on
  float outputs) on INT8 / TFLM outputs from the VAL pool. INT8 outputs have
  1/256 resolution.
- ☐ Run the TEST split through the on-target model over UART and compare to
  the host TFLM figures (fruit F1 0.8179, condition F1 0.6896).

## D. Camera preprocessing (must match training)
- ☐ OV2640 output RGB565 at QQVGA (160×120) or a windowed square.
- ☐ **Centre-crop to a square** (120×120 from 160×120), then resize to
  80×80. The model was trained mostly on square images (81.2%); letterboxing
  a 4:3 frame adds 12.5% black bars per side.
- ☐ Convert RGB565 → RGB888 → int8 with the input quantisation
  (scale/zero-point from the `.tflite` input tensor). Normalisation is inside
  the model: feed raw 0–255 values quantised, **not** /127.5.
- ☐ Port the image sanity checks (luminance std, neighbour correlation,
  chroma; `configs/image_checks.json`). They are cheap integer statistics on
  the 80×80 buffer.
- ☐ Validate on device photos: the image models have **not** been
  evaluated on OV2640 images. Expect a domain gap.

## E. Timing / power (all ☐, nothing measured)
- ☐ Inference latency at 168 MHz with CMSIS-NN.
- ☐ MQ135 heater current (~150 mA typical, datasheet) and supply budget.
- ☐ DHT22 minimum 2 s between reads.

## Firmware skeleton status (2026-10-13)
- [x] Portable application modules + host parity tests (`firmware/stm32f407/`, `tests/test_fw_stm32_app.py`)
- [x] Real TFLM integration (`fv_vision.cc`) verified on 32-bit x86 host (20/20 exact; end-to-end 10/10)
- [x] Linker script + startup link-checked with lld (not GCC, not flashable)
- [x] ARM GNU toolchain installed in WSL (gcc 13.2.1)
- [x] Real GCC/newlib-nano target build: FLASH 432,276 B, RAM 106,624 B, CCM 53,248 B (`tools/firmware/build_gcc.sh`)
- [ ] Board schematic / pin map — next action (user)
- [ ] Board detection: NOT detected 2026-10-17 (no ST-LINK/DFU/USB-serial visible, no probe tool installed) — see `BOARD_BRINGUP_AUDIT.md`
- [ ] STM32CubeF4 HAL + 168 MHz clock config; flash with ST-LINK
- [ ] Board pin map; OV2640/DCMI, I2C, ADC, DHT22, UART drivers (currently `FV_ERR_NOT_IMPLEMENTED`)
- [ ] On-target: arena used bytes, stack painting, inference time, real camera frames
