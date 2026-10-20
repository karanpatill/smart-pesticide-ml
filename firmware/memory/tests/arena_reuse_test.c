/* Host unit test for fv_select_camera_window (not firmware). Exit code 0 = all pass. */
#include <stdio.h>

#include "../fv_arena_reuse.h"

static unsigned char arena[96000] __attribute__((aligned(16)));
static int fails = 0;
#define CHECK(c, msg) do { if (!(c)) { printf("FAIL: %s\n", msg); ++fails; } else printf("ok: %s\n", msg); } while (0)

int main(void) {
    /* Layout MEASURED with TFLM (32-bit host, CMSIS-NN kernels, split arenas 53120/96000):
     * input0 at offset 0 (19200 B); outputs at offsets 0..160 (2..5 B each). */
    fv_range_t busy[9] = {{arena + 0, 19200}, {arena + 144, 2}, {arena + 48, 3}, {arena + 64, 3}, {arena + 32, 3},
                          {arena + 80, 3}, {arena + 0, 3}, {arena + 112, 5}, {arena + 96, 2}};
    unsigned char *w = fv_select_camera_window(arena, sizeof arena, busy, 9, 96 * 96 * 2, 16);
    CHECK(w == arena + 19200, "96x96 RGB565 window placed right after the input tensor (offset 19200)");
    w = fv_select_camera_window(arena, sizeof arena, busy, 9, 160 * 120 * 2, 16);
    CHECK(w == arena + 19200, "QQVGA RGB565 (38400 B) also fits at offset 19200");
    w = fv_select_camera_window(arena, sizeof arena, busy, 9, 96000 - 19200 + 1, 16);
    CHECK(w == NULL, "window larger than the free space is refused");
    /* input placed in the middle: window must go to the start */
    fv_range_t mid[1] = {{arena + 40000, 19200}};
    w = fv_select_camera_window(arena, sizeof arena, mid, 1, 18432, 16);
    CHECK(w == arena, "lowest free window chosen when input is in the middle");
    w = fv_select_camera_window(arena, sizeof arena, mid, 1, 45000, 16);
    CHECK(w == NULL, "no window when neither gap is big enough");
    /* misaligned end rounds up */
    fv_range_t odd[1] = {{arena + 0, 19201}};
    w = fv_select_camera_window(arena, sizeof arena, odd, 1, 1000, 16);
    CHECK(w == arena + 19216, "start rounded up to 16-byte alignment");
    CHECK(fv_select_camera_window(NULL, 10, NULL, 0, 4, 16) == NULL, "null arena rejected");
    CHECK(fv_select_camera_window(arena, sizeof arena, busy, 9, 64, 12) == NULL, "non-power-of-two alignment rejected");
    return fails ? 1 : 0;
}
