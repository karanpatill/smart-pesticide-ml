# Model 3: Quality Grade + estimated shelf-life range (artifacts 2026-10-09)

Built on **Model 1's frozen feature extractor** (56-d `gap` features) with small
per-fruit heads. Model 1's predicted fruit selects the head. **No Natural
Growth output exists.** Shelf life is **not regressed**: a stage head plus a
fixed, documented range table. Model 1 and Model 2 are unchanged; Model 1's
SHA-256 was checked before and after (`fc3f9ecc…`).

## Formulation (approved)
| Fruit | Quality Grade (labels → grade) | Shelf life |
|---|---|---|
| Banana | Class A / B / Defect → Good / Average / Poor (`quality_banana`) | AgriFreshNET stage head (`stage_banana`) → Fresh 3–6 d · Semi-fresh 0–3 d · Rotten 0 |
| Guava | Class A / B / Defect → Good / Average / Poor (`quality_guava`) | **Not available** |
| Tomato | Fresh / Semi-fresh / Rotten → Good / Average / Poor (`stage_tomato`); **grade = freshness stage** | same head → Fresh 14–23 d · Semi-fresh 0–14 d · Rotten 0 |
| Brinjal | Fresh / Semi-fresh / Rotten → Good / Average / Poor (`stage_brinjal`); **grade = freshness stage** | same head → Fresh 4–7 d · Semi-fresh 0–4 d · Rotten 0 |
| Apple | Good / Bad → **Good / Poor only** (`quality_apple`) | **Not available** |

Shelf-life ranges (`configs/model3_shelf_life.yaml`) describe **AgriFreshNET's
storage conditions** (ambient, Bangladesh, Nov 2025 – Jan 2026). They are not
universal guarantees, are not temperature-adjusted, and add no information
beyond the predicted stage.

## Data and splits (`scripts/model3_prepare.py` → `data/model3/manifest.csv`)
- **Leakage control:** images the frozen extractor was trained on (FruitNet
  apple; AgriFreshNET banana/tomato/brinjal fresh & rotten) **inherit Model 1's
  train/val/test split**. Images Model 1 never saw (all semi-fresh folders, the
  56td5w4wz2 grade set) get a new stratified group split (70/15/15).
- **Groups:** AgriFreshNET capture bursts + 256-bit pHash near-duplicates
  (≤ 16 bits). The grade set has no time info, so groups are pHash only.
- **Removed:** `aug_*` copies; **76** grade images (38 byte-identical pairs with
  conflicting neighbouring labels); 9 same-label exact duplicates.

| Head | Train / Val / Test | Classes (test) | Split origin | Independent groups |
|---|---|---|---|---|
| quality_banana | 789 / 169 / 169 | Good 74 · Average 38 · Poor 57 | new | 1,107 (pHash only) |
| quality_guava | 381 / 82 / 82 | Good 24 · Average 27 · Poor 31 | new | 543 (pHash only) |
| quality_apple | 1,581 / 419 / 275 | Good 134 · Poor 141 | inherited (Model 1) | few capture sessions (Model 1 audit: 4 per class) |
| stage_tomato | 793 / 168 / 167 | Fresh 86 · Semi 44 · Rotten 37 | inherited + new | 61 |
| stage_brinjal | 450 / 97 / 96 | Fresh 35 · Semi 39 · Rotten 22 | inherited + new | 54 |
| stage_banana | 479 / 100 / 91 | Fresh 20 · Semi 27 · Rotten 44 | inherited + new | 33 |

## Training (`scripts/model3_train.py`)
Frozen Model 1 features; train set = clean image + 4 augmented views (Model 1's
augmentation config). Candidate heads: linear (Dense softmax) or mlp16 (Dense
16 ReLU → Dropout 0.3 → softmax), L2 1e-4, Adam 3e-3, balanced class weights,
early stopping on VAL loss. **Pre-registered rule:** linear unless mlp16 beats
it by more than 0.02 VAL macro-F1. Selected: mlp16 for banana grade, apple and
tomato; linear for guava grade, brinjal and banana stage.

## Results (macro-F1; per-class P/R/F1 and confusion matrices in `reports/model3/<head>/`)
| Head | VAL macro-F1 | **TEST acc** | **TEST macro-F1** | TEST per-class F1 | Model 1 routes test images to this head | End-to-end TEST acc (incl. routing errors) |
|---|---|---|---|---|---|---|
| quality_banana | 0.909 | 0.840 | **0.822** | Good 0.84 · Average 0.66 · Poor 0.96 | 100% | 0.840 |
| quality_guava | 0.925 | 0.866 | **0.870** | Good 0.91 · Average 0.85 · Poor 0.84 | **45%** | **0.366** |
| quality_apple | 0.959 | 0.531 | **0.456** | Good 0.25 · Poor 0.66 | 70% | 0.345 |
| stage_tomato | 0.687 | 0.569 | **0.554** | Fresh 0.64 · Semi 0.46 · Rotten 0.56 | 96% | 0.545 |
| stage_brinjal | 0.638 | 0.552 | **0.545** | Fresh 0.44 · Semi 0.58 · Rotten 0.62 | 92% | 0.510 |
| stage_banana | 0.795 | 0.956 | **0.955** | Fresh 0.97 · Semi 0.92 · Rotten 0.97 | 98% | 0.934 |

