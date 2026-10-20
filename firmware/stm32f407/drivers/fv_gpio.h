/* STM32F4 GPIO + RCC clock-enable, register level (RM0090 8.4 / 7.3). No HAL dependency.
 * Register blocks are reached through fv_gpio_port(); host tests replace them via fv_gpio_set_mock(). */
#ifndef FV_GPIO_H
#define FV_GPIO_H
#include <stdint.h>

typedef struct {
    volatile uint32_t MODER, OTYPER, OSPEEDR, PUPDR, IDR, ODR, BSRR, LCKR, AFR[2];
} fv_gpio_regs_t;

enum { FV_GPIO_IN = 0, FV_GPIO_OUT = 1, FV_GPIO_AF = 2, FV_GPIO_ANALOG = 3 };
enum { FV_GPIO_PP = 0, FV_GPIO_OD = 1 };
enum { FV_GPIO_NOPULL = 0, FV_GPIO_PULLUP = 1, FV_GPIO_PULLDOWN = 2 };
enum { FV_GPIO_SPEED_LOW = 0, FV_GPIO_SPEED_MED = 1, FV_GPIO_SPEED_HIGH = 2, FV_GPIO_SPEED_VHIGH = 3 };

typedef struct { int8_t port, pin; } fv_pin_t;

fv_gpio_regs_t *fv_gpio_port(int port);           /* NULL for an invalid port */
void fv_gpio_set_mock(fv_gpio_regs_t *ports, uint32_t *rcc_ahb1enr);   /* host tests only; NULL restores hardware */
void fv_gpio_clock_enable(int port);
/* Full pin configuration; af is used only for FV_GPIO_AF. Returns 0, or -1 for invalid arguments. */
int fv_gpio_config(fv_pin_t p, int mode, int otype, int pull, int speed, int af);
void fv_gpio_write(fv_pin_t p, int level);        /* atomic via BSRR */
int fv_gpio_read(fv_pin_t p);                     /* IDR */

#endif
