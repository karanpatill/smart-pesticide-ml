# P1: read-only live frame read (prepared 2026-10-17, NOT executed)

No SWD command was run while preparing this. **No live camera frame has been captured yet.**

## 1. Addresses (re-verified from the ENTC backup; the board's flash equals the backup byte for byte, see audit (i))
| Address | Length | Content | Evidence (disassembly of the backup) |
|---|---|---|---|
| 0x2000A35C | 1 B | camera_ready (set to 1 when a polarity combination captured a valid frame) | `strb #1 → [0x2000A35C]` @0x08002054; read @0x080020be |
| 0x2000A35D | 1 B | **VSPOL** (0/1) | polarity search: `VSPOL = i & 1` → stored @0x0800204C; passed as arg0 → DCMI_CR bit 7 |
| 0x2000A35E | 1 B | **HSPOL** (0/1) | `HSPOL = (i >> 1) & 1` → stored @0x08002052; arg1 → DCMI_CR bit 6 |
| 0x2000A35F | 1 B | unknown (used elsewhere) | read only, not interpreted |
| 0x2000A360 | 4 B | received byte count of the last capture (u32) | capture fn writes `(10112 − NDTR) × 4` through its 3rd argument |
| 0x20000008 | 16 B | status: +0 frame_ok, +1 err, +2/+3/+4 mean R/G/B, +5 dark %, +8 class (u32) | periodic capture @0x080020b8 and analysis @0x08001234 |
| 0x2000055C | 40,448 B | DMA capture buffer; **first 38,400 B = 160×120 RGB565, high byte first, row-major** | DMA M0AR literal @0x08001bc0, NDTR 0x2780 words; analysis reads `(b[2i] << 8) \| b[2i+1]` |

All regions are in SRAM1 and word-aligned. The script reads 8 + 16 + 40,448 + 16 + 40,448 + 8 B = 80,944 B.

## 2. Could a hot-plug SRAM read halt, reset or disturb the running firmware?
**Reset: no reset command is issued.** The command contains only `-c ... mode=HOTPLUG` and `-u` (upload/read). The CLI line
"Reset mode: Software reset" is the configured method for *later* reset commands; none is given.
**Halt: hot-plug attaches without halting.** Memory reads go through the debug access port while the core keeps running.
Measured evidence on this board: during the self-test readbacks the firmware heartbeat advanced 694 ms over 690 ms of wall
time across two hot-plug reads (`reports/firmware/selftest_clock_check.json`). The core was neither halted nor reset.
**Possible disturbances (small, transient, nothing is written):**
1. Bus contention: debugger reads share the SRAM bus with the CPU and DMA2. At these rates the effect is expected to be
   negligible. In the worst case one ENTC capture could report an error (OLED `CAMERA ERR 5`, overrun); the firmware retries on its next cycle.
2. Debug domain powered while connected (DP power-up request). This can keep clocks running in low-power modes during the session. We do not write
   DBGMCU or any other register.
3. Torn frame: the ENTC firmware re-captures periodically (snapshot into the same buffer). A read during a capture can mix two frames.
   This is detected, not prevented: the frame is read twice (a == b), and the ENTC statistics check (below) must match.

## 3. Capture script
`python tools/firmware/capture_live_frame.py` = DRY RUN (prints the plan, connects to nothing).
`python tools/firmware/capture_live_frame.py --execute --i-confirm-read-only` performs ONE CLI call:
```
"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 mode=HOTPLUG
  -u 0x2000A35C 8 <dir>\meta_a.bin   -u 0x20000008 16 <dir>\status_a.bin   -u 0x2000055C 40448 <dir>\frame_a.bin
  -u 0x20000008 16 <dir>\status_b.bin -u 0x2000055C 40448 <dir>\frame_b.bin -u 0x2000A35C 8 <dir>\meta_b.bin
```
`<dir>` = new `reports/firmware/live_capture/<UTC timestamp>/` (refuses to reuse an existing directory). Then it validates automatically:
* the file lengths;
* camera_ready = 1, valid polarities, last byte count = 38,400;
* frame stability (frame_a == frame_b over 38,400 B);
* **ENTC statistics cross-check:** mean R/G/B and dark % recomputed with the exact integer formula of the ENTC analysis
  (ROI x 40–119, y 30–89) from the frame decoded **big-endian** must equal the values the ENTC firmware stored at 0x2000000A–0x2000000D.
  The little-endian result is reported for contrast. This independently confirms the byte order and layout on the real data.

