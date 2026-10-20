#include "fv_tcs34725.h"

#define CMD 0x80u
#define CMD_AUTOINC 0xA0u
#define REG_ENABLE 0x00u
#define REG_ATIME 0x01u
#define REG_CONTROL 0x0Fu
#define REG_ID 0x12u
#define REG_STATUS 0x13u
#define REG_CDATAL 0x14u

static int wr(fv_tcs34725_t *d, uint8_t reg, uint8_t v) {
    const uint8_t buf[2] = {(uint8_t)(CMD | reg), v};
    return fv_i2c_write(d->bus, d->addr8, 0, 0, buf, 2) == FV_BB_OK ? FV_TCS_OK : FV_TCS_ERR_BUS;
}

int fv_tcs34725_init(fv_tcs34725_t *d) {
    if (!d || !d->bus || !d->delay_ms) return FV_TCS_ERR_ARG;
    if (fv_i2c_read_reg(d->bus, d->addr8, (uint8_t)(CMD | REG_ID), &d->id, 1) != FV_BB_OK) return FV_TCS_ERR_BUS;
    if (d->id != 0x44 && d->id != 0x4D) return FV_TCS_ERR_ID;
    d->atime = FV_TCS_ATIME_ENTC;
    d->gain = FV_TCS_GAIN_ENTC;
    if (wr(d, REG_ATIME, d->atime) || wr(d, REG_CONTROL, d->gain) || wr(d, REG_ENABLE, 0x01)) return FV_TCS_ERR_BUS;
    d->delay_ms(3);
    if (wr(d, REG_ENABLE, 0x03)) return FV_TCS_ERR_BUS;
    d->delay_ms(60);
    return FV_TCS_OK;
}

int fv_tcs34725_read(fv_tcs34725_t *d, uint16_t *c, uint16_t *r, uint16_t *g, uint16_t *b) {
    if (!d || !d->bus || !c || !r || !g || !b) return FV_TCS_ERR_ARG;
    uint8_t st = 0, x[8];
    if (fv_i2c_read_reg(d->bus, d->addr8, (uint8_t)(CMD | REG_STATUS), &st, 1) != FV_BB_OK) return FV_TCS_ERR_BUS;
    if (!(st & 0x01u)) return FV_TCS_ERR_NOT_READY;
    if (fv_i2c_read_reg(d->bus, d->addr8, (uint8_t)(CMD_AUTOINC | REG_CDATAL), x, 8) != FV_BB_OK) return FV_TCS_ERR_BUS;
    *c = (uint16_t)(x[0] | x[1] << 8);
    *r = (uint16_t)(x[2] | x[3] << 8);
    *g = (uint16_t)(x[4] | x[5] << 8);
    *b = (uint16_t)(x[6] | x[7] << 8);
    return FV_TCS_OK;
}
