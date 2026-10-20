# Quick Start & Demonstration Guide — Smart Pesticide System
**Version:** Handover Candidate (2026-10-18)

---

## 1. Hardware Setup

1. **Board:** STM32F407VET6 "Black Board"
2. **Camera:** OV2640 DVP module mounted to camera header
3. **Display:** SSD1306 0.96" I2C OLED (128x64) connected to I2C1 (PB8=SCL, PB9=SDA)
4. **Debug/Flash:** ST-LINK V2 SWD header (GND, SWCLK, SWDIO, 3V3)
5. **Sensors:**
   - DHT22: Temperature/Humidity on PA1
   - MQ135: Analog output on PC1 (ADC1_IN11)
   - pH Sensor: Analog output on PA4 (ADC1_IN4)
   - TCS34725: Color sensor on I2C2 (PB10=SCL, PB11=SDA)

---

## 2. Reading Live Diagnostics via SWD

To read live telemetry and inference state from the microcontroller without interrupting execution:

```powershell
# In PowerShell at project root:
.venv\Scripts\python tools\firmware\read_diag.py --elf handover_final_20261018\firmware\fv_app_candidate.elf --execute
```

This returns:
- Fruit classification and confidence (`fruit`, `fruit_conf_pm`, `fruit_st`)
- Presence verification status (`fruit_present`)
- Quality grade and shelf life
- Sensor values (pH, MQ135, Temp, Humidity, TCS RGB)
- 8-row OLED text buffer dump
- UART telemetry line

---

## 3. Demonstration Procedure (Recommended Flow)

### Step 1: Empty Scene (Rejection Baseline)
- Aim camera at empty table / wall.
- Observe OLED:
  ```text
  Fruit:NOFRUIT/UNKNOWN
  Cond:UNCERTAIN
  Grade:UNCERTAIN
  Shelf:UNCERTAIN
  Risk:UNCERTAIN
  pH9.28 ENTC MQ...
  T33.0C RH50%
  ```
- **Talking Point:** Explain that the system employs a dual-stage presence filter (background-rejection neural head + laplacian edge-detail gate) that refuses to guess when no fruit is presented.

### Step 2: Banana Classification (Positive Verification)
- Place a fresh banana 10–15 cm in front of the lens in good light.
- Observe OLED:
  ```text
  Fruit:banana 0.996
  Cond:fresh
  Grade:Good
  Shelf:3-6d Fresh
  Risk:UNCERTAIN
  pH9.28 ENTC MQ...
  T33.0C RH50%
  ```
- **Talking Point:** Model inference runs fully on-device on Cortex-M4 via TensorFlow Lite for Microcontrollers (TFLM). Inference latency is ~120 ms, utilizing CMSIS-NN INT8 SIMD kernels.

### Step 3: Apple / Guava Demonstration (Conservative Safety Behavior)
- Place Apple or Guava in front of the lens.
- The system will report `Fruit:NOFRUIT/UNKNOWN`.
- **Talking Point:** Explain the honest engineering principle implemented: rather than outputting an erroneous fruit with low or false confidence due to OV2640 sensor domain shift, the strict 0.976 confidence gate suppresses the misclassification and protects downstream logic.

---

## 4. Running Regression Tests

To verify software parity and host inference models:

```powershell
.venv\Scripts\python -m pytest tests -v
```
All 180 tests should report `PASSED`.

---

## 5. Firmware Flashing Procedure (If Approved)

To program the board via ST-LINK CLI:

```powershell
STM32_Programmer_CLI -c port=SWD freq=4000 -d handover_final_20261018\firmware\fv_app_candidate.bin 0x08000000 -v -rst
```

To rollback to original manufacturer ENTC firmware:

```powershell
STM32_Programmer_CLI -c port=SWD freq=4000 -d handover_final_20261018\models\original_entc_ref\board_flash_0x08000000_512K.bin 0x08000000 -v -rst
```
