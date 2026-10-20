/* Common status / state types for the STM32F407 firmware (portable C99). */
#ifndef FV_COMMON_H
#define FV_COMMON_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    FV_OK = 0,
    FV_ERR_ARG = -1,              /* invalid argument */
    FV_ERR_NOT_IMPLEMENTED = -2,  /* hardware-specific code pending (see platform/) */
    FV_ERR_HW = -3,               /* peripheral reported an error */
    FV_ERR_TIMEOUT = -4,
    FV_ERR_MODEL = -5,            /* model load / shape / quantisation mismatch */
    FV_ERR_MEMORY = -6,           /* arena too small or no free camera window */
    FV_ERR_INPUT_REJECTED = -7    /* input failed validation */
} fv_status_t;

/* Same vocabulary as the Python pipeline (fruitvision.postprocess / system). */
typedef enum {
    FV_STATE_PREDICTED = 0,    /* a model produced the value */
    FV_STATE_UNCERTAIN = 1,    /* a model exists but its output is withheld */
    FV_STATE_UNAVAILABLE = 2   /* no valid input, or no model/data for this case */
} fv_state_t;

const char *fv_state_name(fv_state_t s);
const char *fv_status_name(fv_status_t s);

#endif
