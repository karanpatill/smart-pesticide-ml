#include "preprocess_rgb565.h"

static inline void px(const uint8_t *src, int w, int x, int y, int be, int *r, int *g, int *b) {
    const uint8_t *p = src + 2 * (y * w + x);
    unsigned v = be ? ((unsigned)p[0] << 8) | p[1] : ((unsigned)p[1] << 8) | p[0];
    unsigned r5 = (v >> 11) & 0x1F, g6 = (v >> 5) & 0x3F, b5 = v & 0x1F;
    *r = (int)((r5 << 3) | (r5 >> 2));   /* bit replication: 0..31 -> 0..255 */
    *g = (int)((g6 << 2) | (g6 >> 4));   /* 0..63 -> 0..255 */
    *b = (int)((b5 << 3) | (b5 >> 2));
}

int fv_rgb565_to_input_int8(const uint8_t *src, int w, int h, int be, int8_t *dst) {
    if (!src || !dst || w < 8 || h < 8) return -1;
    const int side = w < h ? w : h;
    const int x0 = (w - side) / 2, y0 = (h - side) / 2;
    /* Q16 source coordinate of output pixel centre: ((o + 0.5) * side / 80 - 0.5) */
    const int32_t step = (int32_t)(((int64_t)side << 16) / FV_IN_W);
    for (int oy = 0; oy < FV_IN_H; ++oy) {
        int32_t sy = (int32_t)(((2 * oy + 1) * (int64_t)step) / 2) - (1 << 15);
        if (sy < 0) sy = 0;
        int y = sy >> 16, fy = sy & 0xFFFF;
        int y1 = y + 1 < side ? y + 1 : side - 1;
        for (int ox = 0; ox < FV_IN_W; ++ox) {
            int32_t sx = (int32_t)(((2 * ox + 1) * (int64_t)step) / 2) - (1 << 15);
            if (sx < 0) sx = 0;
            int x = sx >> 16, fx = sx & 0xFFFF;
            int x1 = x + 1 < side ? x + 1 : side - 1;
            int c[4][3];
            px(src, w, x0 + x, y0 + y, be, &c[0][0], &c[0][1], &c[0][2]);
            px(src, w, x0 + x1, y0 + y, be, &c[1][0], &c[1][1], &c[1][2]);
            px(src, w, x0 + x, y0 + y1, be, &c[2][0], &c[2][1], &c[2][2]);
            px(src, w, x0 + x1, y0 + y1, be, &c[3][0], &c[3][1], &c[3][2]);
            for (int k = 0; k < 3; ++k) {
                int64_t top = (int64_t)c[0][k] * (65536 - fx) + (int64_t)c[1][k] * fx;
                int64_t bot = (int64_t)c[2][k] * (65536 - fx) + (int64_t)c[3][k] * fx;
                int64_t v = (top * (65536 - fy) + bot * fy + ((int64_t)1 << 31)) >> 32;  /* round */
                if (v > 255) v = 255;
                dst[(oy * FV_IN_W + ox) * 3 + k] = (int8_t)(v - 128);
            }
        }
    }
    return 0;
}
