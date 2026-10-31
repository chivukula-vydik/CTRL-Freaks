"""Customer Loyalty and Engagement domain (UC5). Profile, segments, strategy, offer eligibility, reminder stage
and draft checks are plain code with thresholds from the rule registry. The LLM only rewrites an approved
template from verified facts; app/engage.py runs the flow, stores drafts and handles review and mock send."""
import json
import re
from datetime import date

from app import db
from app.domain.base import Domain
from app.rules import get_rule

TEMPLATE_VERSION = "tpl-v1"
SUPPORT = {"support_phone": "1800-200-3000", "dispute_contact": "billing-disputes@example.com"}
# fields the classifier may read; protected or proxy attributes (age, gender, religion, location...) never enter
ALLOWED_FIELDS = ["plan", "plan_status", "tenure_months", "last_active_on", "activity", "invoices",
                  "consent_email", "do_not_contact", "communications"]

SEGMENT_PRIORITY = ["payment_reminder", "dormant", "declining", "loyalty_candidate", "consistent"]
STRATEGIES = {
    "payment_reminder:1": {"objective": "courteous_reminder", "tone": "courteous", "template": "REM1"},
    "payment_reminder:2": {"objective": "firm_reminder", "tone": "firm and respectful", "template": "REM2"},
    "payment_reminder:3": {"objective": "final_notice", "tone": "formal and respectful", "template": "REM3"},
    "dormant": {"objective": "win_back", "tone": "warm", "template": "WINBACK", "offer": True},
    "declining": {"objective": "re_engage", "tone": "warm", "template": "REENGAGE", "offer": True},
    "loyalty_candidate": {"objective": "reward", "tone": "grateful", "template": "REWARD", "offer": True},
    "consistent": {"objective": "appreciation", "tone": "grateful", "template": "APPRECIATION"},
}
OFFER_BLOCK = ("As a thank-you, we would like to offer you {offer_name} (offer {offer_id}): {offer_value}. "
               "{offer_terms} Valid until {offer_expiry}.\n\n")
TEMPLATES = {
    "APPRECIATION": ("Thank you for being with us, {first_name}",
                     "Hi {first_name},\n\nThank you for being with us for {tenure_months} months on the {plan} plan. "
                     "We truly appreciate your loyalty.\n\n{offer_block}If you ever need help, reply to this email or "
                     "call {support_phone}.\n\nWarm regards,\nCustomer Care"),
    "REWARD": ("A thank-you reward for you, {first_name}",
               "Hi {first_name},\n\nYou have been with us for {tenure_months} months and your payments have always "
               "been on time. Thank you.\n\n{offer_block}If you have any questions, call {support_phone}.\n\n"
               "Warm regards,\nCustomer Care"),
    "REENGAGE": ("Something for you on your {plan} plan, {first_name}",
                 "Hi {first_name},\n\nWe noticed you have been using your {plan} plan less recently, and we would "
                 "love to help you get more from it.\n\n{offer_block}If something is not working for you, call "
                 "{support_phone} and we will help.\n\nWarm regards,\nCustomer Care"),
    "WINBACK": ("We miss you, {first_name}",
                "Hi {first_name},\n\nWe have not seen you on your {plan} plan for a while and we would love to "
                "have you back.\n\n{offer_block}Call {support_phone} if we can help with anything.\n\n"
                "Warm regards,\nCustomer Care"),
    "REM1": ("Friendly reminder: invoice {invoice_id}",
             "Hi {first_name},\n\n{gratitude_line}This is a friendly reminder that Rs {amount_due} for invoice "
             "{invoice_id} was due on {due_date}. If you have already paid, please ignore this note.\n\n"
             "If you believe this bill is incorrect, you can raise a dispute at {dispute_contact} or call "
             "{support_phone}.\n\nRegards,\nCustomer Care"),
    "REM2": ("Payment overdue: invoice {invoice_id}",
             "Hi {first_name},\n\nOur records show that Rs {amount_due} for invoice {invoice_id}, due on {due_date}, "
             "is now {days_overdue} days overdue. Please arrange the payment at your earliest convenience.\n\n"
             "If you believe this bill is incorrect, you can raise a dispute at {dispute_contact} or call "
             "{support_phone}.\n\nRegards,\nCustomer Care"),
    "REM3": ("Final reminder: invoice {invoice_id}",
             "Dear {first_name},\n\nRs {amount_due} for invoice {invoice_id}, due on {due_date}, is now "
             "{days_overdue} days overdue. As per our Reminder Policy, please contact us within "
             "{final_notice_contact_days} days to arrange payment or discuss a payment plan.\n\n"
             "If you believe this bill is incorrect, you can raise a dispute at {dispute_contact} or call "
             "{support_phone}.\n\nRegards,\nCustomer Care"),
}
BLOCKED_PHRASES = [r"legal action", r"\bcourt\b", r"\bpolice\b", r"blacklist", r"credit score", r"final warning",
                   r"guarantee", r"risk[- ]free", r"act now", r"last chance", r"no choice", r"\bimmediately\b",
                   r"penalt", r"\bthreat"]
