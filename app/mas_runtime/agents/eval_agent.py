"""
Eval Agent - Post-response quality check against DB ground truth.

Sits between synthesizer and memory_store in the graph.

Responsibilities:
1. Check if final_response is consistent with data_result
2. Check if numbers in the response match values in data_result
3. If inconsistency detected → write to correction_memory automatically
4. Always passes through — never blocks the pipeline

Ground truth source: data_result (already fetched from DB).
No access to golden test set — no data leakage.
No LLM call — rule-based checks only to keep latency low.

State fields written:
  eval_score:      float 0.0-1.0  (1.0 = consistent, 0.0 = likely wrong)
  eval_correction: str            (description of detected issue, if any)
"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState


def _extract_numbers_from_text(text: str) -> list[float]:
    """Extract all numbers from a string."""
    return [float(n.replace(",", "")) for n in re.findall(r"\b\d[\d,]*\.?\d*\b", text)]


def _check_response_consistency(
    user_query: str,
    final_response: str,
    data_result,
    sql_query: str,
) -> tuple[float, str]:
    """
    Check if final_response is consistent with data_result.

    Returns:
        (score, issue_description)
        score=1.0 → consistent
        score=0.0 → likely wrong
        score=0.5 → uncertain
    """
    # ── Check 1: response claims data but result is empty ─────────────────
    if data_result is None or data_result.empty:
        denial_phrases = [
            "no data", "couldn't find", "not available", "no results",
            "no matches", "doesn't exist", "not in the database"
        ]
        response_lower = final_response.lower()
        if any(phrase in response_lower for phrase in denial_phrases):
            return 1.0, ""  # correctly acknowledged no data
        return 0.5, "Response may be fabricated — query returned no data from DB"

    # ── Check 2: numbers in response match numbers in data ─────────────────
    response_numbers = set(_extract_numbers_from_text(final_response))
    if not response_numbers:
        return 1.0, ""  # no numbers to verify

    # Get all numeric values from data_result
    try:
        data_numbers = set()
        for col in data_result.select_dtypes(include="number").columns:
            for val in data_result[col].dropna():
                data_numbers.add(round(float(val), 2))
    except Exception:
        return 1.0, ""  # can't check, pass through

    if not data_numbers:
        return 1.0, ""

    # Check if at least one response number appears in data
    matched = response_numbers & data_numbers
    if not matched:
        # Numbers in response don't match any DB values — likely hallucination
        return 0.0, (
            f"Numbers in response {sorted(response_numbers)[:5]} "
            f"don't match DB values {sorted(data_numbers)[:5]}. "
            f"Possible hallucination. SQL: {sql_query[:150]}"
        )

    return 1.0, ""


def eval_agent(state: AgentState) -> AgentState:
    """
    Eval agent: check response quality against DB ground truth.

    Args:
        state: Current agent state — expects final_response and data_result

    Returns:
        Updated state with eval_score and eval_correction.
        Writes to correction_memory if issue detected.
    """
    import os
    import uuid
    from memory.vector_store_pg import store_correction

    # ── Skip if upstream error or conversational ───────────────────────────
    if state.get("error"):
        state["eval_score"]      = 0.5
        state["eval_correction"] = ""
        return state

    if state.get("intent") == "conversational":
        state["eval_score"]      = 1.0
        state["eval_correction"] = ""
        return state

    # Prediction outputs are probabilities, not SQL facts — the SQL number-consistency
    # check below would mis-flag them. Handle predictions here (D3): if the realised
    # outcome is known (supplied by a backtest / post-match job via state['actual_outcome']),
    # score it and feed a miss into correction_memory for retrieve-before-forecast.
    if state.get("intent") == "prediction_match":
        actual = state.get("actual_outcome")
        md = state.get("prediction_metadata") or {}
        if actual and md.get("probabilities") and md.get("entity_id") is not None:
            try:
                from memory.prediction_feedback import record_outcome_delta
                record_outcome_delta(
                    md.get("task", "prediction"), md.get("entity", ""),
                    int(md["entity_id"]), probabilities=md["probabilities"],
                    actual_label=actual, model_version=md.get("model_version", "v1"),
                    session_id=state.get("session_id"),
                    source=state.get("memory_source", "live"),
                )
            except Exception:
                pass
        state["eval_score"]      = 1.0
        state["eval_correction"] = ""
        return state

    if state.get("needs_clarification"):
        state["eval_score"]      = 1.0
        state["eval_correction"] = ""
        return state

    user_query     = state["user_query"]
    final_response = state.get("final_response", "")
    data_result    = state.get("data_result")
    sql_query      = state.get("sql_query", "")

    # ── Run consistency check ──────────────────────────────────────────────
    score, issue = _check_response_consistency(
        user_query, final_response, data_result, sql_query
    )

    state["eval_score"]      = score
    state["eval_correction"] = issue

    # ── Write to correction_memory if issue detected ───────────────────────
    #     (skipped under cache_experiment so the 186 polluted rows don't grow)
    if score < 1.0 and issue and os.getenv("EVAL_MODE") != "cache_experiment":
        try:
            store_correction(
                memory_id  = str(uuid.uuid4()),
                user_query = user_query,
                error_type = "eval_agent",
                error_message = issue,
                bad_sql    = sql_query,
                stage      = "eval_agent",
                session_id = state.get("session_id"),
                source     = state.get("memory_source", "live"),
            )
        except Exception:
            pass  # best-effort — never block pipeline

    return state


if __name__ == "__main__":
    import pandas as pd
    from state import create_initial_state

    print("=== Test 1: consistent response ===")
    s = create_initial_state("How many points did Arsenal get in 2023_2024?")
    s["intent"]         = "data_request"
    s["final_response"] = "Arsenal finished with 89 points in 2023_2024."
    s["data_result"]    = pd.DataFrame({"team_name": ["Arsenal"], "points": [89]})
    s["sql_query"]      = "SELECT points FROM league_table WHERE team_name='Arsenal'"
    out = eval_agent(s)
    print(f"score={out['eval_score']}  issue='{out['eval_correction']}'")

    print("\n=== Test 2: hallucinated numbers ===")
    s2 = create_initial_state("How many points did Arsenal get in 2023_2024?")
    s2["intent"]         = "data_request"
    s2["final_response"] = "Arsenal finished with 95 points in 2023_2024."
    s2["data_result"]    = pd.DataFrame({"team_name": ["Arsenal"], "points": [89]})
    s2["sql_query"]      = "SELECT points FROM league_table WHERE team_name='Arsenal'"
    out2 = eval_agent(s2)
    print(f"score={out2['eval_score']}  issue='{out2['eval_correction']}'")

    print("\n=== Test 3: empty result, response denies correctly ===")
    s3 = create_initial_state("Show me Norwich stats for 2024-25")
    s3["intent"]         = "data_request"
    s3["final_response"] = "Norwich is not in the database for 2024-25."
    s3["data_result"]    = pd.DataFrame()
    s3["sql_query"]      = "SELECT * FROM league_table WHERE team_name='Norwich'"
    out3 = eval_agent(s3)
    print(f"score={out3['eval_score']}  issue='{out3['eval_correction']}'")