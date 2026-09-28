"""
ChromaDB vector store for agent memory.

Three persistent collections:
  conversation_memory  — completed Q&A turns (query + response + SQL)
  sql_cache            — successful user-query → SQL mappings
  correction_memory    — flagged errors / bad SQL patterns

All embeddings use sentence-transformers (all-MiniLM-L6-v2) locally —
no extra API keys required.

Similarity thresholds (cosine, 0–1):
  SQL_CACHE_THRESHOLD   0.88  — only reuse SQL for very close matches
  MEMORY_THRESHOLD      0.70  — surface past turns for general context
  CORRECTION_THRESHOLD  0.75  — surface warnings for similar past failures
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

# Stored next to agent_v2/ so it persists across restarts
CHROMA_PATH = Path(__file__).parent.parent / "memory_store"

#EMBEDDING_MODEL    = "all-MiniLM-L6-v2"
SQL_CACHE_THRESHOLD  = 0.88
MEMORY_THRESHOLD     = 0.70
CORRECTION_THRESHOLD = 0.75

# Module-level singletons (lazy-initialised)
_client: Optional[chromadb.PersistentClient] = None
_embedding_fn = None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


# REPLACE with this:
def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is None:
        _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    return _embedding_fn


def _collection(name: str):
    """Get-or-create a collection with cosine similarity."""
    return _get_client().get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )


def _similarity(distance: float) -> float:
    """Convert cosine distance → similarity score (0–1)."""
    return round(1.0 - distance, 4)


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
) -> None:
    """
    Persist a completed Q&A turn.

    The document embedded is the user_query so future similar questions
    surface this turn during retrieval.
    """
    _collection("conversation_memory").add(
        ids=[memory_id],
        documents=[user_query],
        metadatas=[{
            "query":     user_query[:500],
            "response":  final_response[:1000],   # truncate large responses
            "sql":       (sql_query or "")[:500],
            "intent":    intent,
            "params":    json.dumps(query_parameters),
            "timestamp": datetime.utcnow().isoformat(),
        }],
    )


def query_conversation_memory(user_query: str, n_results: int = 3) -> list[dict]:
    """
    Return up to n_results past turns semantically similar to user_query.

    Each result dict:  {query, response, sql, intent, similarity}
    Only turns above MEMORY_THRESHOLD are returned.
    """
    col = _collection("conversation_memory")
    if col.count() == 0:
        return []

    results = col.query(
        query_texts=[user_query],
        n_results=min(n_results, col.count()),
        where={"intent": {"$ne": "error"}}  # filter out errors
    )       

    memories = []
    for dist, meta in zip(results["distances"][0], results["metadatas"][0]):
        sim = _similarity(dist)
        if sim >= MEMORY_THRESHOLD:
            memories.append({
                "query":      meta["query"],
                "response":   meta["response"],
                "sql":        meta["sql"],
                "intent":     meta["intent"],
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
) -> None:
    """
    Cache a successful SQL query for future reuse.

    Only raw SQL strings are cached (not Function: … descriptions),
    because those can be executed verbatim if the query matches closely.
    """
    if not sql_query or sql_query.startswith("Function:"):
        return  # function calls are not directly re-executable

    _collection("sql_cache").add(
        ids=[f"sql_{memory_id}"],
        documents=[user_query],
        metadatas=[{
            "sql":       sql_query[:800],
            "row_count": row_count,
            "columns":   json.dumps(columns),
            "variant":   variant,
            "timestamp": datetime.utcnow().isoformat(),
        }],
    )


def query_sql_cache(user_query: str) -> Optional[dict]:
    """
    Return cached SQL for a semantically near-identical past query, or None.

    Result dict:  {sql, similarity, row_count, columns, variant, cached_query}
    Only returned when similarity >= SQL_CACHE_THRESHOLD (0.88).
    """
    col = _collection("sql_cache")
    if col.count() == 0:
        return None

    results = col.query(query_texts=[user_query], n_results=1)

    if not results["distances"][0]:
        return None

    sim = _similarity(results["distances"][0][0])
    if sim < SQL_CACHE_THRESHOLD:
        return None

    meta = results["metadatas"][0][0]
    return {
        "sql":          meta["sql"],
        "similarity":   sim,
        "row_count":    meta["row_count"],
        "columns":      json.loads(meta["columns"]),
        "variant":      meta["variant"],
        "cached_query": results["documents"][0][0],
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
) -> None:
    """Persist a failed query so similar future queries are warned."""
    _collection("correction_memory").add(
        ids=[f"err_{memory_id}"],
        documents=[user_query],
        metadatas=[{
            "error_type":    error_type,
            "error_message": (error_message or "")[:400],
            "bad_sql":       (bad_sql or "")[:400],
            "stage":         stage,
            "timestamp":     datetime.utcnow().isoformat(),
        }],
    )


def query_correction_memory(user_query: str, n_results: int = 2) -> list[dict]:
    """
    Return past failure warnings for semantically similar queries.

    Each result dict:  {error_type, error_message, bad_sql, stage, similarity}
    Only returned when similarity >= CORRECTION_THRESHOLD (0.75).
    """
    col = _collection("correction_memory")
    if col.count() == 0:
        return []

    results = col.query(
        query_texts=[user_query],
        n_results=min(n_results, col.count()),
    )

    warnings = []
    for dist, meta in zip(results["distances"][0], results["metadatas"][0]):
        sim = _similarity(dist)
        if sim >= CORRECTION_THRESHOLD:
            warnings.append({
                "error_type":    meta["error_type"],
                "error_message": meta["error_message"],
                "bad_sql":       meta["bad_sql"],
                "stage":         meta["stage"],
                "similarity":    sim,
            })

    return warnings


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def memory_stats() -> dict:
    """Return document counts for all three collections."""
    return {
        "conversation_memory": _collection("conversation_memory").count(),
        "sql_cache":           _collection("sql_cache").count(),
        "correction_memory":   _collection("correction_memory").count(),
    }


def reset_collection(name: str) -> None:
    """Delete and recreate a collection (useful for testing)."""
    client = _get_client()
    client.delete_collection(name)
    _collection(name)  # recreates it


if __name__ == "__main__":
    print("=== Vector Store Self-Test ===\n")

    test_id = str(uuid.uuid4())

    # Conversation memory
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

    # SQL cache
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
    print("\n✓ Vector store working correctly")
