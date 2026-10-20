"""READ-ONLY readback of g_fv_selftest from the running board over SWD (STM32CubeProgrammer CLI).

Runs exactly: STM32_Programmer_CLI -c port=SWD freq=100 mode=HOTPLUG -r32 <addr> <size>
(hot-plug attach, memory read only: no flash, erase, reset or option-byte change).
The address/size come from the self-test ELF that was flashed. Compares against
reports/firmware/selftest_expected.json and writes reports/firmware/selftest_target_readback.json.

Usage: python tools/firmware/read_selftest.py [--elf reports/firmware/gcc/fv_selftest.elf] [--dump FILE]
--dump parses a saved CLI output instead of talking to the board (for tests)."""
import argparse
import json
import pathlib
import re
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
SIZE = 288            # v1 layout (the image flashed and verified on 2026-10-17)
SIZE_V2 = 372         # v2: + offline 160x120 frame stage (fv_selftest_frame.elf)
MAGIC_DONE, MAGIC_RUNNING = 0xF7A51E57, 0x52554E21


def symbol(elf, name):
    from elftools.elf.elffile import ELFFile
    with open(elf, "rb") as f:
        for s in ELFFile(f).get_section_by_name(".symtab").iter_symbols():
            if s.name == name:
                return s["st_value"], s["st_size"]
    raise SystemExit(f"{name} not in {elf}")


def parse_r32(text, addr, size):
    words = {}
    for m in re.finditer(r"0x([0-9A-Fa-f]{8})\s*:\s*((?:[0-9A-Fa-f]{8}\s*)+)", text):
        a = int(m.group(1), 16)
        for i, w in enumerate(m.group(2).split()):
            words[a + 4 * i] = int(w, 16)
    b = b"".join(struct.pack("<I", words[addr + o]) for o in range(0, size, 4) if addr + o in words)
    if len(b) != size:
        raise SystemExit(f"readback incomplete: got {len(b)} of {size} bytes")
    return b


def decode(b):
    u = lambda o: struct.unpack_from("<I", b, o)[0]
    i = lambda o: struct.unpack_from("<i", b, o)[0]
    f = lambda o: struct.unpack_from("<f", b, o)[0]
    d = {"magic": hex(u(0)), "done": u(0) == MAGIC_DONE, "version": u(4), "clock_status": i(8), "sysclk_source": u(12),
         "init_status": i(16), "arena_used_bytes": u(20), "n_inputs": u(24),
         "invoke_status": [i(28 + 4 * k) for k in range(3)], "invoke_cycles": [u(40 + 4 * k) for k in range(3)],
         "raw_mismatches": [u(52 + 4 * k) for k in range(3)], "max_abs_diff": i(64),
         "image_flags": [u(68 + 4 * k) for k in range(3)], "fruit": [i(80 + 4 * k) for k in range(3)],
         "quality_state": [i(92 + 4 * k) for k in range(3)], "grade": [i(104 + 4 * k) for k in range(3)],
         "consistency": [u(116 + 4 * k) for k in range(3)], "result_mismatches": u(128), "m2_status": i(132),
         "m2_class": i(136), "m2_probs": [f(140 + 4 * k) for k in range(3)], "m2_ok": i(152),
         "stack_used_bytes": u(156), "pass": u(160),
         "raw": [list(struct.unpack_from("<40b", b, 164 + 40 * k)) for k in range(3)], "heartbeat_ms": u(284)}
    d["invoke_ms_at_168MHz"] = [round(c / 168e3, 2) for c in d["invoke_cycles"]]
    if len(b) >= SIZE_V2:
        d.update({"frame_present": u(288), "frame_pp_status": i(292), "frame_pp_cycles": u(296),
                  "frame_input_hash": hex(u(300)), "frame_input_hash_ok": u(304), "frame_image_flags": u(308),
                  "frame_invoke_status": i(312), "frame_invoke_cycles": u(316), "frame_raw_mismatches": u(320),
                  "frame_fruit": i(324), "frame_result_ok": u(328), "frame_raw": list(struct.unpack_from("<40b", b, 332))})
        d["frame_pp_ms_at_168MHz"] = round(d["frame_pp_cycles"] / 168e3, 2)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ROOT / "reports/firmware/gcc/fv_selftest.elf"))
    ap.add_argument("--dump")
    a = ap.parse_args()
    addr, size = symbol(a.elf, "g_fv_selftest")
    assert size in (SIZE, SIZE_V2), f"g_fv_selftest size {size} not in ({SIZE}, {SIZE_V2}) (reader layout out of date)"
    if a.dump:
        text = pathlib.Path(a.dump).read_text()
    else:
        cmd = [CLI, "-c", "port=SWD", "freq=100", "mode=HOTPLUG", "-r32", hex(addr), str(size)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        text = r.stdout + r.stderr
        (ROOT / "reports/firmware/selftest_target_readback_raw.txt").write_text(" ".join(cmd) + "\n" + text)
        if r.returncode != 0:
            print(text); return 2
    d = decode(parse_r32(text, addr, size))
    exp = json.loads((ROOT / "reports/firmware/selftest_expected.json").read_text())
    d["raw_equal_expected"] = [d["raw"][k] == exp["inputs"][k]["raw"] for k in range(3)]
    d["address"] = hex(addr)
    d["source"] = "dump file" if a.dump else "SWD hot-plug -r32 readback from the board"
    print(json.dumps({k: v for k, v in d.items() if k not in ("raw", "frame_raw")}, indent=1))
    if not a.dump:
        name = "selftest_target_readback.json" if size == SIZE else "selftest_frame_target_readback.json"
        (ROOT / "reports/firmware" / name).write_text(json.dumps(d, indent=1))
    return 0 if d["done"] and d["pass"] == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
