/* SNIPPET (not a complete linker script) for STM32F407VETx GCC builds.
 * Merge into the CubeMX-generated STM32F407VETX_FLASH.ld. Not built or tested on hardware.
 *
 * Memory map (RM0090 / DS8626 - confirm against the documents):
 *   FLASH   0x08000000  512K   sectors 0-3: 16K, 4: 64K, 5-7: 128K
 *   RAM     0x20000000  128K   SRAM1 112K + SRAM2 16K (contiguous); reachable by DMA1/DMA2
 *   CCMRAM  0x10000000   64K   CPU D-bus only: NOT reachable by any DMA (incl. DCMI), no code execution
 *
 * Placement rules used by docs/STM32_MEMORY_PLAN.md:
 *   - TFLM persistent arena (CPU-only data)           -> CCMRAM  (.ccm_arena, NOLOAD)
 *   - TFLM non-persistent arena (camera DMA reuses it) -> RAM     (.bss)
 *   - any buffer touched by DMA (DCMI, I2C, ADC, UART) -> RAM, never CCMRAM, never on a CCM stack
 */
MEMORY
{
  CCMRAM (xrw) : ORIGIN = 0x10000000, LENGTH = 64K
  RAM    (xrw) : ORIGIN = 0x20000000, LENGTH = 128K
  FLASH  (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
}

SECTIONS
{
  /* NOLOAD: not copied or zeroed by startup code; TFLM initialises what it uses. */
  .ccm_arena (NOLOAD) :
  {
    . = ALIGN(16);
    *(.ccm_arena)
    *(.ccm_arena*)
    . = ALIGN(16);
  } >CCMRAM
}