TEST confusion matrices (rows = true):
- quality_banana: [[61, 13, 0], [10, 26, 2], [0, 2, 55]]
- quality_guava: [[21, 1, 2], [0, 23, 4], [1, 3, 27]]
- quality_apple: [[22, 112], [17, 124]]
- stage_tomato: [[47, 17, 22], [12, 21, 11], [1, 9, 27]]
- stage_brinjal: [[12, 11, 12], [7, 21, 11], [0, 2, 20]]
- stage_banana: [[19, 1, 0], [0, 24, 3], [0, 0, 44]]

### Interpretation
- **Banana and guava grades work within their dataset** (0.82 / 0.87 test F1).
  "Average" is the weakest banana class (0.66). The grade set offers only pHash
  grouping, so repeated shots of one fruit may sit on both sides of the split;
  these scores may be optimistic.
- **Guava is limited by routing, not the head.** Model 1 recognises only 45% of
  these yellow, ripe guavas as guava (misrouted to apple 26, banana 11). Model 1
  was trained on mostly green FruitNet guavas, so end-to-end guava accuracy
  is 0.37.
- **Apple quality does not generalise:**
  - test 0.456 vs val 0.959; 112 of 134 Good test apples are predicted Poor;
  - this is the same capture-session / background failure seen in Model 1's
    apple condition (test F1 0.59);
  - the head was trained on features of images the extractor was trained on,
    which makes VAL look far better than TEST;
  - apple Quality Grade is the same binary label as Model 1's fresh/spoiled
    output.
- **Tomato and brinjal stages are weak** (≈ 0.55 test F1); Semi-fresh is hardest.
  The shelf-life ranges for these fruits are therefore often the wrong band.
- **The banana stage test score (0.955) is above VAL (0.795)** on a small test
  set (91 images, few capture groups), so treat it as unstable. The stage head
  is trained only on AgriFreshNET images.

### Known output-consistency issues (found in clean-process verification)
1. **Routing errors propagate.** A guava misrouted to "banana" (fruit confidence
   0.40) receives a banana grade *and* a banana shelf-life range.
2. **Banana grade and banana stage can disagree.** They come from different
   datasets. Example: a Class "Defect" banana graded Poor (0.99) while the
   AgriFreshNET stage head said Fresh (3–6 days).

Not implemented (needs a decision): abstain or "uncertain" when Model 1's
fruit confidence is low; suppress or flag shelf life when grade and stage
contradict.

## Size and STM32 practicality
| Item | Value |
|---|---|
| Model 3 head parameters (all 6 heads) | **3,385** (171–963 per head) |
| Added flash, float32 / int8 (estimate) | **~13.5 KB / ~3.5 KB** |
| Added RAM (estimate) | **~300 B** (56-d feature + 16 hidden + ≤ 3 outputs) |
| Combined model (Model 1 + heads) params | 202,904 (Model 1: 199,519) |
| Combined vs Model 1 outputs | identical (max abs diff 0.0); heads vs saved heads ≤ 6e-6 |

**The shared extractor is practical for the STM32.**
- Model 1 runs once per image, and the heads add < 2% parameters and a
  negligible amount of RAM and compute.
- Deployment needs the Model 1 graph to expose its `gap` tensor (or to be
  converted as the combined graph). Model 1's weights are unchanged either way.
- Not measured on device; no INT8 conversion was done.
- The real limits are **accuracy and routing** (guava, apple, tomato and
  brinjal stages), not size.

## Artifacts (`models/model3/`)
| File | Content |
|---|---|
| `model3_combined.keras` | Single flat graph: image → Model 1 outputs (fruit, condition) + 6 Model 3 heads (Model 1 layers shared, frozen) |
| `model3_heads.keras`, `model3_heads.weights.h5` | Heads only (input: Model 1 56-d `gap` features) |
| `labels.json` | Class order per head |
| `heads_selected.json` | linear / mlp16 choice per head |
| `shelf_life_ranges.json` | Copy of `configs/model3_shelf_life.yaml` |
| `training_config.json` | Extractor path + SHA-256, head recipe, augmentation, manifest SHA-256, seed |
| `metrics.json` | VAL/TEST metrics, confusions, routing, size estimates |
| `scripts/model3_predict.py` | Inference with the final output schema |
| `reports/model3/` | Per-head reports + confusion PNGs, VAL/TEST predictions, clean-process verification |

