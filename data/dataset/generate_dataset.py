#!/usr/bin/env python3
"""
Synthetic dataset generator for the customer-outreach pipeline.

Deterministic: the same SEED always produces the same files.
Every customer is built from a scenario (target segment + injected stop signs),
then the reference rules below re-derive the answer key from the data itself
and assert it matches the intent. If a scenario does not produce what it was
meant to, generation fails loudly.

Usage:  python3 generate_dataset.py [output_dir]
"""
import csv
import os
import random
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

SEED = 20261027
SNAP = date(2026, 10, 27)          # snapshot_date for every record
OUT = sys.argv[1] if len(sys.argv) > 1 else "dataset"


def D(n):
    return timedelta(days=n)


# ----------------------------------------------------------------------------
# Policy constants (mirror these in the pipeline's policy config)
# ----------------------------------------------------------------------------
DORMANT_DAYS = 30            # last_activity_days >= 30            -> dormant
DECLINE_MIN_PREV = 10        # declining only if activity_prev_30d >= 10
DECLINE_PCT = 70             # activity_30d <= 70% of activity_prev_30d -> declining
LOYAL_TENURE = 24            # loyalty: tenure >= 24 months
LOYAL_TIERS = ("Gold", "Platinum")
LOYAL_MIN_BILLS = 6          # postpaid: at least 6 bills in last 12
LOYAL_PCT = 90               # postpaid: on-time >= 90%
REMINDER_WINDOW = 7          # unpaid bill overdue, or due within 7 days
COOLDOWN_DAYS = 7            # any message sent < 7 days ago      -> block
DUP_DAYS = 14                # same message_type sent < 14 days ago -> block
OFFER_REPEAT_DAYS = 90       # same offer_id sent < 90 days ago   -> skip offer

SEG_ORDER = ["payment_reminder", "dormant", "declining_activity",
             "loyalty_candidate", "consistent"]
BLOCK_ORDER = ["account_inactive", "data_conflict", "email_not_allowed",
               "consent_missing", "email_undeliverable",
               "dispute_or_complaint_open", "payment_arrangement_or_hardship",
               "cooldown_or_duplicate"]

PLANS = {
    "postpaid": [("PP399", 399), ("PP599", 599), ("PP999", 999), ("PP1499", 1499)],
    "prepaid": [("PR199", 199), ("PR299", 299), ("PR479", 479)],
}

TEMPLATES = {
    "appreciation": "TPL-APP-01", "reward_offer": "TPL-RWD-01",
    "reengagement_offer": "TPL-REE-01", "payment_reminder": "TPL-PR-01",
    "overdue_notice": "TPL-OD-01",
}

# Approved offer catalog (as of SNAP). Lower priority number = tried first.
OFFERS = [
    dict(offer_id="OFR-RWD-SMS", offer_name="Loyalty SMS bonus", message_type="reward_offer",
         eligible_segments="loyalty_candidate", plan_type="any", min_tenure_months=12, channel="sms",
         value="200", value_unit="loyalty_points", terms="Credited within 48 hours.",
         valid_from=date(2026, 9, 1), expiry_date=date(2026, 12, 31), priority=1),
    dict(offer_id="OFR-RWD-500", offer_name="Loyalty bill credit", message_type="reward_offer",
         eligible_segments="loyalty_candidate", plan_type="postpaid", min_tenure_months=36, channel="email",
         value="100.00", value_unit="INR_bill_credit", terms="Applied to next bill. One per account.",
         valid_from=date(2026, 10, 1), expiry_date=date(2026, 12, 31), priority=2),
    dict(offer_id="OFR-RWD-2GB", offer_name="Loyalty data gift", message_type="reward_offer",
         eligible_segments="loyalty_candidate", plan_type="any", min_tenure_months=24, channel="email",
         value="2", value_unit="GB_data_30d", terms="Valid 30 days from activation.",
         valid_from=date(2026, 7, 1), expiry_date=date(2026, 11, 30), priority=3),
    dict(offer_id="OFR-REE-EXP", offer_name="Come-back data pack (expired)", message_type="reengagement_offer",
         eligible_segments="declining_activity|dormant", plan_type="any", min_tenure_months=0, channel="email",
         value="5", value_unit="GB_data_7d", terms="Valid 7 days from activation.",
         valid_from=date(2026, 7, 1), expiry_date=date(2026, 10, 20), priority=1),
    dict(offer_id="OFR-REE-FUT", offer_name="Festive re-engagement (not yet live)", message_type="reengagement_offer",
         eligible_segments="declining_activity", plan_type="any", min_tenure_months=0, channel="email",
         value="10", value_unit="GB_data_7d", terms="Valid 7 days from activation.",
         valid_from=date(2026, 11, 15), expiry_date=date(2026, 12, 31), priority=2),
    dict(offer_id="OFR-REE-PRE", offer_name="Prepaid recharge cashback", message_type="reengagement_offer",
         eligible_segments="dormant", plan_type="prepaid", min_tenure_months=0, channel="email",
         value="50.00", value_unit="INR_cashback", terms="On next recharge of 199 or more.",
         valid_from=date(2026, 8, 1), expiry_date=date(2026, 11, 30), priority=3),
    dict(offer_id="OFR-REE-3GB", offer_name="Re-engagement data pack", message_type="reengagement_offer",
         eligible_segments="declining_activity|dormant", plan_type="any", min_tenure_months=3, channel="email",
         value="3", value_unit="GB_data_7d", terms="Valid 7 days from activation.",
         valid_from=date(2026, 7, 1), expiry_date=date(2026, 12, 15), priority=4),
    dict(offer_id="OFR-APP-1GB", offer_name="Thank-you data", message_type="appreciation",
         eligible_segments="consistent", plan_type="any", min_tenure_months=6, channel="email",
         value="1", value_unit="GB_data_30d", terms="Valid 30 days from activation.",
         valid_from=date(2026, 7, 1), expiry_date=date(2026, 12, 31), priority=1),
]

