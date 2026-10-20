/* STM32F407VET6 platform layer for the ENTC board (implements platform/fv_platform.h).
 *
 * Pin map and device settings: board/fv_board_config.h (extracted from the original ENTC firmware, see
 * docs/BOARD_PIN_MAP_EVIDENCE.md). Hardware status: compiled and host-tested logic only; NOT yet run on the board.
 *
 * Sensors: pH = PA2 and MQ135 = PA3 (recovered from the ENTC firmware code); pH uses the ENTC calibration formula
 * (fv_entc_ph.h). No device->Model 2 calibration exists, so the pesticide risk stays UNCERTAIN/UNAVAILABLE.
 * Still unknown: PB14 kind (LED or buzzer) -> only the "alert" condition pulses it (3 x 100 ms), see fv_indicators().
 * No UART exists on this board: fv_serial_write() stores the line in g_fv_diag (read over SWD).
 */
#include <string.h>

#include "fv_adc.h"
#include "fv_bitbang_bus.h"
#include "fv_board_config.h"
#include "fv_clock_stm32f4.h"
#include "fv_dcmi_capture.h"
#include "fv_dht22.h"
#include "fv_diag.h"
#include "fv_entc_ov2640_tables.h"
#include "fv_entc_ph.h"
#include "fv_gpio.h"
#include "fv_ov2640.h"
#include "fv_cam_tune.h"
#include "fv_platform.h"
#include "fv_ssd1306.h"
#include "fv_tcs34725.h"

#define CAM_W 160                     /* output of the ENTC OV2640 tables [LIVE: 38,400 B frames read over SWD] */
#define CAM_H 120
#define CAM_FRAME_BYTES (CAM_W * CAM_H * 2)
#define RCC_AHB1ENR (*(volatile uint32_t *)0x40023830u)
#define RCC_AHB2ENR (*(volatile uint32_t *)0x40023834u)

static uint32_t s_core_hz = 16000000u;

/* ------------------------------------------------------------------ timing (DWT cycle counter) */
static void delay_us(uint32_t us) {
    const uint32_t t0 = fv_dwt_cycles(), n = us * (s_core_hz / 1000000u);
    while (fv_dwt_cycles() - t0 < n) { }
}
static void delay_ms(uint32_t ms) { while (ms--) delay_us(1000); }
static uint32_t now_us(void *ctx) { (void)ctx; return fv_dwt_cycles() / (s_core_hz / 1000000u); }
static void delay_us_ctx(void *ctx, uint32_t us) { (void)ctx; delay_us(us); }

/* ------------------------------------------------------------------ open-drain bit-banged buses */
typedef struct { fv_pin_t scl, sda; } od_pins_t;
static void od_scl(void *c, int v) { fv_gpio_write(((od_pins_t *)c)->scl, v); }
static void od_sda(void *c, int v) { fv_gpio_write(((od_pins_t *)c)->sda, v); }
static int od_sda_in(void *c) { return fv_gpio_read(((od_pins_t *)c)->sda); }
static int od_scl_in(void *c) { return fv_gpio_read(((od_pins_t *)c)->scl); }
static void od_delay(void *c) { (void)c; delay_us(3); }        /* quarter period ~3 us -> ~80 kHz */

static od_pins_t s_i2c_pins = {{FV_I2C_SCL_PORT, FV_I2C_SCL_PIN}, {FV_I2C_SDA_PORT, FV_I2C_SDA_PIN}};
static od_pins_t s_sccb_pins = {{FV_SCCB_SCL_PORT, FV_SCCB_SCL_PIN}, {FV_SCCB_SDA_PORT, FV_SCCB_SDA_PIN}};
static const fv_bb_bus_t s_i2c = {od_scl, od_sda, od_sda_in, od_scl_in, od_delay, &s_i2c_pins};
static const fv_bb_bus_t s_sccb = {od_scl, od_sda, od_sda_in, od_scl_in, od_delay, &s_sccb_pins};

static void od_pin_init(fv_pin_t p) {
    fv_gpio_write(p, 1);                                         /* released before switching to output */
    fv_gpio_config(p, FV_GPIO_OUT, FV_GPIO_OD, FV_GPIO_PULLUP, FV_GPIO_SPEED_HIGH, 0);
}

/* ------------------------------------------------------------------ devices */
static fv_ssd1306_t s_oled;
static fv_tcs34725_t s_tcs = {&s_i2c, FV_TCS34725_ADDR8, delay_ms, 0, 0, 0};
static fv_ov2640_t s_cam = {&s_sccb, FV_OV2640_SCCB_ADDR8, delay_ms, 0, 0, -1};
static int s_oled_ok, s_tcs_ok, s_cam_ok, s_pclk_idx;

