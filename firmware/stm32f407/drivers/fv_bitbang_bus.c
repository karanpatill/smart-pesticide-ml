#include "fv_bitbang_bus.h"

#define STRETCH_LIMIT 1000

static void scl_high(const fv_bb_bus_t *b) {
    b->scl(b->ctx, 1);
    if (b->scl_in)
        for (int i = 0; i < STRETCH_LIMIT && !b->scl_in(b->ctx); ++i) b->delay(b->ctx);
}

int fv_bb_recover(const fv_bb_bus_t *b) {
    if (!b) return FV_BB_ARG;
    b->sda(b->ctx, 1);
    for (int i = 0; i < 9 && !b->sda_in(b->ctx); ++i) {   /* clock out a slave that holds SDA low */
        b->scl(b->ctx, 0); b->delay(b->ctx); b->delay(b->ctx);
        scl_high(b); b->delay(b->ctx); b->delay(b->ctx);
    }
    fv_bb_stop(b);
    return b->sda_in(b->ctx) ? FV_BB_OK : FV_BB_BUS_STUCK;
}

void fv_bb_start(const fv_bb_bus_t *b) {        /* SDA falls while SCL is high */
    b->sda(b->ctx, 1); scl_high(b); b->delay(b->ctx);
    b->sda(b->ctx, 0); b->delay(b->ctx);
    b->scl(b->ctx, 0); b->delay(b->ctx);
}

void fv_bb_stop(const fv_bb_bus_t *b) {         /* SDA rises while SCL is high */
    b->scl(b->ctx, 0); b->sda(b->ctx, 0); b->delay(b->ctx);
    scl_high(b); b->delay(b->ctx);
    b->sda(b->ctx, 1); b->delay(b->ctx);
}

int fv_bb_write_byte(const fv_bb_bus_t *b, uint8_t v) {
    for (int i = 7; i >= 0; --i) {
        b->sda(b->ctx, (v >> i) & 1); b->delay(b->ctx);
        scl_high(b); b->delay(b->ctx); b->delay(b->ctx);
        b->scl(b->ctx, 0); b->delay(b->ctx);
    }
    b->sda(b->ctx, 1); b->delay(b->ctx);              /* release for ACK */
    scl_high(b); b->delay(b->ctx);
    const int nack = b->sda_in(b->ctx);
    b->delay(b->ctx);
    b->scl(b->ctx, 0); b->delay(b->ctx);
    return nack ? FV_BB_NACK : FV_BB_OK;
}

uint8_t fv_bb_read_byte(const fv_bb_bus_t *b, int ack) {
    uint8_t v = 0;
    b->sda(b->ctx, 1);
    for (int i = 0; i < 8; ++i) {
        b->delay(b->ctx);
        scl_high(b); b->delay(b->ctx);
        v = (uint8_t)((v << 1) | (b->sda_in(b->ctx) ? 1 : 0));
        b->delay(b->ctx);
        b->scl(b->ctx, 0);
    }
    b->sda(b->ctx, ack ? 0 : 1); b->delay(b->ctx);
    scl_high(b); b->delay(b->ctx); b->delay(b->ctx);
    b->scl(b->ctx, 0); b->sda(b->ctx, 1); b->delay(b->ctx);
    return v;
}

int fv_i2c_write(const fv_bb_bus_t *b, uint8_t addr8, const uint8_t *prefix, size_t np, const uint8_t *data, size_t n) {
    if (!b || (np && !prefix) || (n && !data)) return FV_BB_ARG;
    fv_bb_start(b);
    int r = fv_bb_write_byte(b, (uint8_t)(addr8 & 0xFEu));
    for (size_t i = 0; r == FV_BB_OK && i < np; ++i) r = fv_bb_write_byte(b, prefix[i]);
    for (size_t i = 0; r == FV_BB_OK && i < n; ++i) r = fv_bb_write_byte(b, data[i]);
    fv_bb_stop(b);
    return r;
}

int fv_i2c_read_reg(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t *out, size_t n) {
    if (!b || !out || n == 0) return FV_BB_ARG;
    fv_bb_start(b);
    int r = fv_bb_write_byte(b, (uint8_t)(addr8 & 0xFEu));
    if (r == FV_BB_OK) r = fv_bb_write_byte(b, reg);
    if (r == FV_BB_OK) {
        fv_bb_start(b);                                  /* repeated start */
        r = fv_bb_write_byte(b, (uint8_t)(addr8 | 1u));
        for (size_t i = 0; r == FV_BB_OK && i < n; ++i) out[i] = fv_bb_read_byte(b, i + 1 < n);
    }
    fv_bb_stop(b);
    return r;
}

int fv_sccb_write(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t val) {
    const uint8_t rv[2] = {reg, val};
    return fv_i2c_write(b, addr8, NULL, 0, rv, 2);
}

int fv_sccb_read(const fv_bb_bus_t *b, uint8_t addr8, uint8_t reg, uint8_t *val) {
    if (!b || !val) return FV_BB_ARG;
    int r = fv_i2c_write(b, addr8, NULL, 0, &reg, 1);   /* 2-phase write: set the register address */
    if (r != FV_BB_OK) return r;
    fv_bb_start(b);                                     /* 2-phase read, NACK on the last byte */
    r = fv_bb_write_byte(b, (uint8_t)(addr8 | 1u));
    if (r == FV_BB_OK) *val = fv_bb_read_byte(b, 0);
    fv_bb_stop(b);
    return r;
}
