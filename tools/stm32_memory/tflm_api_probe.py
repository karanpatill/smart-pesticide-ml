"""Lists the TFLite-Micro Python runtime API available in this environment (WSL)."""
import inspect, os
import tflite_micro
from tflite_micro.python.tflite_micro import runtime
pkg = os.path.dirname(tflite_micro.__file__)
print("package:", pkg)
print("Interpreter methods:", [m for m in dir(runtime.Interpreter) if not m.startswith("__")])
for name in ("from_file", "from_bytes", "__init__"):
    try:
        print(name, inspect.signature(getattr(runtime.Interpreter, name)))
    except (TypeError, ValueError, AttributeError) as e:
        print(name, "?", e)
print(sorted(os.listdir(os.path.join(pkg, "python", "tflite_micro"))))