Clean-process verification: `python -I` from another directory on 6 TEST
images (one per head), 6/6 consistent with training-time predictions
(`reports/model3/inference_verification.txt`).

## Final output schema (per image)
```json
{
  "fruit":       {"label": "apple|banana|guava|tomato|brinjal", "confidence": 0.0, "source": "Model 1"},
  "condition":   {"label": "fresh|spoiled", "confidence": 0.0, "source": "Model 1"},
  "quality_grade": {
    "label": "Good|Average|Poor  (apple: Good|Poor)",
    "confidence": 0.0,
    "scale": "3-level (Good/Average/Poor) | binary (Good/Poor)",
    "basis": "label source; for tomato/brinjal: 'grade = freshness stage'",
    "head": "quality_banana|quality_guava|quality_apple|stage_tomato|stage_brinjal",
    "source": "Model 3"
  },
  "shelf_life": {
    "status": "estimated_range | not_available",
    "range_days": [0, 0],
    "stage": "Fresh|Semi-fresh|Rotten",
    "stage_confidence": 0.0,
    "head": "stage_banana|stage_tomato|stage_brinjal",
    "basis": "AgriFreshNET folder day-range annotations",
    "disclaimer": "Estimated range under the source dataset's storage conditions; not a guarantee.",
    "reason": "(only when not_available: guava/apple explanation)",
    "source": "Model 3 stage head + fixed lookup (no regression)"
  },
  "notes": ["visual estimates from public-dataset labels", "no pesticide-residue detection", "..."]
}
```
No `natural_growth` field exists. Model 2's sensor risk output is separate and
not part of this schema.


---

# Post-processing / consistency layer (added 2026-10-09)

**No model was retrained or modified.** SHA-256 of `model1_final.keras`,
`model3_combined.keras`, `model3_heads.keras` and `model3_heads.weights.h5`
were verified unchanged after this change; Model 2 untouched. The layer is pure
Python (`src/fruitvision/postprocess.py`) driven by
`configs/model3_postprocess.json` (copied to `models/model3/postprocess_config.json`).
This section supersedes the "Not implemented" note and the output schema above.

## What changed
| File | Change |
|---|---|
| `src/fruitvision/postprocess.py` | **new**: rules R1–R3, builds the final record, keeps all raw outputs |
| `configs/model3_postprocess.json`, `models/model3/postprocess_config.json` | **new**: threshold + rule definitions + measured VAL rates |
| `scripts/model3_predict.py` | now: model outputs → `postprocess()` (previous inline formatting removed); `--no-raw` option |
| `scripts/model3_calibrate_threshold.py` | **new**: derives the threshold from VAL |
| `scripts/model3_pipeline_check.py` | **new**: clean-process end-to-end check |
| `tests/test_postprocess.py` | **new**: 11 rule tests (17 tests total pass) |
| Reports | `reports/model3/postprocess/` (threshold report + plot, VAL consistency analysis, pipeline check) |

## R1: low fruit confidence (threshold 0.976)
- **Derivation:** maximise Youden's J (fraction of correct fruit predictions
  kept minus fraction of wrong ones kept) on the VAL pool: Model 1 VAL split
  (1,299) + Model 3 new-split VAL images (364). TEST was used only to report
  the effect.
- **Effect:**

  | | Kept (routed) | Accuracy of kept vs all | Wrong-fruit predictions caught | Correct predictions also withheld |
  |---|---|---|---|---|
  | VAL | 60.9% | 97.2% vs 87.1% | 86.9% | 32.1% |
  | TEST | 50.3% | 95.5% vs 81.2% | 88.0% | 40.9% |

  Per fruit on TEST: apple 86.5% of images become "Uncertain", guava 64%,
  brinjal 34%, tomato 31%, banana 23%.
- **Behaviour below the threshold:**
  - `quality_grade.label = "Uncertain"`, `shelf_life.status = "not_available"`,
    with a reason;
  - fruit label and confidence are kept;
  - routed head outputs appear only in `raw` (`routed_outputs_used_in_final: false`).

## R2: grade vs shelf-life stage (banana only)
- **Convention:** Good ~ Fresh, Average ~ Semi-fresh, Poor ~ Rotten. Ordinal
  distance 1 → `minor_mismatch`; distance 2 → `contradiction`.
- **Neither prediction is altered.** A warning is added under
  `consistency.warnings`.
- **Not applicable:** tomato and brinjal (grade and stage are the same head
  output); apple and guava (no stage).
