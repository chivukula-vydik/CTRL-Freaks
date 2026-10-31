-- Core tables, domain-agnostic. Domain tables live in app/domain/<name>.py (SCHEMA)
CREATE TABLE IF NOT EXISTS rule_registry (
  rule_id          TEXT PRIMARY KEY,
  description      TEXT,
  parameter        TEXT NOT NULL,
  operator         TEXT,
  value            TEXT NOT NULL,
  scope_categories TEXT NOT NULL DEFAULT 'ALL',
  scope_tiers      TEXT NOT NULL DEFAULT 'ALL',
  effective_from   TEXT NOT NULL,
  effective_to     TEXT,
  source_doc_id    TEXT NOT NULL,
  source_section   TEXT
);

-- Annex B, one row per ingested doc
CREATE TABLE IF NOT EXISTS source_register (
  doc_id           TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  issuer           TEXT,
  authority_level  INTEGER NOT NULL CHECK (authority_level BETWEEN 1 AND 5),
  doc_type         TEXT,
  version          TEXT,
  effective_from   TEXT NOT NULL,
  effective_to     TEXT,
  supersedes       TEXT,
  scope_categories TEXT NOT NULL DEFAULT 'ALL',
  scope_tiers      TEXT NOT NULL DEFAULT 'ALL',
  provenance       TEXT,
  retrieved_on     TEXT,
  synthetic        TEXT DEFAULT 'N',
  file_name        TEXT,
  chunks_indexed   INTEGER DEFAULT 0,
  ingested_at      TEXT
);

-- Audit log: one row per pipeline step. Insert-only: a trigger refuses UPDATE and DELETE, and the API roles
-- lose the privileges. (An older single-record audit_log must be renamed first: supabase/audit_log.sql.)
CREATE TABLE IF NOT EXISTS audit_log (
  event_id      BIGSERIAL PRIMARY KEY,
  trace_id      TEXT NOT NULL,
  seq           INTEGER NOT NULL,
  step          TEXT NOT NULL,
  timestamp     TEXT NOT NULL,
  customer_id   TEXT,
  actor         TEXT NOT NULL,
  rule          TEXT,
  evidence      TEXT,
  model_version TEXT,
  record        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_trace ON audit_log (trace_id, seq);

CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  RAISE EXCEPTION 'audit_log is insert-only: % is not allowed', TG_OP;
END
$fn$;
DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC;
DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM anon';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM authenticated';
  END IF;
END
$do$;

-- state-changing tool calls (@action). payload = what is needed to run it again on confirm
CREATE TABLE IF NOT EXISTS actions (
  action_id  TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  tool       TEXT NOT NULL,
  risk       TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN ('pending','done','pending_approval')),
  payload    TEXT NOT NULL,
  result     TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);

-- raw CSVs uploaded for the data pipeline (app/pipeline.py); cleaned on read, so re-upload = re-clean
CREATE TABLE IF NOT EXISTS pipeline_files (
  table_name  TEXT PRIMARY KEY,
  body        TEXT NOT NULL,
  uploaded_at TEXT NOT NULL
);
