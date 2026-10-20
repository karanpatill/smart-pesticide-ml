# Project handoff: Smart Pesticide Residue Detection System (2026-10-17)

## 0. FINAL STATE (2026-10-17, evening): read this first. Supersedes §1 and §10.

**Purpose.** A fruit-inspection demonstrator on an STM32F407VET6:
* An OV2640 camera feeds a frozen INT8 TFLite model (Model 1 fruit + condition heads, Model 3 quality/stage heads). Output goes to an SSD1306 OLED.
* Sensors: TCS34725 colour, MQ135 gas (raw), pH probe (ENTC formula), DHT11.
* Model 2 (pesticide-risk prototype, synthetic data) is NEVER shown as a validated result.

**Architecture.** Each cycle takes ~2.7 s:
1. DCMI/DMA capture, 160×120 RGB565 (big-endian), into the TFLM arena.
2. Centre 120×120 crop, bilinear resize to 80×80 int8.
3. Image checks plus `fv_image_detail` (Laplacian variance).
4. TFLM Invoke (CMSIS-NN).
5. `fv_result_from_raw`, then rule R1 (conf < 0.976 → quality/shelf UNCERTAIN).
6. Presence gate (detail ≥ 43.96 AND conf ≥ 0.976, else "Fruit:NOFRUIT/UNKNOWN").
7. Sensors.
8. Risk is always UNCERTAIN/UNAVAILABLE.
9. OLED, then `g_fv_diag` (SWD-readable; the board has no UART).

| Item | State (verified 2026-10-17 from disk / SWD) |
|---|---|
| **Recommended demo firmware** | **`fv_app_v5`**: `reports/firmware/gcc/fv_app_v5.elf` (sha256 2a72f1b9b9e04e2b…), `.bin` (441,108 B, a48db15766c2172a…), `.map` (85ced9c6b584cd1d…) |
| Why v5 | v4 features (DHT11 decode, 8-page OLED flush, pH/MQ/T/RH rows) **plus** the presence gate; no diagnostic RAM blocks (RAM 108,192 B, 22,880 B free vs 3,560 B in v8_diag); 13/13 placement checks pass; embedded model bytes == `models/experimental/tflite/combined_int8.tflite` (366,848 B, sha256 1af166f0…) |
| Fallback | `fv_app_v4` (b18b2a29… / bin 9cd1191e…): proven on the board, but has **no** presence gate (an empty scene can show a confident wrong fruit) |
| **Board currently runs** | **`fv_app_v5`**. It was flashed with user approval on 2026-10-17: ELF hash checked first, "Download verified successfully", exit 0 (`reports/firmware/flash_fv_app_v5_log.txt`). Before that, `fv_app_v8_diag` ran (`reports/firmware/diag_final_v8_read.json`). |
| v5 on hardware (SWD diagnostics, automated) | Two read-only reads (`reports/firmware/diag_v5_after_flash_1.json`, `_2.json`) at uptime 26.8 s / 32.4 s:<br>• cycles 10 → 12 (no reset); clock, OLED, TCS and camera status 0; camera PID 0x26; table fail index −1; capture 38,400 B<br>• banana 0.996, condition fresh, detail 439.2 / 451.0, fruit_present 1, risk UNCERTAIN<br>• DHT11 33.0 °C / 51 %, pH 9.35 (uncalibrated formula), MQ135 raw 324 (not yet warmed)<br>The physical OLED on v5 is still to be confirmed by eye. |
| Tests | `.venv\Scripts\python -m pytest tests -q` → **172 passed, 0 failed** (`reports/firmware/final_test_output.txt`). Host/simulation tests, not hardware tests. |
| Real-camera fruit evidence | **Banana only:** 4 stable captures on v8_diag, detail 446.8/445.0/448.2/452.7, banana 0.988/0.992/0.996/0.996, STM32 == Python bit-exact (`reports/firmware/device_capture/20261017T144125Z_reposition_check`, `..._reposition_repeat_1..3`). The other 4 fruits are not validated on this camera. |

