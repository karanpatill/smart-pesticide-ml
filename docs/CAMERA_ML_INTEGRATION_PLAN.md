# Camera → frozen ML → OLED integration plan (2026-10-17)

Inputs reviewed: `docs/BOARD_BRINGUP_AUDIT.md` (a–j), `docs/ORIGINAL_FIRMWARE_OBSERVATION.md`, the firmware in
`firmware/stm32f407/`, tests (92 passing), and a **static analysis of a scratch copy** of the ENTC backup. The backup itself was
not modified (sha256 check OK). No board access in this task. **The ML model is NOT integrated with the camera yet.**

Evidence levels used below: **[STATIC]** = read from the ENTC binary (disassembly/data), consistent but not observed on hardware;
**[VERIFIED]** = measured on our host or the board; **[UNKNOWN]** = not determinable from available evidence.

## 1. What the ENTC firmware does with the camera (static analysis of the backup)
| Item | Finding | Evidence |
|---|---|---|
| Sensor init table | OV2640 (reg,val) table at flash 0x0800711C (421 pairs incl. trailing data) | [STATIC] |
| Output size | DSP bank: HSIZE8/VSIZE8 = 0x32/0x25 and HSIZE/VSIZE = 0x64/0x4A (400×296 window); ZMOW/ZMOH/ZMHH = 0x28/0x1E/0x00 → **160×120 (QQVGA)** | [STATIC] |
| Output format | IMAGE_MODE (0xDA) = 0x08 → **RGB565**, byte-swap bit 0 clear | [STATIC] |
| Capture mode | DCMI_CR: snapshot (CM = 1), PCKPOL = 1, 8-bit; **VSPOL/HSPOL are function arguments**. The first call loops over the 4 polarity combinations (auto-detect, string `S%d%d>%d%d`); later calls use RAM globals at **0x2000A35D / 0x2000A35E** | [STATIC] |
| DMA | DMA2 Stream 1, channel 1, P→M, 32-bit/32-bit, MINC, no circular, FIFO full threshold, priority high, PAR = DCMI_DR (0x50050028) | [STATIC] |
| Capture buffer | **0x2000055C**, NDTR 10,112 words = **40,448 B** | [STATIC] |
| Frame validity | success only if 38,384 < bytes ≤ 38,416, i.e. **38,400 B = 160×120×2**; 1.5 s timeout; overrun → error 5 | [STATIC] |
| Pixel layout | analysis code reads `p = (buf[2i] << 8) \| buf[2i+1]`, row stride 160 px → **row-major, RGB565 big-endian (high byte first)** | [STATIC] |
| ENTC analysis | centre ROI x 40–119, y 30–89; dark pixel = max(R,G,B) ≤ 59 ("Dark spots %"); mean RGB | [STATIC] |
| DCMI pins | strings `Check VSYNC PB7`, `PCLK PA6 HSYNC PA4`; D0–D7 not named | [STATIC hint] |
| OV2640 control | strings `PWDN GND RST 3V3`, `SCL:%d SDA:%d idle`, `Found 0x%02X` | [STATIC hint] |
| XCLK source/frequency, SCCB pins/bus, D0–D7 pins, clock tree (no PLLCFGR constant found), OLED bus/address | — | **[UNKNOWN]** |

**Conclusion on Q4:** the output format (160×120 RGB565, big-endian, row-major, 38,400 B, snapshot) and the ENTC buffer
size/location are established **consistently from static evidence**, but not observed on hardware. The actual polarities are chosen at
run time. GPIO/AF pins, XCLK and SCCB wiring are **not** established, so a camera driver cannot be written without guessing.

## 2. Fit with our ML path (from repo evidence)
* Preprocessing `fv_rgb565_to_input_int8(src, w, h, big_endian=1, dst)` already handles any W×H: centre-square crop
  (160×120 → 120×120) then Q16 bilinear to 80×80. [VERIFIED on host for 96×96/96×80; 160×120 not yet tested]
* Memory: our non-persistent arena has a free window [19,200, 97,280) B after the input tensor; a 38,400 B frame fits
  (ends at 57,600 B, 16-B aligned). No extra RAM is needed. [computed from the VERIFIED layout]
* Image checks: aspect 160/120 = 1.33 > 1.1 → `FV_IC_WARN_ASPECT` on every frame (warning, not rejection).
* On-target ML is verified: ~357 ms/inference, arena 148,896 B, stack 1,120 B, outputs identical to the PC [VERIFIED on board].
* Accuracy at 160×120 from an OV2640: **unknown**. Our camera proxy used 96×96 synthesised frames; real-camera accuracy needs real captures.

## 3. Minimum missing configuration (to connect captured frames to the model)
1. **DCMI GPIO map**: D0–D7, PCLK, HSYNC, VSYNC (+ AF13 confirmation). PA4/PA6/PB7 are hints only.
2. **XCLK**: source (MCO1 PA8? timer PWM?) and frequency.
3. **SCCB**: pins / I2C peripheral (I2C1 or I2C3, or bit-banged) and the OV2640 address used.
4. **Polarities**: the VSPOL/HSPOL values the ENTC firmware detected. They can be read **read-only** from 0x2000A35D/0x2000A35E
   while the ENTC firmware runs (SWD hot-plug `-r8`/`-r32`; needs your approval).
5. **Clock tree** (HSE frequency or HSI), so that the XCLK/PCLK timing matches the ENTC setup.
6. **OLED**: controller, I2C bus, address (for showing our result).
**Best single source for all six: the ENTC firmware source / CubeMX project.**

## 4. Prioritised plan
### P0: doable now from repository evidence (no hardware info, no flashing)
1. Make the camera geometry configurable and default it to the evidenced format: `FV_CAMERA_W/H = 160/120`, big-endian,
   38,400 B window. Host tests: the window fits in the arena, preprocessing parity (C vs `camera_preprocess.py`) at 160×120.
