/* Fruit-presence gate for the frozen 5-class fruit model (which has NO background / not-a-fruit class and therefore
 * always outputs one of the 5 fruits, e.g. "guava 0.99" for a uniform grey frame).
 * A fruit may only be shown if BOTH hold:
 *   1. image detail (fv_image_detail) >= FV_PRESENCE_MIN_DETAIL   - rejects empty / defocused / featureless scenes
 *   2. fruit confidence >= FV_FRUIT_CONF_THRESHOLD (R1, 0.976)     - rejects uncertain identities
 * Otherwise fruit, condition, grade and shelf life become UNCERTAIN (shown as "NO FRUIT/UNKNOWN") and
 * FV_CONS_NO_FRUIT is set. The raw model outputs are kept for diagnostics.
 * Threshold derivation and evaluation: configs/presence_gate.json, reports/firmware/presence_gate_eval.json
 * (tools/firmware/calibrate_presence_gate.py). This is NOT a trained not-a-fruit detector. */
#ifndef FV_PRESENCE_H
#define FV_PRESENCE_H

#include "fv_result.h"

#define FV_PRESENCE_MIN_DETAIL 43.96f   /* = 0.5 x 0.5th percentile of VAL images in the device camera format */
#define FV_CONS_NO_FRUIT (1u << 4)

/* Returns 1 if a fruit may be shown, 0 otherwise (result fields downgraded to UNCERTAIN). */
int fv_presence_apply(fv_image_result_t *r, float image_detail);

#endif
