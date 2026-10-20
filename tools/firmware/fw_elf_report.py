"""Placement + size report for a firmware link-check ELF (pyelftools). Verifies the memory rules of
firmware/stm32f407/linker/STM32F407VETX_FV.ld on the LINKED image. Usage: fw_elf_report.py ELF OUT.json"""
import json, pathlib, sys
from elftools.elf.elffile import ELFFile

REGIONS = {"FLASH": (0x08000000, 512 * 1024), "RAM": (0x20000000, 128 * 1024), "CCMRAM": (0x10000000, 64 * 1024)}


def region(addr):
    for n, (o, l) in REGIONS.items():
        if o <= addr < o + l:
            return n
    return None


def category(name):
    if name.startswith("g_fv_model_data"): return "model_weights"
    if name.startswith(("g_arena", "g_cycle")): return "app_buffers"
    if name.startswith("arm_") or name.startswith("arm"): return "cmsis_nn"
    if name.startswith(("_ZN6tflite", "_ZNK6tflite", "_ZN11flatbuffers", "_ZNK11flatbuffers", "_ZN12_GLOBAL__N", "tflite", "TfLite",
                        "MicroPrintf", "DebugLog", "DebugVsnprintf", "_Z")):
        return "tflm_runtime_kernels"
    if name.startswith(("fv_vision", "fv_debug")): return "fv_vision_glue"
    if name.startswith("m2_"): return "model2_c"
    if name.startswith(("fv_rgb565", "fv_select")): return "preprocess_and_arena_reuse"
    if name.startswith(("fv_", "main", "run_image", "s_", "put", "permille", "argmax", "range_check", "QUALITY_HEAD", "STAGE_HEAD", "GRADE", "STAGE", "RISK")):
        return "fv_app"
    if name in ("g_vectors", "Reset_Handler", "Default_Handler") or name.endswith("_Handler"): return "startup"
    if name in ("snprintf", "strncpy", "strcmp", "strncmp", "frexp", "abort", "__cxa_atexit"): return "libc_string_printf (newlib in GCC build, stubs in lld check)"
    return "compiler_rt_libm_other"


def main(elf_path, out_path):
    e = ELFFile(open(elf_path, "rb"))
    secs = []
    for s in e.iter_sections():
        if s["sh_flags"] & 0x2 and s["sh_size"]:   # SHF_ALLOC
            lma = s["sh_addr"]
            for seg in e.iter_segments():
                if seg["p_type"] == "PT_LOAD" and seg["p_vaddr"] <= s["sh_addr"] < seg["p_vaddr"] + max(seg["p_memsz"], 1):
                    lma = seg["p_paddr"] + (s["sh_addr"] - seg["p_vaddr"])
            secs.append({"name": s.name, "vma": s["sh_addr"], "lma": lma, "size": s["sh_size"],
                         "nobits": s["sh_type"] == "SHT_NOBITS", "region": region(s["sh_addr"]),
                         "load_region": region(lma)})
    sym = {}
    cats = {}
    for s in e.get_section_by_name(".symtab").iter_symbols():
        if s["st_size"] and s["st_info"]["type"] in ("STT_FUNC", "STT_OBJECT"):
            sym.setdefault(s.name, (s["st_value"], s["st_size"]))
            r = region(s["st_value"] & ~1)
            c = cats.setdefault(category(s.name), {"FLASH": 0, "RAM": 0, "CCMRAM": 0})
            if r: c[r] += s["st_size"]
    flash_used = sum(x["size"] for x in secs if not x["nobits"] and x["load_region"] == "FLASH")
    ram_used = sum(x["size"] for x in secs if x["region"] == "RAM")
    ccm_used = sum(x["size"] for x in secs if x["region"] == "CCMRAM")
    symv = lambda n: sym.get(n, (None, None))
    checks = {}
    pa, ps = symv("g_arena_persistent"); na, ns = symv("g_arena_nonpersistent"); ma, ms = symv("g_fv_model_data")
    checks["persistent_arena_in_CCM"] = region(pa) == "CCMRAM" if pa is not None else False
    checks["nonpersistent_arena_in_SRAM"] = region(na) == "RAM" if na is not None else False
    checks["nonpersistent_arena_16B_aligned"] = na is not None and na % 16 == 0
    checks["persistent_arena_16B_aligned"] = pa is not None and pa % 16 == 0
    checks["model_in_flash_16B_aligned"] = ma is not None and region(ma) == "FLASH" and ma % 16 == 0
    dma = [x for x in secs if x["name"].startswith(".dma_buffers")]
    checks["dma_buffers_not_in_CCM"] = all(x["region"] == "RAM" for x in dma)
    ccm_secs = [x["name"] for x in secs if x["region"] == "CCMRAM"]
    checks["only_ccm_arena_in_CCM"] = ccm_secs == [".ccm_arena"]
    # overlap check of all allocated sections (by VMA)
    iv = sorted((x["vma"], x["vma"] + x["size"], x["name"]) for x in secs)
    checks["no_section_overlap"] = all(a[1] <= b[0] for a, b in zip(iv, iv[1:]))
    checks["no_section_spans_regions"] = all(region(x["vma"]) == region(x["vma"] + x["size"] - 1) for x in secs)
    stk = next((x for x in secs if x["name"] == "._stack"), None)
    checks["stack_reserve_in_RAM_top_free"] = bool(stk) and stk["vma"] + stk["size"] <= 0x20020000
    checks["flash_within_512K"] = flash_used <= REGIONS["FLASH"][1]
    checks["ram_within_128K"] = ram_used <= REGIONS["RAM"][1]
    checks["ccm_within_64K"] = ccm_used <= REGIONS["CCMRAM"][1]
    rep = {"elf": str(elf_path),
           "WARNING": ("zig/clang + lld link-check with labelled stubs (snprintf/strncpy/strcmp/strncmp/frexp/abort/"
                       "__cxa_atexit) and NO newlib, NO HAL, NO drivers. NOT a GCC/CubeIDE build, NOT flashable, NOT run on STM32."),
           "sections": [{**x, "vma": hex(x["vma"]), "lma": hex(x["lma"])} for x in secs],
           "totals": {"flash_used": flash_used, "flash_free": REGIONS["FLASH"][1] - flash_used,
                      "ram_used_incl_stack_reserve": ram_used, "ram_free": REGIONS["RAM"][1] - ram_used,
                      "ccm_used": ccm_used, "ccm_free": REGIONS["CCMRAM"][1] - ccm_used},
           "symbol_bytes_by_category": cats,
           "key_symbols": {n: {"addr": hex(symv(n)[0]) if symv(n)[0] is not None else None, "size": symv(n)[1]}
                           for n in ("g_fv_model_data", "g_arena_persistent", "g_arena_nonpersistent", "g_cycle", "g_vectors")},
           "checks": checks, "all_checks_pass": all(checks.values())}
    pathlib.Path(out_path).write_text(json.dumps(rep, indent=2))
    print(json.dumps({"totals": rep["totals"], "all_checks_pass": rep["all_checks_pass"],
                      "failed": [k for k, v in checks.items() if not v]}, indent=1))
    return 0 if rep["all_checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
