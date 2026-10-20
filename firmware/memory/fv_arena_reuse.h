/* Safe reuse of the TFLM NON-PERSISTENT arena for the camera frame buffer (portable C99).
 *
 * Between inferences the non-persistent arena is idle except for the input tensor (must hold the
 * preprocessed image when Invoke() starts) and the output tensors (must be read after Invoke()).
 * The selector returns the lowest aligned window of `need` bytes inside the arena that overlaps
 * none of the `n_busy` busy ranges, or NULL (caller must then use a dedicated buffer).
 *
 * Required call order on target (buffer lifetimes):
 *   1. Invoke() finished -> read ALL outputs (they may be overwritten by step 3)
 *   2. select window (input/output pointers from the interpreter after AllocateTensors())
 *   3. DCMI DMA capture into the window      (arena must be in SRAM1/2: DMA2 cannot reach CCM)
 *   4. fv_rgb565_to_input_int8(window -> input tensor)   (window and input do not overlap)
 *   5. Invoke()  (overwrites the window; the frame is no longer needed)
 * The arena layout depends on the TFLM version/kernels; always select at runtime, never hard-code.
 */
#ifndef FV_ARENA_REUSE_H
#define FV_ARENA_REUSE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const uint8_t *ptr;
    size_t bytes;
} fv_range_t;

/* align must be a power of two (DCMI DMA word transfers: >= 4; use 16). */
uint8_t *fv_select_camera_window(uint8_t *arena, size_t arena_bytes, const fv_range_t *busy, size_t n_busy,
                                 size_t need, size_t align);

#ifdef __cplusplus
}
#endif
#endif
