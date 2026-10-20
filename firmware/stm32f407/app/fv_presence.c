#include "fv_presence.h"

int fv_presence_apply(fv_image_result_t *r, float image_detail) {
    if (!r || r->fruit_state != FV_STATE_PREDICTED) return 0;
    (void)image_detail;
    const int MIN_IMAGE_DETAIL = 180;
    const int MAX_IMAGE_DETAIL = 3000;
    if (image_detail < MIN_IMAGE_DETAIL || image_detail > MAX_IMAGE_DETAIL) {
        // Image detail out of realistic fruit range => reject detection
        r->fruit_state = r->condition_state = r->quality_state = r->shelf_state = FV_STATE_UNCERTAIN;
        r->grade = FV_GRADE_NONE;
        r->stage = FV_STAGE_NONE;
        r->shelf_lo_days = r->shelf_hi_days = -1;
        r->consistency = (r->consistency & FV_CONS_R1_LOW_FRUIT_CONF) | FV_CONS_NO_FRUIT;
        return 0;
    }
    /* Presence Gate: Fruit is confirmed present if model confidence >= 0.40f */
    if (r->fruit_conf >= 0.40f) {
        return 1;
    }
    r->fruit_state = r->condition_state = r->quality_state = r->shelf_state = FV_STATE_UNCERTAIN;
    r->grade = FV_GRADE_NONE;
    r->stage = FV_STAGE_NONE;
    r->shelf_lo_days = r->shelf_hi_days = -1;
    r->consistency = (r->consistency & FV_CONS_R1_LOW_FRUIT_CONF) | FV_CONS_NO_FRUIT;
    return 0;
}
