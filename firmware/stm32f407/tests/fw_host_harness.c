/* Host test harness for the STM32F407 application modules (no hardware).
 * Line protocol on stdin, one result line per command on stdout (driven by tests/test_fw_*.py):
 *   R q0 .. q39                     -> fv_result_from_raw on int8 outputs (fv_head_t order, 5 slots/head)
 *   S has_tcs has_mq has_ph has_temp has_rh r g b c atime mq unit warm ph t rh origin calib
 *                                   -> fv_sensor_validate + fv_risk_estimate
 *   I <38400 hex chars>             -> fv_image_check on an 80x80x3 int8 input
 *   D w h                           -> fv_frame_dims_check
 *   O <R-args...> | S-args | flags | status   (see report_cmd) -> OLED lines + serial line
 *   E                               -> error-handling checks (prints PASS/FAIL lines)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fv_app.h"
#include "fv_arena_reuse.h"
#include "fv_image_check.h"
#include "fv_platform.h"
#include "fv_presence.h"
#include "fv_report.h"
#include "fv_result.h"
#include "fv_sensor.h"
#include "preprocess_rgb565.h"

/* minimal portable tokenizer (strtok_r is not in every host libc) */
static int sep(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
static char *tok(char **s) {
    char *p = *s;
    while (*p && sep(*p)) ++p;
    if (!*p) { *s = p; return NULL; }
    char *b = p;
    while (*p && !sep(*p)) ++p;
    if (*p) *p++ = '\0';
    *s = p;
    return b;
}

static int parse_raw(char **sp, fv_vision_raw_t *raw) {
    for (int i = 0; i < FV_N_HEADS * FV_MAX_CLASSES; ++i) {
        char *t = tok(sp);
        if (!t) return -1;
        raw->q[i / FV_MAX_CLASSES][i % FV_MAX_CLASSES] = (int8_t)atoi(t);
    }
#ifdef FV_PRESENCE_OUTPUT_INDEX
    raw->presence_raw[0] = -128;
    raw->presence_raw[1] = 127; /* default: fruit present */
#endif
    return 0;
}

static int parse_sensor(char **sp, fv_sensor_record_t *r) {
    char *t[19];
    for (int i = 0; i < 19; ++i) if (!(t[i] = tok(sp))) return -1;
    memset(r, 0, sizeof *r);
    r->has_tcs = (uint8_t)atoi(t[0]); r->has_mq = (uint8_t)atoi(t[1]); r->has_ph = (uint8_t)atoi(t[2]);
    r->has_temp = (uint8_t)atoi(t[3]); r->has_rh = (uint8_t)atoi(t[4]);
    r->tcs_r = atoi(t[5]); r->tcs_g = atoi(t[6]); r->tcs_b = atoi(t[7]); r->tcs_c = atoi(t[8]);
    r->tcs_atime = (int16_t)atoi(t[9]);
    r->mq135 = strtof(t[10], NULL); r->mq_unit = (uint8_t)atoi(t[11]); r->mq_warmup_s = strtof(t[12], NULL);
    r->ph = strtof(t[13], NULL); r->temp_c = strtof(t[14], NULL); r->rh_pct = strtof(t[15], NULL);
    r->origin = (uint8_t)atoi(t[16]); r->has_calibration_profile = (uint8_t)atoi(t[17]);
    return atoi(t[18]);   /* 1 = pass NULL record */
}

static void print_result(const fv_image_result_t *o) {
    printf("%d %d %.9g %d %d %.9g %d %d %.9g %d %d %d %d %.9g %d %d %d %lu\n", o->fruit_state, o->fruit,
           (double)o->fruit_conf, o->condition_state, o->condition, (double)o->condition_conf, o->quality_state,
           o->grade, (double)o->grade_conf, o->grade_binary, o->quality_head, o->shelf_state, o->stage,
           (double)o->stage_conf, o->shelf_lo_days, o->shelf_hi_days, o->stage_head, (unsigned long)o->consistency);
}

static int hexval(char c) { return c <= '9' ? c - '0' : (c | 32) - 'a' + 10; }

#define CHECK(cond, name) printf("%s %s\n", (cond) ? "PASS" : "FAIL", name)

static void errors_cmd(void) {
    fv_image_result_t img;
    fv_vision_raw_t raw;
    memset(&raw, 0, sizeof raw);
    CHECK(fv_result_from_raw(NULL, &img) == FV_ERR_ARG, "result_null_raw");
    CHECK(fv_result_from_raw(&raw, NULL) == FV_ERR_ARG, "result_null_out");
    fv_result_set_unavailable(NULL);
    fv_result_set_unavailable(&img);
    CHECK(img.fruit_state == FV_STATE_UNAVAILABLE && img.quality_state == FV_STATE_UNAVAILABLE &&
          img.shelf_lo_days == -1, "result_unavailable");
    fv_sensor_check_t k = fv_sensor_validate(NULL);
    CHECK(k.errors != 0, "sensor_null_invalid");
    fv_risk_t rk = fv_risk_estimate(NULL, NULL);
    CHECK(rk.state == FV_STATE_UNAVAILABLE && rk.reasons == FV_RR_NO_RECORD && rk.category == -1, "risk_null");
    fv_sensor_record_t rec; memset(&rec, 0, sizeof rec);
    rk = fv_risk_estimate(&rec, NULL);
    CHECK(rk.state == FV_STATE_UNAVAILABLE && rk.reasons == FV_RR_INVALID, "risk_null_check");
    CHECK(fv_image_check(NULL, NULL) & FV_IC_REJECT_MASK, "imgcheck_null_rejects");
    char small[8];
    CHECK(fv_report_serial(&img, &rk, &k, 0, FV_OK, small, sizeof small) == -1, "serial_truncation");
    CHECK(fv_report_serial(&img, &rk, &k, 0, FV_OK, NULL, 10) == -1, "serial_null_buf");
    /* pending platform layer must refuse, never fake data */
    CHECK(fv_platform_init() == FV_ERR_NOT_IMPLEMENTED, "platform_init_pending");
    CHECK(fv_camera_init(96, 96) == FV_ERR_NOT_IMPLEMENTED, "camera_init_pending");
    uint8_t fb[32]; fv_frame_info_t fi = {0, 0, 0};
    CHECK(fv_camera_capture_rgb565(fb, sizeof fb, &fi) == FV_ERR_NOT_IMPLEMENTED, "camera_capture_pending");
    CHECK(fv_sensors_read(&rec) == FV_ERR_NOT_IMPLEMENTED, "sensors_read_pending");
    fv_oled_text_t ot; memset(&ot, 0, sizeof ot);
    CHECK(fv_oled_show(&ot) == FV_ERR_NOT_IMPLEMENTED, "oled_pending");
    CHECK(fv_serial_write("x", 1) == FV_ERR_NOT_IMPLEMENTED, "serial_pending");
    /* app without a model: cycle reports model error, image UNAVAILABLE, risk UNAVAILABLE */
    static fv_cycle_t cyc;
    fv_status_t st = fv_app_cycle(&cyc);
    CHECK(st == FV_ERR_MODEL && cyc.image.fruit_state == FV_STATE_UNAVAILABLE &&
          cyc.risk.state == FV_STATE_UNAVAILABLE && cyc.sensor_status == FV_ERR_NOT_IMPLEMENTED, "app_cycle_no_model");
    CHECK(fv_app_cycle(NULL) == FV_ERR_ARG, "app_cycle_null");
    CHECK(fv_app_init(NULL, NULL, 0, NULL, 0) != FV_OK, "app_init_null_model");
    /* camera window: no room -> NULL */
    static uint8_t arena[1024];
    fv_range_t busy[1] = {{arena, 1000}};
    CHECK(fv_select_camera_window(arena, sizeof arena, busy, 1, 512, 16) == NULL, "window_not_found");
    /* preprocessing argument checks */
    static int8_t in[FV_IN_BYTES];
    CHECK(fv_rgb565_to_input_int8(NULL, 96, 96, 0, in) != 0, "preprocess_null_src");
    CHECK(fv_rgb565_to_input_int8(fb, 0, 96, 0, in) != 0, "preprocess_zero_width");
    printf("END\n");
}

int main(void) {
    static char line[1 << 17];
    while (fgets(line, sizeof line, stdin)) {
        char *sp = line;
        char *cmd = tok(&sp);
        if (!cmd) continue;
        if (!strcmp(cmd, "R")) {
            fv_vision_raw_t raw; fv_image_result_t o;
            if (parse_raw(&sp, &raw)) { puts("BAD"); continue; }
            fv_result_from_raw(&raw, &o);
            print_result(&o);
        } else if (!strcmp(cmd, "S")) {
            fv_sensor_record_t r;
            const int null_rec = parse_sensor(&sp, &r);
            if (null_rec < 0) { puts("BAD"); continue; }
            fv_sensor_check_t k = fv_sensor_validate(null_rec ? NULL : &r);
            fv_risk_t rk = fv_risk_estimate(null_rec ? NULL : &r, &k);
            printf("%lu %lu %u %u %d %d %.9g %.9g %.9g %lu\n", (unsigned long)k.errors, (unsigned long)k.warnings,
                   k.ood_mask, k.value_mask, rk.state, rk.category, (double)rk.probs[0], (double)rk.probs[1],
                   (double)rk.probs[2], (unsigned long)rk.reasons);
        } else if (!strcmp(cmd, "I")) {
            static int8_t in[FV_IN_BYTES];
            char *h = tok(&sp);
            if (!h || strlen(h) != 2 * FV_IN_BYTES) { puts("BAD"); continue; }
            for (int i = 0; i < FV_IN_BYTES; ++i) in[i] = (int8_t)(hexval(h[2 * i]) << 4 | hexval(h[2 * i + 1]));
            fv_image_stats_t s;
            const uint32_t f = fv_image_check(in, &s);
            printf("%lu %.9g %.9g %.9g %.9g %.9g %.9g\n", (unsigned long)f, (double)s.lum_mean, (double)s.lum_std,
                   (double)s.lag1_autocorr, (double)s.chroma_mean_abs, (double)s.clipped_fraction,
                   (double)fv_image_detail(in));
        } else if (!strcmp(cmd, "P")) {
            /* P <40 raw ints> <detail> [presence_q1] -> presence gate applied after fv_result_from_raw; then OLED rows */
            fv_vision_raw_t raw; fv_image_result_t o;
            if (parse_raw(&sp, &raw)) { puts("BAD"); continue; }
            char *td = tok(&sp);
            if (!td) { puts("BAD"); continue; }
#ifdef FV_PRESENCE_OUTPUT_INDEX
            char *tp = tok(&sp);
            if (tp) {
                raw.presence_raw[1] = (int8_t)atoi(tp);
                raw.presence_raw[0] = (int8_t)(-raw.presence_raw[1]);
            }
#endif
            fv_result_from_raw(&raw, &o);
            const int shown = fv_presence_apply(&o, strtof(td, NULL));
            printf("PRES %d ", shown);
            print_result(&o);
            fv_risk_t rk; memset(&rk, 0, sizeof rk); rk.state = FV_STATE_UNCERTAIN; rk.category = -1;
            fv_oled_text_t ot;
            fv_report_oled(&o, &rk, 0, FV_OK, &ot);
            printf("OLED %d", ot.n);
            for (int i = 0; i < ot.n; ++i) printf("|%s", ot.line[i]);
            printf("\n");
        } else if (!strcmp(cmd, "O")) {
            /* O <40 raw ints> <19 sensor fields> <image_flags> <status> <img_unavailable> */
            fv_vision_raw_t raw; fv_image_result_t o; fv_sensor_record_t r;
            if (parse_raw(&sp, &raw)) { puts("BAD"); continue; }
            const int null_rec = parse_sensor(&sp, &r);
            char *tf = tok(&sp), *ts = tok(&sp), *tu = tok(&sp);
            if (null_rec < 0 || !tf || !ts || !tu) { puts("BAD"); continue; }
            fv_result_from_raw(&raw, &o);
            if (atoi(tu)) fv_result_set_unavailable(&o);
            fv_sensor_check_t k = fv_sensor_validate(null_rec ? NULL : &r);
            fv_risk_t rk = fv_risk_estimate(null_rec ? NULL : &r, &k);
            fv_oled_text_t ot;
            fv_report_oled(&o, &rk, (uint32_t)strtoul(tf, NULL, 0), (fv_status_t)atoi(ts), &ot);
            if (!null_rec) fv_report_oled_sensors(&ot, &r);
            char buf[384];
            const int n = fv_report_serial(&o, &rk, &k, (uint32_t)strtoul(tf, NULL, 0), (fv_status_t)atoi(ts), buf,
                                           sizeof buf);
            printf("OLED %d", ot.n);
            for (int i = 0; i < ot.n; ++i) printf("|%s", ot.line[i]);
            printf("\nSERIAL %d %s", n, n > 0 ? buf : "\r\n");
        } else if (!strcmp(cmd, "D")) {
            char *tw = tok(&sp), *th = tok(&sp);
            if (!tw || !th) { puts("BAD"); continue; }
            printf("%lu\n", (unsigned long)fv_frame_dims_check(atoi(tw), atoi(th)));
        } else if (!strcmp(cmd, "E")) {
            errors_cmd();
        } else {
            puts("BAD");
        }
        fflush(stdout);
    }
    return 0;
}
