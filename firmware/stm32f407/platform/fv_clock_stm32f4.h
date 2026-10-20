/* Board-independent STM32F405/407 clock + timebase (register level, RM0090). Uses the INTERNAL HSI
 * oscillator only, so it does not depend on the board's crystal. Touches no GPIO. */
#ifndef FV_CLOCK_STM32F4_H
#define FV_CLOCK_STM32F4_H
#include <stdint.h>

#define FV_SYSCLK_HZ 168000000u

/* HSI 16 MHz -> PLL (M=16, N=336, P=2, Q=7) -> SYSCLK 168 MHz, AHB 168, APB1 42, APB2 84, USB/SDIO 48.
 * Flash: 5 wait states + prefetch + I/D cache. Returns 0 on success; on PLL timeout stays on HSI
 * (16 MHz) and returns -1. */
int fv_clock_init_hsi_168mhz(void);
uint32_t fv_clock_sysclk_source(void);   /* RCC_CFGR.SWS: 0 HSI, 1 HSE, 2 PLL */
void fv_systick_init_1ms(uint32_t core_hz);
uint32_t fv_millis(void);
void fv_dwt_cycle_counter_init(void);
uint32_t fv_dwt_cycles(void);

#endif
