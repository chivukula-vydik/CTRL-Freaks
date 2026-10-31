"""UC5 flow. 1 context, 2 segments, 3 pre-checks, 4 strategy, 5 offer (all in app/domain/engage.py, no AI), then
6 the AI draft writer, 7 the message validator, 8 human review and 9 the mock outbox.
Every step writes a row to the insert-only audit_log. Gates 3, 5 and 7 re-run at edit, approve and send."""
import json
import time
import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel

from app import config, db, guard, llm, policy
from app.domain import engage as D


class EngageRequest(BaseModel):
    customer_id: str
    as_of_date: date | None = None


class BatchRequest(BaseModel):
    customer_ids: list[str] | None = None
    as_of_date: date | None = None


class EditRequest(BaseModel):
    subject: str
    body: str
    note: str = ""


class NoteRequest(BaseModel):
    note: str = ""


class Refused(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg
        super().__init__(msg)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _j(x) -> str:
    return json.dumps(x, default=str)


def _x(c, sql: str, params=()):
    return c.execute(*db._pg(sql, params))


# ---------------------------------------------------------------- audit ---------------------------------------
class Trail:
    """Collects one audit row per step; save() writes them all, inside the caller's transaction if one is given."""

    def __init__(self, cid: str | None, actor: str = "system", tid: str | None = None):
        self.tid, self.cid, self.actor, self.rows = tid or uuid.uuid4().hex[:12], cid, actor, []

    def step(self, step: str, rule: str | None = None, evidence=None, model_version: str | None = None, **record):
        self.rows.append((self.tid, len(self.rows) + 1, step, _now(), self.cid, self.actor, rule,
                          _j(evidence) if evidence is not None else None, model_version,
                          _j({"step": step, **record})))

    def save(self, c=None) -> str:
        sql = ("INSERT INTO audit_log (trace_id, seq, step, timestamp, customer_id, actor, rule, evidence, "
               "model_version, record) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
        if c is not None:
            with c.cursor() as cur:
                cur.executemany(sql, self.rows)
        else:
            with db.conn() as cc, cc.cursor() as cur:
                cur.executemany(sql, self.rows)
        return self.tid


def audit_trace(tid: str) -> list[dict]:
    rows = db.q("SELECT * FROM audit_log WHERE trace_id = ? ORDER BY seq", (tid,))
    for r in rows:
        r["record"] = json.loads(r["record"])
        r["evidence"] = json.loads(r["evidence"]) if r["evidence"] else None
    return rows


# ---------------------------------------------------------------- steps 1 to 5 --------------------------------
def decide(cid: str, as_of: date | None = None) -> dict:
    """Deterministic part of the pipeline. No AI, writes nothing. The eval and the tests call this."""
    ctx = D.context(cid.strip().upper(), as_of)
    if ctx is None:
        raise Refused(404, "customer not found")
    seg = D.classify(ctx)
    st = D.strategy(ctx, seg)
    blocks = D.precheck(ctx, st["message_type"])
    offer, decisions = (None, []) if blocks else D.select_offer(ctx, st, seg)
    f = D.facts(ctx, st, offer)
    f["plan"] = f["plan_type"]
    return {"ctx": ctx, "seg": seg, "strategy": st, "blocks": blocks, "offer": offer, "decisions": decisions, "facts": f}


def _evidence(ctx: dict) -> dict:
    c, cons = ctx["customer"], ctx["consent"]
    return {"plan_type": c["plan_type"], "tenure_months": c["tenure_months"], "account_status": c["account_status"],
            "last_activity_days": c["last_activity_days"], "activity_30d": c["activity_30d"],
            "activity_prev_30d": c["activity_prev_30d"], "loyalty_tier": c["loyalty_tier"],
            "on_time_payments_last_12": c["on_time_payments_last_12"], "bills_issued_last_12": c["bills_issued_last_12"],
            "reminder_bills": [{"bill_id": b["bill_id"], "outstanding": str(b["outstanding"]),
                                "due_date": str(b["due_date"]), "overdue_days": b["overdue_days"]}
                               for b in ctx["reminder_bills"]],
            "email_allowed": cons.get("email_allowed"), "marketing_consent": cons.get("marketing_consent"),
            "service_consent": cons.get("service_consent"), "email_status": cons.get("email_status"),
            "days_since_contact": ctx["days_since_contact"], "data_conflicts": ctx["conflicts"],
            "snapshot": str(ctx["snapshot"])}


def _applied(d: dict) -> list[dict]:
    pol, out = policy.policy(), []
    for s in d["seg"]["segments"]:
        node = pol["segments"].get(s["segment"])
        out.append({"rule_id": f"segments.{s['segment']}", "parameter": s["segment"], "value": node,
                    "source_doc_id": "config/policy.yaml"})
    out.append({"rule_id": f"strategies.{d['strategy']['name']}", "parameter": "strategy",
                "value": pol["strategies"][d["strategy"]["name"]], "source_doc_id": "config/policy.yaml"})
    out.append({"rule_id": "prechecks", "parameter": "cooldown_days/duplicate_days",
                "value": {k: pol["prechecks"][k] for k in ("cooldown_days", "duplicate_days")},
                "source_doc_id": "config/policy.yaml"})
    if d["strategy"]["offer"]:
        out.append({"rule_id": "offers.gates", "parameter": "gates", "value": policy.offers()["gates"],
                    "source_doc_id": "config/offers.yaml"})
    return out


# ---------------------------------------------------------------- step 6: AI draft writer ---------------------
def generate(d: dict) -> dict:
    """Claude writes the whole email around locked placeholders; code fills them after the check.
    If the AI is down or its text fails a check, the plain fallback text from ai_prompt.yaml is used."""
    st, offer, f, as_of = d["strategy"], d["offer"], d["facts"], d["ctx"]["snapshot"]
    cfg = policy.ai()
    req, allowed = D.allowed_placeholders(st, offer)
    if "total_amount" not in f:
        allowed.discard("total_amount")
    user = json.dumps({
        "strategy": st["name"], "goal": cfg["strategies"][st["name"]]["goal"], "tone": st["tone"],
        "language": f["language"], "required_placeholders": sorted(req),
        "optional_placeholders": sorted(allowed - req), "offer_allowed": bool(offer),
        "placeholder_meaning": {k: cfg["placeholders"][k] for k in sorted(allowed)}})
    warnings = []
    out = llm.chat_json(cfg["system"], user, required=["subject", "body"], temperature=cfg["model"]["temperature"],
                        max_tokens=cfg["model"]["max_tokens"])
    if out:
        subj, body = str(out["subject"]).strip(), str(out["body"]).strip()
        issues = D.check_placeholders(subj, body, st, offer)
        if not issues:
            cand = {"subject": D.fill(subj, f), "body": D.fill(body, f)}
            issues = D.validate(cand, f, st, offer, as_of)
            if not issues:
                return {**cand, "source": "ai", "warnings": [], "model": llm.usage()["model"]}
        warnings.append({"code": "AI_DRAFT_REJECTED",
                         "detail": "; ".join(i["code"] for i in issues) + ": fallback text used"})
    elif not config.MOCK_LLM:
        warnings.append({"code": "AI_UNAVAILABLE", "detail": "no usable AI answer (no key, error or invalid JSON): fallback text used"})
    fb = cfg["fallback"][st["name"]]
    ff = {**f, "offer_paragraph": D.fill(cfg["offer_paragraph"], f) if offer else ""}
    return {"subject": D.fill(fb["subject"], ff), "body": D.fill(fb["body"], ff), "source": "fallback",
            "warnings": warnings, "model": "fallback-text"}


# ---------------------------------------------------------------- run: steps 1 to 7, then store ----------------
def run(cid: str, as_of: date | None = None) -> dict:
    cid, t0 = cid.strip().upper(), time.time()
    llm.reset_usage()
    pending = db.q1("SELECT draft_id FROM drafts WHERE customer_id = ? AND status IN ('pending_review','approved') "
                    "ORDER BY created_at DESC LIMIT 1", (cid,))
    if pending:   # one open draft per customer; show it instead of creating a second one
        return {**get(pending["draft_id"]), "already_pending": True}
    d = decide(cid, as_of)
    ctx, seg, st, offer, f = d["ctx"], d["seg"], d["strategy"], d["offer"], d["facts"]
    tr = Trail(cid)
    tr.step("context", rule="policy.protected_fields (never selected)", evidence=_evidence(ctx),
            fields_dropped=policy.policy()["protected_fields"])
    tr.step("segments", rule="; ".join(f"segments.{s['segment']}" for s in seg["segments"]), evidence=seg["segments"],
            primary=seg["primary"], confidence=seg["confidence"])
    tr.step("prechecks", rule="prechecks.order", evidence=d["blocks"], passed=not d["blocks"])
    tr.step("strategy", rule=f"strategies.{st['name']}", evidence=st)
    tr.step("offer", rule="offers.gates", evidence=d["decisions"], chosen=offer["offer_id"] if offer else None)
    blocks, warnings = list(d["blocks"]), []
    draft, source, model = {"subject": "", "body": ""}, None, None
    if not blocks:
        g = generate(d)
        draft, source, model, warnings = {"subject": g["subject"], "body": g["body"]}, g["source"], g["model"], g["warnings"]
        u = llm.usage()
        tr.step("draft", rule="ai_prompt.yaml", model_version=model, source=source, warnings=warnings,
                llm_calls=u["llm_calls"], tokens=u["tokens"], llm_errors=u["llm_errors"])
        blocks = D.validate(draft, f, st, offer, ctx["snapshot"])
        tr.step("validate", rule="validator: 6 checks + placeholder integrity", evidence=blocks, passed=not blocks)
    status = "blocked" if blocks else "pending_review"
    did = "D-" + uuid.uuid4().hex[:10]
    checks = {"blocking": blocks, "warnings": warnings, "passed": not blocks}
    seg_doc = {"segments": seg["segments"], "primary": seg["primary"], "confidence": seg["confidence"]}
    now = _now()
    tr.step("stored", evidence={"draft_id": did, "status": status}, latency_ms=int((time.time() - t0) * 1000))
    with db.conn() as c:
        _x(c, "INSERT INTO drafts (draft_id, customer_id, as_of, segments, strategy, offer_id, facts, subject, body, "
              "checks, status, draft_source, template_version, model, trace_id, created_at, updated_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (did, cid, str(ctx["snapshot"]), _j(seg_doc), _j(st), offer["offer_id"] if offer else None, _j(f),
            draft["subject"], draft["body"], _j(checks), status, source, D.DOMAIN.TEMPLATE_VERSION,
            model or "none", tr.tid, now, now))
        tr.save(c)
    return {**get(did), "offer_decisions": d["decisions"], "evidence": _evidence(ctx), "applied_rules": _applied(d),
            "already_pending": False}


# ---------------------------------------------------------------- read -------------------------------------------
def _load(did: str) -> dict:
    row = db.q1("SELECT * FROM drafts WHERE draft_id = ?", (did,))
    if not row:
        raise Refused(404, "draft not found")
    for k in ("segments", "strategy", "facts", "checks"):
        row[k] = json.loads(row[k]) if row[k] else None
    return row


def get(did: str) -> dict:
    row = _load(did)
    offer = db.q1("SELECT * FROM offer_catalog WHERE offer_id = ?", (row["offer_id"],)) if row["offer_id"] else None
    seg = row["segments"] or {}
    return {**row, "as_of_date": row["as_of"], "draft": {"subject": row["subject"], "body": row["body"]},
            "primary_segment": seg.get("primary"), "confidence": seg.get("confidence"),
            "offer": json.loads(_j(offer)) if offer else None,
            "human_review_required": bool((row["strategy"] or {}).get("human_review_required"))}


def list_drafts(status: str | None = None) -> list[dict]:
    sql = "SELECT draft_id, customer_id, status, subject, updated_at FROM drafts"
    return db.q(sql + (" WHERE status = ?" if status else "") + " ORDER BY created_at DESC", (status,) if status else ())


# ---------------------------------------------------------------- re-run gates -----------------------------------
PRECHECK_CODES = set(policy.policy()["prechecks"]["order"])


def _recheck(row: dict, subject: str, body: str, gates: set[int]) -> dict:
    """Gate 3 pre-checks, gate 5 offer validator, gate 7 message validator, run again on current data."""
    as_of, st, f = date.fromisoformat(row["as_of"]), row["strategy"], row["facts"]
    ctx = D.context(row["customer_id"], as_of)
    offer = db.q1("SELECT * FROM offer_catalog WHERE offer_id = ?", (row["offer_id"],)) if row["offer_id"] else None
    blocking = []
    if 3 in gates:
        blocking += D.precheck(ctx, st["message_type"])
    if 5 in gates and offer:
        failed = [k for k, ok in D.offer_gates(ctx, offer, row["segments"]["primary"]).items() if not ok]
        if failed:
            blocking.append({"code": "offer_no_longer_valid", "detail": f"{offer['offer_id']} fails: {failed}"})
    if 7 in gates:
        blocking += D.validate({"subject": subject, "body": body}, f, st, offer, as_of)
    return {"blocking": blocking, "warnings": (row["checks"] or {}).get("warnings", []),
            "passed": not blocking, "rerun_gates": sorted(gates)}


def _note(did: str, cid: str, actor: str, event: str, rule: str, evidence, **rec) -> str:
    tr = Trail(cid, actor)
    tr.step(event, rule=rule, evidence=evidence, draft_id=did, **rec)
    return tr.save()


# ---------------------------------------------------------------- step 8: review ---------------------------------
def edit(did: str, req: EditRequest, reviewer: str) -> dict:
    row = _load(did)
    if row["status"] not in ("pending_review", "blocked") or not row["strategy"]:
        raise Refused(409, f"cannot edit a draft in status {row['status']}")
    if row["status"] == "blocked" and any(b["code"] in PRECHECK_CODES for b in (row["checks"] or {}).get("blocking", [])):
        raise Refused(409, "blocked at pre-check: editing cannot fix this; resolve the data issue or reject the draft")
    checks = _recheck(row, req.subject, req.body, {5, 7})
    status = "pending_review" if checks["passed"] else "blocked"
    db.execute("UPDATE drafts SET subject = ?, body = ?, checks = ?, status = ?, edited = 'Y', reviewer = ?, "
               "review_note = ?, updated_at = ? WHERE draft_id = ?",
               (req.subject, req.body, _j(checks), status, reviewer, req.note, _now(), did))
    tid = _note(did, row["customer_id"], reviewer, "edit", "re-run gates 5, 7", checks, note=req.note,
                status=status, subject=req.subject, body_redacted=guard.redact(req.body))
    return {"draft_id": did, "status": status, "checks": checks, "trace_id": tid}


def approve(did: str, req: NoteRequest, reviewer: str) -> dict:
    row = _load(did)
    if row["status"] != "pending_review":
        raise Refused(409, f"only a draft in pending_review can be approved (status {row['status']})")
    if (row["strategy"] or {}).get("human_review_required") and policy.policy()["review"]["stage3_requires_note"] \
            and not req.note.strip():
        raise Refused(409, "final notices need a reviewer note before approval")
    checks = _recheck(row, row["subject"], row["body"], {3, 5, 7})
    if not checks["passed"]:
        db.execute("UPDATE drafts SET checks = ?, status = 'blocked', updated_at = ? WHERE draft_id = ?",
                   (_j(checks), _now(), did))
        _note(did, row["customer_id"], reviewer, "approve_refused", "re-run gates 3, 5, 7", checks)
        raise Refused(409, "checks no longer pass: " + ", ".join(b["code"] for b in checks["blocking"]))
    db.execute("UPDATE drafts SET status = 'approved', checks = ?, reviewer = ?, review_note = ?, updated_at = ? "
               "WHERE draft_id = ?", (_j(checks), reviewer, req.note, _now(), did))
    tid = _note(did, row["customer_id"], reviewer, "approve", "re-run gates 3, 5, 7", checks, note=req.note)
    return {"draft_id": did, "status": "approved", "checks": checks, "trace_id": tid}


def reject(did: str, req: NoteRequest, reviewer: str) -> dict:
    row = _load(did)
    if row["status"] in ("sent", "rejected"):
        raise Refused(409, f"draft already {row['status']}")
    db.execute("UPDATE drafts SET status = 'rejected', reviewer = ?, review_note = ?, updated_at = ? WHERE draft_id = ?",
               (reviewer, req.note, _now(), did))
    tid = _note(did, row["customer_id"], reviewer, "reject", "human decision", None, note=req.note)
    return {"draft_id": did, "status": "rejected", "trace_id": tid}


# ---------------------------------------------------------------- step 9: mock outbox ----------------------------
def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "***"
    local, dom = email.split("@", 1)
    return f"{local[:1]}***@{dom}"


def send(did: str, reviewer: str) -> dict:
    """Mock delivery. Approved drafts only; gates 3, 5, 7 run again before anything is written. The outbox row,
    the contact_history row, the draft status and the audit row are written in one transaction."""
    row = _load(did)
    if row["status"] != "approved":
        _note(did, row["customer_id"], reviewer, "send_refused", "status gate", None,
              reason=f"status {row['status']}, not approved")
        raise Refused(409, f"refused: draft is {row['status']}; only approved drafts can be sent")
    checks = _recheck(row, row["subject"], row["body"], {3, 5, 7})
    if not checks["passed"]:
        _note(did, row["customer_id"], reviewer, "send_refused", "re-run gates 3, 5, 7", checks)
        raise Refused(409, "refused: " + ", ".join(b["code"] for b in checks["blocking"]))
    cust = db.q1("SELECT email_address FROM customers WHERE customer_id = ?", (row["customer_id"],))
    mid, now, st = "M-" + uuid.uuid4().hex[:8], _now(), row["strategy"]
    tr = Trail(row["customer_id"], reviewer)
    tr.step("send", rule="re-run gates 3, 5, 7", evidence=checks, draft_id=did, message_id=mid, send_status="MOCK_SENT")
    with db.conn() as c:
        _x(c, "INSERT INTO outbox (message_id, draft_id, customer_id, to_email_masked, subject, body, queued_at, status) "
              "VALUES (?,?,?,?,?,?,?,?)", (mid, did, row["customer_id"], mask(cust["email_address"]), row["subject"],
                                           row["body"], now, "MOCK_SENT"))
        _x(c, "INSERT INTO contact_history (message_id, customer_id, sent_at, channel, message_type, segment, "
              "template_id, offer_id, bill_id, outcome) VALUES (?,?,?,?,?,?,?,?,?,?)",
           (mid, row["customer_id"], date.fromisoformat(row["as_of"]), "email", st["message_type"],
            row["segments"]["primary"], D.DOMAIN.TEMPLATE_VERSION, row["offer_id"], st.get("target_bill_id"), "mock_sent"))
        _x(c, "UPDATE drafts SET status = 'sent', updated_at = ? WHERE draft_id = ?", (now, did))
        tr.save(c)
    return {"draft_id": did, "status": "sent", "message_id": mid, "trace_id": tr.tid}


def outbox() -> list[dict]:
    return db.q("SELECT * FROM outbox ORDER BY queued_at DESC")
