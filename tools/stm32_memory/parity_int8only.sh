#!/usr/bin/env bash
# Build host32 CMSIS-NN driver with default and INT8_ONLY registrations; compare outputs on 20 real
# test inputs (split arenas at the measured minima) and report tensor offsets in the non-persistent arena.
set -euo pipefail
R=/mnt/d/smart-pesticide-ml; S=$R/tools/stm32_memory; M=$R/models/experimental/tflite/combined_int8.tflite
bash $S/rebuild_driver.sh >/dev/null 2>&1 || true
KERNELS=cmsis_nn bash $S/rebuild_driver.sh | tail -1
KERNELS=cmsis_nn VARIANT=_int8only EXTRA_DEFS=-DINT8_ONLY bash $S/build_host32.sh | tail -1
A=~/tflm_work/build_host32_cmsis_nn/tflm_mem_driver; B=~/tflm_work/build_host32_cmsis_nn_int8only/tflm_mem_driver
same=0; n=0
for f in $R/reports/stm32_memory/test_inputs/in*.int8; do
  oa=$($A $M $f split 53120 96000 2>/dev/null | grep -E "^OUT|STATUS"); ob=$($B $M $f split 53120 96000 2>/dev/null | grep -E "^OUT|STATUS")
  n=$((n+1)); [ "$oa" = "$ob" ] && same=$((same+1))
done
echo "INT8_ONLY_PARITY identical_outputs=$same/$n"
echo "== offsets (cmsis_nn default, split 53120/96000)"; $A $M $R/reports/stm32_memory/test_input0.int8 split 53120 96000 2>/dev/null | grep -E "OFFSET|STATUS"
echo "== int8-only minima"; python3 $S/arena_search.py $B $M $R/reports/stm32_memory/test_input0.int8
