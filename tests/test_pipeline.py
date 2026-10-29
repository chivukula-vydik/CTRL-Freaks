"""Pipeline skeleton on examples/pipeline: cleaning, DQ report, calculations, question routing.
No database needed."""
from app.config import ROOT
from app.pipeline import ask, calc, load

SCHEMA, RES = load(ROOT / "examples" / "pipeline" / "data", uploads=False)
T = RES["tables"]


def test_cleaning_and_report():
    r = RES["report"]["records"]
    assert (r["rows_in"], r["rows_clean"], r["rows_rejected"], r["duplicates_dropped"]) == (12, 5, 6, 1)
    assert r["defaults_filled"] == {"qty": 1} and r["orphan_keys"] == {"item_id->items": 1}
    why = {b["row"]["record_id"]: b["reasons"] for b in RES["rejected"]}
    assert why["R003"] == ["amount: not a number: 'abc'"] and why["R010"][0].startswith("status:")
    r2 = next(x for x in T["records"] if x["record_id"] == "R002")
    assert (r2["amount"], r2["event_date"], r2["status"]) == (1250.5, "2024-02-05", "done")   # coerced + canonical


def test_calc_is_deterministic():
    assert calc(SCHEMA, T, "total_amount")["value"] == 1390.5
    assert calc(SCHEMA, T, "total_amount", group_by="group_name")["value"]["Group A"] == 100
    assert calc(SCHEMA, T, "completion_rate")["value"] == 60.0
    assert calc(SCHEMA, T, "avg_amount", date_from="2024-04-01", date_to="2024-04-30")["value"] == 57.5


def test_ask_routes_to_calc():
    a = ask(SCHEMA, T, "Total amount for Group B in 2024")
    assert a["answer_type"] == "calculated" and a["calculation"]["value"] == 1250.5
    assert a["calculation"]["filters"]["group_name"] == "Group B"
    assert ask(SCHEMA, T, "What is the weather tomorrow?")["answer_type"] == "not_found"
