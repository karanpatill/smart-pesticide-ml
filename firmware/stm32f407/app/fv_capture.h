/* DIAGNOSTIC build only (-DFV_DIAG_CAPTURE): keeps a copy of exactly what the fruit model saw (the 80x80x3 int8 input
 * after camera preprocessing) and the model's raw int8 outputs, so they can be read over SWD (read-only, hot-plug) and
 * compared bit-exact with the Python model (tools/firmware/read_capture.py). Inference is unchanged.
 * Write-once snapshot (fv_app_v7_diag): the block is filled by the first complete inference after FV_SNAPSHOT_SKIP
 * warm-up cycles; magic is set to FV_SNAPSHOT_READY only after input + outputs are fully written, and from then on the
 * block is never written again (until reset). A reader that sees READY therefore cannot get a torn copy. */
#ifndef FV_CAPTURE_H
#define FV_CAPTURE_H
#include <stdint.h>

#define FV_CAPTURE_MAGIC 0xCA97F00Du    /* v6_diag (rolling capture, seqlock) */
#define FV_SNAPSHOT_READY 0x534E4150u   /* "SNAP": v7_diag write-once snapshot complete */
#ifndef FV_SNAPSHOT_SKIP
#define FV_SNAPSHOT_SKIP 5u             /* inference cycles skipped first (camera auto-exposure settling) */
#endif

typedef struct {
    volatile uint32_t magic;    /* 0 until the snapshot is complete, then FV_SNAPSHOT_READY */
    volatile uint32_t seq;      /* inference cycle number the snapshot was taken at */
    uint32_t cycle_ms;          /* fv_platform_millis() when captured */
    int32_t detail_x10;         /* fv_image_detail x10 */
    uint32_t image_flags;
    int32_t fruit_present;      /* presence gate result */
    int8_t raw[40];             /* model outputs, fv_head_t order, 5 slots per head */
    int8_t input[19200];        /* 80x80x3 int8 model input (pixel = value + 128), RGB */
} fv_capture_t;

/* layout is read by tools/firmware/read_capture.py: keep it fixed */
typedef char fv_capture_size_check[(sizeof(fv_capture_t) == 19264u) ? 1 : -1];

/* Stage the model input into s if no snapshot is ready yet and cycle_no > FV_SNAPSHOT_SKIP. Returns 1 if staged. */
int fv_snapshot_stage(fv_capture_t *s, uint32_t cycle_no, const int8_t *in, int32_t detail_x10, uint32_t flags,
                      uint32_t ms);
/* Complete a staged snapshot with the outputs of the same inference and mark it READY (never written again). */
void fv_snapshot_commit(fv_capture_t *s, uint32_t cycle_no, const int8_t *raw40, int32_t fruit_present);

#ifdef FV_DIAG_CAPTURE
extern fv_capture_t g_fv_capture;
#endif

#endif
