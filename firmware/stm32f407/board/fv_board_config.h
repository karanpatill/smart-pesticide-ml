/* Board configuration of the assembled ENTC hardware (STM32F407VET6).
 *
 * PROVENANCE. Every value below was extracted from the ORIGINAL ENTC FIRMWARE (backup sha256 1590cd4e...,
 * disassembly; details in docs/BOARD_PIN_MAP_EVIDENCE.md), i.e. from the HAL_GPIO_Init / HAL_I2C / HAL_RCC / ADC
 * calls of the firmware that is verified to run on this board (live OV2640 frames read over SWD, OLED text).
 * Classification:
 *   [LIVE]    confirmed on this board by an actual read (SWD)
 *   [STATIC]  extracted from the ENTC firmware code; consistent with observed behaviour; ENTC to confirm
 *   [UNKNOWN] not determinable from the evidence -> the feature stays disabled (FV_BOARD_UNKNOWN), never guessed
 */
#ifndef FV_BOARD_CONFIG_H
#define FV_BOARD_CONFIG_H

#define FV_BOARD_UNKNOWN (-1)

/* GPIO port indices (A=0 .. E=4, H=7) and pin numbers */
#define FV_PORT_A 0
#define FV_PORT_B 1
#define FV_PORT_C 2
#define FV_PORT_E 4

/* ---- OV2640 / DCMI, AF13 push-pull, no pull, very high speed [STATIC: HAL_GPIO_Init @0x080019A6..0x080019F4] */
#define FV_DCMI_AF 13
/* {port, pin}: HSYNC PA4, PCLK PA6, D5 PB6, VSYNC PB7, D0..D3 PC6..PC9, D4 PC11, D6 PE5, D7 PE6 */
#define FV_DCMI_PINS { {FV_PORT_A, 4}, {FV_PORT_A, 6}, {FV_PORT_B, 6}, {FV_PORT_B, 7}, {FV_PORT_C, 6}, {FV_PORT_C, 7}, \
                       {FV_PORT_C, 8}, {FV_PORT_C, 9}, {FV_PORT_C, 11}, {FV_PORT_E, 5}, {FV_PORT_E, 6} }
#define FV_DCMI_N_PINS 11
#define FV_DCMI_VSPOL 0          /* [LIVE] read from ENTC RAM 0x2000A35D over SWD */
#define FV_DCMI_HSPOL 0          /* [LIVE] 0x2000A35E */
/* XCLK: the ENTC firmware configures NO MCO/timer pin for XCLK [STATIC] -> camera module assumed self-clocked
 * (module oscillator). PWDN/RESET: ENTC diagnostic text "PWDN GND RST 3V3" [STATIC hint] -> no MCU pin. */
#define FV_CAMERA_XCLK_FROM_MCU 0

/* ---- SCCB (OV2640 control): bit-banged, open-drain + pull-up [STATIC: HAL_GPIO_Init @0x0800144C, start
 * condition @0x0800148C drives PB11 low while PB10 high => PB11 = SDA, PB10 = SCL]. OV2640 8-bit address 0x60/0x61. */
#define FV_SCCB_SCL_PORT FV_PORT_B
#define FV_SCCB_SCL_PIN 10
#define FV_SCCB_SDA_PORT FV_PORT_B
#define FV_SCCB_SDA_PIN 11
#define FV_OV2640_SCCB_ADDR8 0x60

/* ---- I2C bus for SSD1306 + TCS34725 [STATIC: HAL_GPIO_Init @0x080035B2 PB8/PB9 AF4 open-drain; I2C1 Instance
 * @0x08002ED6, 400 kHz, 7-bit; HAL_I2C_Mem_Write with 0x78 (OLED) and 0x52 (TCS34725)]. This firmware drives the
 * same two pins as a bit-banged open-drain bus (no I2C peripheral state machine needed; slower than 400 kHz). */
#define FV_I2C_SCL_PORT FV_PORT_B
#define FV_I2C_SCL_PIN 8
#define FV_I2C_SDA_PORT FV_PORT_B
#define FV_I2C_SDA_PIN 9
#define FV_SSD1306_ADDR8 0x78    /* 7-bit 0x3C [STATIC] */
#define FV_TCS34725_ADDR8 0x52   /* 7-bit 0x29 [STATIC] (fixed by the chip) */
#define FV_OLED_WIDTH 128         /* [STATIC] init sends 0xA8 0x3F (64 rows) and 0xDA 0x12 */
#define FV_OLED_HEIGHT 64

/* ---- DHT22 single-wire: PA1 open-drain + pull-up, very high speed [STATIC: HAL_GPIO_Init @0x08002FE8] */
#define FV_DHT_PORT FV_PORT_A
#define FV_DHT_PIN 1

/* ---- Analog inputs: PA2 = ADC1_IN2, PA3 = ADC1_IN3, analog mode, 480-cycle sampling [STATIC: @0x08003546, ADC
 * read helper @0x08000780]. Mapping recovered from the ENTC main loop [STATIC, docs/BOARD_PIN_MAP_EVIDENCE.md]:
 * channel 2 feeds the pH formula (@0x08002734..0x080027A8), channel 3 feeds the MQ135 warm-up/ratio routine
 * (@0x0800273C, 0x08000A18). */
#define FV_ADC_CH_A 2
#define FV_ADC_CH_B 3
#define FV_ADC_CH_PH 2       /* PA2 [STATIC: ENTC code] */
#define FV_ADC_CH_MQ135 3    /* PA3 [STATIC: ENTC code] */

/* ---- Indicator output: PB14 push-pull, initially low, driven by a "count x (on ms, off ms)" pulse helper
 * [STATIC @0x08000908]. Whether it drives an LED or an active buzzer is [UNKNOWN]. */
#define FV_INDICATOR_PORT FV_PORT_B
#define FV_INDICATOR_PIN 14
#define FV_INDICATOR_KIND FV_BOARD_UNKNOWN /* 1 = LED, 2 = active buzzer, once ENTC confirms */

/* ---- Clock: ENTC runs on HSI 16 MHz without PLL [STATIC: RCC_OscInit @0x08002DCC]. This firmware uses HSI ->
 * PLL 168 MHz (verified on this board by the ML self-test). No crystal is required. */

/* ---- Serial log: no USART/UART peripheral or pin is used by the ENTC firmware [STATIC] -> no UART here; results
 * are exposed in the SWD-readable diagnostics block g_fv_diag instead. */
#define FV_HAVE_UART 0

#endif
