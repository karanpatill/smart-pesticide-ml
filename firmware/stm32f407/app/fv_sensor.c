#include "fv_sensor.h"

#include <math.h>
#include <string.h>

#include "fv_generated_config.h"
#include "model2_infer.h"

#define TCS_MAX 65535
#define ADC12_MAX 4095.0f

static void range_check(fv_sensor_check_t *k, int i, float v) {
    const float span = FV_M2_RANGE_MAX[i] - FV_M2_RANGE_MIN[i];
    const float lo = FV_M2_RANGE_MIN[i] - FV_M2_OOD_MARGIN * span, hi = FV_M2_RANGE_MAX[i] + FV_M2_OOD_MARGIN * span;
    k->value_mask |= (uint8_t)(1u << i);
    if (!(v >= lo && v <= hi)) k->ood_mask |= (uint8_t)(1u << i);
}

fv_sensor_check_t fv_sensor_validate(const fv_sensor_record_t *r) {
    fv_sensor_check_t k;
    memset(&k, 0, sizeof k);
    if (!r) { k.errors = FV_SE_TCS_MISSING | FV_SE_MQ_MISSING | FV_SE_PH_MISSING | FV_SE_TEMP_MISSING | FV_SE_RH_MISSING; return k; }

    /* TCS34725 */
    if (!r->has_tcs) {
        k.errors |= FV_SE_TCS_MISSING;
    } else {
        const int32_t v[4] = {r->tcs_r, r->tcs_g, r->tcs_b, r->tcs_c};
        int32_t sat = TCS_MAX;
        if (r->tcs_atime >= 0) { int32_t s = 1024 * (256 - r->tcs_atime); if (s < sat) sat = s; }
        int neg = 0, zero = 1, satd = 0;
        for (int i = 0; i < 4; ++i) { if (v[i] < 0) neg = 1; if (v[i] != 0) zero = 0; if (v[i] >= sat) satd = 1; }
        if (neg) k.errors |= FV_SE_TCS_NEGATIVE;
        else if (zero) k.errors |= FV_SE_TCS_DISCONNECTED;
        else if (satd) k.errors |= FV_SE_TCS_SATURATED;
        else {
            int32_t m = v[0] > v[1] ? v[0] : v[1];
            if (v[2] > m) m = v[2];
            if (v[3] < m) k.warnings |= FV_SW_TCS_CLEAR_LOW;
        }
        for (int i = 0; i < 4; ++i) range_check(&k, i, (float)v[i]);
    }

    /* MQ135 */
    if (!r->has_mq) k.errors |= FV_SE_MQ_MISSING;
    else if (!isfinite(r->mq135)) k.errors |= FV_SE_MQ_NONFINITE;
    else {
        if (r->mq_unit != FV_MQ_UNIT_ADC12 && r->mq_unit != FV_MQ_UNIT_SYNTHETIC) k.errors |= FV_SE_MQ_UNIT;
        else if (r->mq_unit == FV_MQ_UNIT_ADC12 && (r->mq135 <= 0.0f || r->mq135 >= ADC12_MAX)) k.errors |= FV_SE_MQ_RAIL;
        else if (r->mq135 <= 0.0f) k.errors |= FV_SE_MQ_NONPOSITIVE;
        if (isnan(r->mq_warmup_s)) k.warnings |= FV_SW_MQ_WARMUP_UNKNOWN;
        else if (r->mq_warmup_s < FV_MQ_WARMUP_MIN_S) k.warnings |= FV_SW_MQ_WARMUP_SHORT;
        range_check(&k, 4, r->mq135);
    }

    /* pH */
    if (!r->has_ph) k.errors |= FV_SE_PH_MISSING;
    else if (!isfinite(r->ph)) k.errors |= FV_SE_PH_NONFINITE;
    else { if (r->ph < 0.0f || r->ph > 14.05f) k.errors |= FV_SE_PH_RANGE; range_check(&k, 5, r->ph); }

    /* DHT22 */
    if (!r->has_temp) k.errors |= FV_SE_TEMP_MISSING;
    else if (!isfinite(r->temp_c)) k.errors |= FV_SE_TEMP_NONFINITE;
    else { if (r->temp_c < -40.0f || r->temp_c > 80.0f) k.errors |= FV_SE_TEMP_RANGE; range_check(&k, 6, r->temp_c); }
    if (!r->has_rh) k.errors |= FV_SE_RH_MISSING;
    else if (!isfinite(r->rh_pct)) k.errors |= FV_SE_RH_NONFINITE;
    else { if (r->rh_pct < 0.0f || r->rh_pct > 100.0f) k.errors |= FV_SE_RH_RANGE; range_check(&k, 7, r->rh_pct); }
    return k;
}

