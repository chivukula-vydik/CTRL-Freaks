"""UC5 deterministic steps: 1 context, 2 segments, 3 pre-checks, 4 strategy, 5 offers, and the message validator (7).
No AI in this file. Numbers come from config/policy.yaml and config/offers.yaml; data from the five Supabase tables
(customers, billing, consent, contact_history, offer_catalog)."""
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from app import db, policy
from app.domain.base import Domain

# Only these columns are ever selected. The protected test fields (DOB, gender, address, phone, national id,
# credit score) are never read, so they cannot reach the classifier, the audit log or the AI.
CUSTOMER_COLS = ["customer_id", "first_name", "email_address", "snapshot_date", "tenure_months", "plan_type",
                 "plan_id", "plan_price", "account_status", "preferred_language", "activity_unit",
                 "last_activity_days", "activity_30d", "activity_prev_30d", "loyalty_points", "loyalty_tier",
                 "loyalty_points_expiry_date", "on_time_payments_last_12", "bills_issued_last_12"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _d(x) -> Decimal:
    return Decimal(str(x if x not in (None, "") else 0))


def money(v: Decimal, cur: str = "INR") -> str:
    return f"{cur or 'INR'} {v:.2f}"


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


# ---------------------------------------------------------------- step 1: context ----------------------------
def context(cid: str, as_of: date | None = None) -> dict | None:
    c = db.q1(f"SELECT {', '.join(CUSTOMER_COLS)} FROM customers WHERE customer_id = ?", (cid,))
    if not c:
        return None
    snap = as_of or c["snapshot_date"]
    cons = db.q1("SELECT * FROM consent WHERE customer_id = ?", (cid,)) or {}
    bills = db.q("SELECT * FROM billing WHERE customer_id = ? ORDER BY due_date, bill_id", (cid,))
    hist = db.q("SELECT message_id, sent_at, channel, message_type, segment, offer_id, bill_id "
                "FROM contact_history WHERE customer_id = ? ORDER BY sent_at DESC", (cid,))
    pol = policy.policy()
    within = pol["segments"]["payment_reminder"]["due_within_days"]
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
        "days_since_type": {},
    }
    for h in hist:   # newest first
        ctx["days_since_type"].setdefault(h["message_type"], (snap - h["sent_at"]).days)
    ctx["conflicts"] = _conflicts(ctx)
    return ctx


def tier_for(points: int) -> str:
    t = policy.policy()["tiers"]
    return "Platinum" if points >= t["platinum_points_gte"] else "Gold" if points >= t["gold_points_gte"] else "Silver"


def _conflicts(ctx: dict) -> list[str]:
    c, cons, snap, out = ctx["customer"], ctx["consent"], ctx["snapshot"], []
    for b in ctx["bills"]:
        if b["unpaid"] and _d(b["amount_paid"]) >= _d(b["amount_due"]):
            out.append("UNPAID_BUT_FULLY_PAID")
        if (b["bill_status"] == "overdue" and b["days_to_due"] > 0) or (b["bill_status"] == "due" and b["days_to_due"] < 0):
            out.append("STATUS_DATE_MISMATCH")
        if not (b["currency"] or "").strip():
            out.append("MISSING_CURRENCY")
        if b["bill_status"] == "paid" and _d(b["amount_paid"]) < _d(b["amount_due"]):
            out.append("PAID_AMOUNT_MISMATCH")
    if c["last_activity_days"] >= policy.policy()["segments"]["dormant"]["last_activity_days_gte"] and c["activity_30d"] > 0:
        out.append("ACTIVITY_MISMATCH")
    if c["loyalty_tier"] != tier_for(c["loyalty_points"]):
        out.append("TIER_MISMATCH")
    paid_on_time = sum(1 for b in ctx["bills"] if b["bill_status"] == "paid" and b["last_payment_date"]
                       and b["last_payment_date"] <= b["due_date"])
    if c["plan_type"] == "postpaid" and c["on_time_payments_last_12"] != paid_on_time:
        out.append("PAYMENT_COUNT_MISMATCH")
    if cons.get("consent_updated_at") and cons["consent_updated_at"] > snap:
        out.append("FUTURE_CONSENT_DATE")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- step 2: segments ----------------------------
def _near(value: float, threshold: float, pct: float) -> bool:
    return threshold != 0 and abs(value - threshold) / abs(threshold) <= pct / 100


