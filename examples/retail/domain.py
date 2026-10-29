"""Worked example: retail support agent (the published HCL problem). Run with DOMAIN=retail.

Shows every part of a domain: schema, identity config, intents, PLAN, rule parameters,
@tool functions and validations. Copy patterns from here into your own domain.
"""
import calendar
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.domain.base import Domain, Understanding, action, tool


def _money(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class Retail(Domain):
    name = "retail"

    SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
  customer_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('STANDARD','GOLD','PLATINUM')), city TEXT, joined_year INTEGER);
CREATE TABLE IF NOT EXISTS products (
  sku TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  price REAL NOT NULL CHECK (price > 0), warranty_months INTEGER NOT NULL DEFAULT 0 CHECK (warranty_months >= 0));
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  order_date TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('PLACED','SHIPPED','DELIVERED','CANCELLED')),
  payment_method TEXT CHECK (payment_method IN ('UPI','CARD','COD')), delivery_note TEXT);
CREATE TABLE IF NOT EXISTS order_items (
  order_id TEXT NOT NULL REFERENCES orders(order_id), sku TEXT NOT NULL REFERENCES products(sku),
  qty INTEGER NOT NULL CHECK (qty >= 1), net_unit_price REAL NOT NULL CHECK (net_unit_price > 0),
  delivered_on TEXT, PRIMARY KEY (order_id, sku));
CREATE TABLE IF NOT EXISTS returns (
  return_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
  sku TEXT NOT NULL REFERENCES products(sku), requested_on TEXT NOT NULL,
  reason TEXT CHECK (reason IN ('DEFECTIVE','DAMAGED','WRONG_ITEM','CHANGED_MIND')),
  status TEXT CHECK (status IN ('REQUESTED','PICKED_UP','REFUNDED','REJECTED')), refund_amount REAL);
