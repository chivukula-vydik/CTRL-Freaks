"""Evaluation summary for the review console: the deterministic pipeline (steps 1-5) against
data/dataset/ground_truth.csv, plus live review stats from the drafts and outbox tables.
The answer key is read here only; it never reaches the pipeline. eval/ and data/ are not deployed on Vercel."""
import collections
import json
import re
from functools import lru_cache

from app import db, engage, policy
from app.domain import engage as D


@lru_cache(maxsize=1)
def _answer_key() -> dict:
    from eval import groundtruth as gt
    key = gt.load()
    per = collections.Counter()
    cm = collections.Counter()
    blocked = refused = 0
    pre = D.preload()   # 5 queries instead of ~5 per customer
    for cid, g in key.items():
        d = engage.decide(cid, pre=pre)
        mm = gt.mismatches(d, g)
        for k in gt.FIELDS:
            per[k] += k not in mm
        cm[(g["expected_segment"], d["seg"]["primary"])] += 1
        if g["expected_outcome"] == "blocked":
            blocked += 1
            refused += bool(d["blocks"])
    labels = policy.policy()["segmentation"]["order"]
    n = len(key)
    return {"sampleSize": n, "accuracy": {"correct": per["segment"], "total": n},
            "safetyRefusals": {"refused": refused, "total": blocked}, "labels": labels,
            "confusion": [[cm[(e, p)] for p in labels] for e in labels],
            "scenarios": [{"name": k.replace("_", " "), "result": f"{per[k]}/{n}", "ok": per[k] == n} for k in gt.FIELDS]}


def summary() -> dict:
    try:
        out = dict(_answer_key())
    except (ImportError, FileNotFoundError) as e:
        raise engage.Refused(404, f"answer key not available here: {e}")
    drafts = db.q("SELECT status, checks, edited, review_note, body FROM drafts")
    written = [d for d in drafts if d["body"]]
    checks = [json.loads(d["checks"] or "{}") for d in written]
    caught = sum(any(w["code"] == "AI_DRAFT_REJECTED" for w in c.get("warnings", [])) for c in checks)
    sent = db.q("SELECT d.checks FROM outbox o JOIN drafts d ON d.draft_id = o.draft_id")
    scores = [v for d in drafts for m in re.findall(r"\[rubric (\{.*?\})\]", d["review_note"] or "")
              for v in json.loads(m).values() if isinstance(v, (int, float)) and v > 0]
    out.update(
        grounded={"matched": sum(bool(c.get("passed")) for c in checks), "total": len(written), "caughtPreReview": caught},
        complianceAtSend=(sum(bool(json.loads(s["checks"] or "{}").get("passed")) for s in sent) / len(sent)) if sent else 1.0,
        rubricAverage=round(sum(scores) / len(scores), 1) if scores else 0,
        edits=sum(d["edited"] == "Y" for d in drafts), rejections=sum(d["status"] == "rejected" for d in drafts))
    return out
