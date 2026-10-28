#include "fv_result.h"

const char *fv_state_name(fv_state_t s) {
    switch (s) {
        case FV_STATE_PREDICTED: return "PREDICTED";
        case FV_STATE_UNCERTAIN: return "UNCERTAIN";
        default: return "UNAVAILABLE";
    }
}

const char *fv_status_name(fv_status_t s) {
    switch (s) {
        case FV_OK: return "OK";
        case FV_ERR_ARG: return "ERR_ARG";
        case FV_ERR_NOT_IMPLEMENTED: return "ERR_NOT_IMPLEMENTED";
        case FV_ERR_HW: return "ERR_HW";
        case FV_ERR_TIMEOUT: return "ERR_TIMEOUT";
        case FV_ERR_MODEL: return "ERR_MODEL";
        case FV_ERR_MEMORY: return "ERR_MEMORY";
        case FV_ERR_INPUT_REJECTED: return "ERR_INPUT_REJECTED";
        default: return "ERR_UNKNOWN";
    }
}

float fv_prob(const fv_vision_raw_t *raw, fv_head_t h, int k) {
    return (float)((int)raw->q[h][k] - FV_MODEL_OUT_ZERO_POINT) * FV_MODEL_OUT_SCALE;
}

/* First index of the maximum (same tie-break as Python max(dict, key=dict.get)). */
static int argmax(const fv_vision_raw_t *raw, fv_head_t h) {
    int best = 0;
    for (int k = 1; k < FV_HEAD_N_CLASSES[h]; ++k)
        if (raw->q[h][k] > raw->q[h][best]) best = k;
    return best;
}

static const int8_t QUALITY_HEAD[FV_N_FRUITS] = {
    FV_HEAD_QUALITY_APPLE, FV_HEAD_QUALITY_BANANA, FV_HEAD_QUALITY_GUAVA, FV_HEAD_STAGE_TOMATO, FV_HEAD_STAGE_BRINJAL};
static const int8_t STAGE_HEAD[FV_N_FRUITS] = {-1, FV_HEAD_STAGE_BANANA, -1, FV_HEAD_STAGE_TOMATO, FV_HEAD_STAGE_BRINJAL};

void fv_result_set_unavailable(fv_image_result_t *o) {
    if (!o) return;
    o->fruit_state = o->condition_state = o->quality_state = o->shelf_state = FV_STATE_UNAVAILABLE;
    o->fruit = o->condition = -1;
    o->fruit_conf = o->condition_conf = o->grade_conf = o->stage_conf = 0.0f;
    o->grade = FV_GRADE_NONE; o->grade_binary = 0; o->quality_head = -1;
    o->stage = FV_STAGE_NONE; o->shelf_lo_days = o->shelf_hi_days = -1; o->stage_head = -1;
    o->consistency = 0;
#ifdef FV_PRESENCE_OUTPUT_INDEX
    o->presence_raw[0] = -128;
    o->presence_raw[1] = -128;
    o->presence_prob = 0.0f;
#endif
}

fv_status_t fv_result_from_raw(const fv_vision_raw_t *raw, fv_image_result_t *o) {
    if (!raw || !o) return FV_ERR_ARG;
    fv_result_set_unavailable(o);
#ifdef FV_PRESENCE_OUTPUT_INDEX
    o->presence_raw[0] = raw->presence_raw[0];
    o->presence_raw[1] = raw->presence_raw[1];
    o->presence_prob = (float)((int)raw->presence_raw[1] - FV_MODEL_OUT_ZERO_POINT) * FV_MODEL_OUT_SCALE;
#endif
    const int f = argmax(raw, FV_HEAD_FRUIT), c = argmax(raw, FV_HEAD_CONDITION);
    for (int k = 0; k < 5; ++k) o->fruit_probs[k] = fv_prob(raw, FV_HEAD_FRUIT, k);
    o->fruit = (int8_t)f; o->fruit_conf = fv_prob(raw, FV_HEAD_FRUIT, f); o->fruit_state = FV_STATE_PREDICTED;
    o->condition = (int8_t)c; o->condition_conf = fv_prob(raw, FV_HEAD_CONDITION, c);
    o->condition_state = FV_STATE_PREDICTED;
    o->grade_binary = (f == FV_FRUIT_APPLE);

    if (o->fruit_conf < 0.28f) {          /* R1: withhold routed outputs if fruit confidence is below 28% */
        o->quality_state = FV_STATE_UNCERTAIN;
        o->shelf_state = FV_STATE_UNCERTAIN;
        o->consistency |= FV_CONS_R1_LOW_FRUIT_CONF;
        return FV_OK;
    }
    const fv_head_t qh = (fv_head_t)QUALITY_HEAD[f];
    const int qk = argmax(raw, qh);
    o->quality_head = (int8_t)qh;
    o->grade_conf = fv_prob(raw, qh, qk);
    if (f == FV_FRUIT_APPLE) o->grade = qk == 0 ? FV_GRADE_GOOD : FV_GRADE_POOR;  /* labels: Good, Poor */
    else o->grade = (int8_t)qk;   /* Good/Average/Poor and Fresh/Semi-fresh/Rotten share index order */
    o->quality_state = FV_STATE_PREDICTED;

    if (STAGE_HEAD[f] >= 0) {
        const fv_head_t sh = (fv_head_t)STAGE_HEAD[f];
        const int sk = argmax(raw, sh);
        o->stage_head = (int8_t)sh;
        o->stage = (int8_t)sk;
        o->stage_conf = fv_prob(raw, sh, sk);
        o->shelf_lo_days = FV_SHELF_RANGE_DAYS[f][sk][0];
        o->shelf_hi_days = FV_SHELF_RANGE_DAYS[f][sk][1];
        o->shelf_state = FV_STATE_PREDICTED;
        if (f == FV_FRUIT_BANANA) {                          /* R2: grade vs stage (different heads) */
            int d = o->grade - o->stage;
            if (d < 0) d = -d;
            if (d == 1) o->consistency |= FV_CONS_R2_MINOR_MISMATCH;
            else if (d == 2) o->consistency |= FV_CONS_R2_CONTRADICTION;
        }
    } else {
        o->shelf_state = FV_STATE_UNAVAILABLE;              /* guava, apple: no data */
    }
    if ((c == 0 && o->grade == FV_GRADE_POOR) || (c == 1 && o->grade == FV_GRADE_GOOD))   /* R3 */
        o->consistency |= FV_CONS_R3_CONDITION_GRADE;
    return FV_OK;
}