F_NAMES = ["Asha", "Priya", "Divya", "Kavya", "Meera", "Ananya", "Lakshmi", "Neha", "Pooja", "Sneha",
           "Ishita", "Ritu", "Deepa", "Farah", "Zoya", "Nandini", "Shreya", "Tanvi", "Aparna", "Gayatri"]
M_NAMES = ["Arjun", "Rahul", "Vikram", "Karthik", "Rohan", "Imran", "Suresh", "Aditya", "Nikhil", "Sanjay",
           "Manoj", "Varun", "Harish", "Faisal", "Pranav", "Gautam", "Ravi", "Siddharth", "Ajay", "Joseph"]
CITIES = ["Pune", "Chennai", "Hyderabad", "Bengaluru", "Mumbai", "Kolkata", "Jaipur", "Kochi", "Lucknow", "Ahmedabad"]


def tier_for(points):
    return "Silver" if points < 2000 else ("Gold" if points < 8000 else "Platinum")


def money(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------------------
# Reference rules (the answer key is derived from data with these)
# ----------------------------------------------------------------------------
def unpaid_bills(bills):
    return sorted([b for b in bills if b["bill_status"] in ("due", "overdue")], key=lambda b: b["due_date"])


def target_bill(bills):
    actionable = [b for b in unpaid_bills(bills) if b["due_date"] <= SNAP + D(REMINDER_WINDOW)]
    return actionable[0] if actionable else None


def classify(c, bills):
    segs, codes = [], {}
    tb = target_bill(bills)
    if tb:
        od = (SNAP - tb["due_date"]).days
        segs.append("payment_reminder")
        codes["payment_reminder"] = (f"PAY_OVERDUE_{od}D" if od > 0 else
                                     "PAY_DUE_TODAY" if od == 0 else f"PAY_DUE_IN_{-od}D")
    if c["last_activity_days"] >= DORMANT_DAYS:
        segs.append("dormant")
        codes["dormant"] = f"DORMANT_{c['last_activity_days']}D"
    a, p = c["activity_30d"], c["activity_prev_30d"]
    if p >= DECLINE_MIN_PREV and 100 * a <= DECLINE_PCT * p:
        segs.append("declining_activity")
        codes["declining_activity"] = f"DECLINE_{round(100 * (p - a) / p)}PCT"
    if c["tenure_months"] >= LOYAL_TENURE and c["loyalty_tier"] in LOYAL_TIERS:
        bi, ot = c["bills_issued_last_12"], c["on_time_payments_last_12"]
        if c["plan_type"] == "prepaid" or (bi >= LOYAL_MIN_BILLS and 100 * ot >= LOYAL_PCT * bi):
            segs.append("loyalty_candidate")
            codes["loyalty_candidate"] = (f"LOYAL_T{c['tenure_months']}_{c['loyalty_tier'].upper()}"
                                          + ("_PREPAID" if c["plan_type"] == "prepaid" else f"_OT{ot}OF{bi}"))
    if not segs:
        segs.append("consistent")
        codes["consistent"] = f"STABLE_{a}_VS_{p}"
    segs.sort(key=SEG_ORDER.index)
    return segs, codes


def strategy(primary, tb):
    if primary == "payment_reminder":
        od = (SNAP - tb["due_date"]).days
        if od <= 0:
            return "payment_reminder", "courteous_reminder"
        if od <= 15:
            return "overdue_notice", "overdue_stage_1_polite"
        if od <= 30:
            return "overdue_notice", "overdue_stage_2_firm"
        return "overdue_notice", "overdue_stage_3_final"
    return {"consistent": ("appreciation", "appreciation_warm"),
            "loyalty_candidate": ("reward_offer", "reward_celebratory"),
            "declining_activity": ("reengagement_offer", "reengagement_helpful"),
            "dormant": ("reengagement_offer", "winback_friendly")}[primary]


def data_conflicts(c, bills, consent):
    out = []
    for b in bills:
        if b["bill_status"] == "paid" and b["amount_paid"] != b["amount_due"]:
            out.append("PAID_AMOUNT_MISMATCH")
        if b["bill_status"] == "paid" and b["last_payment_date"] is None:
            out.append("PAID_NO_PAYMENT_DATE")
        if b["bill_status"] in ("due", "overdue") and b["amount_paid"] >= b["amount_due"]:
            out.append("UNPAID_BUT_FULLY_PAID")
        if (b["bill_status"] == "overdue" and b["due_date"] >= SNAP) or \
           (b["bill_status"] == "due" and b["due_date"] < SNAP):
            out.append("STATUS_DATE_MISMATCH")
        if not b["currency"]:
            out.append("MISSING_CURRENCY")
    if c["last_activity_days"] >= DORMANT_DAYS and c["activity_30d"] > 0:
        out.append("ACTIVITY_MISMATCH")
    if c["loyalty_tier"] != tier_for(c["loyalty_points"]):
        out.append("TIER_MISMATCH")
    if c["plan_type"] == "postpaid":
        ot = sum(1 for b in bills if b["bill_status"] == "paid" and b["last_payment_date"]
                 and b["last_payment_date"] <= b["due_date"])
        if c["bills_issued_last_12"] != len(bills) or c["on_time_payments_last_12"] != ot:
            out.append("PAYMENT_COUNT_MISMATCH")
    if consent["consent_updated_at"] > SNAP:
        out.append("FUTURE_CONSENT_DATE")
    return sorted(set(out))


def precheck(c, bills, consent, msgs, primary, mtype):
    r = []
    if c["account_status"] != "active":
        r.append("account_inactive")
    if data_conflicts(c, bills, consent):
        r.append("data_conflict")
    if not consent["email_allowed"]:
        r.append("email_not_allowed")
    need = "service_consent" if primary == "payment_reminder" else "marketing_consent"
    if not consent[need]:
        r.append("consent_missing")
    if not c["email_address"] or consent["email_status"] != "valid":
        r.append("email_undeliverable")
    if consent["open_complaint"] or any(b["dispute_open"] for b in bills):
        r.append("dispute_or_complaint_open")
    if primary == "payment_reminder" and any(b["payment_arrangement_active"] or b["hardship_flag"]
                                             for b in unpaid_bills(bills)):
        r.append("payment_arrangement_or_hardship")
    recent = any((SNAP - m["sent_at"]).days < COOLDOWN_DAYS for m in msgs)
    dup = any(m["message_type"] == mtype and (SNAP - m["sent_at"]).days < DUP_DAYS for m in msgs)
    if recent or dup:
        r.append("cooldown_or_duplicate")
    return r


def select_offer(c, primary, mtype, msgs):
    for o in sorted([o for o in OFFERS if o["message_type"] == mtype], key=lambda o: o["priority"]):
        if primary not in o["eligible_segments"].split("|"):
            continue                                                  # group test
        if o["plan_type"] not in ("any", c["plan_type"]):
            continue                                                  # group test (plan)
        if not (o["valid_from"] <= SNAP <= o["expiry_date"]):
            continue                                                  # expiry test
        if o["channel"] not in ("email", "any"):
            continue                                                  # email channel test
        if c["tenure_months"] < o["min_tenure_months"]:
            continue                                                  # tenure test
        if any(m["offer_id"] == o["offer_id"] and (SNAP - m["sent_at"]).days < OFFER_REPEAT_DAYS for m in msgs):
            continue                                                  # repeat-offer guard
        return o["offer_id"]
    return None


def answer_key(c, bills, consent, msgs):
    segs, codes = classify(c, bills)
    primary = segs[0]
    tb = target_bill(bills) if primary == "payment_reminder" else None
    mtype, strat = strategy(primary, tb)
    blocks = precheck(c, bills, consent, msgs, primary, mtype)
    offer = None if blocks else select_offer(c, primary, mtype, msgs)
    total_out = sum((b["amount_due"] - b["amount_paid"] for b in unpaid_bills(bills)
                     if b["due_date"] <= SNAP + D(REMINDER_WINDOW)), Decimal("0.00"))
    return dict(
        expected_segment=primary,
        expected_all_segments="|".join(segs),
        expected_reason_code=codes[primary],
        expected_outcome="blocked" if blocks else "draft",
        expected_block_reason=blocks[0] if blocks else "",
        expected_all_block_reasons="|".join(blocks),
        expected_data_conflicts="|".join(data_conflicts(c, bills, consent)),
        expected_message_type=mtype,
        expected_strategy=strat,
        expected_target_bill_id=tb["bill_id"] if tb else "",
        expected_overdue_days=(SNAP - tb["due_date"]).days if tb else "",
        expected_amount_outstanding=str(tb["amount_due"] - tb["amount_paid"]) if tb else "",
        expected_total_outstanding=str(total_out) if tb else "",
        expected_offer_id=offer or "",
        expected_greeting_name=c["first_name"] or "Customer",
        human_review_required="true" if strat == "overdue_stage_3_final" else "false",
    )


# ----------------------------------------------------------------------------
# Scenario builder
# ----------------------------------------------------------------------------
class Gen:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.seq = 1000
        self.customers, self.bills, self.consent, self.msgs, self.truth = [], [], [], [], []
        self.msg_seq = 0

    def _msg(self, cid, ago, mtype, segment, channel="email", outcome="delivered", offer_id=None, bill_id=None,
             template=None):
        self.msg_seq += 1
        return dict(message_id=f"M-{self.msg_seq:05d}", customer_id=cid, sent_at=SNAP - D(ago), channel=channel,
                    message_type=mtype, segment=segment, template_id=template or TEMPLATES[mtype],
                    offer_id=offer_id, bill_id=bill_id, outcome=outcome)

    def _offer_at(self, mtype, sent):
        ok = [o["offer_id"] for o in OFFERS if o["message_type"] == mtype and o["channel"] != "sms"
              and o["valid_from"] <= sent <= o["expiry_date"]]
        return self.rng.choice(ok) if ok and self.rng.random() < 0.7 else None

    def build(self, seg, tag, inject=(), expect=(), **o):
        r = self.rng
        self.seq += 1
        cid = f"C{self.seq}"
        female = r.random() < 0.5
        first_name = None if o.get("no_name") else r.choice(F_NAMES if female else M_NAMES)

        needs_bills = seg == "payment_reminder" or "bill" in o or any(
            i.startswith("conflict:") and i.split(":")[1] in ("paid_short", "missing_currency", "count_mismatch")
            for i in inject)
        plan_type = o.get("plan_type") or ("postpaid" if needs_bills or r.random() < 0.75 else "prepaid")
        fail = o.get("fail")
        if seg == "consistent" and not fail and "points" not in o and "tenure" not in o:
            fail = r.choice(["silver", "short_tenure", "late_payer"] if plan_type == "postpaid"
                            else ["silver", "short_tenure"])

        if "tenure" in o:
            tenure = o["tenure"]
        elif seg == "loyalty_candidate":
            tenure = r.randint(LOYAL_TENURE, 110)
        elif fail == "short_tenure":
            tenure = r.randint(1, LOYAL_TENURE - 1)
        elif fail == "late_payer":
            tenure = r.randint(LOYAL_TENURE, 110)
        else:
            tenure = r.randint(1, 120)

        # --- activity
        kind = o.get("activity") or {"dormant": "dormant", "declining_activity": "declining"}.get(seg) or (
            r.choices(["stable", "declining", "dormant"], [0.7, 0.15, 0.15])[0]
            if seg == "payment_reminder" else "stable")
        if kind == "dormant":
            lad = r.randint(30, 240)
            act30 = 0
            prev = 0 if lad >= 60 else r.randint(1, 8)
        elif kind == "declining":
            lad = r.randint(0, 20)
            prev = r.randint(15, 90)
            act30 = max(1, int(prev * r.uniform(0.10, 0.69)))
        else:
            lad = r.randint(0, 14)
            prev = r.randint(10, 90) if r.random() < 0.9 else r.randint(1, 9)
            act30 = max(1, round(prev * r.uniform(0.75, 1.35)))
        lad = o.get("lad", lad)
        prev = o.get("prev", prev)
        act30 = o.get("act30", act30)

        # --- loyalty
        if "points" in o:
            pts = o["points"]
        elif seg == "loyalty_candidate":
            pts = r.randint(2000, 15000)
        elif fail == "silver":
            pts = r.randint(0, 1999)
        else:
            pts = r.choice([0, r.randint(1, 1999), r.randint(2000, 7999), r.randint(8000, 15000)])
        tier = tier_for(pts)

        # --- billing
        pid, price = r.choice(PLANS[plan_type]) if "plan" not in o else o["plan"]
        bills = []
        if plan_type == "postpaid":
            if "bill" in o:
                bkind, bval = o["bill"]
            elif seg == "payment_reminder":
                bkind, bval = (("due", r.randint(0, 7)) if r.random() < 0.3 else
                               ("overdue", r.choice([r.randint(1, 15), r.randint(1, 15), r.randint(16, 30),
                                                     r.randint(31, 45)])))
            else:
                bkind, bval = "none", None
            m = 0
            if bkind == "none":
                d_new, unpaid_from = SNAP + D(r.randint(-14, 14)), None
            elif bkind in ("due", "due_far"):
                d_new = unpaid_from = SNAP + D(bval)
            else:                                   # overdue
                unpaid_from = SNAP - D(bval)
                m = (bval + 15) // 30
                d_new = unpaid_from + D(30 * m)
            n = max(min(tenure, 12), m + 1)
            tenure = max(tenure, n)
            dues = [d_new - D(30 * k) for k in range(n)][::-1]
            extra = money(r.choice([0, 0, 0, r.randint(10, 200), r.randint(10, 200) + 0.5]))
            autopay = r.random() < 0.3
            # late-payment plan
            paid_idx = [i for i, d in enumerate(dues) if not (unpaid_from and d >= unpaid_from)]
            can_late = [i for i in paid_idx if dues[i] + D(1) <= SNAP]
            if "late" in o:
                late_n = o["late"]
            elif seg == "loyalty_candidate":
                late_n = 0 if n < 10 else r.choice([0, 0, 1])
            elif fail == "late_payer":
                late_n = n // 10 + 1 + r.randint(0, 2)
            else:
                late_n = sum(1 for _ in can_late if r.random() < 0.08)
            late_set = set(r.sample(can_late, min(late_n, len(can_late))))
            for i, due in enumerate(dues):
                amt = money(Decimal(price) + extra)
                b = dict(bill_id=f"B-{cid}-{due:%Y%m%d}", customer_id=cid, amount_due=amt, currency="INR",
                         due_date=due, autopay_enabled=autopay, dispute_open=False, dispute_opened_date=None,
                         payment_arrangement_active=False, hardship_flag=False)
                if unpaid_from and due >= unpaid_from:
                    b.update(bill_status="overdue" if due < SNAP else "due", amount_paid=money(0),
                             last_payment_date=None)
                    if o.get("partial") and due == unpaid_from and due < SNAP:
                        b["amount_paid"] = money(amt * Decimal(r.choice(["0.25", "0.40", "0.50"])))
                        b["last_payment_date"] = due + D(r.randint(1, (SNAP - due).days))
                else:
                    if i in late_set:
                        pay = due + D(r.randint(1, min(20, (SNAP - due).days)))
                    else:
                        issue = due - D(15)
                        latest = min(due, SNAP)
                        pay = latest - D(r.randint(0, min(10, (latest - issue).days)))
                    b.update(bill_status="paid", amount_paid=amt, last_payment_date=pay)
                bills.append(b)
        ot = sum(1 for b in bills if b["bill_status"] == "paid" and b["last_payment_date"] <= b["due_date"])

        lang = o.get("lang") or r.choices(["en", "hi", "ta", "te", "kn", "mr", "bn"],
                                          [70, 15, 3, 3, 3, 3, 3])[0]
        dob = SNAP - D(r.randint(18 * 365, 75 * 365))
        c = dict(customer_id=cid, first_name=first_name,
                 email_address=f"{(first_name or 'user').lower()}.{cid.lower()}@example.test",
                 snapshot_date=SNAP, tenure_months=tenure, plan_type=plan_type, plan_id=pid,
                 plan_price=money(price), account_status="active", preferred_language=lang,
                 activity_unit="sessions", last_activity_days=lad, activity_30d=act30, activity_prev_30d=prev,
                 loyalty_points=pts, loyalty_tier=tier,
                 loyalty_points_expiry_date=(SNAP + D(r.randint(30, 365))) if pts > 0 else None,
                 on_time_payments_last_12=ot, bills_issued_last_12=len(bills),
                 date_of_birth=dob, gender="F" if female else r.choice(["M", "M", "M", "Other"]),
                 home_address=f"{r.randint(1, 400)} Test Lane, {r.choice(CITIES)}",
                 phone=f"+9190000{r.randint(0, 99999):05d}",
                 national_id_last4=f"{r.randint(0, 9999):04d}" if r.random() > 0.1 else f"0{r.randint(0, 999):03d}",
                 credit_score=r.randint(300, 900))
        consent = dict(customer_id=cid, email_allowed=True, marketing_consent=True, service_consent=True,
                       consent_updated_at=SNAP - D(r.randint(5, max(6, min(tenure * 30, 900)))),
                       email_status="valid", open_complaint=False)

        # primary + message type are needed to build a history that does / doesn't collide
        segs, _ = classify(c, bills)
        primary = segs[0]
        tb = target_bill(bills) if primary == "payment_reminder" else None
        mtype, _ = strategy(primary, tb)

        # --- contact history (all >= 15 days ago by default, so no accidental blocks)
        msgs = []
        max_ago = min(tenure * 30, 180)
        for _ in range(r.randint(0, 5)):
            if max_ago < 15:
                break
            ago = r.randint(15, max_ago)
            sent = SNAP - D(ago)
            t = r.choice(["appreciation", "reward_offer", "reengagement_offer", "payment_reminder"])
            ch = "email" if r.random() < 0.85 else "sms"
            out = r.choices(["delivered", "opened", "complained"], [50, 47, 3])[0] if ch == "email" else "delivered"
            if t == "payment_reminder":
                # only bills already issued and still unpaid on the day the message went out
                cand = [b for b in bills if sent - D(30) <= b["due_date"] <= sent + D(7)
                        and b["due_date"] - D(15) <= sent
                        and (b["last_payment_date"] is None or b["last_payment_date"] > sent)]
                if not cand:
                    continue
                b = cand[-1]
                t = "payment_reminder" if sent <= b["due_date"] else "overdue_notice"
                msgs.append(self._msg(cid, ago, t, "payment_reminder", ch, out, bill_id=b["bill_id"]))
            else:
                segname = {"appreciation": "consistent", "reward_offer": "loyalty_candidate"}.get(t) or \
                          r.choice(["dormant", "declining_activity"])
                offer = self._offer_at(t, sent) if ch == "email" else None
                msgs.append(self._msg(cid, ago, t, segname, ch, out, offer_id=offer))
        # realistic reminder progression on the current unpaid bill
        if tb and o.get("progression", True):
            od = (SNAP - tb["due_date"]).days
            if od + 3 >= 15 or (od + 3 >= COOLDOWN_DAYS and mtype != "payment_reminder"):
                msgs.append(self._msg(cid, od + 3, "payment_reminder", "payment_reminder", bill_id=tb["bill_id"],
                                      outcome=r.choice(["delivered", "opened"])))
            if od > 20 and od - 5 >= DUP_DAYS:
                msgs.append(self._msg(cid, od - 5, "overdue_notice", "payment_reminder", bill_id=tb["bill_id"],
                                      outcome=r.choice(["delivered", "opened"])))
        # explicit contact overrides
        if "last_contact" in o:
            L, ltype = o["last_contact"], o.get("last_type")
            msgs = [x for x in msgs if (SNAP - x["sent_at"]).days >= L]
            if not ltype:
                ltype = r.choice([t for t in ["appreciation", "reward_offer", "reengagement_offer"] if t != mtype])
            seg_of = {"appreciation": "consistent", "reward_offer": "loyalty_candidate",
                      "reengagement_offer": "declining_activity", "payment_reminder": "payment_reminder",
                      "overdue_notice": "payment_reminder"}[ltype]
            msgs.append(self._msg(cid, L, ltype, seg_of, bill_id=tb["bill_id"] if tb and seg_of == "payment_reminder" else None))
        if "sent_offer" in o:
            oid, ago = o["sent_offer"]
            off = next(x for x in OFFERS if x["offer_id"] == oid)
            msgs.append(self._msg(cid, ago, off["message_type"], off["eligible_segments"].split("|")[0],
                                  outcome="opened", offer_id=oid))

        # --- inject stop signs / conflicts
        unpaid = unpaid_bills(bills)
        for inj in inject:
            name, _, arg = inj.partition(":")
            if name == "inactive":
                c["account_status"] = arg or r.choice(["suspended", "closed"])
            elif name == "email_off":
                consent["email_allowed"] = False
            elif name == "mkt_off":
                consent["marketing_consent"] = False
            elif name == "svc_off":
                consent["service_consent"] = False
            elif name == "bounced":
                consent["email_status"] = "bounced"
            elif name == "unverified":
                consent["email_status"] = "unverified"
            elif name == "no_email":
                c["email_address"] = None
            elif name == "complaint":
                consent["open_complaint"] = True
            elif name == "dispute":
                tgt = unpaid[0] if unpaid else bills[-1]
                tgt["dispute_open"] = True
                tgt["dispute_opened_date"] = SNAP - D(r.randint(1, 20))
            elif name == "arrangement":
                unpaid[0]["payment_arrangement_active"] = True
            elif name == "hardship":
                unpaid[0]["hardship_flag"] = True
            elif name == "cooldown":
                L = int(arg) if arg else r.randint(0, COOLDOWN_DAYS - 1)
                ltype = r.choice([t for t in ["appreciation", "reward_offer", "reengagement_offer"] if t != mtype])
                msgs.append(self._msg(cid, L, ltype, "consistent" if ltype == "appreciation" else
                                      "loyalty_candidate" if ltype == "reward_offer" else "dormant"))
            elif name == "dup":
                ago = int(arg) if arg else r.randint(COOLDOWN_DAYS, DUP_DAYS - 1)
                msgs = [x for x in msgs if (SNAP - x["sent_at"]).days >= COOLDOWN_DAYS]
                msgs.append(self._msg(cid, ago, mtype, primary, bill_id=tb["bill_id"] if tb else None))
            elif name == "conflict":
                if arg == "paid_short":
                    b = next(b for b in bills if b["bill_status"] == "paid")
                    b["amount_paid"] = money(b["amount_due"] - Decimal("100.00"))
                elif arg == "overdue_fully_paid":
                    unpaid[0]["amount_paid"] = unpaid[0]["amount_due"]
                    unpaid[0]["last_payment_date"] = SNAP - D(1)
                elif arg == "status_date_mismatch":
                    unpaid[0]["bill_status"] = "overdue"
                elif arg == "missing_currency":
                    bills[-1]["currency"] = None
                elif arg == "activity_mismatch":
                    c["activity_30d"] = r.randint(1, 5)
                elif arg == "tier_mismatch":
                    c["loyalty_points"] = r.randint(300, 1999)
                    c["loyalty_tier"] = "Gold"
                elif arg == "count_mismatch":
                    c["on_time_payments_last_12"] = c["bills_issued_last_12"]
                    late = [b for b in bills if b["bill_status"] == "paid"]
                    for b in r.sample(late, 3):          # reality: 3 late payments
                        b["last_payment_date"] = b["due_date"] + D(r.randint(1, 10))
                elif arg == "future_consent":
                    consent["consent_updated_at"] = SNAP + D(r.randint(1, 30))
                else:
                    raise ValueError(arg)
            else:
                raise ValueError(inj)

        # email status consistency with history
        emails = sorted([x for x in msgs if x["channel"] == "email"], key=lambda x: x["sent_at"])
        if consent["email_status"] == "bounced":
            if emails:
                emails[-1]["outcome"] = "bounced"
            else:
                msgs.append(self._msg(cid, min(max_ago, 40) if max_ago >= 15 else 15, "appreciation",
                                      "consistent", outcome="bounced"))
        elif consent["email_status"] == "unverified":
            for x in emails:
                x["channel"], x["outcome"] = "sms", "delivered"
        if c["email_address"] is None:
            for x in msgs:
                x["channel"] = "sms"
                if x["outcome"] in ("opened", "bounced", "complained"):
                    x["outcome"] = "delivered"

        key = answer_key(c, bills, consent, msgs)
        got_blocks = key["expected_all_block_reasons"].split("|") if key["expected_all_block_reasons"] else []
        if key["expected_segment"] != seg or set(got_blocks) != set(expect):
            raise AssertionError(f"{cid} {tag}: wanted seg={seg} blocks={sorted(expect)}; "
                                 f"got seg={key['expected_segment']} blocks={got_blocks} "
                                 f"conflicts={key['expected_data_conflicts']}")
        if "offer" in o and key["expected_offer_id"] != (o["offer"] or ""):
            raise AssertionError(f"{cid} {tag}: wanted offer {o['offer']}, got {key['expected_offer_id']}")

        self.customers.append(c)
        self.bills += bills
        self.consent.append(consent)
        self.msgs += sorted(msgs, key=lambda x: x["sent_at"])
        self.truth.append(dict(customer_id=cid, scenario_tag=tag, **key))


# ----------------------------------------------------------------------------
# Scenario plan
# ----------------------------------------------------------------------------
def plan(g):
    # 1) Clean baseline: 20 per segment, all should produce a draft
    for seg in SEG_ORDER:
        for _ in range(20):
            g.build(seg, f"clean_{seg}")

    # 2) Each stop sign, 8 cases spread across segments
    B = "account_inactive"
    g.build("payment_reminder", "block_inactive_closed_overdue", ["inactive:closed"], [B], bill=("overdue", 40))
    g.build("payment_reminder", "block_inactive_suspended_overdue", ["inactive:suspended"], [B], bill=("overdue", 20))
    g.build("payment_reminder", "block_inactive_suspended_due", ["inactive:suspended"], [B], bill=("due", 3))
    g.build("dormant", "block_inactive_closed_dormant", ["inactive:closed"], [B])
    g.build("dormant", "block_inactive_closed_dormant", ["inactive:closed"], [B])
    g.build("consistent", "block_inactive_suspended", ["inactive:suspended"], [B])
    g.build("loyalty_candidate", "block_inactive_suspended", ["inactive:suspended"], [B])
    g.build("declining_activity", "block_inactive_closed", ["inactive:closed"], [B])

    B = "data_conflict"
    g.build("payment_reminder", "conflict_overdue_but_fully_paid", ["conflict:overdue_fully_paid"], [B], bill=("overdue", 9))
    g.build("payment_reminder", "conflict_overdue_but_fully_paid", ["conflict:overdue_fully_paid"], [B], bill=("overdue", 22))
    g.build("payment_reminder", "conflict_status_overdue_future_due", ["conflict:status_date_mismatch"], [B], bill=("due", 4))
    g.build("payment_reminder", "conflict_missing_currency", ["conflict:missing_currency"], [B], bill=("overdue", 6))
    g.build("consistent", "conflict_paid_amount_short", ["conflict:paid_short"], [B], plan_type="postpaid", fail="short_tenure", tenure=14)
    g.build("dormant", "conflict_dormant_but_active_30d", ["conflict:activity_mismatch"], [B])
    g.build("loyalty_candidate", "conflict_tier_vs_points", ["conflict:tier_mismatch"], [B])
    g.build("loyalty_candidate", "conflict_ontime_overstated", ["conflict:count_mismatch"], [B], plan_type="postpaid", tenure=48)

    B = "email_not_allowed"
    for seg in ["payment_reminder", "payment_reminder", "loyalty_candidate", "loyalty_candidate",
                "consistent", "dormant", "declining_activity", "consistent"]:
        g.build(seg, "block_email_not_allowed", ["email_off"], [B])

    B = "consent_missing"
    for seg in ["consistent", "loyalty_candidate", "loyalty_candidate", "declining_activity", "dormant", "dormant"]:
        g.build(seg, "block_marketing_consent_off", ["mkt_off"], [B])
    g.build("payment_reminder", "block_service_consent_off", ["svc_off"], [B], bill=("overdue", 12))
    g.build("payment_reminder", "block_service_consent_off", ["svc_off"], [B], bill=("due", 2))

    B = "email_undeliverable"
    for seg, inj in [("consistent", "bounced"), ("dormant", "bounced"), ("payment_reminder", "bounced"),
                     ("loyalty_candidate", "unverified"), ("declining_activity", "unverified"),
                     ("payment_reminder", "unverified"), ("consistent", "no_email"), ("payment_reminder", "no_email")]:
        g.build(seg, f"block_email_{inj}", [inj], [B])

    B = "dispute_or_complaint_open"
    for days in (5, 14, 25, 38):
        g.build("payment_reminder", "block_dispute_open", ["dispute"], [B], bill=("overdue", days))
    for seg in ["consistent", "loyalty_candidate", "dormant", "declining_activity"]:
        g.build(seg, "block_open_complaint", ["complaint"], [B])

    B = "payment_arrangement_or_hardship"
    for days in (8, 18, 33, 44):
        g.build("payment_reminder", "block_payment_arrangement", ["arrangement"], [B], bill=("overdue", days))
    for days in (3, 12, 27, 41):
        g.build("payment_reminder", "block_hardship_flag", ["hardship"], [B], bill=("overdue", days))

    B = "cooldown_or_duplicate"
    for seg, d in [("consistent", 0), ("loyalty_candidate", 3), ("dormant", 6), ("payment_reminder", 2)]:
        g.build(seg, f"block_cooldown_{d}d", [f"cooldown:{d}"], [B])
    for seg, d in [("declining_activity", 9), ("consistent", 13), ("loyalty_candidate", 10)]:
        g.build(seg, f"block_duplicate_{d}d", [f"dup:{d}"], [B])
    g.build("payment_reminder", "block_duplicate_overdue_notice_11d", ["dup:11"], [B], bill=("overdue", 25))

    # 3) Boundaries and edge cases that must still produce a draft (or the right segment)
    g.build("payment_reminder", "edge_marketing_off_reminder_still_ok", ["mkt_off"], [], bill=("overdue", 10))
    g.build("payment_reminder", "edge_marketing_off_reminder_still_ok", ["mkt_off"], [], bill=("due", 5))
    g.build("loyalty_candidate", "edge_service_off_offer_still_ok", ["svc_off"], [])
    g.build("consistent", "edge_service_off_offer_still_ok", ["svc_off"], [])
    g.build("consistent", "edge_cooldown_boundary_7d_ok", [], [], last_contact=7)
    g.build("dormant", "edge_cooldown_boundary_7d_ok", [], [], last_contact=7)
    g.build("consistent", "edge_cooldown_boundary_6d_block", ["cooldown:6"], ["cooldown_or_duplicate"])
    g.build("loyalty_candidate", "edge_duplicate_boundary_14d_ok", [], [], last_contact=14, last_type="reward_offer")
    g.build("declining_activity", "edge_duplicate_boundary_14d_ok", [], [], last_contact=14, last_type="reengagement_offer")
    g.build("declining_activity", "edge_duplicate_boundary_13d_block", ["dup:13"], ["cooldown_or_duplicate"])

    g.build("consistent", "edge_last_activity_29d_not_dormant", lad=29, fail="silver", points=500)
    g.build("dormant", "edge_last_activity_30d_dormant", lad=30, act30=0, prev=4)
    g.build("declining_activity", "edge_decline_exactly_70pct", lad=3, prev=50, act30=35)
    g.build("consistent", "edge_decline_72pct_not_declining", lad=3, prev=50, act30=36, fail="silver", points=900)
    g.build("consistent", "edge_low_baseline_prev_9_not_declining", lad=2, prev=9, act30=1, fail="silver", points=100)

    g.build("payment_reminder", "edge_due_today_courteous", bill=("due", 0))
    g.build("payment_reminder", "edge_due_in_7d_courteous", bill=("due", 7))
    g.build("consistent", "edge_due_in_8d_not_yet_reminder", bill=("due_far", 8), fail="short_tenure", tenure=10)
    g.build("payment_reminder", "edge_overdue_1d_stage1", bill=("overdue", 1))
    g.build("payment_reminder", "edge_overdue_15d_stage1", bill=("overdue", 15))
    g.build("payment_reminder", "edge_overdue_16d_stage2", bill=("overdue", 16))
    g.build("payment_reminder", "edge_overdue_30d_stage2", bill=("overdue", 30))
    g.build("payment_reminder", "edge_overdue_31d_stage3_two_unpaid_bills", bill=("overdue", 31))
    g.build("payment_reminder", "edge_overdue_45d_stage3_two_unpaid_bills", bill=("overdue", 45))
    g.build("payment_reminder", "edge_partial_payment", bill=("overdue", 20), partial=True)
    g.build("payment_reminder", "edge_partial_payment", bill=("overdue", 9), partial=True)
    g.build("payment_reminder", "edge_overdue_and_dormant_secondary", bill=("overdue", 12), activity="dormant")
    g.build("payment_reminder", "edge_overdue_and_declining_secondary", bill=("overdue", 6), activity="declining")

    g.build("consistent", "edge_tenure_23_not_loyal", tenure=23, points=6000)
    g.build("loyalty_candidate", "edge_tenure_24_loyal", tenure=24, points=6000, late=0)
    g.build("consistent", "edge_points_1999_silver_not_loyal", tenure=60, points=1999)
    g.build("loyalty_candidate", "edge_points_2000_gold_loyal", tenure=60, points=2000, late=0)
    g.build("loyalty_candidate", "edge_ontime_11_of_12_loyal", plan_type="postpaid", tenure=50, points=9000, late=1)
    g.build("consistent", "edge_ontime_10_of_12_not_loyal", plan_type="postpaid", tenure=50, points=9000, late=2)
    g.build("loyalty_candidate", "edge_prepaid_loyal_no_bills", plan_type="prepaid", tenure=70, points=12000)
    g.build("declining_activity", "edge_declining_primary_loyal_secondary", activity="declining",
            plan_type="postpaid", tenure=40, points=5000, late=0)

    # 4) Offer validator cases (expected offer asserted)
    g.build("loyalty_candidate", "offer_postpaid_t40_gets_bill_credit", plan_type="postpaid", tenure=40, late=0, offer="OFR-RWD-500")
    g.build("loyalty_candidate", "offer_tenure_30_too_short_for_bill_credit", plan_type="postpaid", tenure=30, late=0, offer="OFR-RWD-2GB")
    g.build("loyalty_candidate", "offer_bill_credit_sent_30d_ago_skip", plan_type="postpaid", tenure=60, late=0,
            sent_offer=("OFR-RWD-500", 30), offer="OFR-RWD-2GB")
    g.build("loyalty_candidate", "offer_prepaid_gets_data_gift", plan_type="prepaid", tenure=45, offer="OFR-RWD-2GB")
    g.build("dormant", "offer_prepaid_dormant_gets_cashback", plan_type="prepaid", tenure=20, offer="OFR-REE-PRE")
    g.build("dormant", "offer_postpaid_dormant_skips_expired", plan_type="postpaid", tenure=20, offer="OFR-REE-3GB")
    g.build("declining_activity", "offer_declining_skips_expired_and_future", plan_type="postpaid", tenure=15, offer="OFR-REE-3GB")
    g.build("declining_activity", "offer_none_tenure_2", plan_type="postpaid", tenure=2, offer=None)
    g.build("consistent", "offer_none_appreciation_tenure_4", tenure=4, fail="short_tenure", offer=None)
    g.build("consistent", "offer_appreciation_tenure_6", tenure=6, fail="short_tenure", offer="OFR-APP-1GB")

    # 5) Data-shape edge cases
    g.build("consistent", "edge_missing_first_name_fallback_greeting", no_name=True)
    g.build("payment_reminder", "edge_missing_first_name_fallback_greeting", no_name=True, bill=("overdue", 7))
    g.build("loyalty_candidate", "edge_preferred_language_hi", lang="hi")
    g.build("payment_reminder", "edge_preferred_language_ta", lang="ta", bill=("due", 2))
    g.build("dormant", "edge_preferred_language_bn", lang="bn")
    g.build("consistent", "conflict_future_consent_date", ["conflict:future_consent"], ["data_conflict"])

    # 6) Multiple stop signs at once (first in fixed order is reported)
    g.build("payment_reminder", "multi_closed_bounced_dispute", ["inactive:closed", "bounced", "dispute"],
            ["account_inactive", "email_undeliverable", "dispute_or_complaint_open"], bill=("overdue", 35))
    g.build("loyalty_candidate", "multi_email_off_and_marketing_off", ["email_off", "mkt_off"],
            ["email_not_allowed", "consent_missing"])
    g.build("payment_reminder", "multi_dispute_hardship_cooldown", ["dispute", "hardship", "cooldown:2"],
            ["dispute_or_complaint_open", "payment_arrangement_or_hardship", "cooldown_or_duplicate"], bill=("overdue", 19))
    g.build("payment_reminder", "multi_conflict_and_duplicate", ["conflict:overdue_fully_paid", "dup:9"],
            ["data_conflict", "cooldown_or_duplicate"], bill=("overdue", 14))
    g.build("consistent", "multi_no_email_and_complaint", ["no_email", "complaint"],
            ["email_undeliverable", "dispute_or_complaint_open"])
    g.build("payment_reminder", "multi_suspended_and_arrangement", ["inactive:suspended", "arrangement"],
            ["account_inactive", "payment_arrangement_or_hardship"], bill=("overdue", 28))


# ----------------------------------------------------------------------------
# Writers
# ----------------------------------------------------------------------------
def fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def write(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r.get(c)) for c in cols])


