// Host-side TFLite-Micro memory driver (NOT firmware). Built with zig for 32-bit x86
// (same pointer width as Cortex-M) to measure arena requirements of a .tflite model.
//
//   tflm_mem_driver MODEL.tflite INPUT.int8 recording ARENA
//       -> RecordingMicroAllocator breakdown (single arena) + output bytes
//   tflm_mem_driver MODEL.tflite INPUT.int8 split PERSISTENT NON_PERSISTENT
//       -> "OK"/"FAIL" + outputs (separate persistent / non-persistent arenas)
//   tflm_mem_driver MODEL.tflite INPUT.int8 single ARENA
//       -> "OK"/"FAIL" + outputs (single arena, plain MicroAllocator)
// Minimum sizes are searched by tools/stm32_memory/arena_search.py with ONE PROCESS PER PROBE,
// because TFLM may fault (not just fail) when an arena is too small for its own bookkeeping.
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <vector>

#include "tensorflow/lite/micro/kernels/conv.h"
#include "tensorflow/lite/micro/kernels/depthwise_conv.h"
#include "tensorflow/lite/micro/kernels/fully_connected.h"
#include "tensorflow/lite/micro/kernels/softmax.h"
#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/kernels/mul.h"
#include "tensorflow/lite/micro/micro_allocator.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/recording_micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

extern "C" void DebugLog(const char* format, va_list args) {
  if (getenv("TFLM_QUIET") == nullptr) vfprintf(stderr, format, args);
}
extern "C" int DebugVsnprintf(char* b, size_t n, const char* f, va_list a) { return vsnprintf(b, n, f, a); }

namespace {
using Resolver = tflite::MicroMutableOpResolver<7>;

void AddOps(Resolver& r) {
#ifdef INT8_ONLY  // int8-only kernel variants (drop int4/int16 code paths); same model, same math
  r.AddAdd(tflite::Register_ADD_INT8()); r.AddConv2D(tflite::Register_CONV_2D_INT8());
  r.AddDepthwiseConv2D(tflite::Register_DEPTHWISE_CONV_2D_INT8());
  r.AddFullyConnected(tflite::Register_FULLY_CONNECTED_INT8());
  r.AddMean(); r.AddMul(tflite::Register_MUL_INT8()); r.AddSoftmax(tflite::Register_SOFTMAX_INT8());
#else
  r.AddAdd(); r.AddConv2D(); r.AddDepthwiseConv2D(); r.AddFullyConnected();
  r.AddMean(); r.AddMul(); r.AddSoftmax();
#endif
}

std::vector<unsigned char> ReadFile(const char* p) {
  FILE* f = fopen(p, "rb");
  if (!f) { fprintf(stderr, "cannot open %s\n", p); exit(2); }
  std::vector<unsigned char> v;
  unsigned char buf[65536];
  size_t n;
  while ((n = fread(buf, 1, sizeof buf, f)) > 0) v.insert(v.end(), buf, buf + n);
  fclose(f);
  return v;
}

alignas(16) unsigned char g_model[1 << 20];
alignas(16) unsigned char g_a[1 << 20];
alignas(16) unsigned char g_b[1 << 20];
std::vector<unsigned char> g_input;

void PrintOutputs(tflite::MicroInterpreter& it) {
  for (size_t j = 0; j < it.outputs_size(); ++j) {
    TfLiteTensor* t = it.output(j);
    printf("OUT %zu", j);
    for (size_t k = 0; k < t->bytes; ++k) printf(" %d", t->data.int8[k]);
    printf("\n");
  }
}

const unsigned char* g_offset_base = nullptr;  // set in split mode: print tensor offsets vs this base

bool RunInto(tflite::MicroInterpreter& it, bool print) {
  if (it.AllocateTensors() != kTfLiteOk) return false;
  if (print && g_offset_base) {
    printf("OFFSET input0 %ld bytes %zu\n", (long)((const unsigned char*)it.input(0)->data.raw - g_offset_base),
           it.input(0)->bytes);
    for (size_t j = 0; j < it.outputs_size(); ++j)
      printf("OFFSET output%zu %ld bytes %zu\n", j, (long)((const unsigned char*)it.output(j)->data.raw - g_offset_base),
             it.output(j)->bytes);
  }
  TfLiteTensor* in = it.input(0);
  if (in->bytes != g_input.size()) { fprintf(stderr, "input size %zu != %zu\n", in->bytes, g_input.size()); exit(3); }
  memcpy(in->data.int8, g_input.data(), in->bytes);
  if (it.Invoke() != kTfLiteOk) return false;
  if (print) PrintOutputs(it);
  return true;
}

bool TrySingle(const tflite::Model* m, const Resolver& r, size_t n, bool print) {
  tflite::MicroInterpreter it(m, r, g_a, n);
  return RunInto(it, print);
}

bool TrySplit(const tflite::Model* m, const Resolver& r, size_t p, size_t np, bool print) {
  tflite::MicroAllocator* a = tflite::MicroAllocator::Create(g_a, p, g_b, np);
  if (a == nullptr) return false;
  tflite::MicroInterpreter it(m, r, a);
  return RunInto(it, print);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: see header\n"); return 1; }
  std::vector<unsigned char> mb = ReadFile(argv[1]);
  if (mb.size() > sizeof g_model) { fprintf(stderr, "model too big\n"); return 1; }
  memcpy(g_model, mb.data(), mb.size());
  g_input = ReadFile(argv[2]);
  const tflite::Model* m = tflite::GetModel(g_model);
  Resolver r;
  AddOps(r);
  printf("sizeof(void*)=%zu model_bytes=%zu\n", sizeof(void*), mb.size());
  const char* mode = argv[3];
  if (!strcmp(mode, "recording")) {
    size_t n = strtoul(argv[4], nullptr, 10);
    tflite::RecordingMicroInterpreter it(m, r, g_a, n);
    bool ok = RunInto(it, true);
    printf("STATUS %s arena_used_bytes=%zu\n", ok ? "OK" : "FAIL", it.arena_used_bytes());
    if (ok) it.GetMicroAllocator().PrintAllocations();
    return ok ? 0 : 4;
  }
  if (!strcmp(mode, "single")) {
    bool ok = TrySingle(m, r, strtoul(argv[4], nullptr, 10), true);
    printf("STATUS %s\n", ok ? "OK" : "FAIL");
    return ok ? 0 : 4;
  }
  if (!strcmp(mode, "split")) {
    g_offset_base = g_b;  // non-persistent arena base
    bool ok = TrySplit(m, r, strtoul(argv[4], nullptr, 10), strtoul(argv[5], nullptr, 10), true);
    printf("STATUS %s\n", ok ? "OK" : "FAIL");
    return ok ? 0 : 4;
  }
  return 1;
}
