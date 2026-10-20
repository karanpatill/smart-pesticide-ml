/* Host test: camera tuning register builder (drivers/fv_cam_tune.c) and the rolling seqlock capture (app/fv_capture.c
 * built with -DFV_DIAG_ROLLING). Prints PASS/FAIL lines + END; exit code 1 on any failure. */
#include <stdio.h>
#include <string.h>

#include "fv_cam_tune.h"
#include "fv_capture.h"

#define CHECK(cond, name) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "PASS" : "FAIL", name); fails += !ok_; } while (0)

/* value written to reg in bank (simulates the OV2640 bank register 0xFF); -1 if never written */
static int reg_in_bank(const fv_cam_reg_t *r, int n, int bank, int reg) {
    int b = -1, v = -1;
    for (int i = 0; i < n; ++i) {
        if (r[i].reg == 0xFF) { b = r[i].val; continue; }
        if (b == bank && r[i].reg == reg) v = r[i].val;
    }
    return v;
}

static fv_capture_t cap;
static int8_t in_a[19200], raw_a[40];

int main(void) {
    int fails = 0;
    fv_cam_reg_t r[FV_CAM_TUNE_MAX_PAIRS + 4];

    int n = fv_cam_tune_pairs(0, 0, 0, 0, r, FV_CAM_TUNE_MAX_PAIRS);
    CHECK(n > 0 && reg_in_bank(r, n, 0, 0xC3) == 0xFD && reg_in_bank(r, n, 0, 0xC7) == 0x10 &&
          reg_in_bank(r, n, 0, 0x7D) == 0x00 && reg_in_bank(r, n, 1, 0x24) == 0x40 && reg_in_bank(r, n, 1, 0x25) == 0x38 &&
          reg_in_bank(r, n, 1, 0x26) == 0x82 && reg_in_bank(r, n, 0, 0xCC) == -1, "defaults_equal_entc");
    CHECK(r[0].reg == 0xFF && r[0].val == 0x00 && r[n - 1].reg == 0xFF && r[n - 1].val == 0x00, "starts_and_ends_in_dsp_bank");

    n = fv_cam_tune_pairs(1, 0, 0, 0, r, FV_CAM_TUNE_MAX_PAIRS);
    CHECK(reg_in_bank(r, n, 0, 0xC3) == 0xFF, "lenc_on_sets_ctrl1_bit1");
    n = fv_cam_tune_pairs(0, 1, 0, 0, r, FV_CAM_TUNE_MAX_PAIRS);
    CHECK(reg_in_bank(r, n, 0, 0xC7) == 0x00 && reg_in_bank(r, n, 0, 0xCC) == -1, "awb_auto");
    n = fv_cam_tune_pairs(0, 4, 0, 0, r, FV_CAM_TUNE_MAX_PAIRS);
    CHECK(reg_in_bank(r, n, 0, 0xC7) == 0x40 && reg_in_bank(r, n, 0, 0xCC) == 0x52 && reg_in_bank(r, n, 0, 0xCD) == 0x41 &&
          reg_in_bank(r, n, 0, 0xCE) == 0x66, "awb_office_manual_gains");
    n = fv_cam_tune_pairs(0, 0, 5, 0, r, FV_CAM_TUNE_MAX_PAIRS);
    int sat_ok = 0;
    for (int i = 0; i + 2 < n; ++i)
        if (r[i].reg == 0x7C && r[i].val == 0x03 && r[i + 1].reg == 0x7D && r[i + 1].val == 0x68 && r[i + 2].val == 0x68) sat_ok = 1;
    CHECK(sat_ok && reg_in_bank(r, n, 0, 0x7C) == 0x03, "saturation_plus2");
    n = fv_cam_tune_pairs(0, 0, 0, 5, r, FV_CAM_TUNE_MAX_PAIRS);
    CHECK(reg_in_bank(r, n, 1, 0x24) == 0x58 && reg_in_bank(r, n, 1, 0x25) == 0x50 && reg_in_bank(r, n, 1, 0x26) == 0x92, "ae_plus2");

    int max_n = 0, all_ok = 1;
    for (uint32_t l = 0; l < FV_TUNE_LENC_N; ++l)
        for (uint32_t a = 0; a < FV_TUNE_AWB_N; ++a)
            for (uint32_t s = 0; s < FV_TUNE_SAT_N; ++s)
                for (uint32_t e = 0; e < FV_TUNE_AE_N; ++e) {
                    const int k = fv_cam_tune_pairs(l, a, s, e, r, FV_CAM_TUNE_MAX_PAIRS);
                    if (k <= 0 || k > FV_CAM_TUNE_MAX_PAIRS) all_ok = 0;
                    if (k > max_n) max_n = k;
                    for (int i = 0; i < k; ++i)        /* only the tuning registers, never DCMI format/size/clock */
                        if (!r[i].reg || !strchr("\xFF\xC3\xC7\xCC\xCD\xCE\x7C\x7D\x24\x25\x26", r[i].reg)) all_ok = 0;
                }
    CHECK(all_ok && max_n <= FV_CAM_TUNE_MAX_PAIRS, "all_combinations_bounded_and_whitelisted");

    memset(r, 0xAB, sizeof r);
    CHECK(fv_cam_tune_pairs(2, 0, 0, 0, r, FV_CAM_TUNE_MAX_PAIRS) == -1 && fv_cam_tune_pairs(0, 6, 0, 0, r, 24) == -1 &&
          fv_cam_tune_pairs(0, 0, 6, 0, r, 24) == -1 && fv_cam_tune_pairs(0, 0, 0, 6, r, 24) == -1 &&
          fv_cam_tune_pairs(0xFFFFFFFFu, 0, 0, 0, r, 24) == -1 && fv_cam_tune_pairs(0, 0, 0, 0, NULL, 24) == -1 &&
          r[0].reg == 0xAB, "out_of_range_rejected_nothing_written");
    CHECK(fv_cam_tune_pairs(0, 0, 0, 0, r, 3) == -1 && r[0].reg == 0xAB, "small_buffer_rejected");

    /* rolling capture seqlock */
    for (int i = 0; i < 19200; ++i) in_a[i] = (int8_t)i;
    for (int i = 0; i < 40; ++i) raw_a[i] = (int8_t)i;
    fv_snapshot_stage(&cap, 1, in_a, 1, 2, 3);
    CHECK(cap.magic == FV_CAPTURE_MAGIC && (cap.seq & 1u), "rolling_odd_while_writing");
    fv_snapshot_commit(&cap, 1, raw_a, 1);
    CHECK(cap.seq == 2 && !memcmp(cap.raw, raw_a, 40) && !memcmp(cap.input, in_a, sizeof in_a), "rolling_even_when_complete");
    fv_snapshot_stage(&cap, 2, in_a, 1, 2, 3);        /* staged, inference rejected: no commit */
    fv_snapshot_stage(&cap, 3, in_a, 1, 2, 3);        /* next cycle stages again: must stay odd */
    CHECK(cap.seq == 3, "uncommitted_stage_stays_odd");
    fv_snapshot_commit(&cap, 3, raw_a, 1);
    fv_snapshot_commit(&cap, 3, raw_a, 1);            /* duplicate commit must not flip parity */
    CHECK(cap.seq == 4, "commit_once_per_stage");
    printf("END\n");
    return fails ? 1 : 0;
}
