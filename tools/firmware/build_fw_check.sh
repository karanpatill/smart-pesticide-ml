#!/usr/bin/env bash
# Firmware build CHECKS in WSL with zig (clang + lld). NOT a GCC/newlib/CubeIDE build; the ELFs
# produced here are NOT flashable. Two parts:
#  1. host32: real vision/fv_vision.cc + app/*.c + TFLM (CMSIS-NN portable int8 kernels), 32-bit
#     x86, run on the 20 test inputs (raw mode) and on RGB565 frames (app mode).
#  2. cm4: full Cortex-M4F link of firmware + TFLM int8-only + model with
#     firmware/stm32f407/linker/STM32F407VETX_FV.ld, to check placement and measure sizes.
# Reuses TFLM objects cached by tools/stm32_memory/build_host32.sh / build_cm4.sh.
set -euo pipefail
W=~/tflm_work; T=$W/tflite-micro; D=$W/downloads; R=/mnt/d/smart-pesticide-ml
F=$R/firmware/stm32f407; OUT=$W/build_fw; mkdir -p $OUT/host32 $OUT/cm4
ZIG="python3 -m ziglang"
INC_TFLM="-I$T -I$D/flatbuffers/include -I$D/cmsis_nn -I$D/cmsis_nn/Include"
INC_FW="-I$F/app -I$F/board -I$F/drivers -I$F/platform -I$F/vision -I$F/generated -I$R/firmware/model2 -I$R/models/model2_export -I$R/firmware/image -I$R/firmware/memory"
python3 $R/tools/firmware/gen_model_data.py $OUT/fv_model_data.c
APP_C="$F/app/fv_app.c $F/app/fv_presence.c $F/app/fv_result.c $F/app/fv_sensor.c $F/app/fv_image_check.c $F/app/fv_report.c $R/firmware/model2/model2_infer.c $R/firmware/image/preprocess_rgb565.c $R/firmware/memory/fv_arena_reuse.c"
md() { echo $1 | md5sum | cut -c1-12; }

# ---------------- 1. host32
H=$W/build_host32_cmsis_nn_int8only
[ -d $H ] || { echo "missing $H (run tools/stm32_memory/build_host32.sh with KERNELS=cmsis_nn VARIANT=_int8only)"; exit 1; }
EXCL="$(md $R/tools/stm32_memory/tflm_mem_driver.cc)"
TF_OBJS=$(ls $H/*.o | grep -v "$EXCL")
HT="-target x86-linux-musl"
HCXX="$HT -std=c++17 -O2 -fno-exceptions -fno-rtti -fno-threadsafe-statics -DTF_LITE_STATIC_MEMORY -DCMSIS_NN -DTF_LITE_DISABLE_X86_NEON -Wall -Wextra -Werror -Wno-unused-parameter"
$ZIG c++ $HCXX $INC_TFLM $INC_FW -Wno-error -Wno-everything -c $F/vision/fv_vision.cc -o $OUT/host32/fv_vision.o
ho=()
for s in $APP_C $F/vision/fv_debug_log.c $F/tests/fv_platform_host.c $F/tests/fv_vision_host_main.c $OUT/fv_model_data.c; do
  o=$OUT/host32/$(basename $s).o; $ZIG cc $HT -std=c99 -O2 -Wall -Wextra -Werror $INC_FW -c $s -o $o; ho+=($o); done
$ZIG c++ $HT -static -o $OUT/host32/fv_vision_host $OUT/host32/fv_vision.o "${ho[@]}" $TF_OBJS
echo "BUILT $OUT/host32/fv_vision_host"

# ---------------- 2. cm4 full link with the firmware linker script
C=$W/build_cm4_int8only
EXCL2="$(md $R/tools/stm32_memory/cm4_size_main.cc)|$(md $C/model_data.cc)"
TF_OBJS_CM4=$(ls $C/*.o | grep -vE "$EXCL2|zz_stubs")
CT="-target thumb-linux-musleabihf -mcpu=cortex_m4 -mfloat-abi=hard -fno-pic -fno-pie"
CCF="$CT -Os -ffunction-sections -fdata-sections -std=c99 -Wall -Wextra -Werror -Wdouble-promotion"
CXXF="$CT -Os -ffunction-sections -fdata-sections -std=c++17 -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-unwind-tables -fno-asynchronous-unwind-tables -DCMSIS_NN -DTF_LITE_STATIC_MEMORY -DTF_LITE_STRIP_ERROR_STRINGS -Wno-everything"
$ZIG c++ $CXXF $INC_TFLM $INC_FW -c $F/vision/fv_vision.cc -o $OUT/cm4/fv_vision.o
co=($OUT/cm4/fv_vision.o)
for s in $APP_C $F/vision/fv_debug_log.c $F/app/main.c $F/app/fv_diag.c $F/platform/fv_platform_stm32_pending.c $F/startup/fv_startup.c $OUT/fv_model_data.c; do
  o=$OUT/cm4/$(basename $s).o; $ZIG cc $CCF $INC_FW -c $s -o $o; co+=($o); done
# labelled link-check stubs (NOT newlib): snprintf/strncpy + the 5 libc symbols TFLM needs
$ZIG cc $CT -Os -c $F/tests/fw_link_stubs.c -o $OUT/cm4/zz_fw_stubs.o
$ZIG cc $CT -Os -c $R/tools/stm32_memory/cm4_libc_stubs.c -o $OUT/cm4/zz_libc_stubs.o
LNK="-target thumb-freestanding-eabihf -mcpu=cortex_m4 -mfloat-abi=hard -nostdlib -Wl,--gc-sections -Wl,-e,Reset_Handler -T $F/linker/STM32F407VETX_FV.ld"
$ZIG c++ $LNK -o $OUT/cm4/fv_fw_linkcheck.elf "${co[@]}" $TF_OBJS_CM4 $OUT/cm4/zz_fw_stubs.o $OUT/cm4/zz_libc_stubs.o
echo "LINKED $OUT/cm4/fv_fw_linkcheck.elf"