- **Measured on banana VAL:** 49% consistent, 29% one-level mismatch, **21%
  contradiction** (30% on grade-set images, because the AgriFreshNET-only stage
  head calls most of them "Fresh"). On routed banana TEST predictions R2 fires
  for 56%. **The banana shelf-life range is unreliable on images unlike
  AgriFreshNET.**

## R3: Model 1 condition vs quality grade (all fruits)
Warning when condition `fresh` meets grade `Poor`, or `spoiled` meets `Good`.
Nothing is altered. VAL rates: apple 10.7%, banana 7.4%, guava 12.2%, tomato
1.8%, brinjal 10.3%; routed TEST predictions 11.5%.

## Clean-process verification (`reports/model3/postprocess/pipeline_check.*`)
`python -I` from another directory on 22 inputs. All checks passed:
- R1 applied exactly when confidence < threshold;
- fruit prediction preserved;
- no routed output when uncertain;
- raw head outputs always present;
- every real banana contradiction case flagged by R2 with its predictions
  unaltered.

| Group | Inputs | Outcome |
|---|---|---|
| A. existing 6 test examples | apple, 3 banana, brinjal, tomato | 4 now "Uncertain" (fruit conf 0.40–0.80, including the misrouted guava), 1 banana R2 contradiction (grade Poor vs stage Fresh), 1 ok |
| B. real low-confidence test images | 3 misrouted + 3 correct | all 6 "Uncertain"; no wrong-fruit grade or shelf life emitted |
| C. real banana contradictions | 4 grade-set bananas | all flagged R2 contradiction (Poor vs Fresh, 3–6 d); one also R3 |
| D. constructed degraded inputs | blur / dark banana & tomato | 3 of 4 → "Uncertain"; blurred tomato stayed confident (0.982) and was passed |
| D. constructed non-fruit inputs | uniform grey, random noise | **classified guava at 0.997 / 1.000 confidence and passed R1** (grade "Average") |

**Known limitation (not fixed):** softmax confidence does not detect
out-of-distribution inputs. Non-fruit images can receive near-100% fruit
confidence and pass the threshold. Fixing this needs an out-of-distribution
or "no fruit" mechanism, which means new training or data, outside this
change's scope.

**No accuracy improvement is claimed.** The layer withholds or flags outputs.
It does not make any model more accurate, and on TEST about half of all inputs
become "Uncertain".

## Final inference schema (per image)
```json
{
  "image": "path",
  "fruit":     {"label": "apple|banana|guava|tomato|brinjal", "confidence": 0.0, "source": "Model 1"},
  "condition": {"label": "fresh|spoiled", "confidence": 0.0, "source": "Model 1"},
  "quality_grade": {
    "label": "Good|Average|Poor | Good|Poor (apple) | Uncertain",
    "confidence": 0.0,
    "scale": "3-level (Good/Average/Poor) | binary (Good/Poor) | null",
    "basis": "label source; tomato/brinjal: 'grade = freshness stage' | null",
    "head": "quality_banana|quality_guava|quality_apple|stage_tomato|stage_brinjal | null",
    "reason": "(only when Uncertain)",
    "source": "Model 3 | post-processing (R1)"
  },
  "shelf_life": {
    "status": "estimated_range | not_available",
    "range_days": [0, 0],
    "stage": "Fresh|Semi-fresh|Rotten",
    "stage_confidence": 0.0,
    "head": "stage_banana|stage_tomato|stage_brinjal",
    "basis": "AgriFreshNET folder day-range annotations",
    "disclaimer": "Estimated range under the source dataset's storage conditions; not a guarantee.",
    "reason": "(only when not_available: low routing confidence, or guava/apple has no data)",
    "source": "Model 3 stage head + fixed lookup | post-processing (R1) | Model 3"
  },
  "consistency": {
    "status": "ok | warning | uncertain",
    "warnings": [{"rule": "R1_low_fruit_confidence|R2_grade_vs_stage|R3_condition_vs_grade",
                  "severity": "uncertain|minor_mismatch|contradiction",
                  "message": "...", "details": {}}]
  },
  "raw": {
    "fruit_probabilities": {}, "condition_probabilities": {},
    "head_probabilities": {"quality_banana": {}, "quality_guava": {}, "quality_apple": {},
                           "stage_tomato": {}, "stage_brinjal": {}, "stage_banana": {}},
    "routed_quality_head": "...", "routed_stage_head": "... | null",
    "routed_outputs_used_in_final": true
  },
  "postprocess": {"version": 1, "fruit_confidence_threshold": 0.976},
  "notes": ["visual estimates from public-dataset labels", "no pesticide-residue detection",
            "shelf-life ranges reflect the source dataset's storage conditions"]
}
```
`--no-raw` omits the `raw` block. There is no `natural_growth` field.
