/* Diagnostics block in SRAM, readable over SWD while the firmware runs (STM32CubeProgrammer hot-plug -r32/-u),
 * because the board has no UART. Fixed layout (32-bit fields + char array), version-tagged.
 * Written every cycle by the platform/app; never read back by the firmware. */
#ifndef FV_DIAG_H
#define FV_DIAG_H
#include <stdint.h>

#define FV_DIAG_MAGIC 0xF1D1A600u
#define FV_DIAG_VERSION 3u

typedef struct {
    uint32_t magic, version;
    uint32_t uptime_ms, cycles;
    int32_t clock_status;              /* 0 = PLL 168 MHz from HSI */
    int32_t oled_status, tcs_status, cam_status, cam_probe_status;
    uint32_t cam_pid, cam_ver, cam_pclk_div, cam_table_fail_index;
    int32_t last_cycle_status, last_camera_status, last_sensor_status, last_capture_status;
    uint32_t last_capture_bytes, last_image_flags;
    int32_t fruit, fruit_conf_pm, condition, condition_conf_pm, quality_state, grade, shelf_state;
    uint32_t consistency;
    int32_t risk_state, risk_reasons;
    uint32_t sensor_errors, sensor_warnings;
    uint32_t tcs_c, tcs_r, tcs_g, tcs_b;
    int32_t dht_status, temp_c_x10, rh_x10;
    uint32_t adc_ch_a_raw, adc_ch_b_raw;  /* PA2 (IN2) = pH, PA3 (IN3) = MQ135 [STATIC, ENTC code] */
    uint32_t vision_arena_used;
    /* v2: sensor values. pH uses the ENTC calibration formula (not re-measured by this project). */
    int32_t ph_x100;                    /* pH * 100 (ENTC calibration), -1 = not available */
    int32_t ph_mv;                      /* smoothed pH-board voltage in mV (nominal 3.3 V reference) */
    uint32_t mq135_raw;                 /* PA3, 50-sample average, 12-bit ADC counts */
    uint32_t mq135_warmed;              /* 1 after the ENTC 120 s warm-up since power-up */
    /* v3: fruit-presence gate (fv_presence.h) */
    int32_t img_detail_x10;             /* image detail x10 (Laplacian variance of the model input) */
    uint32_t fruit_present;             /* 1 = fruit shown, 0 = NO FRUIT / UNKNOWN */
    char serial_line[256];
} fv_diag_t;

extern fv_diag_t g_fv_diag;
void fv_diag_init(void);

#endif
