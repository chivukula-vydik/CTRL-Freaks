"""Active domain, picked by env DOMAIN (default: engage).

Lookup: app/domain/<name>.py.
Its data pack (docs, source_register.csv, csv/, eval_set.jsonl) is data/<name>/,
; override with PACK_DIR.
"""
import importlib
import os
from pathlib import Path

from app.config import ROOT
from app.domain.base import COMMON_OUT_OF_SCOPE, Ctx, Domain, ToolResult, Understanding, action, tool  # noqa: F401

NAME = os.getenv("DOMAIN", "engage")


def _load(name: str) -> Domain:
    for mod in (f"app.domain.{name}",):
        try:
            return importlib.import_module(mod).DOMAIN
        except ModuleNotFoundError as e:
            if e.name not in (mod, mod.rsplit(".", 1)[0]):
                raise
    raise SystemExit(f"DOMAIN={name}: no app/domain/{name}.py")


def pack_dir() -> Path:
    if os.getenv("PACK_DIR"):
        return Path(os.environ["PACK_DIR"])
    for p in (ROOT / "data" / NAME,):
        if p.exists():
            return p
    return ROOT / "data" / NAME


DOMAIN: Domain = _load(NAME)
PARAMETERS = DOMAIN.PARAMETERS
