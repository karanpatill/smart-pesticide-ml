cd ~/tflm_work/tflite-micro
echo "== micro top-level"; ls tensorflow/lite/micro/*.cc | grep -v _test | xargs -n1 basename | tr '\n' ' '; echo
for d in arena_allocator memory_planner tflite_bridge; do echo "== $d"; ls tensorflow/lite/micro/$d/*.cc 2>/dev/null | grep -v _test | xargs -n1 basename | tr '\n' ' '; echo; done
echo "== kernels (relevant)"; ls tensorflow/lite/micro/kernels/*.cc | grep -v _test | xargs -n1 basename | grep -E "^(add|conv|depthwise|fully|reduce|mul|softmax|kernel_util|micro_tensor|quantize|dequantize)" | tr '\n' ' '; echo
echo "== cmsis_nn kernels"; ls tensorflow/lite/micro/kernels/cmsis_nn/ | tr '\n' ' '; echo
echo "== other api dirs"; find . -path ./tensorflow/lite/micro -prune -o -name "*.cc" -path "*api*" -print | grep -v test | head; find . -name "flatbuffer_conversions.cc" -o -name "common.cc" -path "*lite/c*" -o -name "quantization_util.cc" -o -name "tensor_ctypes.cc" -o -name "portable_tensor_utils.cc" -o -name "runtime_shape.cc" | grep -v test | head -20
echo "== debug_log"; find tensorflow/lite/micro -name "debug_log.cc" -o -name "micro_time.cc" -o -name "system_setup.cc" | head
