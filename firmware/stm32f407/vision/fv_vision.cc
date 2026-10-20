#include "fv_vision.h"

#include <new>

#include "fv_generated_config.h"
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

namespace {
using Resolver = tflite::MicroMutableOpResolver<7>;
alignas(Resolver) unsigned char g_resolver_buf[sizeof(Resolver)];
alignas(tflite::MicroInterpreter) unsigned char g_interp_buf[sizeof(tflite::MicroInterpreter)];
tflite::MicroInterpreter* g_it = nullptr;

bool QuantIs(const TfLiteTensor* t, float scale, int zp) {
  if (t->quantization.type != kTfLiteAffineQuantization) return false;
  const auto* q = static_cast<const TfLiteAffineQuantization*>(t->quantization.params);
  return q && q->scale && q->scale->size == 1 && q->scale->data[0] == scale && q->zero_point->data[0] == zp;
}
}  // namespace

extern "C" fv_status_t fv_vision_init(const uint8_t* model_data, uint8_t* persistent, size_t persistent_bytes,
                                      uint8_t* nonpersistent, size_t nonpersistent_bytes) {
  if (!model_data || !persistent || !nonpersistent) return FV_ERR_ARG;
  if ((reinterpret_cast<uintptr_t>(model_data) | reinterpret_cast<uintptr_t>(persistent) |
       reinterpret_cast<uintptr_t>(nonpersistent)) & 15u)
    return FV_ERR_ARG;  // TFLM expects 16-byte alignment
  const tflite::Model* model = tflite::GetModel(model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION) return FV_ERR_MODEL;

  auto* r = new (g_resolver_buf) Resolver();
  r->AddAdd(tflite::Register_ADD_INT8());
  r->AddConv2D(tflite::Register_CONV_2D_INT8());
  r->AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8());
  r->AddFullyConnected(tflite::Register_FULLY_CONNECTED_INT8());
  r->AddMean();
  r->AddMul(tflite::Register_MUL_INT8());
  r->AddSoftmax(tflite::Register_SOFTMAX_INT8());

  tflite::MicroAllocator* a =
      tflite::MicroAllocator::Create(persistent, persistent_bytes, nonpersistent, nonpersistent_bytes);
  if (!a) return FV_ERR_MEMORY;
  g_it = new (g_interp_buf) tflite::MicroInterpreter(model, *r, a);
  if (g_it->AllocateTensors() != kTfLiteOk) { g_it = nullptr; return FV_ERR_MEMORY; }

  // Interface checks against the generated header (fail closed on any mismatch).
  const TfLiteTensor* in = g_it->input(0);
  if (g_it->inputs_size() != 1 || in->type != kTfLiteInt8 || in->dims->size != 4 ||
      in->dims->data[1] != FV_MODEL_IN_H || in->dims->data[2] != FV_MODEL_IN_W || in->dims->data[3] != FV_MODEL_IN_C ||
      !QuantIs(in, FV_MODEL_IN_SCALE, FV_MODEL_IN_ZERO_POINT) || g_it->outputs_size() != FV_MODEL_N_OUTPUTS) {
    g_it = nullptr;
    return FV_ERR_MODEL;
  }
  for (int h = 0; h < FV_N_HEADS; ++h) {
    const TfLiteTensor* t = g_it->output(FV_HEAD_OUTPUT_INDEX[h]);
    if (t->type != kTfLiteInt8 || t->bytes != FV_HEAD_N_CLASSES[h] ||
        !QuantIs(t, FV_MODEL_OUT_SCALE, FV_MODEL_OUT_ZERO_POINT)) {
      g_it = nullptr;
      return FV_ERR_MODEL;
    }
  }
#ifdef FV_PRESENCE_OUTPUT_INDEX
  const TfLiteTensor* tp = g_it->output(FV_PRESENCE_OUTPUT_INDEX);
  if (tp->type != kTfLiteInt8 || tp->bytes != 2 ||
      !QuantIs(tp, FV_MODEL_OUT_SCALE, FV_MODEL_OUT_ZERO_POINT)) {
    g_it = nullptr;
    return FV_ERR_MODEL;
  }
#endif
  return FV_OK;
}

extern "C" int8_t* fv_vision_input(size_t* bytes) {
  if (!g_it) return nullptr;
  if (bytes) *bytes = g_it->input(0)->bytes;
  return g_it->input(0)->data.int8;
}

extern "C" size_t fv_vision_busy_ranges(fv_range_t* out, size_t max) {
  if (!g_it || !out) return 0;
  size_t n = 0;
  if (n < max) out[n++] = {reinterpret_cast<const uint8_t*>(g_it->input(0)->data.raw), g_it->input(0)->bytes};
  for (size_t j = 0; j < g_it->outputs_size() && n < max; ++j)
    out[n++] = {reinterpret_cast<const uint8_t*>(g_it->output(j)->data.raw), g_it->output(j)->bytes};
  return n;
}

extern "C" fv_status_t fv_vision_invoke(fv_vision_raw_t* out) {
  if (!g_it || !out) return FV_ERR_ARG;
  if (g_it->Invoke() != kTfLiteOk) return FV_ERR_MODEL;
  for (int h = 0; h < FV_N_HEADS; ++h) {
    const TfLiteTensor* t = g_it->output(FV_HEAD_OUTPUT_INDEX[h]);
    for (int k = 0; k < FV_MAX_CLASSES; ++k) out->q[h][k] = k < FV_HEAD_N_CLASSES[h] ? t->data.int8[k] : 0;
  }
#ifdef FV_PRESENCE_OUTPUT_INDEX
  const TfLiteTensor* tp = g_it->output(FV_PRESENCE_OUTPUT_INDEX);
  out->presence_raw[0] = tp->data.int8[0];
  out->presence_raw[1] = tp->data.int8[1];
#endif
  return FV_OK;
}

extern "C" size_t fv_vision_arena_used_bytes(void) { return g_it ? g_it->arena_used_bytes() : 0; }
