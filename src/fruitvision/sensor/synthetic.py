"""Synthetic development data for Model 2 (estimated residue-RISK prototype).

SYNTHETIC / PROTOTYPE ONLY. The generator encodes the assumptions in
configs/model2_synthetic.yaml; models trained on it can only recover those
assumptions. Nothing here is real pesticide-residue behaviour.

Column groups (prefix = role):
  meta_*    session / device identifiers (used for splitting only)
  sensor_*  simulated readings of TCS34725 (AChE strip), MQ135, pH, DHT22
  aux_*     simulated Model 1 outputs (fruit, fresh/spoiled, P(spoiled))
  target_*  the (noisy) LOW/MEDIUM/HIGH risk label used for training/evaluation
  latent_*  hidden generator truth — diagnostics ONLY, never model inputs
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SENSOR_COLS = ["sensor_tcs_r", "sensor_tcs_g", "sensor_tcs_b", "sensor_tcs_c",
               "sensor_mq135", "sensor_ph", "sensor_temp_c", "sensor_humidity_pct"]
AUX_COLS = ["aux_m1_fruit", "aux_m1_condition", "aux_m1_p_spoiled"]
TARGET_COL = "target_risk"
GROUP_COL = "meta_session_id"


def _neighbour_flip(labels: np.ndarray, classes: list[str], rate: float, rng) -> tuple[np.ndarray, np.ndarray]:
    idx = {c: i for i, c in enumerate(classes)}
    out = labels.copy()
    flip = rng.random(len(labels)) < rate
    for i in np.flatnonzero(flip):
        k = idx[labels[i]]
        nbrs = [j for j in (k - 1, k + 1) if 0 <= j < len(classes)]
        out[i] = classes[rng.choice(nbrs)]
    return out, flip


def generate(cfg: dict, m1_test: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(cfg["seed"])
    S, T = cfg["sensors"], cfg["target"]
    fruits, classes = cfg["fruits"], T["classes"]

    # ---- sessions: ambient conditions, calibration offsets, lighting ----
    n_sess = cfg["samples"]["n_sessions"]
    lo, hi = cfg["samples"]["samples_per_session"]
    sess = pd.DataFrame({
        "session": np.arange(n_sess),
        "n": rng.integers(lo, hi + 1, n_sess),
        "unit": rng.integers(0, cfg["samples"]["device_units"], n_sess),
        "temp": rng.uniform(*S["dht22"]["temperature_c"]["session_range"], n_sess),
        "rh": rng.uniform(*S["dht22"]["humidity_pct"]["session_range"], n_sess),
        "mq_off": rng.normal(0, S["mq135"]["session_offset_sd"], n_sess),
        "ph_off": rng.normal(0, S["ph"]["probe_offset_sd"], n_sess),
        "light": rng.normal(1, S["tcs34725"]["lighting_gain_sd"], n_sess).clip(0.6, 1.4),
    })
    unit_mq = rng.normal(0, S["mq135"]["unit_offset_sd"], cfg["samples"]["device_units"])
    unit_tcs = rng.normal(1, S["tcs34725"]["unit_gain_sd"], cfg["samples"]["device_units"]).clip(0.8, 1.2)

    rows = sess.loc[sess.index.repeat(sess.n)].reset_index(drop=True)
    n = len(rows)

    # ---- latent truth (independent of fruit and freshness by design) ----
    fruit = rng.choice(fruits, n)
    spoiled = rng.random(n) < cfg["freshness"]["p_spoiled"]
    fd, sd = cfg["freshness"]["storage_day"]["fresh"], cfg["freshness"]["storage_day"]["spoiled"]
    day = np.where(spoiled, rng.integers(sd[0], sd[1] + 1, n), rng.integers(fd[0], fd[1] + 1, n))
    risk = rng.choice(classes, n, p=[T["prior"][c] for c in classes])
    band = np.array([T["score_bands"][c] for c in risk])
    score = rng.uniform(band[:, 0], band[:, 1])
    pos = (score - band[:, 0]) / (band[:, 1] - band[:, 0])          # position within band

    temp = rows.temp.to_numpy() + rng.normal(0, S["dht22"]["temperature_c"]["within_session_sd"], n)
    rh = (rows.rh.to_numpy() + rng.normal(0, S["dht22"]["humidity_pct"]["within_session_sd"], n)).clip(5, 99)
    unit = rows.unit.to_numpy()

    # ---- MQ135: spoilage-dominated, T/RH-sensitive, small risk effect ----
    q = S["mq135"]
    base = np.array([q["day1_median_by_fruit"][f] for f in fruit])
    growth = rng.uniform(*q["day_growth_factor"], n) ** (day - 1)
    env = 1 + q["temp_coeff_per_c"] * (temp - 25) + q["humidity_coeff_per_pct"] * (rh - 50)
    risk_mq = 1 + np.array([q["risk_effect_relative"][c] for c in risk])
    mq = base * growth * env * (1 + rows.mq_off.to_numpy() + unit_mq[unit]) * risk_mq
    mq = mq * (1 + rng.normal(0, q["noise_sd"], n))

    # ---- pH: fruit-dominated, small risk shift ----
    p = S["ph"]
    ph = (np.array([p["baseline_by_fruit"][f] for f in fruit]) + rng.normal(0, p["fruit_sample_sd"], n)
          + rows.ph_off.to_numpy() + np.array([p["risk_effect"][c] for c in risk]) + rng.normal(0, p["noise_sd"], n))

    # ---- TCS34725 reading an AChE strip: inhibition -> less blue dye ----
    t = S["tcs34725"]
    ib = np.array([t["inhibition_by_risk"][c] for c in risk])
    inhibition = (ib[:, 0] + pos * (ib[:, 1] - ib[:, 0]) + rng.normal(0, t["overlap_jitter_sd"], n)).clip(0, 0.98)
    dye = (1 - inhibition) * (1 + t["reaction_temp_coeff"] * (temp - 25)).clip(0.5, 1.5)
    refl = np.array(t["strip_reflectance_white"])[None, :] - dye[:, None] * np.array(t["dye_absorption_rgb"])[None, :]
    gain = (rows.light.to_numpy() * unit_tcs[unit])[:, None]
    rgb = refl.clip(0.02, 1) * gain * t["counts_full_scale"]
    rgb = rgb * (1 + rng.normal(0, t["count_noise_sd"], rgb.shape))
    clear = t["clear_vs_rgb_sum"] * rgb.sum(1) * (1 + rng.normal(0, t["count_noise_sd"], n))

    # ---- DHT22 readings ----
    d = S["dht22"]
    temp_r = temp + rng.normal(0, d["temperature_c"]["noise_sd"], n)
    rh_r = (rh + rng.normal(0, d["humidity_pct"]["noise_sd"], n)).clip(0, 100)

    # ---- Model 1 auxiliary outputs, sampled from Model 1's REAL test predictions ----
    m1 = m1_test.assign(true_spoiled=m1_test.condition == "spoiled")
    pools = {k: g for k, g in m1.groupby(["fruit", "true_spoiled"])}
    aux_f, aux_c, aux_p = [], [], []
    for f, s in zip(fruit, spoiled):
        r = pools[(f, bool(s))].iloc[rng.integers(len(pools[(f, bool(s))]))]
        aux_f.append(r.pred_fruit); aux_c.append(r.pred_condition); aux_p.append(1 - r.p_condition_fresh)

    noisy, flipped = _neighbour_flip(risk, classes, T["label_noise"], rng)

    return pd.DataFrame({
        "meta_sample_id": np.arange(n),
        GROUP_COL: rows.session.to_numpy(),
        "meta_device_unit": rows.unit.to_numpy(),
        "sensor_tcs_r": rgb[:, 0].round(1), "sensor_tcs_g": rgb[:, 1].round(1),
        "sensor_tcs_b": rgb[:, 2].round(1), "sensor_tcs_c": clear.round(1),
        "sensor_mq135": np.asarray(mq).round(1), "sensor_ph": np.asarray(ph).round(2),
        "sensor_temp_c": np.asarray(temp_r).round(1), "sensor_humidity_pct": np.asarray(rh_r).round(1),
        "aux_m1_fruit": aux_f, "aux_m1_condition": aux_c, "aux_m1_p_spoiled": np.round(aux_p, 4),
        TARGET_COL: noisy,
        "latent_risk_clean": risk, "latent_risk_score": score.round(4), "latent_label_flipped": flipped,
        "latent_fruit": fruit, "latent_spoiled": spoiled, "latent_storage_day": day,
        "latent_inhibition": inhibition.round(4),
    })
