#include "fv_report.h"

#include <stdio.h>
#include <string.h>

#include "fv_image_check.h"

static const char *const GRADE[3] = {"Good", "Average", "Poor"};
static const char *const STAGE[3] = {"Fresh", "Semi-fresh", "Rotten"};
static const char *const STAGE_SHORT[3] = {"Fresh", "Semi", "Rotten"};   /* fits the 21-column OLED */
static const char *const RISK[3] = {"LOW", "MEDIUM", "HIGH"};
static const char FOOTER[] = "*proto, not lab test";

static int permille(float p) { int v = (int)(p * 1000.0f + 0.5f); return v < 0 ? 0 : (v > 1000 ? 1000 : v); }

static void put(fv_oled_text_t *o, const char *s) {
    if (o->n >= FV_OLED_ROWS) return;
    strncpy(o->line[o->n], s, FV_OLED_COLS);          /* truncates to the 21-column grid */
    o->line[o->n][FV_OLED_COLS] = '\0';
    o->n++;
}

void fv_report_oled(const fv_image_result_t *img, const fv_risk_t *risk, uint32_t flags, fv_status_t st,
                    fv_oled_text_t *o) {
    char b[48];
    memset(o, 0, sizeof *o);
    if (st != FV_OK && st != FV_ERR_INPUT_REJECTED) { snprintf(b, sizeof b, "ERR %s", fv_status_name(st)); put(o, b); }
    if (flags & FV_IC_REJECT_MASK) put(o, "Image REJECTED:retake");
    if (img && img->fruit_state == FV_STATE_UNCERTAIN) {          /* presence gate: no fruit / identity unknown */
        put(o, "Fruit:NOFRUIT/UNKNOWN");
        put(o, "Cond:UNCERTAIN");
        put(o, "Grade:UNCERTAIN");
        put(o, "Shelf:UNCERTAIN");
    } else if (!img || img->fruit_state != FV_STATE_PREDICTED) {
        put(o, "Fruit: UNAVAILABLE");
    } else {
        snprintf(b, sizeof b, "Fruit:%s %d.%03d", FV_FRUIT_LABELS[img->fruit], permille(img->fruit_conf) / 1000,
                 permille(img->fruit_conf) % 1000);
        put(o, b);
        snprintf(b, sizeof b, "Cond:%s", FV_CONDITION_LABELS[img->condition]);
        put(o, b);
        if (img->quality_state == FV_STATE_PREDICTED) snprintf(b, sizeof b, "Grade:%s", GRADE[img->grade]);
        else snprintf(b, sizeof b, "Grade:%s", fv_state_name(img->quality_state));
        put(o, b);
        if (img->shelf_state == FV_STATE_PREDICTED)
            snprintf(b, sizeof b, "Shelf:%d-%dd %s", img->shelf_lo_days, img->shelf_hi_days, STAGE_SHORT[img->stage]);
#ifdef FV_DEMO_PROTO_RISK
        else snprintf(b, sizeof b, "Shelf:%s", img->shelf_state == FV_STATE_UNAVAILABLE ? "no data" : "UNCERTAIN");
#else
        else snprintf(b, sizeof b, "Shelf:%s", img->shelf_state == FV_STATE_UNAVAILABLE ? "N/A" : "UNCERTAIN");
#endif
        put(o, b);
        if (img->consistency & (FV_CONS_R2_CONTRADICTION | FV_CONS_R3_CONDITION_GRADE)) put(o, "!Outputs disagree");
    }
    if (risk && risk->state == FV_STATE_PREDICTED) snprintf(b, sizeof b, "Risk:%s*", RISK[risk->category]);
#ifdef FV_DEMO_PROTO_RISK
    else if (risk && risk->state == FV_STATE_PROTOTYPE && risk->category >= 0 && risk->category < 3)
        snprintf(b, sizeof b, "Risk:%s proto", RISK[risk->category]);
    else if (risk && risk->state == FV_STATE_UNCERTAIN && (risk->reasons & FV_RR_OUT_OF_RANGE))
        snprintf(b, sizeof b, "Risk:OUT-RANGE");
#endif
    else snprintf(b, sizeof b, "Risk:%s", risk ? fv_state_name(risk->state) : "UNAVAILABLE");
    put(o, b);
    put(o, FOOTER);
}

static void fmt_x10(char *b, size_t n, const char *prefix, int v10, const char *suffix) {
    const int neg = v10 < 0, a = neg ? -v10 : v10;
    snprintf(b, n, "%s%s%d.%d%s", prefix, neg ? "-" : "", a / 10, a % 10, suffix);
}

