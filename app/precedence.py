"""Annex A Source Precedence Policy. Domain-agnostic; used for doc chunks AND registry rules.

Order: 1 applicability -> 2 explicit supersession (issuer level 1-2 only)
-> 3 authority -> 4 recency -> (tiebreak) scope specificity -> 5 unresolved = conflict.
Level 5 (unofficial) never overrides anything.
"""
import re
from datetime import date

STEP = {1: "not applicable on as_of_date (step 1)", 2: "superseded (step 2)",
        3: "lower authority (step 3)", 4: "older effective date, same authority (step 4)",
        "spec": "less specific scope, same authority and date (tiebreak)"}


def norm_section(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"(?i)^\s*(section|clause|§|sec\.?)\s*", "", str(s)).strip().rstrip(".")
    return s.lower()


def _scope_list(s: str | None) -> list[str]:
    return [x.strip().upper() for x in (s or "ALL").split(";") if x.strip()] or ["ALL"]


def scope_covers(scope: str | None, value: str | None, strict: bool = True) -> bool:
    """strict (rules): an unknown request value only matches ALL-scope rules, so a GOLD-only
    rule never answers a tier-less question. Non-strict (chunks): unknown value matches all."""
    lst = _scope_list(scope)
    if "ALL" in lst:
        return True
    if value is None:
        return not strict
    return value.upper() in lst


def specificity(item: dict) -> int:
    return int("ALL" not in _scope_list(item.get("scope_categories"))) + \
        int("ALL" not in _scope_list(item.get("scope_tiers")))


def effective_state(eff_from: str | None, eff_to: str | None, as_of: date) -> str:
    """'current' | 'upcoming' | 'expired'"""
    a = as_of.isoformat()
    if eff_from and eff_from > a:
        return "upcoming"
    if eff_to and eff_to < a:
        return "expired"
    return "current"


def parse_supersedes(s: str | None) -> list[tuple[str, str]]:
    """'RET-POL-2024#3.1; FAQ-01' -> [('RET-POL-2024','3.1'), ('FAQ-01','')]"""
    out = []
    for part in (s or "").replace(",", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        doc, _, sec = part.partition("#")
        out.append((doc.strip(), norm_section(sec)))
    return out


def is_superseded(doc_id: str, section: str | None, superseders: list[dict]) -> str | None:
    """Return the superseding doc_id if any level<=2 applicable doc replaces this doc/section."""
    sec = norm_section(section)
    for s in superseders:
        if int(s.get("authority_level", 9)) > 2 or s["doc_id"] == doc_id:
            continue
        for tgt_doc, tgt_sec in parse_supersedes(s.get("supersedes")):
            if tgt_doc == doc_id and (not tgt_sec or tgt_sec == sec or sec.startswith(tgt_sec + ".")):
                return s["doc_id"]
    return None


def resolve(cands: list[dict], as_of: date, category: str | None, tier: str | None,
            docs: dict[str, dict]) -> dict:
    """Resolve competing rule rows for ONE parameter.

    cands: rule_registry rows. docs: doc_id -> source_register row.
    Returns {winner, conflicts, upcoming, unresolved: [rows], dropped: [(row, reason)]}
    """
    dropped: list[tuple[dict, str]] = []
    upcoming: list[dict] = []
    live: list[dict] = []

    for r in cands:
        d = docs.get(r["source_doc_id"], {})
        r = {**r, "authority_level": int(d.get("authority_level", 5)),
             "doc_title": d.get("title", r["source_doc_id"]), "doc_version": d.get("version"),
             "doc_supersedes": d.get("supersedes", "")}
        if not (scope_covers(r.get("scope_categories"), category) and scope_covers(r.get("scope_tiers"), tier)):
            continue  # out of scope: not a competitor at all
        if r["authority_level"] >= 5:
            dropped.append((r, "unofficial source (level 5) cannot set a rule"))
            continue
        st = effective_state(r.get("effective_from"), r.get("effective_to"), as_of)
        if st == "upcoming":
            upcoming.append(r)
            continue
        if st == "expired":
            continue
        live.append(r)

    # step 2: explicit supersession, by level 1-2 docs that are themselves live
    supers = [{"doc_id": r["source_doc_id"], "authority_level": r["authority_level"],
               "supersedes": r["doc_supersedes"]} for r in live]
    kept = []
    for r in live:
        by = is_superseded(r["source_doc_id"], r.get("source_section"), supers)
        if by:
            dropped.append((r, f"superseded by {by} (step 2)"))
        else:
            kept.append(r)
    live = kept

    # step 3: authority
    if live:
        best = min(r["authority_level"] for r in live)
        for r in [r for r in live if r["authority_level"] != best]:
            dropped.append((r, f"lower authority (level {r['authority_level']} vs {best}) (step 3)"))
        live = [r for r in live if r["authority_level"] == best]
    # step 4: recency
    if live:
        newest = max(r["effective_from"] for r in live)
        for r in [r for r in live if r["effective_from"] != newest]:
            dropped.append((r, f"older effective date {r['effective_from']} (step 4)"))
        live = [r for r in live if r["effective_from"] == newest]
    # tiebreak: the more specific scope (e.g. ELECTRONICS over ALL) in the same doc/level/date
    if len(live) > 1:
        top = max(specificity(r) for r in live)
        for r in [r for r in live if specificity(r) != top]:
            dropped.append((r, "less specific scope (tiebreak)"))
        live = [r for r in live if specificity(r) == top]

    distinct = {str(r["value"]).strip() for r in live}
    unresolved = live if len(distinct) > 1 else []
    winner = live[0] if live and not unresolved else None

    conflicts = []
    if winner:
        for r, why in dropped:
            if str(r["value"]).strip() != str(winner["value"]).strip():
                conflicts.append({"loser": r, "reason": why})
    return {"winner": winner, "conflicts": conflicts, "upcoming": upcoming,
            "unresolved": unresolved, "dropped": dropped}


def filter_chunks(hits: list[dict], as_of: date, category: str | None, tier: str | None,
                  docs: dict[str, dict]) -> dict:
    """Apply step 1 + step 2 to retrieved chunks. Steps 3-4 are applied as ordering + prompt
    annotation; numeric answers go through the rule registry where resolve() is exact."""
    current, upcoming, dropped, informational = [], [], [], []
    for h in hits:
        m = h["meta"]
        if not (scope_covers(m.get("scope_categories"), category, strict=False)
                and scope_covers(m.get("scope_tiers"), tier, strict=False)):
            continue
        st = effective_state(m.get("effective_from"), m.get("effective_to") or None, as_of)
        if st == "upcoming":
            upcoming.append(h)
        elif st == "current":
            (informational if int(m.get("authority_level", 5)) >= 5 else current).append(h)

    # a superseding doc only counts if it is in force AND strictly covers this request's scope
    # (a GOLD-only circular must not knock out the general clause for a STANDARD customer)
    live_docs = [d for d in docs.values()
                 if effective_state(d.get("effective_from"), d.get("effective_to"), as_of) == "current"
                 and scope_covers(d.get("scope_categories"), category) and scope_covers(d.get("scope_tiers"), tier)]
    kept = []
    for h in current:
        by = is_superseded(h["meta"]["doc_id"], h["meta"].get("section"), live_docs)
        if by:
            dropped.append((h, f"{h['meta']['doc_id']}#{h['meta'].get('section')} superseded by {by} (step 2)"))
        else:
            kept.append(h)
    kept.sort(key=lambda h: -h["score"])
    return {"current": kept, "upcoming": upcoming, "dropped": dropped, "informational": informational}