**OLED (physical observation by the user, photo, on v8_diag with the banana in the fixed position):** all 8 rows were visible:
1. `Fruit:banana 0.996`
2. `Cond:fresh`
3. `Grade:Good`
4. `Shelf:3-6d Fresh`
5. `Risk:UNCERTAIN`
6. `pH9.37 ENTC MQ324`
7. `T33.0C RH51%`
8. `*proto, not lab test`

v5 uses the same display code. Its screen must still be checked after flashing.

**Handover snapshot:** `backups/final_handover_<timestamp>/` with `MANIFEST.json` and `MANIFEST.sha256`. The latest snapshot is listed in `docs/FINAL_DEMO_CHECKLIST.md`.

**Camera lesson (most important for the demo).**
* The blur and the "banana → guava" results were caused by lens focus and camera position, not by registers or code. Evidence (`reports/firmware/camera_blur_investigation.md`):
  * The same firmware and the same registers gave detail 35 (blurred) and 351 (sharp) 10 s apart.
  * Once the camera was set back to the sharp position, 4/4 captures gave detail ~450 and banana ≥ 0.988.
* Fix the camera in that position (holder/tape) and do not turn the lens.
* The model sees only the centre square: the left and right 20 px of the 160×120 frame are cut. Keep the fruit centred and filling about half of the view.

**Live preview** (read-only; one SWD tool at a time):
* On `fv_app_v6/v7/v8_diag`: `.venv\Scripts\python tools\firmware\live_preview.py --firmware diag`
* On the original ENTC firmware: `.venv\Scripts\python tools\firmware\live_preview.py`
* `fv_app_v4`/`v5` keep no copy of the image, so there is no preview on them. Use the OLED and `read_diag.py`.

**Diagnostics (read-only):** `.venv\Scripts\python tools\firmware\read_diag.py --elf reports\firmware\gcc\<running firmware>.elf --execute`
(v5/v6/v7/v8 use the v3 layout, 444 B). Single camera capture (diag builds only):
`.venv\Scripts\python tools\firmware\read_capture.py --elf reports\firmware\gcc\fv_app_v8_diag.elf --label <name> --attempts 5 --execute`.

**Flash the final firmware: REQUIRES EXPLICIT APPROVAL** (close all other SWD tools first):
```
& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\reports\firmware\gcc\fv_app_v5.elf" -v -rst
```
Expect "Download verified successfully". Then: `read_diag.py --elf reports\firmware\gcc\fv_app_v5.elf --execute`.

**Rebuild:** use the archived v5 artifacts; do not rebuild for the demo. If a rebuild is needed, it goes to a NEW name (approval required for any flash):
`wsl bash -lc "cd /mnt/d/smart-pesticide-ml && FV_NAME=fv_app_v5_rebuild bash tools/firmware/build_gcc.sh"`
The build script now also lists `fv_capture.c`/`fv_cam_tune.c`; without `-DFV_DIAG_*` the linker drops them.
**Source equivalence was verified:** a rebuild of v5 from the current source is byte-identical to the archived `fv_app_v5.bin` (sha256 a48db157…; `reports/firmware/fv_app_v5_source_equivalence.json`).

**Restore the original ENTC firmware: REQUIRES EXPLICIT APPROVAL:**
```
& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\backups\board_original_firmware\board_flash_0x08000000_512K.bin" 0x08000000 -v -rst
```
Backup sha256 `1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c` (re-verified 2026-10-17, identical copy `pre_fv_app_20261017T102117Z.bin`).

**Firmware history** (all kept in `reports/firmware/gcc/`):

| Version | Description |
|---|---|
| v1 `fv_app` | First application build |
| v2 | pH/MQ135 pins and OLED sensor rows |
| v3 | DHT11 decode |
| v4 | 8-page OLED flush; proven on the board |
| v5 | Presence gate |
| v6_diag | Rolling capture of the model input |
| v7_diag | Write-once snapshot; never flashed |
| v8_diag | Rolling capture + live OV2640 tuning block; now on the board |

