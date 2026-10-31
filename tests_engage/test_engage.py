"""UC5 backend v2: answer key, pipeline, AI writer, re-run gates, outbox transaction, audit log."""
import json
import re

import psycopg
import pytest

from app import db, engage, llm, policy
from app.domain import engage as D
from eval import groundtruth as gt
from tests_engage.conftest import H

GT = gt.load()


def pick(tag_prefix=None, **want):
    """First customer from the answer key with the given tag prefix and expected fields."""
    for cid, g in GT.items():
        if tag_prefix and not g["scenario_tag"].startswith(tag_prefix):
            continue
        if all(g[k] == v for k, v in want.items()):
            return cid
    raise AssertionError(f"no customer for {tag_prefix} {want}")


def run(client, cid):
    r = client.post("/engage", json={"customer_id": cid}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def codes(r):
    return {b["code"] for b in r["checks"]["blocking"]}


# ------------------------------------------------------------------ the answer key
def test_all_222_customers_match_the_answer_key():
    bad = {}
    for cid, g in GT.items():
        m = gt.mismatches(engage.decide(cid), g)
        if m:
            bad[cid] = (g["scenario_tag"], m)
    assert not bad, f"{len(bad)} customers differ from ground_truth.csv, first: {list(bad.items())[:3]}"


def test_protected_fields_are_never_read():
    prot = set(policy.policy()["message"]["pii_fields_to_drop"])
    assert not prot & set(D.CUSTOMER_COLS)
    d = engage.decide("C1001")
    assert not prot & set(d["ctx"]["customer"]) and not prot & set(d["facts"])


# ------------------------------------------------------------------ pipeline over the API
@pytest.mark.parametrize("tag,seg", [("clean_consistent", "consistent"), ("clean_loyalty_candidate", "loyalty_candidate"),
                                     ("clean_declining_activity", "declining_activity"), ("clean_dormant", "dormant"),
                                     ("clean_payment_reminder", "payment_reminder")])
def test_clean_customers_get_a_checked_draft(client, tag, seg):
    cid = pick(tag)
    r = run(client, cid)
    assert r["status"] == "pending_review", r["checks"]
    assert r["primary_segment"] == seg and r["segments"]["segments"][0]["reasons"] and r["applied_rules"]
    assert r["draft"]["body"] and r["draft_source"] in ("ai", "fallback") and r["checks"]["passed"]
    assert r["facts"]["first_name"] in r["draft"]["body"]


def test_blocked_customers_get_no_draft_and_no_offer(client):
    cid = pick("block_dispute_open")
    r = run(client, cid)
    assert r["status"] == "blocked" and "dispute_or_complaint_open" in codes(r)
    assert r["draft"]["body"] == "" and r["offer"] is None


def test_second_run_returns_the_open_draft(client):
    cid = pick("clean_consistent")
    first, again = run(client, cid), run(client, cid)
    assert again["already_pending"] and again["draft_id"] == first["draft_id"]
    assert len(client.get("/drafts", headers=H).json()) == 1


def test_offer_decisions_explain_rejections(client):
    cid = pick("offer_declining_skips_expired_and_future")
    r = run(client, cid)
    dec = {x["offer_id"]: x for x in r["offer_decisions"]}
    assert dec["OFR-REE-EXP"]["reasons"] == ["expiry"] and "expiry" in dec["OFR-REE-FUT"]["reasons"]
    assert r["offer"]["offer_id"] == GT[cid]["expected_offer_id"]


def test_offers_yaml_mirrors_the_offer_catalog():
    import csv
    rows = {r["offer_id"]: r for r in csv.DictReader((gt.ROOT / "data/dataset/offer_catalog.csv").open(encoding="utf-8"))}
    yml = {o["offer_id"]: o for o in policy.offers()["offers"]}
    assert yml.keys() == rows.keys()
    for oid, o in yml.items():
        r = rows[oid]
        assert (o["name"], o["message_type"], "|".join(o["eligible_segments"]), o["plan_type"], o["channel"],
                o["valid_from"], o["expiry_date"], str(o["min_tenure_months"]), str(o["priority"]), o["value"],
                o["value_unit"], o["terms_text"]) == (r["offer_name"], r["message_type"], r["eligible_segments"],
                r["plan_type"], r["channel"], r["valid_from"], r["expiry_date"], r["min_tenure_months"], r["priority"],
                r["value"], r["value_unit"], r["terms"]), oid


def test_sms_only_offer_is_never_chosen_for_email(client):
    for cid, g in GT.items():
        if g["expected_segment"] == "loyalty_candidate" and g["expected_outcome"] == "draft":
            assert (engage.decide(cid)["offer"] or {}).get("offer_id") != "OFR-RWD-SMS"


# ------------------------------------------------------------------ step 6 AI writer, step 7 validator
GOOD = ("Hi {first_name},\n\nA gentle reminder that your payment of {amount} was due on {due_date} and is still "
        "outstanding. Please pay when you can, or reply if you need help.\n\nKind regards,\nCustomer Care Team")


def overdue_customer():
    return pick("clean_payment_reminder", expected_strategy="overdue_stage_1_polite")


def test_ai_text_with_valid_placeholders_is_used(client, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: GOOD)
    r = run(client, overdue_customer())
    assert r["draft_source"] == "ai" and r["status"] == "pending_review"
    assert "{" not in r["draft"]["body"] and r["facts"]["amount"] in r["draft"]["body"]
    assert r["draft"]["subject"] == policy.ai()["subjects"]["overdue_notice"]


@pytest.mark.parametrize("bad_body,code", [
    ("Hi {first_name}, pay Rs 5000 now. {amount} was due {due_date}. Regards, Customer Care Team", "NO_INJECTED_CURRENCY"),
    ("Hi {first_name}, {amount} was due on {due_date}. Please pay by November 15. Regards, Customer Care Team", "NO_INJECTED_DATES"),
    ("Hi {first_name}, {amount} is overdue, please pay soon so we can help you. Regards, Customer Care Team", "PLACEHOLDER_PRESENCE"),
    ("Hi {first_name}, {amount} was due {due_date}. Your limit is {credit_limit}. Regards, Customer Care Team", "PLACEHOLDER_UNKNOWN"),
    ("Hi {first_name}, {amount} was due {due_date}. Pay or we take legal steps. Regards, Customer Care Team", "TONE_CHECK"),
    ("Your payment of {amount} for {first_name} was due on {due_date}. Please pay. Regards, Customer Care Team", "GREETING_CHECK"),
    ("Hi {first_name}, {amount} was due {due_date}. Call 9876543210 to pay. Regards, Customer Care Team", "PII_CHECK"),
])
def test_bad_ai_text_is_retried_then_falls_back(client, monkeypatch, bad_body, code):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: calls.append(1) or bad_body)
    r = run(client, overdue_customer())
    assert len(calls) == policy.ai()["fallback"]["max_retries"] + 1          # on_any_fail: back to the AI
    assert r["draft_source"] == "fallback" and r["status"] == "pending_review"
    w = [x for x in r["checks"]["warnings"] if x["code"] == "AI_DRAFT_REJECTED"]
    assert w and code in w[0]["detail"]


