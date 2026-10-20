# Model 3: dataset inspection and recommended formulation (2026-10-09)

**Scope decisions applied:**
- Shelf Life is a **range** only, apple "Not available".
- **Natural Growth % removed entirely.**
- "Growth Quality" renamed **Quality Grade**, using real 3-level labels only;
  apple stays binary.
- No IEEE DataPort / FreshLab.

Nothing was generated or trained. Models 1 and 2 are untouched.

## 1. Inspection of the four CC BY 4.0 Mendeley datasets

Sizes and structure were checked first through the Mendeley API. Zip contents
were read remotely from each archive's index (HTTP range requests), with
full or partial download only where needed.

| | Banana day0–7 ([d5tczj7fs7](https://data.mendeley.com/datasets/d5tczj7fs7) v2) | Ripen Banana / carbide ([j9sp322drp](https://data.mendeley.com/datasets/j9sp322drp/1)) | Guava digital + thermal ([5kptnn7ycr](https://data.mendeley.com/datasets/5kptnn7ycr/1)) | Banana & Guava grades ([56td5w4wz2](https://data.mendeley.com/datasets/56td5w4wz2/2) v2) |
|---|---|---|---|---|
| Size | 2.18 GB zip (288 JPEGs, ~7.6 MB each) | 8.7 GB (two zips: With / Without Carbide) | 8.3 GB, 3,959 files | 476 MB zip, 1,748 JPEGs (1024²) |
| What was fetched | zip index + 24 images (3 bananas) | folder listing only | folder listing only | **full download**, SHA-256 verified (`data/raw/banana_guava_quality/`) |
| Structure | `Image/Banana_ID_001…036/Day_0…Day_7.jpg` | With Carbide / Without Carbide | DIGITAL PHOTOS / TI IMAGES → DAY 1–7 → maturity (immature / half / mature) → treatment (healthy, 15/30/45 cm drop, chilling injury, mixed drop); DISEASED separate | Banana / Guava → Class_A / Class_B / Defect |
| Fruits | banana | banana | guava | banana, guava |
| Labels | day 0–7 only | natural vs carbide ripening, 2-hourly | elapsed day, maturity, damage treatment, disease | Class A / Class B / Defect |
| Storage-day info | yes (day index) | yes (hours, one 7-day batch) | yes (day 1–7 at 15–18 °C, 65–70% RH) | **none** |
| Individual fruits tracked? | **claimed, but unreliable:** 122 / 288 files are byte-identical copies, mostly *across* banana IDs (e.g. one image is Day_7 of 7 different IDs). The 36 IDs collapse to **12 independent groups**. Visual check: "ID_001" shows different bananas on different days; another ID repeats one photo on days 5–7. | no | **no IDs** (camera filenames); per-day counts suggest re-photographed fruit, but they cannot be linked | n/a |
| End-of-life label | none | none | none (disease is a separate folder, not per day) | n/a |
| Licence | CC BY 4.0 | CC BY 4.0 | CC BY 4.0 | CC BY 4.0 |
| **Usable for** | **Nothing reliable.** Day labels and fruit identity are corrupted by duplicates, and there is no endpoint. | Nothing in scope (Natural Growth removed). Not downloaded. | **Not for remaining shelf life**: elapsed days only, no endpoint, no fruit IDs. Not downloaded. | **Quality Grade for banana and guava** |

### Banana & Guava grades: detailed audit (`reports/dataset_audit/banana_guava_quality/`)
- **Label noise:** 38 byte-identical images appear in two classes, always
  **neighbouring** (15 Class A/B, 23 Class B/Defect). Both copies must be
  dropped.
- **Usable after removal:** banana A 495 / B 252 / Defect 380; guava A 161 /
  B 179 / Defect 205. **Total 1,672.**
- **Visual check of sample sheets:**
  - banana grades follow a clear brown-spotting progression;
  - guava: A is clean yellow, B small spots, Defect large lesions.
- **Risks:**
  - all images are on white paper in one setting, so expect a domain gap to
    our device;
  - guava Class B photos often have hard side-light and shadows (a possible
    lighting shortcut);
  - guavas here are yellow/ripe, while FruitNet guavas are mostly green;
  - near-duplicates (256-bit pHash ≤ 16): 119 images in 58 groups;
  - no timestamps or session info, so grouped splits can only use pHash
    groups.

### Already-local data relevant to Model 3
- **AgriFreshNET** (non-augmented originals; `aug_*` copies excluded):

  | Fruit | Fresh (days) | Semi-fresh (days) | Rotten (days) |
  |---|---|---|---|
  | banana | 179 (1–4) | 197 (4–7) | 301 (7–13) |
  | tomato | 590 (1–10) | 292 (10–24) | 248 (24–35) |
  | brinjal | 236 (1–4) | 254 (4–8) | 153 (8–15) |

  The day ranges are the authors' per-folder storage annotations. Capture
  dates confirm batches were tracked from fresh into rotten folders.
  Known issues (Model 1 audit): capture-session clustering, and the brinjal
  purple/green variety skew.
- **FruitNet** apple Good 1,134 / Bad 1,141 (after the earlier mislabel
  removal): binary.

## 2. Recommended Model 3 formulation (most defensible)

### 2.1 Quality Grade (3-level where real, binary for apple)
| Fruit | Source labels | Grade mapping (declared convention) | Usable images |
|---|---|---|---|
| Banana | Class A / Class B / Defect (56td5w4wz2) | Good / Average / Poor | 1,127 |
| Guava | Class A / Class B / Defect (56td5w4wz2) | Good / Average / Poor | 545 |
| Tomato | Fresh / Semi-fresh / Rotten (AgriFreshNET) | Good / Average / Poor | 1,130 |
| Brinjal | Fresh / Semi-fresh / Rotten (AgriFreshNET) | Good / Average / Poor | 643 |
| Apple | Good / Bad (FruitNet) | **Good / Poor only** (no Average) | 2,275 |

One scheme per fruit; schemes are never mixed. For banana, Class A/B/Defect
is used because it is a quality grade. AgriFreshNET banana stages serve
shelf life (§2.2). For tomato and brinjal the only 3-level label is a
**freshness stage**, so their Quality Grade and shelf-life stage come from the
same labels; this must be stated in the output documentation.

### 2.2 Shelf Life: estimated remaining-shelf-life RANGE
The only data that ties storage time to an observed end-of-life is
AgriFreshNET: each fruit's **Rotten** band start marks the end of the
annotated shelf life. The defensible formulation is a **3-stage classifier
(Fresh / Semi-fresh / Rotten) plus a fixed, documented lookup** of the
remaining-days range implied by the dataset's own day bands:

remaining range for a stage = [rotten_start − stage_end, rotten_start − stage_start]

| Fruit | Fresh | Semi-fresh | Rotten |
|---|---|---|---|
| Banana (rotten from day 7) | 3–6 days | 0–3 days | 0 (end of shelf life) |
| Tomato (rotten from day 24) | 14–23 days | 0–14 days | 0 |
| Brinjal (rotten from day 8) | 4–7 days | 0–4 days | 0 |
| Guava | **Not available** (time labels without any end-of-life label) | | |
| Apple | **Not available** (no storage-time data) | | |

Caveats that must ship with the output:
- The ranges describe AgriFreshNET's storage conditions (ambient,
  Bangladesh, Nov–Jan). They are **not** temperature-adjusted, and no real
  data here supports a temperature adjustment.
- Labels are per **folder** (stage), not per fruit. The model can only say
  which stage, and the range is a property of that stage. It adds no
  precision beyond the stage.
- The tomato ranges are wide (0–14, 14–23 days). That is the honest
  resolution of the data.

### 2.3 Not recommended
- **Banana day0–7** for anything: duplicate-corrupted identities and day labels.
- **Guava day-wise** for shelf life: no endpoint and no fruit IDs.
  Downloading 8.3 GB is not justified for Model 3.
- **Ripen Banana** (carbide): out of scope after Natural Growth was removed.
- Any synthetic shelf-life or quality data: real labels exist for every
  output we keep.

### 2.4 Suggested model structure (for the training phase, not implemented)
Reuse Model 1's locked feature extractor (frozen) and add small per-fruit heads:
- Model 1's fruit output selects the head;
- stage heads for banana, tomato and brinjal;
- grade heads for banana and guava;
- apple binary.

STM32 cost would be a few KB of dense weights on top of Model 1, with
no second backbone. Splits must be grouped by capture session (AgriFreshNET
bursts) or pHash groups (grade dataset). Report per-fruit metrics and
carry over the brinjal variety and background caveats from Model 1.

## 3. Decisions needed before training
1. Accept the Quality Grade mapping table (§2.1), including that tomato and
   brinjal grade = freshness stage.
2. Accept the shelf-life formulation (§2.2), stage → fixed range, with guava
   and apple "Not available".
3. Accept the frozen-Model-1-backbone + per-fruit-heads structure (§2.4), or
   train separate small models?
