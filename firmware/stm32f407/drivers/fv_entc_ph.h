/* pH conversion of the ORIGINAL ENTC firmware ("ENTC calibration"), reproduced exactly from its code
 * (docs/BOARD_PIN_MAP_EVIDENCE.md, @0x08000800 and @0x08002760):
 *   V  = raw * 3.3 / 4095                      (12-bit ADC, nominal 3.3 V reference)
 *   Vf = 0.95 * Vf + 0.05 * V                  (exponential smoothing; first sample initialises Vf here)
 *   pH = (Vf - 2.282) * (-5.263159) + 7.0      (clamped to 0..14)
 * The constants are ENTC's; they were not re-measured by this project. Not a validated pesticide measurement. */
#ifndef FV_ENTC_PH_H
#define FV_ENTC_PH_H
#include <stdint.h>

#define FV_ENTC_PH_V_AT_7 2.282f
#define FV_ENTC_PH_SLOPE (-5.263159275f)
#define FV_ENTC_PH_ALPHA 0.05f
#define FV_ENTC_PH_SAMPLES 200     /* ENTC averages 200 conversions per pH reading */
#define FV_ENTC_MQ_SAMPLES 50      /* ENTC averages 50 conversions per MQ135 reading */
#define FV_ENTC_MQ_WARMUP_MS 120000u

typedef struct { float vf; int initialised; } fv_entc_ph_t;

float fv_entc_ph_voltage(uint16_t raw);
/* Feeds one averaged raw reading; returns the pH (0..14). *v_filtered (optional) receives Vf. */
float fv_entc_ph_update(fv_entc_ph_t *st, uint16_t raw, float *v_filtered);

#endif
