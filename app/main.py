"""FastAPI surface. Endpoint paths and fields follow the HCL contract; rename here if the day's doc differs."""
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import ValidationError

from app import agent, config, db, llm
from app.domain import DOMAIN
from app.ingest.pipeline import ingest_file, meta_from_json, safe_name
from app.retrieval import store
from app.schemas import AskRequest, AskResponse, IngestResponse, RuleIn

SUBJECT_HEADER = os.getenv("SUBJECT_HEADER", "X-Customer-Id")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="RAG Agent", version="0.1.0", lifespan=lifespan)


def subject(request: Request) -> str | None:
    v = request.headers.get(SUBJECT_HEADER)
    return v.strip().upper() if v and v.strip() else None


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    if x_admin_key != config.ADMIN_KEY:
        raise HTTPException(403, "admin key required")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, sid: str | None = Depends(subject)):
    return agent.run(req.question, sid, req.as_of_date)


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: str = Form(...)):
    try:
        meta = meta_from_json(metadata)
    except (ValidationError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"bad metadata: {e}")
    # only needed while parsing; chunks live in Qdrant. /tmp is the one writable dir on Vercel
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / f"{safe_name(meta.doc_id)}__{safe_name(file.filename or 'doc')}"
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            return ingest_file(dest, meta)
        except ValueError as e:
            raise HTTPException(415, str(e))


@app.get("/health")
def health():
    try:
        vs = {"status": "ok", "chunks": store.count()}
    except Exception as e:
        vs = {"status": "down", "error": type(e).__name__}
    sql = {"status": "ok" if db.ping() else "down"}
    lm = llm.health()
    ok = vs["status"] == "ok" and sql["status"] == "ok" and lm["status"] in {"ok", "mock"}
    return {"status": "ok" if ok else "degraded", "api": "ok", "vector_store": vs, "database": sql,
            "llm": lm, "domain": DOMAIN.name, "embed": f"{config.EMBED_BACKEND}:{config.EMBED_MODEL}"}


@app.get("/audit/{trace_id}")
def audit(trace_id: str, request: Request, x_admin_key: str | None = Header(default=None)):
    row = db.q1("SELECT * FROM audit_log WHERE trace_id = ?", (trace_id,))
    sid = subject(request)
    is_admin = x_admin_key == config.ADMIN_KEY
    # same 404 for "not yours" and "does not exist"
    if not row or not (is_admin or (sid and row["customer_id"] == sid) or
                       (row["customer_id"] is None and sid is None)):
        raise HTTPException(404, "audit record not found")
    return json.loads(row["record"])


@app.get("/sources")
def sources():
    return db.q("SELECT * FROM source_register ORDER BY authority_level, effective_from")


@app.get("/rules")
def rules():
    return db.q("SELECT * FROM rule_registry ORDER BY parameter, effective_from")


@app.post("/admin/rules", dependencies=[Depends(require_admin)])
def add_rule(rule: RuleIn, source_doc_id: str):
    if not db.q1("SELECT 1 FROM source_register WHERE doc_id = ?", (source_doc_id,)):
        raise HTTPException(422, "source_doc_id must exist in the Source Register")
    doc = db.q1("SELECT effective_from, effective_to FROM source_register WHERE doc_id = ?", (source_doc_id,))
    db.upsert("rule_registry", [{**rule.model_dump(), "effective_from": rule.effective_from or doc["effective_from"],
                                 "effective_to": rule.effective_to or doc["effective_to"],
                                 "source_doc_id": source_doc_id}])
    return {"status": "ok", "rule_id": rule.rule_id}


@app.post("/admin/load-data", dependencies=[Depends(require_admin)])
def load_data(files: list[UploadFile] = File(...)):
    """Upload judge CSVs (one file per table, named <table>.csv)."""
    with tempfile.TemporaryDirectory() as d:
        for f in files:
            (Path(d) / safe_name(f.filename or "x.csv")).write_bytes(f.file.read())
        counts = DOMAIN.load_csv_dir(d)
    return {"loaded": counts, "violations": DOMAIN.validate()[:50]}