static const fv_pin_t PIN_DHT = {FV_DHT_PORT, FV_DHT_PIN};
static const fv_pin_t PIN_IND = {FV_INDICATOR_PORT, FV_INDICATOR_PIN};
static void dht_low(void *c) { (void)c; fv_gpio_write(PIN_DHT, 0); }
static void dht_release(void *c) { (void)c; fv_gpio_write(PIN_DHT, 1); }
static int dht_read(void *c) { (void)c; return fv_gpio_read(PIN_DHT); }
static void irq_off(void *c) { (void)c; __asm volatile("cpsid i" ::: "memory"); }
static void irq_on(void *c) { (void)c; __asm volatile("cpsie i" ::: "memory"); }
/* Sensor confirmed as DHT11 by the hardware team; decoded like the ENTC firmware (DHT11 format). */
static const fv_dht22_io_t s_dht = {dht_low, dht_release, dht_read, now_us, delay_us_ctx, 0, irq_off, irq_on,
                                    FV_DHT_FORMAT_DHT11};
static fv_entc_ph_t s_ph;

fv_status_t fv_platform_init(void) {
    fv_diag_init();
    g_fv_diag.clock_status = fv_clock_init_hsi_168mhz();
    s_core_hz = g_fv_diag.clock_status == 0 ? FV_SYSCLK_HZ : 16000000u;
    fv_systick_init_1ms(s_core_hz);
    fv_dwt_cycle_counter_init();
    const int ports[] = {FV_PORT_A, FV_PORT_B, FV_PORT_C, FV_PORT_E};
    for (unsigned i = 0; i < sizeof ports / sizeof ports[0]; ++i) fv_gpio_clock_enable(ports[i]);

    fv_gpio_write(PIN_IND, 0);                                    /* PB14 low, as the ENTC firmware */
    fv_gpio_config(PIN_IND, FV_GPIO_OUT, FV_GPIO_PP, FV_GPIO_NOPULL, FV_GPIO_SPEED_LOW, 0);

    od_pin_init(s_i2c_pins.scl); od_pin_init(s_i2c_pins.sda);
    od_pin_init(s_sccb_pins.scl); od_pin_init(s_sccb_pins.sda);
    (void)fv_bb_recover(&s_i2c);
    (void)fv_bb_recover(&s_sccb);

    s_oled.bus = &s_i2c;
    s_oled.addr8 = FV_SSD1306_ADDR8;
    g_fv_diag.oled_status = fv_ssd1306_init(&s_oled);
    s_oled_ok = g_fv_diag.oled_status == FV_SSD1306_OK;
    if (s_oled_ok) { fv_ssd1306_draw_text(&s_oled, 0, 0, "FV starting..."); (void)fv_ssd1306_flush(&s_oled); }
    g_fv_diag.tcs_status = fv_tcs34725_init(&s_tcs);
    s_tcs_ok = g_fv_diag.tcs_status == FV_TCS_OK;

    fv_gpio_write(PIN_DHT, 1);
    fv_gpio_config(PIN_DHT, FV_GPIO_OUT, FV_GPIO_OD, FV_GPIO_PULLUP, FV_GPIO_SPEED_VHIGH, 0);
    fv_gpio_config((fv_pin_t){FV_PORT_A, 2}, FV_GPIO_ANALOG, FV_GPIO_PP, FV_GPIO_NOPULL, FV_GPIO_SPEED_LOW, 0);
    fv_gpio_config((fv_pin_t){FV_PORT_A, 3}, FV_GPIO_ANALOG, FV_GPIO_PP, FV_GPIO_NOPULL, FV_GPIO_SPEED_LOW, 0);
    fv_adc_init();
    return g_fv_diag.clock_status == 0 ? FV_OK : FV_ERR_HW;
}

uint32_t fv_platform_millis(void) { return fv_millis(); }

