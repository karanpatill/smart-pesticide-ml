/* TFLM DebugLog hooks (tensorflow/lite/micro/debug_log.h). TFLM is built with
 * TF_LITE_STRIP_ERROR_STRINGS, so messages are dropped: no printf/vsnprintf is linked for logging.
 * Init/invoke failures are reported through fv_status_t codes on the serial line instead. */
#include <stdarg.h>
#include <stddef.h>

void DebugLog(const char *format, va_list args) { (void)format; (void)args; }

int DebugVsnprintf(char *buffer, size_t buf_size, const char *format, va_list vlist) {
    (void)format; (void)vlist;
    if (buffer && buf_size) buffer[0] = '\0';
    return 0;
}
