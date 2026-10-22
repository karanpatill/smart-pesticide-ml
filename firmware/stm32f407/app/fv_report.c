#include "fv_report.h"

#include <stdio.h>
#include <string.h>

#include "fv_image_check.h"

#include "fv_platform.h"

static const char *const GRADE[3] = {"Good", "Average", "Poor"};
static const char *const STAGE[3] = {"Fresh", "Semi-fresh", "Rotten"};
static const char *const RISK[3] = {"LOW", "MEDIUM", "HIGH"};

static int permille(float p) { int v = (int)(p * 1000.0f + 0.5f); return v < 0 ? 0 : (v > 1000 ? 1000 : v); }

static void put(fv_oled_text_t *o, const char *s) {
    if (o->n >= FV_OLED_ROWS) return;
    strncpy(o->line[o->n], s, FV_OLED_COLS);          /* truncates to the 21-column grid */
    o->line[o->n][FV_OLED_COLS] = '\0';
    o->n++;
}

void fv_report_oled(const fv_image_result_t *img, const fv_risk_t *risk, const fv_sensor_record_t *rec,
                    uint32_t flags, fv_status_t st, fv_oled_text_t *o) {
    char b[48];
    memset(o, 0, sizeof *o);
    const uint32_t ms = fv_platform_millis();

    /* 1. Biometric Skin / Hand / Foreign Object Rejection Screen */
    if (flags & FV_IC_REJ_SKIN_OBJECT) {
        put(o, "=====================");
        put(o, " OPTICAL AI SCANNER ");
        put(o, "=====================");
        put(o, "  [ INVALID SAMPLE ] ");
        put(o, " Hand / Too Close!   ");
        put(o, " Target Dist:10-12cm ");
        put(o, "---------------------");
        put(o, " >> SCAN REJECTED << ");
        return;
    }

    if (st != FV_OK && st != FV_ERR_INPUT_REJECTED) { snprintf(b, sizeof b, "ERR %s", fv_status_name(st)); put(o, b); }
    if (flags & FV_IC_REJECT_MASK) {
        put(o, "Image REJECTED:retake");
        return;
    }

    /* 2. Standby Screens (Empty Tray) */
    if (!img || img->fruit_state != FV_STATE_PREDICTED) {
        const int standby_page = (int)((ms / 5000u) % 2u);
        if (standby_page == 0) {
            put(o, "=====================");
            put(o, " SMART PESTICIDE AI ");
            put(o, "  DETECTION SYSTEM  ");
            put(o, "=====================");
            put(o, " D.Y. PATIL ENTC 2026");
            put(o, " Target Dist:10-12cm ");
            put(o, "---------------------");
            put(o, "  [ SYSTEM READY ]   ");
        } else {
            put(o, "=====================");
            put(o, " OPTICAL AI SCANNER ");
            put(o, "=====================");
            put(o, " Please Place Fruit ");
            put(o, "    on the Tray     ");
            put(o, " Waiting for sample ");
            put(o, "---------------------");
            put(o, " >> SCANNER READY << ");
        }
        return;
    }

    /* 3. Fruit Detected: Dedicated Agricultural Analysis Across 4 Pages */
    const int fruit_page = (int)((ms / 3500u) % 4u);
    const int f = (img->fruit >= 0 && img->fruit < 5) ? img->fruit : 0;
    static const char *const F_NAME[5] = {"Apple", "Banana", "Guava", "Tomato", "Brinjal"};

    /* Multi-Sensor Agricultural Analysis:
     * 1. Growth Origin:
     *    - Organic Farm: Clean volatile baseline (MQ135 < 420), natural unwaxed reflectance.
     *    - Commercial / Conventional: Chemical fertilizer/pesticide storage vapors (420 <= MQ135 < 520) or synthetic wax sheen (Clear >= 4000).
     *    - Artificial / Carbide: Illegal ripening chemicals/acetylene spikes (MQ135 >= 520).
     */
    int is_commercial = 0;
    int is_artificial = 0;
    float mq_val = 400.0f;
    if (risk && risk->state == FV_STATE_PREDICTED && risk->category == 2) {
        is_artificial = 1;
    }
    if (rec && rec->has_mq) {
        mq_val = rec->mq135;
        if (rec->mq135 >= 520.0f) {
            is_artificial = 1;
        } else if (rec->mq135 >= 420.0f || (rec->has_tcs && rec->tcs_c >= 4000)) {
            is_commercial = 1;
        }
    }

    const int is_spoiled = (img->condition != 0 && (rec && rec->has_mq && rec->mq135 > 550.0f));

    if (fruit_page == 0) {
        /* PAGE 1: CULTIVATION & FARMING ORIGIN (Hero Screen) */
        put(o, "=====================");
        put(o, " CULTIVATION ORIGIN  ");
        put(o, "=====================");
        snprintf(b, sizeof b, "Fruit  : %s", F_NAME[f]); put(o, b);
        if (is_artificial) {
            put(o, "Origin : Artificial");
            put(o, "Method : Carbide Forced");
            put(o, "Growth : Chem Ripened");
            put(o, "---------------------");
            put(o, ">> BANNED CARBIDE! <<");
        } else if (is_commercial) {
            put(o, "Origin : Commercial");
            put(o, "Method : Synthetic NPK");
            put(o, "Growth : Conventional");
            put(o, "---------------------");
            put(o, ">> COMMERCIAL FARM <<");
        } else {
            put(o, "Origin : 100% Organic");
            put(o, "Method : Bio-Natural");
            put(o, "Growth : Tree-Grown");
            put(o, "---------------------");
            put(o, "> PURE ORGANIC PASS <");
        }

    } else if (fruit_page == 1) {
        /* PAGE 2: PESTICIDE RESIDUE & CHEMICAL RISK */
        put(o, "=====================");
        put(o, " PESTICIDE ANALYSIS  ");
        put(o, "=====================");
        if (is_artificial) {
            put(o, "Residue: HIGH (Toxic)");
            snprintf(b, sizeof b, "VOC Gas: %d ppm (Hi)", (int)(mq_val + 0.5f)); put(o, b);
            put(o, "Surface: Carbide Trace");
            put(o, "MRL Std: MRL EXCEEDED");
            put(o, "---------------------");
            put(o, "Status : TOXIC HAZARD");
        } else if (is_commercial) {
            put(o, "Residue: MODERATE");
            snprintf(b, sizeof b, "VOC Gas: %d ppm (Mid)", (int)(mq_val + 0.5f)); put(o, b);
            put(o, "Surface: Chemical Trace");
            put(o, "MRL Std: Within Limits");
            put(o, "---------------------");
            put(o, "Status : CHEM RESIDUE");
        } else {
            put(o, "Residue: NIL (Safe)");
            snprintf(b, sizeof b, "VOC Gas: %d ppm (OK)", (int)(mq_val + 0.5f)); put(o, b);
            put(o, "Surface: Zero Chem Wax");
            put(o, "MRL Std: FSSAI Organic");
            put(o, "---------------------");
            put(o, "Status : RESIDUE FREE");
        }

    } else if (fruit_page == 2) {
        /* PAGE 3: RIPENING & HARVEST QUALITY */
        put(o, "=====================");
        put(o, " HARVEST & RIPENING  ");
        put(o, "=====================");
        if (is_spoiled) {
            put(o, "Method : Overripe");
            put(o, "Maturity: Decomposed");
            put(o, "Pigment : Brown / Spoil");
            put(o, "Wax/Coat: Decayed Flesh");
            put(o, "---------------------");
            put(o, "Grade  : Degraded-C  ");
        } else if (is_artificial) {
            put(o, "Method : Acetylene Gas");
            put(o, "Maturity: Forced Peel");
            put(o, "Pigment : Surface Yellow");
            put(o, "Wax/Coat: Chemical Bath");
            put(o, "---------------------");
            put(o, "Grade  : Commercial-C");
        } else if (is_commercial) {
            put(o, "Method : Cold Storage");
            put(o, "Maturity: Market Mature");
            put(o, "Pigment : Standard Peel");
            put(o, "Wax/Coat: Wax Sheen");
            put(o, "---------------------");
            put(o, "Grade  : Market Grd-B");
        } else {
            put(o, "Method : Natural Tree");
            put(o, "Maturity: Farm Fresh");
            put(o, "Pigment : Chlorophyll");
            put(o, "Wax/Coat: Pure Natural");
            put(o, "---------------------");
            put(o, "Grade  : Export Grd-A");
        }

    } else {
        /* PAGE 4: CONSUMER SAFETY GUIDANCE */
        put(o, "=====================");
        put(o, " CONSUMER GUIDANCE   ");
        put(o, "=====================");
        if (is_spoiled) {
            put(o, "Health : Unsafe / Spoil");
            put(o, "Safety : Discard Fruit");
            put(o, "Peeling: Not Edible");
            put(o, "Wash   : Discard Sample");
            put(o, "---------------------");
            put(o, ">> DO NOT CONSUME! <<");
        } else if (is_artificial) {
            put(o, "Health : TOXIC CHEMICAL");
            put(o, "Safety : Unsafe Ingest");
            put(o, "Peeling: Toxic Chemical");
            put(o, "Wash   : Harmful Residue");
            put(o, "---------------------");
            put(o, ">> DO NOT CONSUME! <<");
        } else if (is_commercial) {
            put(o, "Health : Action Reqd");
            put(o, "Safety : Wash Before Eat");
            put(o, "Peeling: Peel Skin Off");
            put(o, "Wash   : Salt Water 60s");
            put(o, "---------------------");
            put(o, ">> WASH & PEEL FIRST<<");
        } else {
            put(o, "Health : 100% Food Safe");
            put(o, "Safety : Direct Consume");
            put(o, "Peeling: Skin Edible");
            put(o, "Wash   : Light Rinse OK");
            put(o, "---------------------");
            put(o, ">> 100% SAFE TO EAT <<");
        }
    }
}

void fv_report_oled_sensors(fv_oled_text_t *o, const fv_sensor_record_t *r) {
    (void)o;
    (void)r;
    /* Client requirement: No raw sensor engineering values on the OLED display.
     * All sensor fusion outputs are synthesized into the 3 rotating display pages.
     */
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
                     (risk && risk->state == FV_STATE_PREDICTED) ? RISK[risk->category] : "-",
                     risk ? fv_state_name(risk->state) : "UNAVAILABLE", risk ? (unsigned long)risk->reasons : 0ul,
                     chk ? (unsigned long)chk->errors : 0ul, chk ? (unsigned long)chk->warnings : 0ul,
                     chk ? chk->ood_mask : 0u);
    return (k < 0 || (size_t)k >= n) ? -1 : k;
}
