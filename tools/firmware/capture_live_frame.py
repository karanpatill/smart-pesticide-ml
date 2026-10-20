"""READ-ONLY capture of the live OV2640 frame held in SRAM by the ENTC firmware (P1 of
docs/CAMERA_ML_INTEGRATION_PLAN.md). Default = DRY RUN: prints the plan and the exact command, connects to nothing.

Addresses (STATIC analysis of the ENTC backup, sha256 1590cd4e...; see docs/P1_LIVE_FRAME_READ_PLAN.md):
  0x2000A35C  8 B   u8 camera_ready, u8 VSPOL, u8 HSPOL, u8 (unknown), u32 last received byte count
  0x20000008 16 B   status: u8 frame_ok, u8 err, u8 meanR, u8 meanG, u8 meanB, u8 dark%, 2 B pad, u32 class result, 4 B extra
  0x2000055C 40448 B DCMI/DMA capture buffer; valid frame = first 38,400 B = 160x120 RGB565, high byte first, row-major

Execution (only with BOTH --execute and --i-confirm-read-only): ONE STM32_Programmer_CLI call in hot-plug mode with
only -u (upload = read) commands. No -w/-d/-e/-ob/-rst/-hardRst/-s. Output goes to a NEW directory under
reports/firmware/live_capture/ (never overwritten).

--analyze DIR validates a capture directory offline (also used by tests with synthetic data):
  lengths; camera_ready/polarity sanity; byte count == 38,400; frame stability (frame_a == frame_b);
  ENTC statistics check: meanR/G/B and dark% recomputed from the frame (big-endian decode) must equal the values the
  ENTC firmware itself stored in the status struct (the little-endian decode is reported for comparison);
  writes PNGs and runs OUR model on the PC (Python preprocessing == C, TFLite) - an offline inference on a real
  frame, NOT on-target camera-to-model inference.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CLI = r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe"
W, H = 160, 120
FRAME = W * H * 2
REGIONS = [  # (file, address, length) in read order
    ("meta_a.bin", 0x2000A35C, 8),
    ("status_a.bin", 0x20000008, 16),
    ("frame_a.bin", 0x2000055C, 40448),
    ("status_b.bin", 0x20000008, 16),
    ("frame_b.bin", 0x2000055C, 40448),
    ("meta_b.bin", 0x2000A35C, 8),
]
FORBIDDEN = {"-w", "-d", "-e", "-ob", "-rst", "-hardRst", "-s", "-w32", "-w16", "-w8", "--write", "--download", "--erase",
             "--optionbytes", "--start", "-g", "--go", "-fwupgrade", "--fwupgrade", "-fwupdate", "-r", "-run"}


def build_command(outdir: Path, freq_khz: int) -> list[str]:
    cmd = [CLI, "-c", "port=SWD", f"freq={freq_khz}", "mode=HOTPLUG"]
    for name, addr, n in REGIONS:
        cmd += ["-u", f"0x{addr:08X}", str(n), str(outdir / name)]
    assert not FORBIDDEN & set(cmd), "write/reset option in command"
    check_allowlist(cmd, outdir)
    return cmd


def check_allowlist(cmd: list[str], outdir: Path) -> None:
    """STRICT allow-list: exactly [CLI, -c, port=SWD, freq=N, mode=HOTPLUG] then only (-u, addr, len, file) groups that
    match REGIONS one-to-one, with files inside `outdir`. Anything else (write, erase, reset, option bytes, firmware
    upgrade, run/go, any unknown option) fails."""
    if cmd[0] != CLI or cmd[1:3] != ["-c", "port=SWD"] or not (cmd[3].startswith("freq=") and cmd[3][5:].isdigit()) \
            or cmd[4] != "mode=HOTPLUG":
        raise AssertionError(f"unexpected connect section: {cmd[:5]}")
    rest = cmd[5:]
    if len(rest) != 4 * len(REGIONS):
        raise AssertionError("unexpected number of tokens after connect")
    for k, (name, addr, n) in enumerate(REGIONS):
        grp = rest[4 * k:4 * k + 4]
        if grp != ["-u", f"0x{addr:08X}", str(n), str(outdir / name)]:
            raise AssertionError(f"unexpected read group {grp}")


def incomplete_files(d: Path) -> list[str]:
    """Files missing or with a wrong length (partial read)."""
    return [f"{name}: {'missing' if not (d / name).exists() else (d / name).stat().st_size}/{n} B"
            for name, _, n in REGIONS if not (d / name).exists() or (d / name).stat().st_size != n]


def decode_be(frame: bytes) -> np.ndarray:
    a = np.frombuffer(frame[:FRAME], np.uint8).reshape(H, W, 2).astype(np.uint16)
    return (a[..., 0] << 8) | a[..., 1]


def decode_le(frame: bytes) -> np.ndarray:
    a = np.frombuffer(frame[:FRAME], np.uint8).reshape(H, W, 2).astype(np.uint16)
    return (a[..., 1] << 8) | a[..., 0]


def entc_stats(p: np.ndarray) -> dict:
    """Exact integer re-implementation of the ENTC analysis (flash 0x08001234): ROI x 40..119, y 30..89."""
    roi = p[30:90, 40:120].astype(np.uint32)
    r = ((roi >> 11) << 3) & 0xFF
    g = ((roi >> 5) << 2) & 0xFF
    b = (roi << 3) & 0xFF
    n = roi.size
    dark = int((np.maximum(np.maximum(r, g), b) <= 59).sum())
    return {"meanR": int(r.sum() // n) & 0xFF, "meanG": int(g.sum() // n) & 0xFF, "meanB": int(b.sum() // n) & 0xFF,
            "dark_pct": (dark * 100 // n) & 0xFF}


def to_rgb888(p: np.ndarray) -> np.ndarray:
    r5, g6, b5 = (p >> 11) & 0x1F, (p >> 5) & 0x3F, p & 0x1F
    return np.stack([(r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2)], -1).astype(np.uint8)


def analyze(d: Path, run_model: bool = True) -> dict:
    files = {name: (d / name).read_bytes() for name, _, _ in REGIONS}
    rep: dict = {"dir": str(d), "label": "Frame read from SRAM over SWD (if this directory came from --execute); "
                 "PC-side analysis only, NOT on-target camera-to-model inference.", "checks": {}}
    c = rep["checks"]
    for name, _, n in REGIONS:
        c[f"len_{name}"] = len(files[name]) == n
    ma, mb = files["meta_a.bin"], files["meta_b.bin"]
    rep["meta_a"] = {"camera_ready": ma[0], "vspol": ma[1], "hspol": ma[2], "byte_3": ma[3],
                     "last_bytes": struct.unpack_from("<I", ma, 4)[0]}
    rep["meta_b"] = {"camera_ready": mb[0], "vspol": mb[1], "hspol": mb[2], "byte_3": mb[3],
                     "last_bytes": struct.unpack_from("<I", mb, 4)[0]}
    c["camera_ready"] = ma[0] == 1 and mb[0] == 1
    c["polarity_values_valid"] = ma[1] in (0, 1) and ma[2] in (0, 1)
    c["polarity_stable"] = ma[1:3] == mb[1:3]
    c["last_frame_38400"] = rep["meta_a"]["last_bytes"] == FRAME and rep["meta_b"]["last_bytes"] == FRAME
    fa, fb = files["frame_a.bin"], files["frame_b.bin"]
    c["frame_stable_a_eq_b"] = fa[:FRAME] == fb[:FRAME]
    rep["frame_a_sha256"] = hashlib.sha256(fa[:FRAME]).hexdigest()
    rep["frame_b_sha256"] = hashlib.sha256(fb[:FRAME]).hexdigest()
    rep["frame_bytes_differing_a_b"] = int(np.count_nonzero(np.frombuffer(fa[:FRAME], np.uint8) != np.frombuffer(fb[:FRAME], np.uint8)))
    rep["tail_nonzero_bytes_after_38400"] = int(np.count_nonzero(np.frombuffer(fa[FRAME:], np.uint8)))
    for tag in ("a", "b"):
        s = files[f"status_{tag}.bin"]
        rep[f"status_{tag}"] = {"frame_ok": s[0], "err": s[1], "meanR": s[2], "meanG": s[3], "meanB": s[4], "dark_pct": s[5],
                                "class_u32": hex(struct.unpack_from("<I", s, 8)[0])}
    st = rep["status_a"]
    want = {k: st[k] for k in ("meanR", "meanG", "meanB", "dark_pct")}
    rep["entc_stats_from_frame_be"] = entc_stats(decode_be(fa))
    rep["entc_stats_from_frame_le"] = entc_stats(decode_le(fa))
    c["status_frame_ok"] = st["frame_ok"] == 1 and st["err"] == 0
    c["entc_stats_match_big_endian"] = rep["entc_stats_from_frame_be"] == want
    rep["entc_stats_match_little_endian"] = rep["entc_stats_from_frame_le"] == want
    try:
        from PIL import Image
        Image.fromarray(to_rgb888(decode_be(fa))).save(d / "frame_a_be.png")
        Image.fromarray(to_rgb888(decode_le(fa))).save(d / "frame_a_le_for_comparison.png")
    except ImportError:
        pass
    required = ["camera_ready", "polarity_values_valid", "last_frame_38400", "status_frame_ok"] + [f"len_{n}" for n, _, _ in REGIONS]
    rep["valid_capture"] = all(c[k] for k in required)
    rep["format_confirmed_by_entc_stats"] = c["entc_stats_match_big_endian"] and c["frame_stable_a_eq_b"]
    if run_model and rep["valid_capture"]:
        rep["our_model_offline_pc"] = run_our_model(fa[:FRAME])
    return rep


def run_our_model(frame: bytes) -> dict:
    """PC inference with the frozen INT8 model through the bit-exact Python mirror of the firmware preprocessing."""
    import re
    import tensorflow as tf
    sys.path.insert(0, str(ROOT / "src"))
    from fruitvision.camera_preprocess import rgb565_to_input_int8
    from fruitvision.postprocess import postprocess
    x = rgb565_to_input_int8(np.frombuffer(frame, np.uint8), W, H, True)
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    inp, outs = it.get_input_details()[0], it.get_output_details()
    it.set_tensor(inp["index"], x.reshape(inp["shape"]))
    it.invoke()
    hdr = (ROOT / "firmware/stm32f407/generated/fv_generated_config.h").read_text()
    idx = [int(v) for v in re.search(r"FV_HEAD_OUTPUT_INDEX\[\w*\]\s*=\s*\{([^}]*)\}", hdr).group(1).split(",")]
    heads = ["fruit", "condition", "quality_banana", "quality_guava", "quality_apple", "stage_tomato", "stage_brinjal", "stage_banana"]
    deq = [(it.get_tensor(outs[idx[h]]["index"]).reshape(-1).astype(float) + 128) / 256 for h in range(8)]
    labels = json.loads((ROOT / "models/model3/labels.json").read_text())
    raw = {"fruit": dict(zip(["apple", "banana", "guava", "tomato", "brinjal"], deq[0])),
           "condition": dict(zip(["fresh", "spoiled"], deq[1])),
           "heads": {h: {labels[h][str(i)]: float(v) for i, v in enumerate(deq[j + 2])} for j, h in enumerate(heads[2:])}}
    pp = postprocess(raw, json.loads((ROOT / "configs/model3_postprocess.json").read_text()),
                     json.loads((ROOT / "models/model3/shelf_life_ranges.json").read_text()))
    return {"note": "offline PC inference on a real captured frame; not on-target", "fruit": pp["fruit"],
            "condition": pp["condition"], "quality_grade": {k: pp["quality_grade"].get(k) for k in ("label", "state", "confidence")},
            "shelf_life_state": pp["shelf_life"]["state"], "consistency": pp["consistency"]["status"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="actually connect (hot-plug) and read")
    ap.add_argument("--i-confirm-read-only", action="store_true")
    ap.add_argument("--freq", type=int, default=1000, help="SWD kHz (reads only)")
    ap.add_argument("--analyze", type=Path, help="validate an existing capture directory (no board access)")
    a = ap.parse_args()
    if a.analyze:
        bad = incomplete_files(a.analyze)
        if bad:
            print(f"PARTIAL/INVALID capture directory: {bad}"); return 3
        rep = analyze(a.analyze)
        (a.analyze / "analysis.json").write_text(json.dumps(rep, indent=1, default=str))
        print(json.dumps(rep, indent=1, default=str))
        return 0 if rep["valid_capture"] else 1
    out = ROOT / "reports/firmware/live_capture" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cmd = build_command(out, a.freq)
    print("PLAN (read-only, hot-plug):")
    for name, addr, n in REGIONS:
        print(f"  read 0x{addr:08X} {n:6d} B -> {out / name}")
    print("COMMAND:\n  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if not (a.execute and a.i_confirm_read_only):
        print("DRY RUN: nothing executed (needs --execute --i-confirm-read-only).")
        return 0
    if out.exists():
        print(f"refusing: {out} exists"); return 2
    out.mkdir(parents=True)                      # raises if it appeared meanwhile: never overwrite
    try:                                          # exactly ONE attempt; no retry on any failure
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as e:
        (out / "cli_log.txt").write_text(" ".join(cmd) + "\n\nTIMEOUT after 300 s\n" + str(e.stdout or "") + str(e.stderr or ""))
        print(f"CLI timed out; stopping (no retry). See {out / 'cli_log.txt'}"); return 4
    (out / "cli_log.txt").write_text(" ".join(cmd) + "\n\n" + r.stdout + r.stderr)
    print(r.stdout[-2000:], r.stderr[-1000:])
    if r.returncode != 0:
        print(f"CLI failed (exit {r.returncode}); stopping (no retry). See {out / 'cli_log.txt'}"); return r.returncode
    bad = incomplete_files(out)
    if bad:
        print(f"PARTIAL READ, stopping (no retry): {bad}"); return 3
    rep = analyze(out)
    (out / "analysis.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: v for k, v in rep.items() if k != "our_model_offline_pc"}, indent=1, default=str))
    return 0 if rep["valid_capture"] else 1


if __name__ == "__main__":
    sys.exit(main())
