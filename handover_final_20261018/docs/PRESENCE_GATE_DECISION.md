# Fruit-presence gate: decision (2026-10-17, PC-only)

**Decision: keep fv_app_v5 unchanged; no v6.** The evidence does not support relaxing the gate.

## Root cause of rejected real fruit
| Real frame (SWD) | detail (≥ 43.96) | confidence (≥ 0.976) | shown |
|---|---|---|---|
| empty/blurry scene | 12.1 ✗ | 0.805 ✗ | no (correct) |
| apple, defocused | 12.4 ✗ | 0.840 ✗ | no |
| apple, focused | **84.1 ✓** | **0.852 ✗** | no (false rejection) |
The detail threshold is not the limiting factor for a focused fruit; **model confidence on real OV2640 frames is** (domain shift:
the frozen model was trained on public photos). Confidence alone is unsafe: uniform grey → guava 0.992; on v4 an empty device scene → guava 0.91–0.95.

## Why the confidence threshold is not lowered
Sweep (`reports/firmware/presence_gate_threshold_sweep.json`, detail gate fixed): accepting the focused apple needs ≤ 0.85 (fitting one
frame). At ≤ 0.90, 4/5 synthetic empty scenes exceed the confidence threshold, so only the detail check would stop a false fruit on an
empty scene, and its real-camera evidence is ONE empty frame. False acceptance on real empty/background/non-fruit scenes is unmeasured.

## Data-collection plan (needed before any threshold change or retraining)
Frames come from the same camera configuration either by (a) temporarily restoring the ENTC firmware and using the proven read-only
`tools/firmware/capture_live_frame.py` (160×120 RGB565, same OV2640 tables), or (b) a future diagnostic build that keeps a copy of the
80×80 model input for SWD readout (19.2 KB of RAM is available). Both need approval.
| Set | Minimum for evaluation | For retraining a "no fruit" class |
|---|---|---|
| each of the 5 fruits, focused, demo lighting | 30 | 200–300 |
| empty scenes / backgrounds (table, hand, walls, textured cloth) | 50 | 500+ |
| non-fruit objects (various colours/shapes) | 50 | 500+ |
| blurred / low-light fruit | 20 each | — |
Acceptance criteria for a new threshold (chosen on one half, tested on the other): false fruit on empty + non-fruit ≤ 2 % (with its
95 % interval reported), real-fruit acceptance ≥ 50 %, accuracy when shown ≥ 90 %. Retraining requires separate approval.

## Update 2026-10-17 (evening): first real fruit accepted by the gate (thresholds unchanged)
The implementation is unchanged: `app/fv_presence.c` with detail ≥ 43.96 (`configs/presence_gate.json`) AND confidence ≥ 0.976.

New real-camera evidence comes from the `fv_app_v8_diag` captures. That build has the same gate code as v5. The device and Python outputs matched bit-exactly.

| Real frame | detail | banana conf | shown |
|---|---|---|---|
| banana, defocused / off-position (5 frames) | 11.4–38.0 | ≤ 0.16 (top class guava) | no (correct: no usable banana in view) |
| banana, sharp but off-centre (1 frame) | 350.7 | 0.738 | no (confidence below 0.976) |
| **banana, focused and well placed (4 frames)** | **445.0–452.7** | **0.988–0.996** | **yes** |

What this shows:
* A focused, well-framed real fruit can pass both checks.
* The earlier false rejections were caused mainly by focus and framing, not by the thresholds.
* The conservative evaluation above remains valid:
  * Only banana has positive real-camera evidence.
  * The focused apple (0.852) is still a measured rejection.
  * False acceptance on real empty and non-fruit scenes is still unmeasured beyond the few frames listed.
* No threshold change is justified or made.