def test_rejected_ai_text_gets_a_second_try_with_the_reasons(client, monkeypatch):
    users = []
    answers = iter(["Hi {first_name}, pay Rs 5000. Regards, Customer Care Team", GOOD])
    monkeypatch.setattr(llm, "chat", lambda system, user, **k: users.append(user) or next(answers))
    r = run(client, overdue_customer())
    assert r["draft_source"] == "ai" and len(users) == 2 and "failed these checks" in users[1]


def test_ai_never_sees_customer_values(client, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "chat", lambda system, user, **k: seen.append(system + user) or GOOD)
    cid = overdue_customer()
    r = run(client, cid)
    text = seen[0]
    assert "{amount}" in text and "polite" in text
    for v in (r["facts"]["amount"], r["facts"]["first_name"], r["facts"]["due_date"], cid, r["strategy"]["amount_outstanding"]):
        assert v not in text


def test_validator_catches_offer_talk_without_an_offer():
    d = engage.decide(overdue_customer())
    f = d["facts"]
    draft = {"subject": "s", "body": f"Hi {f['first_name']}, {f['amount']} was due {f['due_date']}. Enjoy free data "
                                     "and {offer_terms}. Regards, Customer Care Team"}
    got = {i["code"] for i in D.validate(draft, f, d["strategy"], None)}
    assert {"NO_INJECTED_OFFER_WORDS", "PLACEHOLDER_UNKNOWN"} <= got


