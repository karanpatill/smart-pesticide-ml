/* Hardware boundary of the firmware. Everything board-specific lives behind these functions.
 *
 * STATUS: the STM32F407VET6 implementation (fv_platform_stm32_pending.c) is NOT written yet -
 * every function returns FV_ERR_NOT_IMPLEMENTED. No OV2640 driver exists in this repository and
 * no pin assignment has been decided; nothing here assumes one. A host implementation used by the
 * tests lives in firmware/stm32f407/tests/.
 *
 * DMA rule: any buffer passed to a DMA-driven function (camera capture, OLED flush, ADC, UART)
 * must be in SRAM1/SRAM2 (0x2000_0000-0x2001_FFFF), never in CCM (0x1000_0000) and never on a
 * stack placed in CCM. Use FV_DMA_BUFFER for static DMA buffers.
 */
#ifndef FV_PLATFORM_H
#define FV_PLATFORM_H

#include "fv_common.h"
#include "fv_report.h"
#include "fv_sensor.h"

#if defined(__GNUC__) || defined(__clang__)
#define FV_DMA_BUFFER __attribute__((section(".dma_buffers"), aligned(4)))
#else
#define FV_DMA_BUFFER
#endif

typedef struct {
    uint16_t width, height;     /* frame actually captured */
    uint8_t big_endian_pixels;  /* RGB565 byte order in memory (must be confirmed on hardware) */
} fv_frame_info_t;

fv_status_t fv_platform_init(void);                /* clocks, GPIO, peripherals */
uint32_t fv_platform_millis(void);

/* Camera: capture one RGB565 frame into `buf` (DMA-reachable SRAM, >= width*height*2 bytes,
 * 4-byte aligned). Requested size is a hint; the driver reports what it produced. */
fv_status_t fv_camera_init(uint16_t req_width, uint16_t req_height);
fv_status_t fv_camera_capture_rgb565(uint8_t *buf, size_t buf_bytes, fv_frame_info_t *info);

/* Sensors: fill `out` (presence flags, raw values, units, origin = FV_ORIGIN_DEVICE). */
fv_status_t fv_sensors_read(fv_sensor_record_t *out);

/* Outputs */
fv_status_t fv_oled_show(const fv_oled_text_t *text);
fv_status_t fv_serial_write(const char *data, size_t len);
void fv_indicators(int led_on, int buzzer_on);

#endif
