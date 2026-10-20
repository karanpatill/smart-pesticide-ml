#!/usr/bin/env bash
# REAL target build with arm-none-eabi-gcc + newlib-nano (WSL): firmware + TFLM (int8-only CMSIS-NN,
# DSP path) + frozen model, linked with firmware/stm32f407/linker/STM32F407VETX_FV.ld.
# Produces an ELF/BIN/MAP. Platform drivers are still PENDING (FV_ERR_NOT_IMPLEMENTED): the image
# would boot to a halt loop on hardware. Not a CubeIDE/HAL project.
set -euo pipefail
W=~/tflm_work; T=$W/tflite-micro; D=$W/downloads; R=/mnt/d/smart-pesticide-ml
F=$R/firmware/stm32f407; OUT=$W/build_gcc; mkdir -p $OUT/obj
# FV_TARGET=app (default: application + board drivers, pin map from the ENTC firmware) | selftest | selftest_frame
FV_TARGET=${FV_TARGET:-app}; NAME=fv_app; [ "$FV_TARGET" = selftest ] && NAME=fv_selftest   # fv_app replaces nothing: fv_fw.* (earlier skeleton) is kept
[ "$FV_TARGET" = selftest_frame ] && NAME=fv_selftest_frame   # self-test + offline 160x120 RGB565 frame
NAME=${FV_NAME:-$NAME}   # e.g. FV_NAME=fv_app_v2: new artifact name; existing images are never replaced
ARCH="-mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard"
COMMON="$ARCH -Os -g -ffunction-sections -fdata-sections --specs=nano.specs"
DEFS="-DNDEBUG -DCMSIS_NN -DTF_LITE_STATIC_MEMORY -DTF_LITE_STRIP_ERROR_STRINGS -DARM_MATH_DSP"
CXXF="$COMMON $DEFS -std=c++17 -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-unwind-tables -fno-use-cxa-atexit -w"
CF_LIB="$COMMON $DEFS -std=c11 -w"
CF_FW="$COMMON -std=c99 -Wall -Wextra -Werror -Wdouble-promotion"
CF_FW="$CF_FW ${FV_EXTRA_CFLAGS:-}"   # e.g. FV_EXTRA_CFLAGS=-DFV_DIAG_CAPTURE for the diagnostic build
INC_TFLM="-I$T -I$D/flatbuffers/include -I$D/cmsis_nn -I$D/cmsis_nn/Include"
INC_FW="${FV_EXTRA_INC:-} -I$F/selftest -I$F/app -I$F/board -I$F/drivers -I$F/platform -I$F/vision -I$F/generated -I$R/firmware/model2 -I$R/models/model2_export -I$R/firmware/image -I$R/firmware/memory"
M=$T/tensorflow/lite/micro
if [ -n "${FV_MODEL:-}" ]; then
  python3 $R/tools/firmware/gen_model_data.py --model "$FV_MODEL" $OUT/fv_model_data.c
else
  python3 $R/tools/firmware/gen_model_data.py $OUT/fv_model_data.c
