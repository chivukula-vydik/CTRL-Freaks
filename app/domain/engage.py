"""UC5 deterministic steps: 1 context, 2 segments, 3 pre-checks, 4 strategy, 5 offers, and the message validator (7).
No AI in this file. Every threshold and rule comes from the YAMLs in config/ (policy, segmentation_rules,
data_conflict_rules, offers, offer_validator_rules, message_validator_rules); data from the five Supabase tables
(customers, billing, consent, contact_history, offer_catalog)."""
import re
from datetime import date
from decimal import Decimal

from app import db, policy
from app.domain.base import Domain

# Only these columns are ever selected. The PII fields (DOB, gender, address, phone, national id, credit score;
# policy.yaml message.pii_fields_to_drop) are never read, so they cannot reach the classifier, the audit log or the AI.
CUSTOMER_COLS = ["customer_id", "first_name", "email_address", "snapshot_date", "tenure_months", "plan_type",
                 "plan_id", "plan_price", "account_status", "preferred_language", "activity_unit",
                 "last_activity_days", "activity_30d", "activity_prev_30d", "loyalty_points", "loyalty_tier",
                 "loyalty_points_expiry_date", "on_time_payments_last_12", "bills_issued_last_12"]


def _d(x) -> Decimal:
    return Decimal(str(x if x not in (None, "") else 0))


def money(v: Decimal, cur: str = "INR") -> str:
    return f"{cur or 'INR'} {v:.2f}"


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def _seg() -> dict:
    return policy.policy()["segmentation"]


# ---------------------------------------------------------------- step 1: context ----------------------------
HIST_COLS = "message_id, sent_at, channel, message_type, segment, offer_id, bill_id"


def preload() -> dict:
    """Every customer's rows in five queries, for whole-dataset runs (evaluation). Same columns and order as
    context() reads one customer at a time."""
    def by(rows):
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(r["customer_id"], []).append(r)
        return out
    return {
        "customers": {r["customer_id"]: r for r in db.q(f"SELECT {', '.join(CUSTOMER_COLS)} FROM customers")},
        "consent": {r["customer_id"]: r for r in db.q("SELECT * FROM consent")},
        "billing": by(db.q("SELECT * FROM billing ORDER BY customer_id, due_date, bill_id")),
        "history": by(db.q(f"SELECT customer_id, {HIST_COLS} FROM contact_history ORDER BY customer_id, sent_at DESC")),
        "offers": db.q("SELECT * FROM offer_catalog ORDER BY priority, offer_id"),
    }


def context(cid: str, as_of: date | None = None, pre: dict | None = None) -> dict | None:
    if pre is not None:
        c = pre["customers"].get(cid)
        cons = dict(pre["consent"].get(cid) or {})
        bills = [dict(b) for b in pre["billing"].get(cid, [])]
        hist = [{k: h[k] for k in h if k != "customer_id"} for h in pre["history"].get(cid, [])]
    else:
        c = db.q1(f"SELECT {', '.join(CUSTOMER_COLS)} FROM customers WHERE customer_id = ?", (cid,))
        cons = (db.q1("SELECT * FROM consent WHERE customer_id = ?", (cid,)) or {}) if c else {}
        bills = db.q("SELECT * FROM billing WHERE customer_id = ? ORDER BY due_date, bill_id", (cid,)) if c else []
        hist = db.q(f"SELECT {HIST_COLS} FROM contact_history WHERE customer_id = ? ORDER BY sent_at DESC", (cid,)) if c else []
    if not c:
        return None
    snap = as_of or c["snapshot_date"]
    within = _seg()["thresholds"]["reminder_window_days"]
    for b in bills:
        b["outstanding"] = max(_d(b["amount_due"]) - _d(b["amount_paid"]), Decimal("0"))
        b["days_to_due"] = (b["due_date"] - snap).days
        b["overdue_days"] = -b["days_to_due"]            # signed: negative means not yet due
        b["unpaid"] = b["bill_status"] in ("due", "overdue")
        b["reminder"] = b["unpaid"] and b["days_to_due"] <= within     # overdue, or due within the window
    reminder = [b for b in bills if b["reminder"]]
    target = reminder[0] if reminder else None                         # oldest first (ORDER BY due_date)
    ctx = {
        "customer": c, "consent": cons, "bills": bills, "history": hist, "snapshot": snap,
        "reminder_bills": reminder, "target": target,
        "total_outstanding": sum((b["outstanding"] for b in reminder), Decimal("0")),
        "days_since_contact": (snap - hist[0]["sent_at"]).days if hist else None,
        "days_since_type": {}, "offers": pre["offers"] if pre is not None else None,
    }
    for h in hist:   # newest first
        ctx["days_since_type"].setdefault(h["message_type"], (snap - h["sent_at"]).days)
    ctx["conflicts"] = _conflicts(ctx)
    return ctx


