#!/usr/bin/env bash
# Fetch TFLite-Micro + dependencies into ~/tflm_work (outside the repo). Pins: TFLM commit is
# recorded; dependency versions are read from TFLM's own download scripts.
set -euo pipefail
W=~/tflm_work; mkdir -p $W; cd $W
python3 -m pip install --user --break-system-packages -q ziglang==0.13.0
[ -d tflite-micro ] || git clone -q --depth 1 https://github.com/tensorflow/tflite-micro.git
cd tflite-micro; echo "TFLM_COMMIT $(git rev-parse HEAD) $(git log -1 --format=%cs)"; cd ..
grep -hE "^(FLATBUFFERS|GEMMLOWP|CMSIS_NN)?.*(URL|ZIP_PREFIX|_MD5|COMMIT)=" \
  tflite-micro/tensorflow/lite/micro/tools/make/flatbuffers_download.sh \
  tflite-micro/tensorflow/lite/micro/tools/make/third_party_downloads.inc \
  tflite-micro/tensorflow/lite/micro/tools/make/ext_libs/cmsis_nn_download.sh 2>/dev/null | head -20
