/* STM32F407VET6 entry point (application).
 * Memory placement (linker/STM32F407VETX_FV.ld):
 *   g_arena_persistent    -> .ccm_arena  (CCMRAM, NOLOAD): TFLM persistent data, CPU-only
 *   g_arena_nonpersistent -> .bss        (SRAM1): activations; the camera DMA frame is placed inside it
 * Results of every cycle go to the OLED and to g_fv_diag (SWD-readable; the board has no UART). */
#include "fv_app.h"
#ifdef FV_DIAG_CAM_TUNE
#include "fv_cam_tune.h"
#endif
#include "fv_diag.h"
#include "fv_generated_config.h"
#include "fv_platform.h"
#include "fv_vision.h"

extern const unsigned char g_fv_model_data[];   /* generated: tools/firmware/gen_model_data.py */

__attribute__((section(".ccm_arena"), aligned(16))) static uint8_t g_arena_persistent[FV_ARENA_PERSISTENT_BYTES];
__attribute__((aligned(16))) static uint8_t g_arena_nonpersistent[FV_ARENA_NONPERSISTENT_BYTES];

static fv_cycle_t g_cycle;   /* in .bss (SRAM1); not DMA-accessed */

static int32_t permille(float p) { return (int32_t)(p * 1000.0f + 0.5f); }

static void publish(const fv_cycle_t *c) {
    fv_diag_t *d = &g_fv_diag;
    d->uptime_ms = fv_platform_millis();
    d->cycles++;
    d->last_cycle_status = c->status;
    d->last_camera_status = c->camera_status;
    d->last_sensor_status = c->sensor_status;
    d->last_image_flags = c->image_flags;
    d->fruit = c->image.fruit;
    d->fruit_conf_pm = permille(c->image.fruit_conf);
    d->condition = c->image.condition;
    d->condition_conf_pm = permille(c->image.condition_conf);
    d->quality_state = c->image.quality_state;
    d->grade = c->image.grade;
    d->shelf_state = c->image.shelf_state;
    d->consistency = c->image.consistency;
    d->risk_state = c->risk.state;
    d->risk_reasons = (int32_t)c->risk.reasons;
    d->sensor_errors = c->sensor_check.errors;
    d->sensor_warnings = c->sensor_check.warnings;
    d->vision_arena_used = (uint32_t)fv_vision_arena_used_bytes();
    d->img_detail_x10 = (int32_t)(c->image_detail * 10.0f + 0.5f);
    d->fruit_present = (uint32_t)c->fruit_present;
}

int main(void) {
    if (fv_platform_init() != FV_OK) {
        for (;;) { }   /* core clock could not be configured: nothing safe to do */
    }
    (void)fv_camera_init(FV_CAMERA_W, FV_CAMERA_H);   /* failure -> image outputs UNAVAILABLE each cycle */
    fv_status_t st = fv_app_init(g_fv_model_data, g_arena_persistent, sizeof g_arena_persistent,
                                 g_arena_nonpersistent, sizeof g_arena_nonpersistent);
    if (st != FV_OK) {
        static const char msg[] = "FV1,status=INIT_FAILED\r\n";
        (void)fv_serial_write(msg, sizeof msg - 1);
    }
    for (;;) {
        (void)fv_app_cycle(&g_cycle);
        publish(&g_cycle);
#ifdef FV_DIAG_CAM_TUNE
        fv_cam_tune_service(fv_platform_millis());   /* diagnostic: apply PC-requested OV2640 settings between cycles */
#endif
        const uint32_t t0 = fv_platform_millis();
        while (fv_platform_millis() - t0 < 2000u) { }   /* >= 2 s: DHT22 minimum read interval */
    }
}