Memory (v5 / v8_diag):

| Region | v5 | v8_diag |
|---|---|---|
| FLASH | 441,084 B | 441,904 B |
| RAM incl. 8 KB stack reserve | 108,192 B | 127,512 B |
| CCM | 53,248 B | 53,248 B |

**Limitations (do not overstate):**
* **Pesticide detection is not validated.** Model 2 is trained on synthetic data and there are no laboratory residue measurements. The device risk is always UNCERTAIN/UNAVAILABLE.
* **MQ135** gives raw ADC counts only. They are not ppm and not pesticide; it needs a 120 s warm-up.
* **pH** uses the inherited ENTC formula with no buffer calibration (`docs/SENSOR_CALIBRATION_PROTOCOL.md`).
* **TCS34725** colour counts alone do not indicate residue.
* **DHT11** reports whole °C and whole % only.
* A working driver is not the same as a calibrated measurement.
* **Fruit model:**
  * 5 classes only, with no "not a fruit" class.
  * Real-camera success is shown for banana only.
  * The presence gate can reject real fruit (e.g. the earlier focused apple had confidence 0.852), so the OLED shows NOFRUIT/UNKNOWN.

**Troubleshooting:**

| Problem | What to do |
|---|---|
| OLED shows NOFRUIT for a fruit | Re-centre the fruit in the confirmed position and check that the camera holder has not moved (detail should be ≥ 44, ~450 when well placed; `read_diag.py` field `img_detail_x10`). Do not turn the lens at random. The live preview needs v8_diag on the board, and switching firmware requires an approved flash. |
| CLI "No STM32 target found" | Check the ST-LINK cable/power. Close other SWD tools. |
| Preview shows "skipped" | Wrong `--firmware`/`--elf` for the running firmware, or another tool is using SWD. |
| OLED shows UNKNOWN/NOFRUIT with a fruit present | Expected when detail < 43.96 or confidence < 0.976. Re-centre the fruit (about half of the view), use even light and check that the camera has not moved. Do not lower the thresholds. |
| A sensor row is missing or shows no value | Read the diagnostics: `dht_status` (DHT11 wiring/timing), `tcs_status`, `mq135_warmed` (wait 120 s), `ph_x100`. A missing value is reported as unavailable, never invented. Check the wiring with power off. |

**Required before pesticide detection could be claimed** (future work, not done):
* Known-reference fruit samples (spiked and blank).
* Accredited laboratory residue measurements, e.g. LC-MS/MS or GC-MS.
* Repeated, controlled sensor measurements of the same samples.
* Calibration of pH/MQ135/colour signals against those references.
* An independent test set, with performance figures and uncertainty reported.

Synthetic retraining is **not** a substitute for this.

---

## 1. Status (historical, morning of 2026-10-17; see §0)
| Item | State |
|---|---|
| Frozen models (Model 1, 2, 3; INT8 TFLite) | unchanged: 32/32 baseline hashes + 3 experimental artifacts verified |
| On-target ML (stored images) | **verified on the board**: self-test PASS, 3/3 outputs identical to PC, ~357 ms/inference, arena 148,896 B, stack 1,120 B |
| Live OV2640 frames (read over SWD from the ENTC firmware) | 3 captures in `reports/firmware/live_capture/`; format 160×120 RGB565 high-byte-first **confirmed** |
| Application firmware with board drivers (`fv_app`) | **built and host-tested only. NOT flashed, NOT tested on hardware** |
| Board currently runs | the **original ENTC firmware** (restored, verified) |
| Pesticide detection | **not validated**. Model 2 is a synthetic-data prototype; device readings are never reported as a predicted risk |

