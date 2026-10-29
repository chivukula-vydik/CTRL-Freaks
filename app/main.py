"""FastAPI surface. Endpoint paths and fields follow the HCL contract; rename here if the day's doc differs."""
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import ValidationError

from app import agent, config, db, extract, llm, pipeline
from app.domain import DOMAIN, pack_dir
from app.ingest.pipeline import ingest_file, meta_from_json, safe_name
from app.retrieval import store
from app.schemas import AskRequest, AskResponse, CalcRequest, IngestResponse, RuleIn

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


@app.post("/extract")
def extract_docs(files: list[UploadFile] = File(...), fields_json: str | None = Form(default=None)):
    """Documents -> one row each of the fields in <pack>/extract/schema.json (or the `fields_json` form field)."""
    try:
        sch = json.loads(fields_json) if fields_json else json.loads((pack_dir() / "extract" / "schema.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"no usable extraction schema: {e}")
    if not isinstance(sch.get("fields"), dict) or not sch["fields"]:
        raise HTTPException(422, "schema needs a non-empty 'fields' object")
    rows = []
    with tempfile.TemporaryDirectory() as d:
        for f in files:
            dest = Path(d) / safe_name(f.filename or "doc")
            dest.write_bytes(f.file.read())
            try:
                rows.append(extract.extract_file(dest, sch))
            except ValueError as e:
                rows.append({"doc": dest.name, "_valid": False, "_errors": [str(e)]})
    return {"rows": rows}


def _pipeline():
    try:
        return pipeline.load(pack_dir())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"no usable pipeline schema: {e}")


@app.post("/admin/pipeline/upload", dependencies=[Depends(require_admin)])
def pipeline_upload(files: list[UploadFile] = File(...)):
    """Raw CSVs, one per table (<table>.csv). Stored raw, returns the data-quality report."""
    schema, _ = _pipeline()
    now = datetime.now(timezone.utc).isoformat()
    rows, unknown = [], []
    for f in files:
        name = Path(f.filename or "").stem
        if name not in schema["tables"]:
            unknown.append(f.filename)
            continue
        rows.append({"table_name": name, "body": f.file.read().decode("utf-8-sig", errors="replace"),
                     "uploaded_at": now})
    db.upsert("pipeline_files", rows)
    return {"stored": [r["table_name"] for r in rows], "unknown_files": unknown, "report": _pipeline()[1]["report"]}


@app.get("/pipeline/report")
def pipeline_report():
    """Data-quality report + every rejected row with its reasons."""
    _, res = _pipeline()
    return {"report": res["report"], "rejected": res["rejected"]}


@app.get("/pipeline/metrics")
def pipeline_metrics():
    return _pipeline()[0]["metrics"]


@app.post("/pipeline/calc")
def pipeline_calc(req: CalcRequest):
    schema, res = _pipeline()
    if req.metric not in schema["metrics"]:
        raise HTTPException(404, f"unknown metric; available: {list(schema['metrics'])}")
    return pipeline.calc(schema, res["tables"], req.metric, req.filters, req.group_by, req.date_from, req.date_to,
                         req.top, req.bottom)


@app.post("/pipeline/ask")
def pipeline_ask(req: AskRequest):
    schema, res = _pipeline()
    return pipeline.ask(schema, res["tables"], req.question)


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
