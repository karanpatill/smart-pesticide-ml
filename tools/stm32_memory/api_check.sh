cd ~/tflm_work/tflite-micro/tensorflow/lite/micro
echo "== recording_micro_allocator.h Create"; grep -nE "static RecordingMicroAllocator\* Create|uint8_t\*" recording_micro_allocator.h
echo "== micro_interpreter.h ctors"; grep -nE "^  MicroInterpreter\(|MicroAllocator\* allocator|arena_used_bytes|const Model\* model" micro_interpreter.h | head
echo "== debug_log.h"; grep -nE "void DebugLog|DebugVsnprintf" debug_log.h
echo "== debug_log.cc includes"; grep -nE "#include|#if" debug_log.cc | head
echo "== common.cc"; find .. -path "*c/common.c*" | head; ls ../core/c 2>/dev/null
