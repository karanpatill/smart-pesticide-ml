# STM32F407VET6 memory plan for Model 1 + Model 3 (+ Model 2)

Evidence labels:
- **[H64]**: measured, TFLite-Micro on host x86_64 (64-bit pointers).
- **[H32]**: measured, TFLM built for 32-bit x86 (same pointer width as Cortex-M).
- **[XC]**: measured on a Cortex-M4F cross-compiled, size-only link.
- **[S]**: static analysis of the model graph.
- **[DS]**: datasheet / reference-manual fact, to confirm against RM0090 / DS8626.
- **[PLAN]**: design allowance, not measured.

**No firmware has been built, flashed or run on an STM32.** All tools and
versions are listed in §8. Machine-readable numbers:
`reports/stm32_memory/summary.json`.

## 1. Memory map [DS]
| Region | Address | Size | Contiguous with | CPU | DMA (DCMI, I2C, ADC, UART) | Notes |
|---|---|---|---|---|---|---|
| Flash | 0x0800_0000 | 512 KB | — | I/D-bus, ART accelerator | read | sectors 0–3: 16 KB, 4: 64 KB, 5–7: 128 KB |
| SRAM1 | 0x2000_0000 | 112 KB | SRAM2 | yes | **yes** (DMA1, DMA2) | |
| SRAM2 | 0x2001_C000 | 16 KB | SRAM1 | yes | **yes** | SRAM1 + SRAM2 = one **128 KB** contiguous block |
| CCM | 0x1000_0000 | 64 KB | nothing | D-bus only (no code execution) | **no** | DCMI/DMA2 cannot write here |
| Backup SRAM | 0x4002_4000 | 4 KB | — | yes | — | battery domain; not used |

The F407 has no data cache, so DMA buffers need no cache maintenance.
**CCM does not extend the 128 KB block.** A TFLM arena must be contiguous, so
a 149 KB single arena cannot fit anywhere.

## 2. What the "155.7 KB" figure is
TFLM's `RecordingMicroAllocator`, measured on the existing INT8 model
(`models/experimental/tflite/combined_int8.tflite`, 366,848 B, unchanged).
It is **one contiguous tensor arena**. Weights are not in it; they stay in flash.

| Part | [H64] | [H32] reference kernels | [H32] CMSIS-NN kernels | Contents |
|---|---|---|---|---|
| **Head (non-persistent)** | 96,000 | 96,000 | 96,000 | all activation tensors **including** the int8 input (80×80×3 = 19,200 B) and the 8 outputs (24 B), plus kernel scratch. Reused across layers by the greedy planner |
| **Tail (persistent)** | 59,696 | 52,848 | 53,216 | per-op kernel data (requantisation tables): 46,704 / 45,428 B; 202 eval-tensor structs 4,848 / 2,424; 80 node structs 5,120 / 2,560; tensor and quantisation records ~0.9 / 0.5 KB |
| **Total** | **155,696** | 148,848 | 149,216 | ("155.7 KB" earlier = 155,740 found by a ±256 B search) |
| Minimum single arena (16 B search) | — | 148,736 | 149,104 | |

So the figure is **total TFLM arena = activation memory (incl. I/O tensors) +
persistent runtime data**. It is not the activation memory alone (96,000 B),
and not the I/O tensors alone (19,224 B).

**[S] cross-check:**
- Static live-set analysis of the 80-op graph gives a peak of exactly
  **96,000 B**, matching the measured head. The peak is op 6
  (block_1 depthwise conv: 40×40×48 in = 76,800 B, 20×20×48 out = 19,200 B).
- The greedy planner already reaches this lower bound. **No planner can
  reduce activations further** without in-place execution or a model change.
- Cortex-M4 CMSIS-NN DSP scratch (formulas from CMSIS-NN source) adds
  **864 B** at the peak op, giving an **estimated 96,864 B** head on target.
  The largest scratch anywhere is 6,048 B, at an op with a much smaller live
  set.

## 3. Split arena: the no-retraining fix that fits
TFLM (verified in source, `MicroAllocator::Create(persistent, p_size,
non_persistent, np_size)`) supports **separate persistent and
non-persistent arenas**.

