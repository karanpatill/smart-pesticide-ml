# Final demo checklist: Smart Pesticide Residue Detection System

Details and evidence are in `docs/PROJECT_HANDOFF.md` §0.

## 1. Before the demo
- [ ] Camera is fixed in the focused position (holder or tape). **Do not turn the lens.**
  - Proof that the position is right: 4 banana captures with detail ~450 and banana 0.988–0.996.
- [ ] Even, bright light. Plain background. The fruit is about 20 cm away, centred, and fills about half of the view.
  - The model sees only the centre square of the frame.
- [ ] Laptop setup:
  - Open PowerShell in `D:\smart-pesticide-ml`.
  - Connect the ST-LINK.
  - Close any other STM32CubeProgrammer or preview window. Only one SWD tool may run at a time.
- [ ] Power the board and wait **2 minutes** (MQ135 warm-up).

## 2. Firmware (flash ONLY after explicit approval)
**Recommended:** `reports\firmware\gcc\fv_app_v5.elf`
- sha256 `2a72f1b9b9e04e2b…`
- bin `a48db15766c2172a…`, 441,108 B

```
& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\reports\firmware\gcc\fv_app_v5.elf" -v -rst
```
- Expect "Download verified successfully".
- **Fallback:** `fv_app_v4.elf`. It is proven on the board but has no presence gate.
- **Camera-check build:** `fv_app_v8_diag.elf`. It provides the live preview.
- **Candidate build (integrated background head, NOT flashed):** `fv_app_candidate.elf` (sha256 `6a2ae908…`, bin 446,980 B `29081e60…`).
- **Flash status (2026-10-17):** **`fv_app_v5` is flashed and verified** ("Download verified successfully", `reports\firmware\flash_fv_app_v5_log.txt`).
  - SWD diagnostics after the flash: banana 0.996, detail ~445, fruit_present 1, all statuses 0.
  - Always use the ELF of the firmware that is actually running: now `fv_app_v5.elf`.

## 3. Verify the camera and the OLED
1. Read the diagnostics:
   `.venv\Scripts\python tools\firmware\read_diag.py --elf reports\firmware\gcc\fv_app_v5.elf --execute`
   - Expect `clock_status` 0, `cycles` increasing, `oled_status` 0, `cam_status` 0, `last_capture_bytes` 38400 and `dht_status` 0.
   - With the banana in place, expect `img_detail_x10` above 440 and `fruit_present` 1.
2. Check the OLED. Reference photo (v8_diag, banana in the fixed position): `Fruit:banana 0.996` / `Cond:fresh` / `Grade:Good` / `Shelf:3-6d Fresh` / `Risk:UNCERTAIN` / `pH9.37 ENTC MQ324` / `T33.0C RH51%` / `*proto, not lab test`.
   - On v5, confirm that all 8 rows are visible.
   - **PB14** (LED or buzzer, still unconfirmed):
     - It pulses 3× (100 ms) only on an "alert": an image rejected by the image check, or a PREDICTED HIGH risk. The second never happens, because risk is always UNCERTAIN/UNAVAILABLE.
     - In a normal demo it stays off. If you see it pulse, note it. Do not change anything to provoke it.
   - UNKNOWN/NOFRUIT with a fruit present: see §7.
3. Only if the picture must be seen:
   `.venv\Scripts\python tools\firmware\live_preview.py --firmware diag`
   - Works only while **v8_diag** runs. v4/v5 keep no image copy, and switching firmware needs an approved flash.
   - Only **one SWD tool at a time**: close the preview before `read_diag.py`, `read_capture.py` or STM32CubeProgrammer.

## 4. Demo sequence (3–5 min)
1. **(30 s) Architecture:**
   - OV2640 → STM32F407 → INT8 model on the chip (CMSIS-NN, ~2.7 s per cycle).
   - Sensors: TCS34725, MQ135, pH, DHT11. Output on the OLED.
