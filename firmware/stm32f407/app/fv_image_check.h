/* Generic image sanity check on the 80x80x3 int8 model input (portable C99).
 * C port of content_stats() in src/fruitvision/validation/image_checks.py, thresholds from
 * configs/image_checks.json (via the generated header). NOT a trained not-a-fruit detector.
 * Parity with Python: tests/test_fw_image_check_parity.py. */
#ifndef FV_IMAGE_CHECK_H
#define FV_IMAGE_CHECK_H

#include "fv_common.h"

typedef struct {
    float lum_mean, lum_std, lag1_autocorr, chroma_mean_abs, clipped_fraction;
} fv_image_stats_t;

#define FV_IC_REJ_UNIFORM    (1u << 0)
#define FV_IC_REJ_NOISE      (1u << 1)
#define FV_IC_REJ_GRAYSCALE  (1u << 2)
#define FV_IC_WARN_DARK      (1u << 8)
#define FV_IC_WARN_BRIGHT    (1u << 9)
#define FV_IC_WARN_CLIPPED   (1u << 10)
#define FV_IC_REJ_TOO_SMALL  (1u << 3)    /* frame min side < reject_min_side */
#define FV_IC_REJ_SKIN_OBJECT (1u << 4)   /* human skin / foreign hand biometric rejection */
#define FV_IC_WARN_SMALL     (1u << 11)   /* frame min side < warn_min_side (upsampled) */
#define FV_IC_WARN_ASPECT    (1u << 12)   /* frame aspect > warn_aspect_ratio (centre crop) */
#define FV_IC_REJECT_MASK    0xFFu

/* `in` is the model input tensor (pixel = q - zero_point). Returns FV_IC_* flags; stats optional. */
uint32_t fv_image_check(const int8_t *in, fv_image_stats_t *stats);
/* Image detail (variance of the Laplacian of the luminance of the 80x80 model input). Used by the presence gate. */
float fv_image_detail(const int8_t *in);
/* Frame-dimension checks (configs/image_checks.json "dimensions"); returns FV_IC_* flags. */
uint32_t fv_frame_dims_check(int width, int height);

#endif
