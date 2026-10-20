set -euo pipefail
K=${KERNELS:-reference}; B=~/tflm_work/build_host32_$K/tflm_mem_driver
R=/mnt/d/smart-pesticide-ml; M=$R/models/experimental/tflite/combined_int8.tflite; I=$R/reports/stm32_memory/test_input0.int8
file $B 2>/dev/null | cut -d, -f1-2 || true
$B $M $I recording 200000 2>&1
python3 $R/tools/stm32_memory/arena_search.py $B $M $I
