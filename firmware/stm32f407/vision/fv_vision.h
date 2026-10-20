/* Model 1 + Model 3 inference (one shared-backbone INT8 graph) via TensorFlow Lite Micro.
 * C API over a C++ implementation (fv_vision.cc). Uses TFLM's SPLIT allocator:
 *   persistent arena     -> CCM   (TFLM-owned CPU-only data: allocator, planner, eval tensors,
 *                                  node structs, per-op kernel data)
 *   non-persistent arena -> SRAM1 (activations incl. input/output tensors, kernel scratch,
 *                                  temporary allocations during AllocateTensors)
 * Int8-only CMSIS-NN kernel registrations (outputs verified identical on the host).
 */
#ifndef FV_VISION_H
#define FV_VISION_H

#include "fv_arena_reuse.h"
#include "fv_common.h"
#include "fv_result.h"

#ifdef __cplusplus
extern "C" {
#endif

/* model_data must be 16-byte aligned and stay valid (flash). Checks the model against the
 * generated header (input 80x80x3 int8 scale/zero-point, 8 outputs with expected sizes). */
fv_status_t fv_vision_init(const uint8_t *model_data, uint8_t *persistent, size_t persistent_bytes,
                           uint8_t *nonpersistent, size_t nonpersistent_bytes);
int8_t *fv_vision_input(size_t *bytes);
/* Busy ranges (input + outputs) for fv_select_camera_window(); returns count written. */
size_t fv_vision_busy_ranges(fv_range_t *out, size_t max);
fv_status_t fv_vision_invoke(fv_vision_raw_t *out);
/* Arena usage after init (bytes), for on-target verification of the memory plan. */
size_t fv_vision_arena_used_bytes(void);

#ifdef __cplusplus
}
#endif
#endif