def tier_for(points: int) -> str:
    for name, (lo, hi) in _seg()["tier_points"].items():
        if points >= lo and (hi is None or points <= hi):
            return name
    return next(iter(_seg()["tier_points"]))


def _conflicts(ctx: dict) -> list[str]:
    """data_conflict_rules.yaml: every check runs; only the codes listed there are reported, sorted."""
    c, cons, snap, out = ctx["customer"], ctx["consent"], ctx["snapshot"], []
    for b in ctx["bills"]:
        paid = b["bill_status"] == "paid"
        if paid and _d(b["amount_paid"]) != _d(b["amount_due"]):
            out.append("PAID_AMOUNT_MISMATCH")
        if paid and not b["last_payment_date"]:
            out.append("PAID_NO_PAYMENT_DATE")
        if b["unpaid"] and _d(b["amount_paid"]) >= _d(b["amount_due"]):
            out.append("UNPAID_BUT_FULLY_PAID")
        if (b["bill_status"] == "overdue" and b["due_date"] >= snap) or (b["bill_status"] == "due" and b["due_date"] < snap):
            out.append("STATUS_DATE_MISMATCH")
        if not (b["currency"] or "").strip():
            out.append("MISSING_CURRENCY")
    if c["last_activity_days"] >= _seg()["thresholds"]["dormant_days"] and c["activity_30d"] > 0:
        out.append("ACTIVITY_MISMATCH")
    if c["loyalty_tier"] != tier_for(c["loyalty_points"]):
        out.append("TIER_MISMATCH")
    paid_on_time = sum(1 for b in ctx["bills"] if b["bill_status"] == "paid" and b["last_payment_date"]
                       and b["last_payment_date"] <= b["due_date"])
    if c["plan_type"] == "postpaid" and (c["bills_issued_last_12"] != len(ctx["bills"])
                                         or c["on_time_payments_last_12"] != paid_on_time):
        out.append("PAYMENT_COUNT_MISMATCH")
    if cons.get("consent_updated_at") and cons["consent_updated_at"] > snap:
        out.append("FUTURE_CONSENT_DATE")
    enabled = {x["code"] for x in policy.conflicts()["checks"]}
    return sorted(set(out) & enabled)


# ---------------------------------------------------------------- step 2: segments ----------------------------
def _near(value: float, threshold: float, pct: float) -> bool:
    return threshold != 0 and abs(value - threshold) / abs(threshold) <= pct / 100


def classify(ctx: dict) -> dict:
    sp, c = _seg(), ctx["customer"]
    th, conf = sp["thresholds"], sp["confidence"]
    pct = conf["near_boundary_pct"]
    rules = {r["segment"]: r["id"] for r in policy.segmentation()["rules"]}
    texts = policy.segmentation()["reason_codes"]
    found = []

    def add(seg, reasons, near):
        found.append({"segment": seg, "rule_id": rules.get(seg), "rule_text": texts.get(seg), "reasons": reasons,
                      "near_boundary": near, "confidence": conf["near_boundary"] if near else conf["normal"]})

    t = ctx["target"]
    if t:
        lows = [s["overdue_range"][0] for s in policy.policy()["strategy"]["payment_stages"]]
        edges = [lo - 1 for lo in lows if lo and lo > 1]                    # 15, 30: where the stage flips
        if t["overdue_days"] > 0:
            reason, near = f"PAY_OVERDUE_{t['overdue_days']}D", any(_near(t["overdue_days"], e, pct) for e in edges)
        else:
            reason = "PAY_DUE_TODAY" if t["days_to_due"] == 0 else f"PAY_DUE_IN_{t['days_to_due']}D"
            near = False
        add("payment_reminder", [reason], near)
    if c["last_activity_days"] >= th["dormant_days"]:
        add("dormant", [f"DORMANT_{c['last_activity_days']}D"], _near(c["last_activity_days"], th["dormant_days"], pct))
    prev, cur = c["activity_prev_30d"], c["activity_30d"]
    if prev >= th["decline_min_prev"] and cur * 100 <= th["decline_pct"] * prev:
        drop = round((prev - cur) / prev * 100)
        add("declining_activity", [f"DECLINE_{drop}PCT"], _near(cur / prev, th["decline_pct"] / 100, pct))
    if c["tenure_months"] >= th["loyal_tenure_months"] and c["loyalty_tier"] in th["loyal_tiers"]:
        n, m = c["on_time_payments_last_12"], c["bills_issued_last_12"]
        near_t = _near(c["tenure_months"], th["loyal_tenure_months"], pct)
        if c["plan_type"] == "prepaid":
            add("loyalty_candidate", [f"LOYAL_T{c['tenure_months']}_{c['loyalty_tier'].upper()}_PREPAID"], near_t)
        elif m >= th["loyal_min_bills"] and n * 100 >= th["loyal_on_time_pct"] * m:
            add("loyalty_candidate", [f"LOYAL_T{c['tenure_months']}_{c['loyalty_tier'].upper()}_OT{n}OF{m}"],
                near_t or _near(n / m, th["loyal_on_time_pct"] / 100, pct))
    if not found:
        add("consistent", [f"STABLE_{cur}_VS_{prev}"], False)
    order = sp["order"]
    found.sort(key=lambda s: order.index(s["segment"]))
    return {"segments": found, "primary": found[0]["segment"], "confidence": min(s["confidence"] for s in found)}


