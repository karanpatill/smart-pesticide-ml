/* SIZE-MEASUREMENT STUBS ONLY (not for firmware). On target these come from newlib-nano/libm.
 * They let the freestanding Cortex-M4 link complete so section sizes can be measured; their own
 * size (a few bytes each) is NOT representative of newlib's implementations. */
#include <stddef.h>
int strcmp(const char *a, const char *b) { while (*a && *a == *b) { ++a; ++b; } return (unsigned char)*a - (unsigned char)*b; }
int strncmp(const char *a, const char *b, size_t n) { for (; n && *a && *a == *b; --n) { ++a; ++b; } return n ? (unsigned char)*a - (unsigned char)*b : 0; }
double frexp(double x, int *e) { *e = 0; return x; }   /* STUB: real libm frexp required on target */
void abort(void) { for (;;) {} }
int __cxa_atexit(void (*f)(void *), void *p, void *d) { (void)f; (void)p; (void)d; return 0; }