def classify(ctx: dict) -> dict:
    pol, c, snap = policy.policy(), ctx["customer"], ctx["snapshot"]
    sp, pct, conf = pol["segments"], pol["segments"]["near_boundary_pct"], pol["segments"]["confidence"]
    found = []

    def add(seg, reasons, near):
        found.append({"segment": seg, "reasons": reasons, "near_boundary": near,
                      "confidence": conf["near_boundary"] if near else conf["normal"]})

    t = ctx["target"]
    if t:
        stages = [s["overdue_days"] for s in pol["strategies"].values() if s.get("overdue_days")]
        edges = [lo - 1 for lo, _ in stages if lo > 1]                       # 15, 30: where the stage flips
        if t["overdue_days"] > 0:
            reason, near = f"PAY_OVERDUE_{t['overdue_days']}D", any(_near(t["overdue_days"], e, pct) for e in edges)
        else:
            reason = "PAY_DUE_TODAY" if t["days_to_due"] == 0 else f"PAY_DUE_IN_{t['days_to_due']}D"
            near = False
        add("payment_reminder", [reason], near)
    d = sp["dormant"]["last_activity_days_gte"]
    if c["last_activity_days"] >= d:
        add("dormant", [f"DORMANT_{c['last_activity_days']}D"], _near(c["last_activity_days"], d, pct))
    prev, cur, ratio = c["activity_prev_30d"], c["activity_30d"], sp["declining_activity"]["ratio_lte"]
    if prev >= sp["declining_activity"]["prev_30d_gte"] and cur <= ratio * prev:
        drop = round((prev - cur) / prev * 100)
        add("declining_activity", [f"DECLINE_{drop}PCT"], _near(cur / prev, ratio, pct))
    lo = sp["loyalty_candidate"]
    if c["tenure_months"] >= lo["tenure_months_gte"] and c["loyalty_tier"] in lo["tiers"]:
        n, m = c["on_time_payments_last_12"], c["bills_issued_last_12"]
        if c["plan_type"] == "prepaid":
            add("loyalty_candidate", [f"LOYAL_T{c['tenure_months']}_{c['loyalty_tier'].upper()}_PREPAID"],
                _near(c["tenure_months"], lo["tenure_months_gte"], pct))
        elif m >= lo["min_bills_issued_postpaid"] and n / m >= lo["on_time_ratio_gte"]:
            add("loyalty_candidate", [f"LOYAL_T{c['tenure_months']}_{c['loyalty_tier'].upper()}_OT{n}OF{m}"],
                _near(c["tenure_months"], lo["tenure_months_gte"], pct) or _near(n / m, lo["on_time_ratio_gte"], pct))
    if not found:
        add("consistent", [f"STABLE_{cur}_VS_{prev}"], False)
    order = sp["priority"]
    found.sort(key=lambda s: order.index(s["segment"]))
    return {"segments": found, "primary": found[0]["segment"], "confidence": min(s["confidence"] for s in found)}


# ---------------------------------------------------------------- step 4: strategy ----------------------------
def strategy(ctx: dict, seg: dict) -> dict:
    strategies, primary = policy.policy()["strategies"], seg["primary"]
    name = None
    if primary == "payment_reminder":
        od = ctx["target"]["overdue_days"]
        for n, s in strategies.items():
            if s["segment"] != primary:
                continue
            if od <= 0 and s["stage"] == 0:
                name = n
            elif od > 0 and s.get("overdue_days") and od >= s["overdue_days"][0] and (
                    s["overdue_days"][1] is None or od <= s["overdue_days"][1]):
                name = n
    else:
        name = next(n for n, s in strategies.items() if s["segment"] == primary)
    s = strategies[name]
    out = {"name": name, "objective": name, "template": name, "message_type": s["message_type"], "tone": s["tone"],
           "stage": s.get("stage") or None, "offer": bool(s.get("offer")),
           "human_review_required": bool(s.get("human_review_required"))}
    if primary == "payment_reminder":
        t = ctx["target"]
        out.update(target_bill_id=t["bill_id"], overdue_days=t["overdue_days"], amount_outstanding=str(t["outstanding"]),
                   total_outstanding=str(ctx["total_outstanding"]), currency=(t["currency"] or "INR"))
    return out


def message_type_for(ctx: dict, seg: dict) -> str:
    return strategy(ctx, seg)["message_type"]


# ---------------------------------------------------------------- step 3: pre-check gate -----------------------
def precheck(ctx: dict, mtype: str) -> list[dict]:
    pol = policy.policy()["prechecks"]
    c, cons, hist = ctx["customer"], ctx["consent"], ctx["history"]
    reminder = mtype in policy.policy()["reminder_message_types"]
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
    if not c["email_address"] or cons.get("email_status") in pol["undeliverable_email_status"]:
        hits["email_undeliverable"] = f"email status: {cons.get('email_status') or 'none'}" if c["email_address"] else "no email address"
    if cons.get("open_complaint") or any(b["dispute_open"] for b in ctx["bills"]):
        hits["dispute_or_complaint_open"] = "open dispute or complaint"
    if reminder and any(b["unpaid"] and (b["payment_arrangement_active"] or b["hardship_flag"]) for b in ctx["bills"]):
        hits["payment_arrangement_or_hardship"] = "payment arrangement or hardship flag on an unpaid bill"
    last, same = ctx["days_since_contact"], ctx["days_since_type"].get(mtype)
    if last is not None and last < pol["cooldown_days"]:
        hits["cooldown_or_duplicate"] = f"last message {last} days ago, cooldown {pol['cooldown_days']} days"
    elif same is not None and same < pol["duplicate_days"]:
        hits["cooldown_or_duplicate"] = f"same message type sent {same} days ago, duplicate window {pol['duplicate_days']} days"
    return [{"code": k, "detail": hits[k]} for k in pol["order"] if k in hits]