| Arena | [H32] CMSIS-NN minimum | Reserve on target [PLAN] | Region |
|---|---|---|---|
| Persistent | 53,120 B | **53,248 B** | **CCM** (CPU-only data; DMA never touches it) |
| Non-persistent | 96,000 B (DSP estimate 96,864 B) | **97,280 B** | **SRAM1** (DMA-reachable, so the camera can reuse it, §4) |

- Both minima together run correctly [H32].
- With int8-only kernel registration (§6): 20/20 test images give
  **byte-identical outputs** and the same minima [H32].

## 4. Camera strategy
**There is no OV2640 driver in this repository**, so supported output sizes
on our board are **unverified**. Reference evidence: the open-source
espressif/esp32-camera OV2640 driver produces 96×96, 128×128 and 160×120
etc. through the sensor's DSP scaler (ZMOW/ZMOH registers, 1:1 window).
Native formats: RGB565 / YUV422 at 2 B/px, or JPEG.

| Capture (RGB565, 2 B/px) | Buffer | Fits in the free arena window (76,800 B)? |
|---|---|---|
| 80×80 (not a listed driver size; scaler should allow it, unverified) | 12,800 B | yes |
| **96×96 (listed in esp32-camera)** | **18,432 B** | **yes** |
| 128×128 | 32,768 B | yes |
| 160×120 QQVGA | 38,400 B | yes |
| 176×144 QCIF | 50,688 B | yes |
| 240×240 | 115,200 B | no |
| 320×240 QVGA | 153,600 B | no |

JPEG would need a decoder plus a decode buffer and is not recommended.

**Reuse plan (no extra RAM for the frame):**
- [H32] measured layout: input tensor at non-persistent offset 0–19,199;
  all outputs at offsets 0–160. **[19,200, 96,000) is free between
  inferences.**
- Lifetime order (`firmware/memory/fv_arena_reuse.h`):
  1. read outputs;
  2. select window;
  3. DCMI DMA into the window;
  4. `fv_rgb565_to_input_int8()` into the input tensor (no overlap);
  5. `Invoke()`, which overwrites the frame after it is no longer needed.
- The window is **selected at runtime** from the interpreter's real pointers
  (layout can change with kernels/version); a dedicated 18,432 B buffer is
  the fallback.
- Unit-tested on host, including the measured layout.
- The model input tensor shares memory with intermediate activations (TFLM
  planner); outputs reuse the input's region after the first layers.

**Preprocessing** (`firmware/image/preprocess_rgb565.c`, C99, integer-only):
- centre-square crop, Q16 bilinear resize to 80×80, RGB565 → 8-bit by bit
  replication, int8 = v − 128 (model input scale 1.0, zero point −128, [H64]);
- **bit-exact** against the Python reference on 6 frame geometries;
- 666 B for Cortex-M4F [XC].

**Accuracy proxy [host, public test images, INT8 model]:**

| Path | Fruit F1 | Condition F1 | Agreement with training path (fruit / condition) |
|---|---|---|---|
| Training preprocessing | 0.8212 | 0.6883 | — |
| + RGB565 quantisation only | 0.8147 | 0.6822 | 95.9% / 97.0% |
| Firmware path (96×96 → RGB565 → 80×80) | 0.7893 | 0.7797 | 83.9% / 82.1% |

RGB565 itself costs little. The full camera-style path changes 16–18% of
predictions: the model is **sensitive to resampling** (no anti-aliasing,
square crop instead of letterbox). The higher condition F1 is not a claimed
improvement. **Real OV2640 images are required.**

## 5. RAM budget [measured parts + PLAN allowances]
| Main SRAM (128 KB = 131,072 B) | Bytes | Basis |
|---|---|---|
| TFLM non-persistent arena (camera frame reused inside) | 97,280 | [H32] 96,000 + [S] DSP scratch, rounded up |
| Camera frame | 0 | (fallback +18,432 if runtime selection fails) |
| SSD1306 128×64 frame buffer (I2C DMA) | 1,024 | [PLAN] |
| ADC / I2C / UART DMA buffers | ~1,024 | [PLAN] |
| Main stack (kept in SRAM so DMA-from-stack is never a hazard) | 8,192 | [PLAN]; measure by stack painting |
| **Remaining for HAL / drivers / app .data/.bss** | **~23,552** | not measured |

