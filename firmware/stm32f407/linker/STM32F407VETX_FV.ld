/* Linker script for STM32F407VETx (512K flash, 128K SRAM1+SRAM2, 64K CCM) - Smart Pesticide FW.
 * Memory map per RM0090 / DS8626 (confirm against the documents). NOT yet used by a GCC/newlib
 * build on hardware; checked by an lld link (tools/firmware/build_fw_check.sh) and by
 * tests/test_fw_linker.py.
 *
 * Rules enforced below (ASSERTs fail the link):
 *  - DMA-capable buffers (.dma_buffers) and the TFLM non-persistent arena live in RAM (SRAM1/2),
 *    never in CCMRAM (DMA2/DCMI cannot reach CCM).
 *  - Only the TFLM persistent arena (.ccm_arena, CPU-only) is placed in CCMRAM.
 *  - A dedicated stack region (_Min_Stack_Size) sits at the top of RAM after all RAM sections;
 *    the link fails if .data + .bss + .dma_buffers + stack exceed 128K.
 *  - No single section spans two regions (each output section is assigned to one region).
 */
ENTRY(Reset_Handler)

_Min_Stack_Size = 0x2000;   /* 8 KB main stack (PLAN; measure by stack painting on target) */

MEMORY
{
  FLASH  (rx)  : ORIGIN = 0x08000000, LENGTH = 512K
  RAM    (xrw) : ORIGIN = 0x20000000, LENGTH = 128K
  CCMRAM (rw)  : ORIGIN = 0x10000000, LENGTH = 64K
}

_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS
{
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } >FLASH

  .text : { . = ALIGN(4); *(.text) *(.text*) *(.glue_7) *(.glue_7t) KEEP(*(.init)) KEEP(*(.fini)) . = ALIGN(4); _etext = .; } >FLASH

  /* Model flatbuffer is const data -> .rodata (TFLM requires 16-byte alignment; set on the array). */
  .rodata : { . = ALIGN(16); *(.rodata) *(.rodata*) . = ALIGN(4); } >FLASH

  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } >FLASH
  .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } >FLASH

  .init_array : { PROVIDE_HIDDEN(__init_array_start = .); KEEP(*(SORT(.init_array.*))) KEEP(*(.init_array*)) PROVIDE_HIDDEN(__init_array_end = .); } >FLASH

  _sidata = LOADADDR(.data);
  .data : { . = ALIGN(4); _sdata = .; *(.data) *(.data*) . = ALIGN(4); _edata = .; } >RAM AT>FLASH

  .bss (NOLOAD) : { . = ALIGN(4); _sbss = .; *(.bss) *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } >RAM

  /* Static DMA buffers (FV_DMA_BUFFER): SRAM only. Zeroing not required. */
  .dma_buffers (NOLOAD) : { . = ALIGN(4); _sdma = .; *(.dma_buffers) *(.dma_buffers*) . = ALIGN(4); _edma = .; } >RAM

  /* Reserve the stack at the top of RAM so overlap with any RAM section fails the link. */
  ._stack (NOLOAD) : { . = ALIGN(8); _sstack_reserved = .; . = . + _Min_Stack_Size; . = ALIGN(8); } >RAM

  /* TFLM persistent arena: CPU-only data. NOLOAD (not copied/zeroed by startup). */
  .ccm_arena (NOLOAD) : { . = ALIGN(16); _sccm = .; *(.ccm_arena) *(.ccm_arena*) . = ALIGN(16); _eccm = .; } >CCMRAM

  /DISCARD/ : { *(.note.GNU-stack) *(.gnu_debuglink) }
}

ASSERT(_sstack_reserved + _Min_Stack_Size <= _estack, "RAM overflow: .data + .bss + .dma_buffers + stack exceed 128K")
ASSERT(_eccm <= ORIGIN(CCMRAM) + LENGTH(CCMRAM), "CCM overflow")
ASSERT(_sdma >= ORIGIN(RAM) && _edma <= ORIGIN(RAM) + LENGTH(RAM), "DMA buffers must be in SRAM (RAM)")
