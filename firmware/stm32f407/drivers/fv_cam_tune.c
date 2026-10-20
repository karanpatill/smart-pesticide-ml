#include "fv_cam_tune.h"

#include <stddef.h>

static const uint8_t WB_MANUAL[4][3] = {          /* CC, CD, CE: sunny, cloudy, office, home */
    {0x5E, 0x41, 0x54}, {0x65, 0x41, 0x4F}, {0x52, 0x41, 0x66}, {0x42, 0x3F, 0x71}};
static const uint8_t SAT_UV[5] = {0x28, 0x38, 0x48, 0x58, 0x68};
static const uint8_t AE_LEVEL[6][3] = {           /* AEW, AEB, VV (sensor bank) */
    {0x40, 0x38, 0x82}, {0x20, 0x18, 0x60}, {0x34, 0x1C, 0x00}, {0x3E, 0x38, 0x81}, {0x48, 0x40, 0x81}, {0x58, 0x50, 0x92}};

int fv_cam_tune_pairs(uint32_t lenc, uint32_t awb, uint32_t sat, uint32_t ae, fv_cam_reg_t *out, int max) {
    if (!out || lenc >= FV_TUNE_LENC_N || awb >= FV_TUNE_AWB_N || sat >= FV_TUNE_SAT_N || ae >= FV_TUNE_AE_N) return -1;
    fv_cam_reg_t t[FV_CAM_TUNE_MAX_PAIRS];
    int n = 0;
#define PUT(r, v) do { t[n].reg = (uint8_t)(r); t[n].val = (uint8_t)(v); ++n; } while (0)
    PUT(0xFF, 0x00);                                       /* DSP bank */
    PUT(0xC3, lenc ? 0xFF : 0xFD);                         /* CTRL1: ENTC 0xFD, bit1 = LENC */
    PUT(0xC7, awb == 0 ? 0x10 : awb == 1 ? 0x00 : 0x40);
    if (awb >= 2) { PUT(0xCC, WB_MANUAL[awb - 2][0]); PUT(0xCD, WB_MANUAL[awb - 2][1]); PUT(0xCE, WB_MANUAL[awb - 2][2]); }
    PUT(0x7C, 0x00); PUT(0x7D, sat ? 0x02 : 0x00);         /* SDE control: ENTC 0x00 (off); 0x02 = saturation */
    if (sat) { PUT(0x7C, 0x03); PUT(0x7D, SAT_UV[sat - 1]); PUT(0x7D, SAT_UV[sat - 1]); }
    PUT(0xFF, 0x01);                                       /* sensor bank */
    PUT(0x24, AE_LEVEL[ae][0]); PUT(0x25, AE_LEVEL[ae][1]); PUT(0x26, AE_LEVEL[ae][2]);
    PUT(0xFF, 0x00);
#undef PUT
    if (n > max) return -1;
    for (int i = 0; i < n; ++i) out[i] = t[i];
    return n;
}

#ifdef FV_DIAG_CAM_TUNE
__attribute__((used, aligned(4))) fv_cam_tune_t g_fv_cam_tune;

void fv_cam_tune_service(uint32_t now_ms) {
    fv_cam_tune_t *t = &g_fv_cam_tune;
    if (t->magic != FV_CAM_TUNE_MAGIC || t->req == t->ack) return;
    const uint32_t req = t->req, v[4] = {t->lenc, t->awb, t->sat, t->ae};
    fv_cam_reg_t regs[FV_CAM_TUNE_MAX_PAIRS];
    const int n = fv_cam_tune_pairs(v[0], v[1], v[2], v[3], regs, FV_CAM_TUNE_MAX_PAIRS);
    int32_t st = FV_CAM_TUNE_ERR_RANGE;
    if (n > 0) st = fv_camera_write_regs(regs, n) == 0 ? FV_CAM_TUNE_OK : FV_CAM_TUNE_ERR_BUS;
    if (st == FV_CAM_TUNE_OK) for (int k = 0; k < 4; ++k) t->applied[k] = v[k];
    t->status = st;
    t->applied_ms = now_ms;
    __sync_synchronize();
    t->ack = req;
}
#endif