| CCM (64 KB = 65,536 B) | Bytes | Basis |
|---|---|---|
| TFLM persistent arena | 53,248 | [H32] 53,120 |
| Remaining for CPU-only app state (results, sensor history, Model 2 state) | ~12,288 | no DMA buffers here |

Model 2 needs only ~63 constants (flash) and a few hundred bytes of stack.

## 6. Flash feasibility [XC]
- Linked for Cortex-M4F (`-Os`, `--gc-sections`, CMSIS-NN DSP path), with
  TFLM runtime + CMSIS-NN + model.
- The combined model holds Model 1 and the Model 3 heads in **one**
  flatbuffer with a shared backbone, so weights are not double-counted.

| | Default kernel registration | **Int8-only registration** |
|---|---|---|
| .text (code) | 92,940 | **59,256** |
| — CMSIS-NN | 42,958 | 19,654 |
| — TFLM runtime | 39,700 | 29,666 |
| — compiler runtime (soft double maths) | 8,566 | 8,254 |
| .rodata (model 366,848 + 456) | 367,304 | 367,304 |
| **Flash total** | 461,364 | **427,660** |

- **Other firmware C [XC compile-only]:** Model 2 768 B, preprocessing
  666 B, arena selector 314 B. Subtotal **429,408 B**.
- **Left for** newlib-nano (`frexp`, `strcmp`, `strncmp`, `abort`,
  `__cxa_atexit` were stubbed), startup/vectors, STM32 HAL, the six device
  drivers, OLED font, post-processing/UI: **~94,880 B (92.7 KB)**.
  Not measured; plausible but must be confirmed by a real link.
- **Optional layout:** the model fits sectors 5–7 (384 KB from 0x0802_0000;
  26 KB spare), leaving sectors 0–4 (128 KB) for code. That lets the model
  be updated without erasing code.

## 7. No-retraining options (in the order requested)
| Option | Measured effect | Remaining requirement | Limits | Code change | Verifiable without HW? |
|---|---|---|---|---|---|
| A. Planner / activation optimisation | **0 B**: greedy plan already equals the live-set lower bound (96,000) [H32, S] | 96,000 B head | Only in-place execution or a model change could go lower | none | yes (done) |
| B. Input/output sharing | Already shared by the planner: input at offset 0, outputs inside it, **0 extra B** [H32] | — | Layout version-dependent | none | yes (done) |
| C. Camera / preprocessing buffer reuse | **−18,432 B** (96×96) vs a dedicated buffer [H32 layout] | frame inside arena window | Strict lifetime order; runtime selection | `fv_arena_reuse.c` (tested) | partly (host test; target confirm) |
| D. CCM for persistent arena + CPU-only data | **moves 53,120 B out of main SRAM** [H32]; main-SRAM arena 149,104 → 96,000 (+~864 est.) | fits | TFLM must use the split `Create`; no DMA in CCM | linker snippet + split create (size-link built) | partly |
| E. Smaller capture | 96×96 instead of 160×120: 18,432 vs 38,400 B | — | 96×96 support on our OV2640 setup unverified | camera driver config | no |
| F. Int8-only kernel registration | **−33,704 B flash** [XC]; outputs identical 20/20 [H32] | 427,660 B flash | none for this int8 model | 6 registration calls | yes (done) |

**Best no-retraining solution:** D + C + F + E. That is a split arena
(persistent → CCM, non-persistent → SRAM1), the camera frame captured at
96×96 RGB565 into the idle arena window, and int8-only kernels. By host and
cross-compile measurements this fits:
- **SRAM1:** ~97.3 KB of 128 KB;
- **CCM:** ~53.2 KB of 64 KB;
- **flash:** ~429 KB of 512 KB.

**64×64 retraining is not needed** on present evidence.

## 8. STM32Cube.AI
- **Not available:** no X-CUBE-AI pack, no `stedgeai` CLI, no
  STM32CubeMX/CubeIDE, on Windows or in WSL (checked
  `C:\ST`, `C:\Program Files\STMicroelectronics`, `~/STM32Cube`, PATH, pip).
  They are distributed by ST behind a myST login/licence.
