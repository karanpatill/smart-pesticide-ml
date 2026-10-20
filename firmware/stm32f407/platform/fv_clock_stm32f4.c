/* Register addresses/bits from RM0090 (STM32F405/407 reference manual). No HAL dependency. */
#include "fv_clock_stm32f4.h"

#define REG(a) (*(volatile uint32_t *)(a))
/* RCC */
#define RCC_CR       REG(0x40023800u)
#define RCC_PLLCFGR  REG(0x40023804u)
#define RCC_CFGR     REG(0x40023808u)
#define RCC_APB1ENR  REG(0x40023840u)
/* PWR */
#define PWR_CR       REG(0x40007000u)
/* FLASH */
#define FLASH_ACR    REG(0x40023C00u)
/* Cortex-M4 core */
#define SYST_CSR     REG(0xE000E010u)
#define SYST_RVR     REG(0xE000E014u)
#define SYST_CVR     REG(0xE000E018u)
#define DEMCR        REG(0xE000EDFCu)
#define DWT_CTRL     REG(0xE0001000u)
#define DWT_CYCCNT   REG(0xE0001004u)

#define TIMEOUT 1000000u

static volatile uint32_t s_ms;

void SysTick_Handler(void) { s_ms++; }

static int wait_set(volatile uint32_t *r, uint32_t mask, uint32_t val) {
    for (uint32_t i = 0; i < TIMEOUT; ++i)
        if ((*r & mask) == val) return 0;
    return -1;
}

int fv_clock_init_hsi_168mhz(void) {
    RCC_CR |= 1u << 0;                                            /* HSION */
    if (wait_set(&RCC_CR, 1u << 1, 1u << 1)) return -1;           /* HSIRDY */
    RCC_APB1ENR |= 1u << 28;                                      /* PWREN */
    (void)RCC_APB1ENR;
    PWR_CR |= 1u << 14;                                           /* VOS = scale 1 (168 MHz) */
    /* flash: 5 WS for 168 MHz @ 2.7-3.6 V, prefetch, I-cache, D-cache (before raising the clock) */
    FLASH_ACR = (FLASH_ACR & ~7u) | 5u | (1u << 8) | (1u << 9) | (1u << 10);
    if ((FLASH_ACR & 7u) != 5u) return -1;
    /* AHB /1, APB1 /4, APB2 /2 */
    RCC_CFGR = (RCC_CFGR & ~((0xFu << 4) | (7u << 10) | (7u << 13))) | (5u << 10) | (4u << 13);
    RCC_CR &= ~(1u << 24);                                        /* PLL off before configuring */
    if (wait_set(&RCC_CR, 1u << 25, 0u)) return -1;
    /* M=16 N=336 P=2 SRC=HSI Q=7; reserved bits kept at their current value (RM0090) */
    RCC_PLLCFGR = (RCC_PLLCFGR & ~0x0F437FFFu) | (16u << 0) | (336u << 6) | (0u << 16) | (0u << 22) | (7u << 24);
    RCC_CR |= 1u << 24;                                           /* PLLON */
    if (wait_set(&RCC_CR, 1u << 25, 1u << 25)) return -1;         /* PLLRDY; stay on HSI on failure */
    RCC_CFGR = (RCC_CFGR & ~3u) | 2u;                             /* SW = PLL */
    if (wait_set(&RCC_CFGR, 3u << 2, 2u << 2)) return -1;         /* SWS = PLL */
    return 0;
}

uint32_t fv_clock_sysclk_source(void) { return (RCC_CFGR >> 2) & 3u; }

void fv_systick_init_1ms(uint32_t core_hz) {
    SYST_RVR = core_hz / 1000u - 1u;
    SYST_CVR = 0;
    SYST_CSR = 7u;                                                /* CLKSOURCE=core, TICKINT, ENABLE */
}

uint32_t fv_millis(void) { return s_ms; }

void fv_dwt_cycle_counter_init(void) {
    DEMCR |= 1u << 24;                                            /* TRCENA */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1u;                                               /* CYCCNTENA */
}

uint32_t fv_dwt_cycles(void) { return DWT_CYCCNT; }
