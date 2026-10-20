/* HOST unit test of platform/fv_dcmi_capture.c against plain-memory register mocks (no hardware).
 * Checks the programmed register values against the configuration decoded from the ENTC binary and
 * the error handling of fv_dcmi_finish. Prints PASS/FAIL lines, exit code = number of failures. */
#include <stdio.h>
#include <string.h>

#include "fv_dcmi_capture.h"

static fv_dcmi_regs_t dcmi;
static fv_dma_regs_t dma;
static uint32_t buf_words[40448 / 4];
static uint32_t now_ms;
static uint32_t fake_millis(void) { return now_ms++; }   /* advances 1 ms per call */
static int fails;

#define CHECK(c, name) do { int ok_ = (c); printf("%s %s\n", ok_ ? "PASS" : "FAIL", name); fails += !ok_; } while (0)

#define BUF_BYTES 40448u
#define FRAME 38400u

static void reset_mocks(void) { memset(&dcmi, 0, sizeof dcmi); memset(&dma, 0, sizeof dma); now_ms = 0; }

int main(void) {
    uint8_t *buf = (uint8_t *)buf_words;
    const fv_dcmi_cfg_t cfg = {1, 0, 1500};
    size_t got = 0;

    /* register layout sanity (offsets per RM0090) */
    CHECK((size_t)((uint8_t *)&dcmi.DR - (uint8_t *)&dcmi) == 0x28, "dcmi_dr_offset_0x28");
    CHECK((size_t)((uint8_t *)&dma.S[1].CR - (uint8_t *)&dma) == 0x28, "dma2_s1cr_offset_0x28");
    CHECK((size_t)((uint8_t *)&dma.S[1].FCR - (uint8_t *)&dma) == 0x3C, "dma2_s1fcr_offset_0x3c");

    /* start: programmed values */
    reset_mocks();
    CHECK(fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg) == FV_CAP_OK, "start_ok");
    CHECK(dma.S[1].CR == (FV_DMA_S1CR_DCMI | 1u), "dma_cr_matches_entc_plus_en");
    CHECK(dma.S[1].PAR == FV_DCMI_DR_ADDR, "dma_par_dcmi_dr");
    CHECK(dma.S[1].M0AR == (uint32_t)(uintptr_t)buf, "dma_m0ar_buffer");
    CHECK(dma.S[1].NDTR == BUF_BYTES / 4u, "dma_ndtr_words");
    CHECK(dma.S[1].FCR == FV_DMA_FCR_DCMI, "dma_fcr");
    CHECK(dma.LIFCR == FV_DMA2_S1_CLEAR_FLAGS, "dma_lifcr_clear_s1");
    CHECK(dcmi.ICR == 0x1Fu, "dcmi_icr_clear_all");
    CHECK(dcmi.CR == (FV_DCMI_CR_CM | FV_DCMI_CR_PCKPOL | FV_DCMI_CR_VSPOL | FV_DCMI_CR_ENABLE | FV_DCMI_CR_CAPTURE),
          "dcmi_cr_snapshot_pck_vs1_hs0_enabled");
    const fv_dcmi_cfg_t cfg2 = {0, 1, 1500};
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg2);
    CHECK((dcmi.CR & (FV_DCMI_CR_VSPOL | FV_DCMI_CR_HSPOL)) == FV_DCMI_CR_HSPOL, "dcmi_cr_vs0_hs1");

    /* finish: good frame (38,400 B received) */
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg);
    dcmi.RIS = FV_DCMI_RIS_FRAME;
    dma.S[1].NDTR = BUF_BYTES / 4u - FRAME / 4u;
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, fake_millis, &got) == FV_CAP_OK && got == FRAME,
          "finish_ok_38400");
    CHECK((dcmi.CR & (FV_DCMI_CR_ENABLE | FV_DCMI_CR_CAPTURE)) == 0 && (dma.S[1].CR & 1u) == 0, "finish_stops_dcmi_dma");

    /* finish: wrong size */
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg);
    dcmi.RIS = FV_DCMI_RIS_FRAME;
    dma.S[1].NDTR = BUF_BYTES / 4u - 9512u;
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, fake_millis, &got) == FV_CAP_ERR_SIZE && got == 38048u,
          "finish_size_mismatch");

    /* finish: buffer full (frame larger than buffer) */
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg);
    dcmi.RIS = FV_DCMI_RIS_FRAME;
    dma.S[1].NDTR = 0;
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, fake_millis, &got) == FV_CAP_ERR_BUFFER_FULL,
          "finish_buffer_full");

    /* finish: overrun */
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg);
    dcmi.RIS = FV_DCMI_RIS_OVR;
    dma.S[1].NDTR = 100;
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, fake_millis, &got) == FV_CAP_ERR_OVERRUN, "finish_overrun");

    /* finish: timeout (no flag), must respect timeout_ms */
    reset_mocks();
    fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &cfg);
    dma.S[1].NDTR = BUF_BYTES / 4u;
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, fake_millis, &got) == FV_CAP_ERR_TIMEOUT && got == 0 &&
          now_ms > 1500u && now_ms < 1600u, "finish_timeout_1500ms");

    /* argument checks */
    const fv_dcmi_cfg_t badpol = {2, 0, 1500};
    CHECK(fv_dcmi_start(NULL, &dma, buf, BUF_BYTES, &cfg) == FV_CAP_ERR_ARG, "start_null_dcmi");
    CHECK(fv_dcmi_start(&dcmi, &dma, buf + 1, BUF_BYTES - 4u, &cfg) == FV_CAP_ERR_ARG, "start_misaligned_buf");
    CHECK(fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES - 2u, &cfg) == FV_CAP_ERR_ARG, "start_size_not_multiple_of_4");
    CHECK(fv_dcmi_start(&dcmi, &dma, buf, BUF_BYTES, &badpol) == FV_CAP_ERR_ARG, "start_bad_polarity");
    CHECK(fv_dcmi_start(&dcmi, &dma, buf, 0x40000u * 4u, &cfg) == FV_CAP_ERR_ARG, "start_ndtr_overflow");
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, FRAME, &cfg, NULL, &got) == FV_CAP_ERR_ARG, "finish_null_millis");
    CHECK(fv_dcmi_finish(&dcmi, &dma, BUF_BYTES, BUF_BYTES + 4u, &cfg, fake_millis, &got) == FV_CAP_ERR_ARG,
          "finish_frame_larger_than_buf");
    printf("END fails=%d\n", fails);
    return fails;
}
