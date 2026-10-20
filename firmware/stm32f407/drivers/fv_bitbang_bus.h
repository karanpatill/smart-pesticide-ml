/* Bit-banged open-drain two-wire bus (I2C master / OV2640 SCCB master). Portable: the pins and the delay are
 * callbacks, so the protocol logic is unit-tested on the host against a simulated slave (tests/fv_drivers_test.c).
 * Lines are open-drain: writing 1 releases the line (pull-up), writing 0 drives it low. */
#ifndef FV_BITBANG_BUS_H
#define FV_BITBANG_BUS_H
#include <stddef.h>
#include <stdint.h>

typedef struct {
    void (*scl)(void *ctx, int level);
    void (*sda)(void *ctx, int level);
    int (*sda_in)(void *ctx);
    int (*scl_in)(void *ctx);          /* optional (NULL): clock-stretching support */
    void (*delay)(void *ctx);          /* quarter bit period */
    void *ctx;
} fv_bb_bus_t;

enum { FV_BB_OK = 0, FV_BB_NACK = -1, FV_BB_ARG = -2, FV_BB_BUS_STUCK = -3 };

int fv_bb_recover(const fv_bb_bus_t *b);                        /* 9 clocks + stop; FV_BB_BUS_STUCK if SDA stays low */
void fv_bb_start(const fv_bb_bus_t *b);
void fv_bb_stop(const fv_bb_bus_t *b);
int fv_bb_write_byte(const fv_bb_bus_t *b, uint8_t v);          /* returns 0 on ACK, FV_BB_NACK otherwise */
uint8_t fv_bb_read_byte(const fv_bb_bus_t *b, int ack);

/* I2C: [S addr8 prefix... data...] P. prefix may be NULL. */
int fv_i2c_write(const fv_bb_bus_t *b, uint8_t addr8, const uint8_t *prefix, size_t np, const uint8_t *data, size_t n);
/* I2C: S addr8 reg Sr addr8|1 data... P (repeated start). */
int fv_i2c_read_reg(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t *out, size_t n);
/* SCCB (OV2640): 3-phase write; 2-phase write + 2-phase read (stop between, no repeated start). */
int fv_sccb_write(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t val);
int fv_sccb_read(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t *val);

#endif
