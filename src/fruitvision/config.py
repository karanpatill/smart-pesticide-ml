"""Configuration loading helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str | Path = "configs/config.yaml") -> dict[str, Any]:
    cfg = load_yaml(path)
    _validate(cfg)
    return cfg


def resolve(path: str | Path) -> Path:
    """Resolve a project-relative path to an absolute one."""
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _validate(cfg: dict[str, Any]) -> None:
    s = cfg["split"]
    total = s["train"] + s["val"] + s["test"]
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"split fractions must sum to 1.0, got {total}")
    if len(set(cfg["fruits"])) != len(cfg["fruits"]):
        raise ValueError("duplicate fruit names in config")
    if len(set(cfg["conditions"])) != len(cfg["conditions"]):
        raise ValueError("duplicate condition names in config")
