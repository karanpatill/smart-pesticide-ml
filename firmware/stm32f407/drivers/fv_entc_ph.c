#include "fv_entc_ph.h"

#include <stddef.h>

float fv_entc_ph_voltage(uint16_t raw) { return (float)raw * 3.3f / 4095.0f; }

float fv_entc_ph_update(fv_entc_ph_t *st, uint16_t raw, float *v_filtered) {
    const float v = fv_entc_ph_voltage(raw);
    if (!st) return 0.0f;
    if (!st->initialised) { st->vf = v; st->initialised = 1; }
    else st->vf = (1.0f - FV_ENTC_PH_ALPHA) * st->vf + FV_ENTC_PH_ALPHA * v;
    if (v_filtered) *v_filtered = st->vf;
    float ph = (st->vf - FV_ENTC_PH_V_AT_7) * FV_ENTC_PH_SLOPE + 7.0f;
    if (ph < 0.0f) ph = 0.0f;
    if (ph > 14.0f) ph = 14.0f;
    return ph;
}
