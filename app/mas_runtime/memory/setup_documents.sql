-- =============================================================================
-- agent_v4 text/RAG layer — `documents` content collection (pgvector)
-- Run once on Aiven PostgreSQL:
--   psql $DATABASE_URI -f memory/setup_documents.sql
--
-- Unlike the three memory tables (conversation_memory / sql_cache /
-- correction_memory), which embed the *user question*, this table embeds
-- *document content* (match summaries, player bios, season narratives) and is
-- queried by embedding the incoming question against it (content-keyed RAG).
--
-- Leakage gate: `as_of_date` = when the text was publishable/known; `event_date`
-- = what the text is about. A prediction that must not see the future filters on
-- `as_of_date < kickoff`. Qualitative retrieval ignores the gate.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id       BIGSERIAL PRIMARY KEY,
    entity_type  TEXT,                 -- 'player' | 'team' | 'match' | 'season'
    entity_id    BIGINT,               -- player_id / team_id / game_id / season_id (nullable)
    doc_type     TEXT,                 -- 'match_report' | 'player_bio' | 'season_narrative' | 'prematch_preview'
    as_of_date   DATE,                 -- leakage gate: date the text was known/published
    event_date   DATE,                 -- the date the text is ABOUT (e.g. kickoff)
    source       TEXT,                 -- provenance + licensing tag (e.g. Wikipedia URL#revid)
    text         TEXT NOT NULL,
    embedding    vector(384),          -- all-MiniLM-L6-v2 output dimension
    session_id   TEXT,                 -- eval namespacing (mirrors the memory tables)
    doc_source   TEXT DEFAULT 'live',  -- 'live' | 'eval_session' (retrieval-scope tag)
    content_hash TEXT,                 -- dedupe key (entity|doc_type|source|text); see below
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Idempotent ingestion: a UNIQUE index on content_hash lets store_document() use
-- ON CONFLICT DO NOTHING, so re-running the loader never inserts duplicate chunks.
CREATE UNIQUE INDEX IF NOT EXISTS documents_content_hash_idx
    ON documents (content_hash);

-- HNSW index for fast approximate nearest-neighbour search (cosine)
CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Entity/type lookups (filter before/with the vector search)
CREATE INDEX IF NOT EXISTS documents_entity_idx
    ON documents (entity_type, entity_id, doc_type);

-- as_of gate uses a range scan on the leakage date
CREATE INDEX IF NOT EXISTS documents_as_of_idx
    ON documents (as_of_date);

-- =============================================================================
-- Verify setup
-- =============================================================================
SELECT
    table_name,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS size
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = 'documents';
