import os
import sys
from pathlib import Path

# isolated store, offline embeddings, no LLM. Never the production DATABASE_URL: tables get truncated
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
os.environ["QDRANT_URL"] = ":memory:"
os.environ.setdefault("EMBED_BACKEND", "hash")
os.environ.setdefault("MOCK_LLM", "true")
os.environ["ADMIN_KEY"] = "test-admin-key"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.domain import pack_dir  # noqa: E402
from app.loader import load_pack  # noqa: E402
from app.main import SUBJECT_HEADER, app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    db.init_db()
    db.reset()
    if pack_dir().exists():
        load_pack(pack_dir())   # the active domain's data pack, if it has one
    with TestClient(app) as c:
        yield c


def ask(client, q, cid=None, as_of="2026-10-06"):
    h = {SUBJECT_HEADER: cid} if cid else {}
    r = client.post("/ask", json={"question": q, "as_of_date": as_of}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()
