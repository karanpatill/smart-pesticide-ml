#!/usr/bin/env bash
# Build the TFLM memory driver for 32-bit x86 Linux (static musl) with zig.
# KERNELS=reference (default) or cmsis_nn (portable-C CMSIS-NN kernels; no DSP intrinsics on x86).
set -euo pipefail
EXTRA_DEFS=${EXTRA_DEFS:-}; VARIANT=${VARIANT:-}
W=~/tflm_work; T=$W/tflite-micro; D=$W/downloads; KERNELS=${KERNELS:-reference}
OUT=$W/build_host32_$KERNELS$VARIANT; mkdir -p $OUT
ZIG="python3 -m ziglang"
TARGET=${TARGET:-x86-linux-musl}
CXXFLAGS="-target $TARGET -std=c++17 -O2 -fno-exceptions -fno-rtti -fno-threadsafe-statics -DTF_LITE_STATIC_MEMORY $EXTRA_DEFS -DTF_LITE_DISABLE_X86_NEON -Wno-everything"
INC="-I$T -I$D/flatbuffers/include -I$D/cmsis_nn -I$D/cmsis_nn/Include"
M=$T/tensorflow/lite/micro
SRCS="$(ls $M/*.cc | grep -vE '_test|debug_log|test_helper|mock_micro_graph|fake_micro_context|hexdump')
$(ls $M/arena_allocator/*.cc $M/memory_planner/*.cc | grep -v _test)
$(ls $M/kernels/internal/*.cc 2>/dev/null | grep -v _test)
$M/kernels/kernel_util.cc $M/kernels/reduce.cc $M/kernels/reduce_common.cc
$M/kernels/add_common.cc $M/kernels/conv_common.cc $M/kernels/depthwise_conv_common.cc
$M/kernels/fully_connected_common.cc $M/kernels/mul_common.cc $M/kernels/softmax_common.cc
$(find $T/tensorflow -path '*c/common.cc' -o -path '*core/api/*.cc' | grep -vE 'test|/micro/' || true)"
if [ "$KERNELS" = cmsis_nn ]; then
  CXXFLAGS="$CXXFLAGS -DCMSIS_NN"   # as TFLM's Makefile does for OPTIMIZED_KERNEL_DIR=cmsis_nn
  SRCS="$SRCS $(for k in add conv depthwise_conv fully_connected mul softmax; do echo $M/kernels/cmsis_nn/$k.cc; done)"
  CSRCS="$(find $D/cmsis_nn/Source -name '*.c' ! -name '*_f32.c' ! -name '*_f16.c')"
else
  SRCS="$SRCS $(for k in add conv depthwise_conv fully_connected mul softmax; do echo $M/kernels/$k.cc; done)"
  CSRCS=""
fi
SRCS="$SRCS /mnt/d/smart-pesticide-ml/tools/stm32_memory/tflm_mem_driver.cc"
objs=()
for s in $SRCS; do o=$OUT/$(echo $s | md5sum | cut -c1-12).o; [ -f $o ] || $ZIG c++ $CXXFLAGS $INC -c $s -o $o; objs+=($o); done
for s in $CSRCS; do o=$OUT/$(echo $s | md5sum | cut -c1-12).o; [ -f $o ] || $ZIG cc -target $TARGET -O2 -Wno-everything $INC -c $s -o $o; objs+=($o); done
$ZIG c++ -target $TARGET -static -o $OUT/tflm_mem_driver "${objs[@]}"
echo "BUILT $OUT/tflm_mem_driver ($KERNELS, ${#objs[@]} objects)"
