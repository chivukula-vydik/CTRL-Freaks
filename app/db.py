"""Postgres (Supabase) access through a small pool. Call sites keep SQLite-style `?` / `:name` params."""
import re
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

SCHEMA = Path(__file__).with_name("schema.sql")
_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # prepare_threshold=None: required behind Supabase's transaction pooler (port 6543)
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, open=True,
                               kwargs={"row_factory": dict_row, "prepare_threshold": None})
    return _pool


@contextmanager
def conn():
    with _get_pool().connection() as c:  # commits on success, rolls back on error
        yield c


def _pg(sql: str, params):
    # ponytail: textual ? -> %s, so a literal "?" inside a SQL string breaks; none exist today
    if not params:
        return sql, None
    sql = sql.replace("%", "%%")
    if isinstance(params, dict):
        return re.sub(r"(?<![:\w]):(\w+)", r"%(\1)s", sql), params
    return sql.replace("?", "%s"), tuple(params)


def init_db() -> None:
    from app.domain import DOMAIN
    with conn() as c:
        c.execute(SCHEMA.read_text())
        if DOMAIN.SCHEMA:
            c.execute(DOMAIN.SCHEMA)


def reset() -> None:
    """Empty core + domain tables. Tests and the offline eval only, never against production."""
    from app.domain import DOMAIN
    tables = ["rule_registry", "source_register", "audit_log", "pipeline_files"] + DOMAIN.tables()
    with conn() as c:
        c.execute(f"TRUNCATE {', '.join(tables)} CASCADE")


def q(sql: str, params: tuple | dict = ()) -> list[dict]:
    with conn() as c:
        cur = c.execute(*_pg(sql, params))
        return cur.fetchall() if cur.description else []


def q1(sql: str, params: tuple | dict = ()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | dict = ()) -> int:
    with conn() as c:
        return c.execute(*_pg(sql, params)).rowcount


@lru_cache(maxsize=None)
def _pk(table: str) -> tuple[str, ...]:
    rows = q("""SELECT a.attname FROM pg_index i JOIN pg_attribute a
                ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = ?::regclass AND i.indisprimary""", (table,))
    return tuple(r["attname"] for r in rows)


def upsert(table: str, rows: list[dict]) -> int:
    """INSERT OR REPLACE equivalent: update on primary-key conflict."""
    if not rows:
        return 0
    cols = list(rows[0])
    pk = _pk(table)
    upd = [c for c in cols if c not in pk]
    tail = ""
    if pk:
        tail = f" ON CONFLICT ({','.join(pk)}) DO " + (
            "UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in upd) if upd else "NOTHING")
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))}){tail}"
    with conn() as c, c.cursor() as cur:
        cur.executemany(sql, [tuple(r[k] for k in cols) for r in rows])
    return len(rows)


def ping() -> bool:
    try:
        q("SELECT 1")
        return True
    except Exception:
        return False
