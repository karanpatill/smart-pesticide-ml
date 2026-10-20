/* TARGET entry point of the self-test image. Board-independent: configures only the core clock
 * (HSI->PLL 168 MHz), SysTick, the DWT cycle counter and the FPU (startup). NO GPIO and no peripheral
 * pins are touched, so all board pins stay in their reset state. Results go to g_fv_selftest (SRAM)
 * and are read back over SWD with tools/firmware/read_selftest.py. */
#include <string.h>

#include "fv_clock_stm32f4.h"
#include "fv_generated_config.h"
#include "fv_selftest.h"

extern const unsigned char g_fv_model_data[];
extern uint32_t _sstack_reserved, _estack;

__attribute__((section(".ccm_arena"), aligned(16))) static uint8_t g_arena_persistent[FV_ARENA_PERSISTENT_BYTES];
__attribute__((aligned(16))) static uint8_t g_arena_nonpersistent[FV_ARENA_NONPERSISTENT_BYTES];
__attribute__((used, aligned(4))) fv_selftest_t g_fv_selftest;

#define STACK_PAINT 0xA5A5A5A5u

static void paint_stack(void) {
    uint32_t sp;
    __asm volatile("mov %0, sp" : "=r"(sp));
    for (volatile uint32_t *p = &_sstack_reserved; (uint32_t)(uintptr_t)p < sp - 64u; ++p) *p = STACK_PAINT;
}

static uint32_t stack_used(void) {
    const uint32_t *p = &_sstack_reserved;
    while (p < &_estack && *p == STACK_PAINT) ++p;
    return (uint32_t)((uintptr_t)&_estack - (uintptr_t)p);
}

int main(void) {
    memset(&g_fv_selftest, 0, sizeof g_fv_selftest);
    paint_stack();
    g_fv_selftest.clock_status = fv_clock_init_hsi_168mhz();
    g_fv_selftest.sysclk_source = fv_clock_sysclk_source();
    fv_systick_init_1ms(g_fv_selftest.clock_status == 0 ? FV_SYSCLK_HZ : 16000000u);
    fv_dwt_cycle_counter_init();
    fv_selftest_run(&g_fv_selftest, g_fv_model_data, g_arena_persistent, sizeof g_arena_persistent,
                    g_arena_nonpersistent, sizeof g_arena_nonpersistent, fv_dwt_cycles);
    g_fv_selftest.stack_used_bytes = stack_used();
    if (g_fv_selftest.clock_status != 0 || g_fv_selftest.sysclk_source != 2u) g_fv_selftest.pass = 0;
    g_fv_selftest.magic = FV_ST_MAGIC_DONE;
    for (;;) g_fv_selftest.heartbeat_ms = fv_millis();
}
