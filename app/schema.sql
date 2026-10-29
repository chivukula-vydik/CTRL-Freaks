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

CREATE TABLE IF NOT EXISTS audit_log (
  trace_id    TEXT PRIMARY KEY,
  timestamp   TEXT NOT NULL,
  customer_id TEXT,
  record      TEXT NOT NULL
);
