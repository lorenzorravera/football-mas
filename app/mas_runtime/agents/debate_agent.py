"""
Debate Agent - Two independent SQL generation paths for higher confidence.

Sits between data_discovery and data_analyst in the graph.
Runs two SQL generation attempts independently, compares results.

WHEN IT FIRES:
- Only on cache misses (no high-confidence cached SQL available)
- Skipped entirely when sql_cache_hit=True with similarity >= 0.88

WHY:
- Running 2 LLM calls on every query doubles latency and cost
- Cache hits are already high-confidence — debate adds no value there
- Debate is most useful on novel queries where SQL generation is uncertain

If both paths agree  → injects winning SQL into state["cached_sql"] so
                       data_analyst fast-paths it (skips LLM generation)
If they disagree     → sets debate_agreed=False, data_analyst generates
                       its own SQL with extra caution via debate_hint

No graph cycle — all logic runs inside one node call.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState
from config import call_llm, get_agent_model
from schema_loader import get_schema_context
from db.connection import read_sql


def _generate_sql(user_query: str, params: dict, schema: str,
                  memory_warnings: list, temperature: float = 0.0) -> str | None:
    """
    Generate a single SQL query attempt.
    Returns SQL string or None on failure.
    """
    warnings_block = ""
    if memory_warnings:
        lines = "\n".join(
            f"  - [{w['stage']}] {w['error_message']}  (bad SQL: {w['bad_sql'][:100]})"
            for w in memory_warnings
        )
        warnings_block = f"\n⚠️  Past failures on similar queries — avoid these patterns:\n{lines}\n"

    prompt = f"""You are an expert SQL analyst for a Premier League PostgreSQL database.
{warnings_block}

Database Schema:
{schema}

User Query: "{user_query}"
Extracted Parameters: {params}

Generate a SQL query to answer this question.

CRITICAL RULES:
1. Use ONLY tables/columns from the schema above
2. Team names must match EXACTLY (e.g., "Man City" not "Manchester City")
3. Season format: "YYYY_YYYY" (e.g., "2023_2024")
4. ALWAYS use the season values from Extracted Parameters
5. For standings with points adjustments, use league_table view
6. match_team_stats has 2 rows per match (one per team)
7. Return ONLY the SQL query, no explanations

Return ONLY the SQL, nothing else."""

    model = get_agent_model("data_analyst")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=temperature)
        sql = response.strip()
        if sql.startswith("```"):
            lines = sql.split("\n")
            sql = "\n".join(lines[1:-1]) if len(lines) > 2 else sql
        sql = sql.replace("```sql", "").replace("```", "").strip()
        return sql if sql else None
    except Exception:
        return None


def _results_agree(df_a: pd.DataFrame, df_b: pd.DataFrame) -> bool:
    """
    Check if two DataFrames agree on key numeric values.
    Uses shape + sorted numeric column sums as a lightweight agreement check.
    """
    if df_a.empty and df_b.empty:
        return True
    if df_a.empty or df_b.empty:
        return False
    if df_a.shape != df_b.shape:
        return False

    try:
        nums_a = df_a.select_dtypes(include="number").sum().sort_index()
        nums_b = df_b.select_dtypes(include="number").sum().sort_index()
        if list(nums_a.index) != list(nums_b.index):
            return False
        return all(abs(a - b) < 0.01 for a, b in zip(nums_a, nums_b))
    except Exception:
        return False


def debate_agent(state: AgentState) -> AgentState:
    """
    Debate agent: two independent SQL paths, compare results.

    Skipped entirely on high-confidence cache hits to avoid doubling
    latency and cost on queries that are already well-served by memory.

    Args:
        state: Current agent state — expects data_discovery outputs populated

    Returns:
        Updated state with debate_agreed, debate_sql_a, debate_sql_b,
        and optionally cached_sql injected for data_analyst fast-path
    """
    # ── Guard: skip on upstream error ─────────────────────────────────────
    if state.get("error"):
        state["debate_agreed"] = False
        return state

    # ── Guard: skip on high-confidence cache hit ───────────────────────────
    # Cache hit with similarity >= 0.88 means memory already has a reliable
    # answer — running debate would double cost with no benefit
    cache_similarity = state.get("sql_cache_meta", {}).get("similarity", 0) or 0
    if state.get("sql_cache_hit") and cache_similarity >= 0.88:
        state["debate_agreed"] = True  # treat cache as pre-agreed
        state["debate_sql_a"]  = state.get("cached_sql", "")
        state["debate_sql_b"]  = state.get("cached_sql", "")
        return state

    user_query      = state["user_query"]
    params          = state.get("query_parameters", {})
    memory_warnings = state.get("memory_warnings", [])
    schema          = get_schema_context(include_views=True, include_indexes=False)

    # ── Path A: temperature=0.0 (deterministic) ───────────────────────────
    sql_a = _generate_sql(user_query, params, schema, memory_warnings, temperature=0.0)
    state["debate_sql_a"] = sql_a or ""

    # ── Path B: temperature=0.2 (slight variation) ────────────────────────
    sql_b = _generate_sql(user_query, params, schema, memory_warnings, temperature=0.2)
    state["debate_sql_b"] = sql_b or ""

    # ── If either failed, skip debate ─────────────────────────────────────
    if not sql_a or not sql_b:
        state["debate_agreed"] = False
        return state

    # ── Execute both ──────────────────────────────────────────────────────
    try:
        df_a = read_sql(sql_a)
    except Exception:
        df_a = pd.DataFrame()

    try:
        df_b = read_sql(sql_b)
    except Exception:
        df_b = pd.DataFrame()

    # ── Compare ───────────────────────────────────────────────────────────
    agreed = _results_agree(df_a, df_b)
    state["debate_agreed"] = agreed

    if agreed and not df_a.empty:
        # Inject winning SQL so data_analyst fast-paths it
        state["cached_sql"]     = sql_a
        state["sql_cache_hit"]  = False  # not from memory, from debate
        state["sql_cache_meta"] = {
            "similarity": 1.0,
            "row_count":  len(df_a),
            "columns":    list(df_a.columns),
            "variant":    "debate",
        }

    return state


if __name__ == "__main__":
    from state import create_initial_state

    print("=== Test: cache hit — debate should skip ===")
    s = create_initial_state("How many points did Arsenal get in 2023_2024?")
    s["sql_cache_hit"]  = True
    s["sql_cache_meta"] = {"similarity": 0.95}
    s["cached_sql"]     = "SELECT points FROM league_table WHERE team_name='Arsenal'"
    out = debate_agent(s)
    print(f"agreed={out['debate_agreed']}  skipped={'debate_sql_a' not in out or not out['debate_sql_a']}")

    print("\n=== Test: cache miss — debate should fire ===")
    s2 = create_initial_state("How many points did Arsenal get in 2023_2024?")
    s2["intent"]           = "data_request"
    s2["query_parameters"] = {"teams": ["Arsenal"], "seasons": ["2023_2024"]}
    s2["relevant_tables"]  = ["league_table"]
    s2["memory_warnings"]  = []
    out2 = debate_agent(s2)
    print(f"agreed={out2['debate_agreed']}")
    print(f"sql_a={out2.get('debate_sql_a', '')[:80]}")
    print(f"sql_b={out2.get('debate_sql_b', '')[:80]}")