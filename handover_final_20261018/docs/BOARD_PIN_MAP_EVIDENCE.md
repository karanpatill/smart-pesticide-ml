# Board pin map and peripheral configuration: evidence (2026-10-17)

Source: static analysis of the original ENTC firmware backup (`backups/board_original_firmware/…bin`, sha256 `1590cd4e…601c`),
which runs on this board (live OV2640 frames read over SWD; OLED showing readings). No board access was used for this document.
**[LIVE]** = read on the board; **[STATIC]** = extracted from the ENTC code (HAL calls/literals; ENTC to confirm); **[UNKNOWN]** = not determinable.

| Function | Pins / setting | Evidence | Level |
|---|---|---|---|
| DCMI (AF13, push-pull, no pull, very high speed) | HSYNC PA4, PCLK PA6, D5 PB6, VSYNC PB7, D0–D3 PC6–PC9, D4 PC11, D6 PE5, D7 PE6 | HAL_GPIO_Init (0x080043DC) calls @0x080019A6–0x080019F4: GPIOA 0x0050, GPIOB 0x00C0, GPIOC 0x0BC0, GPIOE 0x0060, AF=13 | STATIC |
| DCMI polarity | VSPOL 0, HSPOL 0 | SWD read of 0x2000A35D/E | LIVE |
| Frame format | 160×120 RGB565 high byte first, 38,400 B | SWD frame reads + ENTC statistics match | LIVE |
| OV2640 SCCB | bit-banged, SCL PB10, SDA PB11 (open-drain, pull-up), address 0x60 | GPIO init @0x0800144C (pins 0x0C00, mode OD); start condition @0x0800148C; write address 0x60 @0x0800178A | STATIC |
| OV2640 registers | table A 157 pairs @0x0800711C + table B 22 pairs @0x08007258 after 0xFF←0x01; PCLK divider candidates 0x0C/0x18/0x30 (written \|0x80 to 0xD3) | init @0x08001F96, PCLK search @0x08002006 | STATIC (output LIVE-verified) |
| XCLK | no MCO/timer pin configured → module oscillator assumed | absence of any XCLK GPIO/AF config | STATIC |
| I2C bus (OLED + TCS34725) | I2C1, SCL PB8, SDA PB9 (AF4 open-drain), 400 kHz, 7-bit | GPIO init @0x080035B2; I2C1 Instance + 400000 @0x08002ED6 | STATIC |
| SSD1306 | addr 0x3C (0x78), 128×64; init order AE,20 00,B0,C8,00,10,40,81 FF,A1,A6,A8 3F,A4,D3 00,D5 F0,D9 22,DA 12,DB 20,8D 14,AF | HAL_I2C_Mem_Write 0x78 @0x08003054; init @0x080030AA | STATIC |
| TCS34725 | addr 0x29 (0x52); ATIME 0xEB, gain 0x01 (4×), ENABLE PON→PON\|AEN; burst read 0xB4 | @0x08003760–0x08003818 | STATIC |
| DHT22 | PA1 open-drain + pull-up | GPIO init @0x08002FE8; "DHT err" text | STATIC |
| Analog | PA2 (ADC1_IN2), PA3 (ADC1_IN3), 480-cycle sampling | GPIO init @0x08003546 (mode analog); ADC helper @0x08000780 | STATIC |
| **MQ135 vs pH channel** | which of IN2/IN3 is which | no conversion constants in the readers | **UNKNOWN** |
| Indicator | PB14 push-pull, initially low; pulse helper (count, on ms, off ms) | @0x080008D2, @0x08000908 | STATIC |
| **PB14 = LED or buzzer** | — | — | **UNKNOWN** |
| Clock | HSI 16 MHz, no PLL (ENTC). Our firmware: HSI→PLL 168 MHz (verified by self-test) | RCC_OscInit @0x08002DCC | STATIC / LIVE |
| UART | none used | no USART/UART literal | STATIC |

## What the application firmware (`reports/firmware/gcc/fv_app.elf`, NOT flashed) does with this
* **Camera:** DCMI pins AF13 → SCCB probe (PID 0x26) → ENTC tables → PCLK 0x8C (steps to 0x98/0xB0 after errors, like ENTC) →
  DCMI snapshot + DMA2 into the TFLM arena window → frozen INT8 model → validation.
* **Sensors:** TCS34725 (ENTC settings) and DHT22 are read. MQ135/pH raw ADC values are only published in `g_fv_diag` until the
  channel mapping is confirmed. pH is never reported without a calibration profile. Device data never yields a PREDICTED Model 2 risk
  (no calibration profile), so the risk shows UNCERTAIN/UNAVAILABLE.
* **OLED:** 21×8 text from `fv_report_oled`. **PB14:** 3 pulses only on alert (image rejected, or risk HIGH while predicted).
* **Diagnostics:** `g_fv_diag` (420 B, SRAM), read with `tools/firmware/read_diag.py` (read-only, hot-plug).
* Deviation from ENTC: I2C1 pins are driven as a bit-banged open-drain bus (~80 kHz) instead of the I2C1 peripheral at 400 kHz.

## Update 2026-10-17: ADC mapping, pH conversion and DHT22 timing recovered from the ENTC firmware [STATIC]
| Item | Finding | Evidence |
|---|---|---|
| **pH = PA2 (ADC1_IN2)** | main loop @0x08002734 calls the channel-2 reader (0x08000800); its float result goes into `pH = (V − 2.282) × (−5.263) + 7.0`, clamped 0–14 | @0x08002760–0x080027A8; constants @0x080028F4/F8 |
| pH voltage | `V = raw × 3.3 / 4095`, smoothed `Vf = 0.95·Vf + 0.05·V` | @0x08000822–0x0800085E |
| **MQ135 = PA3 (ADC1_IN3)** | channel 3, 50-sample average → routine 0x08000A18: 120,000 ms warm-up (flag 0x20000000 = "MQ … (warm up)"), ratio to a stored baseline, thresholds 1.5× and 3.0× ("Gas: x…") | @0x0800273C–0x08002756, 0x08000A18 |
| **DHT22 timing** | PA1 low for **20 ms** (HAL_Delay(20)), then interrupts off, release, 30 µs, response + 40 bits, interrupts on | @0x08000712–0x0800073A, 0x08000620 |
fv_app differences: the DHT22 start pulse is 1.1 ms (likely why dht_status = −1); pH/MQ135 are still disabled in fv_app.
