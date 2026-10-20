/* Host-only stand-in for vision/fv_vision.cc (TFLM is not built on Windows). Behaves like a
 * vision module whose init has not succeeded: every call fails closed. The real fv_vision.cc is
 * built and exercised against TFLM in tools/firmware/build_fw_check.sh (WSL). */
#include "fv_vision.h"

fv_status_t fv_vision_init(const uint8_t *m, uint8_t *p, size_t pb, uint8_t *np, size_t npb) {
    (void)m; (void)p; (void)pb; (void)np; (void)npb;
    return FV_ERR_MODEL;
}
int8_t *fv_vision_input(size_t *bytes) { if (bytes) *bytes = 0; return 0; }
size_t fv_vision_busy_ranges(fv_range_t *out, size_t max) { (void)out; (void)max; return 0; }
fv_status_t fv_vision_invoke(fv_vision_raw_t *out) { (void)out; return FV_ERR_MODEL; }
size_t fv_vision_arena_used_bytes(void) { return 0; }
