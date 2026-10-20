#include "fv_dht22.h"

#define BIT_THRESHOLD_US 48u   /* '0' ~26-28 us, '1' ~70 us */

int fv_dht22_decode(const uint16_t high_us[40], float *temp_c, float *rh_pct, uint8_t raw[5]) {
    if (!high_us || !temp_c || !rh_pct) return FV_DHT_ERR_ARG;
    uint8_t b[5] = {0, 0, 0, 0, 0};
    for (int i = 0; i < 40; ++i) b[i >> 3] = (uint8_t)((b[i >> 3] << 1) | (high_us[i] > BIT_THRESHOLD_US));
    if (raw) for (int i = 0; i < 5; ++i) raw[i] = b[i];
    if ((uint8_t)(b[0] + b[1] + b[2] + b[3]) != b[4]) return FV_DHT_ERR_CHECKSUM;
    const int rh10 = (b[0] << 8) | b[1];
    int t10 = ((b[2] & 0x7F) << 8) | b[3];
    if (b[2] & 0x80) t10 = -t10;
    if (rh10 > 1000 || t10 < -400 || t10 > 800) return FV_DHT_ERR_RANGE;   /* outside the AM2302 range */
    *rh_pct = (float)rh10 / 10.0f;
    *temp_c = (float)t10 / 10.0f;
    return FV_DHT_OK;
}

/* Wait while the line equals `level`; returns the elapsed microseconds or -1 on timeout. */
static int32_t wait_while(const fv_dht22_io_t *io, int level, uint32_t timeout_us) {
    const uint32_t t0 = io->now_us(io->ctx);
    while (io->read(io->ctx) == level) {
        const uint32_t dt = io->now_us(io->ctx) - t0;
        if (dt > timeout_us) return -1;
    }
    return (int32_t)(io->now_us(io->ctx) - t0);
}

int fv_dht22_read(const fv_dht22_io_t *io, float *temp_c, float *rh_pct) {
    if (!io || !io->drive_low || !io->release || !io->read || !io->now_us || !io->delay_us || !temp_c || !rh_pct)
        return FV_DHT_ERR_ARG;
    io->drive_low(io->ctx);
    io->delay_us(io->ctx, FV_DHT22_START_LOW_US);   /* start signal: 20 ms (ENTC), interrupts still enabled */
    if (io->irq_off) io->irq_off(io->ctx);
    io->release(io->ctx);
    uint16_t high[40];
    int r = FV_DHT_OK;
    if (wait_while(io, 1, 100) < 0 || wait_while(io, 0, 120) < 0 || wait_while(io, 1, 120) < 0) {
        r = FV_DHT_ERR_NO_RESPONSE;                 /* release -> ~80 us low -> ~80 us high */
    } else {
        for (int i = 0; i < 40; ++i) {
            const int32_t h = wait_while(io, 0, 100) < 0 ? -1 : wait_while(io, 1, 120);   /* ~50 us low, then data */
            if (h < 0) { r = FV_DHT_ERR_TIMEOUT; break; }
            high[i] = (uint16_t)h;
        }
    }
    if (io->irq_on) io->irq_on(io->ctx);
    if (r != FV_DHT_OK) return r;
    return io->format == FV_DHT_FORMAT_DHT11 ? fv_dht11_decode(high, temp_c, rh_pct, 0)
                                             : fv_dht22_decode(high, temp_c, rh_pct, 0);
}

int fv_dht11_decode(const uint16_t high_us[40], float *temp_c, float *rh_pct, uint8_t raw[5]) {
    if (!high_us || !temp_c || !rh_pct) return FV_DHT_ERR_ARG;
    uint8_t b[5] = {0, 0, 0, 0, 0};
    for (int i = 0; i < 40; ++i) b[i >> 3] = (uint8_t)((b[i >> 3] << 1) | (high_us[i] > BIT_THRESHOLD_US));
    if (raw) for (int i = 0; i < 5; ++i) raw[i] = b[i];
    if ((uint8_t)(b[0] + b[1] + b[2] + b[3]) != b[4]) return FV_DHT_ERR_CHECKSUM;
    if (b[0] > 100 || b[2] > 80) return FV_DHT_ERR_RANGE;
    *rh_pct = (float)b[0];
    *temp_c = (float)b[2];
    return FV_DHT_OK;
}