## 2. Files
* Firmware source: `firmware/stm32f407/` (app/, board/fv_board_config.h, drivers/, platform/fv_platform_stm32.c, vision/, startup/, linker/, selftest/, tests/)
* Pin map evidence: `docs/BOARD_PIN_MAP_EVIDENCE.md` (extracted from the ENTC firmware). Bring-up history: `docs/BOARD_BRINGUP_AUDIT.md`
* Firmware images: `reports/firmware/gcc/fv_app.{elf,bin,map}` (new application), `fv_selftest.*` (verified on board), `fv_fw.*`, `fv_selftest_frame.*`
  * `fv_app.elf` sha256 `b9a394b24dac1e5517814870726d55221e5d5d70e96241dfda35b7a8cc2489f7`
  * `fv_app.bin` sha256 `12e25e796c2811150f2f95a4a5a7cefdb05ec1ed503f380360388badf0d4900e` (438,708 B, load address 0x08000000)
* Snapshot of all sources + firmware artifacts (no git repo): `backups/handoff/source_snapshot_20261017T101552Z.zip` and
  `backups/handoff/manifest_20261017T101552Z.sha256` (235 files)
* Tools: `tools/firmware/read_diag.py` (read diagnostics, dry run by default), `capture_live_frame.py`, `live_preview.py`, `read_selftest.py`

## 3. Build and test commands
* Firmware (WSL, arm-none-eabi-gcc 13.2.1): `wsl bash /mnt/d/smart-pesticide-ml/tools/firmware/build_gcc.sh`
  (outputs to `~/tflm_work/build_gcc/`; refuses to overwrite a different existing `reports/firmware/gcc/fv_app.bin` unless `FV_OVERWRITE=1`)
* Placement report: `.venv\Scripts\python tools\firmware\fw_elf_report.py reports\firmware\gcc\fv_app.elf reports\firmware\gcc\fv_app_build_report.json`
* Tests (PowerShell): `.venv\Scripts\python -m pytest tests -q` → **147 passed, 0 failed** (2026-10-17). Includes 44 driver checks on simulated
  hardware (I2C/SCCB bit-level slave, OV2640/TCS34725/SSD1306 models, DHT22 waveform, GPIO/ADC register mocks).

## 4. Firmware size and memory (`fv_app`, GCC -Os, all placement checks pass)
| Region | Used | Free |
|---|---|---|
| FLASH 512 KB | 438,708 B (83.7 %) | 85,612 B |
| RAM 128 KB (incl. 8 KB stack reserve) | 108,152 B (82.5 %) | 22,920 B |
| CCM 64 KB (TFLM persistent arena only) | 53,248 B | 12,288 B |
Camera DMA frame (40,448 B) lives inside the TFLM working arena in SRAM (never CCM). Estimated stack ≪ 8 KB (largest non-ML frame 208 B).

## 5. Known hardware uncertainties
1. **MQ135 vs pH ADC channel** (PA2 = IN2, PA3 = IN3): unknown → both disabled, raw values only in `g_fv_diag`.
2. **pH calibration**: none → pH never reported.
3. **PB14 = LED or buzzer**: unknown → pulses 3× only on alert.
4. Pin map is extracted from the ENTC binary (STATIC), not from a schematic. Camera polarity and frame format are LIVE-verified.
5. XCLK assumed from the camera module (ENTC configures no XCLK pin).
6. I2C1 bus is bit-banged (~80 kHz) instead of ENTC's 400 kHz I2C peripheral.
7. DHT22 timing runs with interrupts briefly disabled (~5 ms); untested on hardware.

## 6. Recovery (restore the original ENTC firmware)
Backup: `backups\board_original_firmware\board_flash_0x08000000_512K.bin`, 524,288 B, sha256
`1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c` (verified OK 2026-10-17; restore already proven once).
```
certutil -hashfile backups\board_original_firmware\board_flash_0x08000000_512K.bin SHA256
& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\backups\board_original_firmware\board_flash_0x08000000_512K.bin" 0x08000000 -v -rst
```

