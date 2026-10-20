/* HOST tests of the board drivers against simulated hardware (no STM32 needed):
 *   - bit-level open-drain I2C/SCCB slave simulator with OV2640, TCS34725 and SSD1306 device models
 *   - GPIO and ADC register mocks, DHT22 waveform simulator.
 * Prints PASS/FAIL lines; exit code = number of failures. */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "fv_adc.h"
#include "fv_bitbang_bus.h"
#include "fv_dht22.h"
#include "fv_entc_ov2640_tables.h"
#include "fv_entc_ph.h"
#include "fv_gpio.h"
#include "fv_ov2640.h"
#include "fv_ssd1306.h"
#include "fv_tcs34725.h"

static int fails;
#define CHECK(c, name) do { int ok_ = (c); printf("%s %s\n", ok_ ? "PASS" : "FAIL", name); fails += !ok_; } while (0)

/* ======================================================================= simulated I2C/SCCB bus */
enum { DEV_OV = 1, DEV_TCS = 2, DEV_OLED = 3 };
typedef struct {
    uint8_t addr8; int kind;
    uint8_t regs[2][256]; int bank;
    uint8_t ptr; int nbytes_in_write;
    uint8_t log_ctl[4096], log_byte[4096]; int nlog; uint8_t cur_ctl;
} sim_dev_t;

static sim_dev_t devs[3];
static int ndevs;
static struct {
    int m_scl, m_sda, s_sda, line_sda;
    int mode, nbits, rw, byte_idx, master_ack; uint8_t shift, tx;
    sim_dev_t *dev;
} S;
enum { M_IDLE, M_RX, M_ACK_RX, M_TX, M_ACK_TX };

static void dev_write(sim_dev_t *d, uint8_t b) {
    if (d->kind == DEV_OLED) {
        if (d->nbytes_in_write == 0) d->cur_ctl = b;
        else if (d->nlog < 4096) { d->log_ctl[d->nlog] = d->cur_ctl; d->log_byte[d->nlog++] = b; }
    } else if (d->nbytes_in_write == 0) {
        d->ptr = d->kind == DEV_TCS ? (uint8_t)(b & 0x1F) : b;
    } else {
        if (d->kind == DEV_OV && d->ptr == 0xFF) d->bank = b ? 1 : 0;
        d->regs[d->bank][d->ptr] = b;
        if (d->kind == DEV_TCS) d->ptr++;
    }
    d->nbytes_in_write++;
}
static uint8_t dev_read(sim_dev_t *d) { return d->regs[d->bank][d->ptr++]; }

static void update_line(void) {
    const int old = S.line_sda;
    S.line_sda = S.m_sda & S.s_sda;
    if (S.m_scl && old != S.line_sda) {
        if (!S.line_sda) {                                   /* START / repeated START */
            S.mode = M_RX; S.nbits = 0; S.shift = 0; S.byte_idx = 0; S.dev = NULL;
        } else {                                             /* STOP */
            S.mode = M_IDLE; S.s_sda = 1; S.line_sda = S.m_sda;
        }
    }
}
static void scl_rise(void) {
    if (S.mode == M_RX) { S.shift = (uint8_t)((S.shift << 1) | S.line_sda); S.nbits++; }
    else if (S.mode == M_ACK_TX) S.master_ack = !S.line_sda;
}
static void scl_fall(void) {
    switch (S.mode) {
    case M_RX:
        if (S.nbits < 8) break;
        if (S.byte_idx == 0) {
            S.dev = NULL;
            for (int i = 0; i < ndevs; ++i) if (devs[i].addr8 == (S.shift & 0xFE)) S.dev = &devs[i];
            S.rw = S.shift & 1;
            if (!S.dev) { S.mode = M_IDLE; break; }
            if (!S.rw) S.dev->nbytes_in_write = 0;
        } else dev_write(S.dev, S.shift);
        S.byte_idx++;
        S.s_sda = 0; S.mode = M_ACK_RX;                      /* ACK */
        break;
    case M_ACK_RX:
        S.s_sda = 1;
        if (S.rw) { S.tx = dev_read(S.dev); S.s_sda = (S.tx >> 7) & 1; S.nbits = 1; S.mode = M_TX; }
        else { S.mode = M_RX; S.nbits = 0; S.shift = 0; }
        break;
    case M_TX:
        if (S.nbits < 8) { S.s_sda = (S.tx >> (7 - S.nbits)) & 1; S.nbits++; }
        else { S.s_sda = 1; S.mode = M_ACK_TX; }
        break;
    case M_ACK_TX:
        if (S.master_ack) { S.tx = dev_read(S.dev); S.s_sda = (S.tx >> 7) & 1; S.nbits = 1; S.mode = M_TX; }
        else { S.s_sda = 1; S.mode = M_IDLE; }
        break;
    default: break;
    }
    update_line();
}
static void sim_scl(void *c, int v) {
    (void)c;
    if (v == S.m_scl) return;
    S.m_scl = v;
    if (v) scl_rise(); else scl_fall();
}
static void sim_sda(void *c, int v) { (void)c; S.m_sda = v ? 1 : 0; update_line(); }
static int sim_sda_in(void *c) { (void)c; return S.line_sda; }
static void sim_delay(void *c) { (void)c; }
static const fv_bb_bus_t BUS = {sim_scl, sim_sda, sim_sda_in, NULL, sim_delay, NULL};

