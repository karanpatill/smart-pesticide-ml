#include "fv_arena_reuse.h"

static uintptr_t align_up(uintptr_t v, size_t a) { return (v + a - 1) & ~(uintptr_t)(a - 1); }

/* A window [s, s+need) is valid if it lies inside the arena and overlaps no non-empty busy range. */
static int valid(uintptr_t s, size_t need, uintptr_t lo, uintptr_t hi, const fv_range_t *busy, size_t n) {
    if (s < lo || s + need > hi) return 0;
    for (size_t i = 0; i < n; ++i) {
        uintptr_t b0 = (uintptr_t)busy[i].ptr, b1 = b0 + busy[i].bytes;
        if (busy[i].bytes && s < b1 && b0 < s + need) return 0;
    }
    return 1;
}

uint8_t *fv_select_camera_window(uint8_t *arena, size_t arena_bytes, const fv_range_t *busy, size_t n_busy,
                                 size_t need, size_t align) {
    if (!arena || need == 0 || align == 0 || (align & (align - 1)) || (n_busy && !busy)) return NULL;
    const uintptr_t lo = (uintptr_t)arena, hi = lo + arena_bytes;
    /* The lowest valid window always starts at the arena start or right after a busy range. */
    uintptr_t best = 0;
    int found = 0;
    for (size_t k = 0; k <= n_busy; ++k) {
        uintptr_t s = align_up(k == 0 ? lo : (uintptr_t)busy[k - 1].ptr + busy[k - 1].bytes, align);
        if (valid(s, need, lo, hi, busy, n_busy) && (!found || s < best)) { best = s; found = 1; }
    }
    return found ? (uint8_t *)best : NULL;
}
