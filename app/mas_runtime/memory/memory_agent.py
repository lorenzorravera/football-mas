"""
Memory agent nodes for the LangGraph pipeline.

Updated for agent_v3 — uses pgvector on Aiven instead of local ChromaDB.
Two nodes wrap the existing pipeline:

  memory_retrieval_agent  (runs BEFORE manager)
  memory_store_agent      (runs AFTER synthesizer)

All storage calls are best-effort — failures are swallowed silently
so they never block the main pipeline.
"""

import os
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState
from memory.vector_store_pg import (
    query_conversation_memory,
    query_sql_cache,
    query_correction_memory,
    query_documents,
    store_conversation,
    store_sql_cache,
    store_correction,
)


def _cache_experiment() -> bool:
    """SQL-cache isolation mode: sql_cache stays live, but conversation_memory and
    correction_memory reads+writes are disabled so the cache is the ONLY active memory
    mechanism. Used by eval_cache_sweep.py. Default behavior is unaffected."""
    return os.getenv("EVAL_MODE") == "cache_experiment"


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def memory_retrieval_agent(state: AgentState) -> AgentState:
    """Pre-pipeline node: hydrate state with relevant memories from Aiven."""
    if "user_query" not in state:
        return state
    # Stamp a memory_id up front — BEFORE the eval_no_memory gate — so the trajectory
    # row for this turn always carries a query_id. The ablation control arm must stay
    # cost/latency-observable without any harness-side scaffolding.
    if not state.get("memory_id"):
        state["memory_id"] = str(uuid.uuid4())
    if state.get("eval_no_memory"):
        return state
    user_query = state["user_query"]

    # Namespacing (A1): when an eval session_id is set, retrieval is hard-scoped to that
    # session only; otherwise live reads exclude eval_session rows (the default in
    # query_*). session_id is None for normal production turns.
    session_id = state.get("session_id")

    try:
        # cache_experiment isolates sql_cache: skip conversation/correction reads entirely
        cache_exp = _cache_experiment()
        state["memory_context"] = [] if cache_exp else query_conversation_memory(
            user_query, n_results=3, session_id=session_id)

        # sql_cache bypassed under golden eval to prevent stale-SQL replay across runs
        cached = (query_sql_cache(user_query, session_id=session_id)
                  if os.getenv("EVAL_MODE") != "golden" else None)
        if cached:
            state["cached_sql"]     = cached["sql"]
            state["sql_cache_hit"]  = True
            state["sql_cache_meta"] = cached
        else:
            state["cached_sql"]     = None
            state["sql_cache_hit"]  = False
            state["sql_cache_meta"] = None

        state["memory_warnings"] = [] if cache_exp else query_correction_memory(
            user_query, n_results=2, session_id=session_id)

    except Exception:
        state["memory_context"]  = []
        state["cached_sql"]      = None
        state["sql_cache_hit"]   = False
        state["sql_cache_meta"]  = None
        state["memory_warnings"] = []

    # Narrative RAG (documents layer) — retrieved in its OWN guard so a missing
    # `documents` table (before setup_documents.sql is run) never collapses the
    # memory path above. Skipped under EVAL_MODE (golden / cache_experiment) so the
    # frozen benchmark experiments' token/latency/accuracy stay unperturbed.
    # No as_of gate here: qualitative retrieval may use post-hoc narrative. The
    # prediction path does its own as_of-gated retrieval (leak-safe).
    try:
        state["narrative_context"] = (
            query_documents(user_query, n_results=4) if not os.getenv("EVAL_MODE") else []
        )
    except Exception:
        state["narrative_context"] = []

    return state


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def memory_store_agent(state: AgentState) -> AgentState:
    """Post-pipeline node: persist the completed turn to Aiven."""
    if state.get("eval_no_memory"):
        return state
    import pandas as pd

    memory_id      = state.get("memory_id") or str(uuid.uuid4())
    user_query     = state["user_query"]
    final_response = state.get("final_response", "")
    sql_query      = state.get("sql_query", "")
    intent         = state.get("intent", "unknown")
    params         = state.get("query_parameters", {})
    error          = state.get("error")
    data_result    = state.get("data_result")

    # Namespacing (A1): writes are tagged with the turn's session_id + source so eval
    # rows can be retrieved session-scoped and purged afterwards. Defaults: no session,
    # source='live' (normal production turns).
    session_id     = state.get("session_id")
    source         = state.get("memory_source", "live")

    # ── 1. Conversation memory — only successful responses ────────────────
    #     (skipped under cache_experiment to isolate sql_cache as the sole memory)
    if final_response and not state.get("needs_clarification") and not error and not _cache_experiment():
        try:
            store_conversation(
                memory_id=memory_id,
                user_query=user_query,
                final_response=final_response,
                sql_query=sql_query or "",
                intent=intent,
                query_parameters=params,
                session_id=session_id,
                source=source,
            )
        except Exception:
            pass

    # ── 2. SQL cache — only on success with non-empty results ─────────────
    #     (skipped entirely under golden eval so runs never read/write stale SQL)
    if (
        os.getenv("EVAL_MODE") != "golden"
        and not error
        and sql_query
        and not sql_query.startswith("Function:")
        and data_result is not None
        and isinstance(data_result, pd.DataFrame)
        and not data_result.empty
    ):
        try:
            store_sql_cache(
                memory_id=memory_id,
                user_query=user_query,
                sql_query=sql_query,
                row_count=len(data_result),
                columns=list(data_result.columns),
                variant=state.get("variant", "unknown"),
                session_id=session_id,
                source=source,
            )
        except Exception:
            pass

    # ── 3. Correction memory — only on errors ────────────────────────────
    #     (skipped under cache_experiment so the 186 polluted rows don't grow)
    if error and not _cache_experiment():
        try:
            store_correction(
                memory_id=memory_id,
                user_query=user_query,
                error_type=state.get("error_stage", "unknown"),
                error_message=error,
                bad_sql=sql_query or "",
                stage=state.get("error_stage", "unknown"),
                session_id=session_id,
                source=source,
            )
        except Exception:
            pass

    return state
