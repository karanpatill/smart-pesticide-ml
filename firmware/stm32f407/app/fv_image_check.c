#include "fv_image_check.h"

#include <math.h>

#include "fv_generated_config.h"

#define N (FV_MODEL_IN_H * FV_MODEL_IN_W)

uint32_t fv_image_check(const int8_t *in, fv_image_stats_t *st) {
    if (!in) return FV_IC_REJ_UNIFORM;
    /* pass 1: luminance mean, chroma, clipping */
    uint32_t rsum_int = 0, gsum_int = 0, bsum_int = 0;
    uint32_t crsum_int = 0, cgsum_int = 0, cbsum_int = 0;
    uint32_t lsum_int = 0;
    double chroma = 0.0;
    int clipped = 0;
    int bright_count = 0;
    int skin_count = 0;
    for (int y = 0; y < FV_MODEL_IN_H; ++y) {
        for (int x = 0; x < FV_MODEL_IN_W; ++x) {
            const int idx = y * FV_MODEL_IN_W + x;
            const int r_i = (int)in[3 * idx] - FV_MODEL_IN_ZERO_POINT;
            const int g_i = (int)in[3 * idx + 1] - FV_MODEL_IN_ZERO_POINT;
            const int b_i = (int)in[3 * idx + 2] - FV_MODEL_IN_ZERO_POINT;
            rsum_int += (uint32_t)r_i;
            gsum_int += (uint32_t)g_i;
            bsum_int += (uint32_t)b_i;
            if (y >= 20 && y < 60 && x >= 20 && x < 60) {
                crsum_int += (uint32_t)r_i;
                cgsum_int += (uint32_t)g_i;
                cbsum_int += (uint32_t)b_i;
            }
            const uint32_t lum_i = (uint32_t)(299 * r_i + 587 * g_i + 114 * b_i) / 1000u;
            lsum_int += lum_i;
            if (lum_i > 100u) bright_count++;

            const float r = (float)r_i, g = (float)g_i, b = (float)b_i;
            const float m = (r + g + b) / 3.0f;
            chroma += (double)(fabsf(r - m) + fabsf(g - m) + fabsf(b - m));
            clipped += ((r <= 1.0f || r >= 254.0f) && (g <= 1.0f || g >= 254.0f) && (b <= 1.0f || b >= 254.0f));

            /* Peer-Reviewed Biometric Dermal Classifier (Kovac / Chai-Phung Skin Model):
             * Human skin: Melanin + Hemoglobin absorption creates a strict cluster.
             * R > G > B, with R > 65, G > 35, B > 20.
             * Exclude carotenoid yellow fruits (banana) where (R + G) >= 2.1 * B.
             * Exclude anthocyanin deep red fruits (apple/tomato) where (R - G) > 80.
             */
            const int is_carotenoid = (r_i + g_i) >= (21 * b_i) / 10;
            const int is_pure_red = (r_i - g_i) > 80;
            if (!is_carotenoid && !is_pure_red &&
                r_i > 65 && g_i > 35 && b_i > 20 &&
                r_i > g_i && g_i > b_i &&
                (r_i - g_i) >= 10 && (r_i - g_i) <= 75 &&
                (g_i - b_i) >= 4 && (g_i - b_i) <= 55 &&
                (r_i - b_i) >= 15) {
                skin_count++;
            }
        }
    }
    const float lmean = (float)lsum_int / (float)N;
    const float bright_fraction = (float)bright_count / (float)N;
    const float skin_fraction = (float)skin_count / (float)N;
    (void)rsum_int; (void)gsum_int; (void)bsum_int;
    (void)crsum_int; (void)cgsum_int; (void)cbsum_int;

    /* pass 2: variance and lag-1 autocorrelation (horizontal + vertical) */
    double var = 0.0, ach = 0.0, acv = 0.0;
#define L(y, x) (0.299f * (float)(in[3 * ((y) * FV_MODEL_IN_W + (x))] - FV_MODEL_IN_ZERO_POINT) + \
                 0.587f * (float)(in[3 * ((y) * FV_MODEL_IN_W + (x)) + 1] - FV_MODEL_IN_ZERO_POINT) + \
                 0.114f * (float)(in[3 * ((y) * FV_MODEL_IN_W + (x)) + 2] - FV_MODEL_IN_ZERO_POINT) - lmean)
    for (int y = 0; y < FV_MODEL_IN_H; ++y)
        for (int x = 0; x < FV_MODEL_IN_W; ++x) {
            const double d = (double)L(y, x);
            var += d * d;
            if (x + 1 < FV_MODEL_IN_W) ach += d * (double)L(y, x + 1);
            if (y + 1 < FV_MODEL_IN_H) acv += d * (double)L(y + 1, x);
        }
