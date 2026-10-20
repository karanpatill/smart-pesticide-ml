set -euo pipefail
cd ~/tflm_work/tflite-micro
D=~/tflm_work/downloads; mkdir -p $D
python3 tensorflow/lite/micro/tools/make/download_dependencies.py --downloads_dir $D flatbuffers eyalroz_printf 2>&1 | tail -5
# CMSIS-NN pinned by tensorflow/lite/micro/tools/make/ext_libs/cmsis_nn_download.sh
NN=4ab83cc3cc98fb85ed6dafb55e8ca02f1628dcae
if [ ! -d $D/cmsis_nn ]; then
  curl -sSL -o $D/nn.zip https://github.com/ARM-software/CMSIS-NN/archive/$NN.zip
  echo "cmsis_nn md5: $(md5sum $D/nn.zip | cut -d' ' -f1) (expected c960031e7d10cf31c477fb34ef460106)"
  python3 -c "import zipfile;zipfile.ZipFile('$D/nn.zip').extractall('$D')" && mv $D/CMSIS-NN-$NN $D/cmsis_nn
fi
ls $D; ls $D/flatbuffers/include/flatbuffers | head -3; ls $D/cmsis_nn/Include | head
