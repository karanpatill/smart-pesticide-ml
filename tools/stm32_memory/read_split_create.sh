cd ~/tflm_work/tflite-micro/tensorflow/lite/micro
n=$(grep -n "MicroAllocator\* MicroAllocator::Create(uint8_t\* persistent_tensor_arena" micro_allocator.cc | cut -d: -f1)
sed -n "$n,$((n+40))p" micro_allocator.cc
echo "=== where temp allocations go"
grep -nE "AllocateTemp|DeallocateTemp|ResetTempAllocations|IsAllAllocations|non_persistent_buffer_allocator_->|persistent_buffer_allocator_->" micro_allocator.cc | head -40
echo "=== AllocatePersistentBuffer users"; grep -rn "AllocatePersistentBuffer" kernels/cmsis_nn/conv.cc kernels/cmsis_nn/depthwise_conv.cc | head -5
echo "=== commit"; cd ../../..; git rev-parse --short HEAD