# ---------------------------------------------------------------- step 4: strategy ----------------------------
def strategy(ctx: dict, seg: dict) -> dict:
    pol, primary = policy.policy(), seg["primary"]
    sc, tones = pol["strategy"], pol["tone"]
    stage, human = None, False
    if primary == "payment_reminder":
        od = ctx["target"]["overdue_days"]
        for i, s in enumerate(sc["payment_stages"]):
            lo, hi = s["overdue_range"]
            if (lo is None or od >= lo) and (hi is None or od <= hi):
                name, mtype, stage, human = s["stage"], s["message_type"], i, bool(s.get("human_review_required"))
                break
        tone_key = f"{mtype}_stage_{stage}" if stage else mtype
    else:
        name, mtype = sc["names"][primary], sc[primary]
        tone_key = f"{mtype}_{primary}" if f"{mtype}_{primary}" in tones else mtype
    out = {"name": name, "objective": name, "template": name, "message_type": mtype, "tone": tones[tone_key],
           "stage": stage or None, "offer": True, "human_review_required": human}
    if primary == "payment_reminder":
        t = ctx["target"]
        out.update(target_bill_id=t["bill_id"], overdue_days=t["overdue_days"], amount_outstanding=str(t["outstanding"]),
                   total_outstanding=str(ctx["total_outstanding"]), currency=(t["currency"] or "INR"))
    return out


def message_type_for(ctx: dict, seg: dict) -> str:
    return strategy(ctx, seg)["message_type"]


# ---------------------------------------------------------------- step 3: pre-check gate -----------------------
def precheck(ctx: dict, mtype: str) -> list[dict]:
    pc = policy.policy()["precheck"]
    cd = pc["rules"]["cooldown_or_duplicate"]
    c, cons = ctx["customer"], ctx["consent"]
    reminder = mtype in policy.reminder_types()
    hits: dict[str, str] = {}
    if c["account_status"] != "active":
        hits["account_inactive"] = f"account is {c['account_status']}"
    if ctx["conflicts"]:
        hits["data_conflict"] = ", ".join(ctx["conflicts"])
    if not cons.get("email_allowed"):
        hits["email_not_allowed"] = "customer does not allow email"
    need = "service_consent" if reminder else "marketing_consent"
    if not cons.get(need):
        hits["consent_missing"] = f"{need} is off for {mtype}"
    if not c["email_address"] or cons.get("email_status") != "valid":
        hits["email_undeliverable"] = f"email status: {cons.get('email_status') or 'none'}" if c["email_address"] else "no email address"
    if cons.get("open_complaint") or any(b["dispute_open"] for b in ctx["bills"]):
        hits["dispute_or_complaint_open"] = "open dispute or complaint"
    if reminder and any(b["unpaid"] and (b["payment_arrangement_active"] or b["hardship_flag"]) for b in ctx["bills"]):
        hits["payment_arrangement_or_hardship"] = "payment arrangement or hardship flag on an unpaid bill"
    last, same = ctx["days_since_contact"], ctx["days_since_type"].get(mtype)
    if last is not None and last < cd["cooldown_days"]:
        hits["cooldown_or_duplicate"] = f"last message {last} days ago, cooldown {cd['cooldown_days']} days"
    elif same is not None and same < cd["duplicate_days"]:
        hits["cooldown_or_duplicate"] = f"same message type sent {same} days ago, duplicate window {cd['duplicate_days']} days"
    return [{"code": k, "detail": hits[k]} for k in pc["order"] if k in hits]


