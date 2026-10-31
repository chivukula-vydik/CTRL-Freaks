#!/usr/bin/env python3
"""
Independent validator. Re-implements the rules with pandas (no code shared with
the generator) and checks schema, integrity, internal consistency and that
ground_truth.csv agrees with the data.

Usage: python3 validate_dataset.py [dataset_dir]
"""
import sys
import re
import pandas as pd

DIR = sys.argv[1] if len(sys.argv) > 1 else "dataset"
SNAP = pd.Timestamp("2026-10-27")
errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


rd = lambda n: pd.read_csv(f"{DIR}/{n}.csv", dtype=str, keep_default_na=False)
cu, bi, co, mh, of, gt = (rd(n) for n in ["customers", "billing", "consent", "contact_history",
                                          "offer_catalog", "ground_truth"])

# ---------- keys
for df, k, n in [(cu, "customer_id", "customers"), (bi, "bill_id", "billing"), (co, "customer_id", "consent"),
                 (mh, "message_id", "contact_history"), (of, "offer_id", "offer_catalog"),
                 (gt, "customer_id", "ground_truth")]:
    check(df[k].is_unique, f"{n}.{k} not unique")
    check((df[k] != "").all(), f"{n}.{k} has blanks")
ids = set(cu.customer_id)
for df, n in [(bi, "billing"), (co, "consent"), (mh, "contact_history"), (gt, "ground_truth")]:
    check(set(df.customer_id) <= ids, f"{n}.customer_id FK broken")
check(set(co.customer_id) == ids and set(gt.customer_id) == ids, "consent/ground_truth must cover every customer")
check(set(mh.bill_id[mh.bill_id != ""]) <= set(bi.bill_id), "contact_history.bill_id FK broken")
check(set(mh.offer_id[mh.offer_id != ""]) <= set(of.offer_id), "contact_history.offer_id FK broken")
# a message's bill must belong to the same customer
mb = mh[mh.bill_id != ""].merge(bi[["bill_id", "customer_id"]], on="bill_id", suffixes=("", "_b"))
check((mb.customer_id == mb.customer_id_b).all(), "message references another customer's bill")

# ---------- enums / formats
enum = [
    (cu, "plan_type", {"prepaid", "postpaid"}), (cu, "account_status", {"active", "suspended", "closed"}),
    (cu, "loyalty_tier", {"Silver", "Gold", "Platinum"}), (bi, "bill_status", {"paid", "due", "overdue"}),
    (co, "email_status", {"valid", "bounced", "unverified"}), (mh, "channel", {"email", "sms"}),
    (mh, "outcome", {"delivered", "opened", "bounced", "complained"}),
    (mh, "message_type", {"appreciation", "reward_offer", "reengagement_offer", "payment_reminder", "overdue_notice"}),
]
for df, col, allowed in enum:
    bad = set(df[col]) - allowed
    check(not bad, f"{col} has invalid values {bad}")
for df, cols in [(bi, ["autopay_enabled", "dispute_open", "payment_arrangement_active", "hardship_flag"]),
                 (co, ["email_allowed", "marketing_consent", "service_consent", "open_complaint"])]:
    for c in cols:
        check(set(df[c]) <= {"true", "false"}, f"{c} not boolean")
money = re.compile(r"^\d+\.\d{2}$")
for col in ["amount_due", "amount_paid"]:
    check(bi[col].str.match(money).all(), f"billing.{col} not DECIMAL(10,2)")
check(cu.plan_price.str.match(money).all(), "plan_price not DECIMAL(10,2)")
check(cu.national_id_last4.str.match(r"^\d{4}$").all(), "national_id_last4 must be 4 chars (leading zeros kept)")
check(cu.phone.str.match(r"^\+91\d{10}$").all(), "phone not E.164")
check(cu.customer_id.str.match(r"^C\d{4}$").all(), "customer_id format")
check((cu.snapshot_date == "2026-10-27").all(), "snapshot_date differs")
check(cu.preferred_language.str.match(r"^[a-z]{2}$").all(), "preferred_language not ISO 639-1")
check(cu.email_address[cu.email_address != ""].str.endswith("@example.test").all(), "non-synthetic email domain")

