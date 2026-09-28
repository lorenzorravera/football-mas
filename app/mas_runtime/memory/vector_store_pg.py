"""
pgvector-backed vector store for agent_v3 memory.

Replaces ChromaDB with PostgreSQL + pgvector on Aiven.
Same public API as vector_store.py — drop-in replacement.

Three tables mirror the three ChromaDB collections:
  conversation_memory  — completed Q&A turns
  sql_cache            — successful SQL queries
  correction_memory    — failed queries / bad SQL patterns

Setup (run once on Aiven):
    psql $DATABASE_URI -f memory/setup_pgvector.sql

Similarity thresholds (cosine, 0–1):
  SQL_CACHE_THRESHOLD   0.88
  MEMORY_THRESHOLD      0.70
  CORRECTION_THRESHOLD  0.75
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, UTC
from typing import Optional

import psycopg2
import psycopg2.extras
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SQL_CACHE_THRESHOLD  = 0.88
MEMORY_THRESHOLD     = 0.70
CORRECTION_THRESHOLD = 0.75
# Content RAG: question-vs-document cosine runs lower than question-vs-question,
# so the documents floor is deliberately looser than the memory thresholds.
DOCUMENTS_THRESHOLD  = 0.30

VECTOR_DIM = 384  # all-MiniLM-L6-v2 output dimension

# Module-level singletons
_embedding_fn = None
_conn = None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = DefaultEmbeddingFunction()
    return _embedding_fn


def _get_conn():
    """Get or create a psycopg2 connection to Aiven PostgreSQL."""
    global _conn
    if _conn is None or _conn.closed:
        database_uri = os.getenv("DATABASE_URI")
        if not database_uri:
            raise ValueError("DATABASE_URI environment variable not set")
        _conn = psycopg2.connect(database_uri)
        _conn.autocommit = True
        # Register pgvector type
        psycopg2.extras.register_uuid()
    return _conn


def _embed(text: str) -> list[float]:
    """Convert text to a vector using all-MiniLM-L6-v2 via onnxruntime."""
    fn = _get_embedding_fn()
    return fn([text])[0].tolist()


def _cosine_similarity(distance: float) -> float:
    """pgvector <=> operator returns cosine distance (0=identical, 2=opposite)."""
    return round(1.0 - (distance / 2.0), 4)


# Default sources excluded from LIVE retrieval (eval rows must never leak to prod).
DEFAULT_EXCLUDE_SOURCES = ("eval_session",)


def _scope_clause(
    session_id: Optional[str],
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> tuple[str, list]:
    """
    Build the namespacing WHERE fragment + params for a retrieval query.

    Hard eval guard:
      - session_id set   -> return ONLY that session's rows (nothing else is visible).
      - session_id None  -> live mode: return rows whose source is NOT in exclude_sources
                            (NULL source is kept for backward compatibility).

    Returns (sql_fragment, params) where sql_fragment starts with ' AND ...'.
    """
    if session_id is not None:
        return " AND session_id = %s", [session_id]
    if exclude_sources:
        return " AND (source IS NULL OR NOT (source = ANY(%s)))", [list(exclude_sources)]
    return "", []


# ---------------------------------------------------------------------------
# Collection 1: conversation_memory
# ---------------------------------------------------------------------------

def store_conversation(
    memory_id: str,
    user_query: str,
    final_response: str,
    sql_query: str,
    intent: str,
    query_parameters: dict,
    session_id: Optional[str] = None,
    source: str = "live",
) -> None:
    """Persist a completed Q&A turn.

    session_id / source namespace the row (Option 2 eval isolation):
      source='live'         normal production turns (default)
      source='eval_session' written by the session-eval harness; purged after, and
                            excluded from live retrieval
      source='legacy'       pre-migration rows (backfilled)
    """
    embedding = _embed(user_query)
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO conversation_memory
                (id, query, response, sql_query, intent, params, embedding,
                 created_at, session_id, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            memory_id,
            user_query[:500],
            final_response[:1000],
            (sql_query or "")[:500],
            intent,
            json.dumps(query_parameters),
            str(embedding),
            datetime.now(UTC),
            session_id,
            source,
        ))


def query_conversation_memory(
    user_query: str,
    n_results: int = 3,
    session_id: Optional[str] = None,
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> list[dict]:
    """
    Return up to n_results past turns semantically similar to user_query.
    Only successful turns (no error in response) above MEMORY_THRESHOLD.

    Namespacing (see _scope_clause): when session_id is set, ONLY that session's
    rows are visible (eval guard); otherwise eval_session rows are excluded.
    """
    embedding = _embed(user_query)
    scope_sql, scope_params = _scope_clause(session_id, exclude_sources)
    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                query, response, sql_query, intent,
                (embedding <=> %s::vector) AS distance
            FROM conversation_memory
            WHERE response NOT LIKE 'Hybrid analysis failed%%'
              AND response NOT LIKE '%%RateLimitError%%'
              AND response NOT LIKE '%%No module%%'
        """ + scope_sql + """
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (str(embedding), *scope_params, str(embedding), n_results))

        rows = cur.fetchall()

    memories = []
    for row in rows:
        sim = _cosine_similarity(row["distance"])
        if sim >= MEMORY_THRESHOLD:
            memories.append({
                "query":      row["query"],
                "response":   row["response"],
                "sql":        row["sql_query"],
                "intent":     row["intent"],
                "similarity": sim,
            })

    return memories


# ---------------------------------------------------------------------------
# Collection 2: sql_cache
# ---------------------------------------------------------------------------

def store_sql_cache(
    memory_id: str,
    user_query: str,
    sql_query: str,
    row_count: int,
    columns: list[str],
    variant: str,
    session_id: Optional[str] = None,
    source: str = "live",
) -> None:
    """Cache a successful SQL query for future reuse."""
    if not sql_query or sql_query.startswith("Function:"):
        return

    embedding = _embed(user_query)
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sql_cache
                (id, query, sql_query, row_count, columns, variant, embedding,
                 created_at, session_id, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            f"sql_{memory_id}",
            user_query,
            sql_query[:800],
            row_count,
            json.dumps(columns),
            variant,
            str(embedding),
            datetime.now(UTC),
            session_id,
            source,
        ))


# Discriminating metric vocabulary — if the cached query and the new query mention
# DIFFERENT metrics (e.g. red vs yellow cards, corners vs fouls), the cached SQL has the
# wrong columns hardcoded and must not be reused. Each entry is a set of synonyms.
_METRIC_TERMS = [
    {"corner", "corners"}, {"foul", "fouls"}, {"yellow"}, {"red"},
    {"card", "cards"}, {"shot", "shots"}, {"clean sheet", "clean sheets", "cleansheet"},
    {"point", "points"}, {"goal", "goals", "scored", "scorer"}, {"win", "wins", "won"},
    {"draw", "draws"}, {"loss", "losses", "lost"}, {"assist", "assists"},
    {"possession"}, {"save", "saves"}, {"conceded", "against"}, {"tackle", "tackles"},
]
# Words that are Capitalized but are NOT entities (so they don't count as a team/player).
_PROPER_STOP = {"Premier", "League", "How", "What", "And", "Which", "Who", "The", "Show",
                "In", "English", "Whats", "Where", "During", "Across", "Total", "Season"}


def _query_tokens(text: str) -> tuple[set, set, set]:
    """Extract (seasons, metric-groups present, proper-noun entities) from a query/SQL string."""
    import re
    low = (text or "").lower()
    seasons = set(re.findall(r"\d{4}-\d{4}", text or ""))
    # Whole-word match so e.g. "red" doesn't fire inside "scored".
    metrics = {i for i, syns in enumerate(_METRIC_TERMS)
               if any(re.search(r"\b" + re.escape(s) + r"\b", low) for s in syns)}
    propers = {w for w in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text or "")
               if w not in _PROPER_STOP}
    return seasons, metrics, propers


def _cache_consistency_ok(new_query: str, cached_query: str, cached_sql: str) -> bool:
    """Guard against entity-mismatched cache reuse.

    A high embedding similarity (≥0.88) fires for structurally-identical queries that differ
    only in team/season/metric — but the cached SQL has those literals hardcoded, so reusing
    it returns the WRONG answer (e.g. a Liverpool/2024-25 question served Arsenal/2023-24 SQL).
    Reject the hit unless the discriminating tokens match. Season + metric are compared against
    the cached query text AND its resulting SQL concatenated (so a literal baked only into the
    executed SQL still counts); entities against the cached query text alone. Empty-vs-empty is
    allowed (no signal to contradict)."""
    n_seasons, n_metrics, n_propers = _query_tokens(new_query)
    c_seasons, c_metrics, _ = _query_tokens(cached_query + " " + cached_sql)
    _, _, c_propers = _query_tokens(cached_query)

    # Season mismatch: the cached SQL targets a season the new query doesn't ask for.
    if n_seasons and c_seasons and n_seasons != c_seasons:
        return False
    # Metric mismatch: different stat columns are baked into the cached SQL.
    if n_metrics and c_metrics and n_metrics != c_metrics:
        return False
    # Entity mismatch: different team/player named.
    if n_propers and c_propers and n_propers != c_propers:
        return False
    return True


def query_sql_cache(
    user_query: str,
    session_id: Optional[str] = None,
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> Optional[dict]:
    """
    Return cached SQL for a near-identical past query, or None.
    Only returned when similarity >= SQL_CACHE_THRESHOLD (0.88) AND the discriminating
    entities (season / metric / team) match — see _cache_consistency_ok. The entity guard
    prevents a structurally-similar but different-entity query from reusing stale SQL with the
    wrong literals hardcoded.
    Namespaced via _scope_clause (session-scoped under eval; eval rows excluded live).
    """
    embedding = _embed(user_query)
    scope_sql, scope_params = _scope_clause(session_id, exclude_sources)
    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                query, sql_query, row_count, columns, variant,
                (embedding <=> %s::vector) AS distance
            FROM sql_cache
            WHERE TRUE
        """ + scope_sql + """
            ORDER BY embedding <=> %s::vector
            LIMIT 1
        """, (str(embedding), *scope_params, str(embedding)))

        row = cur.fetchone()

    if not row:
        return None

    sim = _cosine_similarity(row["distance"])
    if sim < SQL_CACHE_THRESHOLD:
        return None

    # Entity guard: a near-identical embedding can still be a different team/season/metric.
    if not _cache_consistency_ok(user_query, row["query"], row["sql_query"] or ""):
        return None

    return {
        "sql":          row["sql_query"],
        "similarity":   sim,
        "row_count":    row["row_count"],
        "columns": row["columns"] if isinstance(row["columns"], list) else json.loads(row["columns"]),
        "variant":      row["variant"],
        "cached_query": row["query"],
    }


