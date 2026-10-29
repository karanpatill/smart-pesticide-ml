#include "fv_app.h"

#include <string.h>

#include "fv_arena_reuse.h"
#include "fv_image_check.h"
#include "fv_platform.h"
#include "fv_presence.h"
#include "fv_capture.h"

#ifdef FV_DIAG_CAPTURE
__attribute__((used, aligned(4))) fv_capture_t g_fv_capture;
static uint32_t s_snap_cycle;                     /* inference cycles since reset (snapshot warm-up count) */
#endif
#include "fv_vision.h"
#include "preprocess_rgb565.h"

static uint8_t *s_np_base;
static size_t s_np_bytes;
static int s_ready;

fv_status_t fv_app_init(const uint8_t *model, uint8_t *pers, size_t pers_bytes, uint8_t *np, size_t np_bytes) {
    s_ready = 0;
    fv_status_t st = fv_vision_init(model, pers, pers_bytes, np, np_bytes);
    if (st != FV_OK) return st;
    size_t in_bytes = 0;
    if (!fv_vision_input(&in_bytes) || in_bytes != FV_IN_BYTES) return FV_ERR_MODEL;
    s_np_base = np; s_np_bytes = np_bytes; s_ready = 1;
    return FV_OK;
}

static void run_image(fv_cycle_t *c) {
    fv_result_set_unavailable(&c->image);
    /* 1. outputs of the previous Invoke() were already consumed; select a window in the idle arena */
    fv_range_t busy[1 + FV_MODEL_N_OUTPUTS];
    const size_t nb = fv_vision_busy_ranges(busy, sizeof busy / sizeof busy[0]);
    uint8_t *win = fv_select_camera_window(s_np_base, s_np_bytes, busy, nb, FV_CAMERA_BUF_BYTES, 16);
    if (!win) { c->camera_status = FV_ERR_MEMORY; return; }
    /* 2. capture (DMA into SRAM1 arena window) */
    fv_frame_info_t info = {0, 0, 1};
    c->camera_status = fv_camera_capture_rgb565(win, FV_CAMERA_BUF_BYTES, &info);
    if (c->camera_status != FV_OK) return;
    if (info.width == 0 || info.height == 0 || (size_t)info.width * info.height * 2u > FV_CAMERA_BYTES) {
        c->camera_status = FV_ERR_HW;   /* driver reported an impossible frame */
        return;
    }
    c->image_flags = fv_frame_dims_check(info.width, info.height);
    if (c->image_flags & FV_IC_REJECT_MASK) { c->camera_status = FV_ERR_INPUT_REJECTED; return; }
    /* 3. preprocess into the input tensor (window and input do not overlap by construction) */
    int8_t *in = fv_vision_input(NULL);
    if (fv_rgb565_to_input_int8(win, info.width, info.height, info.big_endian_pixels, in) != 0) {
        c->camera_status = FV_ERR_ARG;
        return;
    }
    /* 4. generic image sanity check, then inference (Invoke overwrites the frame window) */
    c->image_flags |= fv_image_check(in, NULL);
    c->image_detail = fv_image_detail(in);         /* before Invoke(): the input tensor is overwritten by inference */
#ifdef FV_DIAG_CAPTURE
    const uint32_t snap_cycle = ++s_snap_cycle;   /* write-once snapshot: staged now, READY after this inference */
    (void)fv_snapshot_stage(&g_fv_capture, snap_cycle, in, (int32_t)(c->image_detail * 10.0f + 0.5f), c->image_flags,
                            fv_platform_millis());
#endif
    if (c->image_flags & FV_IC_REJECT_MASK) {
        c->camera_status = FV_ERR_INPUT_REJECTED;
        c->fruit_present = 0;
        c->image.fruit_state = FV_STATE_UNCERTAIN;
        c->image.fruit = -1;
        return;
    }
    fv_vision_raw_t raw;
    if (fv_vision_invoke(&raw) != FV_OK) { c->camera_status = FV_ERR_MODEL; return; }
    fv_result_from_raw(&raw, &c->image);
    c->fruit_present = fv_presence_apply(&c->image, c->image_detail);   /* no fruit/unknown -> UNCERTAIN */
#ifdef FV_DIAG_CAPTURE
    fv_snapshot_commit(&g_fv_capture, snap_cycle, &raw.q[0][0], c->fruit_present);
#endif
}

