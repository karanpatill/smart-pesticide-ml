"""Live OV2640 tuning on fv_app_v8_diag over SWD hot-plug: writes ONLY the g_fv_cam_tune RAM block (never flash), waits
for the firmware to acknowledge, lets auto-exposure/AWB settle, then takes one validated capture with read_capture.py.
Default = DRY RUN. Usage:
    python tools/firmware/cam_tune.py --lenc 1 --awb 1 --sat 0 --ae 0 [--settle 8] [--execute]
Settings (index 0 = ENTC original): lenc 0/1 | awb 0 ENTC,1 auto,2 sunny,3 cloudy,4 office,5 home | sat 0 ENTC,1..5 = -2..+2 |
ae 0 ENTC,1..5 = -2..+2."""
import argparse
import json
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import read_selftest as rs  # noqa: E402

MAGIC = 0x54554E45
SIZE = 52
RANGES = {"lenc": 2, "awb": 6, "sat": 6, "ae": 6}
OFF = {"magic": 0, "req": 4, "ack": 8, "status": 12, "applied_ms": 16, "lenc": 20, "awb": 24, "sat": 28, "ae": 32, "applied": 36}
STATUS = {0: "OK", -1: "ERR_RANGE (rejected, nothing written)", -2: "ERR_BUS (SCCB NACK / camera absent)"}


def conn(freq=4000):
    return [rs.CLI, "-c", "port=SWD", f"freq={freq}", "mode=HOTPLUG"]


def read_block(addr):
    r = subprocess.run(conn() + ["-r32", hex(addr), str(SIZE)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise SystemExit(r.stdout + r.stderr)
    b = rs.parse_r32(r.stdout, addr, SIZE)
    w = struct.unpack("<IIIiIIIII4I", b)
    return {"magic": w[0], "req": w[1], "ack": w[2], "status": w[3], "applied_ms": w[4],
            "set": dict(zip(RANGES, w[5:9])), "applied": dict(zip(RANGES, w[9:13]))}


def write_cmd(addr, settings, req):
    """Settings words first, then magic, then req LAST (the firmware acts only when req != ack). RAM block only."""
    cmd = conn()
    for k in RANGES:
        cmd += ["-w32", hex(addr + OFF[k]), hex(settings[k])]
    cmd += ["-w32", hex(addr + OFF["magic"]), hex(MAGIC), "-w32", hex(addr + OFF["req"]), hex(req)]
    return cmd


def check_writes_confined(cmd, addr):
    allowed = {"-c", "port=SWD", "mode=HOTPLUG", "-w32"}
    for i, c in enumerate(cmd[1:], 1):
        if c.startswith("-") and c not in allowed:
            raise SystemExit(f"refusing: option {c} not allowed")
        if c == "-w32":
            a = int(cmd[i + 1], 16)
            if not addr <= a < addr + OFF["applied"] or a % 4:
                raise SystemExit(f"refusing: write to {cmd[i + 1]} outside g_fv_cam_tune PC fields")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ROOT / "reports/firmware/gcc/fv_app_v8_diag.elf"))
    for k, n in RANGES.items():
        ap.add_argument(f"--{k}", type=int, default=0, choices=range(n))
    ap.add_argument("--settle", type=float, default=8.0, help="seconds to wait after the ack (AEC/AWB settling, >= 2 cycles)")
    ap.add_argument("--label", default="tune")
    ap.add_argument("--execute", action="store_true")
    a = ap.parse_args()
    addr, size = rs.symbol(a.elf, "g_fv_cam_tune")
    assert size == SIZE, f"g_fv_cam_tune size {size} != {SIZE}"
    settings = {k: getattr(a, k) for k in RANGES}
    tag = "_".join(f"{k}{v}" for k, v in settings.items())
    if not a.execute:
        cmd = write_cmd(addr, settings, 1)
        check_writes_confined(cmd, addr)
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        print(f"DRY RUN: RAM-only writes inside g_fv_cam_tune @ {addr:#x} ({SIZE} B); then read_capture --label {a.label}_{tag}")
        return 0
    before = read_block(addr)
    req = (max(before["req"], before["ack"]) + 1) & 0xFFFFFFFF
    cmd = write_cmd(addr, settings, req)
    check_writes_confined(cmd, addr)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(r.stdout + r.stderr); return 2
    t0 = time.time()
    while True:
        blk = read_block(addr)
        if blk["ack"] == req:
            break
        if time.time() - t0 > 15:
            print(json.dumps({"error": "no ack within 15 s", "block": blk})); return 2
        time.sleep(1.0)
    print(json.dumps({"request": req, "status": STATUS.get(blk["status"], blk["status"]), "applied": blk["applied"],
                      "applied_ms": blk["applied_ms"]}))
    if blk["status"] != 0:
        return 1
    time.sleep(a.settle)
    r = subprocess.run([sys.executable, str(ROOT / "tools/firmware/read_capture.py"), "--elf", a.elf, "--label",
                        f"{a.label}_{tag}", "--attempts", "5", "--execute"], capture_output=True, text=True, timeout=600)
    out = r.stdout[r.stdout.index("{"):] if "{" in r.stdout else ""
    if not out:
        print(r.stdout + r.stderr); return 2
    rep = json.loads(out)
    after = rep.get("cycle_ms", 0) > blk["applied_ms"]
    rep["captured_after_apply"] = after
    print(json.dumps({k: rep.get(k) for k in ("stable_complete_read", "captured_after_apply", "detail", "fruit_present",
                                              "device_fruit_probs", "python_equals_device_bit_exact", "input_mean_rgb", "saved_to")}))
    return 0 if r.returncode == 0 and after else 1


if __name__ == "__main__":
    sys.exit(main())