"""
    VALIDATIONS = [
        ("delivered_on set but order not DELIVERED", "SELECT oi.order_id, oi.sku FROM order_items oi JOIN orders o "
         "USING(order_id) WHERE oi.delivered_on IS NOT NULL AND o.status != 'DELIVERED'"),
        ("DELIVERED without delivered_on", "SELECT oi.order_id, oi.sku FROM order_items oi JOIN orders o "
         "USING(order_id) WHERE oi.delivered_on IS NULL AND o.status = 'DELIVERED'"),
        ("delivered_on before order_date", "SELECT oi.order_id, oi.sku FROM order_items oi JOIN orders o "
         "USING(order_id) WHERE oi.delivered_on < o.order_date"),
        ("net price above list price", "SELECT oi.order_id, oi.sku FROM order_items oi JOIN products p USING(sku) "
         "WHERE oi.net_unit_price > p.price"),
        ("qty < 1", "SELECT order_id, sku FROM order_items WHERE qty < 1"),
        ("return refers to missing item", "SELECT r.return_id, r.order_id FROM returns r LEFT JOIN order_items oi "
         "ON oi.order_id = r.order_id AND oi.sku = r.sku WHERE oi.order_id IS NULL"),
        ("reserved customer id", "SELECT customer_id FROM customers WHERE customer_id BETWEEN 'C9000' AND 'C9999'"),
        ("reserved sku", "SELECT sku FROM products WHERE sku LIKE 'SKU-JDG%'"),
        ("reserved order id", "SELECT order_id FROM orders WHERE order_id >= 'O-900000'"),
    ]

    SUBJECT_ID = re.compile(r"\bC\d{4}\b", re.I)
    SUBJECT_TABLE, SUBJECT_KEY, SUBJECT_TIER_COL = "customers", "customer_id", "tier"
    RECORD_ID = re.compile(r"\bO-\d{6}\b", re.I)
    RECORD_TABLE, RECORD_KEY, RECORD_SUBJECT_COL = "orders", "order_id", "customer_id"

    TARGETS_SQL = """SELECT oi.order_id, oi.sku, oi.qty, oi.net_unit_price, oi.delivered_on, o.status,
                     o.order_date, p.name, p.category, p.warranty_months
                     FROM order_items oi JOIN orders o USING(order_id) JOIN products p USING(sku)
                     WHERE o.customer_id = :sid ORDER BY o.order_date DESC"""
    TARGET_ID_COLS = ["order_id", "sku"]
    TARGET_NAME_COL, TARGET_CATEGORY_COL = "name", "category"

    INTENT_WORDS = {
        "order_status": [r"where is", r"\bstatus\b", r"\btrack", r"when will .* (arrive|deliver)", r"has .* shipped"],
        "return_eligibility": [r"can i return", r"\breturn (it|them|this|my|the)\b", r"eligib",
                               r"send (it|them)? ?back", r"exchange"],
        "refund": [r"how much .*refund", r"refund amount", r"how much .* (get|back)", r"money back",
                   r"refund (for|on) (my|the|this|order)"],
        "warranty": [r"warrant", r"stopped working", r"not working", r"\brepair", r"guarantee"],
        "raise_return": [r"(raise|initiate|start|create|place|file|book) (a |the )?return", r"return request"],
    }
    PERSONAL_INTENTS = set(INTENT_WORDS)
    PLAN = {"order_status": ["lookup_order"], "return_eligibility": ["check_return_eligibility"],
            "refund": ["check_return_eligibility"], "warranty": ["check_warranty"],
            "raise_return": ["raise_return"]}
    CATEGORY_WORDS = {
        "ELECTRONICS": ["electronic", "laptop", "phone", "mobile", "headphone", "earbud", "tv", "television",
                        "camera", "tablet", "speaker", "smartwatch", "charger", "monitor"],
        "FASHION": ["fashion", "cloth", "shirt", "jean", "dress", "shoe", "sneaker", "jacket", "kurta", "apparel"],
        "HOME": ["home", "furniture", "kitchen", "cookware", "mattress", "lamp", "bedsheet", "mixer"],
        "BEAUTY": ["beauty", "cosmetic", "makeup", "lipstick", "cream", "perfume", "shampoo", "skincare"],
        "GROCERY": ["grocery", "groceries", "food", "rice", "atta", "oil", "snack", "perishable"],
    }
    TIERS = ["STANDARD", "GOLD", "PLATINUM"]

    PARAMETERS = ["return_window_days", "returnable", "restocking_fee_pct", "reverse_shipping_fee",
                  "defect_fee_waiver", "auto_refund_limit"]
    PARAM_QUERIES = {
        "return_window_days": [r"return (window|period|policy)", r"how (many|long).*(days|time).*return",
                               r"(how many days|how long).*(return|send (it |them )?back)",
                               r"days.*(to )?return", r"return.*within"],
        "restocking_fee_pct": [r"restocking", r"return fee", r"deduct"],
        "reverse_shipping_fee": [r"(reverse|return) (shipping|pickup) (fee|charge|cost)"],
        "auto_refund_limit": [r"(approval|auto.?refund) limit", r"refund.*(above|over).*approv"],
        "returnable": [r"(non.?returnable|can(not|'t) be returned|which .* returnable)"],
    }
    PARAM_UNIT = {"return_window_days": "{v} days", "restocking_fee_pct": "{v}% of the price paid",
                  "reverse_shipping_fee": "Rs {v}", "auto_refund_limit": "Rs {v}",
                  "returnable": "{v} (1 = returnable, 0 = not returnable)"}

    REASONS = [("DEFECTIVE", r"stopped working|not working|defect|faulty|broken|doesn't work|dead"),
               ("DAMAGED", r"damaged|cracked|dent"), ("WRONG_ITEM", r"wrong (item|product|size|colou?r)")]

    # ---------------- understanding hooks ----------------
    def understand(self, question, subject_id):
        und = super().understand(question, subject_id)
        if "raise_return" in und.intents and "return_eligibility" in und.intents:
            und.intents.remove("return_eligibility")
        if und.record_ids and not und.intents:
            und.intents = ["order_status"]
        return und

    def enrich(self, question: str, und: Understanding) -> None:
        for code, pat in self.REASONS:
            if re.search(pat, question, re.I):
                und.extra["reason"] = code
                return
        und.extra["reason"] = "CHANGED_MIND"
        if set(und.intents) & {"refund", "raise_return", "return_eligibility"}:
            und.assumptions.append("Reason not stated: assuming change of mind.")

    def record_level(self, intent: str) -> bool:
        return intent == "order_status"

    def describe_target(self, t: dict) -> str:
        return f"{t['name']} in order {t['order_id']} ({t['order_date']})"

    # ---------------- tools: pure code, thresholds from ctx.rule() ----------------
    def _item(self, ctx, oid=None, sku=None):
        return ctx.q1("""SELECT oi.*, o.status, o.customer_id, p.name, p.category, p.warranty_months
                         FROM order_items oi JOIN orders o USING(order_id) JOIN products p USING(sku)
                         WHERE oi.order_id = ? AND oi.sku = ? AND o.customer_id = ?""",
                      (oid or ctx.target["order_id"], sku or ctx.target["sku"], ctx.sid))

    @tool
    def lookup_order(self, ctx):
        o = ctx.q1("SELECT * FROM orders WHERE order_id = ? AND customer_id = ?", (ctx.target["order_id"], ctx.sid))
        if not o:
            return {"result": "NOT_FOUND_FOR_CUSTOMER"}
        items = ctx.q("""SELECT oi.sku, p.name, oi.qty, oi.net_unit_price, oi.delivered_on FROM order_items oi
                         JOIN products p USING(sku) WHERE oi.order_id = ?""", (o["order_id"],))
        d = [i["delivered_on"] for i in items if i["delivered_on"]]
        # delivery_note is untrusted (R8): never returned, never acted on
        return {"result": "FOUND", "order_id": o["order_id"], "status": o["status"], "order_date": o["order_date"],
                "items": items, "delivery_note_present": bool(o.get("delivery_note")),
                "_say": f"Order {o['order_id']} is {o['status']}" + (f", delivered on {d[0]}." if d else ".")}

    @tool
    def check_return_eligibility(self, ctx):
        it = self._item(ctx)
        if not it:
            return {"result": "NOT_FOUND_FOR_CUSTOMER"}
        warranty_next = ["check_warranty"] if it["warranty_months"] else []
        if ctx.rule("returnable", default="1", quiet=True).strip() in {"0", "N", "false"}:
            return {"result": "NOT_RETURNABLE_CATEGORY", "category": it["category"],
                    "_say": f"Items in {it['category']} are not returnable.", "_next": warranty_next}
        if it["status"] != "DELIVERED" or not it["delivered_on"]:
            return {"result": "NOT_DELIVERED", "order_status": it["status"],
                    "_say": f"The order is not delivered yet (status {it['status']}), so a return cannot start."}
        ex = ctx.q1("SELECT return_id, status FROM returns WHERE order_id = ? AND sku = ? AND status != 'REJECTED'",
                    (it["order_id"], it["sku"]))
        if ex:
            return {"result": "ALREADY_RETURNED", "return_id": ex["return_id"], "return_status": ex["status"],
                    "_say": f"A return already exists for this item ({ex['return_id']}, {ex['status']})."}
        window = int(float(ctx.rule("return_window_days")))
        delivered = date.fromisoformat(it["delivered_on"])
        days = ctx.und.what_if.get("days", (ctx.as_of - delivered).days)
        out = {"result": "ELIGIBLE" if days <= window else "WINDOW_EXPIRED", "days_since_delivery": days,
               "window_days": window, "category": it["category"], "tier": ctx.tier,
               "delivered_on": it["delivered_on"], "last_return_date": (delivered + timedelta(days=window)).isoformat()}
        if out["result"] == "ELIGIBLE":
            out["_say"] = (f"Yes, you can return the {it['name']}: {days} days since delivery, within the "
                           f"{window}-day window (last day {out['last_return_date']}).")
            out["_next"] = ["calculate_refund"] if ctx.wants("refund", "return_eligibility") else []
        else:
            out["_say"] = f"No, the {window}-day return window has passed ({days} days since delivery)."
            out["_next"] = warranty_next
        return out

    def _refund(self, ctx, it, reason):
        gross = Decimal(str(it["net_unit_price"])) * it["qty"]  # net price, after coupons
        waived = reason != "CHANGED_MIND" and ctx.rule("defect_fee_waiver", default="1", quiet=True).strip() == "1"
        fee_pct = Decimal("0") if waived else Decimal(ctx.rule("restocking_fee_pct", default="0"))
        ship = Decimal("0") if waived else Decimal(ctx.rule("reverse_shipping_fee", default="0"))
        fee = gross * fee_pct / 100
        refund = max(Decimal("0"), gross - fee - ship)
        limit = Decimal(ctx.rule("auto_refund_limit", default="1e12"))
        return {"result": "CALCULATED", "gross_amount": _money(gross), "restocking_fee_pct": float(fee_pct),
                "restocking_fee": _money(fee), "reverse_shipping_fee": _money(ship), "refund_amount": _money(refund),
                "reason": reason, "fees_waived": waived, "requires_human_approval": refund > limit}

    @tool
    def calculate_refund(self, ctx):
        it = self._item(ctx)
        if not it:
            return {"result": "NOT_FOUND_FOR_CUSTOMER"}
        r = self._refund(ctx, it, ctx.und.extra.get("reason", "CHANGED_MIND"))
        r["_say"] = (f"Your refund would be Rs {r['refund_amount']:.2f} (price Rs {r['gross_amount']:.2f} - restocking "
                     f"fee Rs {r['restocking_fee']:.2f} - return shipping Rs {r['reverse_shipping_fee']:.2f})."
                     + (" This refund is above the automatic limit and needs human approval."
                        if r["requires_human_approval"] else ""))
        return r

    @tool
    def check_warranty(self, ctx):
        it = self._item(ctx)
        if not it:
            return {"result": "NOT_FOUND_FOR_CUSTOMER"}
        months = int(it["warranty_months"] or 0)
        if months == 0:
            return {"result": "NO_WARRANTY", "_say": "This product has no warranty."}
        if not it["delivered_on"]:
            return {"result": "NOT_DELIVERED", "warranty_months": months}
        end = _add_months(date.fromisoformat(it["delivered_on"]), months)
        if ctx.as_of <= end:
            return {"result": "VALID", "warranty_months": months, "warranty_end": end.isoformat(),
                    "_say": f"It is under warranty until {end.isoformat()}, so you can raise a warranty claim.",
                    "_followup": "how to raise a warranty claim steps"}
        return {"result": "EXPIRED", "warranty_months": months, "warranty_end": end.isoformat(),
                "_say": f"The warranty expired on {end.isoformat()}."}

    @action(risk="low")  # medium would ask the user to confirm first; high would wait for staff
    def raise_return(self, ctx):
        """State-changing: re-checks eligibility itself and is idempotent (safe to call twice)."""
        it = self._item(ctx)
        if not it:
            return {"result": "NOT_FOUND_FOR_CUSTOMER"}
        ex = ctx.q1("SELECT return_id, status FROM returns WHERE order_id = ? AND sku = ? AND status != 'REJECTED'",
                    (it["order_id"], it["sku"]))
        if ex:
            return {"result": "ALREADY_EXISTS", "return_id": ex["return_id"], "status": ex["status"],
                    "_say": f"A return already exists for this item ({ex['return_id']}, {ex['status']})."}
        elig = self.check_return_eligibility(ctx)
        if elig["result"] != "ELIGIBLE":
            return {"result": "NOT_RAISED", "eligibility": elig["result"], "_say": elig.get("_say", "")}
        reason = ctx.und.extra.get("reason", "CHANGED_MIND")
        ref = self._refund(ctx, it, reason)
        n = (ctx.q1("SELECT COUNT(*) AS n FROM returns")["n"] or 0) + 1
        while ctx.q1("SELECT 1 FROM returns WHERE return_id = ?", (f"R-{n:06d}",)):
            n += 1
        rid = f"R-{n:06d}"
        # returns has no customer column, so ownership is proven through orders (:sid is bound by ctx)
        ctx.execute("""INSERT INTO returns (return_id, order_id, sku, requested_on, reason, status, refund_amount)
                       SELECT :rid, order_id, :sku, :d, :reason, 'REQUESTED', :amt FROM orders
                       WHERE order_id = :oid AND customer_id = :sid""",
                    {"rid": rid, "sku": it["sku"], "d": ctx.as_of.isoformat(), "reason": reason,
                     "amt": ref["refund_amount"], "oid": it["order_id"]})
        return {"result": "RAISED", "return_id": rid, "refund_amount": ref["refund_amount"],
                "requires_human_approval": ref["requires_human_approval"],
                "_say": f"Return {rid} raised; expected refund Rs {ref['refund_amount']:.2f}"
                        + (" (needs human approval)." if ref["requires_human_approval"] else ".")}


DOMAIN = Retail()
