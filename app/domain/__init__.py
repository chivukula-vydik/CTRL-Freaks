"""Active domain, picked by env DOMAIN (default: generic).

Lookup order: app/domain/<name>.py, then examples/<name>/domain.py.
Its data pack (docs, source_register.csv, csv/, eval_set.jsonl) is data/<name>/,
else examples/<name>/data/ ; override with PACK_DIR.
"""
import importlib
import os
from pathlib import Path

from app.config import ROOT
from app.domain.base import Ctx, Domain, ToolResult, Understanding, tool  # noqa: F401

NAME = os.getenv("DOMAIN", "generic")


def _load(name: str) -> Domain:
    for mod in (f"app.domain.{name}", f"examples.{name}.domain"):
        try:
            return importlib.import_module(mod).DOMAIN
        except ModuleNotFoundError as e:
            if e.name not in (mod, mod.rsplit(".", 1)[0]):
                raise
    raise SystemExit(f"DOMAIN={name}: no app/domain/{name}.py or examples/{name}/domain.py")


def pack_dir() -> Path:
    if os.getenv("PACK_DIR"):
        return Path(os.environ["PACK_DIR"])
    for p in (ROOT / "data" / NAME, ROOT / "examples" / NAME / "data"):
        if p.exists():
            return p
    return ROOT / "data" / NAME


DOMAIN: Domain = _load(NAME)
PARAMETERS = DOMAIN.PARAMETERS
