# Viva preparation: defensible answers

Every number cites its evidence type:
- **[PUBLIC]**: public-dataset test set;
- **[SYNTH]**: synthetic data;
- **[HOST]**: measured on the development PC;
- **[NOT DONE]**: not performed.

**Q1. Does your system detect pesticide residue?**
No.
- The camera models classify fruit type and *visible* condition.
- The sensor model (Model 2) outputs an *estimated risk category* but was
  trained only on synthetic data, because no public dataset pairs these
  sensors with pesticide labels (docs/MODEL2_DATA_RESEARCH.md).
- Residue levels can only be established by laboratory analysis
  (LC-MS/MS / GC-MS). Our calibration protocol describes how real labelled
  data would be collected.

**Q2. What accuracy do you achieve?**
- Model 1 held-out test: fruit F1 **0.822**, fresh/spoiled F1 **0.679**
  [PUBLIC].
- After INT8 conversion run in TFLite-Micro: 0.818 / 0.690 [HOST].
- Model 3 grades: banana 0.82, guava 0.87; tomato and brinjal stages ~0.55;
  apple 0.46 [PUBLIC].
- Model 2 macro-F1 0.772 is **[SYNTH]** only. It shows the pipeline
  recovers our own generator's assumptions, not real detection performance.

**Q3. Why is the test score lower than validation?**
- Capture-session dependence and background shortcuts: FruitNet classes have
  only 4–8 independent sessions.
- The background-only CNN still reached 0.81 F1 on apple condition; the
  banana cross-source fruit recall was 26%.
- We report test, not validation (docs/TRAINING_REPORT_01.md).

**Q4. Why MobileNetV2-0.35 at 80×80, cut at block_15?**
- The full backbone is 589 KB INT8 > 512 KB flash.
- 96 px needs ≥ 135 KB of activations.
- 80 px with block_15 was the best fruit F1 in a capture-group-aware
  architecture sweep [PUBLIC] that fits flash.

**Q5. Does it run on the STM32?**
Not demonstrated [NOT DONE].
- The INT8 model is 358 KB, with all operators supported by TFLite-Micro
  [HOST].
- The measured TFLite-Micro arena is 155.7 KB, which exceeds the 128 KB
  contiguous main SRAM; the camera frame buffer also needs DMA-reachable
  RAM.
- Next steps: STM32Cube.AI memory analysis, or a 64 px retrain (needs
  approval).
- Model 2 compiles for Cortex-M4F at 768 B and matches Python to 4.8e-7
  [HOST, compile-only].

**Q6. How do you handle unreliable inputs?**
- Images: rejected if corrupted, uniform, noise-like or grayscale.
  Thresholds sit at half the minimum over 10,869 real photos, so 0% of
  those are rejected.
- Sensors: rejected if missing, NaN, at a rail, saturated or out of range.
- Low fruit confidence (< 0.976, chosen by Youden's J on validation)
  withholds grade and shelf life.
- Uncalibrated device readings never produce a risk category.
- Every output says `predicted`, `uncertain` or `unavailable`.

**Q7. Is the 0.976 confidence a probability?**
- No. Softmax scores are uncalibrated. A grey frame received 0.997 "guava"
  before the image checks were added.
- The threshold is an empirically chosen operating point that flags 88% of
  wrong-fruit predictions on test, at the cost of withholding 41% of
  correct ones [PUBLIC].

**Q8. Where does the shelf-life number come from?**
- A fixed lookup from AgriFreshNET's per-folder day bands: e.g. a banana
  classified "Fresh" means 3–6 days remaining under that dataset's ambient
  storage.
- It is not a regression and not a guarantee; guava and apple are "Not
  available" (no data).

**Q9. What would you do with more time?**
- (1) Collect OV2640 images and reference-labelled sensor data
  (SENSOR_CALIBRATION_PROTOCOL.md).
- (2) Resolve the RAM blocker.
- (3) Re-derive the confidence threshold on the deployed INT8 runtime.
- (4) Add a trained out-of-distribution / "no fruit" class.

**Q10. What did you deliberately NOT do?**
- No fabricated labels, no "Natural Growth %", no ppm output, no combined
  safety score.
- Synthetic metrics are never presented as real.
- The frozen models are unchanged; hashes are verified.
