/* DHT22 / AM2302 single-wire sensor. Protocol (AM2302 datasheet): host pulls low >= 1 ms, releases; sensor answers
 * ~80 us low + ~80 us high, then 40 bits, each ~50 us low + high 26-28 us ('0') or ~70 us ('1').
 * Pin access and the microsecond clock are callbacks so the protocol is tested on the host with a simulated sensor. */
#ifndef FV_DHT22_H
#define FV_DHT22_H
#include <stdint.h>

enum { FV_DHT_OK = 0, FV_DHT_ERR_NO_RESPONSE = -1, FV_DHT_ERR_TIMEOUT = -2, FV_DHT_ERR_CHECKSUM = -3,
       FV_DHT_ERR_ARG = -4, FV_DHT_ERR_RANGE = -5 };

typedef struct {
    void (*drive_low)(void *ctx);
    void (*release)(void *ctx);
    int (*read)(void *ctx);
    uint32_t (*now_us)(void *ctx);
    void (*delay_us)(void *ctx, uint32_t us);
    void *ctx;
    void (*irq_off)(void *ctx);   /* optional: called after the start pulse (bit timing must not be interrupted) */
    void (*irq_on)(void *ctx);    /* optional: called on every exit after irq_off */
    int format;                   /* FV_DHT_FORMAT_DHT22 (0, default) or FV_DHT_FORMAT_DHT11 */
} fv_dht22_io_t;

enum { FV_DHT_FORMAT_DHT22 = 0, FV_DHT_FORMAT_DHT11 = 1 };

/* DHT11 data format, as decoded by the original ENTC firmware (@0x08000748..0x0800076E): checksum = sum of bytes 0..3,
 * humidity = byte 0 (integer %), temperature = byte 2 (integer deg C); bytes 1 and 3 (fractions) are ignored, as in ENTC.
 * Range: RH 0..100 %, T 0..80 deg C, otherwise FV_DHT_ERR_RANGE. */
int fv_dht11_decode(const uint16_t high_us[40], float *temp_c, float *rh_pct, uint8_t raw[5]);

/* Host start pulse: 20 ms, as the original ENTC firmware (HAL_Delay(20) @0x08000722), with interrupts enabled. */
#define FV_DHT22_START_LOW_US 20000u

/* Pure decoder: 40 high-pulse widths (us) -> temperature (deg C) and RH (%). */
int fv_dht22_decode(const uint16_t high_us[40], float *temp_c, float *rh_pct, uint8_t raw[5]);
/* Full transaction. Interrupt latency can corrupt bits: callers should treat any error as "no reading". */
int fv_dht22_read(const fv_dht22_io_t *io, float *temp_c, float *rh_pct);

#endif
