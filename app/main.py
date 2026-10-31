"""FastAPI surface. Endpoint paths and fields follow the HCL contract; rename here if the day's doc differs."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from app import config, db, engage, evaluation, llm, policy
from app.domain import DOMAIN

SUBJECT_HEADER = os.getenv("SUBJECT_HEADER", "X-Customer-Id")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="UC5 Engagement Assistant", version="0.2.0", lifespan=lifespan)


def subject(request: Request) -> str | None:
    v = request.headers.get(SUBJECT_HEADER)
    return v.strip().upper() if v and v.strip() else None


def _is_admin(key: str | None) -> bool:
    return bool(config.ADMIN_KEY) and key == config.ADMIN_KEY   # no key configured = nobody is admin


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if not _is_admin(x_admin_key):
        raise HTTPException(403, "admin key required")


@app.get("/health")
def health():
    sql = {"status": "ok" if db.ping() else "down"}
    lm = llm.health()
    ok = sql["status"] == "ok" and lm["status"] in {"ok", "mock"}
    return {"status": "ok" if ok else "degraded", "database": sql, "llm": lm, "domain": DOMAIN.name}


@app.get("/audit", dependencies=[Depends(require_admin)])
def audit_recent(limit: int = 200):
    """Newest audit rows across all requests, for the console's audit log (evidence left out)."""
    return engage.audit_recent(max(1, min(limit, 1000)))


@app.get("/audit/{trace_id}")
def audit(trace_id: str, request: Request, x_admin_key: str | None = Header(default=None)):
    """All steps of one request, in order. Same 404 for "not yours" and "does not exist"."""
    steps = engage.audit_trace(trace_id)
    sid = subject(request)
    if not steps or not (_is_admin(x_admin_key) or (sid and steps[0]["customer_id"] == sid)):
        raise HTTPException(404, "audit record not found")
    return {"trace_id": trace_id, "steps": steps}


@app.get("/policy")
def get_policy():
    """What the pipeline runs on: every rule YAML in config/, the live offer catalogue and the AI writer settings."""
    ai = policy.ai()
    return {"policy": policy.policy(), "segmentation": policy.segmentation(), "conflicts": policy.conflicts(),
            "offers": policy.offers(), "offer_rules": policy.offer_rules(), "validator": policy.validator(),
            "catalog": db.q("SELECT * FROM offer_catalog ORDER BY message_type, priority"),
            "ai": {"model": llm.model(), "temperature": ai["model"]["temperature"],
                   "tones": {k: v["description"] for k, v in ai["tone_instructions"].items()},
                   "placeholders": policy.policy()["message"]["locked_placeholders"]}}


@app.get("/evaluation", dependencies=[Depends(require_admin)])
def get_evaluation():
    return _call(evaluation.summary)


# ---------------- UC5 customer engagement: draft, review, mock send (staff only) ----------------
def _reviewer(x_reviewer: str | None = Header(default=None)) -> str:
    return (x_reviewer or "reviewer").strip()[:60]


def _call(fn, *a):
    try:
        return fn(*a)
    except engage.Refused as e:
        raise HTTPException(e.status, e.msg)


@app.post("/engage", dependencies=[Depends(require_admin)])
def engage_one(req: engage.EngageRequest):
    return _call(engage.run, req.customer_id, req.as_of_date)


@app.post("/engage/batch", dependencies=[Depends(require_admin)])
def engage_batch(req: engage.BatchRequest):
    """Customers run in parallel (BATCH_WORKERS): the AI call dominates and they are independent.
    With limit, only the next customers without a draft run, and `remaining` tells the console to continue."""
    remaining = 0
    if req.customer_ids:
        ids = req.customer_ids
    elif req.limit:
        ids, remaining = engage.undrafted(max(1, min(req.limit, 50)))
    else:
        ids = [r["customer_id"] for r in db.q("SELECT customer_id FROM customers ORDER BY customer_id")]

    def one(cid: str) -> dict:
        try:
            r = engage.run(cid, req.as_of_date)
            return ({k: r[k] for k in ("customer_id", "draft_id", "status", "primary_segment", "confidence")}
                    | {"blocking": [b["code"] for b in r["checks"]["blocking"]]})
        except engage.Refused as e:
            return {"customer_id": cid, "status": "error", "detail": e.msg}

    with ThreadPoolExecutor(max_workers=config.BATCH_WORKERS) as pool:
        out = list(pool.map(one, ids))
    return {"results": out, "remaining": remaining}


@app.get("/drafts", dependencies=[Depends(require_admin)])
def drafts(status: str | None = None, customer_id: str | None = None, full: bool = False):
    return engage.list_drafts(status, customer_id, full)


@app.get("/drafts/{draft_id}", dependencies=[Depends(require_admin)])
def draft(draft_id: str):
    return _call(engage.get, draft_id)


@app.post("/drafts/{draft_id}/edit", dependencies=[Depends(require_admin)])
def draft_edit(draft_id: str, req: engage.EditRequest, reviewer: str = Depends(_reviewer)):
    return _call(engage.edit, draft_id, req, reviewer)


@app.post("/drafts/{draft_id}/approve", dependencies=[Depends(require_admin)])
def draft_approve(draft_id: str, req: engage.NoteRequest, reviewer: str = Depends(_reviewer)):
    return _call(engage.approve, draft_id, req, reviewer)


@app.post("/drafts/{draft_id}/reject", dependencies=[Depends(require_admin)])
def draft_reject(draft_id: str, req: engage.NoteRequest, reviewer: str = Depends(_reviewer)):
    return _call(engage.reject, draft_id, req, reviewer)


@app.post("/drafts/{draft_id}/send", dependencies=[Depends(require_admin)])
def draft_send(draft_id: str, reviewer: str = Depends(_reviewer)):
    return _call(engage.send, draft_id, reviewer)


@app.get("/outbox", dependencies=[Depends(require_admin)])
def outbox():
    return engage.outbox()
