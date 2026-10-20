/* DIAGNOSTIC camera tuning (fv_app_v8_diag, -DFV_DIAG_CAM_TUNE): a small RAM block the PC writes over SWD
 * (tools/firmware/cam_tune.py) to try OV2640 image settings without re-flashing. The firmware validates every value,
 * applies it between cycles (never during a DCMI capture) and acknowledges. Index 0 of every setting reproduces the
 * ENTC register values exactly (C3=0xFD, C7=0x10, SDE ctrl 0x00, AEW/AEB/VV 0x40/0x38/0x82).
 * Register values: OV2640 datasheet / esp32-camera ov2640 driver (CTRL1 bits, WB presets, saturation, AE levels). */
#ifndef FV_CAM_TUNE_H
#define FV_CAM_TUNE_H
#include <stdint.h>


#define FV_CAM_TUNE_MAGIC 0x54554E45u   /* "TUNE": written by the PC to enable the block */
#define FV_CAM_TUNE_MAX_PAIRS 24
enum { FV_CAM_TUNE_OK = 0, FV_CAM_TUNE_ERR_RANGE = -1, FV_CAM_TUNE_ERR_BUS = -2 };
enum { FV_TUNE_LENC_N = 2, FV_TUNE_AWB_N = 6, FV_TUNE_SAT_N = 6, FV_TUNE_AE_N = 6 };

typedef struct { uint8_t reg, val; } fv_cam_reg_t;

typedef struct {
    volatile uint32_t magic;       /* PC: FV_CAM_TUNE_MAGIC */
    volatile uint32_t req;         /* PC: increment to request applying lenc/awb/sat/ae */
    volatile uint32_t ack;         /* firmware: = req once handled (applied or rejected) */
    volatile int32_t status;       /* firmware: FV_CAM_TUNE_* of the last request */
    volatile uint32_t applied_ms;  /* firmware: fv_platform_millis() when handled */
    volatile uint32_t lenc;        /* 0 off (ENTC), 1 on */
    volatile uint32_t awb;         /* 0 ENTC (C7=0x10), 1 auto (C7=0x00), 2 sunny, 3 cloudy, 4 office, 5 home */
    volatile uint32_t sat;         /* 0 ENTC (SDE off), 1..5 = saturation -2..+2 */
    volatile uint32_t ae;          /* 0 ENTC, 1..5 = AE level -2..+2 */
    volatile uint32_t applied[4];  /* firmware: lenc/awb/sat/ae currently in effect */
} fv_cam_tune_t;

/* Build the SCCB register writes for one setting combination. Returns the number of pairs, or -1 if a value is out
 * of range or max is too small (nothing is written to out beyond max). Always ends in bank 0x00 (DSP). */
int fv_cam_tune_pairs(uint32_t lenc, uint32_t awb, uint32_t sat, uint32_t ae, fv_cam_reg_t *out, int max);

#ifdef FV_DIAG_CAM_TUNE
extern fv_cam_tune_t g_fv_cam_tune;
int fv_camera_write_regs(const fv_cam_reg_t *regs, int n);   /* platform: 0 ok, <0 camera absent / SCCB NACK */
void fv_cam_tune_service(uint32_t now_ms);                    /* call between cycles */
#endif

#endif