def test_filled_values_round_trip_through_the_validator():
    d = engage.decide(pick("clean_loyalty_candidate", expected_offer_id="OFR-RWD-2GB"))
    f = d["facts"]
    body = (f"Hello {f['first_name']}, thank you for being a valued {f['plan_name']} customer with {f['loyalty_points']} "
            f"points. Here is a gift: {f['offer_terms']}. Kind regards, Customer Care Team")
    assert D.validate({"subject": "Thanks", "body": body}, f, d["strategy"], d["offer"]) == []
    assert "NO_INJECTED_DIGITS" in {i["code"] for i in D.validate(
        {"subject": "Thanks", "body": body.replace(f["loyalty_points"], "99999")}, f, d["strategy"], d["offer"])}


# ------------------------------------------------------------------ steps 8 and 9: review, gates, outbox
def approve_ready(client, cid, note="ok"):
    r = run(client, cid)
    assert r["status"] == "pending_review", r["checks"]
    a = client.post(f"/drafts/{r['draft_id']}/approve", json={"note": note}, headers=H)
    assert a.status_code == 200, a.text
    return r["draft_id"]


def test_review_flow_masks_email_and_blocks_a_second_message(client):
    cid = pick("clean_consistent")
    did = run(client, cid)["draft_id"]
    assert client.post(f"/drafts/{did}/send", headers=H).status_code == 409           # not approved yet
    client.post(f"/drafts/{did}/approve", json={"note": "ok"}, headers=H)
    s = client.post(f"/drafts/{did}/send", headers=H).json()
    assert s["status"] == "sent"
    box = [m for m in client.get("/outbox", headers=H).json() if m["draft_id"] == did][0]
    assert re.fullmatch(r".\*\*\*@.+", box["to_email_masked"])
    assert db.q1("SELECT 1 AS x FROM contact_history WHERE message_id = ?", (s["message_id"],))
    again = run(client, cid)
    assert again["status"] == "blocked" and "cooldown_or_duplicate" in codes(again)


def test_edit_with_invented_amount_is_blocked(client):
    did = run(client, overdue_customer())["draft_id"]
    e = client.post(f"/drafts/{did}/edit", headers=H, json={
        "subject": "Overdue", "body": "Pay Rs 5000 immediately or face legal action."}).json()
    assert e["status"] == "blocked" and e["checks"]["rerun_gates"] == [5, 7]
    assert {"NO_INJECTED_CURRENCY", "TONE_CHECK", "GREETING_CHECK", "PLACEHOLDER_PRESENCE"} <= {b["code"] for b in e["checks"]["blocking"]}
    assert client.post(f"/drafts/{did}/approve", json={}, headers=H).status_code == 409


def test_precheck_block_cannot_be_edited_away(client):
    did = run(client, pick("block_dispute_open"))["draft_id"]
    r = client.post(f"/drafts/{did}/edit", headers=H, json={"subject": "Hi", "body": "Hi there"})
    assert r.status_code == 409


def test_final_notice_needs_a_reviewer_note(client):
    cid = pick(expected_strategy="overdue_stage_3_final", expected_outcome="draft")
    r = run(client, cid)
    assert r["human_review_required"] and r["strategy"]["stage"] == 3
    assert client.post(f"/drafts/{r['draft_id']}/approve", json={}, headers=H).status_code == 409
    assert client.post(f"/drafts/{r['draft_id']}/approve", json={"note": "checked with billing"}, headers=H).status_code == 200


def test_gate_5_rechecks_the_offer_at_approval(client):
    cid = pick("clean_loyalty_candidate", expected_offer_id="OFR-RWD-2GB")
    did = run(client, cid)["draft_id"]
    try:
        db.execute("UPDATE offer_catalog SET expiry_date = DATE '2026-10-01' WHERE offer_id = 'OFR-RWD-2GB'")
        a = client.post(f"/drafts/{did}/approve", json={"note": "x"}, headers=H)
        assert a.status_code == 409 and "offer_no_longer_valid" in a.text
    finally:
        db.execute("UPDATE offer_catalog SET expiry_date = DATE '2026-11-30' WHERE offer_id = 'OFR-RWD-2GB'")


def test_gate_3_rechecks_contact_history_before_send(client):
    cid = pick("clean_consistent")
    did = approve_ready(client, cid)
    db.execute("INSERT INTO contact_history (message_id, customer_id, sent_at, channel, message_type, segment, outcome) "
               "VALUES ('M-TESTX', ?, DATE '2026-10-26', 'email', 'appreciation', 'consistent', 'mock_sent')", (cid,))
    s = client.post(f"/drafts/{did}/send", headers=H)
    assert s.status_code == 409 and "cooldown_or_duplicate" in s.text
    assert client.get("/outbox", headers=H).json() == []


