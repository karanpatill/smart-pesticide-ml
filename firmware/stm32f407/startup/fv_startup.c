/* Minimal Cortex-M4F startup for STM32F407xx (portable C, GCC/clang).
 * INTERIM: replace with CubeMX's startup_stm32f407xx.s + system_stm32f4xx.c when the HAL project
 * exists (those also configure clocks). This file only:
 *   1. enables the FPU (code is built with -mfloat-abi=hard; any float op before this would fault),
 *   2. copies .data from flash, zeroes .bss (CCM arena is NOLOAD: not touched),
 *   3. runs C/C++ static constructors (.init_array), then calls main().
 * Vector table: 16 core entries + 82 STM32F407 IRQ entries (IRQ0..IRQ81, RM0090), all routed to
 * Default_Handler unless overridden by a strong definition. */
#include <stdint.h>

extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss, _estack;
extern void (*__init_array_start[])(void);
extern void (*__init_array_end[])(void);
int main(void);

void Default_Handler(void) { for (;;) { } }
void Reset_Handler(void);
void NMI_Handler(void) __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void MemManage_Handler(void) __attribute__((weak, alias("Default_Handler")));
void BusFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void UsageFault_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SVC_Handler(void) __attribute__((weak, alias("Default_Handler")));
void DebugMon_Handler(void) __attribute__((weak, alias("Default_Handler")));
void PendSV_Handler(void) __attribute__((weak, alias("Default_Handler")));
void SysTick_Handler(void) __attribute__((weak, alias("Default_Handler")));

#define FV_N_IRQ 82
typedef void (*vec_t)(void);
__attribute__((section(".isr_vector"), used)) const vec_t g_vectors[16 + FV_N_IRQ] = {
    (vec_t)(uintptr_t)&_estack, Reset_Handler, NMI_Handler, HardFault_Handler, MemManage_Handler,
    BusFault_Handler, UsageFault_Handler, 0, 0, 0, 0, SVC_Handler, DebugMon_Handler, 0, PendSV_Handler,
    SysTick_Handler,
    /* IRQ0..IRQ81 */
    [16 ... 16 + FV_N_IRQ - 1] = Default_Handler,
};

void Reset_Handler(void) {
    /* 1. FPU: CPACR (0xE000ED88) CP10/CP11 full access */
    *(volatile uint32_t *)0xE000ED88u |= (0xFu << 20);
    __asm volatile("dsb\n isb" ::: "memory");
    /* 2. .data / .bss */
    uint32_t *src = &_sidata, *dst = &_sdata;
    while (dst < &_edata) *dst++ = *src++;
    for (dst = &_sbss; dst < &_ebss;) *dst++ = 0u;
    /* 3. constructors */
    for (void (**f)(void) = __init_array_start; f < __init_array_end; ++f) (*f)();
    (void)main();
    for (;;) { }
}
