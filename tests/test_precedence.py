"""Annex A precedence, pure functions: domain-independent."""
from datetime import date

from app.precedence import resolve

D = date(2026, 10, 6)
DOCS = {
    "POL": {"doc_id": "POL", "authority_level": 1, "supersedes": "", "title": "Policy"},
    "CIRC": {"doc_id": "CIRC", "authority_level": 2, "supersedes": "POL#3.1", "title": "Circular"},
    "FAQ": {"doc_id": "FAQ", "authority_level": 4, "supersedes": "", "title": "FAQ"},
    "STORE": {"doc_id": "STORE", "authority_level": 3, "supersedes": "POL#3.1", "title": "Store notice"},
    "FORUM": {"doc_id": "FORUM", "authority_level": 5, "supersedes": "", "title": "Forum"},
    "A": {"doc_id": "A", "authority_level": 2, "supersedes": "", "title": "A"},
    "B": {"doc_id": "B", "authority_level": 2, "supersedes": "", "title": "B"},
}


def rule(rid, doc, value, eff="2024-01-01", cat="ALL", tier="ALL", sec="1", to=None):
    return {"rule_id": rid, "source_doc_id": doc, "value": value, "effective_from": eff, "effective_to": to,
            "scope_categories": cat, "scope_tiers": tier, "source_section": sec, "parameter": "p"}


def win(rows, cat=None, tier=None, as_of=D):
    return resolve(rows, as_of, cat, tier, DOCS)


def test_supersession_beats_higher_authority():
    r = win([rule("R1", "POL", "10", sec="3.1"), rule("R2", "CIRC", "7", eff="2026-08-01")], cat="X")
    assert r["winner"]["rule_id"] == "R2" and r["conflicts"]


def test_supersession_needs_level_1_or_2():
    r = win([rule("R1", "POL", "10", sec="3.1"), rule("R2", "STORE", "5", eff="2026-08-01")])
    assert r["winner"]["rule_id"] == "R1"


def test_authority_beats_recency():
    r = win([rule("R1", "POL", "10"), rule("R2", "FAQ", "15", eff="2026-09-15")])
    assert r["winner"]["rule_id"] == "R1"


def test_recency_at_same_authority():
    r = win([rule("R1", "A", "10", eff="2025-01-01"), rule("R2", "B", "12", eff="2026-01-01")])
    assert r["winner"]["rule_id"] == "R2"


def test_not_yet_effective_is_upcoming_only():
    r = win([rule("R1", "POL", "30"), rule("R2", "CIRC", "45", eff="2026-11-01", sec="9")])
    assert r["winner"]["rule_id"] == "R1" and r["upcoming"][0]["rule_id"] == "R2"


def test_expired_rule_ignored():
    r = win([rule("R1", "A", "10", to="2026-01-01"), rule("R2", "POL", "20")])
    assert r["winner"]["rule_id"] == "R2"


def test_level5_never_wins():
    r = win([rule("R1", "FORUM", "60")])
    assert r["winner"] is None


def test_unresolved_conflict():
    r = win([rule("R1", "A", "10"), rule("R2", "B", "12")])
    assert r["winner"] is None and len(r["unresolved"]) == 2


def test_same_value_is_not_a_conflict():
    r = win([rule("R1", "A", "10"), rule("R2", "B", "10")])
    assert r["winner"] is not None and not r["unresolved"]


def test_specific_scope_tiebreak():
    r = win([rule("R1", "POL", "10"), rule("R2", "POL", "7", cat="ELEC")], cat="ELEC")
    assert r["winner"]["rule_id"] == "R2"


def test_tier_rule_not_used_without_tier():
    r = win([rule("R1", "POL", "10"), rule("R2", "A", "0", tier="GOLD")])
    assert r["winner"]["rule_id"] == "R1"
    assert win([rule("R1", "POL", "10"), rule("R2", "A", "0", tier="GOLD")], tier="GOLD")["winner"]["rule_id"] == "R1"


def test_out_of_scope_category_excluded():
    r = win([rule("R1", "POL", "10", cat="FASHION")], cat="ELEC")
    assert r["winner"] is None