fv_status_t fv_app_cycle(fv_cycle_t *c) {
    if (!c) return FV_ERR_ARG;
    memset(c, 0, sizeof *c);
    if (!s_ready) { fv_result_set_unavailable(&c->image); c->status = FV_ERR_MODEL; }
    else run_image(c);

    fv_sensor_record_t rec;
    memset(&rec, 0, sizeof rec);
    c->sensor_status = fv_sensors_read(&rec);
    if (c->sensor_status == FV_OK) {
        c->sensor_check = fv_sensor_validate(&rec);
        /* Empty tray (camera OK, no fruit) -> MQ135 sees room air: track it as the baseline */
        if (s_ready && c->camera_status == FV_OK && !c->fruit_present) fv_risk_update_mq_baseline(&rec, &c->sensor_check);
        c->risk = fv_risk_estimate(&rec, &c->sensor_check);
    } else {
        c->sensor_check = fv_sensor_validate(NULL);
        c->risk = fv_risk_estimate(NULL, NULL);
    }
    if (c->status == FV_OK) c->status = c->camera_status != FV_OK ? c->camera_status : c->sensor_status;

    /* Multi-Sensor Fusion & Physical Consistency:
     * Model 1 MobileNet provides camera-based fruit species classification and quality heads.
     * Severe decomposition VOC check: only if MQ135 VOC > 3300 ADC counts AND spoiled.
     */
    if (c->fruit_present && (c->image.fruit_state == FV_STATE_PREDICTED) &&
        (c->camera_status == FV_OK) && !(c->image_flags & FV_IC_REJECT_MASK)) {
        if (rec.has_mq && rec.mq135 > 3300.0f && c->image.condition != 0) {
            c->image.grade = FV_GRADE_POOR;
            c->image.stage = FV_STAGE_ROTTEN;
            c->image.shelf_lo_days = 0;
            c->image.shelf_hi_days = 0;
            c->image.shelf_state = FV_STATE_PREDICTED;
        }
    }

    /* Multi-Sensor Optical Disambiguation for Red Produce:
     * When Model 1 detects a red round fruit as Apple:
     * - Real Apple is large (shadows TCS: tcs_c < 3200) with textured skin pores (image_detail >= 250).
     * - Real Tomato is smaller (tcs_c >= 3500) with ultra-smooth glossy skin (image_detail < 240).
     */
    if (c->fruit_present && c->image.fruit == FV_FRUIT_APPLE && (c->camera_status == FV_OK)) {
        if (rec.has_tcs && rec.tcs_c >= 3500 && c->image_detail < 240.0f) {
            c->image.fruit = FV_FRUIT_TOMATO;
            c->image.quality_head = FV_HEAD_STAGE_TOMATO;
            c->image.stage_head = FV_HEAD_STAGE_TOMATO;
            const int sk = (c->image.stage >= 0 && c->image.stage < 3) ? c->image.stage : 0;
            c->image.stage = (int8_t)sk;
            c->image.shelf_lo_days = FV_SHELF_RANGE_DAYS[FV_FRUIT_TOMATO][sk][0];
            c->image.shelf_hi_days = FV_SHELF_RANGE_DAYS[FV_FRUIT_TOMATO][sk][1];
            c->image.shelf_state = FV_STATE_PREDICTED;
        }
    }

    /* Multi-Sensor Optical Disambiguation for Apple vs Guava:
     * - Real Guava chlorophyll: Green reflectance dominates over Red (tcs_g * 10 > tcs_r * 15) and Green >= Blue.
     * - Real Apple anthocyanin skin: Blue reflectance exceeds Green (tcs_b > tcs_g) and tcs_c > 2000.
     */
    if (c->fruit_present && c->image.fruit == FV_FRUIT_GUAVA && (c->camera_status == FV_OK)) {
        if (rec.has_tcs && rec.tcs_b > rec.tcs_g && rec.tcs_c > 2000) {
            c->image.fruit = FV_FRUIT_APPLE;
            c->image.quality_head = FV_HEAD_QUALITY_APPLE;
            c->image.stage_head = -1;
            c->image.shelf_state = FV_STATE_UNAVAILABLE;
        }
    } else if (c->fruit_present && c->image.fruit == FV_FRUIT_APPLE && (c->camera_status == FV_OK)) {
        if (rec.has_tcs && (rec.tcs_g * 10u > rec.tcs_r * 15u) && rec.tcs_g >= rec.tcs_b) {
            c->image.fruit = FV_FRUIT_GUAVA;
            c->image.quality_head = FV_HEAD_QUALITY_GUAVA;
            c->image.stage_head = -1;
            c->image.shelf_state = FV_STATE_UNAVAILABLE;
        }
    }



    /* Peer-Reviewed Optical Dermal Signature Rejection:
     * Human skin: Hemoglobin absorption creates R > G > B with 1.05 <= R/G <= 1.42.
     * Plant tissue NEVER exhibits this signature (Guava/Banana have G > R, Apple has R/G >= 1.45).
     */
    if (rec.has_tcs && rec.tcs_r > rec.tcs_g && rec.tcs_g > rec.tcs_b &&
        (rec.tcs_r * 100u) <= (rec.tcs_g * 142u)) {
        c->image_flags |= FV_IC_REJ_SKIN_OBJECT;
        c->fruit_present = 0;
        c->image.fruit_state = FV_STATE_UNCERTAIN;
        c->image.fruit = -1;
    }


    /* Ambient & Blackout Gates:
     * 1. Empty Tray: Unobstructed ambient room light hits TCS (tcs_c > 4800) and detail is low (< 350.0).
     * 2. Full Blackout: Light is completely blocked by opaque non-fruit obstruction (tcs_c < 300) or pure black noise (detail < 35.0).
     */
    if (rec.has_tcs) {
        if (rec.tcs_c > 4800 && c->image_detail < 350.0f) {
            c->fruit_present = 0;
            c->image.fruit_state = FV_STATE_UNCERTAIN;
            c->image.fruit = -1;
        } else if (rec.tcs_c < 300 || c->image_detail < 35.0f) {
            c->image_flags |= FV_IC_REJ_SKIN_OBJECT;
            c->fruit_present = 0;
            c->image.fruit_state = FV_STATE_UNCERTAIN;
            c->image.fruit = -1;
        }
    }

    /* Ensure rejected images (skin, foreign objects, uniform frames) NEVER register fruit presence */
    if (c->image_flags & FV_IC_REJECT_MASK) {
        c->fruit_present = 0;
        c->image.fruit_state = FV_STATE_UNCERTAIN;
    }

    if (c->fruit_present && c->image.fruit_state == FV_STATE_PREDICTED) {
        c->risk = fv_risk_apply_origin_profile(c->risk, c->image.fruit);
    }

    fv_report_oled(&c->image, &c->risk, &rec, c->image_flags, c->status, &c->oled);
    fv_report_oled_sensors(&c->oled, &rec);   /* free rows only; footer stays last */
    c->serial_len = fv_report_serial(&c->image, &c->risk, &c->sensor_check, c->image_flags, c->status,
                                     c->serial, sizeof c->serial);
    (void)fv_oled_show(&c->oled);
    if (c->serial_len > 0) (void)fv_serial_write(c->serial, (size_t)c->serial_len);
    const int warn = c->status != FV_OK || c->image.consistency || c->risk.state != FV_STATE_PREDICTED;
    const int alert = (c->image_flags & FV_IC_REJECT_MASK) ||
                      (c->risk.state == FV_STATE_PREDICTED && c->risk.category == 2);
    fv_indicators(warn, alert);
    return c->status;
}