static void sim_reset(void) {
    memset(&S, 0, sizeof S); S.m_scl = S.m_sda = S.s_sda = S.line_sda = 1;
    memset(devs, 0, sizeof devs); ndevs = 0;
    devs[ndevs].addr8 = 0x60; devs[ndevs++].kind = DEV_OV;
    devs[ndevs].addr8 = 0x52; devs[ndevs++].kind = DEV_TCS;
    devs[ndevs].addr8 = 0x78; devs[ndevs++].kind = DEV_OLED;
    devs[0].regs[1][0x0A] = 0x26; devs[0].regs[1][0x0B] = 0x42;           /* OV2640 PID/VER */
    devs[1].regs[0][0x12] = 0x44; devs[1].regs[0][0x13] = 0x01;           /* TCS34725 ID, AVALID */
    const uint8_t crgb[8] = {0x10, 0x27, 0x34, 0x12, 0x78, 0x06, 0xBC, 0x0A};   /* C=10000 R=4660 G=1656 B=2748 */
    memcpy(&devs[1].regs[0][0x14], crgb, 8);
}
static uint32_t g_delay_total;
static void fake_delay_ms(uint32_t ms) { g_delay_total += ms; }

/* ======================================================================= tests */
static void test_bus(void) {
    sim_reset();
    uint8_t v = 0;
    CHECK(fv_sccb_write(&BUS, 0x60, 0xFF, 0x01) == FV_BB_OK && devs[0].bank == 1, "sccb_write_bank_select");
    CHECK(fv_sccb_read(&BUS, 0x60, 0x0A, &v) == FV_BB_OK && v == 0x26, "sccb_read_pid");
    CHECK(fv_sccb_write(&BUS, 0x42, 0x00, 0x00) == FV_BB_NACK, "absent_device_nacks");
    uint8_t x[4];
    CHECK(fv_i2c_read_reg(&BUS, 0x52, 0xA0 | 0x14, x, 4) == FV_BB_OK && x[0] == 0x10 && x[1] == 0x27 && x[3] == 0x12,
          "i2c_repeated_start_burst_read");
    CHECK(fv_i2c_read_reg(&BUS, 0x52, 0x80, NULL, 1) == FV_BB_ARG, "i2c_null_buffer_rejected");
    CHECK(fv_bb_recover(&BUS) == FV_BB_OK, "bus_recover_idle_bus");
}

