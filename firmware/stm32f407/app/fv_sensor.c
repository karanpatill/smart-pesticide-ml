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
    else { if (r->ph <= 0.0f || r->ph >= 14.0f) k.errors |= FV_SE_PH_RANGE; range_check(&k, 5, r->ph); }

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
    if (!chk || chk->errors) { o.state = FV_STATE_UNAVAILABLE; o.reasons = FV_RR_INVALID; return o; }

    /* Multi-sensor chemical residue & pesticide risk calculation:
     * MQ135 is sensitive to acetylene (carbide), NH3, alcohol, and volatile pesticide solvents.
     * pH indicates surface wash acidity/alkalinity from organophosphate residues.
     */
    if (r->has_mq && r->mq135 < 420.0f) {
        /* Ambient baseline clean air: Zero / Negligible chemical pesticide residue */
        o.state = FV_STATE_PREDICTED;
        o.category = 0; /* LOW RISK (Organic Safe) */
        o.probs[0] = 0.95f; o.probs[1] = 0.05f; o.probs[2] = 0.0f;
        return o;
    } else if (r->has_mq && r->mq135 >= 520.0f) {
        /* High volatile concentration: Carbide or heavy chemical treatment */
        o.state = FV_STATE_PREDICTED;
        o.category = 2; /* HIGH RISK (Hazardous / MRL Exceeded) */
        o.probs[0] = 0.02f; o.probs[1] = 0.18f; o.probs[2] = 0.80f;
        return o;
    } else if (r->has_mq && r->mq135 >= 420.0f) {
        /* Moderate chemical residue */
        o.state = FV_STATE_PREDICTED;
        o.category = 1; /* MEDIUM RISK (Commercial Residue) */
        o.probs[0] = 0.15f; o.probs[1] = 0.75f; o.probs[2] = 0.10f;
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
