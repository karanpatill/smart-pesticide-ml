"""Section and symbol size report for the size-measurement Cortex-M4 ELF (pyelftools).

Usage: python tools/stm32_memory/elf_size_report.py ELF [OUT.json]
Flash = .text + .rodata + .ARM.exidx/extab + .data (load image); RAM = .data + .bss (+ custom arena sections).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


def main() -> None:
    path = sys.argv[1]
    with open(path, "rb") as f:
        e = ELFFile(f)
        secs = {s.name: {"size": s["sh_size"], "flags": s["sh_flags"], "type": s["sh_type"]}
                for s in e.iter_sections() if s["sh_flags"] & 0x2}  # SHF_ALLOC
        hdr = {"machine": e["e_machine"], "class": e.elfclass, "flags": hex(e["e_flags"])}
        syms = []
        for s in e.iter_sections():
            if isinstance(s, SymbolTableSection):
                for y in s.iter_symbols():
                    if y["st_size"] and y["st_info"]["type"] in ("STT_FUNC", "STT_OBJECT"):
                        sec = e.get_section(y["st_shndx"]).name if isinstance(y["st_shndx"], int) else "?"
                        syms.append((y.name, y["st_size"], y["st_info"]["type"], sec))

    def bucket(name: str, typ: str) -> str:
        if name == "g_model_data":
            return "model_flatbuffer"
        if name in ("_ZL12g_persistent", "_ZL15g_nonpersistent") or "persistent" in name:
            return "tensor_arenas"
        if name.startswith("arm_"):
            return "cmsis_nn"
        if re.match(r"^_Z.*tflite|^_ZN6tflite|^_ZNK6tflite|flatbuffers|^_Z.*TfLite|^Tf", name):
            return "tflm_runtime"
        if name.startswith("__") or name in ("memcpy", "memset", "memmove"):
            return "compiler_rt_libc"
        return "other"

    by = defaultdict(lambda: {"code": 0, "data": 0})
    for n, sz, typ, sec in syms:
        by[bucket(n, typ)]["code" if typ == "STT_FUNC" else "data"] += sz
    flash_secs = [k for k in secs if k.startswith((".text", ".rodata", ".ARM", ".data", ".init_array"))]
    ram_secs = [k for k in secs if k.startswith((".data", ".bss", ".ccm"))]
    res = {"elf": path, "header": hdr,
           "allocated_sections": {k: v["size"] for k, v in sorted(secs.items())},
           "flash_bytes_total": sum(secs[k]["size"] for k in flash_secs),
           "ram_bytes_total_incl_arenas": sum(secs[k]["size"] for k in ram_secs),
           "symbol_buckets": dict(by),
           "largest_symbols": sorted(({"name": n, "size": sz, "type": t, "section": s} for n, sz, t, s in syms),
                                     key=lambda d: -d["size"])[:12]}
    out = json.dumps(res, indent=1)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(out)
    print(out)


if __name__ == "__main__":
    main()
