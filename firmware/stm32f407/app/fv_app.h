/* Application pipeline: camera -> preprocessing -> image check -> Model 1+3 -> output validation,
 * sensors -> validation -> Model 2 risk, then OLED + serial reporting. Portable C99; all hardware
 * access goes through platform/fv_platform.h. */
#ifndef FV_APP_H
#define FV_APP_H

#include "fv_common.h"
#include "fv_report.h"
#include "fv_result.h"
#include "fv_sensor.h"

/* Capture geometry. Default = the format the ENTC firmware configures and validates (STATIC evidence from
 * the ENTC binary, docs/CAMERA_ML_INTEGRATION_PLAN.md): OV2640 160x120 (QQVGA) RGB565, row-major, high byte
 * first, 38,400 B per frame. Not yet observed on hardware. Override with -DFV_CAMERA_W/-DFV_CAMERA_H. */
#ifndef FV_CAMERA_W
#define FV_CAMERA_W 160
#endif
#ifndef FV_CAMERA_H
#define FV_CAMERA_H 120
#endif
#ifndef FV_CAMERA_BIG_ENDIAN
#define FV_CAMERA_BIG_ENDIAN 1   /* ENTC pixel decode: p = (b[0] << 8) | b[1] */
#endif
#define FV_CAMERA_BYTES ((size_t)FV_CAMERA_W * FV_CAMERA_H * 2u)
/* DMA capture buffer = frame + 2,048 B slack (same as the ENTC firmware: 40,448 B for 160x120). The slack lets the
 * driver tell an exact frame (DMA count left > 0) from an oversized one (count reaches 0). */
#ifndef FV_CAMERA_SLACK_BYTES
#define FV_CAMERA_SLACK_BYTES 2048u
#endif
#define FV_CAMERA_BUF_BYTES (FV_CAMERA_BYTES + FV_CAMERA_SLACK_BYTES)

typedef struct {
    fv_status_t status;          /* overall pipeline status of this cycle */
    fv_status_t camera_status, sensor_status;
    uint32_t image_flags;        /* fv_image_check() flags */
    float image_detail;          /* fv_image_detail() of the model input (presence gate) */
    int fruit_present;           /* 1 = presence gate passed (fruit shown), 0 = NO FRUIT / UNKNOWN */
    fv_image_result_t image;
    fv_sensor_check_t sensor_check;
    fv_risk_t risk;
    fv_oled_text_t oled;
    char serial[384];
    int serial_len;              /* -1 if the line did not fit */
} fv_cycle_t;

fv_status_t fv_app_init(const uint8_t *model_data, uint8_t *persistent, size_t persistent_bytes,
                        uint8_t *nonpersistent, size_t nonpersistent_bytes);
/* One full measurement cycle. Never reports values from a failed stage as predicted. */
fv_status_t fv_app_cycle(fv_cycle_t *out);

#endif
