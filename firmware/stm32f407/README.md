# STM32F407VET6 firmware integration (skeleton)

**Status: real target build done (arm-none-eabi-gcc 13.2.1 + newlib-nano, 2026-10-14). NOT flashed, NOT run on hardware.**
Board drivers (camera, sensors, OLED, UART) are **pending**, so the image would halt after `fv_platform_init()`.

Build (WSL): `bash /mnt/d/smart-pesticide-ml/tools/firmware/build_gcc.sh` → `reports/firmware/gcc/fv_fw.{elf,bin,map}`.

GCC result: FLASH 432,276 B (82.5 %), RAM 106,624 B incl. 8 KB stack reserve (81.4 %), CCM 53,248 B (81.3 %).
All placement checks pass (`reports/firmware/gcc/gcc_build_report.json`). Reset_Handler enables the FPU first;
hard-float VFPv4-D16 ABI. No-heap policy: `startup/fv_syscalls.c` (`_sbrk` always fails, `abort` halts).

## On-target ML self-test (board-independent, NOT yet flashed)
`FV_TARGET=selftest bash tools/firmware/build_gcc.sh` → `reports/firmware/gcc/fv_selftest.{elf,bin,map}`. Uses only the core clock
(HSI→PLL 168 MHz), SysTick and DWT; no GPIO. Results go to `g_fv_selftest` (SRAM), read with `tools/firmware/read_selftest.py` (SWD, read-only).
See `docs/BOARD_BRINGUP_AUDIT.md` (f) for the approval sequence.

## Application firmware with board drivers (2026-10-17, NOT flashed)
`bash tools/firmware/build_gcc.sh` → `reports/firmware/gcc/fv_app.{elf,bin,map}` (GCC 13.2.1, -Werror): FLASH 438,708 B, RAM 108,152 B
(incl. 8 KB stack), CCM 53,248 B; placement checks pass. Pin map and device settings come from the original ENTC firmware
(`docs/BOARD_PIN_MAP_EVIDENCE.md`, `board/fv_board_config.h`); drivers in `drivers/` (GPIO, bit-banged I2C/SCCB, OV2640, TCS34725,
SSD1306, DHT22, ADC) are tested against simulated hardware (`tests/fv_drivers_test.c`, 44 checks). Still disabled: MQ135/pH values
(channel mapping unknown; pH needs calibration); PB14 kind unknown. Diagnostics: `g_fv_diag` via `tools/firmware/read_diag.py`.

## Layout
| Path | Content | Status |
|---|---|---|
| `app/fv_app.{h,c}` | Pipeline: camera window → preprocess → image check → Model 1+3 → output validation; sensors → validation → Model 2; OLED + serial | host-tested |
| `app/fv_result.{h,c}` | Model 1/3 output validation (R1–R3, routing, shelf lookup), int8 dequant | parity vs `fruitvision.postprocess` |
| `app/fv_sensor.{h,c}` | Sensor validation + Model 2 applicability (calls `firmware/model2`) | parity vs `SmartPesticideSystem._risk` |
| `app/fv_image_check.{h,c}` | Content stats + frame-dimension checks | parity vs `image_checks.py` |
| `app/fv_report.{h,c}` | OLED 21×8 text, `FV1,...` serial line (no float printf) | host-tested |
| `app/main.c` | Arenas: persistent → `.ccm_arena` (CCM), non-persistent → `.bss` (SRAM) | GCC-built |
| `vision/fv_vision.{h,cc}` | TFLM interpreter, split arenas, int8-only CMSIS-NN ops, fail-closed interface checks | host32 x86: 20/20 exact vs TFLite; GCC-built |
| `vision/fv_debug_log.c` | TFLM DebugLog hooks (messages dropped) | |
| `platform/fv_platform.h` | Hardware boundary (camera, sensors, OLED, serial, LEDs), DMA rule | interface only |
| `platform/fv_platform_stm32_pending.c` | Every function returns `FV_ERR_NOT_IMPLEMENTED`. **No pins, no OV2640 driver.** | PENDING |
| `startup/fv_startup.c` | Interim vector table (16+82), FPU enable, .data/.bss, ctors. No clock config (HSI 16 MHz). Replace with CubeMX startup + `system_stm32f4xx.c` | GCC-built |
| `startup/fv_syscalls.c` | newlib hooks: no heap, abort halts | GCC-built |
| `linker/STM32F407VETX_FV.ld` | FLASH 512K / RAM 128K / CCMRAM 64K, `.dma_buffers` in RAM, stack reserve, `.ccm_arena` NOLOAD, ASSERTs | GNU ld + lld checked, negative test |
| `generated/fv_generated_config.h` | From frozen artifacts (`tools/firmware/gen_firmware_config.py`); drift-tested | |
| `tests/` | Host harness, host platform, TFLM stub, lld link stubs (**not firmware**) | |

Model data: `python tools/firmware/gen_model_data.py <out.c>` (hash-checked, 16-byte aligned, `.rodata`).

## Evidence
* `tests/test_fw_stm32_app.py` (13 tests): C vs Python parity of result/sensor/image checks, report format,
  error handling, pending-platform refusal, config drift, config vs `.tflite`, Cortex-M4F `-Werror` compile,
  lld placement, RAM-overflow ASSERT, recorded host32 and GCC evidence.
* `tools/firmware/build_fw_check.sh` (WSL, zig): real `fv_vision.cc` + TFLM on 32-bit x86 →
  `reports/firmware/host32_fv_vision_vs_tflite.json` (20/20 exact) and `host32_fv_app_e2e.json`
  (10/10 agree with the Python path; camera window at offset 19,200, after the input tensor).
* `tools/firmware/build_gcc.sh` (WSL, arm-none-eabi-gcc): real target ELF/BIN; sizes above.

## Remaining blockers
1. Board schematic / pin assignment for OV2640 (DCMI + SCCB + XCLK), TCS34725/SSD1306 (I2C), MQ135/pH (ADC), DHT22, UART.
2. STM32CubeF4 HAL/CMSIS device files and a 168 MHz clock configuration.
3. OV2640 driver (96×96 RGB565 via scaler — unverified) and all other drivers.
4. Hardware: flash with ST-LINK, on-target arena check (`fv_vision_arena_used_bytes`), stack painting, inference time, real captures.

## Tools
* ARM GNU toolchain — installed in WSL (gcc 13.2.1, make 4.3, cmake 3.28.3). Windows `sudo` is disabled; install
  WSL packages with `wsl -u root apt-get install ...` instead.
* STM32CubeF4 HAL/CMSIS — no login: `git clone --depth 1 --recurse-submodules https://github.com/STMicroelectronics/STM32CubeF4`
* STM32CubeMX / STM32CubeIDE — optional (pin/clock GUI, debugger); st.com downloads ask for a myST account or e-mail.
* Flashing: ST-LINK (`stlink-tools` in WSL needs USB passthrough via `usbipd`; or STM32CubeProgrammer on Windows).
* X-CUBE-AI / ST Edge AI — **not required**: the model runs on TFLM, already integrated.
