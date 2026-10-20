#!/usr/bin/env bash
# Split arenas (53120 persistent / 96000 non-persistent) vs ONE single arena (149104): outputs must be
# byte-identical on all 20 real test inputs (32-bit host, CMSIS-NN int8-only kernels).
set -uo pipefail
R=/mnt/d/smart-pesticide-ml; M=$R/models/experimental/tflite/combined_int8.tflite
B=~/tflm_work/build_host32_cmsis_nn_int8only/tflm_mem_driver
same=0; n=0
for f in $R/reports/stm32_memory/test_inputs/in*.int8; do
  a=$($B $M $f single 149104 2>/dev/null | grep -E "^OUT|STATUS"); b=$($B $M $f split 53120 96000 2>/dev/null | grep -E "^OUT|STATUS")
  n=$((n+1)); [ "$a" = "$b" ] && [ -n "$a" ] && same=$((same+1))
done
echo "SPLIT_VS_SINGLE identical_outputs=$same/$n"
