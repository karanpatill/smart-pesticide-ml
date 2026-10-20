#include "fv_ov2640.h"

#include <stddef.h>

#include "fv_entc_ov2640_tables.h"

static int write_table(fv_ov2640_t *c, const fv_sccb_reg_t *t, int n, int base_index) {
    for (int i = 0; i < n; ++i)
        if (fv_sccb_write(c->bus, c->addr8, t[i].reg, t[i].val) != FV_BB_OK) {
            c->failed_index = base_index + i;
            return FV_OV2640_ERR_TABLE;
        }
    return FV_OV2640_OK;
}

int fv_ov2640_probe(fv_ov2640_t *c) {
    if (!c || !c->bus) return FV_OV2640_ERR_ARG;
    c->pid = c->ver = 0;
    if (fv_sccb_write(c->bus, c->addr8, 0xFF, 0x01) != FV_BB_OK) return FV_OV2640_ERR_BUS;
    if (fv_sccb_read(c->bus, c->addr8, 0x0A, &c->pid) != FV_BB_OK) return FV_OV2640_ERR_BUS;
    if (fv_sccb_read(c->bus, c->addr8, 0x0B, &c->ver) != FV_BB_OK) return FV_OV2640_ERR_BUS;
    return c->pid == FV_OV2640_PIDH ? FV_OV2640_OK : FV_OV2640_ERR_ID;
}

int fv_ov2640_init_entc(fv_ov2640_t *c) {
    if (!c || !c->bus || !c->delay_ms) return FV_OV2640_ERR_ARG;
    c->failed_index = -1;
    if (fv_sccb_write(c->bus, c->addr8, 0xFF, 0x01) != FV_BB_OK) return FV_OV2640_ERR_BUS;
    int r = write_table(c, FV_ENTC_OV2640_TABLE_A, FV_ENTC_OV2640_TABLE_A_LEN, 0);
    if (r != FV_OV2640_OK) return r;
    c->delay_ms(10);
    return write_table(c, FV_ENTC_OV2640_TABLE_B, FV_ENTC_OV2640_TABLE_B_LEN, FV_ENTC_OV2640_TABLE_A_LEN);
}

int fv_ov2640_set_pclk_div(fv_ov2640_t *c, uint8_t div) {
    if (!c || !c->bus) return FV_OV2640_ERR_ARG;
    if (fv_sccb_write(c->bus, c->addr8, 0xFF, 0x00) != FV_BB_OK) return FV_OV2640_ERR_BUS;
    return fv_sccb_write(c->bus, c->addr8, 0xD3, (uint8_t)(div | 0x80u)) == FV_BB_OK ? FV_OV2640_OK : FV_OV2640_ERR_BUS;
}
