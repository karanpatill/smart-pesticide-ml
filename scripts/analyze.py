"""Analyze one RGB image and/or one sensor record with the full validated pipeline.

Usage:
  python scripts/analyze.py --image path/to/fruit.jpg
  python scripts/analyze.py --image fruit.jpg --sensors record.json
  python scripts/analyze.py --sensor-fixture synthetic_medium        # from data/fixtures/sensor_records.json
  python scripts/analyze.py --image fruit.jpg --json                  # full JSON result

Each output is marked predicted / uncertain / unavailable. The pesticide-risk output
comes from a SYNTHETIC-DATA PROTOTYPE and is never a measurement.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def summary(r: dict) -> str:
    def fmt(name, o, value):
        st = o.get("state", "?")
        if st == "predicted":
            return f"  {name:<16} {value}  [predicted]"
        return f"  {name:<16} {st.upper()}: {o.get('reason') or '; '.join(o.get('reasons', [])) or '-'}"
    q, s, p = r["quality_grade"], r["shelf_life"], r["pesticide_risk"]
    lines = [f"Image check: {r['input_checks']['image']['status']}   Sensor check: {r['input_checks']['sensors']['status']}",
             fmt("Fruit", r["fruit"], f"{r['fruit'].get('label')} (confidence {r['fruit'].get('confidence')})"),
             fmt("Condition", r["condition"], f"{r['condition'].get('label')} (confidence {r['condition'].get('confidence')})"),
             fmt("Quality grade", q, f"{q.get('label')} ({q.get('scale')}; {q.get('basis')})"),
             fmt("Shelf life", s, f"{s.get('range_days')} days, stage {s.get('stage')} (source dataset storage conditions)"),
             fmt("Pesticide risk", p, f"{p.get('category')}  <- SYNTHETIC-DATA PROTOTYPE, not a measurement")]
    if r["warnings"]:
        lines.append("Warnings:")
        lines += [f"  - {w}" for w in r["warnings"]]
    lines.append("Recommendation:")
    lines += [f"  - {t}" for t in r["recommendation"]["text"]]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", type=Path)
    ap.add_argument("--sensors", type=Path, help="JSON file with one sensor record")
    ap.add_argument("--sensor-fixture", help="name of a record in data/fixtures/sensor_records.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sensors = None
    if a.sensors:
        sensors = json.loads(a.sensors.read_text())
    elif a.sensor_fixture:
        sensors = json.loads((ROOT / "data/fixtures/sensor_records.json").read_text())["records"][a.sensor_fixture]["record"]
    from fruitvision.system import SmartPesticideSystem
    r = SmartPesticideSystem(ROOT).analyze(image=a.image, sensors=sensors)
    print(json.dumps(r, indent=2, default=str) if a.json else summary(r))


if __name__ == "__main__":
    main()
