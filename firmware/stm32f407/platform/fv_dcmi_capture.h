/* DCMI + DMA2 snapshot capture core (register level, RM0090). Board-independent part only.
 *
 * Register configuration mirrors what the ENTC firmware programs (STATIC evidence from its binary,
 * docs/CAMERA_ML_INTEGRATION_PLAN.md): DCMI snapshot mode, 8-bit data, PCKPOL=1, DMA2 Stream1 channel 1,
 * peripheral->memory, 32-bit/32-bit, memory increment, FIFO full threshold, priority high.
 * VSPOL/HSPOL are NOT fixed here: the ENTC firmware detects them at run time, so the caller must supply
 * the confirmed values. GPIO alternate functions, XCLK and the OV2640 (SCCB) setup are NOT part of this
 * module (platform hooks, pending board information).
 *
 * Register blocks are passed in as pointers so the logic can be unit-tested on the host against a
 * register mock (tests/test_fw_dcmi_capture.py). On target use FV_DCMI_REGS / FV_DMA2_REGS. */
#ifndef FV_DCMI_CAPTURE_H
#define FV_DCMI_CAPTURE_H

#include <stddef.h>
#include <stdint.h>

#include "fv_common.h"

typedef struct {               /* DCMI @ 0x50050000 (RM0090 15.8) */
    volatile uint32_t CR, SR, RIS, IER, MIS, ICR, ESCR, ESUR, CWSTRT, CWSIZE, DR;
} fv_dcmi_regs_t;

typedef struct {               /* one DMA stream (CR, NDTR, PAR, M0AR, M1AR, FCR) */
    volatile uint32_t CR, NDTR, PAR, M0AR, M1AR, FCR;
} fv_dma_stream_regs_t;

typedef struct {               /* DMA2 @ 0x40026400: LISR, HISR, LIFCR, HIFCR, streams 0..7 */
    volatile uint32_t LISR, HISR, LIFCR, HIFCR;
    fv_dma_stream_regs_t S[8];
} fv_dma_regs_t;

#define FV_DCMI_BASE 0x50050000u
#define FV_DMA2_BASE 0x40026400u
#define FV_DCMI_REGS ((fv_dcmi_regs_t *)FV_DCMI_BASE)
#define FV_DMA2_REGS ((fv_dma_regs_t *)FV_DMA2_BASE)
#define FV_DCMI_DR_ADDR (FV_DCMI_BASE + 0x28u)

/* DCMI_CR bits */
#define FV_DCMI_CR_CAPTURE (1u << 0)
#define FV_DCMI_CR_CM      (1u << 1)    /* snapshot */
#define FV_DCMI_CR_PCKPOL  (1u << 5)
#define FV_DCMI_CR_HSPOL   (1u << 6)
#define FV_DCMI_CR_VSPOL   (1u << 7)
#define FV_DCMI_CR_ENABLE  (1u << 14)
/* DCMI_RIS bits */
#define FV_DCMI_RIS_FRAME  (1u << 0)
#define FV_DCMI_RIS_OVR    (1u << 1)
#define FV_DCMI_RIS_ERR    (1u << 2)
/* DMA stream CR value used by the ENTC firmware (decoded: CHSEL=1, PL=high, MSIZE=PSIZE=32-bit, MINC, P->M) */
#define FV_DMA_S1CR_DCMI   0x02025400u
#define FV_DMA_FCR_DCMI    0x00000007u   /* DMDIS (FIFO mode), FTH = full */
#define FV_DMA2_S1_CLEAR_FLAGS 0x00000F40u /* LIFCR: CTCIF1|CHTIF1|CTEIF1|CDMEIF1|CFEIF1 */

typedef struct {
    uint8_t vspol;             /* 0/1, from the confirmed board configuration (no default) */
    uint8_t hspol;             /* 0/1 */
    uint32_t timeout_ms;       /* ENTC uses 1500 ms */
} fv_dcmi_cfg_t;

typedef enum {
    FV_CAP_OK = 0,
    FV_CAP_ERR_ARG = 1,
    FV_CAP_ERR_DMA_BUSY = 2,   /* DMA stream did not disable */
    FV_CAP_ERR_TIMEOUT = 3,    /* no frame-complete flag */
    FV_CAP_ERR_BUFFER_FULL = 4,/* NDTR reached 0: frame larger than the buffer */
    FV_CAP_ERR_OVERRUN = 5,
    FV_CAP_ERR_SIZE = 6        /* received byte count != expected frame size */
} fv_cap_status_t;

/* Programs DMA2 Stream1 + DCMI and starts one snapshot into `buf` (DMA-reachable SRAM, 4-byte aligned,
 * buf_bytes >= frame_bytes + 4, multiple of 4). Does not wait. */
fv_cap_status_t fv_dcmi_start(fv_dcmi_regs_t *dcmi, fv_dma_regs_t *dma, uint8_t *buf, size_t buf_bytes,
                              const fv_dcmi_cfg_t *cfg);
/* Waits for frame-complete (or timeout via millis()), stops DCMI/DMA and validates the byte count.
 * `received` (optional) gets the number of bytes written by DMA. */
fv_cap_status_t fv_dcmi_finish(fv_dcmi_regs_t *dcmi, fv_dma_regs_t *dma, size_t buf_bytes, size_t frame_bytes,
                               const fv_dcmi_cfg_t *cfg, uint32_t (*millis)(void), size_t *received);

#endif
