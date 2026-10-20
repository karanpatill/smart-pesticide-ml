# Dataset research and selection

Research date: 2026-10-08. Counts and licences come from the publishers' pages and
papers (linked). **Nothing has been downloaded yet.** Every claim marked
_(unverified)_ must be confirmed with `scripts/inspect_dataset.py` after download.

## 1. What labels actually exist

No public dataset found provides:

- a **continuous freshness score or percentage** per image, or
- a **multi-grade quality scale** (e.g. Excellent / Good / Fair / Poor),

for all five target fruits. The labels that exist are categorical:

| Label scheme | Where it exists |
|---|---|
| Good / Bad (+ "Mixed") | FruitNet: apple, banana, guava |
| Fresh / Semi-fresh / Rotten (+ shelf-life range) | AgriFreshNET: banana, tomato, eggplant |
| Fresh / Rotten | several sources (see table) |
| Healthy / disease type | BrinjalFruitX (field disease, not freshness) |

**Consequence:** the only condition label shared by all 5 fruits is **binary:
fresh vs spoiled**. The model output `Freshness: 92%` / `Quality: Excellent`
**cannot be learned from these datasets** without inventing labels. See
README § "Output limitation".

## 2. Candidate comparison

| Dataset | Target fruits covered | Condition labels | Images (relevant) | Image quality / capture | Licence | Duplicate risk | Verdict |
|---|---|---|---|---|---|---|---|
| **FruitNet** (Meshram & Patil 2022) [link](https://data.mendeley.com/datasets/b6fftwbr2v/3) | apple, banana, guava | Good / Bad / Mixed | apple 1149 G + 1141 B; banana 1113 G + 1087 B; guava 1152 G + 1129 B (≈6.8k excl. Mixed) | Phone camera, 256×256 (from 3024²), 5 background types, natural + artificial light. Paper says no augmentation | CC BY 4.0 | Low–medium (multiple shots of the same fruit likely) | **Primary for apple, guava, banana** |
| **AgriFreshNET** (Risdin et al.) [link](https://data.mendeley.com/datasets/42m5tb7yv9/1) | banana, tomato, **eggplant (brinjal)** | Fresh / Semi-fresh / Rotten + shelf-life range | ≈569/class on average → about 1.7k per fruit (unverified) | Smartphone, markets, homes, farms; varied light/background. Resolution not stated | CC BY 4.0 | Unknown: very new and not yet independently used. Must audit | **Primary for tomato, brinjal; extra banana**. The only freshness-labelled brinjal source found |
| Spoiled & Fresh Fruit Inspection (Pachón Suescun et al. 2020) [link](https://data.mendeley.com/datasets/6ps7gtp2wg) | banana, tomato | Fresh / Spoiled | 2000 tomato, 2000 banana | Controlled varied backgrounds, rotation, distance, light | CC BY 4.0 | Medium (likely sequential shots of the same fruit) | **Optional supplement** for tomato/banana source diversity |
| Fresh & Rotten Fruits (Sultana et al.) [link](https://data.mendeley.com/datasets/bdd69gyhv8) | apple, banana, guava | Fresh / Rotten | 3200 original over 16 classes (≈200/class); +12,335 augmented | Shops and fields; expert-validated | CC BY 4.0 | **High**: augmented copies (rotate/flip/zoom) mixed in; must use originals only | Possible later supplement, originals only |
| Tomato Maturity & Quality (Khatun et al. 2023) [link](https://data.mendeley.com/datasets/s42kpg8h37) | tomato | Immature / Mature / Fresh / Rotten | 2986 original + 10k augmented | Collected at an agricultural university | CC BY 4.0 | **High** (augmented); the label axes mix ripeness and spoilage | Not recommended now |
| BrinjalFruitX [paper](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12915278/) | brinjal | Healthy / 4 disease types | 1823 | Field, on-plant | (check) | Low | **Not suitable**: disease ≠ post-harvest freshness |
| Fruits & Vegetables (Tripathi) [link](https://data.mendeley.com/datasets/73kpfrbcck/2) | apple, brinjal, tomato | **None** (type only) | ? | DSLR, market | CC BY 4.0 | ? | Fruit-type only; could add fruit-head data later |
| Kaggle "Fresh and Stale Images" (raghavrpotdar) | apple, banana, tomato | Fresh / Stale | (Kaggle page not readable) | Phone, daily captures | Not confirmed | Medium–high (daily shots of the same items) | Licence unverified; not recommended |
| Kaggle "Fruits fresh and rotten" (sriramr) | apple, banana | Fresh / Rotten | ~13k | Mixed web/augmented | Not confirmed | **High**: widely reported augmented duplicates | Not recommended |

## 3. Recommended combination

**Phase 1 (core):** FruitNet + AgriFreshNET

| Fruit | Source(s) | Fresh label | Spoiled label | Excluded |
|---|---|---|---|---|
| Apple | FruitNet | Good | Bad | Mixed |
| Guava | FruitNet | Good | Bad | Mixed |
| Banana | FruitNet + AgriFreshNET | Good / Fresh | Bad / Rotten | Mixed, Semi-fresh |
| Tomato | AgriFreshNET | Fresh | Rotten | Semi-fresh |
| Brinjal | AgriFreshNET (eggplant) | Fresh | Rotten | Semi-fresh |

Why:
- Both are CC BY 4.0 (attribution required; commercial use allowed).
- Both are real photos with varied backgrounds, which suits transfer learning
  and a cheap camera on the STM32 end.
- Together they cover all five fruits with a condition label, and neither
  ships pre-augmented copies (to be verified).
- Semi-fresh rows are **kept in the manifest** (status `excluded`) so a
  3-class condition head can later be evaluated for banana/tomato/brinjal.

**Phase 2 (optional, after a Phase-1 baseline):** add Spoiled & Fresh Fruit
Inspection (tomato, banana) to reduce single-source risk.

## 4. Known risks (must be measured, not assumed)

1. **Source / fruit confounding.** Apple and guava come only from FruitNet;
   tomato and brinjal only from AgriFreshNET. The fruit head could partly learn
   "which dataset's background is this?" Banana spans both sources and acts as
   a control. `evaluate.py` reports metrics per source so this can be checked.
2. **"Bad quality" ≠ "rotten".** FruitNet's Good/Bad criteria are not defined
   in the paper. Bad may include bruised or blemished fruit that is not
   rotten. Merging it with AgriFreshNET "Rotten" into `spoiled` is a
   harmonisation decision that **must be checked by looking at contact
   sheets** before `labels_verified: true`.
3. **Brinjal has one source** (AgriFreshNET) with roughly 1.1k fresh + rotten
   images (unverified). Expect weaker generalisation for brinjal.
4. **AgriFreshNET is new.** Its quality, per-class counts and duplicate rate are
   unknown until audited.
5. **Domain gap to the device camera.** Phone photos differ from an STM32
   camera module (e.g. OV7670/OV2640: low resolution, colour cast). A small
   capture set from the real device will be needed for final validation.

## 5. Download sizes

Not stated on the Mendeley pages that were read. FruitNet at 256×256 for
about 19.5k images should be small (a few hundred MB). AgriFreshNET's size is
unknown. Disk free at research time: 39 GB.

## 6. Attribution (required by CC BY 4.0)

- Meshram, V., Patil, K. (2022). *FruitNet: Indian fruits image dataset with
  quality for machine learning applications.* Data in Brief 40, 107686.
  doi:10.1016/j.dib.2021.107686. Data: doi:10.17632/b6fftwbr2v.3
- Risdin, F., Salauddin, H., Tufa, T. A., Hossain, M. J. *AgriFreshNET
  Freshness and Shelf-Life Image Dataset.* Mendeley Data V1.
  doi:10.17632/42m5tb7yv9.1
- (if used) Pachón Suescun, C. G., Pinzón Arenas, J. O., Jiménez-Moreno, R.
  *Spoiled and fresh fruit inspection dataset.* doi:10.17632/6ps7gtp2wg.1
