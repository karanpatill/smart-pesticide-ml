cd ~/tflm_work/tflite-micro/tensorflow/lite/micro/tools/make
sed -n '1,80p' download_dependencies.py | grep -nE "url|md5|sha|flatbuffers|gemmlowp|ruy|def |name" | head -30
grep -nE "flatbuffers|gemmlowp|ruy|kissfft" third_party_downloads.inc third_party.inc | head