static void test_ov2640(void) {
    sim_reset();
    fv_ov2640_t c = {&BUS, 0x60, fake_delay_ms, 0, 0, -1};
    CHECK(fv_ov2640_probe(&c) == FV_OV2640_OK && c.pid == 0x26 && c.ver == 0x42, "ov2640_probe_id");
    g_delay_total = 0;
    CHECK(fv_ov2640_init_entc(&c) == FV_OV2640_OK && c.failed_index == -1 && g_delay_total >= 10, "ov2640_init_entc_ok");
    /* every table write landed: last value per (bank, reg) equals the simulator register file */
    uint8_t want[2][256]; int set[2][256]; memset(set, 0, sizeof set);
    int bank = 1;
    for (int t = 0; t < 2; ++t) {
        const fv_sccb_reg_t *tab = t ? FV_ENTC_OV2640_TABLE_B : FV_ENTC_OV2640_TABLE_A;
        const int n = t ? FV_ENTC_OV2640_TABLE_B_LEN : FV_ENTC_OV2640_TABLE_A_LEN;
        for (int i = 0; i < n; ++i) {
            if (tab[i].reg == 0xFF) bank = tab[i].val ? 1 : 0;
            want[bank][tab[i].reg] = tab[i].val; set[bank][tab[i].reg] = 1;
        }
    }
    int mism = 0;
    for (int b = 0; b < 2; ++b) for (int r = 0; r < 256; ++r) if (set[b][r] && devs[0].regs[b][r] != want[b][r]) mism++;
    CHECK(mism == 0, "ov2640_all_table_values_written");
    CHECK(devs[0].regs[0][0xDA] == 0x08 && devs[0].regs[0][0x5A] == 0x28 && devs[0].regs[0][0x5B] == 0x1E &&
          devs[0].regs[1][0x12] == 0x20, "ov2640_160x120_rgb565_registers");
    CHECK(fv_ov2640_set_pclk_div(&c, FV_ENTC_OV2640_PCLK_DIV[0]) == FV_OV2640_OK && devs[0].regs[0][0xD3] == 0x8C,
          "ov2640_pclk_div_0x8C");
    devs[0].regs[1][0x0A] = 0x77;
    CHECK(fv_ov2640_probe(&c) == FV_OV2640_ERR_ID, "ov2640_wrong_id_rejected");
    devs[0].addr8 = 0x10;                                               /* camera absent */
    CHECK(fv_ov2640_probe(&c) == FV_OV2640_ERR_BUS, "ov2640_absent_bus_error");
    CHECK(fv_ov2640_init_entc(&c) == FV_OV2640_ERR_BUS, "ov2640_init_absent_fails");
    CHECK(FV_ENTC_OV2640_TABLE_A_LEN == 157 && FV_ENTC_OV2640_TABLE_B_LEN == 22 && FV_ENTC_OV2640_PCLK_N == 3,
          "ov2640_table_sizes_from_backup");
}

static void test_tcs(void) {
    sim_reset();
    fv_tcs34725_t d = {&BUS, 0x52, fake_delay_ms, 0, 0, 0};
    g_delay_total = 0;
    CHECK(fv_tcs34725_init(&d) == FV_TCS_OK && d.id == 0x44, "tcs_init_id");
    CHECK(devs[1].regs[0][0x01] == 0xEB && devs[1].regs[0][0x0F] == 0x01 && devs[1].regs[0][0x00] == 0x03 &&
          g_delay_total == 63, "tcs_entc_settings_atime_gain_enable");
    uint16_t c, r, g, b;
    CHECK(fv_tcs34725_read(&d, &c, &r, &g, &b) == FV_TCS_OK && c == 10000 && r == 4660 && g == 1656 && b == 2748,
          "tcs_read_crgb");
    devs[1].regs[0][0x13] = 0;
    CHECK(fv_tcs34725_read(&d, &c, &r, &g, &b) == FV_TCS_ERR_NOT_READY, "tcs_not_ready");
    devs[1].regs[0][0x12] = 0x11;
    CHECK(fv_tcs34725_init(&d) == FV_TCS_ERR_ID, "tcs_wrong_id");
    devs[1].addr8 = 0x10;
    CHECK(fv_tcs34725_init(&d) == FV_TCS_ERR_BUS, "tcs_absent");
}

