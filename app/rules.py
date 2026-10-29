"""Rule registry lookup with precedence. Tools get every threshold from here, never from constants."""
from datetime import date

from app import db
from app.ingest.pipeline import load_register_rows
from app.precedence import resolve
from app.retrieval import store


class RuleUnresolved(Exception):
    def __init__(self, parameter: str, rows: list[dict]):
        self.parameter, self.rows = parameter, rows
        super().__init__(f"conflicting rules for {parameter}")


class RuleMissing(Exception):
    pass


def get_rule(parameter: str, as_of: date, category: str | None = None, tier: str | None = None,
             default: str | None = None, trace: dict | None = None, quiet: bool = False) -> str:
    """Return the winning value. Records applied rule, conflicts and upcoming changes into `trace`."""
    cands = db.q("SELECT * FROM rule_registry WHERE parameter = ?", (parameter,))
    docs = load_register_rows()
    res = resolve(cands, as_of, category, tier, docs)
    t = trace if trace is not None else {}
    for u in res["upcoming"]:
        t.setdefault("upcoming", []).append(
            f"{parameter} becomes {u['value']} from {u['effective_from']} "
            f"({u['source_doc_id']}#{u.get('source_section') or ''}); not applied as of {as_of}.")
    if res["unresolved"]:
        t.setdefault("unresolved", []).append({"parameter": parameter, "rows": res["unresolved"]})
        raise RuleUnresolved(parameter, res["unresolved"])
    w = res["winner"]
    if not w:
        if default is None:
            raise RuleMissing(parameter)
        if not quiet:
            t.setdefault("assumptions", []).append(
                f"No rule found for {parameter} ({category or 'ALL'}/{tier or 'ALL'}); using default {default}.")
        return default
    t.setdefault("applied_rules", []).append({
        "rule_id": w["rule_id"], "parameter": parameter, "value": w["value"],
        "source_doc_id": w["source_doc_id"], "source_section": w.get("source_section")})
    d = docs.get(w["source_doc_id"], {})
    t.setdefault("citations", []).append({
        "doc_id": w["source_doc_id"], "title": d.get("title", w["source_doc_id"]),
        "section": w.get("source_section"),
        "page": store.page_for(w["source_doc_id"], w.get("source_section")), "version": d.get("version"),
        "effective_from": d.get("effective_from")})
    for c in res["conflicts"]:
        t.setdefault("conflicts", []).append({
            "parameter": parameter, "winner": w["rule_id"], "losers": [c["loser"]["rule_id"]],
            "resolution": [f"{c['loser']['rule_id']} ({c['loser']['source_doc_id']}, value "
                           f"{c['loser']['value']}): {c['reason']}"]})
    return str(w["value"])