/* ------------------------------------------------------------------ camera */
fv_status_t fv_camera_init(uint16_t req_width, uint16_t req_height) {
    if (req_width != CAM_W || req_height != CAM_H) return FV_ERR_ARG;   /* only the ENTC-verified mode */
    RCC_AHB1ENR |= 1u << 22;                                     /* DMA2 */
    RCC_AHB2ENR |= 1u << 0;                                      /* DCMI */
    (void)RCC_AHB2ENR;
    const fv_pin_t dcmi[FV_DCMI_N_PINS] = FV_DCMI_PINS;
    for (int i = 0; i < FV_DCMI_N_PINS; ++i)
        fv_gpio_config(dcmi[i], FV_GPIO_AF, FV_GPIO_PP, FV_GPIO_NOPULL, FV_GPIO_SPEED_VHIGH, FV_DCMI_AF);
    g_fv_diag.cam_probe_status = fv_ov2640_probe(&s_cam);
    g_fv_diag.cam_pid = s_cam.pid;
    g_fv_diag.cam_ver = s_cam.ver;
    int r = g_fv_diag.cam_probe_status;
    for (int attempt = 0; attempt < 5; ++attempt) {
        fv_bb_recover(s_cam.bus);
        delay_ms(20);
        r = fv_ov2640_init_entc(&s_cam);
        if (r == FV_OV2640_OK) break;
        delay_ms(50);
    }
    if (r == FV_OV2640_OK) r = fv_ov2640_set_pclk_div(&s_cam, FV_ENTC_OV2640_PCLK_DIV[s_pclk_idx = 0]);
    g_fv_diag.cam_table_fail_index = (uint32_t)s_cam.failed_index;
    g_fv_diag.cam_pclk_div = FV_ENTC_OV2640_PCLK_DIV[s_pclk_idx];
    g_fv_diag.cam_status = r;
    s_cam_ok = r == FV_OV2640_OK;
    if (s_cam_ok) delay_ms(150);                                 /* ENTC waits 150 ms after a PCLK change */
    return s_cam_ok ? FV_OK : FV_ERR_HW;
}

fv_status_t fv_camera_capture_rgb565(uint8_t *buf, size_t buf_bytes, fv_frame_info_t *info) {
    if (!buf || !info || buf_bytes < CAM_FRAME_BYTES + 4u) return FV_ERR_ARG;
    if (!s_cam_ok) return FV_ERR_HW;
    const fv_dcmi_cfg_t cfg = {FV_DCMI_VSPOL, FV_DCMI_HSPOL, 1500};
    size_t got = 0;
    fv_cap_status_t c = fv_dcmi_start(FV_DCMI_REGS, FV_DMA2_REGS, buf, buf_bytes & ~(size_t)3u, &cfg);
    if (c == FV_CAP_OK)
        c = fv_dcmi_finish(FV_DCMI_REGS, FV_DMA2_REGS, buf_bytes & ~(size_t)3u, CAM_FRAME_BYTES, &cfg, fv_millis, &got);
    g_fv_diag.last_capture_status = (int32_t)c;
    g_fv_diag.last_capture_bytes = (uint32_t)got;
    if (c == FV_CAP_OK) {
        info->width = CAM_W; info->height = CAM_H; info->big_endian_pixels = 1;
        return FV_OK;
    }
    if ((c == FV_CAP_ERR_OVERRUN || c == FV_CAP_ERR_SIZE || c == FV_CAP_ERR_BUFFER_FULL) &&
        s_pclk_idx + 1 < FV_ENTC_OV2640_PCLK_N) {                /* ENTC strategy: slower pixel clock next time */
        ++s_pclk_idx;
        if (fv_ov2640_set_pclk_div(&s_cam, FV_ENTC_OV2640_PCLK_DIV[s_pclk_idx]) == FV_OV2640_OK)
            g_fv_diag.cam_pclk_div = FV_ENTC_OV2640_PCLK_DIV[s_pclk_idx];
    }
    return c == FV_CAP_ERR_TIMEOUT ? FV_ERR_TIMEOUT : FV_ERR_HW;
}

#ifdef FV_DIAG_CAM_TUNE
int fv_camera_write_regs(const fv_cam_reg_t *regs, int n) {
    if (!s_cam_ok || !regs || n < 0) return -1;
    for (int i = 0; i < n; ++i)
        if (fv_sccb_write(&s_sccb, FV_OV2640_SCCB_ADDR8, regs[i].reg, regs[i].val) != FV_BB_OK) return -1;
    return 0;
}
#endif