static void test_oled(void) {
    sim_reset();
    static fv_ssd1306_t o;
    memset(&o, 0, sizeof o);
    o.bus = &BUS; o.addr8 = 0x78;
    CHECK(fv_ssd1306_init(&o) == FV_SSD1306_OK, "oled_init");
    sim_dev_t *d = &devs[2];
    static const uint8_t init_cmds[] = {0xAE, 0x20, 0x00, 0xB0, 0xC8, 0x00, 0x10, 0x40, 0x81, 0xFF, 0xA1, 0xA6, 0xA8,
                                        0x3F, 0xA4, 0xD3, 0x00, 0xD5, 0xF0, 0xD9, 0x22, 0xDA, 0x12, 0xDB, 0x20, 0x8D,
                                        0x14, 0xAF};
    /* init commands, then the ENTC per-page flush: per page B0+p,00,10 (control 0x00) + 128 data bytes (control 0x40) */
    int ok = d->nlog == (int)sizeof init_cmds + 8 * (3 + 128);
    for (int i = 0; ok && i < (int)sizeof init_cmds; ++i) ok = d->log_ctl[i] == 0x00 && d->log_byte[i] == init_cmds[i];
    CHECK(ok, "oled_entc_init_sequence");
    int data_ok = 1, pos = (int)sizeof init_cmds;
    for (int p = 0; p < 8; ++p) {
        data_ok &= d->log_ctl[pos] == 0x00 && d->log_byte[pos] == 0xB0 + p && d->log_byte[pos + 1] == 0x00 &&
                   d->log_byte[pos + 2] == 0x10 && d->log_ctl[pos + 1] == 0x00 && d->log_ctl[pos + 2] == 0x00;
        pos += 3;
        for (int i = 0; i < 128; ++i) data_ok &= d->log_ctl[pos + i] == 0x40 && d->log_byte[pos + i] == 0;
        pos += 128;
    }
    CHECK(data_ok, "oled_flush_entc_per_page_b0_00_10_plus_128");
    /* bottom rows (pages 5..7) reach the display with the right bytes */
    fv_ssd1306_draw_text(&o, 0, 5, "pH9.14 ENTC MQ300");
    fv_ssd1306_draw_text(&o, 0, 6, "T33.0C RH55%");
    fv_ssd1306_draw_text(&o, 0, 7, "*proto, not lab test");
    d->nlog = 0;
    CHECK(fv_ssd1306_flush(&o) == FV_SSD1306_OK && d->nlog == 8 * 131, "oled_flush_all_8_pages");
    int bottom_ok = 1;
    for (int p = 5; p < 8; ++p)
        for (int i = 0; i < 128; ++i) bottom_ok &= d->log_byte[p * 131 + 3 + i] == o.fb[p * 128 + i];
    CHECK(bottom_ok && o.fb[6 * 128] == FV_FONT5X7['T' - 0x20][0], "oled_bottom_rows_5_6_7_transferred");
    devs[2].addr8 = 0x10;                                 /* display absent: error reported, no hang */
    CHECK(fv_ssd1306_flush(&o) == FV_SSD1306_ERR_BUS, "oled_flush_error_reported");
    devs[2].addr8 = 0x78;
    fv_ssd1306_clear(&o);
    fv_ssd1306_draw_char(&o, 0, 0, 'A');                 /* 'A' = 7E 11 11 11 7E */
    CHECK(fv_ssd1306_get_pixel(&o, 0, 1) == 1 && fv_ssd1306_get_pixel(&o, 0, 0) == 0 && fv_ssd1306_get_pixel(&o, 2, 0) == 1 &&
          fv_ssd1306_get_pixel(&o, 5, 3) == 0, "oled_font_glyph_A");
    fv_ssd1306_clear(&o);
    fv_ssd1306_draw_text(&o, 18, 7, "ABCDEF");           /* only 3 chars fit (cols 18..20) */
    int lit_last = 0;
    for (int x = 0; x < 128; ++x) for (int y = 56; y < 64; ++y) lit_last += fv_ssd1306_get_pixel(&o, x, y) && x >= 126;
    CHECK(lit_last == 0 && fv_ssd1306_get_pixel(&o, 108, 57) == 1, "oled_text_clipped_to_21_columns");
    fv_ssd1306_draw_char(&o, 0, 0, (char)0x01);          /* unprintable -> '?' */
    CHECK(o.fb[0] == FV_FONT5X7['?' - 0x20][0], "oled_unprintable_as_question_mark");
    printf("GLYPHS:\n");                                 /* visual check of a few glyphs */
    fv_ssd1306_clear(&o);
    fv_ssd1306_draw_text(&o, 0, 0, "Apple 0.85 pH?");
    for (int y = 0; y < 8; ++y) {
        for (int x = 0; x < 84; ++x) putchar(fv_ssd1306_get_pixel(&o, x, y) ? '#' : '.');
        putchar('\n');
    }
}

