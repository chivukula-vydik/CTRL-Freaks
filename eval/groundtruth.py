"""Compare the pipeline's deterministic steps with data/dataset/ground_truth.csv (the answer key).
The key is evaluation-only: it is never passed to the pipeline."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["segment", "all_segments", "reason", "outcome", "block", "all_blocks", "message_type", "strategy", "offer",
          "bill", "overdue_days", "amount", "total", "conflicts", "greeting", "human_review"]


def load(path: Path | None = None) -> dict[str, dict]:
    path = path or ROOT / "data" / "dataset" / "ground_truth.csv"
    return {r["customer_id"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}


def got(d: dict) -> dict:
    """What the pipeline decided, in the answer key's vocabulary. d = engage.decide(...)."""
    seg, st, blocks, offer = d["seg"], d["strategy"], d["blocks"], d["offer"]
    return {
        "segment": seg["primary"], "all_segments": "|".join(s["segment"] for s in seg["segments"]),
        "reason": seg["segments"][0]["reasons"][0], "outcome": "blocked" if blocks else "draft",
        "block": blocks[0]["code"] if blocks else "", "all_blocks": "|".join(b["code"] for b in blocks),
        "message_type": st["message_type"], "strategy": st["name"], "offer": offer["offer_id"] if offer else "",
        "bill": st.get("target_bill_id", ""), "overdue_days": str(st.get("overdue_days", "")),
        "amount": st.get("amount_outstanding", ""), "total": st.get("total_outstanding", ""),
        "conflicts": "|".join(d["ctx"]["conflicts"]), "greeting": d["facts"]["first_name"],
        "human_review": str(st["human_review_required"]).lower(),
    }


def expected(g: dict) -> dict:
    return {"segment": g["expected_segment"], "all_segments": g["expected_all_segments"],
            "reason": g["expected_reason_code"], "outcome": g["expected_outcome"], "block": g["expected_block_reason"],
            "all_blocks": g["expected_all_block_reasons"], "message_type": g["expected_message_type"],
            "strategy": g["expected_strategy"], "offer": g["expected_offer_id"], "bill": g["expected_target_bill_id"],
            "overdue_days": g["expected_overdue_days"], "amount": g["expected_amount_outstanding"],
            "total": g["expected_total_outstanding"], "conflicts": g["expected_data_conflicts"],
            "greeting": g["expected_greeting_name"], "human_review": g["human_review_required"]}


def _same(k: str, a: str, b: str) -> bool:
    if k in ("amount", "total") and a and b:
        return f"{float(a):.2f}" == f"{float(b):.2f}"
    return a == b


def mismatches(d: dict, g: dict) -> dict[str, tuple[str, str]]:
    a, e = got(d), expected(g)
    return {k: (a[k], e[k]) for k in FIELDS if not _same(k, a[k], e[k])}
