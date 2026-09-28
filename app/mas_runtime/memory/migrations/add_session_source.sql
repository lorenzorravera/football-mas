-- =============================================================================
-- A1 — Memory namespacing: add session_id + source to the three memory stores.
-- Idempotent; safe to re-run. Apply with: python memory/migrations/run_migrations.py
-- =============================================================================

ALTER TABLE conversation_memory ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE conversation_memory ADD COLUMN IF NOT EXISTS source     TEXT;
ALTER TABLE sql_cache           ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE sql_cache           ADD COLUMN IF NOT EXISTS source     TEXT;
ALTER TABLE correction_memory   ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE correction_memory   ADD COLUMN IF NOT EXISTS source     TEXT;

-- Backfill existing untagged rows as 'legacy' so they are (a) distinguishable from
-- new 'live' rows and (b) excluded from eval retrieval via the source filter.
UPDATE conversation_memory SET source = 'legacy' WHERE source IS NULL;
UPDATE sql_cache           SET source = 'legacy' WHERE source IS NULL;
UPDATE correction_memory   SET source = 'legacy' WHERE source IS NULL;

-- Indexes for session-scoped queries/purges and source filtering.
CREATE INDEX IF NOT EXISTS conversation_memory_session_idx ON conversation_memory (session_id);
CREATE INDEX IF NOT EXISTS sql_cache_session_idx           ON sql_cache (session_id);
CREATE INDEX IF NOT EXISTS correction_memory_session_idx   ON correction_memory (session_id);
CREATE INDEX IF NOT EXISTS conversation_memory_source_idx  ON conversation_memory (source);
CREATE INDEX IF NOT EXISTS sql_cache_source_idx            ON sql_cache (source);
CREATE INDEX IF NOT EXISTS correction_memory_source_idx    ON correction_memory (source);
