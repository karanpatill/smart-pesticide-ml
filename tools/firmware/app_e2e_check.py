"""End-to-end HOST check of the firmware application path (fv_app_cycle with the real fv_vision.cc on
32-bit x86, TFLM CMSIS-NN portable int8 kernels) against the Python reference path on the same RGB565
frames: camera_preprocess.rgb565_to_input_int8 -> content_stats -> TFLite (reference kernels) ->
postprocess. Frames are synthesised from the stored test inputs (NOT camera captures).
Requires WSL with tools/firmware/build_fw_check.sh already run."""
import json, pathlib, subprocess, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from fruitvision.camera_preprocess import rgb565_to_input_int8, rgb888_to_rgb565_bytes  # noqa: E402
from fruitvision.postprocess import postprocess  # noqa: E402
from fruitvision.validation.image_checks import content_stats  # noqa: E402

FR = ROOT / "reports/firmware/e2e_frames"
SET = sys.argv[1] if len(sys.argv) > 1 else "default"   # "default" | "160x120"
SUF = "" if SET == "default" else "_" + SET
if SET != "default":
    FR = ROOT / f"reports/firmware/e2e_frames{SUF}"
HEADS = ["fruit", "condition", "quality_banana", "quality_guava", "quality_apple", "stage_tomato", "stage_brinjal",
         "stage_banana"]