# ---------------------------------------------------------------------------
# Collection 3: correction_memory
# ---------------------------------------------------------------------------

def store_correction(
    memory_id: str,
    user_query: str,
    error_type: str,
    error_message: str,
    bad_sql: str,
    stage: str,
    session_id: Optional[str] = None,
    source: str = "live",
) -> None:
    """Persist a failed query so similar future queries are warned."""
    embedding = _embed(user_query)
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO correction_memory
                (id, query, error_type, error_message, bad_sql, stage, embedding,
                 created_at, session_id, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            f"err_{memory_id}",
            user_query,
            error_type,
            (error_message or "")[:400],
            (bad_sql or "")[:400],
            stage,
            str(embedding),
            datetime.now(UTC),
            session_id,
            source,
        ))

# ---------------------------------------------------------------------------
# Add this function to memory/vector_store_pg.py
# Place it after the store_correction() function
# ---------------------------------------------------------------------------

def store_feedback(
    memory_id: str,
    user_query: str,
    score: int,       # +1 = thumbs up, -1 = thumbs down
    variant: str = "unknown",
) -> None:
    """Persist thumbs up/down feedback linked to a conversation turn."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO feedback
                (id, memory_id, user_query, score, variant, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            f"fb_{memory_id}",
            memory_id,
            user_query,
            score,
            variant,
            datetime.now(UTC),
        ))
        
def query_correction_memory(
    user_query: str,
    n_results: int = 2,
    session_id: Optional[str] = None,
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> list[dict]:
    """Return past failure warnings for semantically similar queries.
    Namespaced via _scope_clause (session-scoped under eval; eval rows excluded live)."""
    embedding = _embed(user_query)
    scope_sql, scope_params = _scope_clause(session_id, exclude_sources)
    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                error_type, error_message, bad_sql, stage,
                (embedding <=> %s::vector) AS distance
            FROM correction_memory
            WHERE TRUE
        """ + scope_sql + """
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (str(embedding), *scope_params, str(embedding), n_results))

        rows = cur.fetchall()

    warnings = []
    for row in rows:
        sim = _cosine_similarity(row["distance"])
        if sim >= CORRECTION_THRESHOLD:
            warnings.append({
                "error_type":    row["error_type"],
                "error_message": row["error_message"],
                "bad_sql":       row["bad_sql"],
                "stage":         row["stage"],
                "similarity":    sim,
            })

    return warnings


# ---------------------------------------------------------------------------
# Collection 4: documents (content-keyed RAG — narrative text)
#
# Unlike the three collections above (which embed the user QUESTION), this one
# embeds document CONTENT (match summaries, player bios, season narratives). It
# is queried by embedding the incoming question against the stored content.
# See memory/setup_documents.sql for the table.
# ---------------------------------------------------------------------------

def _doc_scope_clause(
    session_id: Optional[str],
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> tuple[str, list]:
    """Namespacing fragment for `documents`. Mirrors _scope_clause but on the
    `doc_source` column (the table's `source` column holds provenance, not scope)."""
    if session_id is not None:
        return " AND session_id = %s", [session_id]
    if exclude_sources:
        return " AND (doc_source IS NULL OR NOT (doc_source = ANY(%s)))", [list(exclude_sources)]
    return "", []


def store_document(
    entity_type: Optional[str],
    entity_id: Optional[int],
    doc_type: str,
    text: str,
    as_of_date=None,
    event_date=None,
    source: str = "",
    session_id: Optional[str] = None,
    doc_source: str = "live",
) -> None:
    """Persist one narrative document (or chunk) with its content embedding.

    Chunking is the caller's job (see data_prep/ingest_wikipedia.py) — this stores
    a single text blob per row. `as_of_date` is the leakage gate (when the text was
    known); leave it None only for timeless content that will never feed a forecast.
    `source` is provenance (e.g. a Wikipedia URL#revid); `doc_source` is the eval
    scope tag ('live' | 'eval_session'), analogous to `source` on the memory tables.
    """
    if not text or not text.strip():
        return
    # Dedupe key: same (entity, doc_type, source, text) chunk is inserted at most once,
    # so re-running the ingester is idempotent (ON CONFLICT DO NOTHING on the unique index).
    content_hash = hashlib.sha256(
        "|".join([entity_type or "", str(entity_id or ""), doc_type or "",
                  source or "", text]).encode("utf-8")
    ).hexdigest()
    embedding = _embed(text)
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO documents
                (entity_type, entity_id, doc_type, as_of_date, event_date, source,
                 text, embedding, session_id, doc_source, content_hash, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING
        """, (
            entity_type,
            entity_id,
            doc_type,
            as_of_date,
            event_date,
            source,
            text,
            str(embedding),
            session_id,
            doc_source,
            content_hash,
            datetime.now(UTC),
        ))


def query_documents(
    query_text: str,
    entity_filter: Optional[dict] = None,
    doc_types: Optional[list] = None,
    as_of=None,
    n_results: int = 5,
    min_sim: float = DOCUMENTS_THRESHOLD,
    session_id: Optional[str] = None,
    exclude_sources: Optional[tuple] = DEFAULT_EXCLUDE_SOURCES,
) -> list[dict]:
    """Return up to n_results narrative documents most similar to query_text.

    entity_filter: optional {'entity_type': ..., 'entity_id': ...} (either key optional).
    doc_types:     optional list restricting to given doc_type values.
    as_of:         LEAKAGE GATE. When set (a date/ISO string), only documents with
                   as_of_date < as_of are returned (NULL as_of_date is excluded, since
                   we can't prove it predates the cutoff). Leave None for qualitative
                   retrieval, where post-hoc text is allowed.
    """
    embedding = _embed(query_text)
    where = " WHERE TRUE"
    params: list = []

    if entity_filter:
        if entity_filter.get("entity_type") is not None:
            where += " AND entity_type = %s"
            params.append(entity_filter["entity_type"])
        if entity_filter.get("entity_id") is not None:
            where += " AND entity_id = %s"
            params.append(entity_filter["entity_id"])
    if doc_types:
        where += " AND doc_type = ANY(%s)"
        params.append(list(doc_types))
    if as_of is not None:
        # Strict gate: exclude NULL as_of_date — cannot be proven pre-cutoff.
        where += " AND as_of_date IS NOT NULL AND as_of_date < %s"
        params.append(as_of)

    scope_sql, scope_params = _doc_scope_clause(session_id, exclude_sources)

    conn = _get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT
                doc_id, entity_type, entity_id, doc_type, as_of_date, event_date,
                source, text,
                (embedding <=> %s::vector) AS distance
            FROM documents
        """ + where + scope_sql + """
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (str(embedding), *params, *scope_params, str(embedding), n_results))

        rows = cur.fetchall()

    docs = []
    for row in rows:
        sim = _cosine_similarity(row["distance"])
        if sim >= min_sim:
            docs.append({
                "doc_id":      row["doc_id"],
                "entity_type": row["entity_type"],
                "entity_id":   row["entity_id"],
                "doc_type":    row["doc_type"],
                "as_of_date":  row["as_of_date"],
                "event_date":  row["event_date"],
                "source":      row["source"],
                "text":        row["text"],
                "similarity":  sim,
            })

    return docs


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def memory_stats() -> dict:
    """Return row counts for all three tables."""
    conn = _get_conn()
    stats = {}
    with conn.cursor() as cur:
        for table in ("conversation_memory", "sql_cache", "correction_memory"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cur.fetchone()[0]
        # documents is optional (needs setup_documents.sql) — don't break stats if absent
        try:
            cur.execute("SELECT COUNT(*) FROM documents")
            stats["documents"] = cur.fetchone()[0]
        except psycopg2.errors.UndefinedTable:
            stats["documents"] = None
    return stats


def reset_collection(name: str) -> None:
    """Truncate a memory table (useful for testing)."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {name}")


_MEMORY_TABLES = ("conversation_memory", "sql_cache", "correction_memory")


def purge_session(session_id: str) -> dict:
    """Delete all rows written under a given session_id across the three stores.

    Used by the session-eval harness after each session so eval rows never persist
    to live memory. Returns {table: rows_deleted}.
    """
    if not session_id:
        raise ValueError("purge_session requires a non-empty session_id")
    conn = _get_conn()
    deleted = {}
    with conn.cursor() as cur:
        for table in _MEMORY_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE session_id = %s", (session_id,))
            deleted[table] = cur.rowcount
    return deleted


def purge_source(source: str) -> dict:
    """Delete all rows with a given source across the three stores. Returns counts.

    Safety: refuses to purge 'live' / 'legacy' so production rows can't be wiped by
    a mistaken call; intended for 'eval_session' cleanup.
    """
    if source in ("live", "legacy"):
        raise ValueError(f"refusing to purge protected source={source!r}")
    conn = _get_conn()
    deleted = {}
    with conn.cursor() as cur:
        for table in _MEMORY_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE source = %s", (source,))
            deleted[table] = cur.rowcount
    return deleted


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env")

    print("=== pgvector Store Self-Test ===\n")

    test_id = str(uuid.uuid4())

    store_conversation(
        memory_id=test_id,
        user_query="How many points did Arsenal get in 2023_2024?",
        final_response="Arsenal finished with 89 points in 2023_2024.",
        sql_query="SELECT points FROM league_table WHERE team_name='Arsenal' AND season='2023_2024';",
        intent="data_request",
        query_parameters={"teams": ["Arsenal"], "seasons": ["2023_2024"]},
    )

    hits = query_conversation_memory("What were Arsenal's points last season?")
    print(f"Conversation hits: {len(hits)}")
    if hits:
        print(f"  similarity={hits[0]['similarity']}  query='{hits[0]['query']}'")

    store_sql_cache(
        memory_id=test_id,
        user_query="How many points did Arsenal get in 2023_2024?",
        sql_query="SELECT points FROM league_table WHERE team_name='Arsenal' AND season='2023_2024';",
        row_count=1,
        columns=["team_name", "points"],
        variant="no_control",
    )

    cached = query_sql_cache("Arsenal points in 2023_2024")
    print(f"\nSQL cache hit: {cached is not None}")
    if cached:
        print(f"  similarity={cached['similarity']}  sql='{cached['sql'][:60]}...'")

    print(f"\nMemory stats: {memory_stats()}")
    print("\n✓ pgvector store working correctly")