# ---------------------------------------------------------------- step 5: offer validator ---------------------
def offer_gates(ctx: dict, offer: dict, segment: str) -> dict:
    """The five gates of offer_validator_rules.yaml, keyed by the names in offers.yaml selection.gates."""
    sel, snap, c = policy.offers()["selection"], ctx["snapshot"], ctx["customer"]
    channels = next(g for g in policy.offer_rules()["gates"] if g["id"] == "OV-03")["allowed"]
    sent = [h for h in ctx["history"] if h["offer_id"] == offer["offer_id"]
            and (snap - h["sent_at"]).days < sel["repeat_guard_days"]]
    g = {
        "group": segment in offer["eligible_segments"].split("|") and offer["plan_type"] in ("any", c["plan_type"]),
        "expiry": offer["valid_from"] <= snap <= offer["expiry_date"],
        "channel": (offer["channel"] or "").lower() in channels,
        "tenure": c["tenure_months"] >= offer["min_tenure_months"],
        "repeat_guard": not sent,
    }
    return {k: g[k] for k in sel["gates"]}


def select_offer(ctx: dict, strat: dict, seg: dict) -> tuple[dict | None, list[dict]]:
    if not strat["offer"]:
        return None, []
    ids = {g["name"].split("_")[0]: g["id"] for g in policy.offer_rules()["gates"]}
    chosen, decisions = None, []
    if ctx.get("offers") is not None:   # preloaded (same order as the query below)
        offers = [o for o in ctx["offers"] if o["message_type"] == strat["message_type"]]
    else:
        offers = db.q("SELECT * FROM offer_catalog WHERE message_type = ? ORDER BY priority, offer_id",
                      (strat["message_type"],))
    for o in offers:
        g = offer_gates(ctx, o, seg["primary"])
        failed = [k for k, ok in g.items() if not ok]
        decisions.append({"offer_id": o["offer_id"], "eligible": not failed, "reasons": failed,
                          "rule_ids": [ids.get(k.split("_")[0], k) for k in failed], "gates": g})
        if not failed and chosen is None:
            chosen = o
    return chosen, decisions


def offer_text(o: dict) -> str:
    fmt = policy.offers()["value_formats"].get(o["value_unit"], "{value} " + o["value_unit"])
    v = _d(o["value"])
    return fmt.format(value=f"{v:.2f}" if o["value_unit"].startswith("INR") else f"{v.normalize():f}")


# ---------------------------------------------------------------- facts: values of the locked placeholders -----
def locked() -> list[str]:
    return [p.strip("{}") for p in policy.policy()["message"]["locked_placeholders"]]


def facts(ctx: dict, strat: dict, offer: dict | None) -> dict:
    """Display strings that fill the locked placeholders, plus a few permitted facts for the review screen."""
    c = ctx["customer"]
    f = {"first_name": (c["first_name"] or "").strip() or "Customer", "plan_name": c["plan_id"] or c["plan_type"],
         "loyalty_points": str(c["loyalty_points"]), "plan_type": c["plan_type"],
         "tenure_months": str(c["tenure_months"]), "language": c["preferred_language"] or "en"}
    if strat["message_type"] in policy.reminder_types():
        t = ctx["target"]
        f.update(amount=money(t["outstanding"], strat["currency"]), due_date=fmt_date(t["due_date"]))
    if offer:
        f["offer_terms"] = (f"{offer['offer_name']}: {offer_text(offer)}. {offer['terms']} "
                            f"Valid until {fmt_date(offer['expiry_date'])}")
    return f


# ---------------------------------------------------------------- placeholders and step 7 validator -----------
PH = re.compile(r"\{(\w+)\}")


def fill(text: str, f: dict) -> str:
    return PH.sub(lambda m: str(f[m[1]]) if m[1] in f else m[0], text)


def unfill(text: str, f: dict) -> str:
    """Turn filled-in values back into their locked placeholders, longest first, so the validator sees exactly
    what the AI or the reviewer added. A value the reviewer typed differently stays as text and gets checked."""
    for k in sorted((k for k in locked() if f.get(k)), key=lambda k: -len(str(f[k]))):
        text = re.sub(r"(?<![\w{])" + re.escape(str(f[k])) + r"(?![\w}])", "{" + k + "}", text)
    return text