def frames_160x120(n=12):
    """Real public test images -> centre 4:3 crop -> 160x120 (PIL bilinear) -> RGB565 big-endian (ENTC format)."""
    import pandas as pd
    from PIL import Image
    FR.mkdir(parents=True, exist_ok=True)
    te = pd.read_csv(ROOT / "data/splits/test.csv")
    idx = np.linspace(0, len(te) - 1, n).astype(int)
    out = []
    for k, i in enumerate(idx):
        with Image.open(ROOT / "data/raw" / te.path[i]) as im:
            im = im.convert("RGB"); w, h = im.size
            cw, ch = (h * 4 // 3, h) if w * 3 >= h * 4 else (w, w * 3 // 4)
            x0, y0 = (w - cw) // 2, (h - ch) // 2
            rgb = np.asarray(im.crop((x0, y0, x0 + cw, y0 + ch)).resize((160, 120), Image.BILINEAR), np.uint8)
        out.append((f"q{k:02d}.rgb565", rgb888_to_rgb565_bytes(rgb, big_endian=True).reshape(-1), 160, 120, 1))
    out.append(("uniform160.rgb565", rgb888_to_rgb565_bytes(np.full((120, 160, 3), 120, np.uint8)).reshape(-1), 160, 120, 1))
    for name, b, *_ in out:
        (FR / name).write_bytes(b.tobytes())
    return out


def frames():
    FR.mkdir(parents=True, exist_ok=True)
    out = []
    ins = sorted((ROOT / "reports/stm32_memory/test_inputs").glob("in*.int8"))
    for i, p in enumerate(ins[:8]):
        rgb = (np.fromfile(p, np.int8).reshape(80, 80, 3).astype(np.int16) + 128).astype(np.uint8)
        if i % 2 == 0:   # 96x96 (nearest upsample)
            yy, xx = (np.arange(96) * 80) // 96, (np.arange(96) * 80) // 96
            w, h = 96, 96
        else:            # 96x80 non-square -> centre crop + aspect warning
            yy, xx = np.arange(80), (np.arange(96) * 80) // 96
            w, h = 96, 80
        big = rgb[yy][:, xx]
        be = i % 4 < 2
        out.append((f"f{i:02d}.rgb565", rgb888_to_rgb565_bytes(big, big_endian=be).reshape(-1), w, h, int(be)))
    out.append(("uniform.rgb565", rgb888_to_rgb565_bytes(np.full((96, 96, 3), 120, np.uint8)).reshape(-1), 96, 96, 1))
    out.append(("tiny.rgb565", rgb888_to_rgb565_bytes(np.full((20, 96, 3), 120, np.uint8)).reshape(-1), 96, 20, 1))
    for name, b, *_ in out:
        (FR / name).write_bytes(b.tobytes())
    return out


def main():
    import tensorflow as tf
    fs = frames() if SET == "default" else frames_160x120()
    args = []
    for name, _, w, h, be in fs:
        args += [f"reports/firmware/e2e_frames{SUF}/{name}", str(w), str(h), str(be)]
    r = subprocess.run(["wsl.exe", "bash", "-lc", "cd /mnt/d/smart-pesticide-ml && ~/tflm_work/build_fw/host32/fv_vision_host app "
                        + " ".join(args)], capture_output=True, text=True, env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"})
    (ROOT / f"reports/firmware/host32_fv_app_e2e{SUF}.txt").write_text(r.stdout)
    apps = [l.split() for l in r.stdout.splitlines() if l.startswith("APP")]
    wins = [int(l.split()[1]) for l in r.stdout.splitlines() if l.startswith("WIN")]
    assert len(apps) == len(fs), r.stdout + r.stderr
    cfg = json.loads((ROOT / "configs/model3_postprocess.json").read_text())
    shelf = json.loads((ROOT / "models/model3/shelf_life_ranges.json").read_text())
    labels = json.loads((ROOT / "models/model3/labels.json").read_text())
    img_cfg = json.loads((ROOT / "configs/image_checks.json").read_text())
    it = tf.lite.Interpreter(model_path=str(ROOT / "models/experimental/tflite/combined_int8.tflite"),
                             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    it.allocate_tensors()
    sig = it.get_signature_runner()
    hdr = (ROOT / "firmware/stm32f407/generated/fv_generated_config.h").read_text()
    fruits = ["apple", "banana", "guava", "tomato", "brinjal"]
    rows, agree = [], 0
    for (name, b, w, h, be), a, win in zip(fs, apps, wins + [None] * len(fs)):
        cam = int(a[1].split("=")[1])
        dims = img_cfg["dimensions"]
        rej_dim = min(w, h) < dims["reject_min_side"]
        exp = {"name": name}
        if rej_dim:
            exp["expected"] = "rejected (dimensions)"
            ok = cam == -7
        else:
            x = rgb565_to_input_int8(b, w, h, bool(be))
            st = content_stats(x.astype(np.float32) + 128)
            rj = img_cfg["reject"]
            rejected = (st["lum_std"] < rj["lum_std_below"] or st["lag1_autocorr"] < rj["lag1_autocorr_below"]
                        or st["chroma_mean_abs"] < rj["chroma_below"])
            if rejected:
                exp["expected"] = "rejected (content)"
                ok = cam == -7
            else:
                o = sig(**{sig.get_input_details() and list(sig.get_input_details())[0]: x[None]})
                deq = {k: (v.reshape(-1).astype(np.float64) + 128) / 256 for k, v in o.items()}
                key = {hd: next(k for k in deq if k.endswith(hd) or k == hd) for hd in HEADS}
                raw = {"fruit": dict(zip(fruits, deq[key["fruit"]])),
                       "condition": dict(zip(["fresh", "spoiled"], deq[key["condition"]])),
                       "heads": {hd: {labels[hd][str(i)]: float(p) for i, p in enumerate(deq[key[hd]])}
                                 for hd in HEADS[2:]}}
                pp = postprocess(raw, cfg, shelf)
                c_fruit, c_cond, c_qst, c_grade, c_sst, c_stage = (int(a[4]), int(a[5]), int(a[6]), int(a[7]),
                                                                    int(a[8]), int(a[9]))
                gmap = {"Good": 0, "Average": 1, "Poor": 2}
                smap = {"Fresh": 0, "Semi-fresh": 1, "Rotten": 2}
                st_map = {"predicted": 0, "uncertain": 1, "unavailable": 2}
                ok = (cam == 0 and fruits[c_fruit] == pp["fruit"]["label"] and ["fresh", "spoiled"][c_cond] == pp["condition"]["label"]
                      and c_qst == st_map[pp["quality_grade"]["state"]] and c_sst == st_map[pp["shelf_life"]["state"]]
                      and (c_qst != 0 or c_grade == gmap[pp["quality_grade"]["label"]])
                      and (c_sst != 0 or c_stage == smap[pp["shelf_life"]["stage"]]))
                exp["expected"] = {"fruit": pp["fruit"]["label"], "quality": pp["quality_grade"]["label"],
                                   "shelf": pp["shelf_life"]["state"]}
        exp["c_app"] = " ".join(a[1:]); exp["window_offset"] = win; exp["agree"] = bool(ok)
        agree += ok
        rows.append(exp)
    res = {"n": len(fs), "agree": agree, "windows_outside_input": all(wv is None or wv >= 19200 for wv in wins),
           "device": "host32 x86 (zig) - NOT STM32. Frames: " + ("stored test inputs" if SET == "default" else "public test images, centre 4:3 crop, PIL-resized to 160x120, RGB565 big-endian (ENTC format)") + " - OFFLINE, NOT camera captures",
           "rows": rows}
    (ROOT / f"reports/firmware/host32_fv_app_e2e{SUF}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}))
    return 0 if agree == len(fs) else 1


if __name__ == "__main__":
    sys.exit(main())
