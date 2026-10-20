# OV2640 blur investigation: read-only Phase 1 and Phase 2 baseline (2026-10-17)

No board writes, flashes or resets were done for this report. All evidence comes from repository code, the ENTC table and saved captures.

## 1. Pipeline check

| Step | Finding | Evidence |
|---|---|---|
| SCCB init | ENTC sequence, in order: 0xFF←0x01, table A (157), 10 ms, table B (22), then PCLK 0xD3←0x8C | `drivers/fv_ov2640.c`, `platform/fv_platform_stm32.c:131-135`; diag `cam_table_fail_index = -1` (all 179 writes ACKed) |
| Later SCCB writes | Only (a) a PCLK fallback after capture errors (not triggered: `cam_pclk_div = 12`) and (b) the v8 tune request #1 | grep of all `fv_sccb_write` callers |
| v8 tune #1 (all index 0) | Writes the same values as ENTC: C3=FD, C7=10, SDE ctrl 7C/7D=00/00, AEW/AEB/VV=40/38/82 | host test `defaults_equal_entc`; the image was already blurred before it (diag `img_detail_x10 = 116` at cycle 11, before any tune write) |
| Overwrites inside the ENTC tables | Present in the original ENTC firmware (CIF block over SVGA defaults, E0/05 reset bracketing); reproduced 1:1 | table decode |
| Pixel format | COM7 = 0x20 (CIF), DSP 0xDA = 0x08 (RGB565), 400x296 → zoom 160x120 (ZMOW/ZMOH 0x28/0x1E) | effective register values below |
| Byte order | Big-endian RGB565 confirmed: the ENTC firmware's own meanR/G/B/dark% (168/166/153/0) are reproduced exactly from the BE decode | `live_capture/20261017T094631Z/analysis.json` `entc_stats_match_big_endian = true` |
| Channel order | Correct: in the sharp frame the banana is yellow and the blue object is blue | `device_capture/20261017T140046Z_focus_loop_12` |
| Device vs PC preprocessing | Bit-exact in every one of 16 captures | `python_equals_device_bit_exact = true` |
| Preview display | Nearest-neighbour enlargement (`np.repeat`), so the display adds no blur | `tools/firmware/live_preview.py` `render` |
| Mirror/flip | REG04 = 0x28: no H/V flip | effective values |

## 2. Effective register values in use (ENTC A+B, plus PCLK, plus tune #1)

- **Sensor bank:** 04=28, 11=01, 12=20, 13=E5 (AEC/AGC auto, banding), 14=48, 17=11, 18=43, 19=00, 1A=25, 22=1A, 24=40, 25=38, 26=82, 32=89, 34=C0, 3C=32
- **DSP bank:** 05=00, 50=80, 51=64, 52=4A, 53..57=00, 5A=28, 5B=1E, 5C=00, 86=3D, 87=50, 8C=00, C0=32, C1=25, C3=FD (LENC off, AWB on), C7=10, D3=8C, DA=08, E0=00, E1=77
- **SDE sequence:** 7C=00 7D=00 | 7C=03 7D=48 48 | 7C=08 7D=20 10 0E

## 3. Captures (detail = variance of the Laplacian of the 80x80 luma; it depends on the scene)

- All captures with the same v6_diag firmware and ENTC registers (no tuning existed then):
  - 01–11: 34.7–36.3
  - 12: **350.7**, ten seconds after 11, with no register change between them
- Frame 12 is visibly sharp: banana speckles, foil texture and object edges are clear. So the score is supported by the image.
- Frames 07 and 12 show the same scene layout (luma correlation 0.877). Frame 07 shows round bright discs where frame 12 has specular foil highlights, which is the typical look of optical defocus.
- After the v8 flash, the baseline frame is nearly uniform (11.4).
- Corner/centre brightness is 0.44 (vignetting; LENC is off).

## 4. Conclusion

- The strongest evidence: **the same firmware and the same registers produced both a sharp frame and blurred frames**, ten seconds apart.
- So the register configuration can deliver a sharp image, and the blur comes from the optical/mechanical side: lens focus position, a loose lens, or camera/scene placement.
- No register in the table explains a change from 35 to 351 between two frames with no writes.
- Software settings (LENC, AWB, saturation, AE) do not restore optical focus.

## 5. Proposed first register test (needs approval; secondary to refocusing)

- **Change:** DSP bank 0xC3: 0xFD → 0xFF (LENC on).
  - Command: `cam_tune.py --lenc 1`.
  - Rollback: `cam_tune.py --lenc 0` (0xC3 = 0xFD).
- **Expected effect:** brighter corners (corner/centre 0.44 ↑). No effect on focus.
- **Procedure:**
  1. Static scene.
  2. Baseline capture at 0,0,0,0.
  3. Capture after `--lenc 1`.
  4. Compare corner/centre ratio and detail.
  5. Roll back if the result is not better or if any instability is seen.