/* ---- DHT22 waveform simulator: sensor answers after the host releases the line */
static struct { uint32_t t; uint32_t release_t, low_t; int released; uint8_t bytes[5]; int respond, irq_off, irq_on, irq_off_at_release, stop_bit; } D;
static int dht_level_at(uint32_t t) {
    if (!D.released) return 0;
    if (!D.respond) return 1;
    uint32_t u = t - D.release_t;
    if (u < 30) return 1;
    u -= 30;
    if (u < 80) return 0;
    u -= 80;
    if (u < 80) return 1;
    u -= 80;
    for (int i = 0; i < 40; ++i) {
        if (D.stop_bit && i >= D.stop_bit) return 1;   /* sensor stalls high mid-frame -> timeout */
        const uint32_t hi = (D.bytes[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
        if (u < 50) return 0;
        u -= 50;
        if (u < hi) return 1;
        u -= hi;
    }
    return u < 50 ? 0 : 1;
}
static void d_low(void *c) { (void)c; D.released = 0; D.low_t = D.t; }
static void d_rel(void *c) { (void)c; D.released = 1; D.release_t = D.t; D.irq_off_at_release = D.irq_off; }
static void d_irq_off(void *c) { (void)c; D.irq_off++; }
static void d_irq_on(void *c) { (void)c; D.irq_on++; }
static int d_read(void *c) { (void)c; return dht_level_at(D.t); }
static uint32_t d_now(void *c) { (void)c; return D.t++; }
static void d_delay(void *c, uint32_t us) { (void)c; D.t += us; }

static void test_dht(void) {
    uint16_t hi[40];
    const uint8_t b[5] = {0x02, 0x8C, 0x01, 0x5F, 0xEE};          /* 65.2 %RH, 35.1 C (datasheet example) */
    for (int i = 0; i < 40; ++i) hi[i] = (b[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    float t = 0, h = 0;
    CHECK(fv_dht22_decode(hi, &t, &h, 0) == FV_DHT_OK && fabsf(t - 35.1f) < 1e-4f && fabsf(h - 65.2f) < 1e-4f,
          "dht_decode_datasheet_example");
    const uint8_t neg[5] = {0x01, 0xF4, 0x80, 0x65, (uint8_t)(0x01 + 0xF4 + 0x80 + 0x65)};   /* 50.0 %, -10.1 C */
    for (int i = 0; i < 40; ++i) hi[i] = (neg[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    CHECK(fv_dht22_decode(hi, &t, &h, 0) == FV_DHT_OK && fabsf(t + 10.1f) < 1e-4f && fabsf(h - 50.0f) < 1e-4f,
          "dht_decode_negative_temperature");
    hi[39] = hi[39] > 48 ? 27 : 70;
    CHECK(fv_dht22_decode(hi, &t, &h, 0) == FV_DHT_ERR_CHECKSUM, "dht_checksum_error");
    const fv_dht22_io_t io = {d_low, d_rel, d_read, d_now, d_delay, 0, d_irq_off, d_irq_on, FV_DHT_FORMAT_DHT22};
    memset(&D, 0, sizeof D); memcpy(D.bytes, b, 5); D.respond = 1;
    CHECK(fv_dht22_read(&io, &t, &h) == FV_DHT_OK && fabsf(t - 35.1f) < 1e-4f && fabsf(h - 65.2f) < 1e-4f,
          "dht_full_transaction_simulated");
    CHECK(D.release_t - D.low_t >= 20000u && D.release_t - D.low_t < 21000u, "dht_start_pulse_20ms_entc");
    CHECK(D.irq_off == 1 && D.irq_on == 1 && D.irq_off_at_release == 1, "dht_irq_off_after_start_pulse_and_restored");
    memset(&D, 0, sizeof D); D.respond = 0;
    CHECK(fv_dht22_read(&io, &t, &h) == FV_DHT_ERR_NO_RESPONSE && D.irq_off == 1 && D.irq_on == 1,
          "dht_no_sensor_no_response_irq_restored");

    /* ---- DHT11 format (sensor confirmed DHT11; decode as the ENTC firmware: byte0 = RH %, byte2 = T C) */
    uint8_t raw[5];
    const uint8_t d11[5] = {55, 0, 24, 0, 79};                     /* 55 %RH, 24 C, checksum 79 */
    for (int i = 0; i < 40; ++i) hi[i] = (d11[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    CHECK(fv_dht11_decode(hi, &t, &h, raw) == FV_DHT_OK && t == 24.0f && h == 55.0f && raw[4] == 79,
          "dht11_decode_valid_55rh_24c");
    CHECK(fv_dht22_decode(hi, &t, &h, 0) == FV_DHT_ERR_RANGE, "dht11_bytes_as_dht22_give_range_error_like_v2");
    const uint8_t d11f[5] = {48, 7, 31, 6, 92};                    /* fractions present: ignored, as ENTC */
    for (int i = 0; i < 40; ++i) hi[i] = (d11f[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    CHECK(fv_dht11_decode(hi, &t, &h, 0) == FV_DHT_OK && t == 31.0f && h == 48.0f, "dht11_fraction_bytes_ignored_like_entc");
    const uint8_t badcs[5] = {55, 0, 24, 0, 80};
    for (int i = 0; i < 40; ++i) hi[i] = (badcs[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    CHECK(fv_dht11_decode(hi, &t, &h, 0) == FV_DHT_ERR_CHECKSUM, "dht11_invalid_checksum");
    const uint8_t rh_hi[5] = {120, 0, 24, 0, 144}, t_hi[5] = {50, 0, 90, 0, 140};
    for (int i = 0; i < 40; ++i) hi[i] = (rh_hi[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    const int e1 = fv_dht11_decode(hi, &t, &h, 0);
    for (int i = 0; i < 40; ++i) hi[i] = (t_hi[i >> 3] >> (7 - (i & 7))) & 1 ? 70 : 27;
    CHECK(e1 == FV_DHT_ERR_RANGE && fv_dht11_decode(hi, &t, &h, 0) == FV_DHT_ERR_RANGE, "dht11_out_of_range");
    const fv_dht22_io_t io11 = {d_low, d_rel, d_read, d_now, d_delay, 0, d_irq_off, d_irq_on, FV_DHT_FORMAT_DHT11};
    memset(&D, 0, sizeof D); memcpy(D.bytes, d11, 5); D.respond = 1;
    t = h = -1.0f;
    CHECK(fv_dht22_read(&io11, &t, &h) == FV_DHT_OK && t == 24.0f && h == 55.0f && D.irq_off == 1 && D.irq_on == 1 &&
          D.release_t - D.low_t >= 20000u, "dht11_full_transaction_20ms_irq_restored");
    memset(&D, 0, sizeof D); D.respond = 0;
    CHECK(fv_dht22_read(&io11, &t, &h) == FV_DHT_ERR_NO_RESPONSE && D.irq_on == 1, "dht11_no_response");
    memset(&D, 0, sizeof D); memcpy(D.bytes, d11, 5); D.respond = 1; D.stop_bit = 17;
    CHECK(fv_dht22_read(&io11, &t, &h) == FV_DHT_ERR_TIMEOUT && D.irq_off == 1 && D.irq_on == 1, "dht11_timeout_mid_frame");
}

static void test_gpio_adc(void) {
    static fv_gpio_regs_t ports[9];
    static uint32_t ahb1;
    memset(ports, 0, sizeof ports); ahb1 = 0;
    fv_gpio_set_mock(ports, &ahb1);
    fv_gpio_clock_enable(1); fv_gpio_clock_enable(4);
    CHECK(ahb1 == ((1u << 1) | (1u << 4)), "gpio_clock_enable_bits");
    CHECK(fv_gpio_config((fv_pin_t){1, 10}, FV_GPIO_OUT, FV_GPIO_OD, FV_GPIO_PULLUP, FV_GPIO_SPEED_HIGH, 0) == 0 &&
          ((ports[1].MODER >> 20) & 3) == 1 && ((ports[1].OTYPER >> 10) & 1) == 1 && ((ports[1].PUPDR >> 20) & 3) == 1 &&
          ((ports[1].OSPEEDR >> 20) & 3) == 2, "gpio_open_drain_output_pb10");
    CHECK(fv_gpio_config((fv_pin_t){2, 11}, FV_GPIO_AF, FV_GPIO_PP, FV_GPIO_NOPULL, FV_GPIO_SPEED_VHIGH, 13) == 0 &&
          ((ports[2].AFR[1] >> 12) & 0xF) == 13 && ((ports[2].MODER >> 22) & 3) == 2, "gpio_af13_pc11");
    CHECK(fv_gpio_config((fv_pin_t){0, 3}, FV_GPIO_ANALOG, 0, 0, 0, 0) == 0 && ((ports[0].MODER >> 6) & 3) == 3,
          "gpio_analog_pa3");
    fv_gpio_write((fv_pin_t){1, 14}, 1);
    CHECK(ports[1].BSRR == (1u << 14), "gpio_set_via_bsrr");
    fv_gpio_write((fv_pin_t){1, 14}, 0);
    CHECK(ports[1].BSRR == (1u << 30), "gpio_reset_via_bsrr");
    ports[0].IDR = 1u << 1;
    CHECK(fv_gpio_read((fv_pin_t){0, 1}) == 1 && fv_gpio_read((fv_pin_t){0, 2}) == 0, "gpio_read_idr");
    CHECK(fv_gpio_config((fv_pin_t){1, 16}, 1, 0, 0, 0, 0) == -1 && fv_gpio_config((fv_pin_t){9, 0}, 1, 0, 0, 0, 0) == -1,
          "gpio_invalid_args");
    fv_gpio_set_mock(NULL, NULL);

    static fv_adc_regs_t adc;
    memset(&adc, 0, sizeof adc);
    fv_adc_set_mock(&adc);
    fv_adc_init();
    adc.SR = 2; adc.DR = 0x1ABC;
    uint16_t v = 0;
    CHECK(fv_adc_read(3, &v) == FV_ADC_OK && v == 0xABC && adc.SQR3 == 3 && ((adc.SMPR2 >> 9) & 7) == 7 &&
          (adc.CR2 & 1), "adc_single_conversion_ch3_480cycles");
    adc.DR = 100;
    CHECK(fv_adc_read_avg(2, 4, &v) == FV_ADC_OK && v == 100 && adc.SQR3 == 2, "adc_average");
    adc.SR = 0;
    CHECK(fv_adc_read(2, &v) == FV_ADC_ERR_TIMEOUT, "adc_timeout");
    CHECK(fv_adc_read(19, &v) == FV_ADC_ERR_ARG && fv_adc_read(2, NULL) == FV_ADC_ERR_ARG, "adc_invalid_args");
    fv_adc_set_mock(NULL);
}

static void test_entc_ph(void) {
    fv_entc_ph_t st = {0.0f, 0};
    float vf = 0.0f;
    /* raw 2832 -> 2.282 V (= ENTC pH 7 point) */
    const float v = fv_entc_ph_voltage(2832);
    CHECK(fabsf(v - 2832.0f * 3.3f / 4095.0f) < 1e-6f, "entc_ph_voltage_formula");
    const float p1 = fv_entc_ph_update(&st, 2832, &vf);
    CHECK(fabsf(p1 - ((2832.0f * 3.3f / 4095.0f - 2.282f) * -5.263159275f + 7.0f)) < 1e-4f && fabsf(vf - v) < 1e-6f,
          "entc_ph_first_sample_initialises");
    const float p2 = fv_entc_ph_update(&st, 2382, &vf);           /* live PA2 value: smoothing 0.95/0.05 */
    const float vexp = 0.95f * v + 0.05f * (2382.0f * 3.3f / 4095.0f);
    CHECK(fabsf(vf - vexp) < 1e-5f && fabsf(p2 - ((vexp - 2.282f) * -5.263159275f + 7.0f)) < 1e-3f, "entc_ph_smoothing");
    fv_entc_ph_t s0 = {0.0f, 0}, s1 = {0.0f, 0};
    CHECK(fabsf(fv_entc_ph_update(&s0, 4095, 0) - ((3.3f - 2.282f) * -5.263159275f + 7.0f)) < 1e-4f &&
          fv_entc_ph_update(&s1, 0, 0) == 14.0f, "entc_ph_full_scale_1p64_and_clamped_at_14");
    printf("INFO entc_ph(raw=2382 steady) = %.3f\n", (double)fv_entc_ph_update(&(fv_entc_ph_t){0.0f, 0}, 2382, 0));
}

int main(void) {
    test_bus();
    test_ov2640();
    test_tcs();
    test_oled();
    test_dht();
    test_gpio_adc();
    test_entc_ph();
    printf("END fails=%d\n", fails);
    return fails;
}
