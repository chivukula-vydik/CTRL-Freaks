"""Thresholds from rule_registry: the rule in force on as_of (latest effective_from wins)."""
from datetime import date

from app import db


class RuleMissing(Exception):
    pass


def get_rule(parameter: str, as_of: date, category: str | None = None, tier: str | None = None,
             default: str | None = None, trace: dict | None = None, quiet: bool = False) -> str:
    d = as_of.isoformat()
    w = db.q1("SELECT * FROM rule_registry WHERE parameter = ? AND effective_from <= ? "
              "AND (effective_to IS NULL OR effective_to >= ?) ORDER BY effective_from DESC LIMIT 1", (parameter, d, d))
    if not w:
        if default is None:
            raise RuleMissing(parameter)
        return default
    if trace is not None:
        trace.setdefault("applied_rules", []).append({"rule_id": w["rule_id"], "parameter": parameter,
                                                      "value": w["value"], "source_doc_id": w["source_doc_id"],
                                                      "source_section": w.get("source_section")})
    return str(w["value"])