# ---------- types
for col in ["tenure_months", "last_activity_days", "activity_30d", "activity_prev_30d", "loyalty_points",
            "on_time_payments_last_12", "bills_issued_last_12", "credit_score"]:
    cu[col] = cu[col].astype(int)
for col in ["amount_due", "amount_paid"]:
    bi[col] = bi[col].astype(float)
for df, cols in [(bi, ["due_date", "last_payment_date", "dispute_opened_date"]), (mh, ["sent_at"]),
                 (co, ["consent_updated_at"])]:
    for c in cols:
        df[c] = pd.to_datetime(df[c].replace("", None))
tf = lambda s: s == "true"

# ---------- independent rule re-implementation
bi["unpaid"] = bi.bill_status.isin(["due", "overdue"])
act = bi[bi.unpaid & (bi.due_date <= SNAP + pd.Timedelta(days=7))].sort_values("due_date")
tbill = act.groupby("customer_id").first()


def tier(p):
    return "Silver" if p < 2000 else "Gold" if p < 8000 else "Platinum"


rows = []
for _, c in cu.iterrows():
    cid = c.customer_id
    b = bi[bi.customer_id == cid]
    m = mh[mh.customer_id == cid]
    k = co[co.customer_id == cid].iloc[0]
    segs = []
    if cid in tbill.index:
        segs.append("payment_reminder")
    if c.last_activity_days >= 30:
        segs.append("dormant")
    if c.activity_prev_30d >= 10 and c.activity_30d * 10 <= c.activity_prev_30d * 7:
        segs.append("declining_activity")
    if c.tenure_months >= 24 and c.loyalty_tier in ("Gold", "Platinum") and (
            c.plan_type == "prepaid" or (c.bills_issued_last_12 >= 6 and
                                         c.on_time_payments_last_12 * 10 >= c.bills_issued_last_12 * 9)):
        segs.append("loyalty_candidate")
    segs = segs or ["consistent"]
    p = segs[0]
    if p == "payment_reminder":
        od = (SNAP - tbill.loc[cid, "due_date"]).days
        mt = "payment_reminder" if od <= 0 else "overdue_notice"
    else:
        od = None
        mt = {"consistent": "appreciation", "loyalty_candidate": "reward_offer"}.get(p, "reengagement_offer")
    # conflicts
    ontime = ((b.bill_status == "paid") & (b.last_payment_date <= b.due_date)).sum()
    conflict = (
        ((b.bill_status == "paid") & (b.amount_paid != b.amount_due)).any()
        or ((b.bill_status == "paid") & b.last_payment_date.isna()).any()
        or (b.unpaid & (b.amount_paid >= b.amount_due)).any()
        or ((b.bill_status == "overdue") & (b.due_date >= SNAP)).any()
        or ((b.bill_status == "due") & (b.due_date < SNAP)).any()
        or (b.currency == "").any()
        or (c.last_activity_days >= 30 and c.activity_30d > 0)
        or c.loyalty_tier != tier(c.loyalty_points)
        or (c.plan_type == "postpaid" and (c.bills_issued_last_12 != len(b) or c.on_time_payments_last_12 != ontime))
        or k.consent_updated_at > SNAP)
    days = (SNAP - m.sent_at).dt.days
    blocks = [name for name, hit in [
        ("account_inactive", c.account_status != "active"),
        ("data_conflict", conflict),
        ("email_not_allowed", not tf(k.email_allowed)),
        ("consent_missing", not tf(k.service_consent if p == "payment_reminder" else k.marketing_consent)),
        ("email_undeliverable", c.email_address == "" or k.email_status != "valid"),
        ("dispute_or_complaint_open", tf(k.open_complaint) or tf(b.dispute_open).any()),
        ("payment_arrangement_or_hardship", p == "payment_reminder" and
         (b.unpaid & (tf(b.payment_arrangement_active) | tf(b.hardship_flag))).any()),
        ("cooldown_or_duplicate", (days < 7).any() or ((m.message_type == mt) & (days < 14)).any()),
    ] if hit]
    rows.append(dict(customer_id=cid, seg=p, segs="|".join(segs), od="" if od is None else str(od), mt=mt,
                     blocks="|".join(blocks)))

    # consistency checks that are not rules
    check((m.sent_at <= SNAP).all(), f"{cid}: message in the future")
    check((m.sent_at >= SNAP - pd.Timedelta(days=30 * c.tenure_months)).all(), f"{cid}: message before tenure start")
    em = m[m.channel == "email"]
    if k.email_status == "bounced":
        check(not em.empty and em.sort_values("sent_at").iloc[-1].outcome == "bounced",
              f"{cid}: bounced status but latest email not bounced")
    else:
        check((m.outcome != "bounced").all(), f"{cid}: bounced outcome but email_status={k.email_status}")
    if k.email_status == "unverified" or c.email_address == "":
        check(em.empty, f"{cid}: email sent to unverified/missing address")
    if c.plan_type == "prepaid":
        check(b.empty, f"{cid}: prepaid customer has bills")
    check(c.bills_issued_last_12 <= 12 and c.on_time_payments_last_12 <= c.bills_issued_last_12,
          f"{cid}: payment counts out of range")
    check((b.last_payment_date.dropna() <= SNAP).all(), f"{cid}: payment date in the future")
    pm = m[m.message_type.isin(["payment_reminder", "overdue_notice"])].merge(
        b[["bill_id", "due_date", "last_payment_date"]], on="bill_id")
    check((pm.bill_id.notna()).all() and len(pm) == (m.message_type.isin(["payment_reminder", "overdue_notice"])).sum(),
          f"{cid}: payment message without a valid bill")
    check(((pm.last_payment_date.isna()) | (pm.last_payment_date > pm.sent_at)).all(),
          f"{cid}: payment message sent after the bill was paid")
    check((pm[pm.message_type == "overdue_notice"].sent_at > pm[pm.message_type == "overdue_notice"].due_date).all(),
          f"{cid}: overdue notice sent before due date")

