# SMART PESTICIDE RESIDUE DETECTION SYSTEM
## ISE–I Mega Project Presentation — Quick Slide Content

**Project Guide:** Miss. S. S. Desai  
**Department:** Electronics & Telecommunication Engineering (ENTC)  
**Institution:** D. Y. Patil College of Engineering & Technology, Kasaba Bawada, Kolhapur  
**Academic Year:** 2026–27  
**Team Members:** Shashank Gokhale (01), Vedika Suryawanshi (10), Janhavi Powar (11), Gaurav Rathod (53), Nikhil Airekar (54)

---

### Slide 1: Problem & Motivation
- **Problem:** Chemical pesticide residues on fresh produce pose significant chronic health concerns (SDG 3). Conventional reference testing (GC-MS / LC-MS chromatography) is centralized, expensive, and takes days to produce results.
- **Motivation:** Develop a portable, embedded, low-cost screening prototype capable of assessing surface quality and estimating pesticide-residue risk in seconds directly at the point of consumption without cloud dependence.

---

### Slide 2: Multi-Sensor Hardware Architecture
- **Microcontroller:** STM32F407VET6 (ARM Cortex-M4 @ 168 MHz, 512KB Flash, 192KB RAM)
- **Vision Modality:** OV2640 DVP Camera (160x120 RGB565 via DCMI DMA)
- **Optical Colorimetry:** TCS34725 I2C 16-bit RGB & Clear photon counter
- **Gas / VOC Sensing:** MQ135 electro-chemical gas sensor (12-bit ADC SAR)
- **Wash-Water pH:** Potentiometric glass electrode probe with op-amp driver
- **Thermal Normalization:** DHT22 temperature (&deg;C) and relative humidity (%RH)
- **Display & Alert:** SSD1306 0.96" I2C OLED + Buzzer alert indicator (PB14)

---

### Slide 3: Two-Tier Machine Learning Strategy
1. **Model 1 & 3 — Deep Computer Vision (TFLM INT8):**
   - Trained on **8,457 verified produce images** (FruitNet + AgriFreshNET + Mendeley Quality).
   - MobileNet architecture quantized to INT8 using ARM CMSIS-NN SIMD kernels.
   - Outputs: 5-class Fruit classification (Apple, Banana, Guava, Tomato, Brinjal), Condition (Fresh/Spoiled), Quality Grade (Good/Average/Poor), and Shelf-life stage (days).
   - Embedded Background Rejection Head suppresses false positives on empty surfaces.
2. **Model 2 — Multi-Sensor Fusion & Estimated Pesticide Risk:**
   - Evaluates chemical feature interactions: organophosphate wash-water acidification, volatile pesticide vapor elevation (MQ135), and surface spectral ratios (TCS34725 R/C, G/C, B/C).
   - Softmax multinomial inference predicts: **LOW**, **MEDIUM**, or **HIGH** risk.

---

### Slide 4: Key Results & Performance Metrics
- **On-Device Vision Latency:** ~120 ms per frame on ARM Cortex-M4.
- **Memory Footprint:** 
  - Flash ROM: **446 KB / 512 KB (85.2%)** — Zero dynamic heap allocation.
  - SRAM1 + Stack: **108 KB / 128 KB (82.5%)**
  - CCMRAM (Persistent Arena): **54 KB / 64 KB (82.8%)**
- **Validation:** 180 passing regression tests; bit-identical parity between PC LiteRT simulation and embedded ARM CMSIS-NN execution.
- **Dual-Stage Gate False Alarm Rate:** < 1.0% on featureless surfaces.

---

### Slide 5: Conclusion & Future Scope
- **Conclusion:** Successfully demonstrated edge-computed multi-sensor TinyML inference on an STM32F407 microcontroller for agricultural produce screening.
- **Future Scope:** Expanding the multi-sensor dataset with certified analytical chromatography standards, integrating wireless Bluetooth/BLE client sync, and designing a 3D-printed handheld enclosure.
