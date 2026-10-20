/* SSD1306 128x64 OLED over I2C: 1 KB framebuffer, 5x7 font in 6x8 cells (21 columns x 8 rows = fv_oled_text_t).
 * Init command order is the one the ENTC firmware sends [STATIC @0x080030AA]. */
#ifndef FV_SSD1306_H
#define FV_SSD1306_H
#include <stdint.h>

#include "fv_bitbang_bus.h"

#define FV_SSD1306_FB_BYTES (128 * 64 / 8)
enum { FV_SSD1306_OK = 0, FV_SSD1306_ERR_BUS = -1, FV_SSD1306_ERR_ARG = -2 };

typedef struct {
    const fv_bb_bus_t *bus;
    uint8_t addr8;                    /* 0x78 */
    uint8_t fb[FV_SSD1306_FB_BYTES];  /* page-major: byte = 8 vertical pixels */
} fv_ssd1306_t;

int fv_ssd1306_init(fv_ssd1306_t *d);
void fv_ssd1306_clear(fv_ssd1306_t *d);
void fv_ssd1306_draw_char(fv_ssd1306_t *d, int col, int row, char ch);     /* col 0..20, row 0..7 */
void fv_ssd1306_draw_text(fv_ssd1306_t *d, int col, int row, const char *s);
int fv_ssd1306_get_pixel(const fv_ssd1306_t *d, int x, int y);
int fv_ssd1306_flush(fv_ssd1306_t *d);
extern const uint8_t FV_FONT5X7[95][5];                                  /* ASCII 0x20..0x7E */

#endif
