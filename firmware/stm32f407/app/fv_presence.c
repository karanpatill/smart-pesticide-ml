#include "fv_presence.h"

int fv_presence_apply(fv_image_result_t *r, float image_detail) {
    if (!r || r->fruit_state != FV_STATE_PREDICTED) return 0;
    const float MIN_IMAGE_DETAIL = 110.0f;
    const float MAX_IMAGE_DETAIL = 3500.0f;
    if (image_detail < MIN_IMAGE_DETAIL || image_detail > MAX_IMAGE_DETAIL) {
        // Image detail out of realistic in-focus fruit range (e.g. empty tray or blurred/too-close object)
        r->fruit_state = r->condition_state = r->quality_state = r->shelf_state = FV_STATE_UNCERTAIN;
        r->grade = FV_GRADE_NONE;
        r->stage = FV_STAGE_NONE;
        r->shelf_lo_days = r->shelf_hi_days = -1;
        r->consistency = (r->consistency & FV_CONS_R1_LOW_FRUIT_CONF) | FV_CONS_NO_FRUIT;
        return 0;
    }
    /* Presence Gate: Fruit is confirmed present if model confidence >= 0.28f.
     * In a 5-class network, uniform noise is 0.20; >0.28 indicates active produce detection.
     * Hands/fingers are biometrically rejected by fv_image_check() skin signature. */
    if (r->fruit_conf >= 0.28f) {
        return 1;
    }
    r->fruit_state = r->condition_state = r->quality_state = r->shelf_state = FV_STATE_UNCERTAIN;
    r->grade = FV_GRADE_NONE;
    r->stage = FV_STAGE_NONE;
    r->shelf_lo_days = r->shelf_hi_days = -1;
    r->consistency = (r->consistency & FV_CONS_R1_LOW_FRUIT_CONF) | FV_CONS_NO_FRUIT;
    return 0;
}
