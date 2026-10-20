/* HOST TEST platform (not firmware): camera frames come from files, sensors from a fixture.
 * Used only by fv_vision_host_main.c to exercise the real fv_app/fv_vision code paths on a PC. */
#include <stdio.h>
#include <string.h>

#include "fv_platform.h"

static uint8_t s_frame[160 * 120 * 2];
static uint16_t s_w, s_h;
static uint8_t s_be;
static const fv_sensor_record_t *s_rec;
uint8_t *g_host_last_capture_buf;   /* where the app asked the camera to write (window check) */

void fv_host_set_frame(const uint8_t *px, uint16_t w, uint16_t h, uint8_t be) {
    if ((size_t)w * h * 2u > sizeof s_frame) { s_w = s_h = 0; return; }   /* oversize: capture will fail */
    memcpy(s_frame, px, (size_t)w * h * 2u); s_w = w; s_h = h; s_be = be;
}
void fv_host_set_sensors(const fv_sensor_record_t *r) { s_rec = r; }

fv_status_t fv_platform_init(void) { return FV_OK; }
uint32_t fv_platform_millis(void) { return 0u; }
fv_status_t fv_camera_init(uint16_t w, uint16_t h) { (void)w; (void)h; return FV_OK; }
fv_status_t fv_camera_capture_rgb565(uint8_t *buf, size_t n, fv_frame_info_t *info) {
    const size_t need = (size_t)s_w * s_h * 2u;
    if (!buf || !info || need == 0 || n < need) return FV_ERR_ARG;
    g_host_last_capture_buf = buf;
    memcpy(buf, s_frame, need);
    info->width = s_w; info->height = s_h; info->big_endian_pixels = s_be;
    return FV_OK;
}
fv_status_t fv_sensors_read(fv_sensor_record_t *out) {
    if (!s_rec) return FV_ERR_HW;
    *out = *s_rec;
    return FV_OK;
}
fv_status_t fv_oled_show(const fv_oled_text_t *t) { (void)t; return FV_OK; }
fv_status_t fv_serial_write(const char *d, size_t n) { (void)d; (void)n; return FV_OK; }
void fv_indicators(int a, int b) { (void)a; (void)b; }
