#!/usr/bin/env bash
# Cross-compile TFLM + CMSIS-NN (DSP path) + model for Cortex-M4F with zig and link with
# --gc-sections, to MEASURE linked section sizes. Target triple thumb-linux-musleabihf is used only
# to obtain libc headers/archive; code is Thumb-2 for -mcpu=cortex_m4 with hard-float ABI.
set -euo pipefail
EXTRA_DEFS=${EXTRA_DEFS:-}; VARIANT=${VARIANT:-}
W=~/tflm_work; T=$W/tflite-micro; D=$W/downloads; OUT=$W/build_cm4$VARIANT; mkdir -p $OUT
R=/mnt/d/smart-pesticide-ml; ZIG="python3 -m ziglang"
TGT="-target thumb-linux-musleabihf -mcpu=cortex_m4 -mfloat-abi=hard"
COMMON="$TGT -Os -ffunction-sections -fdata-sections -DCMSIS_NN -DTF_LITE_STATIC_MEMORY $EXTRA_DEFS -DTF_LITE_STRIP_ERROR_STRINGS -Wno-everything"
CXXF="$COMMON -std=c++17 -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-unwind-tables -fno-asynchronous-unwind-tables"
INC="-I$T -I$D/flatbuffers/include -I$D/cmsis_nn -I$D/cmsis_nn/Include"
M=$T/tensorflow/lite/micro
python3 - "$R/models/experimental/tflite/combined_int8.tflite" "$OUT/model_data.cc" <<'PY'
import sys
b = open(sys.argv[1], "rb").read()
with open(sys.argv[2], "w") as f:
    f.write("alignas(16) extern const unsigned char g_model_data[] = {")
    f.write(",".join(str(x) for x in b))
    f.write("};\nextern const unsigned int g_model_len = %d;\n" % len(b))
PY
SRCS="$(ls $M/*.cc | grep -vE '_test|debug_log|test_helper|mock_micro_graph|fake_micro_context|hexdump|recording_' )
$(ls $M/arena_allocator/*.cc $M/memory_planner/*.cc | grep -vE '_test|recording_')
$(ls $M/kernels/internal/*.cc | grep -v _test)
$M/kernels/kernel_util.cc $M/kernels/reduce.cc $M/kernels/reduce_common.cc
$M/kernels/add_common.cc $M/kernels/conv_common.cc $M/kernels/depthwise_conv_common.cc
$M/kernels/fully_connected_common.cc $M/kernels/mul_common.cc $M/kernels/softmax_common.cc
$(for k in add conv depthwise_conv fully_connected mul softmax; do echo $M/kernels/cmsis_nn/$k.cc; done)
$R/tools/stm32_memory/cm4_size_main.cc $OUT/model_data.cc"
CSRCS="$(find $D/cmsis_nn/Source -name '*.c' ! -name '*_f32.c' ! -name '*_f16.c')"
objs=()
for s in $SRCS; do o=$OUT/$(echo $s | md5sum | cut -c1-12).o; [ -f $o ] && [ $o -nt $s ] || $ZIG c++ $CXXF $INC -c $s -o $o; objs+=($o); done
for s in $CSRCS; do o=$OUT/$(echo $s | md5sum | cut -c1-12).o; [ -f $o ] || $ZIG cc $COMMON $INC -c $s -o $o; objs+=($o); done
# Freestanding link: no libc (musl's ARM-Linux asm is A-profile only). Undefined libc/libm
# symbols are first LISTED (link without ignore), then ignored so sizes can be measured.
LNK="-target thumb-freestanding-eabihf -mcpu=cortex_m4 -mfloat-abi=hard -nostdlib -Wl,--gc-sections -Wl,-e,main"
$ZIG c++ $LNK -o $OUT/probe.elf "${objs[@]}" 2>&1 | grep -oE "undefined symbol: [^ ]+" | sort -u > $OUT/undefined_symbols.txt || true
$ZIG cc $COMMON -c $R/tools/stm32_memory/cm4_libc_stubs.c -o $OUT/zz_stubs.o
$ZIG c++ $LNK -o $OUT/tflm_cm4.elf "${objs[@]}" $OUT/zz_stubs.o
echo "UNDEFINED (to be provided by newlib/libm on target): $(wc -l < $OUT/undefined_symbols.txt)"
echo "BUILT $OUT/tflm_cm4.elf (${#objs[@]} objects)"
