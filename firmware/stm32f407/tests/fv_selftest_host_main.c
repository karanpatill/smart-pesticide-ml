/* HOST run of the self-test core (x86, TFLM portable CMSIS-NN). Verifies the self-test logic itself
 * reports PASS when outputs match; not evidence of target behaviour. */
#include <stdio.h>

#include "fv_generated_config.h"
#include "fv_selftest.h"

extern const unsigned char g_fv_model_data[];
__attribute__((aligned(16))) static uint8_t g_p[FV_ARENA_PERSISTENT_BYTES];
__attribute__((aligned(16))) static uint8_t g_np[FV_ARENA_NONPERSISTENT_BYTES];
fv_selftest_t g_fv_selftest;

int main(void) {
    fv_selftest_t *s = &g_fv_selftest;
    fv_selftest_run(s, g_fv_model_data, g_p, sizeof g_p, g_np, sizeof g_np, NULL);
    printf("init=%d used=%u inv=%d,%d,%d mism=%u,%u,%u maxdiff=%d resmism=%u fruit=%d,%d,%d m2=%d cls=%d p=%.6f,%.6f,%.6f m2ok=%d PASS=%u\n",
           s->init_status, s->arena_used_bytes, s->invoke_status[0], s->invoke_status[1], s->invoke_status[2],
           s->raw_mismatches[0], s->raw_mismatches[1], s->raw_mismatches[2], s->max_abs_diff, s->result_mismatches,
           s->fruit[0], s->fruit[1], s->fruit[2], s->m2_status, s->m2_class, (double)s->m2_probs[0],
           (double)s->m2_probs[1], (double)s->m2_probs[2], s->m2_ok, s->pass);
    if (s->frame_present)
        printf("FRAME pp=%d hash=0x%08X hash_ok=%u flags=%u inv=%d mism=%u fruit=%d result_ok=%u\n", s->frame_pp_status,
               (unsigned)s->frame_input_hash, s->frame_input_hash_ok, s->frame_image_flags, s->frame_invoke_status,
               s->frame_raw_mismatches, s->frame_fruit, s->frame_result_ok);
    return s->pass ? 0 : 1;
}
