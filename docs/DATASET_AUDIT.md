# Dataset audit — FruitNet + AgriFreshNET (2026-10-08)

Both archives were downloaded from Mendeley Data and their SHA-256 checksums
match the published values (`scripts/download_datasets.py`).
Reproduce everything with:

```
python scripts/inspect_dataset.py --source fruitnet      # raw audit per folder
python scripts/inspect_dataset.py --source agrifreshnet
python scripts/prepare_dataset.py                        # manifest, dedupe, split
python scripts/audit_dataset.py                          # sheets, stats, bias probe
```

## Visual label verification (user action)

Sample sheets for every fruit × condition × source:
`reports/dataset_audit/_combined/sheets/*.jpg`. The matching `.txt` lists
the file shown in each numbered cell. Raw per-folder sheets, including
excluded folders, are in `reports/dataset_audit/<source>/samples/`.

## Final usable data

8,457 images (6,146 train / 1,299 val / 1,012 test).

| Fruit | Condition | Source | Train | Val | Test | Total | Split groups* |
|---|---|---|---|---|---|---|---|
| apple | fresh | FruitNet | 837 | 163 | 134 | 1,134 | 4 |
| apple | spoiled | FruitNet | 744 | 256 | 141 | 1,141 | 4 |
| banana | fresh | FruitNet + AgriFreshNET | 844 | 337 | 105 | 1,286 | 13 |
| banana | spoiled | FruitNet + AgriFreshNET | 1,169 | 93 | 126 | 1,388 | 20 |
| guava | fresh | FruitNet | 799 | 156 | 197 | 1,152 | 8 |
| guava | spoiled | FruitNet | 888 | 112 | 129 | 1,129 | 5 |
| tomato | fresh | AgriFreshNET | 419 | 85 | 86 | 590 | 22 |
| tomato | spoiled | AgriFreshNET | 173 | 38 | 37 | 248 | 18 |
| brinjal | fresh | AgriFreshNET | 164 | 37 | 35 | 236 | 14 |
| brinjal | spoiled | AgriFreshNET | 109 | 22 | 22 | 153 | 24 |

\* Independent groups (capture bursts plus near duplicates). Whole groups go
to one split, which is why per-class ratios deviate from 70/15/15.

By fruit: banana 2,674 · guava 2,281 · apple 2,275 · tomato 838 · brinjal 389.
By condition: fresh 4,398 · spoiled 4,059.
By source: FruitNet 6,756 · AgriFreshNET 1,701.

## What was removed and why

| Removed | Count | Reason |
|---|---|---|
| AgriFreshNET `aug_*` files | 1,833 in target classes | Pre-augmented flipped/rotated copies of other images used to pad every class to exactly 590 |
| AgriFreshNET semi-fresh | 1,770 | Not part of the binary scheme (kept in the manifest as `excluded`) |
| FruitNet Mixed | 1,074 | Piles of several fruits of mixed quality, so no single label |
| FruitNet Apple_Good burst `IMG202007301326*` | 15 | **Mislabel**: a banana on grass |
| Exact duplicates | 6 | Same file bytes |
| Corrupt files | 0 | none |

## Problems detected

1. **Capture bursts, so far fewer independent samples than images.** FruitNet
   was shot as continuous bursts (median gap 1 s); one group has 665 frames.
   Apple and guava have only **4–8 independent groups per class**. The test
   set therefore holds roughly 1 capture session per FruitNet class, so test
   metrics will be noisy and session-dependent.
2. **Background/source shortcut in FruitNet (high risk).** Fresh images are
   mostly outdoors on varied backgrounds. Spoiled images are mostly held in a
   hand over a cream floor (mean border brightness 0.50–0.55 fresh vs 0.65–0.74
   spoiled). A linear model on border colour and global colour stats alone
   predicts guava condition at **84%** (chance 51%) and banana at 81%.
   Banana's figure is partly legitimate, since rotten bananas are darker.
3. **Source is identifiable.** Without image-size features the same probe
   recognises the source 92% of the time (chance 80%). Apple and guava come
   only from FruitNet; tomato and brinjal only from AgriFreshNET.
4. **Brinjal variety confound.** Fresh brinjal is overwhelmingly a
   green-striped round variety; purple brinjal is concentrated in the spoiled
   class. A colour heuristic (checked by eye on
   `reports/shortcut/brinjal_variety/tag_purple.jpg`) tags **12 / 236 fresh
   (5%)** vs **47 / 153 spoiled (31%)** as purple. *Correction:* the first
   version of this audit said every fresh brinjal was green; that came from a
   24-image sample sheet and was wrong. Brinjal also has the fewest images (389).
5. **AgriFreshNET labels are by storage days, not appearance.** Some "fresh"
   bananas have large brown patches, and some "rotten" tomatoes look intact.
6. **Class imbalance** across fruits (banana 2,674 vs brinjal 389) and for
   tomato (590 fresh vs 248 spoiled). `train.py` balances with per-sample
   weights over the fruit × condition cells.
7. **The 64-bit pHash was unreliable on plain backgrounds.** It matched
   tomato and brinjal on the same white cloth. Replaced by a 256-bit pHash
   (0 cross-fruit pairs up to 40 bits), threshold 16 bits.
8. **Automatic cross-fruit mislabel scanning does not work.** ImageNet
   MobileNetV2 called the known banana burst "slug". Other mislabels can only
   be found by eye.

## Input size and architecture recommendation (pre-training)

No accuracy has been measured. The recommendation is based on the measured
flash/RAM budget (docs/DEPLOYMENT_BUDGET.md) and on the data:

- Keep **MobileNetV2 α = 0.35** (smallest with ImageNet weights).
- Do **not** lock the architecture. Run a short controlled sweep on the same
  splits: input **{64, 80, 96} px** × cut **{block_13_expand_relu (189 KB),
  block_15_add (326 KB), block_16_project_BN (404 KB)}**, then pick by
  validation macro-F1 per fruit and the STM32Cube.AI arena report.
- Prior expectation: **80 px + block_15_add** as the balanced candidate.
  96 px exceeds the 128 KB main SRAM on activations alone (≥ 135 KB) and is
  only for measuring how much accuracy the smaller inputs lose. 64 px risks
  losing small rot spots.
- The full backbone (589 KB INT8) does not fit and is excluded.
- Because of problem 1, also use **group k-fold cross-validation** on
  train+val for model selection, and report per-source and per-fruit metrics.
  Do not rely on one aggregate number.
- Against problem 2: strong crop/zoom and colour-jitter augmentation, and a
  per-source / per-background error analysis after the first run.