2. **(60 s) Banana in the fixed position:**
   - Expected, based on the 4 confirmed banana captures: the OLED shows banana with its condition.
   - Explain the presence gate: a fruit is shown only if the image is sharp AND confidence ≥ 0.976.
   - (Optional) Other fruits are **not validated** on this camera. They may show UNKNOWN. That is the conservative gate, not a failure; do not promise them.
3. **(30 s) Remove the fruit:**
   - The OLED shows `NOFRUIT/UNKNOWN`. The system refuses to guess.
4. **(60 s) Sensors:**
   - T/RH row (DHT11, whole numbers).
   - pH probe in water.
   - MQ135 raw value reacting to vapour.
   - Colour sensor.
5. **(30 s) Risk row:** UNCERTAIN/UNAVAILABLE (see §5).
6. **(optional) Laptop:** `read_diag.py` output. The STM32 and the PC give bit-exact identical model outputs.

## 5. What to say about pesticide risk
> "The pesticide-risk model is a prototype trained on synthetic data. We have no laboratory residue measurements to validate it, so the device deliberately shows UNCERTAIN/UNAVAILABLE. MQ135 gives raw gas counts, not pesticide ppm. pH uses an uncalibrated formula. The colour sensor alone cannot detect residue. This system does **not** certify fruit as residue-free."

- This device has **no validated pesticide-residue detection**. It gives **no ppm or concentration output of any kind**.
- There is **no basis to certify any fruit as pesticide-free**. Validation would need reference samples, accredited lab measurements (e.g. LC-MS/MS, GC-MS), sensor calibration and independent testing (`docs/PROJECT_HANDOFF.md` §0).

## 6. Limitations and rollback
**Limitations:**
- **Fruit model:**
  - Real-camera success is confirmed for **banana only**.
  - Apple, guava, tomato and brinjal are not validated on this camera.
  - There is no "not a fruit" class.
  - A real fruit can be shown as UNKNOWN.
- **Sensors:**
  - DHT11 gives whole numbers only.
  - MQ135 needs warm-up and is not in ppm.
  - pH needs calibration with buffers (pH 4/7/10).
- **Display:** there is no UART; results come from the OLED and SWD diagnostics.

**Rollback (each needs explicit approval; never run automatically):**
- **v4 fallback:**
  `& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\reports\firmware\gcc\fv_app_v4.elf" -v -rst`
- **Original ENTC firmware:**
  `& "C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe" -c port=SWD freq=1000 -d "D:\smart-pesticide-ml\backups\board_original_firmware\board_flash_0x08000000_512K.bin" 0x08000000 -v -rst`
  - sha256 `1590cd4e…601c`.

**Final handover snapshot:** the newest `backups\final_handover_<timestamp>\` folder, with `MANIFEST.sha256` and `MANIFEST.json`.
- The 20261017T145003Z snapshot is kept.
- A newer one adds the final docs and the v5 source-equivalence result.

## 7. Troubleshooting (safe steps only)
| Symptom | Safe action |
|---|---|
| UNKNOWN/NOFRUIT with a fruit present | Expected when the image is not sharp enough (detail < 43.96) or confidence < 0.976. Put the fruit back in the confirmed position: centred, ~20 cm, filling about half of the view, even light. Check that the camera holder has not moved. **Do not turn the lens at random, and do not change thresholds or firmware.** |
| Poor framing (fruit at the edge, too small) | The model sees only the centre square. Move the **fruit**, not the lens. To see the image, `live_preview.py --firmware diag` works only on v8_diag (switching = an approved flash). |
| Sensor row missing or no value | Run `read_diag.py` with the running ELF: `dht_status`, `tcs_status`, `mq135_warmed` (wait 120 s), `ph_x100`. A value is never invented when it is missing. Check the wiring only with the power **off**. No pin or calibration changes. |
| CLI cannot connect / preview "skipped" | Close all other SWD tools. Check the ST-LINK cable and power. Use the `--elf`/`--firmware` that matches the running firmware. |
