#include "fv_gpio.h"

#include <stddef.h>

#define GPIO_BASE(port) (0x40020000u + 0x400u * (uint32_t)(port))
#define RCC_AHB1ENR (*(volatile uint32_t *)0x40023830u)

static fv_gpio_regs_t *s_mock_ports;   /* array indexed by port when mocked */
static uint32_t *s_mock_ahb1enr;

void fv_gpio_set_mock(fv_gpio_regs_t *ports, uint32_t *rcc_ahb1enr) {
    s_mock_ports = ports;
    s_mock_ahb1enr = rcc_ahb1enr;
}

fv_gpio_regs_t *fv_gpio_port(int port) {
    if (port < 0 || port > 8) return NULL;
    if (s_mock_ports) return &s_mock_ports[port];
    return (fv_gpio_regs_t *)(uintptr_t)GPIO_BASE(port);
}

void fv_gpio_clock_enable(int port) {
    if (port < 0 || port > 8) return;
    if (s_mock_ahb1enr) { *s_mock_ahb1enr |= 1u << port; return; }
    RCC_AHB1ENR |= 1u << port;
    (void)RCC_AHB1ENR;                         /* read back: clock settles before first register access */
}

int fv_gpio_config(fv_pin_t p, int mode, int otype, int pull, int speed, int af) {
    fv_gpio_regs_t *g = fv_gpio_port(p.port);
    if (!g || p.pin < 0 || p.pin > 15 || mode < 0 || mode > 3 || otype < 0 || otype > 1 || pull < 0 || pull > 2 ||
        speed < 0 || speed > 3 || af < 0 || af > 15)
        return -1;
    const uint32_t s2 = 2u * (uint32_t)p.pin;
    if (mode == FV_GPIO_AF) {
        const uint32_t i = (uint32_t)p.pin >> 3, s4 = 4u * ((uint32_t)p.pin & 7u);
        g->AFR[i] = (g->AFR[i] & ~(0xFu << s4)) | ((uint32_t)af << s4);   /* AF before MODER: no glitch */
    }
    g->OTYPER = (g->OTYPER & ~(1u << p.pin)) | ((uint32_t)otype << p.pin);
    g->OSPEEDR = (g->OSPEEDR & ~(3u << s2)) | ((uint32_t)speed << s2);
    g->PUPDR = (g->PUPDR & ~(3u << s2)) | ((uint32_t)pull << s2);
    g->MODER = (g->MODER & ~(3u << s2)) | ((uint32_t)mode << s2);
    return 0;
}

void fv_gpio_write(fv_pin_t p, int level) {
    fv_gpio_regs_t *g = fv_gpio_port(p.port);
    if (!g || p.pin < 0 || p.pin > 15) return;
    g->BSRR = level ? (1u << p.pin) : (1u << (p.pin + 16));
}

int fv_gpio_read(fv_pin_t p) {
    fv_gpio_regs_t *g = fv_gpio_port(p.port);
    if (!g || p.pin < 0 || p.pin > 15) return 0;
    return (int)((g->IDR >> p.pin) & 1u);
}
