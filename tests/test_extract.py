"""Extraction skeleton: mock-mode run over examples/extract scores 100%, and /extract returns rows.
No database needed."""
import json

from fastapi.testclient import TestClient

from app.config import ROOT
from app.extract import extract_file, score
from app.main import app

PACK = ROOT / "examples" / "extract" / "data" / "extract"
SCHEMA = json.loads((PACK / "schema.json").read_text())


def test_example_pack_scores():
    rows = [extract_file(p, SCHEMA) for p in sorted((PACK / "docs").iterdir())]
    exp = [json.loads(x) for x in (PACK / "expected.jsonl").read_text().splitlines() if x.strip()]
    s = score(rows, exp, SCHEMA)
    assert s["doc_exact_match"] == 1.0, s["failures"]
    assert all(r["_sources"]["reference_id"]["quote"] for r in rows)   # every value carries its quote


def test_extract_endpoint_flags_invalid():
    doc = b"Party Name: X\nReference ID: bad\nTotal Amount: -5"
    r = TestClient(app).post("/extract", files=[("files", ("a.txt", doc, "text/plain"))],
                             data={"fields_json": json.dumps(SCHEMA)})
    row = r.json()["rows"][0]
    assert r.status_code == 200 and not row["_valid"]
    assert any(e.startswith("reference_id:") for e in row["_errors"]) and row["total_amount"] == -5
