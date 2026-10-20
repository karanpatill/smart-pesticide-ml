# Model 3: Shelf Life, Natural Growth, Growth Quality, data research (2026-10-09)

**Status: research only.** No data downloaded for Model 3, nothing generated,
nothing trained. Model 1 and Model 2 artifacts are untouched.
Fruits: apple, banana, guava, tomato, brinjal.

## 1. Candidate datasets

| # | Dataset (source) | Fruits (of our 5) | Size | Labels / targets | Real or inferred | Licence / access | Downloadable? | Shelf life | Natural growth | Growth quality | Major limitations |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **FreshLab-Tomato** ([IEEE DataPort, DOI 10.21227/wvqh-5c80](https://ieee-dataport.org/documents/freshlab-tomato-longitudinal-shelf-life-dataset)) | tomato | 1,080 images; **12 individual tomatoes** × 10 days × 3 storage conditions (ambient / refrigerated / outdoor) × 3 views × 3 times a day | observation day, storage condition, **temperature, RH**, **5-point visual spoilage score**, notes | **Real**, longitudinal per fruit (score is a visual rating, not a lab measurement) | Licence not stated; **subscription/login required** | Only with an IEEE DataPort account/subscription (not verified) | **Best real source**: per-fruit trajectories, so remaining days to a spoilage-score threshold can be *derived*, with censoring | No | Score 1–5 could be binned (binning must be declared) | Only 12 fruits (tiny); 10-day window may not reach end-of-life (censoring); one cultivar/site |
| 2 | **banana_ripening_dataset_day0_to_day7** ([Mendeley d5tczj7fs7](https://data.mendeley.com/datasets/d5tczj7fs7), v2, 2026) | banana | ~30 individual bananas (description) × 8 daily images. A third-party project reports 528 images / 66 IDs with duplicates collapsing to 17 groups ([repo](https://github.com/LeeRuiDa/banana-shelf-life-predictor)) | day 0–7 per banana ID | **Real** elapsed days per individual fruit | CC BY 4.0 | Yes (public) | Elapsed days: real. Remaining days only if a "rotten" endpoint is defined and reached within 7 days | No | No quality labels | Small; sample count inconsistent between sources; duplicates reported; no stated end-of-life; one setup |
| 3 | **Ripen Banana (carbide vs natural)** ([Mendeley j9sp322drp](https://data.mendeley.com/datasets/j9sp322drp/1), CC BY 4.0, 2025) | banana | 1,404 original photos (1,093 natural, 311 carbide-treated) + 6,410 augmented | **natural vs calcium-carbide ripening**, ripening stage, photos every 2 h over 7 days | **Real** (controlled experiment) | CC BY 4.0 | Yes | Weak: elapsed hours in one 7-day batch | **Closest real label** to "natural": *natural vs chemically ripened* (binary, banana only), not a growth % | Ripening stages, not quality | Single batch/site (Bangladesh, Sabri banana); augmented copies mixed in; carbide set reaches ripeness by day 2 |
| 4 | **Guava digital & thermal images** ([Mendeley 5kptnn7ycr](https://data.mendeley.com/datasets/5kptnn7ycr/1), CC BY 4.0, 2023) | guava | 2,095 digital (600 healthy, 1,100 damaged, 395 diseased) + 1,821 thermal | **day-wise** (up to 7 days), **maturity** (immature / half / mature), drop-height damage, disease type; stored at 15–18 °C, 65–70% RH | **Real** | CC BY 4.0 | Yes | Elapsed days (≤ 7) at one storage condition; per-fruit identity not confirmed | No (maturity stage is not growth %) | healthy / damaged / diseased (defect type, not a grade) | Damage is induced by drop tests; per-fruit tracking unclear |
| 5 | **Banana & Guava non-destructive quality** ([Mendeley 56td5w4wz2](https://data.mendeley.com/datasets/56td5w4wz2/2), CC BY 4.0) | banana, guava | 1,738 images | **Class A / Class B / Defect** "according to maturity stages" | **Real** (grading criteria only briefly described) | CC BY 4.0 | Yes | No time labels | No | **Real 3-level grade**, the most direct source for Good / Average / Poor | Grading protocol not detailed; phone images in sunlight; no apple/tomato/brinjal |
| 6 | **AgriFreshNET** (already downloaded; [Mendeley 42m5tb7yv9](https://data.mendeley.com/datasets/42m5tb7yv9/1)) | banana, tomato, brinjal | 590 / class incl. `aug_` copies. Originals (fresh / rotten): banana 179 / 301, tomato 590 / 248, brinjal 236 / 153; semi-fresh originals not yet counted | Fresh / Semi-fresh / Rotten + **per-folder day range** (e.g. banana 1–4 / 4–7 / 7–13 days) | Day ranges are **real but coarse, per folder**. Capture dates confirm batches tracked over days (banana fresh from 2 Nov, semi from 5 Nov, rotten from 9 Nov) | CC BY 4.0 | Yes (local) | Coarse **elapsed-day bands**; no per-fruit identity; remaining days only as an interval | No | **Real 3-level freshness** (Fresh / Semi / Rotten) | Freshness, not "growth quality"; same-session bias (Model 1 audit); purple/green brinjal skew |
| 7 | **FruitNet** (already downloaded) | apple, banana, guava | ~6.8k usable | Good / Bad (+ Mixed) | Real, criteria undefined | CC BY 4.0 | Yes (local) | No time | No | **Binary only**: no "Average" | Background shortcut (see Model 1 report) |
| 8 | **Guava Good/Bad** ([Mendeley 6sz8vjhsxf](https://data.mendeley.com/datasets/6sz8vjhsxf), CC BY 4.0, 2025) | guava | not stated | Good / Bad | Real | CC BY 4.0 | Yes | Shelf-life text is general background (3–4 days at room temp), not per-sample | No | Binary | Small/unclear |
| 9 | **Multimodal perishable F&V** (Data in Brief, [DOI 10.1016/j.dib.2026.112545](https://doi.org/10.1016/j.dib.2026.112545)) | guava, tomato, banana | ~14k sRGB + 14.5k IR-fusion images, 18 **methane** sensor files, 18.99 GB | Spoiled / Not_spoiled; decomposition time series | Real; how spoilage was decided is not stated | Not confirmed | Repository not identified | Possibly (time series + gas), but per-image time and fruit identity unconfirmed | No | Binary | Unverified access; 19 GB |
| 10 | **Food Freshness E-Nose** (Zenodo 17285312, already downloaded) | banana, tomato | MQ2–MQ135 time series, day 1–5 | storage day | **Real** elapsed day | CC BY 4.0 | Yes (local) | Sensor-based elapsed day (≤ 5 days); one batch per fruit | No | No | Very few fruits per day; no endpoint |
| 11 | Thermal & visible organic / non-organic ([Mendeley pwzk7dj5wf](https://data.mendeley.com/datasets/pwzk7dj5wf/1)) | apple | ~160 apples | organic vs non-organic | Real | Mendeley (licence to confirm) | Yes | No | Related concept (organic), **not** a growth % | No | Apple only; small |
| 12 | FruitVision ([Mendeley xkbjx8959c](https://data.mendeley.com/datasets/xkbjx8959c)) | apple, banana | 10k originals → 81k augmented | fresh / rotten / **formalin-mixed** | Real | Mendeley | Yes | No | Adulteration, not growth | Binary-ish | Heavy augmentation |
| 13 | Postharvest literature (e.g. [UC Davis eggplant](https://postharvest.ucdavis.edu/node/8076); tomato/guava storage studies) | all 5 (tables) | — | reference storage life vs temperature | Real reference values, but **not datasets** | — | — | Usable only as **documented heuristic** ranges, not ML labels | No | No | Cultivar- and condition-specific |

**Apple:** no public dataset with storage-time, shelf-life or 3-level quality
labels was found. Only FruitNet Good/Bad, FruitVision fresh/rotten/formalin
and the organic/non-organic set.
**Brinjal:** only AgriFreshNET (coarse day bands, 3-level freshness).

## 2. Conclusions per output

### 2.1 Shelf Life (remaining days)
- **No dataset labels remaining shelf life directly.** What exists is
  *elapsed* storage time: per individual fruit for tomato (FreshLab) and banana
  (day0–7), and coarse per-folder bands for AgriFreshNET and guava day-wise.
- Remaining days can be **derived** only where (a) individual fruits are
  tracked and (b) a declared end-of-life event (e.g. FreshLab spoilage score ≥
  a threshold, or the dataset's "rotten" stage) is observed: remaining =
  end-day − current-day. Fruits that never reach the endpoint within the window
  are **right-censored**, which calls for a survival or interval treatment, not
  plain regression.
- Remaining life strongly depends on **storage temperature** (FreshLab's
  ambient / fridge / outdoor arms; guava 3–4 days ambient vs 1–3 weeks at
  8–10 °C).
- **Learnable from real labels:** tomato (FreshLab, if accessible; 12 fruits,
  so very small), banana (day0–7, small) and coarse banana/tomato/brinjal
  bands (AgriFreshNET). **Not learnable for apple** (no data). Guava only as
  elapsed day at one storage condition. Any output must be a **fruit- and
  condition-specific range**, not precise days.

### 2.2 Natural Growth %
- **No defensible real target exists.** No dataset or established
  measurement defines a "natural growth percentage" for harvested fruit, and
  it would not be appropriate to invent a biological definition.
- Real, related labels:
  - *natural vs chemically ripened* (banana only, carbide; #3);
  - *formalin-treated* (apple, banana; #12);
  - *organic vs non-organic* (apple only; #11);
  - *maturity/ripeness stage* (guava #4, banana #3).
- None of these is a percentage. A classifier probability for one of them
  is not a "growth %" either.
- **Recommendation:** drop this output, or replace it with a clearly named,
  real label (see §3). Needs your decision.

### 2.3 Growth Quality (Good / Average / Poor)
- **Real 3-level labels exist, but they are post-harvest grades or freshness,
  not "growth" quality:**
  - Class A / Class B / Defect: banana, guava (#5);
  - Fresh / Semi-fresh / Rotten: banana, tomato, brinjal (#6);
  - 5-point spoilage score: tomato (#1). Binning it would be a stated
    choice, e.g. 1–2 / 3 / 4–5.
- **Apple has only binary labels** (Good / Bad). Producing "Average" for
  apple would mean inventing labels.
- Overlap: Fresh / Semi / Rotten largely duplicates Model 1's fresh/spoiled
  output plus one middle level.

## 3. Most defensible prototype strategy (proposal; NOT implemented)
1. **Shelf Life → "estimated remaining shelf-life range" (prototype).**
   - Learn elapsed storage day / stage from real time-labelled images:
     banana (#2, #6), tomato (#1 if accessible, #6), brinjal (#6 bands),
     guava (#4).
   - Convert to remaining days only through each dataset's **declared
     endpoint**, with censoring handled, and report a range, e.g. "~2–4 days
     at ambient".
   - The DHT22 storage temperature could be used only through a clearly
     labelled literature heuristic (no real labels for that adjustment exist
     here).
   - **Apple:** output "not available" or a literature reference range marked
     as heuristic, never an ML prediction.
2. **Natural Growth:** **do not implement as a percentage.** Options:
   - (a) remove it;
   - (b) replace with "Ripeness stage" (real labels for banana/guava/tomato);
   - (c) replace with "Natural vs chemically ripened" for banana only,
     shown as a class with confidence, never as a growth %.
3. **Growth Quality → "Quality grade" (rename suggested).**
   - Use real 3-level labels where they exist: Class A/B/Defect → Good /
     Average / Poor for banana and guava (#5); Fresh / Semi / Rotten for
     banana, tomato and brinjal (#6). The mapping must be stated as a
     convention.
   - **Apple: binary only** (Good / Poor) unless new labelled data is
     collected.
   - Pick one consistent label definition per fruit and do not mix grading
     schemes silently.
4. Synthetic data would add nothing for these targets except pipeline
   testing. The real labels above are better, even though they are small and
   coarse.

## 4. Decisions needed
- **D1 (Shelf life):** accept range/interval output from elapsed-day labels
  with declared endpoints, apple excluded or heuristic? Should I attempt to
  get FreshLab-Tomato access (requires your IEEE DataPort account)?
- **D2 (Natural growth):** remove, or replace with (b) ripeness stage or
  (c) natural vs carbide-ripened (banana only)?
- **D3 (Quality):** accept "Quality grade" from Class A/B/Defect and
  Fresh/Semi/Rotten mappings, binary for apple?
- **D4 (Downloads):** approve downloading #2, #3, #4, #5 (Mendeley, CC BY 4.0)
  for inspection. Their sizes still need checking before download.
