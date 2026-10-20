# End-to-end interface and result schema (schema_version 1.0)

```python
from fruitvision.system import SmartPesticideSystem
s = SmartPesticideSystem()                       # loads frozen artifacts read-only
r = s.analyze(image="fruit.jpg", sensors=record)  # either argument may be None
```
CLI: `python scripts/analyze.py --image fruit.jpg --sensors record.json [--json]`
Demo: `python scripts/demo.py` → `docs/DEMO_REPORT.md`, `reports/demo/demo_results.json`

## Pipeline
1. **Image check:** decode, format, channels, size, content statistics.
   Rejected → all image outputs `unavailable`.
2. **Model 1 + Model 3:** one forward pass of `models/model3/model3_combined.keras`,
   on the TF-decoded image with Model 1 preprocessing.
3. **Post-processing:** R1 low fruit confidence, R2 banana grade vs stage,
   R3 condition vs grade.
4. **Sensor validation, then the Model 2 decision:**
   - invalid → `unavailable`;
   - uncalibrated device units or out of training range → `uncertain`;
   - otherwise `predicted` (synthetic fixtures only today).
5. **Rule-based recommendation text.** No combined score.

## Sensor record schema
```json
{
  "tcs34725": {"r": 0, "g": 0, "b": 0, "c": 0, "atime": 192},
  "mq135":    {"value": 0.0, "unit": "adc_counts_12bit | synthetic_scale", "warmup_s": 600},
  "ph":       {"value": 0.0},
  "dht22":    {"temperature_c": 0.0, "humidity_pct": 0.0},
  "meta":     {"data_origin": "device | synthetic_fixture", "calibration_profile": null}
}
```
- `atime` is optional and enables an exact saturation check.
- `warmup_s` is optional (a warning is raised if unknown).
- `calibration_profile` is the name of a measured mapping. **None exists
  yet**, so device data always yields risk `uncertain`.

## Result schema (top level)
| Field | Content |
|---|---|
| `input_checks.image` | `status` ok / warning / rejected / not_supplied, `reasons`, `warnings`, `stats` |
| `input_checks.sensors` | `status` valid / invalid, `errors`, `warnings`, `out_of_training_range` |
| `fruit`, `condition` | `label`, `confidence` (uncalibrated softmax), `source`, **`state`** |
| `quality_grade` | `label` (Good/Average/Poor; apple Good/Poor; or Uncertain), `scale`, `basis`, `head`, **`state`** |
| `shelf_life` | `status` estimated_range / not_available, `range_days`, `stage`, `disclaimer`, **`state`** |
| `pesticide_risk` | **`state`**, `category` (LOW/MEDIUM/HIGH or null), `probabilities`, `evidence_level` ("SYNTHETIC-DATA PROTOTYPE …"), `interpretation`, `reasons`, `warnings` |
| `consistency` | `status` ok / warning / uncertain / not_evaluated, `warnings` (R1–R3) |
| `warnings` | flat list of every warning and reason |
| `recommendation` | `text` (list), `basis`, `note` |
| `limitations` | fixed list of model/data limitations |
| `raw` | all image-model probabilities; Model 2 probabilities withheld when `uncertain` |

`state` meanings:
- `predicted`: a model produced the value;
- `uncertain`: a model exists but its output was withheld (low confidence,
  uncalibrated or out-of-range inputs);
- `unavailable`: no valid input, or no model/data exists for that case.
