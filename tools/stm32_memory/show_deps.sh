cd ~/tflm_work/tflite-micro/tensorflow/lite/micro/tools/make
grep -nE "ZIP_PREFIX_NN=|CMSIS_NN_MD5" ext_libs/cmsis_nn_download.sh
grep -nE "ZIP_PREFIX=|FLATBUFFERS_URL=|FLATBUFFERS_MD5=|DOWNLOADED_FLATBUFFERS_PATH" flatbuffers_download.sh | head
grep -nE "GEMMLOWP_URL|GEMMLOWP_MD5|RUY_URL" third_party_downloads.inc
ls ~/.local/bin | grep -i zig || python3 -m ziglang version
