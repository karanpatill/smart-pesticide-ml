"""READ-ONLY readback of g_fv_capture (diagnostic build fv_app_v6_diag) over SWD hot-plug: the exact 80x80 model input the
STM32 used and its raw outputs. Saves the input as PNG + .int8 into a NEW folder and runs the SAME input through the Python
TFLite model to compare outputs bit-exactly (C vs Python on the same image).
Default = DRY RUN. Usage: python tools/firmware/read_capture.py [--label banana] [--execute] [--elf ...]"""
import argparse
import datetime as dt
import json
import pathlib
import re
import struct
import subprocess
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/firmware"))
import read_selftest as rs  # noqa: E402

MAGIC = 0xCA97F00D          # v6_diag rolling capture (seqlock: seq even = complete)
READY = 0x534E4150          # v7_diag write-once snapshot complete (never rewritten until reset)
SIZE = 24 + 40 + 19200
FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]


def decode(b: bytes) -> dict:
    magic, seq, ms, det, flags, present = struct.unpack_from("<IIIiIi", b, 0)
    raw = list(struct.unpack_from("<40b", b, 24))
    inp = np.frombuffer(b[64:64 + 19200], np.int8)
    return {"magic": magic, "magic_ok": magic in (MAGIC, READY), "snapshot": magic == READY, "seq": seq, "cycle_ms": ms, "detail": det / 10.0, "image_flags": flags,
            "fruit_present": present, "raw": raw, "input": inp}


def split_reads(text: str, addr: int) -> list:
    """Split one CLI session's stdout into one text per -r32 command (each read restarts at addr)."""
    segs = []
    for m in re.finditer(r"0x([0-9A-Fa-f]{8})\s*:\s*((?:[0-9A-Fa-f]{8}\s*)+)", text):
        if int(m.group(1), 16) == addr or not segs:
            segs.append([])
        segs[-1].append(m.group(0))
    return ["\n".join(s) for s in segs]


def python_raw(inp: np.ndarray) -> list:
    import re
    import tensorflow as tf
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    d, outs = it.get_input_details()[0], it.get_output_details()
    it.set_tensor(d["index"], inp.reshape(d["shape"]))
    it.invoke()
    hdr = (ROOT / "firmware/stm32f407/generated/fv_generated_config.h").read_text()
    idx = [int(v) for v in re.search(r"FV_HEAD_OUTPUT_INDEX\[\w*\]\s*=\s*\{([^}]*)\}", hdr).group(1).split(",")]
    n = [5, 2, 3, 3, 2, 3, 3, 3]
    flat = []
    for h in range(8):
        v = [int(a) for a in it.get_tensor(outs[idx[h]]["index"]).reshape(-1)]
        flat += v + [0] * (5 - n[h])
    return flat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=str(ROOT / "reports/firmware/gcc/fv_app_v7_diag.elf"))
    ap.add_argument("--label", default="unlabelled", help="what is physically in front of the camera (for the record)")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--attempts", type=int, default=1, help="read-only reads until one is stable (max 10); each validated")
    ap.add_argument("--dump", nargs=2, metavar=("DUMP_A", "DUMP_B"), help="decode two saved -r32 outputs (tests)")
    a = ap.parse_args()
    addr, size = rs.symbol(a.elf, "g_fv_capture")
    assert size == SIZE, f"g_fv_capture size {size} != {SIZE}"
    # One CLI session: full block, then the 8-byte header again right after.
    # v7 snapshot: stable iff READY in both and seq unchanged (block is write-once). v6: stable iff seq even and unchanged.
    cmd = [rs.CLI, "-c", "port=SWD", "freq=4000", "mode=HOTPLUG", "-r32", hex(addr), str(size), "-r32", hex(addr), "8"]
    if a.dump:
        texts = [pathlib.Path(p).read_text() for p in a.dump]
        c1, c2 = (decode(rs.parse_r32(t, addr, size)) for t in texts)
        same = c1["seq"] == c2["seq"] and np.array_equal(c1["input"], c2["input"]) and c1["raw"] == c2["raw"]
        stable = same and (c1["snapshot"] and c2["snapshot"] or c1["magic"] == MAGIC and c1["seq"] % 2 == 0)
    elif not a.execute:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        print("DRY RUN: read-only hot-plug memory read (block + header re-read in one session); nothing executed (add --execute).")
        return 0
    else:
        for attempt in range(1, min(max(a.attempts, 1), 10) + 1):
            if attempt > 1:
                time.sleep(1.0)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                print(r.stdout + r.stderr); return 2
            segs = split_reads(r.stdout, addr)
            if len(segs) != 2:
                print(f"expected 2 reads in CLI output, got {len(segs)}"); return 2
            c1 = decode(rs.parse_r32(segs[0], addr, size))
            magic_after, seq_after = struct.unpack_from("<II", rs.parse_r32(segs[1], addr, 8), 0)
            if c1["snapshot"]:
                stable = magic_after == READY and seq_after == c1["seq"]
            else:
                stable = c1["magic"] == MAGIC and c1["seq"] % 2 == 0 and seq_after == c1["seq"]
            print(f"attempt {attempt}: magic={c1['magic']:#010x} seq in block={c1['seq']} "
                  f"re-read after block: magic={magic_after:#010x} seq={seq_after} -> {'STABLE' if stable else 'rejected'}")
            if c1["magic"] == 0:
                print("snapshot NOT READY yet (first inference cycles after reset); nothing saved"); return 3
            if stable:
                break
    rep = {"label_given_by_user": a.label, "magic_ok": c1["magic_ok"], "write_once_snapshot": c1["snapshot"],
           "stable_complete_read": bool(stable), "seq": c1["seq"], "cycle_ms": c1["cycle_ms"],
           "detail": c1["detail"], "image_flags": c1["image_flags"], "fruit_present": c1["fruit_present"]}
    dev = c1["raw"][:5]
    rep["device_fruit_probs"] = {f: round((v + 128) / 256, 4) for f, v in zip(FRUITS, dev)}
    rep["device_fruit"] = FRUITS[int(np.argmax(dev))]
    if stable and c1["magic_ok"]:
        py = python_raw(c1["input"])
        rep["python_equals_device_bit_exact"] = py == c1["raw"]
        rep["python_fruit"] = FRUITS[int(np.argmax(py[:5]))]
        rgb = (c1["input"].astype(np.int16) + 128).astype(np.uint8).reshape(80, 80, 3)
        rep["input_mean_rgb"] = [round(float(rgb[..., k].mean()), 1) for k in range(3)]
        if not a.dump:
            out = ROOT / "reports/firmware/device_capture" / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{a.label}")
            out.mkdir(parents=True)
            from PIL import Image
            Image.fromarray(rgb).resize((320, 320), Image.NEAREST).save(out / "model_input_x4.png")
            (out / "model_input.int8").write_bytes(c1["input"].tobytes())
            (out / "result.json").write_text(json.dumps(rep, indent=1))
            rep["saved_to"] = str(out)
    print(json.dumps(rep, indent=1))
    return 0 if stable else 1


if __name__ == "__main__":
    sys.exit(main())