## 7. First board test (each step needs explicit approval)
1. Close any preview or CubeProgrammer window (one ST-LINK user at a time).
2. Read-only identify: `STM32_Programmer_CLI.exe -c port=SWD freq=100 mode=HOTPLUG` (expect ID 0x413).
3. Fresh read-only backup to a NEW file: `... -c port=SWD freq=100 mode=HOTPLUG -u 0x08000000 0x80000 D:\smart-pesticide-ml\backups\board_original_firmware\pre_fv_app_<date>.bin`
4. Flash: `... -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\reports\firmware\gcc\fv_app.elf" -v -rst` → expect "Download verified successfully".
5. Observe: OLED shows "FV starting..." then a results page every ~2 s; note what PB14 does.
6. Read diagnostics (read-only): `.venv\Scripts\python tools\firmware\read_diag.py --execute`. Check, in order:
   * `clock_status` 0, `oled_status` 0, `tcs_status` 0;
   * `cam_probe_status` 0 with `cam_pid` 0x26, `cam_status` 0, `cam_table_fail_index` -1;
   * `last_capture_status` 0 with `last_capture_bytes` 38400;
   * fruit/condition values, TCS counts, DHT temperature/humidity, `adc_ch_a_raw`/`adc_ch_b_raw`.
7. If anything is wrong: record the `read_diag` output, then restore the ENTC firmware (section 6).

## 8. Update 2026-10-17: fv_app_v2 (PC-only; NOT flashed)
Changes (no model retraining; camera/ML code unchanged):
* DHT22 start pulse 1.1 ms → **20 ms** (ENTC timing); interrupts are now disabled only after the start pulse.
* pH = **PA2**, MQ135 = **PA3** (recovered from ENTC code, `docs/BOARD_PIN_MAP_EVIDENCE.md`). pH uses the **ENTC calibration** formula
  (`drivers/fv_entc_ph.{h,c}`: V = raw·3.3/4095, Vf = 0.95·Vf + 0.05·V, pH = (Vf − 2.282)·(−5.263) + 7, clamp 0–14; 200 samples).
  MQ135: raw 12-bit counts, 50 samples, warm-up flag after 120 s.
* OLED: up to two sensor rows ("pH<x.xx> ENTC MQ<raw>[w]", "T<t>C RH<h>%") are inserted only into free rows; existing rows and the
  "*proto, not lab test" footer are unchanged. Diagnostics v2 (436 B) adds ph_x100, ph_mv, mq135_raw, mq135_warmed.
* Pesticide risk stays UNCERTAIN/UNAVAILABLE (no device→Model 2 calibration profile).
Build: `FV_NAME=fv_app_v2 bash tools/firmware/build_gcc.sh` (clean) → `reports/firmware/gcc/fv_app_v2.{elf,bin,map}`;
FLASH 439,892 B (83.9 %), RAM 108,176 B (82.5 %), CCM 53,248 B; placement checks pass. Tests: 150 passed.
Flash command (requires approval): `STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v2.elf -v -rst`;
read diagnostics: `.venv\Scripts\python tools\firmware\read_diag.py --elf reports\firmware\gcc\fv_app_v2.elf --execute`.

## 9. Update 2026-10-17: fv_app_v3, DHT11 decoding (PC-only; NOT flashed)
The sensor is confirmed **DHT11**. v2 decoded it as DHT22, giving status −5 (range). v3 decodes DHT11 format exactly like the ENTC
firmware: checksum = sum of bytes 0–3, humidity = byte 0 (integer %), temperature = byte 2 (integer °C); bytes 1/3 ignored; range RH ≤ 100,
T ≤ 80 °C. Timing (20 ms start, IRQ handling), checksum, timeouts and diagnostics are unchanged; the diagnostics layout is still v2 (436 B).
Changed: `drivers/fv_dht22.{h,c}` (new `format` field, default DHT22; new `fv_dht11_decode`), `platform/fv_platform_stm32.c`
(format = DHT11), `tests/fv_drivers_test.c` (+8 DHT11 checks, 58 total), `tests/test_fw_board_drivers.py`.
Build: `FV_NAME=fv_app_v3 bash tools/firmware/build_gcc.sh` → `reports/firmware/gcc/fv_app_v3.{elf,bin,map}`;
FLASH 440,052 B (83.9 %, +160 B vs v2), RAM 108,176 B, CCM 53,248 B (both unchanged); placement checks pass; model bytes identical.
Tests: 150 passed. Flash (requires approval): `STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v3.elf -v -rst`;
diagnostics: `read_diag.py --elf reports\firmware\gcc\fv_app_v3.elf --execute`.

