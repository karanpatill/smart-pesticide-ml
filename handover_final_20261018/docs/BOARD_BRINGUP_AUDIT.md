# Board bring-up audit (2026-10-17): read-only, nothing flashed

**Result: the board was NOT detected.** No debug probe, USB-serial adapter or STM32 DFU device is visible to
this PC, and no flashing/debug tool is installed. Nothing was flashed, erased, reset or modified.

## 1. Firmware / hardware configuration in the repo
| Item | State |
|---|---|
| Firmware skeleton `firmware/stm32f407/` | App, vision (TFLM), startup, syscalls, linker script done; host-tested |
| Platform layer `platform/fv_platform_stm32_pending.c` | **Every function returns `FV_ERR_NOT_IMPLEMENTED`**: no clock config, no GPIO, no drivers |
| Pin map | **None in the repo.** `docs/HARDWARE_INTEGRATION_CHECKLIST.md` lists interfaces only ("suggestions to be verified"); no pins are assigned anywhere |
| Programming interface | **Not documented** (no schematic, no probe type, no SWD/UART/DFU notes) |
| Frozen models | Unchanged (32/32 baseline hashes + 3 experimental artifacts verified) |

## 2. GCC build (verified, reproducible)
`tools/firmware/build_gcc.sh` (arm-none-eabi-gcc 13.2.1 + newlib-nano, WSL) was rebuilt on 2026-10-17 and gave an identical BIN.
| File | Path | SHA-256 |
|---|---|---|
| ELF | `reports/firmware/gcc/fv_fw.elf` | `946437a9a3ec9067c77bb6a50bc7428f8a5874011aaa0658e60438457f1f3867` |
| BIN (432,276 B, load address 0x08000000) | `reports/firmware/gcc/fv_fw.bin` | `d6b56640fd6d2987ec9c257d1fafcffcedc76a2d5ef6f7278da062cb1e14d4af` |
| MAP | `reports/firmware/gcc/fv_fw.map` | n/a |

FLASH 432,276 B (82.45 %), RAM 106,624 B incl. 8 KB stack reserve (81.35 %), CCM 53,248 B (81.25 %).

**Do not flash this image onto the delivered board.** It would overwrite the board's existing (hardware-tested)
firmware with one that stops after `fv_platform_init()` returns NOT_IMPLEMENTED: no output, no sensors, no camera.

## 3. Tools
| Tool | Windows | WSL |
|---|---|---|
| arm-none-eabi-gcc | not on PATH | ✅ 13.2.1 |
| arm-none-eabi-gdb / gdb-multiarch | ✗ | ✗ |
| STM32CubeProgrammer (`STM32_Programmer_CLI`) | ✗ (no `C:\Program Files\STMicroelectronics`) | ✗ |
| ST-LINK utility / gdbserver | ✗ | ✗ |
| OpenOCD, stlink-tools (`st-info`), pyOCD, dfu-util, J-Link | ✗ | ✗ |
| usbipd-win (USB passthrough to WSL) | ✗ | n/a |

## 4. Device detection (read-only)
* Present USB devices: VID 048D, 04F2 (integrated camera), 0BDA (Bluetooth), 3554 (input). **No VID 0483 (ST-LINK / STM32 DFU),
  1366 (J-Link), 0403/1A86/10C4/067B (USB-serial).**
