/* Sensor record validation + Model 2 (synthetic-prototype) risk applicability (portable C99).
 *
 * C port of src/fruitvision/sensor/validation.py and the risk decision in
 * src/fruitvision/system.py. Parity is tested in tests/test_fw_sensor_parity.py.
 * Validity limits are datasheet/hardware limits, NOT calibration. Device readings without a
 * calibration profile can never yield a PREDICTED risk (no such profile exists yet).
 */
#ifndef FV_SENSOR_H
#define FV_SENSOR_H

#include "fv_common.h"

enum { FV_MQ_UNIT_UNKNOWN = 0, FV_MQ_UNIT_ADC12 = 1, FV_MQ_UNIT_SYNTHETIC = 2 };
enum { FV_ORIGIN_DEVICE = 0, FV_ORIGIN_SYNTHETIC_FIXTURE = 1 };

typedef struct {
    uint8_t has_tcs, has_mq, has_ph, has_temp, has_rh;   /* presence flags (1 = reading supplied) */
    int32_t tcs_r, tcs_g, tcs_b, tcs_c;                  /* TCS34725 raw 16-bit counts */
    int16_t tcs_atime;                                   /* ATIME register, -1 = unknown */
    float mq135;                                         /* in `mq_unit` */
    uint8_t mq_unit;                                     /* FV_MQ_UNIT_* */
    float mq_warmup_s;                                   /* NaN = unknown */
    float ph;
    float temp_c, rh_pct;                                /* DHT22; NaN on read failure */
    uint8_t origin;                                      /* FV_ORIGIN_* */
    uint8_t has_calibration_profile;                     /* 0 today (none exists) */
} fv_sensor_record_t;

/* error bits */
#define FV_SE_TCS_MISSING        (1u << 0)
#define FV_SE_TCS_NEGATIVE       (1u << 1)
#define FV_SE_TCS_DISCONNECTED   (1u << 2)
#define FV_SE_TCS_SATURATED      (1u << 3)
#define FV_SE_MQ_MISSING         (1u << 4)
#define FV_SE_MQ_NONFINITE       (1u << 5)
#define FV_SE_MQ_UNIT            (1u << 6)
#define FV_SE_MQ_RAIL            (1u << 7)
#define FV_SE_MQ_NONPOSITIVE     (1u << 8)
#define FV_SE_PH_MISSING         (1u << 9)
#define FV_SE_PH_NONFINITE       (1u << 10)
#define FV_SE_PH_RANGE           (1u << 11)
#define FV_SE_TEMP_MISSING       (1u << 12)
#define FV_SE_TEMP_NONFINITE     (1u << 13)
#define FV_SE_TEMP_RANGE         (1u << 14)
#define FV_SE_RH_MISSING         (1u << 15)
#define FV_SE_RH_NONFINITE       (1u << 16)
#define FV_SE_RH_RANGE           (1u << 17)
/* warning bits */
#define FV_SW_TCS_CLEAR_LOW      (1u << 0)
#define FV_SW_MQ_WARMUP_UNKNOWN  (1u << 1)
#define FV_SW_MQ_WARMUP_SHORT    (1u << 2)

typedef struct {
    uint32_t errors, warnings;
    uint8_t ood_mask;      /* bit i: raw feature i outside synthetic training range (+/-10 %) */
    uint8_t value_mask;    /* bit i: raw feature i available for range checks */
} fv_sensor_check_t;

/* risk reasons (bitmask, for state UNCERTAIN / UNAVAILABLE) */
#define FV_RR_NO_RECORD          (1u << 0)
#define FV_RR_INVALID            (1u << 1)
#define FV_RR_UNCALIBRATED       (1u << 2)
#define FV_RR_OUT_OF_RANGE       (1u << 3)
#define FV_RR_WARMUP             (1u << 4)
#define FV_RR_MODEL_ERROR        (1u << 5)

typedef struct {
    fv_state_t state;
    int8_t category;       /* 0 LOW, 1 MEDIUM, 2 HIGH, -1 none (only set when PREDICTED) */
    float probs[3];        /* Model 2 probabilities; withheld (zeros) unless PREDICTED */
    uint32_t reasons;      /* FV_RR_* */
} fv_risk_t;

#define FV_MQ_WARMUP_MIN_S 180.0f

fv_sensor_check_t fv_sensor_validate(const fv_sensor_record_t *r);
/* r may be NULL (no record supplied). Runs Model 2 only when the record is valid. */
fv_risk_t fv_risk_estimate(const fv_sensor_record_t *r, const fv_sensor_check_t *chk);

#endif
