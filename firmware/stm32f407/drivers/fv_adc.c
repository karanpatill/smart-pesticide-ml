#include "fv_adc.h"

#include <stddef.h>

#define ADC1_BASE 0x40012000u
#define ADC_CCR (*(volatile uint32_t *)0x40012304u)
#define RCC_APB2ENR (*(volatile uint32_t *)0x40023844u)
#define SR_EOC (1u << 1)
#define CR2_ADON (1u << 0)
#define CR2_SWSTART (1u << 30)
#define TIMEOUT 100000u

static fv_adc_regs_t *s_mock;

void fv_adc_set_mock(fv_adc_regs_t *adc) { s_mock = adc; }

static fv_adc_regs_t *adc1(void) { return s_mock ? s_mock : (fv_adc_regs_t *)(uintptr_t)ADC1_BASE; }

void fv_adc_init(void) {
    if (!s_mock) {
        RCC_APB2ENR |= 1u << 8;                 /* ADC1EN */
        (void)RCC_APB2ENR;
        ADC_CCR = (ADC_CCR & ~(3u << 16)) | (1u << 16);   /* ADCPRE = PCLK2/4 (84 MHz -> 21 MHz <= 36 MHz) */
    }
    fv_adc_regs_t *a = adc1();
    a->CR1 = 0;                                 /* 12-bit, no scan */
    a->CR2 = CR2_ADON;                          /* single conversion, right aligned */
}

int fv_adc_read(int channel, uint16_t *value) {
    if (channel < 0 || channel > 18 || !value) return FV_ADC_ERR_ARG;
    fv_adc_regs_t *a = adc1();
    if (channel <= 9) {
        const uint32_t s = 3u * (uint32_t)channel;
        a->SMPR2 = (a->SMPR2 & ~(7u << s)) | (7u << s);          /* 480 cycles */
    } else {
        const uint32_t s = 3u * (uint32_t)(channel - 10);
        a->SMPR1 = (a->SMPR1 & ~(7u << s)) | (7u << s);
    }
    a->SQR1 = 0;                                                 /* 1 conversion */
    a->SQR3 = (uint32_t)channel;
    a->CR2 |= CR2_SWSTART;                                       /* EOC of the previous result was cleared by DR read */
    for (uint32_t i = 0; i < TIMEOUT; ++i)
        if (a->SR & SR_EOC) {
            *value = (uint16_t)(a->DR & 0x0FFFu);               /* reading DR clears EOC */
            return FV_ADC_OK;
        }
    return FV_ADC_ERR_TIMEOUT;
}

int fv_adc_read_avg(int channel, int n, uint16_t *value) {
    if (n < 1 || !value) return FV_ADC_ERR_ARG;
    uint32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        uint16_t v = 0;
        const int r = fv_adc_read(channel, &v);
        if (r != FV_ADC_OK) return r;
        sum += v;
    }
    *value = (uint16_t)((sum + (uint32_t)n / 2u) / (uint32_t)n);
    return FV_ADC_OK;
}
