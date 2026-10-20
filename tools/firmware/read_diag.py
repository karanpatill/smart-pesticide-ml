"""READ-ONLY readback of g_fv_diag (application diagnostics block) from the running board over SWD.

Runs exactly: STM32_Programmer_CLI -c port=SWD freq=1000 mode=HOTPLUG -r32 <addr> <size>  (memory read only; no
flash, erase, reset, halt or option-byte change). Address/size come from the application ELF that is on the board.
Default = DRY RUN (prints the command). Use --execute to read, or --dump FILE to decode a saved CLI output offline.
Usage: python tools/firmware/read_diag.py [--elf reports/firmware/gcc/fv_app.elf] [--execute | --dump FILE]
"""
import argparse
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import read_selftest as rs  # noqa: E402  (ELF symbol lookup + -r32 parser)

MAGIC = 0xF1D1A600
FIELDS_I32 = ["magic", "version", "uptime_ms", "cycles", "clock_status", "oled_status", "tcs_status", "cam_status",
              "cam_probe_status", "cam_pid", "cam_ver", "cam_pclk_div", "cam_table_fail_index", "last_cycle_status",
              "last_camera_status", "last_sensor_status", "last_capture_status", "last_capture_bytes", "last_image_flags",
              "fruit", "fruit_conf_pm", "condition", "condition_conf_pm", "quality_state", "grade", "shelf_state",
              "consistency", "risk_state", "risk_reasons", "sensor_errors", "sensor_warnings", "tcs_c", "tcs_r", "tcs_g",
              "tcs_b", "dht_status", "temp_c_x10", "rh_x10", "adc_ch_a_raw", "adc_ch_b_raw", "vision_arena_used"]
FIELDS_V2 = ["ph_x100", "ph_mv", "mq135_raw", "mq135_warmed"]   # diag version 2 (pH = ENTC calibration)
FIELDS_V3 = ["img_detail_x10", "fruit_present"]                  # diag version 3 (presence gate, fv_app_v5)
SIZE = 4 * len(FIELDS_I32) + 256          # v1 = 420 B (fv_app.elf)
SIZE_V2 = SIZE + 4 * len(FIELDS_V2)       # v2 = 436 B (fv_app_v2..v4)
SIZE_V3 = SIZE_V2 + 4 * len(FIELDS_V3)    # v3 = 444 B (fv_app_v5)


def decode(b: bytes) -> dict:
    f = FIELDS_I32 if len(b) == SIZE else FIELDS_I32 + FIELDS_V2 if len(b) == SIZE_V2 else FIELDS_I32 + FIELDS_V2 + FIELDS_V3
    vals = struct.unpack_from(f"<{len(f)}i", b, 0)
    d = dict(zip(f, vals))
    d["magic"] = hex(d["magic"] & 0xFFFFFFFF)
    d["valid"] = d["magic"] == hex(MAGIC)
    d["serial_line"] = b[4 * len(f):4 * len(f) + 256].split(b"\0")[0].decode("ascii", "replace").strip()
    if "ph_x100" in d:
        d["ph_entc_calibration"] = None if d["ph_x100"] < 0 else d["ph_x100"] / 100.0
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ROOT / "reports/firmware/gcc/fv_app.elf"))
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--dump")
    a = ap.parse_args()
    addr, size = rs.symbol(a.elf, "g_fv_diag")
    assert size in (SIZE, SIZE_V2, SIZE_V3), f"g_fv_diag size {size} not in ({SIZE}, {SIZE_V2}, {SIZE_V3}): reader out of date"
    cmd = [rs.CLI, "-c", "port=SWD", "freq=1000", "mode=HOTPLUG", "-r32", hex(addr), str(size)]
    if a.dump:
        text = pathlib.Path(a.dump).read_text()
    elif not a.execute:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        print("DRY RUN: read-only hot-plug memory read; nothing executed (add --execute).")
        return 0
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        text = r.stdout + r.stderr
        if r.returncode != 0:
            print(text); return 2
    d = decode(rs.parse_r32(text, addr, size))
    print(json.dumps(d, indent=1))
    return 0 if d["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
