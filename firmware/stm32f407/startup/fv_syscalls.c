/* Minimal newlib system hooks for the bare-metal firmware (GCC/newlib-nano build).
 * Policy: NO HEAP. All memory is static (TFLM arenas, frame window inside the arena). _sbrk always
 * fails, so any accidental malloc returns NULL instead of growing into the stack or DMA buffers.
 * abort() halts (TFLM references it for unrecoverable internal errors). Replaceable by CubeMX's
 * syscalls.c/sysmem.c once a HAL project exists - keep the no-heap policy. */
#include <errno.h>
#include <stddef.h>

void *_sbrk(ptrdiff_t incr) {
    (void)incr;
    errno = ENOMEM;
    return (void *)-1;
}

void abort(void) {
    for (;;) { }
}
