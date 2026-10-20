/* Host-side parity harness (not firmware): reads lines of 8 floats
 * (tcs_r tcs_g tcs_b tcs_c mq135 ph temp_c humidity_pct; "nan"/"inf" allowed)
 * from stdin and prints "status p_low p_medium p_high class" per line. */
#include <stdio.h>
#include <stdlib.h>

#include "../model2_infer.h"

int main(void) {
    char line[512];
    while (fgets(line, sizeof line, stdin)) {
        float v[8];
        char *p = line, *end;
        int n = 0;
        for (; n < 8; ++n) {
            v[n] = strtof(p, &end);
            if (end == p) break;
            p = end;
        }
        if (n != 8) { printf("PARSE_ERROR\n"); continue; }
        m2_raw_t in = {v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]};
        float probs[3];
        int cls;
        m2_status_t st = m2_predict(&in, probs, &cls);
        printf("%d %.9g %.9g %.9g %d\n", (int)st, probs[0], probs[1], probs[2], cls);
    }
    return 0;
}
