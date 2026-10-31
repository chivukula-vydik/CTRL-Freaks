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
    prot = set(policy.policy()["protected_fields"])
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


def test_sms_only_offer_is_never_chosen_for_email(client):
    for cid, g in GT.items():
        if g["expected_segment"] == "loyalty_candidate" and g["expected_outcome"] == "draft":
            assert (engage.decide(cid)["offer"] or {}).get("offer_id") != "OFR-RWD-SMS"


# ------------------------------------------------------------------ step 6 AI writer
GOOD = {"subject": "Reminder: bill {bill_id}", "body": "Hi {first_name},\n\nA gentle reminder that {amount} for bill "
        "{bill_id} was due on {due_date}. It is {overdue_days} days overdue.\n\nTo dispute this bill write to "
        "{dispute_contact} or call {support_phone}.\n\nRegards,\nCustomer Care"}


def overdue_customer():
    return pick("clean_payment_reminder", expected_strategy="overdue_stage_1_polite")


def test_ai_text_with_valid_placeholders_is_used(client, monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: dict(GOOD))
    r = run(client, overdue_customer())
    assert r["draft_source"] == "ai" and r["status"] == "pending_review"
    assert "{" not in r["draft"]["body"] and r["facts"]["amount"] in r["draft"]["body"]


@pytest.mark.parametrize("bad_body,code", [
    ("Hi {first_name}, pay Rs 5000 now. Dispute at {dispute_contact}, call {support_phone}. {amount} {due_date} {overdue_days} {bill_id}", "UNSUPPORTED_NUMBER"),
    ("Hi {first_name}, {amount} was due on {due_date}, {bill_id}, {overdue_days}. Dispute at {dispute_contact}, call {support_phone}. Pay by 15 Nov 2026.", "UNSUPPORTED_DATE"),
    ("Hi {first_name}, {amount} was due {due_date}. Dispute at {dispute_contact}, call {support_phone}.", "PLACEHOLDER_MISSING"),
    ("Hi {first_name}, {amount} {due_date} {bill_id} {overdue_days} {dispute_contact} {support_phone} {credit_limit}", "PLACEHOLDER_UNKNOWN"),
    ("Hi {first_name}, {amount} {due_date} {bill_id} {overdue_days} {dispute_contact} {support_phone}. Pay or face legal action.", "BLOCKED_PHRASE"),
])
def test_bad_ai_text_falls_back_and_is_logged(client, monkeypatch, bad_body, code):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {"subject": "Reminder {bill_id}", "body": bad_body})
    r = run(client, overdue_customer())
    assert r["draft_source"] == "fallback" and r["status"] == "pending_review"
    w = [x for x in r["checks"]["warnings"] if x["code"] == "AI_DRAFT_REJECTED"]
    assert w and code in w[0]["detail"]


def test_ai_never_sees_customer_values(client, monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **k: seen.append(user) or dict(GOOD))
    cid = overdue_customer()
    r = run(client, cid)
    text = seen[0]
    assert r["facts"]["amount"] not in text and r["facts"]["first_name"] not in text and cid not in text


def test_validator_catches_unapproved_offer_words():
    d = engage.decide(pick("clean_payment_reminder", expected_strategy="overdue_stage_1_polite"))
    draft = {"subject": "s", "body": f"Hi {d['facts']['first_name']}, enjoy a free cashback offer OFR-XYZ-9. "
             f"{d['facts']['dispute_contact']} {d['facts']['support_phone']}"}
    got = {i["code"] for i in D.validate(draft, d["facts"], d["strategy"], None, d["ctx"]["snapshot"])}
    assert {"UNKNOWN_OFFER", "UNAUTHORIZED_OFFER"} <= got


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
    assert {"UNSUPPORTED_NUMBER", "BLOCKED_PHRASE", "MISSING_DISPUTE_PATH"} <= {b["code"] for b in e["checks"]["blocking"]}
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


def test_policy_endpoint_exposes_thresholds(client):
    p = client.get("/policy").json()
    assert p["policy"]["segments"]["dormant"]["last_activity_days_gte"] == 30
    assert p["offers"]["repeat_guard_days"] == 90
