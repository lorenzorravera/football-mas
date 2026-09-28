-- =============================================================================
-- agent_v3 memory layer — pgvector setup
-- Run once on Aiven PostgreSQL:
--   psql $DATABASE_URI -f memory/setup_pgvector.sql
-- =============================================================================

-- Enable pgvector extension (requires superuser on Aiven — done via console or this)
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- Table 1: conversation_memory
-- Stores every completed Q&A turn for cross-session continuity
-- =============================================================================
CREATE TABLE IF NOT EXISTS conversation_memory (
    id           TEXT PRIMARY KEY,
    query        TEXT NOT NULL,
    response     TEXT,
    sql_query    TEXT,
    intent       TEXT,
    params       JSONB,
    embedding    vector(384),        -- all-MiniLM-L6-v2 output dimension
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- HNSW index for fast approximate nearest-neighbour search (cosine)
CREATE INDEX IF NOT EXISTS conversation_memory_embedding_idx
    ON conversation_memory
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- Table 2: sql_cache
-- Caches successful SQL queries keyed by user query embedding
-- =============================================================================
CREATE TABLE IF NOT EXISTS sql_cache (
    id           TEXT PRIMARY KEY,
    query        TEXT NOT NULL,
    sql_query    TEXT NOT NULL,
    row_count    INTEGER,
    columns      JSONB,
    variant      TEXT,
    embedding    vector(384),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sql_cache_embedding_idx
    ON sql_cache
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- Table 3: correction_memory
-- Stores failed queries so similar future queries are warned
-- =============================================================================
CREATE TABLE IF NOT EXISTS correction_memory (
    id            TEXT PRIMARY KEY,
    query         TEXT NOT NULL,
    error_type    TEXT,
    error_message TEXT,
    bad_sql       TEXT,
    stage         TEXT,
    embedding     vector(384),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS correction_memory_embedding_idx
    ON correction_memory
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- Verify setup
-- =============================================================================
SELECT
    table_name,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS size
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('conversation_memory', 'sql_cache', 'correction_memory')
ORDER BY table_name;
