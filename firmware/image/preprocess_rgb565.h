/* Camera frame -> Model 1/3 int8 input tensor (portable C99, no heap, integer-only).
 *
 * Input : W x H RGB565 frame as captured (2 bytes/pixel). `big_endian_pixels` = 1 if the first
 *         byte of each pixel in memory is the high byte (typical for OV2640 RGB565 via DCMI byte
 *         order); this MUST be confirmed on the real camera configuration.
 * Steps : centre-square crop (side = min(W, H)) -> bilinear resize to 80x80 (Q16 fixed point,
 *         pixel-centre aligned) -> RGB565 to 8-bit by bit replication -> int8 = value - 128.
 * The -128 offset matches the INT8 model input quantisation (scale 1.0, zero point -128) of
 * models/experimental/tflite/combined_int8.tflite (verified with TFLM on the host).
 *
 * Differences from training preprocessing (documented, measured as a host proxy in
 * docs/STM32_MEMORY_PLAN.md): no anti-aliasing filter, RGB565 colour quantisation, and the
 * camera's own ISP/scaler. Not validated on OV2640 images.
 */
#ifndef FV_PREPROCESS_RGB565_H
#define FV_PREPROCESS_RGB565_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FV_IN_W 80
#define FV_IN_H 80
#define FV_IN_BYTES (FV_IN_W * FV_IN_H * 3)

/* Returns 0 on success, -1 on invalid arguments (null pointers, side < 8).
 * `src` and `dst` must not overlap. */
int fv_rgb565_to_input_int8(const uint8_t *src, int w, int h, int big_endian_pixels, int8_t *dst);

#ifdef __cplusplus
}
#endif
#endif
