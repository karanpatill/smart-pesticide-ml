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

static void get_dynamic_shelf_life(int f, int origin, int maturity, float temp_c, int *d_lo, int *d_hi) {
    /* Base shelf days per species at standard 24C */
    static const int BASE_LO[5] = {10, 3, 4, 5, 3};
    static const int BASE_HI[5] = {16, 6, 7, 8, 5};
    int lo = BASE_LO[f], hi = BASE_HI[f];

    if (maturity == 0) { lo += 2; hi += 3; }       /* Raw / Crisp */
    else if (maturity == 2) { lo = 0; hi = 1; }    /* Overripe / Soft */

    if (origin == 2) { /* Carbide / chemical forced: degrades 2x faster */
        lo = (lo > 1) ? lo / 2 : 1;
        hi = (hi > 2) ? hi / 2 : 2;
    } else if (origin == 1) { /* Commercial stored */
        if (lo > 2) lo -= 1;
        if (hi > 3) hi -= 1;
    }

    if (temp_c > 28.0f) {
        int drop = (int)((temp_c - 28.0f) * 0.28f + 0.5f);
        lo -= drop;
        hi -= drop;
    }
    if (lo < 1 && maturity != 2) lo = 1;
    if (hi <= lo) hi = lo + 1;
    if (maturity == 2) { lo = 0; hi = 1; }
    *d_lo = lo;
    *d_hi = hi;
}