def test_send_is_one_transaction(client):
    cid = pick("clean_payment_reminder", expected_strategy="overdue_stage_1_polite")
    did = approve_ready(client, cid)
    row = db.q1("SELECT strategy FROM drafts WHERE draft_id = ?", (did,))
    st = json.loads(row["strategy"]); st["target_bill_id"] = "B-DOES-NOT-EXIST"    # contact_history FK will fail
    db.execute("UPDATE drafts SET strategy = ? WHERE draft_id = ?", (json.dumps(st), did))
    with pytest.raises(Exception):
        client.post(f"/drafts/{did}/send", headers=H)
    assert db.q("SELECT * FROM outbox") == []
    assert db.q1("SELECT status FROM drafts WHERE draft_id = ?", (did,))["status"] == "approved"


def test_staff_only(client):
    assert client.post("/engage", json={"customer_id": "C1001"}).status_code == 403
    assert client.get("/drafts").status_code == 403


# ------------------------------------------------------------------ audit log
def test_audit_has_one_row_per_step_and_is_insert_only(client):
    r = run(client, overdue_customer())
    a = client.get(f"/audit/{r['trace_id']}", headers=H).json()
    assert [s["step"] for s in a["steps"]] == ["context", "segments", "prechecks", "strategy", "offer", "draft",
                                               "validate", "stored"]
    assert all(s["template_version"] == D.DOMAIN.TEMPLATE_VERSION for s in a["steps"])
    assert a["steps"][5]["model_version"] and all(s["actor"] and s["rule"] is not None or s["step"] == "stored" for s in a["steps"])
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE audit_log SET actor = 'x' WHERE trace_id = ?", (r["trace_id"],))
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("DELETE FROM audit_log WHERE trace_id = ?", (r["trace_id"],))
    import csv
    raw = {x["customer_id"]: x for x in csv.DictReader((gt.ROOT / "data/dataset/customers.csv").open(encoding="utf-8"))}[r["customer_id"]]
    blob = json.dumps(a) + json.dumps(r)
    assert not any(raw[k] in blob for k in ("date_of_birth", "home_address", "phone", "national_id_last4"))
    assert client.get(f"/audit/{r['trace_id']}").status_code == 404   # no key, no subject


def test_review_actions_are_audited_with_the_reviewer(client):
    did = run(client, pick("clean_consistent"))["draft_id"]
    t = client.post(f"/drafts/{did}/reject", json={"note": "tone"}, headers=H).json()["trace_id"]
    s = client.get(f"/audit/{t}", headers=H).json()["steps"][0]
    assert s["step"] == "reject" and s["actor"] == "tester"


def test_reviewer_edit_that_keeps_the_facts_passes(client):
    r = run(client, overdue_customer())
    f = r["facts"]
    body = f"Dear {f['first_name']},\n\nYour payment of {f['amount']} was due on {f['due_date']}. Please pay soon.\n\nKind regards,\nCustomer Care Team"
    e = client.post(f"/drafts/{r['draft_id']}/edit", headers=H, json={"subject": "Payment reminder", "body": body}).json()
    assert e["status"] == "pending_review", e["checks"]


def test_policy_endpoint_exposes_the_yaml_rules(client):
    p = client.get("/policy").json()
    assert p["policy"]["segmentation"]["thresholds"]["dormant_days"] == 30
    assert p["offers"]["selection"]["repeat_guard_days"] == 90
    assert [c["id"] for c in p["validator"]["checks"]] == ["MV-01", "MV-02", "MV-03", "MV-04", "MV-05", "MV-06"]
    assert {o["offer_id"] for o in p["catalog"]} >= {"OFR-RWD-2GB", "OFR-REE-3GB"}


def test_audit_list_and_evaluation_for_the_console(client):
    run(client, pick("clean_consistent"))
    rows = client.get("/audit", headers=H).json()
    assert rows and rows[0]["step"] == "stored" and "evidence" not in rows[0]
    assert client.get("/audit").status_code == 403
    ev = client.get("/evaluation", headers=H).json()
    assert ev["accuracy"] == {"correct": 222, "total": 222} and len(ev["confusion"]) == len(ev["labels"])
    assert ev["grounded"]["total"] == 1 and ev["grounded"]["matched"] == 1
