# Restored ENTC firmware: observation checklist and integration gaps (2026-10-17)

Status: the original firmware was restored and the tool verified it byte-for-byte (`reports/firmware/restore_original_firmware_log.txt`:
"File download complete", "Download verified successfully", "Software reset is performed", exit 0).
**Its run-time behaviour has NOT been observed yet.** Nothing in this document was obtained by touching the board.
Static findings come from the local backup file
(`backups/board_original_firmware/board_flash_0x08000000_512K.bin`, sha256 `1590cd4e…601c`): text strings and
peripheral-address literals. They are **hints**, not a verified configuration.

## 1. Static hints from the original firmware (PC analysis of the backup only)
* Display text it can show: `Fruit monitor`, `Starting...`, `Camera start...`, `Camera: ready`, `CAMERA OK`, `CAMERA ERR %d`,
  `T:%dC H:%d%%`, `DHT err %d`, `pH:%d.%02d V:%d.%03d`, `pH:-- V:--`, `MQ:%d (warm up)`, `Warming up`, `Gas:%s`,
  `R:%d G:%d B:%d`, `RGB: --`, `Color: %s` (WHITE/BROWN/ORANGE/YELLOW/GREEN/PURPLE, White/Gray), `Color sensor err`,
  `Class: %s`, `Dark spots: %d%%`, `FRESH` / `RIPENING` / `SPOILED`, `STABLE`, `AVG  n=%d`.
* Camera diagnostics text: `Not an OV2640?`, `OV2640 should be 26`, `Check VSYNC PB7`, `PCLK PA6 HSYNC PA4`, `Check D0-D7 wires`,
  `PWDN GND RST 3V3`, `3.3V SCL SDA GND`, `SCL SDA swapped!`, `Data overrun`, `PCLK too fast`.
  These *suggest* VSYNC = PB7, PCLK = PA6, HSYNC = PA4 (the STM32F407 DCMI alternate-function pins), with PWDN tied to GND and RESET to
  3.3 V. **To be confirmed by ENTC.** Not used in any code.
* Peripheral base addresses referenced: DCMI, DMA2 (stream-1 registers), I2C1, I2C3, ADC1/2/3, TIM1/3/4/6, GPIOA–E/H, SYSCFG,
  RCC, FLASH, PWR. **No USART/UART and no SPI base address appears.** So the original firmware most likely has **no UART log**, and the
  display is probably I2C. Unconfirmed.

## 2. Power-cycle observation checklist (no tools connected to SWD needed)
Record each item as seen / not seen, with a photo or short video:
1. ☐ Power the board off, wait 5 s, power on with its normal supply (ST-LINK may stay connected; do not start a debug session).
2. ☐ OLED lights within ~2 s and shows start-up text (e.g. `Fruit monitor` / `Starting...`). Note the exact text.
3. ☐ Camera status line: `Camera: ready` / `CAMERA OK`, or an error (`CAMERA ERR n`, `Not an OV2640?`, `No picture arrives`, …). Note it.
4. ☐ Temperature/humidity line `T:..C H:..%` appears and updates (or `DHT err n`).
5. ☐ pH line shows a value (or `pH:-- V:--`).
6. ☐ MQ135 line shows `warm up`/`Warming up` first, then a value.
7. ☐ Colour line `R:.. G:.. B:..` / `Color: ...` changes when a coloured object is placed over the TCS34725 (or `Color sensor err`).
8. ☐ With a fruit in front of the camera: `Class:` / `FRESH`/`RIPENING`/`SPOILED` / `Dark spots:` appear. Note what is shown.
9. ☐ LEDs/buzzer behaviour, if any.
10. ☐ Let it run 5 min: no freeze or reboot loop (start-up text not repeating).
11. ☐ Optional, read-only: `STM32_Programmer_CLI -c port=SWD freq=100 mode=HOTPLUG` still identifies the MCU (does not reset or halt it).
Only when items 2–8 are observed can the restored application be called working, and only for the items seen.

## 3. UART logging
**No UART interface is documented** in the repo, and the original firmware references no USART/UART peripheral (hint above). Its pins
and baud rate are therefore unknown and are not guessed. If ENTC says a UART log exists, they need to provide the USART number, TX/RX
pins, baud rate and frame format (e.g. 8N1). Then observe it with a 3.3 V USB-UART adapter (TX→RX, GND→GND, **no** power pin) and a
serial terminal (e.g. PuTTY) at that setting. That is listen-only and does not modify the board.

## 4. Information still needed to integrate our ML application
**Software (from ENTC)**
1. Source project of the original firmware (CubeMX `.ioc` + code) or at least its init code: clock tree, GPIO/AF settings, DMA streams.
2. OV2640 register table used (resolution, output format RGB565/JPEG, byte order), XCLK source and frequency.
3. OLED: controller (SSD1306?), I2C bus (I2C1 or I2C3?), address, resolution, font/driver used.
4. Sensor drivers/settings: TCS34725 gain and ATIME; MQ135 ADC channel, divider, load resistor, warm-up rule; pH ADC channel and
   calibration (buffer points); DHT22 GPIO and timer.
5. Their classification logic (`Class:`, `Dark spots:`, FRESH/RIPENING/SPOILED) and whether to keep it alongside ours.

**Hardware (from ENTC, confirmed on the schematic)**
1. Full pin map:
   * DCMI D0–D7, PCLK, HSYNC, VSYNC; SCCB SDA/SCL; PWDN/RESET wiring.
   * I2C bus/pins for TCS34725 and the OLED.
   * ADC pins for MQ135 and pH.
   * DHT22 pin.
   * LEDs/buzzer.
   * Any UART.
2. HSE crystal frequency (or confirmation that it runs on HSI). The self-test proved HSI → 168 MHz works.
3. Power: 5 V budget for the MQ135 heater, analogue reference, sensor supply voltages.
4. BOOT0 strapping and whether NRST is on the SWD header.

**Integration route once the above arrives:** implement `firmware/stm32f407/platform/` against those settings (camera capture into
the SRAM arena window, 96×96 RGB565, or the format ENTC uses), keep the frozen models and the already-verified on-target ML path
(self-test PASS: ~357 ms/inference, arena 148,896 B, stack 1,120 B). Then flash only with approval, after a fresh backup.
