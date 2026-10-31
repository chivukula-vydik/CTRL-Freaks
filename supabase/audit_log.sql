-- Run once in the Supabase SQL editor if audit_log already exists in its old shape (one JSON record per request).
-- The old rows are kept in audit_log_legacy. The API then creates the new insert-only audit_log on startup
-- (app/schema.sql), or you can paste that block here as well.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'audit_log' AND column_name = 'event_id') THEN
    ALTER TABLE audit_log RENAME TO audit_log_legacy;
  END IF;
END
$$;

-- Drafts and the mock outbox are created by the API on startup. To create them by hand:
CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, as_of TEXT NOT NULL, segments TEXT, strategy TEXT,
  offer_id TEXT, facts TEXT, subject TEXT, body TEXT, checks TEXT, status TEXT NOT NULL, draft_source TEXT,
  template_version TEXT, model TEXT, trace_id TEXT, reviewer TEXT, review_note TEXT, edited TEXT DEFAULT 'N',
  created_at TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  message_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, customer_id TEXT NOT NULL, to_email_masked TEXT,
  subject TEXT NOT NULL, body TEXT NOT NULL, queued_at TEXT NOT NULL, status TEXT NOT NULL);
-- If drafts or outbox already exist from the first version, drop them first (test drafts only):
--   DROP TABLE IF EXISTS drafts, outbox;
