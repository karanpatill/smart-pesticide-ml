/* OV2640 control over SCCB, using the register sequence of the ENTC firmware (generated header
 * fv_entc_ov2640_tables.h, extracted from the hash-checked backup). */
#ifndef FV_OV2640_H
#define FV_OV2640_H
#include <stdint.h>

#include "fv_bitbang_bus.h"

#define FV_OV2640_PIDH 0x26           /* sensor bank (0xFF=0x01) reg 0x0A */
enum { FV_OV2640_OK = 0, FV_OV2640_ERR_BUS = -1, FV_OV2640_ERR_ID = -2, FV_OV2640_ERR_TABLE = -3, FV_OV2640_ERR_ARG = -4 };

typedef struct {
    const fv_bb_bus_t *bus;
    uint8_t addr8;                    /* 0x60 */
    void (*delay_ms)(uint32_t ms);
    uint8_t pid, ver;                 /* filled by probe */
    int failed_index;                 /* table entry that NACKed, -1 if none */
} fv_ov2640_t;

int fv_ov2640_probe(fv_ov2640_t *c);                 /* reads PIDH/PIDL; ERR_ID if PIDH != 0x26 */
int fv_ov2640_init_entc(fv_ov2640_t *c);             /* 0xFF<-0x01, table A, 10 ms, table B */
int fv_ov2640_set_pclk_div(fv_ov2640_t *c, uint8_t div);   /* 0xFF<-0x00, 0xD3<-(div|0x80) */

#endif