2. Host accuracy proxy at 160×120 RGB565 (public test images → 160×120 → our firmware preprocessing → TFLite), reported
   separately from the training-path numbers and labelled as a proxy, not a camera result.
3. Portable DCMI/DMA capture core mirroring the evidenced register configuration (snapshot, DMA2 S1 ch1, 32-bit, NDTR from
   frame size, frame-size validation 38,400 B, overrun/timeout errors), with GPIO/AF, XCLK and SCCB behind explicit
   `NOT_IMPLEMENTED` hooks. Unit-test it against a register mock on the host.
4. An "offline frame" self-test variant: embed a 160×120 RGB565 frame (synthesised from a stored test image) and run
   preprocess → model → validation on the board, to verify the camera-format path on target without the camera (flash
   only with approval, after a fresh backup).
5. OLED result formatter: already exists (`fv_report_oled`, 21×8); only the driver is missing.

### P1: needs a read-only board read (your approval, no flashing)
6. Read the ENTC polarity globals (0x2000A35D/E) and, optionally, the live ENTC frame buffer (0x2000055C, 38,400 B) while it runs.
   That gives a real OV2640 frame for host-side testing of our preprocessing and model (decode with big-endian RGB565).
   This would be the first real-camera input to our model. Caveat: a hot-plug read of a buffer that DMA is updating may
   catch a partial frame; read twice and compare.

### P2: needs ENTC information (Section 3)
7. GPIO/AF init for DCMI, XCLK, SCCB driver + OV2640 table (reuse ENTC's table if they approve), polarities.
8. OLED driver on the confirmed bus/address; sensors (TCS34725, MQ135, pH, DHT22) on confirmed pins.
9. Integrated image: capture → `fv_app_cycle` → OLED. Flash only after a fresh backup and approval; verify camera-to-model
   inference on the board (real captures, outputs logged via SWD readback).

### Alternative route (fastest if ENTC shares source)
Add our model as a library to the ENTC firmware: call `fv_rgb565_to_input_int8(frame, 160, 120, 1, in)` + `fv_vision_invoke` +
`fv_result_from_raw` after their capture succeeds, then print with their OLED functions. Flash budget: ENTC ~34 KB + ours ~430 KB
(< 512 KB, tight). RAM: their buffer 40 KB + our arenas (97 KB SRAM + 53 KB CCM) is **too much for 128 KB SRAM** unless their
frame buffer is moved into our arena window (as our design already does) or their other RAM use is small. Must be checked against their map.

---
## P0 status (2026-10-17): done on the host. No board access, nothing flashed. **Camera-to-model inference is still NOT integrated.**
| P0 item | Result |
|---|---|
| 1. 160×120 geometry | `fv_app.h`: `FV_CAMERA_W/H = 160/120`, `FV_CAMERA_BIG_ENDIAN = 1`, capture buffer `FV_CAMERA_BUF_BYTES` = 38,400 + 2,048 = 40,448 B (ENTC value) |
| C vs Python preprocessing | **bit-identical on 40 real public test images** at 160×120 RGB565 BE (plus the existing random-input parity incl. 160×120) |
| Memory fit | real C selector on the TFLM layout measured on the host: window at offset **19,200–59,648** of the 97,280 B non-persistent arena; no overlap with input/output tensors; 37,632 B spare. A separate 40,448 B buffer would **not** fit (application RAM free = 24,448 B) |
| End-to-end (host32 x86, real `fv_vision.cc` + TFLM) | **13/13** frames agree with the Python path (12 real-image 160×120 frames + 1 uniform frame correctly rejected); window offset 19,200 every time; flags = aspect warning (4096) only. 96×96 set still 10/10 |
| 2. Offline accuracy proxy (`reports/firmware/camera_proxy_160x120.json`) | **OFFLINE PROXY, not real-camera validation.** 1,012 public test images. ENTC format 160×120: fruit F1 0.8149 / condition F1 0.7493; agreement with the training path 0.786 / 0.711. Training path 0.8212 / 0.6883; 96×96 proxy 0.7893 / 0.7797 (reproduced). The 4:3 crop + centre-square crop zooms in, so predictions shift; the higher condition F1 is **not** an improvement claim |
| 3. DCMI/DMA capture core | `platform/fv_dcmi_capture.{h,c}`: ENTC register configuration (DMA S1CR 0x02025400, FCR 7, snapshot, PCKPOL); polarities must be supplied; size/timeout/overrun/buffer-full errors. **26/26 register-mock checks**, Cortex-M4F `-Werror` compile. GPIO/AF, XCLK and SCCB are NOT included |
| 4. Offline-frame self-test (`FV_TARGET=selftest_frame`) | embeds one 160×120 RGB565 BE frame (public banana image, offline). Host32: preprocessing hash 0x75A73113 = Python, raw outputs identical, result OK, PASS. GCC image `fv_selftest_frame.elf` builds: **FLASH 522,652 B = 99.69 %** (1,636 B free: tight), RAM 106,328 B. **Not flashed.** Readback tool supports v1 (288 B) and v2 (372 B) |
| Tests | **103 passed**, 0 failed (was 92) |

### Remaining blockers (unchanged by P0)
DCMI pins D0–D7 (PA4/PA6/PB7 hints only), XCLK source/frequency, SCCB bus/pins/address, confirmed VSPOL/HSPOL, clock tree, OLED
bus/address. Then: GPIO/AF init + OV2640 init + capture on hardware → real frames → on-target camera-to-model verification.
Flash margin: the frame self-test leaves 1.6 KB; the integrated application (~432 KB + drivers) has ~92 KB.
