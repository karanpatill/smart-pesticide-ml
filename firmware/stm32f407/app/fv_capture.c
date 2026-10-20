/* Write-once diagnostic snapshot (see fv_capture.h). Only linked into the diagnostic build. */
#include "fv_capture.h"

#include <string.h>

#ifdef FV_DIAG_ROLLING
/* Rolling capture (v8 camera tuning): every inference is copied; seqlock: seq odd while writing, even when complete.
 * An input staged without a commit (rejected / failed inference) keeps seq odd, so the reader rejects it. */
int fv_snapshot_stage(fv_capture_t *s, uint32_t cycle_no, const int8_t *in, int32_t detail_x10, uint32_t flags,
                      uint32_t ms) {
    (void)cycle_no;
    if (!s || !in) return 0;
    s->magic = FV_CAPTURE_MAGIC;
    s->seq |= 1u;                  /* odd: writing */
    __sync_synchronize();
    memcpy(s->input, in, sizeof s->input);
    s->detail_x10 = detail_x10;
    s->image_flags = flags;
    s->cycle_ms = ms;
    return 1;
}

void fv_snapshot_commit(fv_capture_t *s, uint32_t cycle_no, const int8_t *raw40, int32_t fruit_present) {
    (void)cycle_no;
    if (!s || !raw40 || !(s->seq & 1u)) return;
    memcpy(s->raw, raw40, sizeof s->raw);
    s->fruit_present = fruit_present;
    __sync_synchronize();
    s->seq++;                      /* even: complete */
    __sync_synchronize();
}
#else
int fv_snapshot_stage(fv_capture_t *s, uint32_t cycle_no, const int8_t *in, int32_t detail_x10, uint32_t flags,
                      uint32_t ms) {
    if (!s || !in || s->magic == FV_SNAPSHOT_READY || cycle_no <= FV_SNAPSHOT_SKIP) return 0;
    memcpy(s->input, in, sizeof s->input);
    s->detail_x10 = detail_x10;
    s->image_flags = flags;
    s->cycle_ms = ms;
    s->seq = cycle_no;
    return 1;
}

void fv_snapshot_commit(fv_capture_t *s, uint32_t cycle_no, const int8_t *raw40, int32_t fruit_present) {
    if (!s || !raw40 || s->magic == FV_SNAPSHOT_READY || s->seq != cycle_no) return;   /* staged by this cycle only */
    memcpy(s->raw, raw40, sizeof s->raw);
    s->fruit_present = fruit_present;
    __sync_synchronize();          /* all data stores complete before READY becomes visible (DMB on Cortex-M) */
    s->magic = FV_SNAPSHOT_READY;
    __sync_synchronize();
}
#endif
