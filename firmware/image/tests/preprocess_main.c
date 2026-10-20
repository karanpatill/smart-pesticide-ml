/* Host parity harness (not firmware): reads "W H BE" then W*H*2 raw bytes from stdin,
 * writes 80*80*3 int8 bytes to stdout. */
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#include "../preprocess_rgb565.h"

int main(void) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);   /* raw pixel bytes: no CR/LF or ^Z translation */
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    int w, h, be;
    if (scanf("%d %d %d", &w, &h, &be) != 3) return 2;
    getchar(); /* consume the single newline after the header */
    size_t n = (size_t)w * (size_t)h * 2;
    unsigned char *src = (unsigned char *)malloc(n);
    if (!src || fread(src, 1, n, stdin) != n) return 3;
    int8_t dst[FV_IN_BYTES];
    int rc = fv_rgb565_to_input_int8(src, w, h, be, dst);
    if (rc) return 4;
    fwrite(dst, 1, sizeof dst, stdout);
    free(src);
    return 0;
}