# ---------------------------------------------------------------- step 5: offer validator ---------------------
def offer_gates(ctx: dict, offer: dict, segment: str) -> dict:
    og, snap, c = policy.offers(), ctx["snapshot"], ctx["customer"]
    sent = [h for h in ctx["history"] if h["offer_id"] == offer["offer_id"]
            and (snap - h["sent_at"]).days < og["repeat_guard_days"]]
    return {
        "group": (segment in offer["eligible_segments"].split("|")
                  and offer["plan_type"] in (og["plan_any"], c["plan_type"])),
        "expiry": offer["valid_from"] <= snap <= offer["expiry_date"],
        "channel": (offer["channel"] or "").lower() in og["channels_allowed"],
        "tenure": c["tenure_months"] >= offer["min_tenure_months"],
        "repeat": not sent,
    }


def select_offer(ctx: dict, strat: dict, seg: dict) -> tuple[dict | None, list[dict]]:
    if not strat["offer"]:
        return None, []
    chosen, decisions = None, []
    for o in db.q("SELECT * FROM offer_catalog WHERE message_type = ? ORDER BY priority, offer_id", (strat["message_type"],)):
        g = offer_gates(ctx, o, seg["primary"])
        failed = [k for k, ok in g.items() if not ok]
        decisions.append({"offer_id": o["offer_id"], "eligible": not failed, "reasons": failed, "gates": g})
        if not failed and chosen is None:
            chosen = o
    return chosen, decisions


def offer_text(o: dict) -> str:
    fmt = policy.offers()["value_formats"].get(o["value_unit"], "{value} " + o["value_unit"])
    v = _d(o["value"])
    return fmt.format(value=f"{v:.2f}" if o["value_unit"].startswith("INR") else f"{v:g}")


# ---------------------------------------------------------------- facts the writer may use --------------------
def facts(ctx: dict, strat: dict, offer: dict | None) -> dict:
    """Display strings that fill the locked placeholders. Permitted facts only: no protected field is here."""
    c, pol = ctx["customer"], policy.policy()
    f = {"first_name": (c["first_name"] or "").strip() or "Customer", "plan_type": c["plan_type"],
         "tenure_months": str(c["tenure_months"]), "language": c["preferred_language"] or "en",
         "support_phone": pol["contacts"]["support_phone"], "dispute_contact": pol["contacts"]["dispute_email"]}
    if strat["name"].startswith(("courteous", "overdue")):
        t, cur = ctx["target"], strat["currency"]
        f.update(bill_id=t["bill_id"], amount=money(t["outstanding"], cur), due_date=fmt_date(t["due_date"]),
                 overdue_days=str(t["overdue_days"]))
        if len(ctx["reminder_bills"]) > 1:
            f["total_amount"] = money(ctx["total_outstanding"], cur)
        if strat["stage"] == 3:
            f["contact_days"] = str(pol["prechecks"]["final_notice_contact_days"])
    if offer:
        f.update(offer_name=offer["offer_name"], offer_value=offer_text(offer), offer_terms=offer["terms"],
                 offer_expiry=fmt_date(offer["expiry_date"]))
    return f


# ---------------------------------------------------------------- placeholders and step 7 validator -----------
PH = re.compile(r"\{(\w+)\}")
NUM = re.compile(r"\d+(?:[.,]\d+)*")
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b"),
     lambda m: (int(m[3]), MONTHS.index(m[2][:3].lower()) + 1 if m[2][:3].lower() in MONTHS else 0, int(m[1]))),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"),
     lambda m: (int(m[3]), MONTHS.index(m[1][:3].lower()) + 1 if m[1][:3].lower() in MONTHS else 0, int(m[2]))),
]


def _ascii_digits(s: str) -> str:
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in s)


def _norm(n: str) -> str:
    n = n.replace(",", "")
    try:
        return str(Decimal(n).normalize())
    except Exception:
        return n


def numbers(text: str) -> set[str]:
    return {_norm(n) for n in NUM.findall(_ascii_digits(text or ""))}


def dates(text: str) -> set[tuple]:
    out, t = set(), _ascii_digits(text or "")
    for pat, fn in DATE_PATTERNS:
        for m in pat.finditer(t):
            out.add(fn(m))
    return out