chk = pd.DataFrame(rows).merge(gt, on="customer_id")
for _, r in chk.iterrows():
    check(r.seg == r.expected_segment, f"{r.customer_id}: segment {r.seg} != truth {r.expected_segment}")
    check(r.segs == r.expected_all_segments, f"{r.customer_id}: all segments mismatch")
    check(r.blocks == r.expected_all_block_reasons, f"{r.customer_id}: blocks {r.blocks} != {r.expected_all_block_reasons}")
    check(r.od == r.expected_overdue_days, f"{r.customer_id}: overdue days mismatch")
    check(r.mt == r.expected_message_type, f"{r.customer_id}: message type mismatch")
    check((r.expected_outcome == "blocked") == bool(r.blocks), f"{r.customer_id}: outcome mismatch")
    if r.expected_outcome == "blocked":
        check(r.expected_offer_id == "", f"{r.customer_id}: blocked but offer set")

# ---------- report
print(f"customers {len(cu)} | bills {len(bi)} | messages {len(mh)} | offers {len(of)}")
print("\nPrimary segment x outcome")
print(pd.crosstab(gt.expected_segment, gt.expected_outcome, margins=True).to_string())
print("\nBlock reasons (any position)")
print(gt.expected_all_block_reasons[gt.expected_all_block_reasons != ""].str.split("|").explode()
      .value_counts().to_string())
print("\nPayment strategies")
print(gt.expected_strategy[gt.expected_segment == "payment_reminder"].value_counts().to_string())
print("\nOffers chosen (draft only)")
print(gt.expected_offer_id.replace("", "(none)")[gt.expected_outcome == "draft"].value_counts().to_string())
print("\nPlan type:", cu.plan_type.value_counts().to_dict(), "| language:", cu.preferred_language.value_counts().to_dict())
print(f"\n{'PASS' if not errors else 'FAIL'}: {len(errors)} problems")
for e in errors[:40]:
    print(" -", e)
sys.exit(1 if errors else 0)
