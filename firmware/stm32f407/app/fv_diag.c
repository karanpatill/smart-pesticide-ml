#include "fv_diag.h"

#include <string.h>

__attribute__((used, aligned(4))) fv_diag_t g_fv_diag;

void fv_diag_init(void) {
    memset(&g_fv_diag, 0, sizeof g_fv_diag);
    g_fv_diag.magic = FV_DIAG_MAGIC;
    g_fv_diag.version = FV_DIAG_VERSION;
    g_fv_diag.cam_table_fail_index = 0xFFFFFFFFu;
    g_fv_diag.ph_x100 = -1;
}
