cd ~/tflm_work/downloads/cmsis_nn/Source
for f in ConvolutionFunctions/arm_convolve_get_buffer_sizes_s8.c ConvolutionFunctions/arm_depthwise_conv_get_buffer_sizes_s8.c FullyConnectedFunctions/arm_fully_connected_get_buffer_sizes_s8.c; do
  echo "=== $f"; [ -f $f ] && grep -nE "ARM_MATH_DSP|ARM_MATH_MVEI|return|int32_t arm_|#if|#else|#endif" $f | head -40
done
