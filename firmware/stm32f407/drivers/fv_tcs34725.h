/* TCS34725 colour sensor over I2C. Settings mirror the ENTC firmware [STATIC @0x080037B8]: ATIME 0xEB (~50 ms),
 * CONTROL 0x01 (4x gain), ENABLE PON -> 3 ms -> PON|AEN -> 60 ms; data = 8-byte burst from 0xB4 (C,R,G,B). */
#ifndef FV_TCS34725_H
#define FV_TCS34725_H
#include <stdint.h>

#include "fv_bitbang_bus.h"

#define FV_TCS_ATIME_ENTC 0xEB
#define FV_TCS_GAIN_ENTC 0x01
enum { FV_TCS_OK = 0, FV_TCS_ERR_BUS = -1, FV_TCS_ERR_ID = -2, FV_TCS_ERR_NOT_READY = -3, FV_TCS_ERR_ARG = -4 };

typedef struct {
    const fv_bb_bus_t *bus;
    uint8_t addr8;                    /* 0x52 */
    void (*delay_ms)(uint32_t ms);
    uint8_t id, atime, gain;
} fv_tcs34725_t;

int fv_tcs34725_init(fv_tcs34725_t *d);                         /* ID must be 0x44 or 0x4D */
/* Reads C,R,G,B raw counts. ERR_NOT_READY if STATUS.AVALID is not set. */
int fv_tcs34725_read(fv_tcs34725_t *d, uint16_t *c, uint16_t *r, uint16_t *g, uint16_t *b);

#endif
