// Minimal firmware-shaped program used ONLY to measure linked code size of the TFLM runtime
// + CMSIS-NN kernels + model for Cortex-M4F (cross-compiled with zig). Not a working firmware:
// no startup/HAL/clock/peripherals. Separate persistent (CCM) and non-persistent (SRAM) arenas,
// as recommended in docs/STM32_MEMORY_PLAN.md.
#include <cstdarg>
#include <cstdint>

#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/kernels/conv.h"
#include "tensorflow/lite/micro/kernels/depthwise_conv.h"
#include "tensorflow/lite/micro/kernels/fully_connected.h"
#include "tensorflow/lite/micro/kernels/mul.h"
#include "tensorflow/lite/micro/kernels/softmax.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern const unsigned char g_model_data[];  // generated model array (alignas(16))

extern "C" void DebugLog(const char*, va_list) {}
extern "C" int DebugVsnprintf(char*, size_t, const char*, va_list) { return 0; }

// Placement intent on target (via linker sections): persistent -> .ccmram, non-persistent -> .bss (SRAM1).
__attribute__((section(".ccm_arena"), aligned(16))) static uint8_t g_persistent[53248];
__attribute__((aligned(16))) static uint8_t g_nonpersistent[97280];
volatile int8_t g_sink;

int main() {
  static tflite::MicroMutableOpResolver<7> r;
#ifdef INT8_ONLY
  r.AddAdd(tflite::Register_ADD_INT8()); r.AddConv2D(tflite::Register_CONV_2D_INT8());
  r.AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8());
  r.AddFullyConnected(tflite::Register_FULLY_CONNECTED_INT8());
  r.AddMean(); r.AddMul(tflite::Register_MUL_INT8()); r.AddSoftmax(tflite::Register_SOFTMAX_INT8());
#else
  r.AddAdd(); r.AddConv2D(); r.AddDepthwiseConv2D(); r.AddFullyConnected();
  r.AddMean(); r.AddMul(); r.AddSoftmax();
#endif
  tflite::MicroAllocator* a = tflite::MicroAllocator::Create(g_persistent, sizeof g_persistent,
                                                             g_nonpersistent, sizeof g_nonpersistent);
  static tflite::MicroInterpreter it(tflite::GetModel(g_model_data), r, a);
  if (it.AllocateTensors() != kTfLiteOk) return 1;
  it.input(0)->data.int8[0] = 0;
  if (it.Invoke() != kTfLiteOk) return 2;
  for (size_t j = 0; j < it.outputs_size(); ++j) g_sink = it.output(j)->data.int8[0];
  return 0;
}