It writes PNGs (BE, plus LE for comparison) and runs **our frozen model on the PC** on that frame (offline inference on a real frame;
**not** on-target camera-to-model inference). Tests: `tests/test_fw_live_capture_tool.py` (6, synthetic data, no board).

## 4. Remaining uncertainty
1. Chaining six `-u` commands in one CLI call is standard CLI usage but **not yet exercised with v2.23.0 on this setup**. If it is
   rejected, the CLI exits with an error (read-only, harmless) and the script stops; no automatic fallback.
2. SWD 1000 kHz worked for flashing this board (950 kHz actual); `--freq 100` is available (a 40 KB read then takes ~5 s, more torn-frame risk).
3. Torn frames depend on the unknown ENTC capture period. If a and b differ, repeat the read later (a new approval).
4. The meaning of byte 0x2000A35F and of the class word at 0x20000010 is not decoded.
5. The image content depends on what is in front of the camera (lighting, background). One frame says nothing about accuracy.
6. Bus-contention effects are inferred from the architecture, not measured on this board (the OLED can be watched during the read).

## 5. Approval needed
Run: `.venv\Scripts\python tools\firmware\capture_live_frame.py --execute --i-confirm-read-only`
Expected side effects: none persistent. One hot-plug attach/detach (~2–3 s at 1000 kHz), no halt, no reset, no write. Possibly one
transient ENTC capture error.

## 6. Final safety review (2026-10-17, no board access)
Discrepancies found and fixed in `tools/firmware/capture_live_frame.py`:
1. The command check was a deny-list only. Added a **strict allow-list** (`check_allowlist`): exactly `-c port=SWD freq=N mode=HOTPLUG`,
   then exactly the six `-u <addr> <len> <file>` groups of REGIONS, with files inside the new output directory. Any other token fails.
2. A CLI timeout raised an unhandled exception without a log. It is now caught: log written, exit 4, no retry.
3. A partial read with CLI exit 0 (missing/short file) would have crashed in the analysis. It is now detected (`incomplete_files`) → exit 3, no retry.
Verified: one `subprocess.run` call, no retry loop (all loops iterate over the fixed REGIONS list); the output directory is new and
`mkdir` without `exist_ok` refuses an existing one; the dry run creates nothing. Tests: `tests/test_fw_live_capture_tool.py` 9/9 passed.
Approved-run command: `.venv\Scripts\python tools\firmware\capture_live_frame.py --execute --i-confirm-read-only`.

## 7. EXECUTED 2026-10-17 09:21:39 UTC (user-approved): first real OV2640 frame read from the board
Capture `reports/firmware/live_capture/20261017T092139Z/`. One hot-plug CLI call: 6 × "Data read successfully" (frames 0.67 s each @1 MHz), exit 0.
No write, reset or halt was commanded.
* camera_ready = 1, **VSPOL = 0, HSPOL = 0** (stable across both reads), last capture 38,400 B, ENTC status frame_ok = 1, err = 0.
* frame_a == frame_b (sha256 5c5b55cc…46c4ed); bytes 38,400–40,447 of the buffer are 0.
* **Format confirmed on real data:** ENTC's own stored statistics (meanR/G/B 170/169/155, dark 0 %) are reproduced exactly from
  the frame decoded **160×120 RGB565 big-endian**; little-endian gives 137/143/132 (no match). The BE image looks like a natural, blurry,
  low-contrast scene; the LE image is false-colour noise. ENTC class = "GRAY" (string at 0x08006E20).
* Our image check: no reject, aspect warning only (lum mean 150, std 24.9, lag-1 0.987, chroma 7.6).
* Our frozen model, **offline on the PC** on this frame: fruit guava 0.805 (< 0.976 → R1: quality/shelf UNCERTAIN), condition fresh 0.758.
  The scene does not appear to contain a recognisable fruit; since we have no not-a-fruit detector, this prediction is not meaningful.
  This is NOT on-target camera-to-model inference, and one frame says nothing about accuracy.

## 8. Second capture 2026-10-17 09:23:15 UTC (user-approved, "apple in front of the camera")
`reports/firmware/live_capture/20261017T092315Z/`. One hot-plug call, 6/6 reads OK, exit 0; read-only. All integrity checks pass:
camera_ready 1, VSPOL 0 / HSPOL 0, 38,400 B, frame_a == frame_b (sha256 32e635db…), ENTC status ok/err 0, and ENTC mean RGB
161/161/147 reproduced exactly from the big-endian decode (little-endian 130/124/128 does not match). ENTC class "GRAY".
The frame differs from capture 1 (new data, slightly darker), but **the image again shows a blurry, low-contrast scene with no
recognisable apple**. Likely causes (not verified): lens out of focus / too close, a lens cover or film, camera aimed elsewhere,
or a capture taken before the apple was in place.
Our model, offline on the PC: guava 0.840 (< 0.976 → quality/shelf UNCERTAIN), condition fresh 0.746. **Not meaningful for an
apple test:** the frame does not show the apple. No freshness or pesticide claim.

