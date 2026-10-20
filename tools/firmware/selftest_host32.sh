#!/usr/bin/env bash
# Build + run the self-test core on 32-bit x86 (zig) with the cached TFLM host32 objects.
set -euo pipefail
W=~/tflm_work; T=$W/tflite-micro; D=$W/downloads; R=/mnt/d/smart-pesticide-ml; F=$R/firmware/stm32f407
WITH_FRAME=${WITH_FRAME:-0}; OUT=$W/build_fw/selftest_host32_f$WITH_FRAME; mkdir -p $OUT; ZIG="python3 -m ziglang"; HT="-target x86-linux-musl"
INC_FW="-I$F/selftest -I$F/app -I$F/platform -I$F/vision -I$F/generated -I$R/firmware/model2 -I$R/models/model2_export -I$R/firmware/image -I$R/firmware/memory"
H=$W/build_host32_cmsis_nn_int8only
EXCL="$(echo $R/tools/stm32_memory/tflm_mem_driver.cc | md5sum | cut -c1-12)"
TF_OBJS=$(ls $H/*.o | grep -v "$EXCL")
$ZIG c++ $HT -std=c++17 -O2 -fno-exceptions -fno-rtti -fno-threadsafe-statics -DTF_LITE_STATIC_MEMORY -DCMSIS_NN -DTF_LITE_DISABLE_X86_NEON -Wno-everything -I$T -I$D/flatbuffers/include -I$D/cmsis_nn -I$D/cmsis_nn/Include $INC_FW -c $F/vision/fv_vision.cc -o $OUT/fv_vision.o
python3 $R/tools/firmware/gen_model_data.py $OUT/fv_model_data.c
objs=($OUT/fv_vision.o)
FD=""; EXTRA=""; [ "$WITH_FRAME" = 1 ] && { FD="-DFV_ST_WITH_FRAME"; EXTRA="$R/firmware/image/preprocess_rgb565.c"; }
for s in $F/selftest/fv_selftest_core.c $F/tests/fv_selftest_host_main.c $EXTRA $F/app/fv_result.c $F/app/fv_image_check.c $F/vision/fv_debug_log.c $R/firmware/model2/model2_infer.c; do
  o=$OUT/$(basename $s).o; $ZIG cc $HT -std=c99 -O2 -Wall -Wextra -Werror $FD $INC_FW -c $s -o $o; objs+=($o); done
DATA="$R/build/fw/fv_selftest_data.c"; [ "$WITH_FRAME" = 1 ] && DATA="$DATA $R/build/fw/fv_selftest_frame_data.c"
for s in $DATA $OUT/fv_model_data.c; do o=$OUT/$(basename $s).o; $ZIG cc $HT -std=c99 -O2 $INC_FW -c $s -o $o; objs+=($o); done
$ZIG c++ $HT -static -o $OUT/fv_selftest_host "${objs[@]}" $TF_OBJS
$OUT/fv_selftest_host
