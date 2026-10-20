# Force recompilation of the driver object only (sources hashed by path), then relink.
K=${KERNELS:-reference}; O=~/tflm_work/build_host32_$K
rm -f $O/$(echo /mnt/d/smart-pesticide-ml/tools/stm32_memory/tflm_mem_driver.cc | md5sum | cut -c1-12).o
KERNELS=$K bash /mnt/d/smart-pesticide-ml/tools/stm32_memory/build_host32.sh | tail -1
