/* STM32F407VET6 platform layer - PENDING.
 *
 * Every function deliberately returns FV_ERR_NOT_IMPLEMENTED (or does nothing) until the real
 * drivers are written against a STM32CubeMX-generated HAL project. Required, in order:
 *   1. CubeMX project for STM32F407VETx: 168 MHz SYSCLK, FPU on, SysTick 1 ms.
 *   2. USART (diagnostics) - pin choice per board schematic.
 *   3. I2C for TCS34725 (0x29) and SSD1306 (0x3C) - bus/pins per schematic.
 *   4. ADC + DMA for MQ135 and pH front-ends (divider/amplifier per schematic).
 *   5. DHT22 single-wire on a GPIO (timer-based timing).
 *   6. OV2640: DCMI 8-bit + DMA2 into SRAM, SCCB (I2C-like) configuration, XCLK source.
 *      NO driver exists in this repository; register tables, resolution (96x96 requested),
 *      RGB565 byte order and timing must be implemented and verified on hardware.
 * Pin assignments are intentionally NOT invented here.
 */
#include "fv_platform.h"

fv_status_t fv_platform_init(void) { return FV_ERR_NOT_IMPLEMENTED; }
uint32_t fv_platform_millis(void) { return 0u; }

fv_status_t fv_camera_init(uint16_t req_width, uint16_t req_height) {
    (void)req_width; (void)req_height;
    return FV_ERR_NOT_IMPLEMENTED;
}

fv_status_t fv_camera_capture_rgb565(uint8_t *buf, size_t buf_bytes, fv_frame_info_t *info) {
    (void)buf; (void)buf_bytes; (void)info;
    return FV_ERR_NOT_IMPLEMENTED;
}

fv_status_t fv_sensors_read(fv_sensor_record_t *out) { (void)out; return FV_ERR_NOT_IMPLEMENTED; }
fv_status_t fv_oled_show(const fv_oled_text_t *text) { (void)text; return FV_ERR_NOT_IMPLEMENTED; }
fv_status_t fv_serial_write(const char *data, size_t len) { (void)data; (void)len; return FV_ERR_NOT_IMPLEMENTED; }
void fv_indicators(int led_on, int buzzer_on) { (void)led_on; (void)buzzer_on; }