fi
TF="$(ls $M/*.cc | grep -vE '_test|debug_log|test_helper|mock_micro_graph|fake_micro_context|hexdump|recording_')
$(ls $M/arena_allocator/*.cc $M/memory_planner/*.cc | grep -vE '_test|recording_')
$(ls $M/kernels/internal/*.cc | grep -v _test)
$M/kernels/kernel_util.cc $M/kernels/reduce.cc $M/kernels/reduce_common.cc
$M/kernels/add_common.cc $M/kernels/conv_common.cc $M/kernels/depthwise_conv_common.cc
$M/kernels/fully_connected_common.cc $M/kernels/mul_common.cc $M/kernels/softmax_common.cc
$(for k in add conv depthwise_conv fully_connected mul softmax; do echo $M/kernels/cmsis_nn/$k.cc; done)
$(find $T/tensorflow -path '*c/common.cc' -o -path '*core/api/*.cc' | grep -vE 'test|/micro/' || true)"
NN="$(find $D/cmsis_nn/Source -name '*.c' ! -name '*_f32.c' ! -name '*_f16.c')"
COMMON_FW="$F/app/fv_result.c $F/app/fv_sensor.c $F/app/fv_image_check.c $F/startup/fv_startup.c $F/startup/fv_syscalls.c
$F/vision/fv_debug_log.c $R/firmware/model2/model2_infer.c"
if [ "$FV_TARGET" = selftest_frame ]; then
  for d in fv_selftest_data.c fv_selftest_frame_data.c; do [ -f $R/build/fw/$d ] || { echo "missing build/fw/$d (tools/firmware/gen_selftest_data.py)"; exit 1; }; done
  CF_FW="$CF_FW -DFV_ST_WITH_FRAME"
  FWC="$COMMON_FW $F/selftest/fv_selftest_core.c $F/selftest/fv_selftest_main.c $F/platform/fv_clock_stm32f4.c $R/firmware/image/preprocess_rgb565.c $R/build/fw/fv_selftest_data.c $R/build/fw/fv_selftest_frame_data.c"
elif [ "$FV_TARGET" = selftest ]; then
  [ -f $R/build/fw/fv_selftest_data.c ] || { echo "run tools/firmware/gen_selftest_data.py build/fw/fv_selftest_data.c reports/firmware/selftest_expected.json first"; exit 1; }
  FWC="$COMMON_FW $F/selftest/fv_selftest_core.c $F/selftest/fv_selftest_main.c $F/platform/fv_clock_stm32f4.c $R/build/fw/fv_selftest_data.c"
else
  FWC="$COMMON_FW $F/app/fv_app.c $F/app/fv_capture.c $F/app/fv_presence.c $F/app/fv_report.c $F/app/fv_diag.c $F/app/main.c $F/platform/fv_platform_stm32.c $F/platform/fv_clock_stm32f4.c $F/platform/fv_dcmi_capture.c
$F/drivers/fv_gpio.c $F/drivers/fv_bitbang_bus.c $F/drivers/fv_ov2640.c $F/drivers/fv_cam_tune.c $F/drivers/fv_tcs34725.c $F/drivers/fv_ssd1306.c $F/drivers/fv_dht22.c $F/drivers/fv_adc.c $F/drivers/fv_entc_ph.c
$R/firmware/image/preprocess_rgb565.c $R/firmware/memory/fv_arena_reuse.c"
fi
objs=()
o() { echo $OUT/obj/$(echo $1 | md5sum | cut -c1-12)_$(basename $1).o; }
for s in $TF; do ob=$(o $s); [ -f $ob ] && [ $ob -nt $s ] || arm-none-eabi-g++ $CXXF $INC_TFLM -c $s -o $ob; objs+=($ob); done
for s in $NN; do ob=$(o $s); [ -f $ob ] || arm-none-eabi-gcc $CF_LIB $INC_TFLM -c $s -o $ob; objs+=($ob); done
ob=$(o $F/vision/fv_vision.cc); arm-none-eabi-g++ $CXXF $INC_TFLM $INC_FW -c $F/vision/fv_vision.cc -o $ob; objs+=($ob)
for s in $FWC; do ob=$(o $s); case $s in *fv_selftest_data.c|*fv_selftest_frame_data.c) F2="$COMMON -std=c99";; *) F2="$CF_FW";; esac; arm-none-eabi-gcc $F2 $INC_FW -c $s -o $ob; objs+=($ob); done
ob=$(o $OUT/fv_model_data.c); arm-none-eabi-gcc $CF_FW -c $OUT/fv_model_data.c -o $ob; objs+=($ob)
arm-none-eabi-g++ $ARCH --specs=nano.specs --specs=nosys.specs -nostartfiles -Wl,--gc-sections \
  -Wl,-Map=$OUT/$NAME.map -Wl,--print-memory-usage -T $F/linker/STM32F407VETX_FV.ld -o $OUT/$NAME.elf "${objs[@]}" -lm
arm-none-eabi-objcopy -O binary $OUT/$NAME.elf $OUT/$NAME.bin
arm-none-eabi-size -A $OUT/$NAME.elf | grep -vE '^\.(debug|comment|ARM.attributes)' 
mkdir -p $R/reports/firmware/gcc
# never silently replace a recorded self-test artifact (e.g. the image that was flashed and verified)
if [ -f $R/reports/firmware/gcc/$NAME.bin ] && ! cmp -s $OUT/$NAME.bin $R/reports/firmware/gcc/$NAME.bin && [ "${FV_OVERWRITE:-0}" != 1 ]; then
  echo "NOT COPIED: reports/firmware/gcc/$NAME.bin exists and differs (set FV_OVERWRITE=1 to replace). Build output: $OUT/$NAME.*"
else
  cp $OUT/$NAME.elf $OUT/$NAME.bin $OUT/$NAME.map $R/reports/firmware/gcc/
fi
echo "BUILT $OUT/$NAME.elf (${#objs[@]} objects)"
