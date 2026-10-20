"""Slow live preview of the OV2640 frame held in SRAM by the running ENTC firmware (read-only SWD, hot-plug).

Reuses the reviewed procedure of tools/firmware/capture_live_frame.py (same CLI, same addresses, same frame decode
and ENTC statistics check). Each refresh = ONE STM32_Programmer_CLI call with only four reads:
    -c port=SWD freq=<f> mode=HOTPLUG  -u 0x20000008 16 status_a  -u 0x2000055C 38400 frame_a
                                       -u 0x2000055C 38400 frame_b  -u 0x20000008 16 status_b
No write, erase, reset, halt, option-byte or firmware-upgrade operation (strict allow-list, checked before every call).

A frame is shown only if: all files have the right length, frame_a == frame_b (no camera DMA write during the read;
the ENTC statistics alone only cover the centre region x 40-119, y 30-89, so a tear in the top/bottom rows would
slip through), status_a == status_b, ENTC frame_ok == 1 and err == 0, and ENTC's stored mean R/G/B + dark % are
reproduced exactly from the big-endian decode. Otherwise it is skipped and the last good frame stays on screen.

Read failures: no immediate retry. After a failure the next read waits at least FAIL_BACKOFF_S; after --max-failures
consecutive failures polling pauses until you press "Resume". Nothing is saved unless you press "Save frame".
Raw reads go to a temporary folder that is deleted when the window closes.

Usage (PowerShell, from D:\\smart-pesticide-ml):
    .venv\\Scripts\\python tools\\firmware\\live_preview.py                  # live, refresh ~2 s
    .venv\\Scripts\\python tools\\firmware\\live_preview.py --print-command  # show the SWD command, connect to nothing
    .venv\\Scripts\\python tools\\firmware\\live_preview.py --demo           # simulated frames, no board
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_live_frame as cl  # noqa: E402  (reviewed capture module: CLI path, decode, ENTC statistics)

ROOT = Path(__file__).resolve().parents[2]
STATUS_ADDR, STATUS_LEN = 0x20000008, 16
FRAME_ADDR, FRAME_LEN = 0x2000055C, cl.FRAME          # 38,400 B (valid frame part of the 40,448 B buffer)
MIN_INTERVAL_S = 1.0                                   # never poll faster than this
FAIL_BACKOFF_S = 10.0                                  # wait after a failed read (no rapid retries)
CLI_TIMEOUT_S = 30
SCALE = 4                                              # 160x120 -> 640x480
SAVE_DIR = ROOT / "reports/firmware/live_preview_saves"


# ----------------------------------------------------------------------------- command (strict allow-list)
def build_preview_command(tmp: Path, freq_khz: int) -> list[str]:
    cmd = [cl.CLI, "-c", "port=SWD", f"freq={freq_khz}", "mode=HOTPLUG",
           "-u", f"0x{STATUS_ADDR:08X}", str(STATUS_LEN), str(tmp / "status_a.bin"),
           "-u", f"0x{FRAME_ADDR:08X}", str(FRAME_LEN), str(tmp / "frame_a.bin"),
           "-u", f"0x{FRAME_ADDR:08X}", str(FRAME_LEN), str(tmp / "frame_b.bin"),
           "-u", f"0x{STATUS_ADDR:08X}", str(STATUS_LEN), str(tmp / "status_b.bin")]
    check_preview_allowlist(cmd, tmp)
    return cmd


def check_preview_allowlist(cmd: list[str], tmp: Path) -> None:
    if cl.FORBIDDEN & set(cmd):
        raise AssertionError("forbidden option in command")
    if cmd[0] != cl.CLI or cmd[1:3] != ["-c", "port=SWD"] or not (cmd[3].startswith("freq=") and cmd[3][5:].isdigit()) \
            or cmd[4] != "mode=HOTPLUG":
        raise AssertionError(f"unexpected connect section: {cmd[:5]}")
    expected = [["-u", f"0x{STATUS_ADDR:08X}", str(STATUS_LEN), str(tmp / "status_a.bin")],
                ["-u", f"0x{FRAME_ADDR:08X}", str(FRAME_LEN), str(tmp / "frame_a.bin")],
                ["-u", f"0x{FRAME_ADDR:08X}", str(FRAME_LEN), str(tmp / "frame_b.bin")],
                ["-u", f"0x{STATUS_ADDR:08X}", str(STATUS_LEN), str(tmp / "status_b.bin")]]
    if [cmd[5 + 4 * k:9 + 4 * k] for k in range(4)] != expected or len(cmd) != 21:
        raise AssertionError("unexpected read groups")


# ----------------------------------------------------------------------------- frame validation
@dataclass
class ReadResult:
    ok: bool                       # the read itself succeeded (files complete)
    status_a: bytes = b""
    frame: bytes = b""
    status_b: bytes = b""
    error: str = ""
    frame_b: bytes | None = None   # second read of the same buffer (None = same as frame, e.g. demo)


def validate(r: ReadResult) -> tuple[bool, str]:
    """True only for a complete, stable frame whose ENTC statistics match the big-endian decode."""
    if not r.ok:
        return False, f"read failed: {r.error}"
    fb = r.frame if r.frame_b is None else r.frame_b
    if len(r.status_a) != STATUS_LEN or len(r.status_b) != STATUS_LEN or len(r.frame) != FRAME_LEN or len(fb) != FRAME_LEN:
        return False, "incomplete read"
    if r.frame != fb:
        return False, "frame changed between the two reads (camera DMA was writing)"
    if r.status_a != r.status_b:
        return False, "ENTC re-captured during the read (status changed)"
    if r.status_a[0] != 1 or r.status_a[1] != 0:
        return False, f"ENTC reports no valid frame (ok={r.status_a[0]}, err={r.status_a[1]})"
    want = {"meanR": r.status_a[2], "meanG": r.status_a[3], "meanB": r.status_a[4], "dark_pct": r.status_a[5]}
    if cl.entc_stats(cl.decode_be(r.frame)) != want:
        return False, "colour statistics do not match ENTC (torn or changed frame)"
    return True, "ok"


def render(frame: bytes, scale: int = SCALE) -> np.ndarray:
    """160x120 RGB565 big-endian -> (120*scale, 160*scale, 3) uint8, nearest-neighbour enlargement."""
    rgb = cl.to_rgb888(cl.decode_be(frame))
    return np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)


# ----------------------------------------------------------------------------- frame sources
def run_cli(cmd: list[str]) -> tuple[str, str]:
    """The only place a CLI process is started. Returns (stdout, error message or "")."""
    if cl.FORBIDDEN & set(cmd) or cmd[0] != cl.CLI or "mode=HOTPLUG" not in cmd:
        raise AssertionError("refusing: not a read-only hot-plug command")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return "", f"CLI timeout ({CLI_TIMEOUT_S} s)"
    except OSError as e:
        return "", f"cannot start STM32_Programmer_CLI: {e}"
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
        return "", f"CLI exit {p.returncode}: {tail[0][:120]}"
    return p.stdout, ""


class DiagSource:
    """Our diagnostic firmware (fv_app_v6_diag / v7_diag / v8_diag): shows the exact 80x80 model input kept in
    g_fv_capture. The raw 160x120 frame is NOT available there (inference overwrites it); the 80x80 image is the centre
    120x120 square of the frame, scaled down. One hot-plug call: whole block (-r32), then its 8-byte header again;
    shown only if the block is complete (seq even / snapshot READY) and the header did not change during the read."""
    label = "Read-only SWD view of the 80x80 model input (centre square of the 160x120 frame), enlarged 6x."
    scale = 6

    def __init__(self, elf: Path, freq_khz: int = 4000):
        import read_capture as rc
        import read_selftest as rs
        self.rc, self.rs, self.freq = rc, rs, freq_khz
        self.addr, size = rs.symbol(str(elf), "g_fv_capture")
        if size != rc.SIZE:
            raise SystemExit(f"g_fv_capture size {size} != {rc.SIZE}: unsupported firmware")

    def command(self) -> list[str]:
        return [cl.CLI, "-c", "port=SWD", f"freq={self.freq}", "mode=HOTPLUG",
                "-r32", hex(self.addr), str(self.rc.SIZE), "-r32", hex(self.addr), "8"]

    def read(self) -> ReadResult:
        out, err = run_cli(self.command())
        if err:
            return ReadResult(False, error=err)
        segs = self.rc.split_reads(out, self.addr)
        if len(segs) != 2:
            return ReadResult(False, error=f"expected 2 reads in CLI output, got {len(segs)}")
        try:
            block = self.rs.parse_r32(segs[0], self.addr, self.rc.SIZE)
            hdr = self.rs.parse_r32(segs[1], self.addr, 8)
        except SystemExit as e:
            return ReadResult(False, error=str(e))
        return ReadResult(True, block[:8], block, hdr)

    def validate(self, r: ReadResult) -> tuple[bool, str]:
        if not r.ok:
            return False, f"read failed: {r.error}"
        if len(r.frame) != self.rc.SIZE or len(r.status_b) != 8:
            return False, "incomplete read"
        c = self.rc.decode(r.frame)
        magic_after, seq_after = struct.unpack("<II", r.status_b)
        if c["magic"] == self.rc.MAGIC:
            if c["seq"] % 2 or seq_after != c["seq"] or magic_after != c["magic"]:
                return False, "firmware was writing the image during the read"
        elif c["magic"] == self.rc.READY:
            if magic_after != c["magic"] or seq_after != c["seq"]:
                return False, "snapshot header changed during the read"
        else:
            return False, f"no capture block (magic {c['magic']:#x}): snapshot not ready yet or wrong --elf"
        probs = {f: (v + 128) / 256 for f, v in zip(self.rc.FRUITS, c["raw"][:5])}
        top = max(probs, key=probs.get)
        return True, (f"detail {c['detail']:.1f} (gate 43.96, higher = sharper)   model: {top} {probs[top]:.2f}"
                      f"   OLED fruit: {'shown' if c['fruit_present'] else 'NOFRUIT/UNKNOWN'}")

    def to_rgb(self, frame: bytes) -> np.ndarray:
        return (self.rc.decode(frame)["input"].astype(np.int16) + 128).astype(np.uint8).reshape(80, 80, 3)

    def render(self, frame: bytes) -> np.ndarray:
        return np.repeat(np.repeat(self.to_rgb(frame), self.scale, axis=0), self.scale, axis=1)

    def close(self) -> None:
        pass


class SwdSource:
    """One hot-plug CLI call per read, into a private temp folder (deleted by close())."""

    def __init__(self, freq_khz: int = 1000):
        self.freq = freq_khz
        self.tmp = Path(tempfile.mkdtemp(prefix="fv_preview_"))

    def read(self) -> ReadResult:
        for f in self.tmp.glob("*.bin"):
            f.unlink()                                  # never show stale data from a previous read
        _, err = run_cli(build_preview_command(self.tmp, self.freq))
        if err:
            return ReadResult(False, error=err)
        try:
            return ReadResult(True, (self.tmp / "status_a.bin").read_bytes(), (self.tmp / "frame_a.bin").read_bytes(),
                              (self.tmp / "status_b.bin").read_bytes(), frame_b=(self.tmp / "frame_b.bin").read_bytes())
        except OSError as e:
            return ReadResult(False, error=f"output missing: {e}")

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class DemoSource:
    """Simulated frames for trying the window without the board (moving gradient + matching ENTC statistics)."""

    def __init__(self):
        self.n = 0

    def read(self) -> ReadResult:
        sys.path.insert(0, str(ROOT / "src"))
        from fruitvision.camera_preprocess import rgb888_to_rgb565_bytes
        self.n += 1
        yy, xx = np.mgrid[0:120, 0:160]
        rgb = np.stack([(xx * 1.6 + self.n * 12) % 256, (yy * 2.1) % 256, ((xx + yy + self.n * 20) * 0.7) % 256], -1)
        frame = rgb888_to_rgb565_bytes(rgb.astype(np.uint8), big_endian=True).tobytes()
        s = cl.entc_stats(cl.decode_be(frame))
        status = bytes([1, 0, s["meanR"], s["meanG"], s["meanB"], s["dark_pct"]]) + bytes(10)
        return ReadResult(True, status, frame, status)

    def close(self) -> None:
        pass


# ----------------------------------------------------------------------------- GUI-free controller (tested offline)
@dataclass
class PreviewState:
    reads: int = 0
    shown: int = 0
    skipped: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    paused: bool = False
    last_reason: str = "waiting for first read"
    last_frame: bytes | None = None
    last_frame_time: str = ""
    changed: bool = False
    log: list = field(default_factory=list)


class PreviewController:
    def __init__(self, source, interval_s: float = 2.0, max_failures: int = 3):
        self.source = source
        self.interval = max(MIN_INTERVAL_S, float(interval_s))
        self.max_failures = max(1, int(max_failures))
        self.st = PreviewState()

    def poll_once(self) -> float | None:
        """Do one read (unless paused) and return the delay in seconds before the next read (None = paused)."""
        if self.st.paused:
            return None
        r = self.source.read()
        self.st.reads += 1
        if not r.ok:
            self.st.failures += 1
            self.st.consecutive_failures += 1
            self.st.last_reason = r.error
            self.st.log.append(("fail", r.error))
            if self.st.consecutive_failures >= self.max_failures:
                self.st.paused = True
                self.st.last_reason = f"paused after {self.st.consecutive_failures} failed reads: {r.error}"
                return None
            return max(self.interval, FAIL_BACKOFF_S)          # back off, no rapid retry
        self.st.consecutive_failures = 0
        ok, reason = getattr(self.source, "validate", validate)(r)
        if not ok:
            self.st.skipped += 1
            self.st.last_reason = f"skipped: {reason}"
            self.st.log.append(("skip", reason))
            return self.interval
        self.st.changed = self.st.last_frame != r.frame
        self.st.last_frame = r.frame
        self.st.last_frame_time = dt.datetime.now().strftime("%H:%M:%S")
        self.st.shown += 1
        self.st.last_reason = "ok (new image)" if self.st.changed else "ok (unchanged: ENTC has not captured a new frame)"
        if reason != "ok":
            self.st.last_reason = ("ok (new image)" if self.st.changed else "ok (unchanged)") + "   " + reason
        self.st.log.append(("show", "changed" if self.st.changed else "same"))
        return self.interval

    def resume(self) -> None:
        self.st.paused = False
        self.st.consecutive_failures = 0
        self.st.last_reason = "resumed"

    def save_current(self, save_dir: Path = SAVE_DIR) -> Path | None:
        """Only called from the Save button. Writes PNG + raw frame into a NEW timestamped file pair."""
        if self.st.last_frame is None:
            return None
        from PIL import Image
        save_dir.mkdir(parents=True, exist_ok=True)
        stem = save_dir / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        if stem.with_suffix(".png").exists():
            return None
        if hasattr(self.source, "to_rgb"):
            Image.fromarray(self.source.to_rgb(self.st.last_frame)).save(stem.with_suffix(".png"))
            stem.with_suffix(".fv_capture.bin").write_bytes(self.st.last_frame)
            return stem.with_suffix(".png")
        Image.fromarray(cl.to_rgb888(cl.decode_be(self.st.last_frame))).save(stem.with_suffix(".png"))
        stem.with_suffix(".rgb565be.bin").write_bytes(self.st.last_frame)
        return stem.with_suffix(".png")


# ----------------------------------------------------------------------------- window
def run_window(ctrl: PreviewController, title: str) -> None:
    import tkinter as tk
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title(title)
    blank = np.zeros((120 * SCALE, 160 * SCALE, 3), np.uint8)
    photo = ImageTk.PhotoImage(Image.fromarray(blank))
    img_label = tk.Label(root, image=photo)
    img_label.pack()
    text = tk.StringVar(value="starting...")
    tk.Label(root, textvariable=text, font=("Segoe UI", 10), anchor="w", justify="left").pack(fill="x", padx=6)
    bar = tk.Frame(root)
    bar.pack(fill="x", padx=6, pady=4)
    busy = {"read": False, "after": None, "closing": False}

    def update_view():
        s = ctrl.st
        if s.last_frame is not None:
            p = ImageTk.PhotoImage(Image.fromarray(getattr(ctrl.source, "render", render)(s.last_frame)))
            img_label.configure(image=p)
            img_label.image = p
        text.set(f"Last good frame: {s.last_frame_time or '-'}   shown {s.shown}   skipped {s.skipped}   failed reads {s.failures}\n"
                 f"Status: {s.last_reason}\n" + getattr(ctrl.source, "label",
                 "Read-only SWD preview of the ENTC firmware's frame buffer (160x120, enlarged 4x)."))

    def schedule(delay):
        if busy["closing"]:
            return
        if delay is None:          # paused
            update_view()
            return
        busy["after"] = root.after(int(delay * 1000), start_read)

    def start_read():
        if busy["read"] or busy["closing"]:
            return
        busy["read"] = True
        text.set(text.get().split("\n")[0] + "\nStatus: reading over SWD ...")

        def worker():
            delay = ctrl.poll_once()
            root.after(0, lambda: finish(delay))
        threading.Thread(target=worker, daemon=True).start()

    def finish(delay):
        busy["read"] = False
        update_view()
        schedule(delay)

    def on_resume():
        if ctrl.st.paused and not busy["read"]:
            ctrl.resume()
            schedule(0)

    def on_save():
        p = ctrl.save_current()
        text.set(text.get() + (f"\nSaved: {p}" if p else "\nNothing to save yet."))

    def on_close():
        busy["closing"] = True
        if busy["after"]:
            root.after_cancel(busy["after"])
        root.destroy()

    tk.Button(bar, text="Resume (after failures)", command=on_resume).pack(side="left")
    tk.Button(bar, text="Save frame", command=on_save).pack(side="left", padx=6)
    tk.Button(bar, text="Close", command=on_close).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", on_close)
    update_view()
    schedule(0)
    root.mainloop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=2.0, help=f"seconds between reads (minimum {MIN_INTERVAL_S})")
    ap.add_argument("--freq", type=int, default=None, help="SWD kHz (default 1000 for entc, 4000 for diag)")
    ap.add_argument("--firmware", choices=["entc", "diag"], default="entc",
                    help="entc = original ENTC firmware (160x120 frame); diag = our fv_app_v6/v7/v8_diag (80x80 model input)")
    ap.add_argument("--elf", default=str(ROOT / "reports/firmware/gcc/fv_app_v8_diag.elf"),
                    help="ELF of the RUNNING diagnostic firmware (only for --firmware diag; gives the g_fv_capture address)")
    ap.add_argument("--max-failures", type=int, default=3, help="pause after this many consecutive failed reads")
    ap.add_argument("--demo", action="store_true", help="simulated frames, no board access")
    ap.add_argument("--print-command", action="store_true", help="print the SWD command and exit (no board access)")
    a = ap.parse_args()
    if a.freq is None:
        a.freq = 4000 if a.firmware == "diag" else 1000
    if a.firmware == "diag" and not a.demo:
        dsrc = DiagSource(Path(a.elf), a.freq)
        if a.print_command:
            print(" ".join(f'"{c}"' if " " in c else c for c in dsrc.command()))
            print("Read-only: hot-plug connect + 2 reads (19,264 B g_fv_capture, then its 8-byte header). Nothing executed.")
            return 0
        ctrl = PreviewController(dsrc, a.interval, a.max_failures)
        run_window(ctrl, f"OV2640 model-input preview - read-only SWD ({Path(a.elf).name})")
        print(f"reads {ctrl.st.reads}, shown {ctrl.st.shown}, skipped {ctrl.st.skipped}, failed {ctrl.st.failures}")
        return 0
    if a.print_command:
        tmp = Path(tempfile.gettempdir()) / "fv_preview_EXAMPLE"
        print(" ".join(f'"{c}"' if " " in c else c for c in build_preview_command(tmp, a.freq)))
        print("Read-only: hot-plug connect + 4 reads (16 B status, 2 x 38,400 B frame, 16 B status). Nothing executed.")
        return 0
    src = DemoSource() if a.demo else SwdSource(a.freq)
    ctrl = PreviewController(src, a.interval, a.max_failures)
    try:
        run_window(ctrl, "OV2640 preview - DEMO (simulated)" if a.demo else "OV2640 preview - read-only SWD")
    finally:
        src.close()
    print(f"reads {ctrl.st.reads}, shown {ctrl.st.shown}, skipped {ctrl.st.skipped}, failed {ctrl.st.failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