/* ------------------------------------------------------------------ sensors */
fv_status_t fv_sensors_read(fv_sensor_record_t *out) {
    if (!out) return FV_ERR_ARG;
    memset(out, 0, sizeof *out);
    out->origin = FV_ORIGIN_DEVICE;
    out->has_calibration_profile = 0;                            /* no calibration profile exists */
    out->tcs_atime = -1;
    int any = 0;
    if (s_tcs_ok) {
        uint16_t c, r, g, b;
        if (fv_tcs34725_read(&s_tcs, &c, &r, &g, &b) == FV_TCS_OK) {
            out->has_tcs = 1; out->tcs_c = c; out->tcs_r = r; out->tcs_g = g; out->tcs_b = b;
            out->tcs_atime = s_tcs.atime;
            g_fv_diag.tcs_c = c; g_fv_diag.tcs_r = r; g_fv_diag.tcs_g = g; g_fv_diag.tcs_b = b;
            any = 1;
        }
    }
    float t = 0.0f, h = 0.0f;
    g_fv_diag.dht_status = fv_dht22_read(&s_dht, &t, &h);       /* 20 ms start pulse, then IRQs off for the bits */
    if (g_fv_diag.dht_status == FV_DHT_OK) {
        out->has_temp = out->has_rh = 1; out->temp_c = t; out->rh_pct = h;
        g_fv_diag.temp_c_x10 = (int32_t)(t * 10.0f); g_fv_diag.rh_x10 = (int32_t)(h * 10.0f);
        any = 1;
    }
    /* pH (PA2) and MQ135 (PA3): mapping and sample counts from the ENTC firmware [STATIC]. */
    uint16_t ph_raw = 0, mq_raw = 0;
    if (fv_adc_read_avg(FV_ADC_CH_PH, FV_ENTC_PH_SAMPLES, &ph_raw) == FV_ADC_OK) {
        float vf = 0.0f;
        const float ph = fv_entc_ph_update(&s_ph, ph_raw, &vf);
        g_fv_diag.adc_ch_a_raw = ph_raw;
        g_fv_diag.ph_x100 = (int32_t)(ph * 100.0f + 0.5f);
        g_fv_diag.ph_mv = (int32_t)(vf * 1000.0f + 0.5f);
        out->has_ph = 1;                                         /* ENTC calibration, see fv_entc_ph.h */
        out->ph = ph;
        any = 1;
    } else {
        g_fv_diag.ph_x100 = -1;
    }
    if (fv_adc_read_avg(FV_ADC_CH_MQ135, FV_ENTC_MQ_SAMPLES, &mq_raw) == FV_ADC_OK) {
        g_fv_diag.adc_ch_b_raw = mq_raw;
        g_fv_diag.mq135_raw = mq_raw;
        g_fv_diag.mq135_warmed = fv_millis() >= FV_ENTC_MQ_WARMUP_MS;
        out->has_mq = 1;
        out->mq135 = (float)mq_raw;
        out->mq_unit = FV_MQ_UNIT_ADC12;                         /* raw device counts, NOT the Model 2 synthetic scale */
        out->mq_warmup_s = (float)fv_millis() / 1000.0f;         /* heater powered since power-up */
        any = 1;
    }
    /* has_calibration_profile stays 0: no mapping from device units to the synthetic Model 2 scales exists, so the
     * pesticide-risk estimate can only be UNCERTAIN (or UNAVAILABLE if a reading is invalid/missing). */
    return any ? FV_OK : FV_ERR_HW;
}

/* ------------------------------------------------------------------ outputs */
fv_status_t fv_oled_show(const fv_oled_text_t *text) {
    if (!text) return FV_ERR_ARG;
    if (!s_oled_ok) return FV_ERR_HW;
    fv_ssd1306_clear(&s_oled);
    for (int i = 0; i < text->n && i < FV_OLED_ROWS; ++i) fv_ssd1306_draw_text(&s_oled, 0, i, text->line[i]);
    g_fv_diag.oled_status = fv_ssd1306_flush(&s_oled);           /* last flush result (0 = all 8 pages written) */
    return g_fv_diag.oled_status == FV_SSD1306_OK ? FV_OK : FV_ERR_HW;
}

fv_status_t fv_serial_write(const char *data, size_t len) {     /* no UART: SWD-readable diagnostics line */
    if (!data) return FV_ERR_ARG;
    const size_t n = len < sizeof g_fv_diag.serial_line - 1 ? len : sizeof g_fv_diag.serial_line - 1;
    memcpy(g_fv_diag.serial_line, data, n);
    g_fv_diag.serial_line[n] = '\0';
    return FV_OK;
}

/* Documented indicator policy (single output PB14, LED-or-buzzer unknown):
 *   alert (image rejected, or risk category HIGH while PREDICTED) -> 3 pulses of 100 ms on / 100 ms off
 *   warn only                                                   -> PB14 stays off (shown on the OLED instead) */
void fv_indicators(int led_on, int buzzer_on) {
    (void)led_on;
    if (!buzzer_on) { fv_gpio_write(PIN_IND, 0); return; }
    for (int i = 0; i < 3; ++i) {
        fv_gpio_write(PIN_IND, 1); delay_ms(100);
        fv_gpio_write(PIN_IND, 0); delay_ms(100);
    }
}
