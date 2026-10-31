"""Loads config/policy.yaml, config/offers.yaml and config/ai_prompt.yaml (cached). Edit the YAML, not the code."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

from app import config

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", config.ROOT / "config"))


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


def policy() -> dict:
    return _load("policy")


def offers() -> dict:
    return _load("offers")


def ai() -> dict:
    return _load("ai_prompt")


def reload() -> None:
    _load.cache_clear()