CUSTOMER_COLS = ["customer_id", "first_name", "email_address", "snapshot_date", "tenure_months", "plan_type",
                 "plan_id", "plan_price", "account_status", "preferred_language", "activity_unit",
                 "last_activity_days", "activity_30d", "activity_prev_30d", "loyalty_points", "loyalty_tier",
                 "loyalty_points_expiry_date", "on_time_payments_last_12", "bills_issued_last_12",
                 "date_of_birth", "gender", "home_address", "phone", "national_id_last4", "credit_score"]
BILL_COLS = ["bill_id", "customer_id", "bill_status", "amount_due", "amount_paid", "currency", "due_date",
             "last_payment_date", "autopay_enabled", "dispute_open", "dispute_opened_date",
             "payment_arrangement_active", "hardship_flag"]
CONSENT_COLS = ["customer_id", "email_allowed", "marketing_consent", "service_consent", "consent_updated_at",
                "email_status", "open_complaint"]
MSG_COLS = ["message_id", "customer_id", "sent_at", "channel", "message_type", "segment", "template_id",
            "offer_id", "bill_id", "outcome"]
OFFER_COLS = ["offer_id", "offer_name", "message_type", "eligible_segments", "plan_type", "min_tenure_months",
              "channel", "value", "value_unit", "terms", "valid_from", "expiry_date", "priority"]
