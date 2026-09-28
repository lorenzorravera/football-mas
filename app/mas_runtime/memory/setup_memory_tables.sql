CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS conversation_memory (
    id           TEXT PRIMARY KEY,
    query        TEXT NOT NULL,
    response     TEXT,
    sql_query    TEXT,
    intent       TEXT,
    params       JSONB,
    embedding    vector(384),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS conversation_memory_embedding_idx
    ON conversation_memory USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

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
    ON sql_cache USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

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
    ON correction_memory USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS feedback (
    id           TEXT PRIMARY KEY,
    memory_id    TEXT,
    score        INTEGER,
    user_query   TEXT,
    variant      TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS feedback_memory_id_idx ON feedback (memory_id);