PRE_BLOCKS = {"NO_CONSENT", "DO_NOT_CONTACT", "CONTRADICTORY_DATA", "DISPUTED_INVOICE", "NO_SEGMENT",
              "MISSING_EVIDENCE", "RECENT_CONTACT", "PENDING_DRAFT_EXISTS"}


def _d(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def _months_before(as_of: date, n: int) -> list[str]:
    y, m, out = as_of.year, as_of.month, []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return out[::-1]   # oldest first


def _nums(text: str) -> set[str]:
    return {f"{float(n):g}" for n in re.findall(r"\d+(?:\.\d+)?", text or "")}


class Engage(Domain):
    name = "engage"
    TEMPLATE_VERSION = TEMPLATE_VERSION
    SYSTEM_NAME = "Customer and Billing System"

    SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  customer_id TEXT PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT, email TEXT,
  plan TEXT NOT NULL, plan_status TEXT NOT NULL CHECK (plan_status IN ('ACTIVE','INACTIVE')),
  tenure_months INTEGER NOT NULL CHECK (tenure_months >= 0), last_active_on TEXT,
  consent_email TEXT NOT NULL DEFAULT 'N' CHECK (consent_email IN ('Y','N')),
  do_not_contact TEXT NOT NULL DEFAULT 'N' CHECK (do_not_contact IN ('Y','N')));
CREATE TABLE IF NOT EXISTS activity (
  customer_id TEXT NOT NULL REFERENCES customers(customer_id), month TEXT NOT NULL,
  usage_units REAL NOT NULL CHECK (usage_units >= 0), PRIMARY KEY (customer_id, month));
CREATE TABLE IF NOT EXISTS invoices (
  invoice_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  amount REAL NOT NULL CHECK (amount > 0), issued_on TEXT, due_date TEXT NOT NULL, paid_on TEXT,
  status TEXT NOT NULL CHECK (status IN ('PAID','UNPAID','DISPUTED')));
CREATE TABLE IF NOT EXISTS offers (
  offer_id TEXT PRIMARY KEY, name TEXT NOT NULL, value_text TEXT NOT NULL, terms TEXT NOT NULL,
  eligible_segments TEXT NOT NULL, channel TEXT NOT NULL, min_tenure_months INTEGER NOT NULL DEFAULT 0,
  valid_from TEXT NOT NULL, expiry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS communications (
  comm_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  type TEXT NOT NULL, channel TEXT NOT NULL, sent_on TEXT NOT NULL, draft_id TEXT);
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, as_of TEXT NOT NULL, segments TEXT, strategy TEXT,
  offer_id TEXT, facts TEXT, subject TEXT, body TEXT, checks TEXT, status TEXT NOT NULL,
  template_version TEXT, model TEXT, trace_id TEXT, reviewer TEXT, review_note TEXT, edited TEXT DEFAULT 'N',
  created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  message_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, customer_id TEXT NOT NULL, to_email TEXT,
  subject TEXT NOT NULL, body TEXT NOT NULL, queued_at TEXT NOT NULL, status TEXT NOT NULL);