def _issue(chk: dict, detail: str) -> dict:
    return {"code": chk["name"].upper(), "rule_id": chk["id"], "detail": detail}


def validate(draft: dict, f: dict, strat: dict, offer: dict | None) -> list[dict]:
    """message_validator_rules.yaml on the final text: every check runs, every failure is returned."""
    subj_raw, body_raw = draft.get("subject", "") or "", draft.get("body", "") or ""
    if not subj_raw.strip() or not body_raw.strip():
        return [{"code": "EMPTY_DRAFT", "rule_id": "MV-01", "detail": "subject or body is empty"}]
    msg, out = policy.policy()["message"], []
    body, subj = unfill(body_raw.strip(), f), unfill(subj_raw.strip(), f)
    both = subj + "\n" + body

    def flags(c):
        return re.I if c.get("case_insensitive") or c.get("rule", {}).get("case_insensitive") else 0

    for chk in policy.validator()["checks"]:
        n, rule = chk["name"], chk.get("rule", {})
        if n == "length_check":
            sentences = len([s for s in re.split(r"[.!?]+", body) if s.strip()])
            if not rule["min_chars"] <= len(body_raw.strip()) <= rule["max_chars"]:
                out.append(_issue(chk, f"{len(body_raw.strip())} characters, allowed {rule['min_chars']}-{rule['max_chars']}"))
            if sentences > msg["max_sentences"]:
                out.append(_issue(chk, f"{sentences} sentences, at most {msg['max_sentences']}"))
        elif n == "greeting_check" and not re.search(rule["pattern"], body, flags(chk)):
            out.append(_issue(chk, "the message must open with a greeting"))
        elif n == "signoff_check" and not re.search(rule["pattern"], body, flags(chk)):
            out.append(_issue(chk, "the message must end with a professional sign-off"))
        elif n == "pii_check":
            hit = [k for k, p in chk["patterns"].items() if re.search(p, both)]
            if hit:   # the matched text itself is personal data: name the kind only
                out.append(_issue(chk, f"personal data in the message: {hit}"))
        elif n == "tone_check":
            bad = [w for w in chk["forbidden_words"].get(strat["tone"], [])
                   if re.search(r"\b" + re.escape(w) + r"\b", both, re.I)]
            if bad:
                out.append(_issue(chk, f"words that contradict the {strat['tone']} tone: {bad}"))
        elif n == "placeholder_integrity_check":
            out += _placeholders(chk, both, body, f, strat, offer)
    return out


def _placeholders(chk: dict, both: str, body: str, f: dict, strat: dict, offer: dict | None) -> list[dict]:
    out = []
    allowed = {k for k in locked() if k in f and (k != "offer_terms" or offer)}
    required = {"first_name"} | ({"amount", "due_date"} if strat["message_type"] in policy.reminder_types() else set()) \
        | ({"offer_terms"} if offer else set())
    unknown = sorted(set(PH.findall(both)) - allowed)
    if unknown:
        out.append({"code": "PLACEHOLDER_UNKNOWN", "rule_id": chk["id"],
                    "detail": f"placeholders not allowed or not resolved here: {unknown}"})
    for sub in chk["sub_checks"]:
        if sub["name"] == "placeholder_presence":
            missing = sorted(required - set(PH.findall(body)))
            if missing:
                out.append(_issue(sub, f"required placeholders missing: {missing}"))
        elif re.search(sub["pattern"], PH.sub("", both), re.I if sub.get("case_insensitive") else 0):
            out.append(_issue(sub, sub["description"]))
    return out


class Engage(Domain):
    """The domain slot: owns the tables the flow writes. Customer data tables live in Supabase already."""
    name = "engage"
    PARAMETERS: list[str] = []
    SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, as_of TEXT NOT NULL, segments TEXT, strategy TEXT,
  offer_id TEXT, facts TEXT, subject TEXT, body TEXT, checks TEXT, status TEXT NOT NULL, draft_source TEXT,
  template_version TEXT, model TEXT, trace_id TEXT, reviewer TEXT, review_note TEXT, edited TEXT DEFAULT 'N',
  created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  message_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, customer_id TEXT NOT NULL, to_email_masked TEXT,
  subject TEXT NOT NULL, body TEXT NOT NULL, queued_at TEXT NOT NULL, status TEXT NOT NULL);
-- tables created by the first version lack these columns (additive, no data touched)
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS draft_source TEXT;
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS to_email_masked TEXT;
"""
    TEMPLATE_VERSION = "ai-v2"
    SYSTEM_NAME = "Customer and Billing System"


DOMAIN = Engage()