TRUTH_COLS = ["customer_id", "scenario_tag", "expected_segment", "expected_all_segments", "expected_reason_code",
              "expected_outcome", "expected_block_reason", "expected_all_block_reasons", "expected_data_conflicts",
              "expected_message_type", "expected_strategy", "expected_target_bill_id", "expected_overdue_days",
              "expected_amount_outstanding", "expected_total_outstanding", "expected_offer_id",
              "expected_greeting_name", "human_review_required"]


def main():
    g = Gen()
    plan(g)
    # renumber messages chronologically for readability
    g.msgs.sort(key=lambda m: (m["sent_at"], m["customer_id"]))
    for i, m in enumerate(g.msgs, 1):
        m["message_id"] = f"M-{i:05d}"
    os.makedirs(OUT, exist_ok=True)
    write(f"{OUT}/customers.csv", g.customers, CUSTOMER_COLS)
    write(f"{OUT}/billing.csv", g.bills, BILL_COLS)
    write(f"{OUT}/consent.csv", g.consent, CONSENT_COLS)
    write(f"{OUT}/contact_history.csv", g.msgs, MSG_COLS)
    write(f"{OUT}/offer_catalog.csv", OFFERS, OFFER_COLS)
    write(f"{OUT}/ground_truth.csv", g.truth, TRUTH_COLS)
    print(f"customers={len(g.customers)} bills={len(g.bills)} messages={len(g.msgs)} -> {OUT}/")


if __name__ == "__main__":
    main()
