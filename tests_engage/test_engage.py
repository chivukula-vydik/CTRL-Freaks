"""UC5 scenarios: the five required segments, blocked cases, review flow and mock send."""
import pytest

H = {"X-Admin-Key": "test-admin-key", "X-Reviewer": "tester"}
AS_OF = "2026-10-31"


def engage(client, cid):
    r = client.post("/engage", json={"customer_id": cid, "as_of_date": AS_OF}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def codes(r):
    return {b["code"] for b in r["checks"]["blocking"]}


@pytest.mark.parametrize("cid,segment,template,offer", [
    ("C1001", "consistent", "APPRECIATION", None),
    ("C1002", "loyalty_candidate", "REWARD", "OFF-LOY-500"),
    ("C1003", "declining", "REENGAGE", "OFF-RE-20"),
    ("C1004", "dormant", "WINBACK", "OFF-WB-30"),
    ("C1005", "payment_reminder", "REM2", None),
    ("C1006", "payment_reminder", "REM1", None),
    ("C1011", "payment_reminder", "REM3", None),
])
def test_scenarios(client, cid, segment, template, offer):
    r = engage(client, cid)
    assert r["status"] == "pending_review", r["checks"]
    assert r["primary_segment"] == segment and r["strategy"]["template"] == template
    assert (r["offer"] or {}).get("offer_id") == offer
    assert r["segments"][0]["reasons"] and r["applied_rules"] and r["citations"]


def test_reminder_details(client):
    # 4 days overdue, 36 months tenure: courteous + thanks + dispute path (draft left in review by test_scenarios)
    d = [x for x in client.get("/drafts?status=pending_review", headers=H).json() if x["customer_id"] == "C1006"][0]
    body = client.get(f"/drafts/{d['draft_id']}", headers=H).json()["body"]
    assert "Thank you for being a valued customer" in body and "billing-disputes@example.com" in body
    assert "1299.00" in body and "2026-10-27" in body


def test_offer_decisions_explain_rejections(client):
    d = {x["offer_id"]: x for x in engage(client, "C1003")["offer_decisions"]}
    assert d["OFF-RE-20"]["eligible"] and not d["OFF-OLD-15"]["eligible"]   # expired campaign rejected


@pytest.mark.parametrize("cid,code", [
    ("C1007", "NO_CONSENT"), ("C1008", "CONTRADICTORY_DATA"), ("C1009", "RECENT_CONTACT"),
    ("C1010", "DISPUTED_INVOICE"), ("C1012", "NO_SEGMENT"),
])
def test_blocked_without_generation(client, cid, code):
    r = engage(client, cid)
    assert r["status"] == "blocked" and code in codes(r) and r["draft"]["body"] == ""


def test_cooldown_uses_circular(client):
    r = engage(client, "C1009")
    assert any(x["rule_id"] == "COMM-COOL-02" for x in r["applied_rules"])   # 5 days, superseding 7


def test_second_run_is_duplicate(client):
    assert "PENDING_DRAFT_EXISTS" in codes(engage(client, "C1003"))   # draft from test_scenarios still in review


def test_review_flow_and_mock_send(client):
    r = engage(client, "C1001")
    did = r["draft_id"] if r["status"] == "pending_review" else None
    if did is None:   # an earlier test already left a draft in review for C1001
        did = client.get("/drafts?status=pending_review", headers=H).json()[0]["draft_id"]
    assert client.post(f"/drafts/{did}/send", headers=H).status_code == 409       # not approved yet
    assert client.post(f"/drafts/{did}/approve", json={"note": "ok"}, headers=H).json()["status"] == "approved"
    s = client.post(f"/drafts/{did}/send", headers=H).json()
    assert s["status"] == "sent" and any(m["draft_id"] == did for m in client.get("/outbox", headers=H).json())
    again = engage(client, "C1001")
    assert again["status"] == "blocked" and "RECENT_CONTACT" in codes(again)    # frequency control after send


def test_edit_with_invented_amount_is_blocked(client):
    r = engage(client, "C1005")
    did = r["draft_id"] if r["status"] == "pending_review" else \
        [d for d in client.get("/drafts?status=pending_review", headers=H).json() if d["customer_id"] == "C1005"][0]["draft_id"]
    e = client.post(f"/drafts/{did}/edit", headers=H, json={
        "subject": "Payment overdue", "body": "Pay Rs 5000 immediately or face legal action."}).json()
    assert e["status"] == "blocked"
    assert {"UNSUPPORTED_NUMBER", "BLOCKED_PHRASE", "MISSING_DISPUTE_PATH"} <= {b["code"] for b in e["checks"]["blocking"]}
    assert client.post(f"/drafts/{did}/approve", json={}, headers=H).status_code == 409


def test_staff_only(client):
    assert client.post("/engage", json={"customer_id": "C1001"}).status_code == 403
    assert client.get("/drafts").status_code == 403


def test_audit_written(client):
    r = engage(client, "C1004")
    rec = client.get(f"/audit/{r['trace_id']}", headers=H).json()
    assert rec["event"] == "engage" and rec["template_version"] == "tpl-v1" and rec["checks"]