void fv_report_oled_sensors(fv_oled_text_t *o, const fv_sensor_record_t *r) {
    if (!o || !r || o->n < 1 || o->n > FV_OLED_ROWS || strcmp(o->line[o->n - 1], FOOTER) != 0) return;
    int free_rows = FV_OLED_ROWS - o->n;
    if (free_rows <= 0) return;
    char l1[96], l2[96], ph[24], mq[24], t[24], h[24];   /* generous: put() clips rows to 21 columns */
    if (r->has_ph && r->ph >= 0.0f && r->ph <= 14.0f) {
        const int p = (int)(r->ph * 100.0f + 0.5f);
        snprintf(ph, sizeof ph, "%d.%02d", p / 100, p % 100);
    } else snprintf(ph, sizeof ph, "--");
    if (r->has_mq && r->mq135 >= 0.0f && r->mq135 <= 4095.0f)
        snprintf(mq, sizeof mq, "%d%s", (int)(r->mq135 + 0.5f), r->mq_warmup_s < 120.0f ? "w" : "");
    else snprintf(mq, sizeof mq, "--");
    snprintf(l1, sizeof l1, "pH%s ENTC MQ%s", ph, mq);
    if (r->has_temp) fmt_x10(t, sizeof t, "T", (int)(r->temp_c * 10.0f + (r->temp_c < 0 ? -0.5f : 0.5f)), "C");
    else snprintf(t, sizeof t, "T--");
    if (r->has_rh) snprintf(h, sizeof h, "RH%d%%", (int)(r->rh_pct + 0.5f));
    else snprintf(h, sizeof h, "RH--");
    snprintf(l2, sizeof l2, "%s %s", t, h);
    const char *add[2] = {l1, l2};
    const int n_add = free_rows < 2 ? free_rows : 2;
    o->n--;                                                       /* remove footer, append, re-add footer */
    for (int i = 0; i < n_add; ++i) put(o, add[i]);
    put(o, FOOTER);
}

static int risk_has_category(const fv_risk_t *risk) {
#ifdef FV_DEMO_PROTO_RISK
    if (risk && risk->state == FV_STATE_PROTOTYPE && risk->category >= 0 && risk->category < 3) return 1;
#endif
    return risk && risk->state == FV_STATE_PREDICTED;
}

int fv_report_serial(const fv_image_result_t *img, const fv_risk_t *risk, const fv_sensor_check_t *chk,
                     uint32_t flags, fv_status_t st, char *buf, size_t n) {
    if (!buf || n == 0) return -1;
    const int has = img && img->fruit_state == FV_STATE_PREDICTED;
    int k = snprintf(buf, n,
                     "FV1,status=%s,img_flags=0x%lx,fruit=%s,fruit_pm=%d,fruit_st=%s,cond=%s,cond_pm=%d,"
                     "grade=%s,grade_st=%s,shelf=%d-%d,shelf_st=%s,stage=%s,cons=0x%lx,risk=%s,risk_st=%s,"
                     "risk_reasons=0x%lx,sens_err=0x%lx,sens_warn=0x%lx,ood=0x%x\r\n",
                     fv_status_name(st), (unsigned long)flags, has ? FV_FRUIT_LABELS[img->fruit] : "-",
                     has ? permille(img->fruit_conf) : -1, img ? fv_state_name(img->fruit_state) : "UNAVAILABLE",
                     has ? FV_CONDITION_LABELS[img->condition] : "-", has ? permille(img->condition_conf) : -1,
                     (has && img->quality_state == FV_STATE_PREDICTED) ? GRADE[img->grade] : "-",
                     img ? fv_state_name(img->quality_state) : "UNAVAILABLE",
                     img ? img->shelf_lo_days : -1, img ? img->shelf_hi_days : -1,
                     img ? fv_state_name(img->shelf_state) : "UNAVAILABLE",
                     (has && img->shelf_state == FV_STATE_PREDICTED) ? STAGE[img->stage] : "-",
                     img ? (unsigned long)img->consistency : 0ul,
                     risk_has_category(risk) ? RISK[risk->category] : "-",
                     risk ? fv_state_name(risk->state) : "UNAVAILABLE", risk ? (unsigned long)risk->reasons : 0ul,
                     chk ? (unsigned long)chk->errors : 0ul, chk ? (unsigned long)chk->warnings : 0ul,
                     chk ? chk->ood_mask : 0u);
    return (k < 0 || (size_t)k >= n) ? -1 : k;
}