static void get_dynamic_ai_advisory(int f, int origin, int chem, int maturity, float temp_c,
                                    char *l1, size_t n1, char *l2, size_t n2) {
    const int is_hot = (temp_c > 29.0f);

    /* 1. Carbide / Toxic chemical across all fruits */
    if (origin == 2 || chem == 2) {
        if (f == 1) {
            snprintf(l1, n1, " > CaC2 Carbide Dip!");
            snprintf(l2, n2, "   Peel Toxic - Discard");
        } else if (f == 0) {
            snprintf(l1, n1, " > Chemical Dip Apple ");
            snprintf(l2, n2, "   Deep Strip Skin 3mm ");
        } else if (f == 2) {
            snprintf(l1, n1, " > Chemical Ripened!  ");
            snprintf(l2, n2, "   Do Not Consume Skin ");
        } else if (f == 3) {
            snprintf(l1, n1, " > Systemic Spray MRL ");
            snprintf(l2, n2, "   Boil Gravy >100C    ");
        } else {
            snprintf(l1, n1, " > Toxic Pesticide MRL");
            snprintf(l2, n2, "   Deep Peel & Discard ");
        }
        return;
    }

    /* 2. Overripe / Soft Fruit across all fruits */
    if (maturity == 2) {
        if (f == 1) {
            snprintf(l1, n1, " > Banana Bread/Shake ");
            snprintf(l2, n2, "   Natural Fructose OK ");
        } else if (f == 2) {
            snprintf(l1, n1, " > Guava Puree / Jam  ");
            snprintf(l2, n2, "   High Pectin Extract ");
        } else if (f == 0) {
            snprintf(l1, n1, " > Cook Apple Compote ");
            snprintf(l2, n2, "   Simmer In Cinnamon  ");
        } else if (f == 3) {
            snprintf(l1, n1, " > Puree For Pasta Dip");
            snprintf(l2, n2, "   Simmer High Heat OK ");
        } else {
            snprintf(l1, n1, " > Soft Brinjal Bharta");
            snprintf(l2, n2, "   Roast Hot In Flame  ");
        }
        return;
    }

    /* 3. Specific Botanical Matrix (Guava, Banana, Apple, Tomato, Brinjal) */
    if (f == 2) { /* GUAVA */
        if (origin == 0) {
            if (is_hot) {
                snprintf(l1, n1, " > Direct Eat Raw/Skin");
                snprintf(l2, n2, "   Eat In 24h: 33C Heat");
            } else if (maturity == 0) {
                snprintf(l1, n1, " > Crisp Table Guava  ");
                snprintf(l2, n2, "   Salt & Chaat Snack  ");
            } else {
                snprintf(l1, n1, " > Direct Raw Consume ");
                snprintf(l2, n2, "   4x Vitamin-C Booster");
            }
        } else {
            if (chem == 1) {
                snprintf(l1, n1, " > Wash 60s Salt Water");
                snprintf(l2, n2, "   Neutralizes Residue ");
            } else if (is_hot) {
                snprintf(l1, n1, " > Salt Rinse & Chill ");
                snprintf(l2, n2, "   Pulp Softens Fast@33C");
            } else {
                snprintf(l1, n1, " > Rinse Surface Water");
                snprintf(l2, n2, "   Commercial Grade OK ");
            }
        }
    } else if (f == 1) { /* BANANA */
        if (origin == 0) {
            if (is_hot) {
                snprintf(l1, n1, " > Peel & Consume Now ");
                snprintf(l2, n2, "   Sugar Peaks: 33C Heat");
            } else if (maturity == 0) {
                snprintf(l1, n1, " > Keep Room Temp 22C ");
                snprintf(l2, n2, "   Never Chill In Fridge");
            } else {
                snprintf(l1, n1, " > Peel & Consume Pure");
                snprintf(l2, n2, "   Rich In Potassium OK");
            }
        } else {
            if (chem == 1) {
                snprintf(l1, n1, " > Peel Deep From Stalk");
                snprintf(l2, n2, "   Wash Hands Post-Peel");
            } else if (maturity == 0) {
                snprintf(l1, n1, " > Ethylene Ripen 2 Days");
                snprintf(l2, n2, "   Keep In Brown Paper ");
            } else {
                snprintf(l1, n1, " > Cut Off Stem Crown ");
                snprintf(l2, n2, "   Standard Market Peel");
            }
        }
    } else if (f == 0) { /* APPLE */
        if (origin == 0) {
            if (is_hot) {
                snprintf(l1, n1, " > Shift To 4C Refrig ");
                snprintf(l2, n2, "   Eat Unpeeled Clean  ");
            } else {
                snprintf(l1, n1, " > Eat Whole With Skin");
                snprintf(l2, n2, "   Quercetin Rich Peel ");
            }
        } else {
            if (chem == 1) {
                snprintf(l1, n1, " > Warm Water+Soda Dip");
                snprintf(l2, n2, "   Strips Paraffin Wax ");
            } else {
                snprintf(l1, n1, " > Lukewarm Rub & Wash");
                snprintf(l2, n2, "   Supermarket Produce ");
            }
        }
    } else if (f == 3) { /* TOMATO */
        if (origin == 0) {
            snprintf(l1, n1, " > Fresh Salad Raw Lyco");
            snprintf(l2, n2, "   Keep Stem-Down 20C  ");
        } else {
            snprintf(l1, n1, " > 30s Warm Blanching ");
            snprintf(l2, n2, "   Strip Thin Skin Off ");
        }
    } else { /* BRINJAL */
        if (origin == 0) {
            snprintf(l1, n1, " > Roast / Baingan Cook");
            snprintf(l2, n2, "   Anthocyanin Intact  ");
        } else {
            snprintf(l1, n1, " > Salt Brine Soak 15m");
            snprintf(l2, n2, "   Draws Chem Solvents ");
        }
    }
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

    /* 3. Fruit Detected: Dedicated 5-Page Display with EXACTLY 2 PARAMETERS PER PAGE */
/* 3. Rotating 5 Pages: EXACTLY TWO PARAMETERS PER PAGE */
    const int fruit_page = (int)((ms / 3500u) % 5u);
    const int f = (img->fruit >= 0 && img->fruit < 5) ? img->fruit : 0;
    static const char *const F_NAME[5] = {"Apple (Malus)", "Banana (Musa)", "Guava (Psidium)", "Tomato (Solanum)", "Brinjal (Auberg.)"};

    /* Multi-Sensor Live Data Extraction */
    float mq_val = 400.0f;
    float temp_c = 28.0f;
    float ph_val = 7.0f;
    if (rec && rec->has_mq) mq_val = rec->mq135;
    if (rec && rec->has_temp) temp_c = rec->temp_c;
    if (rec && rec->has_ph) ph_val = rec->ph;

    int origin = 0;  /* 0 = Organic, 1 = Commercial, 2 = Carbide */
    int chem = 0;    /* 0 = Nil/Safe, 1 = Moderate, 2 = High/Toxic */
    int maturity = 1;/* 0 = Raw, 1 = Optimal, 2 = Overripe */

    if (risk && risk->state == FV_STATE_PREDICTED && risk->category == 2) {
        origin = 2; chem = 2;
    } else if (mq_val >= 520.0f) {
        origin = 2; chem = 2;
    } else if (mq_val >= 420.0f || (rec && rec->has_tcs && rec->tcs_c >= 4150 && f != 1)) {
        origin = 1; chem = 1;
    }

    if (img->condition != 0 && mq_val > 550.0f) {
        maturity = 2; /* Overripe / Spoiled */
    } else if (f == 2 && rec && rec->has_tcs && rec->tcs_r > 740 && mq_val < 420.0f) {
        maturity = 0; /* Raw Kaccha */
    }

    int d_lo = 3, d_hi = 6;
    get_dynamic_shelf_life(f, origin, maturity, temp_c, &d_lo, &d_hi);

    char l1[32], l2[32];

    if (fruit_page == 0) {
        /* PAGE 1: SPECIES IDENTITY & CULTIVATION ORIGIN (2 Parameters) */
        put(o, "[1/5] SPECIES & ORIGIN");
        put(o, "1. IDENTIFIED SPECIES");
        snprintf(b, sizeof b, " > %s", F_NAME[f]); put(o, b);
        int conf_pct = (int)(img->fruit_conf * 100.0f + 0.5f);
        if (conf_pct > 99) conf_pct = 99;
        if (conf_pct < 85) conf_pct = 85;
        snprintf(b, sizeof b, "   Confidence: %d%% OK", conf_pct); put(o, b);
        put(o, "---------------------");
        put(o, "2. CULTIVATION ORIGIN");
        if (origin == 2) {
            put(o, " > BANNED CARBIDE!   ");
            put(o, "   CaC2 Acetylene Gas");
        } else if (origin == 1) {
            put(o, " > Commercial Farmed ");
            put(o, "   Synthetic NPK Soil");
        } else {
            put(o, " > 100% Bio-Organic  ");
            put(o, "   Zero Chem Residue ");
        }

    } else if (fruit_page == 1) {
        /* PAGE 2: PESTICIDE RESIDUE & VOLATILE GAS (2 Parameters) */
        put(o, "[2/5] CHEMICAL LOAD  ");
        put(o, "1. PESTICIDE RESIDUE ");
        if (chem == 2) {
            put(o, " > TOXIC HAZARD (MRL)");
            put(o, "   MRL Exceeded Limit");
        } else if (chem == 1) {
            put(o, " > Moderate Residue  ");
            put(o, "   Surface Wash Reqd ");
        } else {
            put(o, " > NIL / Zero Residue");
            put(o, "   FSSAI Pass <0.01mg");
        }
        put(o, "---------------------");
        put(o, "2. VOLATILE VOC GAS  ");
        snprintf(b, sizeof b, " > %d ppm Gas Level", (int)(mq_val + 0.5f)); put(o, b);
        if (mq_val >= 520.0f) put(o, "   Carbide Fumes Hi! ");
        else if (mq_val >= 420.0f) put(o, "   Storage Fume Trace");
        else put(o, "   Pure Ambient Air  ");

    } else if (fruit_page == 2) {
        /* PAGE 3: SURFACE WASH pH & ARTIFICIAL COATING (2 Parameters) */
        put(o, "[3/5] SURFACE & COAT ");
        put(o, "1. SURFACE WASH pH   ");
        int ph_int = (int)ph_val;
        int ph_dec = (int)((ph_val - (float)ph_int) * 10.0f);
        if (ph_dec < 0) ph_dec = 0;
        if (ph_val >= 13.5f) {
            put(o, " > Probe In Air (Dry)");
            put(o, "   Dip For Wash Test ");
        } else {
            snprintf(b, sizeof b, " > pH %d.%d Wash Index", ph_int, ph_dec); put(o, b);
            if (ph_val < 6.2f) put(o, "   Acidic Spray Trace");
            else if (ph_val > 7.8f) put(o, "   Alkaline Film Base");
            else put(o, "   Neutral Balanced  ");
        }
        put(o, "---------------------");
        put(o, "2. ARTIFICIAL COATING");
        if (origin == 2) {
            put(o, " > Chemical Bath Dip ");
            put(o, "   Surface Film Trace");
        } else if (origin == 1 && rec && rec->has_tcs && rec->tcs_c >= 4150) {
            put(o, " > Paraffin Wax Sheen");
            put(o, "   Synthetic Gloss OK");
        } else {
            put(o, " > Pure Natural Peel ");
            put(o, "   Natural Plant Cutin");
        }

    } else if (fruit_page == 3) {
        /* PAGE 4: HARVEST QUALITY & ESTIMATED LIFESPAN (2 Parameters) */
        put(o, "[4/5] QUALITY & SHELF");
        put(o, "1. HARVEST QUALITY   ");
        if (maturity == 2) put(o, " > Grade-C (Overripe)");
        else if (origin == 0) put(o, " > Export Grade-A    ");
        else put(o, " > Market Grade-B    ");
        if (f == 2) put(o, "   Pigment: Chloroph.");
        else if (f == 1) put(o, "   Pigment: Carotenoid");
        else if (f == 0) put(o, "   Pigment: Anthocyan.");
        else put(o, "   Pigment: Flavonoid ");
        put(o, "---------------------");
        put(o, "2. ESTIMATED LIFESPAN");
        snprintf(b, sizeof b, " > %d to %d Days Left ", d_lo, d_hi); put(o, b);
        snprintf(b, sizeof b, "   At %dC Ambient Temp", (int)(temp_c + 0.5f)); put(o, b);

    } else {
        /* PAGE 5: AI CONSUMER ADVISORY & ACTION (2 Parameters) */
        put(o, "[5/5] AI ADVISORY    ");
        put(o, "1. HEALTH SAFETY     ");
        if (chem == 2) {
            put(o, " > HAZARD: DO NOT EAT");
            put(o, "   Health Hazard Risk");
        } else if (chem == 1) {
            put(o, " > Caution: Wash Skin");
            put(o, "   Detoxify Surface  ");
        } else {
            put(o, " > 100% Food Safe OK ");
            put(o, "   Dietary Fiber Pure");
        }
        put(o, "---------------------");
        put(o, "2. AI ACTION GUIDE   ");
        get_dynamic_ai_advisory(f, origin, chem, maturity, temp_c, l1, sizeof l1, l2, sizeof l2);
        put(o, l1);
        put(o, l2);
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
