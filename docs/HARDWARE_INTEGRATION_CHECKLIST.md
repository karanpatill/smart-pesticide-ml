# Hardware integration checklist

Nothing below has been tested on hardware. Pin choices are suggestions to
be verified against the STM32F407VET6 datasheet and the board schematic.

| Component | Interface | Integration checks (all ☐) | Software expectation (exists ✅) |
|---|---|---|---|
| OV2640 | DCMI (8-bit) + SCCB (I2C-like) + XCLK (MCO, ~12–24 MHz) | ☐ chip-ID read (0x26/0x42) ☐ RGB565 QQVGA capture ☐ DMA to main SRAM (not CCM) ☐ exposure / white balance fixed for repeatability ☐ capture under the demo lighting | ✅ image checks reject blank/uniform/noise frames; ✅ aspect warning |
| TCS34725 | I2C 0x29 | ☐ ID register (0x44/0x4D) ☐ ATIME / AGAIN recorded with every reading ☐ fixed LED illumination + strip holder (dark enclosure) ☐ no saturation at the chosen gain | ✅ zero / saturation / ATIME-aware checks |
| MQ135 | ADC (via divider to ≤ 3.3 V) | ☐ heater 5 V supply budget ☐ load resistor value recorded ☐ ≥ 24 h burn-in (datasheet) and ≥ 3 min warm-up per session ☐ rails never reached | ✅ rail checks, warm-up warning / uncertain |
| pH probe + amplifier board | ADC | ☐ 2- or 3-point calibration (pH 4.01 / 6.86 / 9.18 buffers) ☐ temperature noted ☐ probe disconnected → rail detected | ✅ 0 < pH < 14 check |
| DHT22 | 1-wire GPIO | ☐ checksum failures counted ☐ ≥ 2 s between reads | ✅ NaN / range checks |
| SSD1306 | I2C 0x3C | ☐ display shows the state (PREDICTED / UNCERTAIN / UNAVAILABLE) for every field, never a bare number | ✅ result schema carries `state` |
| Buzzer / LED | GPIO | ☐ alert only for invalid input or HIGH (with "screening only" text on the OLED) | ✅ recommendation rules |

## System-level checks
- ☐ One complete record captured and logged over UART in the
  `docs/END_TO_END.md` sensor schema, with `meta.data_origin = "device"`.
- ☐ Logged records replayed through `scripts/analyze.py --sensors`. Expected
  today: risk `uncertain` (no calibration profile). That is correct behaviour.
- ☐ I2C bus scan shows only the expected addresses (0x29, 0x3C, OV2640 SCCB
  0x30).
- ☐ Brown-out check with the MQ135 heater on.
