"""Loads the UC5 config YAMLs from config/ (cached). Edit the YAML, not the code.
policy.yaml is the master; the *_rules.yaml files hold the per-step rule detail."""
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


def segmentation() -> dict:
    return _load("segmentation_rules")


def conflicts() -> dict:
    return _load("data_conflict_rules")


def offer_rules() -> dict:
    return _load("offer_validator_rules")


def validator() -> dict:
    return _load("message_validator_rules")


def reminder_types() -> set[str]:
    return {s["message_type"] for s in policy()["strategy"]["payment_stages"]}


def reload() -> None:
    _load.cache_clear()
