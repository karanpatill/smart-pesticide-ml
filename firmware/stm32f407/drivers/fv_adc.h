/* STM32F4 ADC1 single software-triggered conversion, register level (RM0090 13). Mockable register block. */
#ifndef FV_ADC_H
#define FV_ADC_H
#include <stdint.h>

typedef struct {
    volatile uint32_t SR, CR1, CR2, SMPR1, SMPR2, JOFR[4], HTR, LTR, SQR1, SQR2, SQR3, JSQR, JDR[4], DR;
} fv_adc_regs_t;

enum { FV_ADC_OK = 0, FV_ADC_ERR_ARG = -1, FV_ADC_ERR_TIMEOUT = -2 };

void fv_adc_set_mock(fv_adc_regs_t *adc);     /* host tests only; NULL = hardware ADC1 */
void fv_adc_init(void);                        /* ADC1 clock on, PCLK2/4, 12-bit, right aligned, ADON */
/* One conversion of `channel` (0..18) with 480-cycle sampling (as the ENTC firmware). */
int fv_adc_read(int channel, uint16_t *value);
/* Mean of n conversions (n >= 1). */
int fv_adc_read_avg(int channel, int n, uint16_t *value);

#endif
