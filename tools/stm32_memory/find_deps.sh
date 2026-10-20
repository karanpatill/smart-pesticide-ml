cd ~/tflm_work/tflite-micro
ls tensorflow/lite/micro/tools/make/ | grep -iE "download|\.inc" 
grep -rlE "flatbuffers/flatbuffers.h|fixedpoint/fixedpoint.h" tensorflow/lite/micro tensorflow/lite/kernels tensorflow/lite/core tensorflow/compiler 2>/dev/null | head -5
grep -rhoE '"fixedpoint/[a-z_]+\.h"' tensorflow/lite/kernels tensorflow/lite/micro | sort -u
grep -nE "flatbuffers|gemmlowp" tensorflow/lite/micro/tools/make/Makefile | head -12
ls third_party 2>/dev/null | head