* Windows has **never** enumerated an ST device on this PC (no non-present VID_0483 entries).
* COM3–COM8 are Bluetooth serial links, not the board.
* WSL: no `/dev/ttyACM*` / `/dev/ttyUSB*` (WSL can't see USB without usbipd anyway).

So either the board/probe is not plugged in, the cable is power-only, or a driver is missing. **No tool has confirmed the board.**

## 5. Programming methods for an STM32F407 (the board's actual method is unconfirmed)
Defined by the MCU (RM0090 / AN2606), not by this board. Which ones the board exposes must come from its schematic or vendor:
1. **SWD with an ST-LINK** (SWDIO/SWCLK/GND/3V3 header): preferred, and allows read-only identification.
2. System bootloader over USART1 (BOOT0 = 1).
3. System bootloader over USB DFU (OTG FS, BOOT0 = 1).

## 6. Blockers
1. Board/probe not visible to the PC (connection, cable or driver).
2. No flashing/debug tool installed.
3. Programming interface not documented.
4. No pin map. The board's existing tested firmware/project is the best source and is not in the repo.
5. Platform drivers + clock config not written, so the current image is not useful on the board.
6. The board's existing firmware has not been backed up (needed before any future flash; readout may be blocked by RDP level 1).

## 7. Next safe step (read-only)
1. Get from the board supplier: the schematic/pin map, the programming interface, and the source/binary of the firmware it was tested with.
2. Install one probe tool. Options:
   * STM32CubeProgrammer (st.com; the download asks for a myST account or e-mail), or
   * xPack OpenOCD (GitHub, no login).
   Plus the ST-LINK USB driver.
3. Connect the ST-LINK to SWD, then run identification only:
   `STM32_Programmer_CLI -l st-link` and `STM32_Programmer_CLI -c port=SWD mode=HOTPLUG` (connects without reset and reads the
   device ID, flash size and option bytes/RDP). No `-w`, `-e`, `-d` or `-ob` options.
4. Only after explicit approval: back up the existing flash (`-r32 0x08000000 0x80000 backup.bin`, read-only) if RDP allows it.

---
# Update 2026-10-17 (b): ST-LINK V2 check (read-only, nothing installed, target untouched)

| Check | Result (Windows PnP / filesystem / registry) |
|---|---|
| ST-LINK USB device | **Visible:** `USB\VID_0483&PID_3748\5&3B3FE15C&0&5`, "STM32 STLink" (PID 3748 = ST-LINK/V2) |
| ST-LINK driver | **Missing:** device status *Error*, `CM_PROB_FAILED_INSTALL`, no device class; no ST/ST-LINK package in the driver store (`pnputil /enum-drivers`) |
| STM32CubeProgrammer | **Not installed:** no `STM32_Programmer_CLI.exe` under Program Files, not on PATH, no uninstall entry |
| Target board | **Unknown.** A USB-enumerated probe says nothing about the SWD wiring or target power. Not tested. |

## Windows installation (manual, needs your approval and admin rights)
1. Download **STM32CubeProgrammer** for Windows 64-bit (product page "STM32CubeProg" on st.com). ST's download asks
   for a myST login or an e-mail address. You get `en.stm32cubeprg-win64-v<version>.zip`.
2. Unzip it and run `SetupSTM32CubeProgrammer_win64.exe` as administrator. **Keep the "ST-LINK driver" component selected**
   (the installer bundles it). Default path: `C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\`.
   * Driver only (alternative): **STSW-LINK009** from st.com. Unzip it and run `dpinst_amd64.exe` as administrator.
3. Unplug and replug the ST-LINK. In Device Manager → *Universal Serial Bus devices* it should show **STM32 STLink** with no
   warning. Check: `Get-PnpDevice -InstanceId 'USB\VID_0483&PID_3748*'` → Status `OK`.
4. If CubeProgrammer offers to **upgrade the ST-LINK firmware**, decline for now. That modifies the probe, and clone
   V2 probes can be bricked by it.

## Next safe step: read-only identification
* **Probe only (touches no target):**
  `& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -l st-link`
  This lists the probe serial number and firmware version.
* **Target identification (only after the ENTC team confirms the SWD wiring and power):**
  `STM32_Programmer_CLI.exe -c port=SWD freq=480 mode=HOTPLUG`
  HOTPLUG attaches without asserting reset. Expected output: device ID 0x413 (STM32F405/407), flash size, RDP level.
  Do not add `-w`, `-e`, `-d`, `-ob`, `-rst`, `-hardRst` or `-s`.
* Backup readout (`-r32 0x08000000 0x80000 backup.bin`) only with explicit approval, and only if RDP is level 0.

## Hardware information still required from the ENTC team
1. **SWD header pinout** on the board (SWDIO, SWCLK, GND, 3V3/VTref, NRST if present) and which ST-LINK V2 pins to use.
2. **Power:** is the board self-powered (supply and voltage)? Must the ST-LINK 3.3 V pin be left unconnected (to avoid
   back-powering), or only used as VTref?
3. Whether a debug attach to the running, tested firmware is acceptable, and whether reading back flash is permitted.
4. The **tested firmware**: source project (CubeMX `.ioc` if any) or binary, toolchain, and the RDP level that was set.
5. **Full pin map:**
   * OV2640: DCMI D0–D7, PCLK, HSYNC, VSYNC, XCLK source, SCCB SDA/SCL, PWDN, RESET.
   * TCS34725 and SSD1306 I2C bus and pins.
   * MQ135 and pH ADC channels, with the divider/amplifier values.
   * DHT22 GPIO.
   * UART for logs, and its baud rate.
   * LED and buzzer pins.
6. Clocks: HSE crystal frequency (e.g. 8 MHz?), LSE present?
7. BOOT0/BOOT1 strapping, and whether USART1 or USB DFU bootloader access is wired.

---
# Update 2026-10-17 (c): post-install check, not yet installed
Re-check (read-only): the ST-LINK/V2 `USB\VID_0483&PID_3748\5&3B3FE15C&0&5` is still *Error* / `CM_PROB_FAILED_INSTALL`.
There is no ST driver package in the driver store and no `STM32_Programmer_CLI.exe`. Probe enumeration is therefore **not run**.
The target was not touched.

After installing, run `powershell -ExecutionPolicy Bypass -File tools\firmware\stlink_probe_check.ps1`.
It is read-only: the PnP state, the CLI version and `STM32_Programmer_CLI -l st-link` (lists probes only, no `-c`, no target access).

---
# Update 2026-10-17 (d): verified after the user's installation (read-only)
Supersedes (c). Target NOT connected, NOT detected. Nothing flashed, erased, reset or changed. ST-LINK firmware not upgraded.

| Check | Verified result |
|---|---|
| STM32CubeProgrammer (registry) | `STM32CubeProgrammer` **2.23.0**, publisher STMicroelectronics (HKLM Uninstall); uninstaller in `C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\Uninstaller\` |
| CLI | **Present:** `C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe` (4,959,936 B). Not on PATH. A first recursive `Get-ChildItem` search missed it; the direct directory listing confirmed it. |
| `--version` | `STM32CubeProgrammer version: 2.23.0`, exit 0 |
| ST-LINK PnP | `USB\VID_0483&PID_3748\5&3B3FE15C&0&5` "STM32 STLink": **Status OK, Started, `CM_PROB_NONE`**, class USBDevice |
| Driver | `oem124.inf` = `stlink_dbg_winusb.inf`, STMicroelectronics, 2.2.0.0 (04/01/2021), "Best Ranked / Installed". Also in store: `stlink_bridge_winusb.inf`, `stlink_vcp.inf`, `stm32bootloader.inf` 1.3.0.0 |
| `STM32_Programmer_CLI -l st-link` | **1 probe:** SN `37FF71064E573436D7161343`, FW `V2J37S7`, Access Port Number 1, Board Name (empty); exit 0 |

**Interpretation:** the ST-LINK/V2 probe works with the official driver and CubeProgrammer. This says **nothing** about the
target: `-l` does not open SWD. The probe firmware (V2J37) is old; **do not upgrade** it (clone V2 probes can be bricked
by ST's updater; whether this probe is genuine is unconfirmed).

## Next safe action
Wait for the ENTC team to confirm the SWD wiring (SWDIO/SWCLK/GND/VTref, NRST) and the board power (self-powered? leave
ST-LINK 3.3 V unconnected?). Then, with your approval, run only:
`& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=480 mode=HOTPLUG`
That reads the device ID / flash size / RDP without reset. No `-w -e -d -ob -rst -hardRst -s`, and no firmware upgrade.

---
# Update 2026-10-17 (e): target identified over SWD (read-only HOTPLUG)
User-approved command (the ST-LINK was already wired by the user; wiring was not changed):
`STM32_Programmer_CLI.exe -c port=SWD freq=100 mode=HOTPLUG`, exit code 0.

| Field | Reported by STM32CubeProgrammer 2.23.0 |
|---|---|
| ST-LINK | SN 37FF71064E573436D7161343, FW V2J37S7 |
| Target voltage (VTref) | 3.34 V |
| SWD freq / connect mode | 100 kHz / Hot Plug |
| Reset mode | "Software reset". This is the CLI's configured reset method for later operations; no reset command was issued |
| **Device ID** | **0x413**, Revision ID Rev 2.0 |
| **Device name** | **STM32F405xx/F407xx/F415xx/F417xx** |
| **Flash (NVM) size** | **512 KBytes** (consistent with the "E" flash code of STM32F407VET6) |
| CPU / type | Cortex-M4 / MCU |
| System bootloader version | 0x31 |
| **Read protection (RDP)** | **Not reported** by this command (the connect output does not include option bytes) |

**Verified:** a real STM32F4 target in the F405/F407/F415/F417 family with 512 KB flash answers on SWD.
**Not verified:** that it is the F407 variant specifically (ID 0x413 is shared by the four parts; the package
marking VET6 has not been read by a tool), the RDP level, and the existing firmware contents.
No flash/erase/reset/option-byte change and no probe firmware upgrade were made.

Next read-only step (needs approval): `STM32_Programmer_CLI.exe -c port=SWD freq=100 mode=HOTPLUG -ob displ`. It **displays**
the option bytes, including the RDP level; `displ` writes nothing.

---
# Update 2026-10-17 (f): protection status + board-independent ML self-test image (NOT flashed)

## Target (read-only, verified by STM32CubeProgrammer 2.23.0, HOTPLUG 100 kHz)
Device ID 0x413 Rev 2.0, STM32F405xx/F407xx/F415xx/F417xx, 512 KB flash, VTref 3.34 V, BL 0x31.
`-ob displ` (display only): **RDP 0xAA = Level 0 (no protection)**, BOR off, WDG_SW = software, nRST_STOP/STDBY = no reset,
**WRP0–11 not active**. So the existing firmware can be read back for a backup.
The backup readout (`-u 0x08000000 0x80000 ...`) was **not performed**: the tool-permission policy blocked it. The user decides.

## Board information available in the repo
None: no schematic, `.ioc`, pin map, or ENTC firmware/source. So the camera, TCS34725, MQ135, pH, DHT22, SSD1306, UART,
LED and buzzer drivers **cannot be implemented without guessing pins**. They remain `FV_ERR_NOT_IMPLEMENTED`.

## Shortest safe route implemented: on-target ML self-test (board-independent)
* `platform/fv_clock_stm32f4.c`: HSI 16 MHz → PLL 168 MHz (M16 N336 P2 Q7), 5 WS + ART caches, APB1 42 / APB2 84 MHz,
  SysTick 1 ms, DWT cycle counter. Internal oscillator only, so it doesn't depend on the board crystal.
  Disassembly check: touches only RCC (0x40023800/04/08/40), FLASH_ACR (0x40023C00), PWR_CR (0x40007000) and core
  registers. **No GPIO register referenced; no platform/driver symbols linked.**
* `selftest/fv_selftest_core.c`, `selftest/fv_selftest_main.c`:
  * runs the frozen INT8 Model 1+3 graph on 3 stored test inputs embedded in flash, then image checks + output validation;
  * runs Model 2 on one synthetic vector;
  * measures cycles per inference and the stack high-water mark;
  * writes `g_fv_selftest` (288 B at **0x200001D8**, SRAM) and keeps a heartbeat counter running.
* Expected values are produced independently on the PC (TFLite reference kernels + Python post-processing / image checks / Model 2):
  `tools/firmware/gen_selftest_data.py` → `reports/firmware/selftest_expected.json` (guava, guava, apple; Model 2 MEDIUM).
* PC run of the same self-test logic (x86, real TFLM): **PASS**. All 3 inferences exact (max diff 0), result fields match,
  Model 2 probabilities match (`reports/firmware/selftest_host32.txt`).
* GCC image `reports/firmware/gcc/fv_selftest.{elf,bin,map}` (`FV_TARGET=selftest tools/firmware/build_gcc.sh`):
  FLASH 483,052 B (92.1 %), RAM 106,248 B, CCM 52 KB. BIN sha256 `0c503af648a7e6df1db701c9ab2c553c78bafd8b05f968e13230d771fc7cedea`.
* Readback (read-only): `python tools/firmware/read_selftest.py` runs `-c port=SWD freq=100 mode=HOTPLUG -r32 0x200001D8 288`
  and compares against the expectations.
* Tests: 92 passed (including the self-test source safety check, the host32 PASS record and the readback parser).

## Proposed sequence (each step needs the user's explicit approval)
1. **Backup (read-only):** `STM32_Programmer_CLI -c port=SWD freq=100 mode=HOTPLUG -u 0x08000000 0x80000 backups\board_original_firmware\board_flash_0x08000000_512K.bin`
2. **Flash the self-test** (erases the needed sectors and **replaces the ENTC firmware** until it is restored):
   `STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_selftest.elf -v -rst`
3. **Read results:** `python tools\firmware\read_selftest.py`
4. **Restore the ENTC firmware:** `STM32_Programmer_CLI -c port=SWD freq=1000 -d backups\...\board_flash_0x08000000_512K.bin 0x08000000 -v -rst`

While the self-test runs, no GPIO is configured: board pins stay as after reset (inputs), the same as the moment
after any reset. Camera/sensors/OLED will be idle.

---
# Update 2026-10-17 (g): original firmware backed up (read-only)
Command: `STM32_Programmer_CLI -c port=SWD freq=100 mode=HOTPLUG -u 0x08000000 0x80000 <file>`. Result: "Data read successfully",
1:06.7 min, exit 0. Board not flashed, erased, reset or changed.
| Item | Value |
|---|---|
| File | `D:\smart-pesticide-ml\backups\board_original_firmware\board_flash_0x08000000_512K.bin` (marked read-only) |
| Size | 524,288 B (= 512 KB) |
| SHA-256 | `1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c` (also in `.sha256` next to it) |
| Content check | Initial SP 0x20020000, reset vector 0x08003891 (Thumb, in flash) → valid vector table. 34,466 non-0xFF bytes; last programmed byte at offset 0x8837 (~34 KB image) |
Restore (only with approval): `STM32_Programmer_CLI -c port=SWD freq=1000 -d backups\board_original_firmware\board_flash_0x08000000_512K.bin 0x08000000 -v -rst`

---
# Update 2026-10-17 (h): ML self-test FLASHED (user-approved) and PASSED on the STM32
Flashed: `STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_selftest.elf -v -rst`. Connect Normal, SWD 950 kHz,
download 16.2 s, **"Download verified successfully"** (7.9 s), software reset, exit 0. ELF sha256 `71253b93…1988` (= latest build).
Option bytes and ST-LINK firmware unchanged. **The ENTC firmware is currently replaced** (backup: section (g)).

Readback `python tools/firmware/read_selftest.py` (SWD hot-plug `-r32 0x200001D8 288`), exit 0. `reports/firmware/selftest_target_readback*.json`:
| Item | On-target result |
|---|---|
| Done / PASS | magic 0xF7A51E57, **pass = 1** |
| Clock | PLL from HSI, SWS = 2 (PLL), clock_status 0. Heartbeat vs PC wall clock: 694 ms / 690 ms (ratio 1.006) → 168 MHz confirmed within read jitter |
| TFLM init | OK; arena used **148,896 B** (host32: 149,120 B) in persistent 53,248 (CCM) + non-persistent 97,280 (SRAM) |
| Raw int8 outputs (3 × 40) | **identical to PC TFLite reference** (0 mismatches, max diff 0) |
| Output validation | 0 mismatches. Fruit guava / guava / apple; quality PREDICTED (Average) / UNCERTAIN (R1) / UNCERTAIN (R1) |
| Image checks | flags 0 / 0 / 0 (as expected) |
| Model 2 (synthetic vector) | MEDIUM, p = 0.069783 / 0.644367 / 0.285850 (expected 0.069783 / 0.644367 / 0.285850) |
| Inference cycles | 60,047,336 / 60,058,939 / 60,068,830 → **≈357.4–357.6 ms per inference @168 MHz** |
| Stack high-water | **1,120 B** (8 KB reserved) |
**Not tested by this self-test:** camera, TCS34725, MQ135, pH, DHT22, OLED, UART, LEDs/buzzer, and any pesticide detection. Inputs were
stored test images, not camera captures, and the Model 2 vector is synthetic.

---
# Update 2026-10-17 (i): ENTC original firmware RESTORED (user-approved)
Pre-checks: backup 524,288 B, SHA-256 `1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c` = saved checksum (OK);
target re-identified read-only (ID 0x413, STM32F405/F407/F415/F417, 512 KB, 3.34 V).
Command: `STM32_Programmer_CLI -c port=SWD freq=1000 -d backups\board_original_firmware\board_flash_0x08000000_512K.bin 0x08000000 -v -rst`
Result: 512.00 KB download complete (16.3 s), **"Download verified successfully"** (8.6 s), "MCU Reset / Software reset is performed",
exit 0. Log: `reports/firmware/restore_original_firmware_log.txt`. Option bytes and ST-LINK firmware unchanged.
Flash content now equals the backup (verified by the tool). **Whether the original application runs correctly has NOT been observed or tested.**
Self-test artifacts kept: `reports/firmware/gcc/fv_selftest.*`, `selftest_target_readback*.json`, `selftest_clock_check.json`, `selftest_expected.json`.

---
# Update 2026-10-17 (j)
Observation checklist, static hints from the restored firmware and integration gaps: see `docs/ORIGINAL_FIRMWARE_OBSERVATION.md`. No board access.

---
# Update 2026-10-17 (k)
Static analysis of a scratch copy of the ENTC backup and the camera to ML plan: `docs/CAMERA_ML_INTEGRATION_PLAN.md`. Backup unchanged (sha256 OK). No board access.

---
# Update 2026-10-17 (l)
P0 of `docs/CAMERA_ML_INTEGRATION_PLAN.md` done on the host (103 tests pass). No board access. Backup, frozen models and the verified `fv_selftest.elf` are unchanged.

---
# Update 2026-10-17 (m)
P1 prepared (read-only live frame read): `docs/P1_LIVE_FRAME_READ_PLAN.md`, `tools/firmware/capture_live_frame.py` (dry-run default). NOT executed; no SWD command run.

---
# Update 2026-10-17 (n): Phase B fresh backup (user-approved, read-only)
`STM32_Programmer_CLI -c port=SWD freq=100 mode=HOTPLUG -u 0x08000000 0x80000 backups\board_original_firmware\pre_fv_app_20261017T102117Z.bin`
gave "Data read successfully" (1:06.7), exit 0, VTref 3.37 V, ID 0x413. File: 524,288 B, sha256
`1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c`, **byte-identical** to the original backup (the ENTC flash has not
changed since restore). Marked read-only, with a `.sha256` file next to it. No flash, erase, reset, halt or write. fv_app.elf NOT flashed.

---
# Update 2026-10-17 (o): Phase C, fv_app.elf FLASHED (user-approved) and running on the board
Pre-checks: ELF sha256 b9a394b2…89f7; original backup OK; fresh backup == original.
`STM32_Programmer_CLI -c port=SWD freq=1000 -d reports\firmware\gcc\fv_app.elf -v -rst` gave "File download complete" (15.2 s),
"Download verified successfully" (7.2 s), software reset, exit 0. Log: `reports/firmware/flash_fv_app_log.txt`.
Diagnostics (read-only `read_diag.py --execute`, twice; `reports/firmware/diag_read_{1,2}.json`):
* Running: uptime 6.6 s → 20.0 s, cycles 3 → 8 (~2.7 s/cycle), every cycle status OK. clock_status 0 (PLL 168 MHz).
* OLED: init ACKed (oled_status 0); **visual content not yet confirmed by a person**.
* TCS34725: ok, C/R/G/B ≈ 1695/312/570/711 (stable).
* OV2640: PID 0x26, VER 0x42, all 179 register writes ACKed, PCLK div 0x0C; **captures 38,400 B every cycle** (status 0).
* **On-target camera → frozen INT8 model:** fruit apple, 0.852 → 0.902; condition fresh 0.660 → 0.703. R1 withholds quality/shelf
  (below 0.976). Image flags: aspect warning only. Model predictions, not validated results.
* DHT22: **dht_status -1 (no response)** → temperature/RH missing. Not yet diagnosed (start-pulse length, pin, or pull-up).
* ADC raw (mapping unknown, not reported as sensor values): PA2/IN2 ≈ 2040–2062, PA3/IN3 ≈ 349–368.
* Model 2 risk: UNAVAILABLE (missing MQ135/pH/DHT; no calibration), as designed. PB14: no alert occurred, so it stayed off.
Original backup untouched (sha256 OK). The board now runs fv_app (the ENTC firmware is replaced; restore command in PROJECT_HANDOFF.md §6).

---
# Update 2026-10-17 (p): pH sensor check (read-only; no flash/reset/wiring/potentiometer change)
pH OUT is on **PA2 or PA3; which one is NOT determinable** from the ENTC code. Both are configured as ADC1 analog inputs (IN2/IN3)
and read every cycle (8-sample average), but published only as raw values in g_fv_diag. pH is disabled for two independent reasons:
unknown channel mapping (FV_ADC_CH_PH = UNKNOWN) and no calibration profile (has_ph is never set without calibration).
Live raw values (read_diag.py, uptime ~965 s, cycles 361–362; `reports/firmware/diag_ph_check_{1,2,3}.json`):
PA2/IN2 = 2381–2382 (≈1.92 V nominal at 3.3 V ref), PA3/IN3 = 396–449 (≈0.32–0.36 V nominal). Voltages are nominal: VREF is not measured.

---
# Update 2026-10-17 (q): fv_app_v2 FLASHED (user-approved) and running
Pre-check: v2 ELF sha256 544c99b6…, backup OK, no other ST-LINK user. `-c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v2.elf -v -rst`
gave "File download complete" (429.58 KB, 15.2 s), "Download verified successfully" (7.2 s), software reset, exit 0
(log `reports/firmware/flash_fv_app_v2_log.txt`). Diagnostics read-only, twice (`reports/firmware/diag_v2_read_{1,2}.json`):
* Running: uptime 25.5 s → 36.2 s, cycles 10 → 14; clock_status 0; capture status 0, 38,400 B; OV2640 0x26/0x42, tables OK.
* DHT22: **dht_status −5 (FV_DHT_ERR_RANGE)**, previously −1 (no response). The sensor now answers and the checksum passes, but the
  decoded values are outside the DHT22/AM2302 range. Cause not yet identified (e.g. a DHT11-format sensor, or bit timing); raw
  bytes are not in diagnostics. Temperature/RH remain missing.
* pH (PA2, ENTC calibration): raw 2378–2381, Vf 1.919 V, **pH 8.91** (ENTC formula; not a validated measurement).
* MQ135 (PA3): raw 406–413 counts, warm-up not complete (uptime < 120 s).
* TCS34725 ok: C/R/G/B ≈ 4411/785/1580/1782. OLED init acknowledged (oled_status 0); visual check pending.
* Model output: fruit guava 0.883–0.898, fresh 0.992, R1 → quality/shelf UNCERTAIN (current scene unknown).
* Sensor errors 0x9000 (temperature + RH missing), warning 0x4 (MQ warm-up), OOD 0x2e → pesticide risk **UNAVAILABLE** (reason: invalid inputs).

---
# Update 2026-10-17 (r): fv_app_v3 FLASHED (user-approved), DHT11 now reads on hardware
Pre-check: v3 ELF sha256 7c87e76f…, original backup OK, no other ST-LINK user. `-c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v3.elf -v -rst`
gave "File download complete" (429.74 KB, 14.8 s), "Download verified successfully" (7.5 s), software reset, exit 0
(log `reports/firmware/flash_fv_app_v3_log.txt`). Diagnostics read-only, sequential (`reports/firmware/diag_v3_read_{1,2}.json`):
* Running: uptime 25.5 → 36.2 s, cycles 10 → 14, clock 0, every cycle status OK.
* **DHT11: dht_status 0, T = 32 °C, RH = 60 %** (integer, DHT11 format; stable across reads). Sensor errors now 0x0.
* Camera: capture status 0, 38,400 B; OV2640 0x26/0x42; tables OK. Model: guava 0.926–0.945, fresh 0.930–0.941 (R1 → quality/shelf UNCERTAIN).
* pH (PA2, ENTC calibration): raw 2329–2330, 1.878 V, pH 9.13. MQ135 (PA3): raw 306–311, warm-up not complete (uptime < 120 s).
* TCS34725 ok (C/R/G/B ≈ 5935/967/2061/2571). OLED init acknowledged (visual check by user).
* Pesticide risk: **UNCERTAIN**, reasons 0x1C = uncalibrated (no device→Model 2 calibration) + out of synthetic training range + MQ warm-up. No pesticide claim.

---
# Update 2026-10-17 (s): OLED bottom rows, cause found and v4 built (NOT flashed yet)
Read-only SWD read of the OLED framebuffer on v3 (`reports/firmware/oled_fb_read_v3.txt`): all 8 rows were rendered correctly
(rows 5–7: "pH9.14 ENTC MQ300", "T33.0C RH55%", "*proto, not lab test"), but the panel did not show pages 5–7. v3 flushed with a
horizontal-mode window plus 32 × 32 B transfers; ENTC (@0x080031A0) writes per page (0xB0+p, 0x00, 0x10, then 128 B).
v4 changes only `fv_ssd1306_flush` (ENTC per-page method; continues past a failed page) and stores each flush result in the existing
`g_fv_diag.oled_status` (layout unchanged, 436 B). Build `fv_app_v4.{elf,bin,map}`: FLASH 440,084 B, RAM 108,176 B, CCM 53,248 B;
placement checks pass; model bytes = frozen model. Tests: 150 passed; driver checks 61/61.

---
# Update 2026-10-17 (t): fv_app_v4 FLASHED (user-approved) and running
`-c port=SWD freq=1000 -d reports\firmware\gcc\fv_app_v4.elf -v -rst` gave "File download complete" (429.77 KB, 14.7 s),
"Download verified successfully" (7.1 s), software reset, exit 0 (log `reports/firmware/flash_fv_app_v4_log.txt`). ELF sha256 b18b2a29….
Diagnostics (read-only, sequential; `reports/firmware/diag_v4_read_{1,2}.json`): uptime 22.8 → 33.5 s, cycles 9 → 13, clock 0,
**oled_status 0 (all 8 pages written every cycle)**, TCS ok, OV2640 ok, capture 38,400 B, model guava 0.914–0.945 / fresh 0.895–0.926,
DHT11 ok 33 °C / 54 %, pH 9.25 (ENTC calibration), MQ135 raw 302–307 (warming), sensor errors 0, risk UNCERTAIN (0x1C).
Physical OLED check of the bottom three rows: pending user confirmation.

---
# Update 2026-10-17 (u): empty-scene "guava" bug, presence gate in fv_app_v5 (built, NOT flashed)
Cause: the frozen fruit model has 5 classes and no background class, so it always names a fruit. R1 (conf < 0.976) withheld
quality/shelf but the fruit label stayed PREDICTED. Measured: uniform grey frame → guava 0.992, blurred featureless scene → 0.992
(above R1, so confidence alone is insufficient); real empty camera frame → guava 0.805, detail 12.1.
Fix (no retraining; model bytes unchanged): `app/fv_presence.{h,c}` + `fv_image_detail()` (Laplacian variance of the 80x80 input,
computed before inference). A fruit is shown only if detail ≥ 43.96 (0.5 × 0.5th percentile of VAL in camera format) AND
confidence ≥ 0.976; otherwise fruit/condition/grade/shelf → UNCERTAIN, OLED "Fruit:NOFRUIT/UNKNOWN", flag FV_CONS_NO_FRUIT (0x10).
Diagnostics v3 (444 B) adds img_detail_x10 and fruit_present.
Evaluation (`reports/firmware/presence_gate_eval.json`, `tools/firmware/calibrate_presence_gate.py`):
* synthetic empty scenes 0/5 shown; real frames 0/3 shown (empty scene correct; **both real apple frames rejected = false rejection**,
  focused apple: detail 84 OK but conf 0.852 < 0.976);
* public TEST images in camera format: fruit shown 48.9 %, 96.4 % correct when shown; blurred 7.2 %; dark ×0.25 21.9 %.
* host32 full C path (`reports/firmware/presence_gate_host32_e2e.txt`): 3 real frames → UNCERTAIN (cons 0x11); uniform frame → existing image reject.
Missing evidence: no real non-fruit object photos; only 3 real device frames; no device frames of banana/guava/tomato/brinjal.
Build `fv_app_v5.{elf,bin,map}`: FLASH 441,108 B, RAM 108,192 B, CCM 53,248 B; placement checks pass; model = frozen. Tests 158 passed.

---
# Update 2026-10-17 (v): banana shown as "guava 0.945": investigation (PC-only; nothing flashed)
* Label mapping verified: training metadata, Python and C all use 0 apple, 1 banana, 2 guava, 3 tomato, 4 brinjal; head index
  mapping already bit-exact with TFLite (20/20 + e2e). Not a mapping bug.
* Preprocessing hypotheses tested on public banana images through the exact device path (`reports/firmware/banana_guava_investigation.json`):
  clean 100 % banana, R/B swapped 93 %, blur 100 %, dark ×0.3 100 %, washed-out/desaturated 97 %; **banana small in the frame: 20 %
  banana / 40 % guava**. Camera chroma (7.5–11) is inside the training range (median 11.6).
* The banana reading (guava 0.945 / fresh) equals the device's EMPTY-scene output on v4 (guava 0.91–0.95 / fresh 0.90–0.93), and
  2 of 3 real frames are defocused (detail 12). Most consistent explanation: the model is not seeing a usable banana in its centre crop
  (framing/size/focus) and falls back to its "background" class guava; domain shift of the real camera vs public photos. NOT proven:
  the actual banana frame cannot be read from fv_app (input overwritten by inference).
* Built diagnostic firmware `fv_app_v6_diag` (v5 + `-DFV_DIAG_CAPTURE`): keeps a copy of the exact 80×80 model input and raw
  outputs in `g_fv_capture` for read-only SWD readout with `tools/firmware/read_capture.py` (compares device vs Python bit-exactly and
  saves a PNG). FLASH 441,220 B, RAM 127,456 B (3,616 B free + 8 KB stack reserve), placement checks pass, model bytes = frozen. Tests 160 passed.

---
# Update 2026-10-17 (w): diagnostic captures, camera focus root cause, final state

**Flashes (each approved separately):**
* `fv_app_v6_diag` was flashed and verified.
* `fv_app_v8_diag` (sha256 dbe1ef5a…, bin dd1e138e…) was flashed and verified (`reports/firmware/flash_fv_app_v8_diag_log.txt`).
* `fv_app_v7_diag` (write-once snapshot) was built and never flashed.
* No other firmware was written. v1–v8 and both ENTC backups are intact (hashes re-checked).

**Capture reader:**
* The v6 rolling capture needs a consistent read. `read_capture.py` now reads the block and its header in ONE CLI session (4 MHz) and retries up to 5 times, accepting only an even, unchanged seq. Torn reads are rejected (3 early rejections are recorded in the session); no image was saved from them.
* v8 rolling mode also fixes the seq parity when a staged input is not committed.

**Pipeline verified:**
* RGB565 big-endian (ENTC statistics match).
* Channel order correct (yellow banana, blue object).
* Device output == Python, bit-exact, in all saved captures.
* The preview renders by nearest-neighbour.
* The register sequence is identical to ENTC: 179 writes ACKed; the v8 tune #1 rewrote the ENTC values unchanged.
* Details: `reports/firmware/camera_blur_investigation.md`.

**Blur root cause: optical/mechanical (focus and position), not configuration.**
* Same firmware and same registers: detail 35 (#11) and 351 (#12) 10 s apart.
* After the user restored the sharp camera position, 4 stable captures on v8_diag gave detail 446.8 / 445.0 / 448.2 / 452.7, banana 0.988 / 0.992 / 0.996 / 0.996, fruit_present 1 (`reports/firmware/device_capture/20261017T144125Z_*`).
* This also explains the earlier "banana → guava": the model was seeing a defocused/background scene.

**Final read-only diagnostics on v8_diag** (`reports/firmware/diag_final_v8_read.json`):
* Uptime 1,907 s, 679 cycles.
* clock/OLED/camera status 0, capture 38,400 B.
* Banana 0.996, detail 468.6, risk UNCERTAIN.
* DHT11 33.0 °C / 51 %.
* pH 9.37 (formula only), MQ135 raw 319 (warmed).

**Live preview:** `tools/firmware/live_preview.py --firmware diag` shows the 80×80 model input on the v6/v7/v8 diag builds. The ENTC mode is unchanged.

**Live OV2640 tuning** (`tools/firmware/cam_tune.py`, v8 only):
* It writes only the 52 B `g_fv_cam_tune` RAM block; nothing goes to flash and there is no reset.
* Only the baseline (all ENTC values) was applied. No non-default setting was tested, because focus, not configuration, was the cause.

**Recommended final firmware:** `fv_app_v5` (see `docs/PROJECT_HANDOFF.md` §0). Flashing it needs approval.

**Tests:** 172 passed.

**v5 source equivalence:** a rebuild from the current source is byte-identical to the archived `fv_app_v5.bin` (a48db157…; `reports/firmware/fv_app_v5_source_equivalence.json`).

**OLED (user's physical photo, v8_diag, banana):** all 8 rows were visible (`Fruit:banana 0.996` … `*proto, not lab test`).

**Unresolved:**
* PB14 role (LED or buzzer).
* OLED rows on v5 (visible on v8_diag; same display code).
* Real-camera results for apple/guava/tomato/brinjal.
* pH/MQ135 calibration.
* Pesticide validation.
