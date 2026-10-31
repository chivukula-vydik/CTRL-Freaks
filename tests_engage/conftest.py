"""Test setup. Runs against a throwaway Postgres (TEST_DATABASE_URL), never the real DATABASE_URL.
Loads supabase/schema.sql and data/dataset/*.csv, the same shape as the Supabase tables.
    docker compose up -d db        # or any empty local Postgres
    pytest tests_engage
"""
import csv
import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_URL = os.getenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
os.environ.update(DOMAIN="engage", DATABASE_URL=TEST_URL, MOCK_LLM="true", ADMIN_KEY="test-admin-key")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

TABLES = ["customers", "billing", "consent", "contact_history", "offer_catalog"]
H = {"X-Admin-Key": "test-admin-key", "X-Reviewer": "tester"}


@pytest.fixture(scope="session", autouse=True)
def _database():
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        c.execute((ROOT / "supabase" / "schema.sql").read_text())
        for t in TABLES:
            rows = list(csv.DictReader((ROOT / "data" / "dataset" / f"{t}.csv").open(encoding="utf-8")))
            have = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (t,))}
            cols = [k for k in rows[0] if k in have]   # protected test fields are not in the Supabase tables
            with c.cursor() as cur:
                cur.executemany(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})",
                                [tuple(r[k] if r[k] != "" else None for k in cols) for r in rows])
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def _clean():
    """Each test starts with no drafts, no outbox, no audit rows and the dataset's own contact history."""
    with db.conn() as c:
        c.execute("TRUNCATE drafts, outbox, audit_log")
        c.execute("DELETE FROM contact_history WHERE outcome = 'mock_sent'")
    yield


@pytest.fixture()
def client():
    return TestClient(app)