## 9. Offline model run on capture 2 (no board access), 2026-10-17
User reports the apple is visible. At 4× the BE frame shows a large, round, reddish object filling the centre, strongly defocused
(consistent with an apple very close to the lens). Correct decode = `frame_a_be.png` (pixel-identical to the BE decode of
`frame_a.bin`; LE PNG is the wrong byte order). Output: `reports/firmware/live_capture/20261017T092315Z/model_offline_full.json`.
| Path | Fruit | Condition | Quality | Shelf life | Warnings |
|---|---|---|---|---|---|
| A deployment (firmware preprocessing → INT8 TFLite) | **guava 0.840** (apple 0.148) | fresh 0.746 | Uncertain (R1) | not available (R1) | R1: 0.840 < 0.976 |
| B PC system (float Keras on the PNG, letterbox) | **banana 0.984** (apple 0.002) | fresh 0.759 | Good 0.9999 (banana head) | Rotten → 0–0 days | R2 contradiction (Good vs Rotten); image aspect warning |
**Neither path identifies the apple.** Path B is a confident misclassification that passes R1. Both are model predictions on one
defocused real frame, not validated results. The defocus/close-range domain shift is severe; one frame proves nothing about accuracy.

## 10. Live preview tool (built 2026-10-17, NOT yet run against the board)
`tools/firmware/live_preview.py` reuses `capture_live_frame.py` (CLI, decode, ENTC statistics). Each refresh is one hot-plug CLI call
with a strict allow-list of 4 reads: status 16 B, frame 38,400 B twice, status 16 B. A frame is shown only if both frame reads are
identical, the status did not change, ENTC frame_ok = 1 / err = 0, and ENTC's mean RGB/dark % are reproduced from the BE decode.
The double read was added because the ENTC statistics only cover the centre region: a tear in the top or bottom rows would otherwise
pass. Refresh 2 s (floor 1 s). After a failed read: wait ≥ 10 s; after 3 consecutive failures: pause until "Resume". No automatic
saving (raw reads live in a temp folder deleted on exit; "Save frame" button only). `--demo` uses simulated frames, and
`--print-command` connects to nothing. Tests: `tests/test_fw_live_preview.py` (19, simulated data). Full suite: 131 passed.

## 11. Capture 3 after lens adjustment (2026-10-17 09:46:31 UTC, user-approved, single capture)
The preview was closed by the user first (no live_preview/CubeProgrammer process running). `reports/firmware/live_capture/20261017T094631Z/`:
6/6 reads OK, exit 0, read-only. All integrity checks pass: VSPOL 0 / HSPOL 0, 38,400 B, frame_a == frame_b, ENTC ok/err 0, ENTC mean RGB
168/166/153 reproduced from the BE decode (LE 128/132/129, no match). The image now shows a large round reddish fruit (apple), still soft.
Offline INT8 deployment path (`model_offline_int8.json`): fruit **apple 0.852**, guava 0.148, others 0.000; condition fresh 0.629 / spoiled 0.371.
**R1:** 0.852 < 0.976, so quality and shelf life are withheld (uncertain). Image check: no reject, aspect warning only. ENTC class "GRAY".
Model prediction on one frame, not ground truth; no freshness or pesticide claim.

## 12. Offline image-quality metrics (2026-10-17, no board access)
`tools/firmware/image_quality.py` (tests: `tests/test_fw_image_quality.py`, 8 synthetic-image tests incl. sharp vs blurred). Metrics on
the model's centre crop (120×120 of 160×120) plus the 80×80 model input. **Comparative only; not pass/fail thresholds.**
| Capture | Sharpness (crop) | Sharpness (80×80) | Brightness | Highlight clip % | Shadow clip % |
|---|---|---|---|---|---|
| 20261017T092139Z (blurry scene) | 28.75 | 12.14 | 150.12 | 0.000 | 0.000 |
| 20261017T092315Z (apple, defocused) | 30.01 | 12.43 | 141.83 | 0.000 | 0.000 |
| 20261017T094631Z (apple, after refocus) | **73.60** | **84.07** | 139.07 | 0.875 | 0.000 |
Output: `reports/firmware/image_quality/20261017T095142_381203Z.json`. Capture folders unchanged.
