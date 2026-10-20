"""End-to-end inference interface: RGB image + structured sensor record -> validated result.

    from fruitvision.system import SmartPesticideSystem
    sys_ = SmartPesticideSystem()            # loads frozen artifacts read-only
    result = sys_.analyze(image="photo.jpg", sensors={...})

Every output object has "state": "predicted" | "uncertain" | "unavailable".
No single combined score is produced. Evidence levels are explicit:
  * fruit / condition / quality / shelf life: models trained on PUBLIC image datasets
  * pesticide_risk: Model 2, a SYNTHETIC-DATA PROTOTYPE (not validated on real sensors
    or pesticides). LOW is not evidence of absence; HIGH is not proof of presence.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from fruitvision.postprocess import postprocess
from fruitvision.sensor.risk_model import Model2
from fruitvision.sensor.validation import validate_sensors
from fruitvision.validation.image_checks import check_image

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "1.0"
CONDITIONS = ["fresh", "spoiled"]
FRUITS = ["apple", "banana", "guava", "tomato", "brinjal"]

LIMITATIONS = [
    "The image models classify fruit type and VISIBLE condition only; they do not detect pesticide residue.",
    "Image models were trained/evaluated on public datasets (FruitNet, AgriFreshNET, Mendeley 56td5w4wz2); "
    "held-out test fruit F1 0.822, fresh/spoiled F1 0.679; not validated on the device camera.",
    "Softmax confidences are not calibrated probabilities; non-fruit images can receive high confidence.",
    "The pesticide-risk model is a SYNTHETIC-DATA PROTOTYPE: no real pesticide-labelled sensor data exists for it. "
    "It cannot measure concentration (ppm) or regulatory compliance.",
    "Shelf-life ranges reflect AgriFreshNET storage conditions only; they are not guarantees.",
]


class SmartPesticideSystem:
    def __init__(self, root: str | Path = ROOT):
        import tensorflow as tf
        root = Path(root)
        m3 = root / "models/model3"
        self.model = tf.keras.models.load_model(m3 / "model3_combined.keras")
        self.labels = json.loads((m3 / "labels.json").read_text())
        self.shelf = json.loads((m3 / "shelf_life_ranges.json").read_text())
        self.pp_cfg = json.loads((m3 / "postprocess_config.json").read_text())
        self.img_cfg = json.loads((root / "configs/image_checks.json").read_text())
        self.m2 = Model2(root / "models/model2_export/model2_logreg.json")
        self.m2_ranges = self.m2.spec["synthetic_training_ranges_trainval"]

    # ------------------------------------------------------------------ image
    def _model_input(self, source, rgb: np.ndarray) -> np.ndarray:
        import tensorflow as tf
        from fruitvision.data.pipeline import resize_image
        if isinstance(source, (str, Path, bytes, bytearray)):
            data = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
            img = tf.io.decode_image(data, channels=3, expand_animations=False)   # same decoder as training
        else:
            img = tf.constant(rgb)
        return resize_image(img, 80).numpy()[None]

    def _image_outputs(self, image):
        if image is None:
            chk = {"status": "not_supplied", "reasons": ["no image supplied"], "warnings": []}
            return chk, None
        c = check_image(image, self.img_cfg)
        if c.status == "rejected":
            return c.as_dict(), None
        o = {k: np.asarray(v) for k, v in self.model.predict(self._model_input(image, c.rgb), verbose=0).items()}
        raw = {"fruit": dict(zip(FRUITS, map(float, o["fruit"][0]))),
               "condition": dict(zip(CONDITIONS, map(float, o["condition"][0]))),
               "heads": {h: {self.labels[h][str(k)]: float(v) for k, v in enumerate(o[h][0])} for h in self.labels}}
        return c.as_dict(), postprocess(raw, self.pp_cfg, self.shelf)

    # ---------------------------------------------------------------- sensors
    def _risk(self, sensors):
        v = validate_sensors(sensors, self.m2_ranges)
        base = {"category": None, "probabilities": None, "model": "Model 2 logistic regression (S__logreg export)",
                "evidence_level": "SYNTHETIC-DATA PROTOTYPE - not validated on real sensors or pesticides",
                "interpretation": "Estimated risk category only. LOW does not mean pesticide-free; HIGH does not "
                                  "prove pesticide presence. Confirmation requires laboratory analysis.",
                "reasons": [], "warnings": list(v.get("warnings", []))}
        if sensors is None:
            return v, {**base, "state": "unavailable", "reasons": ["no sensor record supplied"]}
        if v["status"] == "invalid":
            return v, {**base, "state": "unavailable", "reasons": v["errors"]}
        vals = v["values"]
        probs = self.m2.predict_proba([[vals[k] for k in ("tcs_r", "tcs_g", "tcs_b", "tcs_c", "mq135", "ph",
                                                          "temp_c", "humidity_pct")]])[0]
        raw_probs = dict(zip(self.m2.classes, map(lambda p: round(float(p), 4), probs)))
        meta = v["meta"]
        reasons = []
        if meta.get("data_origin") != "synthetic_fixture" or v["mq135_unit"] != "synthetic_scale":
            if not meta.get("calibration_profile"):
                reasons.append("readings are not on the model's synthetic scales and no calibration profile maps "
                               "device units to them (no such profile exists yet)")
        reasons += v["out_of_training_range"]
        if any("warm-up" in w and "only" in w for w in v["warnings"]):
            reasons.append("MQ135 not warmed up")
        if reasons:
            return v, {**base, "state": "uncertain", "reasons": reasons, "raw_probabilities_not_used": raw_probs}
        cat = self.m2.classes[int(np.argmax(probs))]
        return v, {**base, "state": "predicted", "category": cat, "probabilities": raw_probs,
                   "reasons": ["inputs valid and within the synthetic training range (synthetic fixture data)"]}

    # ----------------------------------------------------------- recommendation
    @staticmethod
    def _recommend(img_chk, img, risk) -> dict:
        lines, basis = [], []
        if img is None:
            if img_chk["status"] == "rejected":
                lines.append("Retake the image: " + "; ".join(img_chk["reasons"]))
            else:
                lines.append("No image analysed: fruit, condition, quality and shelf life are unavailable.")
        else:
            if img["quality_grade"]["state"] == "uncertain":
                lines.append("Fruit identity is uncertain; quality and shelf life withheld. Retake the image with the "
                             "fruit centred on a plain background.")
            if img["condition"]["label"] == "spoiled" or img["quality_grade"].get("label") == "Poor":
                lines.append("Visible deterioration indicated by the image model; inspect the produce before use.")
                basis.append("Model 1 condition / Model 3 grade (public-dataset models)")
            if img["consistency"]["warnings"] and img["consistency"]["status"] == "warning":
                lines.append("Image outputs disagree with each other (see warnings); treat them as uncertain.")
        if risk["state"] == "predicted":
            if risk["category"] == "HIGH":
                lines.append("Prototype risk category HIGH (synthetic-data model): treat as a screening flag only and "
                             "seek a validated laboratory test before consumption decisions.")
            elif risk["category"] == "MEDIUM":
                lines.append("Prototype risk category MEDIUM (synthetic-data model): inconclusive screening result.")
            else:
                lines.append("Prototype risk category LOW (synthetic-data model): this is NOT evidence that the produce "
                             "is pesticide-free.")
            basis.append("Model 2 synthetic-data prototype")
        else:
            lines.append(f"No pesticide-risk statement can be made (risk estimate {risk['state']}).")
        lines.append("Only laboratory analysis (e.g. LC-MS/MS or GC-MS) can establish pesticide residue levels.")
        return {"text": lines, "basis": basis or ["input validation rules"],
                "note": "Rule-based text derived from the outputs above; not a safety certification."}

    # ------------------------------------------------------------------- main
    def analyze(self, image=None, sensors=None) -> dict:
        img_chk, img = self._image_outputs(image)
        sens_chk, risk = self._risk(sensors)
        if img is None:
            reason = "; ".join(img_chk["reasons"])
            na = lambda: {"state": "unavailable", "reason": f"image not analysed: {reason}"}  # noqa: E731
            fruit, cond, quality, shelf, consistency, raw_img = na(), na(), na(), na(), {"status": "not_evaluated",
                                                                                          "warnings": []}, None
        else:
            fruit, cond, quality, shelf = img["fruit"], img["condition"], img["quality_grade"], img["shelf_life"]
            consistency, raw_img = img["consistency"], img["raw"]
        warnings = ([f"image: {w}" for w in img_chk.get("warnings", [])]
                    + [f"{w['rule']}: {w['message']}" for w in consistency.get("warnings", [])]
                    + [f"sensors: {w}" for w in sens_chk.get("warnings", [])]
                    + ([f"pesticide_risk ({risk['state']}): {r}" for r in risk["reasons"]]
                       if risk["state"] != "predicted" else []))
        risk_out = {k: v for k, v in risk.items() if k != "raw_probabilities_not_used"}
        return {
            "schema_version": SCHEMA_VERSION,
            "input_checks": {"image": img_chk, "sensors": {k: sens_chk.get(k) for k in
                                                           ("status", "errors", "warnings", "out_of_training_range")}},
            "fruit": fruit, "condition": cond, "quality_grade": quality, "shelf_life": shelf,
            "pesticide_risk": risk_out,
            "consistency": consistency,
            "warnings": warnings,
            "recommendation": self._recommend(img_chk, img, risk),
            "limitations": LIMITATIONS,
            "raw": {"image_models": raw_img, "model2_probabilities_withheld": risk.get("raw_probabilities_not_used")},
        }
