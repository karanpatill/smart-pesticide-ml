# Smart Pesticide Residue Detection System — Final Handover Package
**Date:** 2026-10-18  
**Deadline:** 2026-10-19  
**Board:** STM32F407VET6 (512 KB Flash, 128 KB SRAM1, 64 KB CCMRAM)  
**Firmware version on board at handover:** Candidate (presence-gate enabled, footer removed in source)

---

## 1. Package Structure

```
handover_final_20261018/
├── HANDOVER_README.md              ← This file
├── KNOWN_LIMITATIONS.md            ← Required reading before demo
├── QUICK_START.md                  ← Setup, operation, and demo guide
├── PER_CLASS_EVALUATION.md         ← All 5 classes: accuracy, hardware results
├── firmware/
│   ├── fv_app_candidate.elf        ← Currently flashed candidate firmware (ELF w/ debug symbols)
│   ├── fv_app_candidate.bin        ← Binary for reflashing
│   ├── fv_app_candidate.map        ← Linker map (memory layout)
│   ├── fv_app_candidate_build_report.json  ← Section sizes, checks
│   ├── fv_app_v5_fallback.elf      ← V5 stable fallback (no presence gate)
│   └── fv_app_v5_fallback.bin
├── models/
│   ├── presence_int8_20261017T153321Z/   ← Deployed INT8 TFLite model
│   │   ├── combined_presence_int8.tflite
│   │   ├── README.json
│   │   └── parity_fixture/              ← 40 golden input/output vectors
│   └── original_entc_ref/
│       └── board_flash_0x08000000_512K.bin  ← Original ENTC firmware backup
├── reports/
│   ├── diag_empty_scene.json       ← Physical hardware: empty scene
│   ├── diag_banana.json            ← Physical hardware: banana (PASS)
│   ├── diag_apple.json             ← Physical hardware: apple (rejected by gate)
│   ├── diag_guava.json             ← Physical hardware: guava (rejected by gate)
│   └── APPLE_GUAVA_HARDWARE_AUDIT_REPORT.md  ← Root cause analysis
├── docs/
│   ├── SENSOR_CALIBRATION_PROTOCOL.md
│   ├── BOARD_BRINGUP_AUDIT.md
│   ├── BOARD_PIN_MAP_EVIDENCE.md
│   ├── PRESENCE_GATE_DECISION.md
│   ├── PROJECT_HANDOFF.md
│   └── FINAL_DEMO_CHECKLIST.md
└── tests/
    └── test_report.txt             ← Full pytest output (180 passed)
```

---

## 2. Firmware Checksums

| File | SHA-256 |
|------|---------|
| `fv_app_candidate.elf` | `01d0028711b0d1cd9135ed4071fb1b9e59bc699abff6580b695e1a82b6be3989` |
| `fv_app_candidate.bin` | `8f4813096504266db9f4507bf70b4b05601984f2e04510c746ccf1fd4fc3264a` |
| `combined_presence_int8.tflite` | `612f2e5586f0a4e2f2d7f7227e7cb6576cde1327f1a98453baec575f95e59300` |
| `board_flash_0x08000000_512K.bin` (original ENTC) | `1590cd4e57f3b6b60d48eeefa28b4f502e057591890221fa4ca3d2b1b417601c` |

**Candidate binary size:** 446,980 bytes (436 KB)  
**Flash budget:** 512 KB — **77,332 bytes remaining (15%)**

---

## 3. Memory Layout Summary

| Region | Used | Free | Total |
|--------|------|------|-------|
| Flash | 446,956 B (437 KB) | 77,332 B (75 KB) | 524,288 B (512 KB) |
| SRAM1 | 108,208 B (106 KB) incl. 8 KB stack | 22,864 B (22 KB) | 131,072 B (128 KB) |
| CCMRAM | 54,272 B (53 KB) — persistent TFLM arena | 11,264 B (11 KB) | 65,536 B (64 KB) |

All memory checks pass (see `fv_app_candidate_build_report.json`).

---

## 4. Board State at Handover

- **Running firmware:** `fv_app_candidate` (presence-gate enabled)
- **Uptime at last read:** ~2,400 s (~40 min), ~850 cycles
- **OLED status:** 0 (SSD1306 healthy)
- **Camera:** OV2640, PID=38, VER=66, PCLK_DIV=12
- **Sensors operational:** DHT22 (T=33.0°C, RH=50%), pH probe (9.28), MQ135 (warmed), TCS34725

> **Note:** The OLED footer `*proto, not lab test` is present on the physical OLED because
> the source fix (in `firmware/stm32f407/app/fv_report.c`) has not yet been rebuilt
> and reflashed. The source is clean; the board has the pre-fix binary.

---

## 5. How to Reflash (requires user approval)

```
STM32_Programmer_CLI -c port=SWD freq=4000 -d firmware/fv_app_candidate.bin 0x08000000 -v -rst
```

To restore original ENTC firmware:
```
STM32_Programmer_CLI -c port=SWD freq=4000 -d models/original_entc_ref/board_flash_0x08000000_512K.bin 0x08000000 -v -rst
```

---

## 6. Automated Test Suite

**Result:** 180 passed, 0 failed (run 2026-10-18)  
**Test runner:** `.venv\Scripts\python -m pytest tests -v`  
**Key test files:**
- `tests/test_fw_stm32_app.py` — 18 tests, full inference pipeline
- `tests/test_candidate_presence_integration.py` — 7 tests, presence head
- `tests/test_fw_presence_gate.py` — 10 tests, gate logic and OLED rows
- `tests/test_camera_preprocess.py` — preprocessing/quantization parity
- `tests/test_regression_golden.py` — golden output bit-identity