"""
    VALIDATIONS = [
        ("UNPAID invoice with paid_on (C1008 is a deliberate test case)",
         "SELECT invoice_id FROM invoices WHERE status = 'UNPAID' AND paid_on IS NOT NULL"),
        ("PAID invoice without paid_on", "SELECT invoice_id FROM invoices WHERE status = 'PAID' AND paid_on IS NULL"),
        ("offer expires before it starts", "SELECT offer_id FROM offers WHERE expiry < valid_from"),
    ]

    SUBJECT_ID = re.compile(r"\bC\d{4}\b", re.I)
    SUBJECT_TABLE, SUBJECT_KEY = "customers", "customer_id"
    PARAMETERS = ["dormant_days", "decline_pct", "loyalty_min_tenure_months", "loyalty_on_time_ratio",
                  "consistent_on_time_ratio", "reminder_stage1_max_days", "reminder_stage2_max_days",
                  "final_notice_contact_days", "contact_cooldown_days"]
    PARAM_QUERIES = {
        "contact_cooldown_days": [r"cooldown", r"how (often|frequently).*(contact|email)", r"contact frequency"],
        "dormant_days": [r"dormant", r"inactive.*days"],
        "reminder_stage1_max_days": [r"(first|stage 1|courteous) reminder"],
        "reminder_stage2_max_days": [r"(second|stage 2|firm) reminder"],
    }
    PARAM_UNIT = {"contact_cooldown_days": "{v} days", "dormant_days": "{v} days",
                  "reminder_stage1_max_days": "up to {v} days overdue", "reminder_stage2_max_days": "up to {v} days overdue"}

    # ---------------- FR-01 profile ----------------
    def profile(self, cid: str, as_of: date) -> dict | None:
        c = db.q1("SELECT * FROM customers WHERE customer_id = ?", (cid,))
        if not c:
            return None
        months = _months_before(as_of, 6)
        act = {r["month"]: float(r["usage_units"]) for r in
               db.q("SELECT month, usage_units FROM activity WHERE customer_id = ?", (cid,))}
        prior = [act[m] for m in months[:3] if m in act]
        recent = [act[m] for m in months[3:] if m in act]
        p_avg = sum(prior) / len(prior) if prior else None
        r_avg = sum(recent) / len(recent) if recent else None
        drop = round((p_avg - r_avg) / p_avg * 100, 1) if p_avg and r_avg is not None else None
        inv = db.q("SELECT * FROM invoices WHERE customer_id = ? ORDER BY due_date", (cid,))
        due = [i for i in inv if _d(i["due_date"]) < as_of and (as_of - _d(i["due_date"])).days <= 365
               and i["status"] != "DISPUTED"]
        on_time = [i for i in due if i["paid_on"] and _d(i["paid_on"]) <= _d(i["due_date"])]
        overdue = [{"invoice_id": i["invoice_id"], "amount": float(i["amount"]), "due_date": i["due_date"],
                    "days_overdue": (as_of - _d(i["due_date"])).days}
                   for i in inv if i["status"] == "UNPAID" and not i["paid_on"] and _d(i["due_date"]) < as_of]
        disputed = [i["invoice_id"] for i in inv if i["status"] == "DISPUTED"]
        contradictions = [f"{i['invoice_id']}: status UNPAID but paid_on {i['paid_on']}" for i in inv
                          if i["status"] == "UNPAID" and i["paid_on"]]
        contradictions += [f"{i['invoice_id']}: status PAID but no paid_on" for i in inv
                           if i["status"] == "PAID" and not i["paid_on"]]
        if c["plan_status"] == "INACTIVE" and recent and recent[-1] > 0:
            contradictions.append("plan INACTIVE but usage recorded last month")
        comms = db.q("SELECT type, sent_on FROM communications WHERE customer_id = ? ORDER BY sent_on DESC", (cid,))
        last_active = _d(c["last_active_on"])
        return {
            "customer_id": cid, "first_name": c["first_name"], "email": c["email"], "plan": c["plan"],
            "plan_status": c["plan_status"], "tenure_months": int(c["tenure_months"]),
            "consent_email": c["consent_email"], "do_not_contact": c["do_not_contact"],
            "activity_months": months, "activity": {m: act.get(m) for m in months},
            "activity_months_present": len(prior) + len(recent),
            "usage_prior_avg": p_avg, "usage_recent_avg": r_avg, "usage_drop_pct": drop,
            "last_active_on": c["last_active_on"], "days_inactive": (as_of - last_active).days if last_active else None,
            "invoices_due_12m": len(due), "on_time_12m": len(on_time),
            "on_time_ratio": round(len(on_time) / len(due), 2) if due else None,
            "overdue": overdue, "disputed": disputed, "contradictions": contradictions,
            "last_contact_on": comms[0]["sent_on"] if comms else None,
            "last_contact_type": comms[0]["type"] if comms else None,
        }

    def _r(self, p: str, as_of: date, trace: dict) -> float:
        return float(get_rule(p, as_of, trace=trace))

    # ---------------- FR-02 transparent classification ----------------
    def classify(self, p: dict, as_of: date, trace: dict) -> dict:
        segs, near = [], []

        def conf(*close: bool) -> float:
            c = 0.95 - (0.25 if p["activity_months_present"] < 6 else 0) - 0.15 * sum(close)
            return round(max(c, 0.3), 2)

        def close_to(v, t):   # within 10% of the threshold: less certain
            return v is not None and t and abs(v - t) / t <= 0.10

        if p["overdue"]:
            days = max(o["days_overdue"] for o in p["overdue"])
            total = round(sum(o["amount"] for o in p["overdue"]), 2)
            segs.append({"segment": "payment_reminder", "confidence": 0.95,
                         "reasons": [f"OVERDUE_{days}D", f"AMOUNT_DUE_{total:g}", f"INVOICES_{len(p['overdue'])}"]})
        dormant_days = self._r("dormant_days", as_of, trace)
        decline = self._r("decline_pct", as_of, trace)
        di, drop = p["days_inactive"], p["usage_drop_pct"]
        if p["plan_status"] != "ACTIVE" or (di is not None and di >= dormant_days):
            segs.append({"segment": "dormant", "confidence": conf(close_to(di, dormant_days)),
                         "reasons": [f"INACTIVE_{di}D" if di is not None else "NO_ACTIVITY_DATE",
                                     f"PLAN_{p['plan_status']}"]})
        elif drop is not None and drop >= decline:
            segs.append({"segment": "declining", "confidence": conf(close_to(drop, decline)),
                         "reasons": [f"ACTIVITY_DROP_{drop:g}PCT",
                                     f"USAGE_{p['usage_prior_avg']:g}_TO_{p['usage_recent_avg']:g}"]})
        tenure, ratio = p["tenure_months"], p["on_time_ratio"]
        lt, lr = self._r("loyalty_min_tenure_months", as_of, trace), self._r("loyalty_on_time_ratio", as_of, trace)
        cr = self._r("consistent_on_time_ratio", as_of, trace)
        engaged = not any(s["segment"] in ("dormant", "declining") for s in segs)
        if engaged and not p["overdue"] and ratio is not None:
            if tenure >= lt and ratio >= lr:
                segs.append({"segment": "loyalty_candidate", "confidence": conf(close_to(tenure, lt), close_to(ratio, lr)),
                             "reasons": [f"TENURE_{tenure}M", f"ON_TIME_{round(ratio * 100):g}PCT"]})
            elif ratio >= cr:
                segs.append({"segment": "consistent", "confidence": conf(close_to(ratio, cr)),
                             "reasons": [f"ON_TIME_{round(ratio * 100):g}PCT", f"TENURE_{tenure}M"]})
        segs.sort(key=lambda s: SEGMENT_PRIORITY.index(s["segment"]))
        loyal_history = tenure >= lt
        return {"segments": segs, "primary": segs[0]["segment"] if segs else None,
                "confidence": min((s["confidence"] for s in segs), default=0.0), "loyal_history": loyal_history,
                "fields_used": ALLOWED_FIELDS}

    # ---------------- blocks that stop generation ----------------
    def precheck(self, p: dict, seg: dict, as_of: date, trace: dict) -> list[dict]:
        out = []
        if p["consent_email"] != "Y":
            out.append({"code": "NO_CONSENT", "detail": "customer has not consented to email"})
        if p["do_not_contact"] == "Y":
            out.append({"code": "DO_NOT_CONTACT", "detail": "do-not-contact flag set"})
        if not p["email"]:
            out.append({"code": "MISSING_EVIDENCE", "detail": "no email address on file"})
        if p["contradictions"]:
            out.append({"code": "CONTRADICTORY_DATA", "detail": "; ".join(p["contradictions"])})
        if p["disputed"]:
            out.append({"code": "DISPUTED_INVOICE", "detail": f"disputed: {', '.join(p['disputed'])}; escalate to billing"})
        if not seg["segments"]:
            out.append({"code": "NO_SEGMENT", "detail": "no segment rule matched; send to human review"})
        cool = self._r("contact_cooldown_days", as_of, trace)
        if p["last_contact_on"] and (as_of - _d(p["last_contact_on"])).days < cool:
            out.append({"code": "RECENT_CONTACT", "detail": f"contacted on {p['last_contact_on']} "
                                                            f"({p['last_contact_type']}); cooldown {cool:g} days"})
        if db.q1("SELECT draft_id FROM drafts WHERE customer_id = ? AND status IN ('pending_review','approved')",
                 (p["customer_id"],)):
            out.append({"code": "PENDING_DRAFT_EXISTS", "detail": "a draft for this customer is already in review"})
        return out

    # ---------------- FR-03 strategy, FR-06 reminder stage ----------------
    def strategy(self, p: dict, seg: dict, as_of: date, trace: dict) -> dict | None:
        prim = seg["primary"]
        if not prim:
            return None
        if prim == "payment_reminder":
            days = max(o["days_overdue"] for o in p["overdue"])
            s1, s2 = self._r("reminder_stage1_max_days", as_of, trace), self._r("reminder_stage2_max_days", as_of, trace)
            stage = 1 if days <= s1 else 2 if days <= s2 else 3
            st = dict(STRATEGIES[f"payment_reminder:{stage}"], segment=prim, stage=stage)
            st["gratitude"] = stage == 1 and seg["loyal_history"]
            return st
        return dict(STRATEGIES[prim], segment=prim)

    # ---------------- FR-05 offer controls ----------------
    def select_offer(self, p: dict, st: dict | None, as_of: date) -> tuple[dict | None, list[dict]]:
        if not st or not st.get("offer"):
            return None, []
        decisions, chosen = [], None
        for o in db.q("SELECT * FROM offers ORDER BY offer_id"):
            why = []
            if st["segment"] not in [x.strip() for x in o["eligible_segments"].split(";")]:
                why.append("segment not eligible")
            if not (_d(o["valid_from"]) <= as_of <= _d(o["expiry"])):
                why.append(f"not valid on {as_of} ({o['valid_from']}..{o['expiry']})")
            if o["channel"].upper() != "EMAIL":
                why.append(f"channel {o['channel']} not email")
            if p["tenure_months"] < int(o["min_tenure_months"]):
                why.append(f"needs tenure {o['min_tenure_months']}m")
            decisions.append({"offer_id": o["offer_id"], "eligible": not why, "reasons": why})
            if not why and chosen is None:
                chosen = o
        return chosen, decisions

    # ---------------- FR-04 facts the draft may use ----------------
    def facts(self, p: dict, st: dict, offer: dict | None, as_of: date, trace: dict) -> dict:
        f = {"first_name": p["first_name"], "plan": p["plan"], "tenure_months": p["tenure_months"], **SUPPORT}
        if offer:
            f.update(offer_id=offer["offer_id"], offer_name=offer["name"], offer_value=offer["value_text"],
                     offer_terms=offer["terms"], offer_expiry=offer["expiry"])
        if st["segment"] == "payment_reminder":
            oldest = max(p["overdue"], key=lambda o: o["days_overdue"])
            f.update(invoice_id=oldest["invoice_id"], due_date=oldest["due_date"],
                     days_overdue=oldest["days_overdue"], amount_due=f"{oldest['amount']:.2f}")
            if st["stage"] == 3:
                f["final_notice_contact_days"] = int(self._r("final_notice_contact_days", as_of, trace))
        return f

    def render(self, st: dict, f: dict) -> dict:
        subj, body = TEMPLATES[st["template"]]
        blocks = {"offer_block": OFFER_BLOCK.format(**f) if f.get("offer_id") else "",
                  "gratitude_line": "Thank you for being a valued customer with us. " if st.get("gratitude") else ""}
        return {"subject": subj.format(**f, **blocks), "body": body.format(**f, **blocks)}

    # ---------------- FR-07 safety and compliance checks on a draft ----------------
    def validate(self, draft: dict, f: dict, st: dict, offer: dict | None, as_of: date) -> list[dict]:
        text = f"{draft.get('subject', '')}\n{draft.get('body', '')}"
        out = []
        if not draft.get("subject", "").strip() or not draft.get("body", "").strip():
            out.append({"code": "EMPTY_DRAFT", "detail": "subject or body empty"})
        extra = _nums(text) - _nums(json.dumps(f))
        if extra:
            out.append({"code": "UNSUPPORTED_NUMBER", "detail": f"numbers not in verified facts: {sorted(extra)}"})
        ids = set(re.findall(r"\bOFF-[A-Z0-9-]+\b", text))
        if ids - ({offer["offer_id"]} if offer else set()):
            out.append({"code": "UNKNOWN_OFFER", "detail": f"offer ids not approved for this customer: {sorted(ids)}"})
        if offer and _d(offer["expiry"]) < as_of:
            out.append({"code": "OFFER_EXPIRED", "detail": offer["offer_id"]})
        if offer and offer["terms"].lower() not in text.lower():
            out.append({"code": "MISSING_OFFER_TERMS", "detail": "offer terms must be included verbatim"})
        for pat in BLOCKED_PHRASES:
            m = re.search(pat, text, re.I)
            if m:
                out.append({"code": "BLOCKED_PHRASE", "detail": m.group(0)})
        emails = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)) - {SUPPORT["dispute_contact"]}
        if emails or re.search(r"(?<!\w)(?:\+91[-\s]?)?[6-9]\d{9}(?!\w)|\b(?:\d[ -]?){13,19}\b", text):
            out.append({"code": "PII_LEAK", "detail": "personal contact or card data in message"})
        if st["segment"] == "payment_reminder" and SUPPORT["dispute_contact"] not in text:
            out.append({"code": "MISSING_DISPUTE_PATH", "detail": "reminders must include the dispute contact"})
        return out


DOMAIN = Engage()