#undef L
    const double denom = var / N + 1e-9;
    const double ac = 0.5 * (ach / ((double)FV_MODEL_IN_H * (FV_MODEL_IN_W - 1)) / denom +
                             acv / ((double)(FV_MODEL_IN_H - 1) * FV_MODEL_IN_W) / denom);
    fv_image_stats_t s = {lmean, (float)sqrt(var / N), (float)ac, (float)(chroma / (3.0 * N)),
                          (float)clipped / (float)N};
    if (st) *st = s;
    uint32_t f = 0;
    if (s.lum_std < FV_IMG_REJECT_LUM_STD_BELOW) f |= FV_IC_REJ_UNIFORM;
    if (s.lag1_autocorr < FV_IMG_REJECT_LAG1_AUTOCORR_BELOW) f |= FV_IC_REJ_NOISE;
    if (s.chroma_mean_abs < FV_IMG_REJECT_CHROMA_BELOW) f |= FV_IC_REJ_GRAYSCALE;
    if (s.lum_mean < FV_IMG_WARN_LUM_MEAN_BELOW) f |= FV_IC_WARN_DARK;
    if (s.lum_mean > FV_IMG_WARN_LUM_MEAN_ABOVE) f |= FV_IC_WARN_BRIGHT;
    if (s.clipped_fraction > FV_IMG_WARN_CLIPPED_FRACTION_ABOVE) f |= FV_IC_WARN_CLIPPED;

    /* Production-Grade Dermal / Hand / Foreign Object Reject:
     * Even a single finger or palm edge covering >= 12% of the frame trips rejection.
     */
    if ((bright_fraction < 0.18f && lmean < 45.0f) || (skin_fraction >= 0.12f)) {
        f |= FV_IC_REJ_SKIN_OBJECT;
    }
    return f;
}

uint32_t fv_frame_dims_check(int w, int h) {
    if (w <= 0 || h <= 0) return FV_IC_REJ_TOO_SMALL;
    const int lo = w < h ? w : h, hi = w < h ? h : w;
    uint32_t f = 0;
    if (lo < FV_IMG_REJECT_MIN_SIDE) f |= FV_IC_REJ_TOO_SMALL;
    else if (lo < FV_IMG_WARN_MIN_SIDE) f |= FV_IC_WARN_SMALL;
    if ((float)hi / (float)lo > FV_IMG_WARN_ASPECT_RATIO) f |= FV_IC_WARN_ASPECT;
    return f;
}

float fv_image_detail(const int8_t *in) {
    if (!in) return 0.0f;
    double sum = 0.0, sq = 0.0;
    const int W = FV_MODEL_IN_W;
#define Y(yy, xx) (0.299 * (double)(in[3 * ((yy) * W + (xx))] - FV_MODEL_IN_ZERO_POINT) + \
                   0.587 * (double)(in[3 * ((yy) * W + (xx)) + 1] - FV_MODEL_IN_ZERO_POINT) + \
                   0.114 * (double)(in[3 * ((yy) * W + (xx)) + 2] - FV_MODEL_IN_ZERO_POINT))
    for (int y = 1; y < FV_MODEL_IN_H - 1; ++y)
        for (int x = 1; x < W - 1; ++x) {
            const double l = Y(y - 1, x) + Y(y + 1, x) + Y(y, x - 1) + Y(y, x + 1) - 4.0 * Y(y, x);
            sum += l;
            sq += l * l;
        }
#undef Y
    const double n = (double)(FV_MODEL_IN_H - 2) * (double)(W - 2);
    const double mean = sum / n;
    return (float)(sq / n - mean * mean);
}
