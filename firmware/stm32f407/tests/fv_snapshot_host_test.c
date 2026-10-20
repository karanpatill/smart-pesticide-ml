/* Host test of the write-once diagnostic snapshot (app/fv_capture.c): warm-up skip, no READY without a commit of the
 * same cycle, never rewritten after READY, layout fixed, no writes outside the block. Prints PASS/FAIL lines + END. */
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "fv_capture.h"
#include "fv_result.h"
#include "preprocess_rgb565.h"

#define CHECK(cond, name) do { int ok_ = (cond); printf("%s %s\n", ok_ ? "PASS" : "FAIL", name); fails += !ok_; } while (0)

static struct { uint8_t pre[64]; fv_capture_t s; uint8_t post[64]; } g;
static int8_t in_a[FV_IN_BYTES], in_b[FV_IN_BYTES], in_c[FV_IN_BYTES];
static int8_t raw_b[40], raw_c[40];
static fv_capture_t frozen;

static int canaries_ok(void) {
    for (size_t i = 0; i < sizeof g.pre; ++i) if (g.pre[i] != 0xA5 || g.post[i] != 0x5A) return 0;
    return 1;
}

int main(void) {
    int fails = 0;
    memset(g.pre, 0xA5, sizeof g.pre); memset(g.post, 0x5A, sizeof g.post);
    for (int i = 0; i < FV_IN_BYTES; ++i) { in_a[i] = (int8_t)i; in_b[i] = (int8_t)(i * 7 + 3); in_c[i] = (int8_t)-i; }
    for (int i = 0; i < 40; ++i) { raw_b[i] = (int8_t)(100 - i); raw_c[i] = (int8_t)(i - 100); }

    CHECK(sizeof(fv_capture_t) == 19264 && offsetof(fv_capture_t, raw) == 24 && offsetof(fv_capture_t, input) == 64,
          "layout_matches_reader");
    CHECK(sizeof g.s.input == FV_IN_BYTES && sizeof g.s.raw == FV_N_HEADS * FV_MAX_CLASSES, "buffer_sizes_match_model");

    uint32_t cyc = 0;
    int staged = 0;
    for (cyc = 1; cyc <= FV_SNAPSHOT_SKIP; ++cyc) {
        staged |= fv_snapshot_stage(&g.s, cyc, in_a, 1, 2, 3);
        fv_snapshot_commit(&g.s, cyc, raw_b, 1);
    }
    CHECK(!staged && g.s.magic == 0 && g.s.seq == 0 && g.s.input[5] == 0, "warmup_cycles_skipped");

    CHECK(fv_snapshot_stage(&g.s, cyc, in_a, 10, 20, 30) == 1, "stage_after_warmup");
    CHECK(g.s.magic != FV_SNAPSHOT_READY, "staged_not_ready_before_commit");
    ++cyc;   /* that cycle's input was rejected / inference failed: no commit -> must be re-staged */
    CHECK(fv_snapshot_stage(&g.s, cyc, in_b, 361, 4096, 777) == 1, "restage_after_uncommitted_cycle");
    fv_snapshot_commit(&g.s, cyc - 1, raw_b, 0);
    CHECK(g.s.magic != FV_SNAPSHOT_READY, "commit_of_other_cycle_ignored");
    fv_snapshot_commit(&g.s, cyc, raw_b, 0);
    CHECK(g.s.magic == FV_SNAPSHOT_READY && g.s.seq == cyc, "ready_after_commit");
    CHECK(!memcmp(g.s.input, in_b, sizeof in_b) && !memcmp(g.s.raw, raw_b, sizeof raw_b) && g.s.detail_x10 == 361 &&
          g.s.image_flags == 4096 && g.s.cycle_ms == 777 && g.s.fruit_present == 0, "snapshot_input_and_outputs_consistent");

    memcpy(&frozen, &g.s, sizeof frozen);
    int restaged = 0;
    for (uint32_t k = cyc + 1; k < cyc + 200; ++k) {
        restaged |= fv_snapshot_stage(&g.s, k, in_c, 5, 6, 7);
        fv_snapshot_commit(&g.s, k, raw_c, 1);
    }
    CHECK(!restaged && !memcmp(&frozen, &g.s, sizeof frozen), "never_overwritten_after_ready");

    CHECK(fv_snapshot_stage(NULL, 99, in_a, 0, 0, 0) == 0 && fv_snapshot_stage(&g.s, 99, NULL, 0, 0, 0) == 0, "null_args");
    fv_snapshot_commit(NULL, 99, raw_b, 0);
    fv_snapshot_commit(&g.s, 99, NULL, 0);
    CHECK(canaries_ok(), "no_writes_outside_block");
    printf("END\n");
    return fails ? 1 : 0;
}
