cd ~/tflm_work/tflite-micro/tensorflow/lite/micro/kernels
grep -hoE "TFLMRegistration Register_[A-Z0-9_]+INT8\(\)" conv.h depthwise_conv.h fully_connected.h softmax.h add.h mul.h reduce.h 2>/dev/null | sort -u
grep -nE "Register_(CONV_2D|DEPTHWISE_CONV_2D|FULLY_CONNECTED|SOFTMAX|ADD|MUL)_INT8" cmsis_nn/*.cc | head -20
