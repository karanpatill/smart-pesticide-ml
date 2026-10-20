/* Output validation / post-processing for Model 1 + Model 3 (portable C99, no heap).
 *
 * C port of src/fruitvision/postprocess.py (rules R1-R3, shelf-life lookup, output states),
 * operating on the INT8 model outputs: p = (q - zero_point) * scale.
 * Parity with the Python implementation is tested in tests/test_fw_result_parity.py.
 */
#ifndef FV_RESULT_H
#define FV_RESULT_H

#include "fv_common.h"
#include "fv_generated_config.h"

#define FV_MAX_CLASSES 5

typedef struct {
    int8_t q[FV_N_HEADS][FV_MAX_CLASSES];  /* raw int8 outputs, indexed by fv_head_t */
#ifdef FV_PRESENCE_OUTPUT_INDEX
    int8_t presence_raw[2];                /* raw int8 background vs fruit presence output */
#endif
} fv_vision_raw_t;

/* grade codes */
enum { FV_GRADE_GOOD = 0, FV_GRADE_AVERAGE = 1, FV_GRADE_POOR = 2, FV_GRADE_NONE = -1 };
/* stage codes */
enum { FV_STAGE_FRESH = 0, FV_STAGE_SEMI = 1, FV_STAGE_ROTTEN = 2, FV_STAGE_NONE = -1 };

/* consistency flags (bitmask) */
#define FV_CONS_R1_LOW_FRUIT_CONF   (1u << 0)
#define FV_CONS_R2_MINOR_MISMATCH   (1u << 1)
#define FV_CONS_R2_CONTRADICTION    (1u << 2)
#define FV_CONS_R3_CONDITION_GRADE  (1u << 3)

typedef struct {
    fv_state_t fruit_state;
    int8_t fruit;            /* fv_fruit_t */
    float fruit_conf;        /* uncalibrated softmax */
    fv_state_t condition_state;
    int8_t condition;        /* 0 fresh, 1 spoiled */
    float condition_conf;

    fv_state_t quality_state;
    int8_t grade;            /* FV_GRADE_*; apple uses GOOD/POOR only */
    float grade_conf;
    uint8_t grade_binary;    /* 1 for apple (Good/Poor scale) */
    int8_t quality_head;     /* fv_head_t or -1 */

    fv_state_t shelf_state;
    int8_t stage;            /* FV_STAGE_* */
    float stage_conf;
    int8_t shelf_lo_days, shelf_hi_days;  /* -1 when not available */
    int8_t stage_head;       /* fv_head_t or -1 */

    uint32_t consistency;    /* FV_CONS_* */
#ifdef FV_PRESENCE_OUTPUT_INDEX
    int8_t presence_raw[2];
    float presence_prob;     /* fruit presence probability: (presence_raw[1] - zp) * scale */
#endif
} fv_image_result_t;

/* Dequantised probability of class k of head h. */
float fv_prob(const fv_vision_raw_t *raw, fv_head_t h, int k);

/* Fills `out` from raw outputs. Returns FV_ERR_ARG on null pointers. */
fv_status_t fv_result_from_raw(const fv_vision_raw_t *raw, fv_image_result_t *out);

/* Marks every image output UNAVAILABLE (e.g. image rejected or camera failed). */
void fv_result_set_unavailable(fv_image_result_t *out);

#endif