---
# 10. Handover state after v4 (2026-10-17, superseded by §0)
**Board runs `reports/firmware/gcc/fv_app_v4.elf`** (sha256 b18b2a29…; bin 9cd1191e…, 440,084 B). Flashed and verified on hardware.

## Verified on real hardware (diagnostics read over SWD)
* Boot, 168 MHz clock, main loop (~2.7 s per cycle).
* OV2640 camera: 160×120 RGB565 frame captured every cycle.
* Frozen INT8 fruit/condition model running on the STM32 on live frames (e.g. guava 0.91–0.95 / fresh 0.90–0.93). Quality and
  shelf life are withheld (UNCERTAIN) when fruit confidence < 0.976 (rule R1).
* DHT11 temperature/humidity (e.g. 33 °C / 54 %), TCS34725 colour counts, pH (PA2, ENTC calibration formula), MQ135 raw (PA3).
* OLED: driver reports all 8 pages written each cycle (v4). Physical visibility of the bottom 3 rows: confirm on the board.

## Not validated / limitations
* **Pesticide residue detection is NOT validated.** Model 2 was trained only on synthetic data; with real sensor values the risk is
  always shown as UNCERTAIN or UNAVAILABLE (no calibration from device readings to the model's synthetic scale, no real pesticide data).
* pH uses the ENTC firmware's formula (2.282 V at pH 7, −5.263 pH/V); not re-calibrated by this project. MQ135 = raw ADC counts (not ppm),
  needs 120 s warm-up. DHT11 gives integer °C / %.
* Fruit model: 5 fruits only (apple, banana, guava, tomato, brinjal); accuracy on the real camera is not measured (only a few frames);
  image focus/lighting strongly affect the result. No "not a fruit" detector.
* PB14 (LED or buzzer) is unconfirmed. It pulses 3× only on an "alert": an image rejected by the image check, or a PREDICTED HIGH risk (the latter never occurs). No UART: results are read via SWD (`read_diag.py`).

## How to build (PC, WSL with arm-none-eabi-gcc 13.2.1)
`wsl bash /mnt/d/smart-pesticide-ml/tools/firmware/build_gcc.sh` (set `FV_NAME=<new name>` for a new artifact; existing images are never overwritten).
Tests: `.venv\Scripts\python -m pytest tests -q` → 150 passed (2026-10-17).

## How to flash (PowerShell; close any other STM32CubeProgrammer/preview window first)
`& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\reports\firmware\gcc\fv_app_v4.elf" -v -rst`
Expect "Download verified successfully".

## How to read diagnostics (read-only, board keeps running)
`.venv\Scripts\python tools\firmware\read_diag.py --elf reports\firmware\gcc\fv_app_v4.elf --execute`
Key fields: clock_status 0, cycles increasing, last_capture_bytes 38400, dht_status 0, oled_status 0, fruit/condition, ph_entc_calibration, mq135_raw.
Live camera view (slow, read-only): `.venv\Scripts\python tools\firmware\live_preview.py`.

## How to restore the original ENTC firmware
`& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\backups\board_original_firmware\board_flash_0x08000000_512K.bin" 0x08000000 -v -rst`
(backup sha256 1590cd4e…601c, 524,288 B; a second identical copy: `pre_fv_app_20261017T102117Z.bin`).

## Demonstration procedure
1. Power the board; wait ~2 min (MQ135 warm-up). OLED shows Fruit / Cond / Grade / Shelf / Risk / pH+MQ / T+RH / footer.
2. Hold a fruit 15–30 cm in front of the focused camera, in good even light. Superseded by §0 and `docs/FINAL_DEMO_CHECKLIST.md`:
   only **banana** is confirmed on the real camera. Other fruits may show UNKNOWN.
3. Show sensors: pH probe in water/buffer, breathe or hold hand sanitiser vapour near MQ135, temperature/humidity row, colour
   sensor reacting to coloured objects.
4. On the laptop: `read_diag.py --elf … --execute` (all values) or `live_preview.py` (camera frames). Only one tool at a time.
5. Explain the pesticide risk shows UNCERTAIN/UNAVAILABLE because Model 2 is a synthetic-data prototype, not a validated test.
Firmware images kept: `fv_app.elf` (v1), `fv_app_v2.elf`, `fv_app_v3.elf`, `fv_app_v4.elf` (current) in `reports/firmware/gcc/`.

## 11. Update 2026-10-17: fv_app_v5 (fruit-presence gate) — built and tested on PC, NOT flashed
Fixes "empty scene shown as guava": a fruit is shown only if the image has enough detail AND confidence ≥ 0.976; otherwise the OLED shows
"Fruit:NOFRUIT/UNKNOWN" and Cond/Grade/Shelf UNCERTAIN. Trade-off (measured): real-camera fruit frames are often rejected too (the
focused apple, conf 0.852) — the device prefers "UNKNOWN" over a wrong fruit. Proper fix needs retraining with real device-camera data:
≥ 200–300 frames per fruit and ≥ 500 background/empty/non-fruit frames from this OV2640 under the demo lighting (new "no fruit" class),
then re-evaluation. Flash (approval needed): `STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v5.elf -v -rst`;
diagnostics: `read_diag.py --elf reports\firmware\gcc\fv_app_v5.elf --execute` (fields img_detail_x10, fruit_present).

## 12. Update 2026-10-17: Candidate background/presence head (`fv_app_candidate`) — PC-only, NOT flashed
* **Model:** `models/candidates/presence_int8_20261017T153321Z/combined_presence_int8.tflite` (372,608 B, sha256 `612f2e5586f0a4e2f2d7f7227e7cb6576cde1327f1a98453baec575f95e59300`).
* **Feature integration:** Integrated behind `FV_PRESENCE_OUTPUT_INDEX 4` in `firmware/stm32f407/candidate/generated/fv_generated_config.h`. When disabled/legacy, V5 behavior is 100% bit-exact and unchanged.
* **Metrics:**
  - Previous 8 outputs bit-identical across all 4,158 evaluated inputs.
  - Held-out TEST background false-fruit detections: 25.37% (v5 gate) → 0.93% (candidate head + detail gate).
  - Held-out TEST fruit acceptance: 1,012/1,012 (100.0%).
  - Accuracy when shown: 0.9636 (unchanged).
* **Firmware artifacts:**
  - ELF: `reports/firmware/gcc/fv_app_candidate.elf` (sha256 `6a2ae9087365c444ad92a8fafe072ad47bf6da8936beec1f42fc0662dba30edf`)
  - BIN: `reports/firmware/gcc/fv_app_candidate.bin` (446,980 B, sha256 `29081e6090732dec4f372a6a2842edc463bcf9f0c4c74fa43d0d295caed51095`)
  - MAP: `reports/firmware/gcc/fv_app_candidate.map` (sha256 `d70a4281ca557dab7b9ac9d26555bb3a0779f4def50f14018346db9d25b80827`)
  - Placement: 13/13 checks pass (`reports/firmware/gcc/fv_app_candidate_build_report.json`).
  - FLASH: 446,956 B / 512 KB (77,332 B free, 85.3%).
  - RAM: 108,208 B / 128 KB (22,864 B free, 82.6%, includes 8 KB stack reserve).
  - CCM: 53,248 B / 64 KB (12,288 B free, 81.3%).
* **Tests:** 179 passed, 0 failed (`pytest tests -q`).
* **Hardware status:** Board currently runs verified V5. Candidate is NOT flashed. Flash requires explicit approval.