def allowed_placeholders(strat: dict, offer: dict | None) -> tuple[set, set]:
    spec, ai = policy.ai()["strategies"][strat["name"]], policy.ai()
    req = set(spec["required"]) | (set(ai["offer_placeholders"]) if offer else set())
    return req, req | set(spec.get("optional", []))


def check_placeholders(subject: str, body: str, strat: dict, offer: dict | None) -> list[dict]:
    """Placeholder integrity for AI output, before anything is filled in."""
    req, allowed = allowed_placeholders(strat, offer)
    used_body, used_all = set(PH.findall(body)), set(PH.findall(subject)) | set(PH.findall(body))
    out = []
    missing = sorted(req - used_body)
    unknown = sorted(used_all - allowed)
    if missing:
        out.append({"code": "PLACEHOLDER_MISSING", "detail": f"required placeholders not used: {missing}"})
    if unknown:
        out.append({"code": "PLACEHOLDER_UNKNOWN", "detail": f"placeholders not allowed here: {unknown}"})
    return out


def fill(text: str, f: dict) -> str:
    return PH.sub(lambda m: f.get(m[1], m[0]), text)


def validate(draft: dict, f: dict, strat: dict, offer: dict | None, as_of: date) -> list[dict]:
    """Six proof-read checks on the final text (placeholders already filled)."""
    pol = policy.policy()
    text = f"{draft.get('subject', '')}\n{draft.get('body', '')}"
    out = []
    if not draft.get("subject", "").strip() or not draft.get("body", "").strip():
        return [{"code": "EMPTY_DRAFT", "detail": "subject or body is empty"}]
    if PH.search(text):
        out.append({"code": "PLACEHOLDER_LEFT", "detail": f"unfilled placeholders: {sorted(set(PH.findall(text)))}"})
    # 1 numbers: every number in the text must come from the verified facts
    allowed_n = set().union(*(numbers(str(v)) for k, v in f.items() if k not in ("language",)))
    extra = numbers(text) - allowed_n
    if extra:
        out.append({"code": "UNSUPPORTED_NUMBER", "detail": f"numbers not in verified facts: {sorted(extra)}"})
    # 2 dates
    allowed_d = set().union(*(dates(str(v)) for v in f.values()))
    bad_d = dates(text) - allowed_d
    if bad_d:
        out.append({"code": "UNSUPPORTED_DATE", "detail": f"dates not in verified facts: {sorted(bad_d)}"})
    # 3 offer: only the chosen offer, quoted with its terms; no offer talk when none was chosen
    ids = set(re.findall(r"\bOFR-[A-Z0-9-]+\b", text))
    if ids - ({offer["offer_id"]} if offer else set()):
        out.append({"code": "UNKNOWN_OFFER", "detail": f"offer ids not approved for this customer: {sorted(ids)}"})
    if offer:
        if offer["terms"].lower() not in text.lower():
            out.append({"code": "MISSING_OFFER_TERMS", "detail": "offer terms must be quoted exactly"})
        if f["offer_value"].lower() not in text.lower():
            out.append({"code": "MISSING_OFFER_VALUE", "detail": "offer value must be stated as given"})
        if offer["expiry_date"] < as_of:
            out.append({"code": "OFFER_EXPIRED", "detail": offer["offer_id"]})
    elif re.search(r"\b(offer|discount|cashback|bonus|reward)\b", text, re.I):
        out.append({"code": "UNAUTHORIZED_OFFER", "detail": "no offer is approved for this customer"})
    # 4 prohibited language
    for phrase in pol["blocked_phrases"]:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text, re.I):
            out.append({"code": "BLOCKED_PHRASE", "detail": phrase})
    # 5 personal data leak: contact data other than our own support lines
    emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)) - {pol["contacts"]["dispute_email"]}
    phones = re.findall(r"(?<!\w)(?:\+91[-\s]?)?[6-9]\d{9}(?!\w)", text)
    if emails or phones or re.search(r"\b(?:\d[ -]?){13,19}\b", text):
        out.append({"code": "PII_LEAK", "detail": "personal contact or card data in the message"})
    # 6 required content
    if strat["message_type"] in pol["reminder_message_types"]:
        if pol["contacts"]["dispute_email"] not in text or pol["contacts"]["support_phone"] not in text:
            out.append({"code": "MISSING_DISPUTE_PATH", "detail": "reminders must include the dispute contact and support phone"})
    if f["first_name"] not in text:
        out.append({"code": "MISSING_GREETING_NAME", "detail": "the customer's name must appear in the greeting"})
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
"""
    TEMPLATE_VERSION = "ai-v2"
    SYSTEM_NAME = "Customer and Billing System"


DOMAIN = Engage()
