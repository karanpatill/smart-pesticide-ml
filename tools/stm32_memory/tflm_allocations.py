"""HOST (WSL x86_64) TFLite-Micro allocation breakdown for a .tflite model, using TFLM's
RecordingMicroAllocator (print_allocations). Reference kernels, 64-bit pointers: this is NOT
an STM32 measurement. Usage: python3 tflm_allocations.py MODEL ARENA_BYTES INPUTS_NPZ"""
import sys
import numpy as np
from tflite_micro.python.tflite_micro import runtime
model, arena, npz = sys.argv[1], int(sys.argv[2]), sys.argv[3]
it = runtime.Interpreter.from_file(model, arena_size=arena)
x = np.load(npz)["x"]
it.set_input(x[0:1], 0)
it.invoke()
print("input details:", it.get_input_details(0))
for j in range(8):
    print("output", j, it.get_output_details(j))
it.print_allocations()