- **No STM32Cube.AI result is claimed.**
- **To do it** (on a PC with ST Edge AI Core installed; confirm flags with
  `stedgeai --help` for the installed version):
  ```
  stedgeai analyze  -m models/experimental/tflite/combined_int8.tflite --target stm32f4 -O ram
  stedgeai generate -m models/experimental/tflite/combined_int8.tflite --target stm32f4 -O ram -o experimental/stm32cubeai_out
  ```
  Then compare its reported activations and weights with §2/§6. Check its
  options for allocating inputs/outputs inside the activation buffer and for
  splitting the activation pool across regions.
- Alternatively, ST Edge AI Developer Cloud (web, myST account) on the same
  file.
- Either way, keep the TFLM plan above as the baseline. Cube.AI uses a
  different runtime (no TFLM persistent structs), so its numbers will differ.

**Tools actually used:**
- TensorFlow 2.18.1 TFLite interpreter;
- tflite-micro Python package (WSL, 0.dev20261006);
- TFLM source commit `230c9d95` (2026-10-09);
- CMSIS-NN `4ab83cc3` (MD5 verified);
- flatbuffers v25.9.23 (via TFLM's downloader);
- zig 0.13.0 (clang) for x86 32-bit and Cortex-M4F;
- pyelftools.

Scripts: `tools/stm32_memory/`. Raw logs: `reports/stm32_memory/`.

## 9. Remaining blockers (all need hardware or vendor tools)
1. **A target build and on-device arena check.** STM32 toolchain (CubeMX +
   arm-none-eabi-gcc or CubeIDE) not installed. Confirm `arena_used_bytes()`
   for both arenas with CMSIS-NN DSP kernels on the F407.
2. **TFLM `Invoke()` stack usage** is not measured (stack painting on target).
3. **HAL / driver / application flash and RAM** are not measured (~94.9 KB
   flash and ~23.5 KB SRAM remain for them).
4. **The OV2640 driver does not exist.** 96×96 output, RGB565 byte order
   and DCMI timing are unverified.
5. **Camera-path accuracy** is only proxied. Real OV2640 images are needed.
6. **The post-processing threshold (0.976)** must be re-derived on INT8
   outputs (1/256 resolution).
7. **The STM32Cube.AI comparison** is blocked by the tool not being
   available.

## Update 2026-10-13: placement checked on a full link (still NOT on hardware)
Firmware skeleton in `firmware/stm32f407/` (see its README). Full Cortex-M4F link of firmware + TFLM
(int8-only CMSIS-NN) + model with `firmware/stm32f407/linker/STM32F407VETX_FV.ld` (zig/lld, labelled libc stubs, not flashable):

| Region | Used | Free | Contents |
|---|---|---|---|
| FLASH 512K | 437,536 | 86,752 | model 366,848 · TFLM ~29.8K · CMSIS-NN ~19.7K · compiler-rt/libm ~11.4K · app ~4.8K · preprocess/arena 1K · Model 2 0.45K · startup 0.6K |
| RAM 128K | 107,232 (incl. 8K stack reserve) | 23,840 | non-persistent arena 97,280 (camera frame reused inside it at offset ≥19,200), .data 664, cycle struct 680 |
| CCM 64K | 53,248 | 12,288 | `.ccm_arena` = TFLM persistent arena only (CPU-only data) |

Checks passing on the linked ELF (`tools/firmware/fw_elf_report.py`): no DMA buffer in CCM, only `.ccm_arena` in CCM,
arenas and model 16-byte aligned, no section overlap, no section spanning two regions, stack reserve inside RAM,
RAM-overflow ASSERT verified to fail a 121K-.bss link. Host32 run of the real `fv_vision.cc` with these arena sizes:
AllocateTensors OK, used 149,120 B, outputs 20/20 identical to TFLite. Not counted yet: newlib-nano (printf/libm),
HAL, drivers, real stack depth — remaining flash budget for them is 86,752 B.

### Real GCC build (2026-10-14, still NOT on hardware)
arm-none-eabi-gcc 13.2.1 + newlib-nano, `-Os`, `--gc-sections`, same linker script: FLASH 432,276 B (92,048 free),
RAM 106,624 B incl. 8 KB stack reserve (24,448 free), CCM 53,248 B (12,288 free). All placement checks pass on the
GCC ELF. Budget left for HAL + drivers: ~92 KB flash, ~24 KB RAM.
