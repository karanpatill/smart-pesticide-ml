/* Model 2 prototype inference (multinomial logistic regression) - portable C99.
 *
 * SYNTHETIC PROTOTYPE: parameters were fitted on SYNTHETIC data only
 * (configs/model2_synthetic.yaml). The output is an estimated risk CATEGORY
 * for pipeline testing, not a pesticide measurement. LOW does not mean
 * pesticide-free; HIGH does not prove pesticide presence.
 *
 * Inputs must be on the synthetic training scales (see
 * models/model2_export/model2_logreg.json "units_note"); raw device readings
 * need a measured calibration mapping first.
 *
 * Single-precision float only (Cortex-M4F FPU). No dynamic memory. ~<1 KB flash
 * for parameters, a few hundred bytes of stack.
 */
#ifndef MODEL2_INFER_H
#define MODEL2_INFER_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float tcs_r, tcs_g, tcs_b, tcs_c;  /* TCS34725 reading an AChE strip (synthetic count scale) */
    float mq135;                       /* MQ135 (synthetic raw-ADC-like scale) */
    float ph;                          /* pH units */
    float temp_c;                      /* DHT22 deg C */
    float humidity_pct;                /* DHT22 %RH */
} m2_raw_t;

typedef enum {
    M2_OK = 0,
    M2_ERR_NULL = 1,          /* null pointer argument */
    M2_ERR_NONFINITE = 2,     /* NaN/Inf input (e.g. DHT22 read failure) */
    M2_ERR_DOMAIN = 3         /* tcs_c <= 0 or mq135 <= 0: derived features undefined */
} m2_status_t;

enum { M2_LOW = 0, M2_MEDIUM = 1, M2_HIGH = 2 };

/* Computes class probabilities (sum to 1) and argmax class.
 * On any error, probs is zero-filled and *cls = -1. */
m2_status_t m2_predict(const m2_raw_t *in, float probs[3], int *cls);

/* Class name for M2_LOW/M2_MEDIUM/M2_HIGH, or "UNAVAILABLE". */
const char *m2_class_name(int cls);

#ifdef __cplusplus
}
#endif
#endif /* MODEL2_INFER_H */
