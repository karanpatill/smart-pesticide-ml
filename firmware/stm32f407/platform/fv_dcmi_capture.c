#include "fv_dcmi_capture.h"

#define DMA_EN (1u << 0)
#define DMA_DISABLE_SPINS 100000u

static void stop(fv_dcmi_regs_t *dcmi, fv_dma_stream_regs_t *s) {
    dcmi->CR &= ~(FV_DCMI_CR_ENABLE | FV_DCMI_CR_CAPTURE);
    s->CR &= ~DMA_EN;
}

fv_cap_status_t fv_dcmi_start(fv_dcmi_regs_t *dcmi, fv_dma_regs_t *dma, uint8_t *buf, size_t buf_bytes,
                              const fv_dcmi_cfg_t *cfg) {
    if (!dcmi || !dma || !buf || !cfg || buf_bytes < 8u || (buf_bytes & 3u) || ((uintptr_t)buf & 3u) ||
        buf_bytes / 4u > 0xFFFFu || cfg->vspol > 1u || cfg->hspol > 1u)
        return FV_CAP_ERR_ARG;
    fv_dma_stream_regs_t *s = &dma->S[1];
    stop(dcmi, s);
    uint32_t n = 0;
    while ((s->CR & DMA_EN) && n < DMA_DISABLE_SPINS) ++n;   /* EN reads 1 until the stream has stopped */
    if (s->CR & DMA_EN) return FV_CAP_ERR_DMA_BUSY;
    dma->LIFCR = FV_DMA2_S1_CLEAR_FLAGS;
    s->PAR = FV_DCMI_DR_ADDR;
    s->M0AR = (uint32_t)(uintptr_t)buf;
    s->NDTR = (uint32_t)(buf_bytes / 4u);
    s->FCR = FV_DMA_FCR_DCMI;
    s->CR = FV_DMA_S1CR_DCMI;
    s->CR |= DMA_EN;
    dcmi->CR = FV_DCMI_CR_CM | FV_DCMI_CR_PCKPOL | (cfg->vspol ? FV_DCMI_CR_VSPOL : 0u) |
               (cfg->hspol ? FV_DCMI_CR_HSPOL : 0u);
    dcmi->ICR = 0x1Fu;
    dcmi->CR |= FV_DCMI_CR_ENABLE;
    dcmi->CR |= FV_DCMI_CR_CAPTURE;
    return FV_CAP_OK;
}

fv_cap_status_t fv_dcmi_finish(fv_dcmi_regs_t *dcmi, fv_dma_regs_t *dma, size_t buf_bytes, size_t frame_bytes,
                               const fv_dcmi_cfg_t *cfg, uint32_t (*millis)(void), size_t *received) {
    if (received) *received = 0;
    if (!dcmi || !dma || !cfg || !millis || buf_bytes < 8u || (buf_bytes & 3u) || frame_bytes == 0u ||
        frame_bytes > buf_bytes)
        return FV_CAP_ERR_ARG;
    fv_dma_stream_regs_t *s = &dma->S[1];
    const uint32_t t0 = millis();
    uint32_t ris = 0;
    for (;;) {
        ris = dcmi->RIS;
        if (ris & (FV_DCMI_RIS_FRAME | FV_DCMI_RIS_OVR)) break;
        if (millis() - t0 > cfg->timeout_ms) break;
    }
    const uint32_t ndtr = s->NDTR;
    stop(dcmi, s);
    const size_t got = (buf_bytes / 4u - ndtr) * 4u;
    if (received) *received = got;
    if (ris & FV_DCMI_RIS_OVR) return FV_CAP_ERR_OVERRUN;
    if (!(ris & FV_DCMI_RIS_FRAME)) return FV_CAP_ERR_TIMEOUT;
    if (ndtr == 0u) return FV_CAP_ERR_BUFFER_FULL;
    if (got != frame_bytes) return FV_CAP_ERR_SIZE;
    return FV_CAP_OK;
}
