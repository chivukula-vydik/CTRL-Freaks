"""Bulk loading: Source Register + docs, rule registry CSV, domain CSVs."""
import csv
from pathlib import Path

from app import db
from app.domain import DOMAIN
from app.ingest.pipeline import ingest_file
from app.schemas import IngestMeta

RULE_COLS = ["rule_id", "description", "parameter", "operator", "value", "scope_categories", "scope_tiers",
             "effective_from", "effective_to", "source_doc_id", "source_section"]


def ingest_register(register_csv: Path, docs_dir: Path, skip_existing: bool = True) -> list[dict]:
    have = {r["doc_id"] for r in db.q("SELECT doc_id FROM source_register")}
    out = []
    for row in csv.DictReader(register_csv.open(encoding="utf-8")):
        if skip_existing and row["doc_id"] in have:
            out.append({"doc_id": row["doc_id"], "status": "skipped (already indexed)"})
            continue
        f = docs_dir / row.pop("file")
        meta = IngestMeta(**{k: v for k, v in row.items() if v != ""})
        out.append(ingest_file(f, meta).model_dump())
    return out


def load_rules(path: Path) -> int:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return db.upsert("rule_registry", [{k: r.get(k) or None for k in RULE_COLS} for r in rows])


def load_dir(d: Path) -> dict:
    counts = {}
    if (d / "rule_registry.csv").exists():
        counts["rule_registry"] = load_rules(d / "rule_registry.csv")
    try:
        counts.update(DOMAIN.load_csv_dir(d))
    except NotImplementedError as e:
        counts["domain"] = str(e)
    return counts


def load_pack(pack: Path, reingest: bool = False) -> dict:
    """A data pack = docs/ + source_register.csv (+ csv/<table>.csv, rule_registry.csv)."""
    out = {"docs": [], "tables": {}}
    reg = pack / "source_register.csv"
    if reg.exists():
        out["docs"] = ingest_register(reg, pack / "docs", skip_existing=not reingest)
    if (pack / "csv").exists():
        out["tables"] = load_dir(pack / "csv")
    return out
