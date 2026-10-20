/* On-target ML self-test (no board peripherals). Runs the frozen INT8 Model 1+3 graph on test inputs
 * embedded in flash, the output-validation rules and Model 2 on a fixed synthetic vector, and stores
 * everything in g_fv_selftest (SRAM) for READ-ONLY readback over SWD (STM32CubeProgrammer -r32).
 * Expected values are generated on the PC (tools/firmware/gen_selftest_data.py). */
#ifndef FV_SELFTEST_H
#define FV_SELFTEST_H
#include <stdint.h>

#define FV_ST_MAGIC_DONE 0xF7A51E57u
#define FV_ST_MAGIC_RUNNING 0x52554E21u
#define FV_ST_VERSION 2u
#define FV_ST_N_INPUTS 3
#define FV_ST_RAW 40
#define FV_IN_BYTES_ST 19200
#define FV_ST_FRAME_W 160
#define FV_ST_FRAME_H 120

/* All fields are 32-bit words except the int8 raw arrays so the PC reader can parse a -r32 dump by offset.
 * Layout is fixed: v1 = 288 B, v2 = 372 B (checked by tests). */
typedef struct {
    uint32_t magic;               /* FV_ST_MAGIC_DONE when finished */
    uint32_t version;
    int32_t clock_status;         /* 0 = PLL 168 MHz from HSI */
    uint32_t sysclk_source;       /* RCC_CFGR.SWS: 2 = PLL */
    int32_t init_status;          /* fv_vision_init */
    uint32_t arena_used_bytes;
    uint32_t n_inputs;
    int32_t invoke_status[FV_ST_N_INPUTS];
    uint32_t invoke_cycles[FV_ST_N_INPUTS];
    uint32_t raw_mismatches[FV_ST_N_INPUTS];   /* int8 values differing from the PC reference */
    int32_t max_abs_diff;
    uint32_t image_flags[FV_ST_N_INPUTS];
    int32_t fruit[FV_ST_N_INPUTS];
    int32_t quality_state[FV_ST_N_INPUTS];
    int32_t grade[FV_ST_N_INPUTS];
    uint32_t consistency[FV_ST_N_INPUTS];
    uint32_t result_mismatches;                /* fv_result fields differing from the PC reference */
    int32_t m2_status;
    int32_t m2_class;
    float m2_probs[3];
    int32_t m2_ok;                              /* class equal and |p - p_ref| < 1e-4 */
    uint32_t stack_used_bytes;                  /* stack painting high-water mark */
    uint32_t pass;                              /* 1 = everything matched */
    int8_t raw[FV_ST_N_INPUTS][FV_ST_RAW];
    volatile uint32_t heartbeat_ms;             /* keeps counting after the test: proves the core runs */
    /* ---- v2: offline camera-format frame (FV_ST_WITH_FRAME). Appended so the v1 offsets stay valid. ---- */
    uint32_t frame_present;                     /* 1 if this image embeds a 160x120 RGB565 frame */
    int32_t frame_pp_status;                    /* fv_rgb565_to_input_int8 return value */
    uint32_t frame_pp_cycles;
    uint32_t frame_input_hash;                  /* FNV-1a 32 of the 19,200 B int8 input tensor */
    uint32_t frame_input_hash_ok;               /* equals the PC (Python reference) hash */
    uint32_t frame_image_flags;                 /* fv_image_check + fv_frame_dims_check */
    int32_t frame_invoke_status;
    uint32_t frame_invoke_cycles;
    uint32_t frame_raw_mismatches;
    int32_t frame_fruit;
    uint32_t frame_result_ok;                   /* fruit/quality/grade/consistency equal the PC reference */
    int8_t frame_raw[FV_ST_RAW];
} fv_selftest_t;

extern fv_selftest_t g_fv_selftest;

/* Portable part (also run on the host). cycles() may be NULL. */
void fv_selftest_run(fv_selftest_t *st, const uint8_t *model, uint8_t *pers, uint32_t pers_bytes, uint8_t *np,
                     uint32_t np_bytes, uint32_t (*cycles)(void));

#endif
