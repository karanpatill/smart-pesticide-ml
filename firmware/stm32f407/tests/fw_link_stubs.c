/* LINK-CHECK ONLY. Stand-ins for the two newlib functions the firmware needs that zig's
 * freestanding runtime does not provide, so the linker script can be exercised with lld.
 * The resulting ELF is NOT flashable: snprintf here is a non-functional placeholder and its real
 * newlib-nano size (~1-3 KB without float formatting) is NOT included in the measured sizes. */
#include <stdarg.h>
#include <stddef.h>

int snprintf(char *buf, size_t n, const char *fmt, ...) {
    (void)fmt;
    if (buf && n) buf[0] = '\0';
    return -1;
}

char *strncpy(char *d, const char *s, size_t n) {
    size_t i = 0;
    for (; i < n && s[i]; ++i) d[i] = s[i];
    for (; i < n; ++i) d[i] = '\0';
    return d;
}

/* weak: the WSL link check also links tools/stm32_memory/cm4_libc_stubs.c, which defines strcmp */
__attribute__((weak)) int strcmp(const char *a, const char *b) {
    while (*a && *a == *b) { ++a; ++b; }
    return (unsigned char)*a - (unsigned char)*b;
}