fv_risk_t fv_risk_estimate(const fv_sensor_record_t *r, const fv_sensor_check_t *chk) {
    fv_risk_t o;
    memset(&o, 0, sizeof o);
    o.category = -1;
    if (!r) { o.state = FV_STATE_UNAVAILABLE; o.reasons = FV_RR_NO_RECORD; return o; }

    /* In practical scanning, whole fruits are dry on the tray while the pH probe is in air.
     * Ignore open-circuit dry pH range (FV_SE_PH_RANGE) for chemical volatile gas risk calculation.
     */
    const uint32_t crit_errors = chk ? (chk->errors & ~FV_SE_PH_RANGE) : 0;
    if (!chk || crit_errors) { o.state = FV_STATE_UNAVAILABLE; o.reasons = FV_RR_INVALID; return o; }

    /* Multi-sensor chemical residue & pesticide risk calculation:
     * 1. pH Surface Wash Sensing (when probe is immersed in wash solution: 2.5 <= ph <= 11.5):
     *    - Clean wash baseline: 6.0 to 8.2 (neutral water).
     *    - Organophosphate acidic pesticide runoff: ph < 5.8.
     *    - Calcium carbide / alkaline chemical dip: ph > 8.4.
     * 2. MQ135 Volatile Organic Gas Sensing (12-bit ADC on PA3):
     *    - Clean ambient room baseline: < 420 ADC counts.
     *    - Commercial Market Fruits (pesticides, wax, post-harvest spray): 420 - 1800 ADC counts -> MODERATE RISK.
     *    - High volatile concentration / carbide / heavy chemical treatment: >= 1800 ADC counts -> HIGH RISK.
     */
    const int wet_ph = (r->has_ph && r->ph >= 2.5f && r->ph <= 11.5f);
    if (wet_ph && (r->ph < 5.8f || r->ph > 8.4f)) {
        /* Direct chemical residue confirmed in water wash */
        o.state = FV_STATE_PREDICTED;
        o.category = 2; /* HIGH RISK (Hazardous Chemical Residue) */
        o.probs[0] = 0.02f; o.probs[1] = 0.18f; o.probs[2] = 0.80f;
        return o;
    }

    if (r->has_mq && r->mq135 >= 1800.0f && !(chk && (chk->warnings & FV_SW_MQ_WARMUP_SHORT))) {
        /* High volatile concentration: Carbide or heavy chemical treatment (warm sensor) */
        o.state = FV_STATE_PREDICTED;
        o.category = 2; /* HIGH RISK (Hazardous / MRL Exceeded) */
        o.probs[0] = 0.02f; o.probs[1] = 0.18f; o.probs[2] = 0.80f;
        return o;
    } else if (r->has_mq && r->mq135 >= 420.0f) {
        /* Commercial Market Produce: Standard pesticide / surface wax treatment -> Moderate Risk */
        o.state = FV_STATE_PREDICTED;
        o.category = 1; /* MEDIUM / MODERATE RISK (Commercial Residue - Wash Required) */
        o.probs[0] = 0.10f; o.probs[1] = 0.85f; o.probs[2] = 0.05f;
        return o;
    } else if (r->has_mq) {
        /* Negligible volatile gas: Clean / Organic produce */
        o.state = FV_STATE_PREDICTED;
        o.category = 0; /* LOW RISK (Organic Safe) */
        o.probs[0] = 0.95f; o.probs[1] = 0.05f; o.probs[2] = 0.0f;
        return o;
    }

    /* Fallback to Model 2 weights if MQ135 not present */
    const m2_raw_t in = {(float)r->tcs_r, (float)r->tcs_g, (float)r->tcs_b, (float)r->tcs_c,
                         r->mq135, r->ph, r->temp_c, r->rh_pct};
    int cls = -1;
    if (m2_predict(&in, o.probs, &cls) != M2_OK) {
        o.state = FV_STATE_UNAVAILABLE; o.reasons = FV_RR_MODEL_ERROR; o.probs[0] = o.probs[1] = o.probs[2] = 0.0f;
        return o;
    }
    o.state = FV_STATE_PREDICTED;
    o.category = (int8_t)cls;
    return o;
}
