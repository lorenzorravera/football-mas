"""
AgentState schema for the multi-agent graph.

This state flows through all nodes in the LangGraph pipeline:
memory_retrieval -> Manager -> Data Discovery -> Data Analyst -> Visualizer -> Synthesizer -> memory_store
                                       \
                                        -> Prediction Agent -> Synthesizer  (intent == prediction_match)

Memory fields (populated by memory_retrieval_agent, consumed by other agents):
  memory_id        - UUID for this turn; used by memory_store_agent when persisting
  memory_context   - list of semantically similar past Q&A turns
  cached_sql       - raw SQL reused from the sql_cache collection (or None)
  sql_cache_hit    - True when a cached SQL was found above threshold
  sql_cache_meta   - full cache metadata dict {similarity, row_count, columns, variant}
  memory_warnings  - list of past failure notes for similar queries

Prediction fields (populated by prediction_agent, consumed by synthesizer/eval/memory_store):
  prediction_metadata - dict with model version, feature values, probabilities, confidence.
                        The prediction_agent writes its tabular result into `data_result`
                        (the same field data_analyst uses) so the synthesizer, eval_agent
                        and memory_store need no special-casing.
"""

from typing import TypedDict, Optional, Literal, Any
import pandas as pd

# Intent types for routing.
# - conversational:  greetings, off-topic
# - data_request:    SQL retrospective via data_analyst
# - full_pipeline:   SQL retrospective + visualization (pre-set by app.py)
# - prediction_match: match outcome forecast via prediction_agent
# - qualitative:     explanatory/narrative question answered from the documents
#                    (RAG) layer — no SQL, routed straight to the synthesizer
IntentType = Literal["conversational", "data_request", "full_pipeline",
                     "prediction_match", "qualitative"]


class AgentState(TypedDict, total=False):
    """
    Shared state that flows through all agent nodes.

    Flow:
    0. memory_retrieval: Populates memory_* fields
    1. Manager: Sets intent, validates PL-related, extracts params
    2a. (data_request / full_pipeline) Data Discovery -> Data Analyst -> [Visualizer] -> Synthesizer
    2b. (prediction_match) Prediction Agent -> Synthesizer
    3. Synthesizer: Sets final_response  (uses memory_context for continuity)
    4. eval_agent: checks response vs ground truth, writes to correction_memory
    5. memory_store: Persists turn
    """

    # -- User input --
    user_query: str

    # -- Manager outputs --
    intent: IntentType                      # conversational | data_request | full_pipeline | prediction_match
    is_premier_league_related: bool         # Must be True to proceed
    query_parameters: dict                  # Extracted entities (teams, seasons, etc.)

    # -- Data Discovery outputs --
    relevant_tables: list[str]              # Tables needed for the query
    relevant_columns: dict[str, list[str]]  # {table: [columns]}

    # -- Data Analyst outputs --
    sql_query: str                          # Generated SQL (or "Function: ..." / "PREDICTION: ..." sentinel)
    data_result: Optional[Any]              # Query result (or 1-row prediction DataFrame)

    # -- Visualizer outputs --
    viz_html: Optional[str]                 # Plotly HTML (synthesizer context)
    viz_figure: Optional[Any]               # Plotly Figure for cl.Plotly rendering
    viz_type: Optional[str]                 # Chart type used

    # -- Prediction agent outputs --
    # The prediction agent writes its result into `data_result` (same field as
    # data_analyst) so the synthesizer and eval don't need special handling.
    # It also writes a sentinel into `sql_query` for memory_store, plus this
    # structured metadata dict for the eval agent / post-match evaluation.
    prediction_metadata: Optional[dict]     # {model_version, features, probabilities, confidence}

    # -- Synthesizer output --
    final_response: str                     # Natural language response

    # -- Error handling --
    error: Optional[str]                    # Error message if something fails
    error_stage: Optional[str]              # Which agent encountered the error

    # -- Clarification --
    needs_clarification: Optional[bool]     # True when agent needs more info from user

    # -- Memory fields (populated by memory_retrieval_agent) --
    memory_id: Optional[str]                # UUID for this turn
    memory_context: list[dict]             # Similar past Q&A turns
    cached_sql: Optional[str]               # Reusable SQL from sql_cache (or None)
    sql_cache_hit: bool                     # True when cached_sql was found
    sql_cache_meta: Optional[dict]          # Cache metadata {similarity, row_count, ...}
    memory_warnings: list[dict]            # Past failure notes for similar queries

    # -- Narrative / RAG fields (populated by memory_retrieval_agent from `documents`) --
    narrative_context: list[dict]           # Retrieved narrative passages (content RAG)

    # -- Memory namespacing (A1) — used by the session-eval harness --
    session_id: Optional[str]               # eval session id; scopes memory reads/writes
    memory_source: Optional[str]            # row tag: 'live' (default) | 'eval_session' | ...
    turn_index: Optional[int]               # 0-based position of this turn within a session
    eval_no_memory: bool                    # ablation control: True disables memory read+write
                                            # for this turn. MUST be declared here — an undeclared
                                            # key is silently dropped by LangGraph and the gate no-ops.

    # -- Runtime metadata --
    variant: Optional[str]                  # data_analyst variant, stored for memory_store

    # -- Debate fields --
    debate_agreed: Optional[bool]
    debate_sql_a:  Optional[str]
    debate_sql_b:  Optional[str]

    # -- Validation fields (populated by validation logic in data_analyst) --
    validation_passed:  Optional[bool]      # True when result answers the query
    validation_retries: Optional[int]       # Number of retries attempted (max 2)
    validation_hint:    Optional[str]       # Hint injected into data_analyst on retry

    # -- Eval fields (populated by eval_agent) --
    eval_score:      Optional[float]        # 1.0=consistent, 0.5=uncertain, 0.0=likely wrong
    eval_correction: Optional[str]          # description of detected issue
    actual_outcome:  Optional[str]          # realised label injected by a backtest / post-match job;
                                            # eval_agent scores the forecast against it and feeds a miss
                                            # into correction_memory. MUST be declared or LangGraph drops it.


def create_initial_state(user_query: str) -> AgentState:
    """
    Create initial state from user query.

    Memory fields are initialised to empty defaults; memory_retrieval_agent
    will populate them before the main pipeline runs.

    Args:
        user_query: The user's question

    Returns:
        Initial AgentState
    """
    return {
        "user_query": user_query,
        "is_premier_league_related": False,
        "relevant_tables": [],
        "relevant_columns": {},
        "query_parameters": {},
        "error": None,
        # Memory defaults (overwritten by memory_retrieval_agent)
        "memory_id": None,
        "memory_context": [],
        "cached_sql": None,
        "sql_cache_hit": False,
        "sql_cache_meta": None,
        "memory_warnings": [],
        "narrative_context": [],
        # Memory namespacing (A1): defaults = normal live turn, no eval session.
        "session_id": None,
        "memory_source": "live",
        "turn_index": None,
        "eval_no_memory": False,   # memory ON by default; the ablation harness sets True
        "variant": None,
        "validation_passed":  False,
        "validation_retries": 0,
        "validation_hint":    "",
        "debate_agreed": None,
        "debate_sql_a": "",
        "debate_sql_b": "",
        "eval_score": 1.0,
        "eval_correction": "",
        # Prediction defaults
        "prediction_metadata": None,
    }
