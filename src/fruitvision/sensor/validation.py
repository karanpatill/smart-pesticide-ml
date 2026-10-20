"""Sensor-record validation and the Model 2 applicability decision (no ML).

Record schema (all numeric values plain numbers; see docs/END_TO_END.md):
{
  "tcs34725": {"r": int, "g": int, "b": int, "c": int, "atime": int?},   # raw 16-bit counts
  "mq135":    {"value": num, "unit": "adc_counts_12bit" | "synthetic_scale", "warmup_s": num?},
  "ph":       {"value": num},
  "dht22":    {"temperature_c": num, "humidity_pct": num},
  "meta":     {"data_origin": "synthetic_fixture" | "device", "calibration_profile": str | null}
}

Validity limits are hardware/datasheet limits (16-bit TCS registers, 12-bit ADC,
pH 0-14, DHT22 -40..80 degC / 0..100 %RH); they detect missing, non-finite,
disconnected and saturated readings. They are NOT calibration.

Applicability of Model 2 (synthetic prototype):
  * any invalid required reading            -> risk "unavailable"
  * data_origin == "device" without a calibration profile mapping device units to
    the model's synthetic scales            -> risk "uncertain" (no such profile exists yet)
  * a feature outside the synthetic training range (+/- 10 % of range) -> "uncertain"
"""

from __future__ import annotations

import math

TCS_MAX = 65535            # 16-bit data registers (TCS3472 datasheet)
ADC12_MAX = 4095           # STM32 12-bit ADC
MQ_WARMUP_MIN_S = 180      # minimum heater warm-up before a reading is used (conservative demo rule)
OOD_MARGIN = 0.10


def _num(x) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def validate_sensors(rec: dict | None, ranges: dict) -> dict:
    """Returns {"status": valid|invalid, "errors", "warnings", "values" (model-order dict), "checks"}."""
    errors, warnings, vals = [], [], {}
    if not isinstance(rec, dict):
        return {"status": "invalid", "errors": ["no sensor record supplied"], "warnings": [], "values": {}}

    def need(group, key, label):
        g = rec.get(group)
        if not isinstance(g, dict) or key not in g:
            errors.append(f"{label}: missing")
            return None
        v = _num(g[key])
        if v is None:
            errors.append(f"{label}: not a number ({g[key]!r})")
            return None
        if not math.isfinite(v):
            errors.append(f"{label}: non-finite value ({v}); sensor read failure")
            return None
        return v

    # --- TCS34725 ---
    t = {k: need("tcs34725", k, f"TCS34725 {k.upper()}") for k in ("r", "g", "b", "c")}
    if all(v is not None for v in t.values()):
        atime = rec["tcs34725"].get("atime")
        sat = TCS_MAX if _num(atime) is None else min(TCS_MAX, 1024 * (256 - int(atime)))
        if any(v < 0 or v != int(v) for v in t.values()):
            errors.append("TCS34725: counts must be non-negative integers")
        elif all(v == 0 for v in t.values()):
            errors.append("TCS34725: all channels 0 (sensor disconnected, I2C failure or no illumination)")
        elif any(v >= sat for v in t.values()):
            errors.append(f"TCS34725: saturated channel (>= {sat}); reduce gain/integration time")
        elif t["c"] < max(t["r"], t["g"], t["b"]):
            warnings.append("TCS34725: clear channel below a colour channel (physically implausible); check wiring/timing")
        vals.update({"tcs_r": t["r"], "tcs_g": t["g"], "tcs_b": t["b"], "tcs_c": t["c"]})

    # --- MQ135 ---
    mq = need("mq135", "value", "MQ135")
    unit = (rec.get("mq135") or {}).get("unit")
    if mq is not None:
        if unit not in ("adc_counts_12bit", "synthetic_scale"):
            errors.append(f"MQ135: unit must be 'adc_counts_12bit' or 'synthetic_scale' (got {unit!r})")
        elif unit == "adc_counts_12bit" and (mq <= 0 or mq >= ADC12_MAX):
            errors.append(f"MQ135: ADC at rail ({mq:g}); sensor disconnected, shorted or saturated")
        elif mq <= 0:
            errors.append("MQ135: value must be > 0")
        w = _num((rec.get("mq135") or {}).get("warmup_s"))
        if w is None:
            warnings.append("MQ135: heater warm-up time unknown")
        elif w < MQ_WARMUP_MIN_S:
            warnings.append(f"MQ135: only {w:g} s warm-up (< {MQ_WARMUP_MIN_S} s); reading may drift")
        vals["mq135"] = mq

    # --- pH ---
    ph = need("ph", "value", "pH")
    if ph is not None:
        if ph <= 0 or ph >= 14:
            errors.append(f"pH: {ph:g} outside (0, 14); probe disconnected, rail value or not calibrated")
        vals["ph"] = ph

    # --- DHT22 ---
    tc = need("dht22", "temperature_c", "DHT22 temperature")
    rh = need("dht22", "humidity_pct", "DHT22 humidity")
    if tc is not None and not -40 <= tc <= 80:
        errors.append(f"DHT22 temperature {tc:g} degC outside -40..80 (datasheet range)")
    if rh is not None and not 0 <= rh <= 100:
        errors.append(f"DHT22 humidity {rh:g} % outside 0..100")
    if tc is not None:
        vals["temp_c"] = tc
    if rh is not None:
        vals["humidity_pct"] = rh

    # --- range vs synthetic training data (only meaningful on the synthetic scale) ---
    ood = []
    keymap = {"tcs_r": "sensor_tcs_r", "tcs_g": "sensor_tcs_g", "tcs_b": "sensor_tcs_b", "tcs_c": "sensor_tcs_c",
              "mq135": "sensor_mq135", "ph": "sensor_ph", "temp_c": "sensor_temp_c", "humidity_pct": "sensor_humidity_pct"}
    for k, v in vals.items():
        rg = ranges.get(keymap[k])
        if rg:
            span = rg["max"] - rg["min"]
            lo, hi = rg["min"] - OOD_MARGIN * span, rg["max"] + OOD_MARGIN * span
            if not lo <= v <= hi:
                ood.append(f"{k}={v:g} outside synthetic training range [{lo:.4g}, {hi:.4g}]")
    return {"status": "invalid" if errors else "valid", "errors": errors, "warnings": warnings,
            "values": vals, "out_of_training_range": ood,
            "mq135_unit": unit, "meta": rec.get("meta") or {}}
