/* HOST integration test of the real vision/fv_vision.cc (TFLM, int8 CMSIS-NN portable kernels,
 * split arenas) and app/fv_app.c, built for 32-bit x86 by tools/firmware/build_fw_check.sh.
 *   mode "raw"  <in.int8>...   : fv_vision_input/invoke on 80x80x3 int8 inputs -> 40 raw ints/line
 *   mode "app"  <frame.rgb565 w h be>... : full fv_app_cycle on an RGB565 frame (sensor fixture)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fv_app.h"
#include "fv_generated_config.h"
#include "fv_vision.h"

extern const unsigned char g_fv_model_data[];
void fv_host_set_frame(const uint8_t *px, uint16_t w, uint16_t h, uint8_t be);
void fv_host_set_sensors(const fv_sensor_record_t *r);
extern uint8_t *g_host_last_capture_buf;

__attribute__((aligned(16))) static uint8_t g_p[FV_ARENA_PERSISTENT_BYTES];
__attribute__((aligned(16))) static uint8_t g_np[FV_ARENA_NONPERSISTENT_BYTES];

static int read_file(const char *path, uint8_t *dst, size_t n) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    const size_t got = fread(dst, 1, n, f);
    fclose(f);
    return got == n ? 0 : -1;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    fv_status_t st = fv_app_init(g_fv_model_data, g_p, sizeof g_p, g_np, sizeof g_np);
    printf("INIT %s used=%lu p=%lu np=%lu\n", fv_status_name(st), (unsigned long)fv_vision_arena_used_bytes(),
           (unsigned long)sizeof g_p, (unsigned long)sizeof g_np);
    if (st != FV_OK) return 1;
    fv_range_t busy[9];
    const size_t nb = fv_vision_busy_ranges(busy, 9);
    for (size_t i = 0; i < nb; ++i)
        printf("BUSY %lu %lu\n", (unsigned long)(busy[i].ptr - g_np), (unsigned long)busy[i].bytes);
    if (!strcmp(argv[1], "raw")) {
        for (int a = 2; a < argc; ++a) {
            size_t n = 0;
            int8_t *in = fv_vision_input(&n);
            if (read_file(argv[a], (uint8_t *)in, n)) { printf("READFAIL %s\n", argv[a]); return 1; }
            fv_vision_raw_t raw;
            if (fv_vision_invoke(&raw) != FV_OK) { puts("INVOKEFAIL"); return 1; }
            printf("RAW");
            for (int h = 0; h < FV_N_HEADS; ++h)
                for (int k = 0; k < FV_MAX_CLASSES; ++k) printf(" %d", raw.q[h][k]);
            printf("\n");
        }
    } else if (!strcmp(argv[1], "app")) {
        fv_host_set_sensors(NULL);   /* no sensors on host -> sensor read error path */
        static uint8_t px[160 * 120 * 2];
        for (int a = 2; a + 3 < argc; a += 4) {
            const int w = atoi(argv[a + 1]), h = atoi(argv[a + 2]), be = atoi(argv[a + 3]);
            if (w <= 0 || h <= 0 || (size_t)w * h * 2u > sizeof px) { printf("BADSIZE %d %d\n", w, h); return 1; }
            if (read_file(argv[a], px, (size_t)w * h * 2u)) { printf("READFAIL %s\n", argv[a]); return 1; }
            fv_host_set_frame(px, (uint16_t)w, (uint16_t)h, (uint8_t)be);
            static fv_cycle_t c;
            fv_app_cycle(&c);
            printf("WIN %ld\n", (long)(g_host_last_capture_buf - g_np));
            printf("APP cam=%d img_flags=%lu %d %d %d %d %d %d %d %lu\n", c.camera_status,
                   (unsigned long)c.image_flags, c.image.fruit_state, c.image.fruit, c.image.condition,
                   c.image.quality_state, c.image.grade, c.image.shelf_state, c.image.stage,
                   (unsigned long)c.image.consistency);
            printf("SERIAL %s", c.serial_len > 0 ? c.serial : "-\r\n");
        }
    }
    return 0;
}
