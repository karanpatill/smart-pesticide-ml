/* Text output for the SSD1306 OLED (fixed 21x8 character grid, 6x8 font on 128x64) and a
 * one-line serial diagnostic record. Display-driver independent; no float printf (keeps
 * newlib-nano's float formatting out of flash). Tested in tests/test_fw_report.py. */
#ifndef FV_REPORT_H
#define FV_REPORT_H

#include "fv_result.h"
#include "fv_sensor.h"

#define FV_OLED_COLS 21
#define FV_OLED_ROWS 8

typedef struct {
    char line[FV_OLED_ROWS][FV_OLED_COLS + 1];
    int n;
} fv_oled_text_t;

/* image_flags: fv_image_check() flags (0 if no image); status: last pipeline status. */
void fv_report_oled(const fv_image_result_t *img, const fv_risk_t *risk, const fv_sensor_record_t *rec,
                    uint32_t image_flags, fv_status_t status, fv_oled_text_t *out);

/* Adds up to two sensor rows ("pH<x.xx> ENTC MQ<raw>[w]" and "T<t>C RH<h>%") into FREE rows only.
 * Does nothing if no row is free.
 * pH is shown with the ENTC calibration label; 'w' marks MQ135 still in its 120 s warm-up; "--" = no reading. */
void fv_report_oled_sensors(fv_oled_text_t *out, const fv_sensor_record_t *rec);

/* Writes "FV1,..."+CRLF into buf. Returns length, or -1 if buf is too small (nothing partial is
 * reported as success). */
int fv_report_serial(const fv_image_result_t *img, const fv_risk_t *risk, const fv_sensor_check_t *chk,
                     uint32_t image_flags, fv_status_t status, char *buf, size_t n);

#endif
