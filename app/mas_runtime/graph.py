"""
LangGraph orchestration for multi-agent system - agent_v4.

Graph topology:

  memory_retrieval
       |
       v
    manager --------------------------------+
       |  (data_request / full_pipeline)     |  (prediction_match)
       v                                     v
  data_discovery                       prediction_agent
       |                                     |
       v                                     |
  data_analyst                              |
  (validation + retry internal)             |
       |                                     |
       v                                     |
   visualizer                               |
       |                                     |
       v                                     |
  synthesizer <------------------------------+   (also: conversational / error)
       |
       v
  eval_agent
  (checks response vs DB ground truth,
   writes to correction_memory)
       |
       v
  memory_store
       |
       v
      END
"""

from langgraph.graph import StateGraph, END

from state import AgentState
from agents import (
    manager_agent,
    data_discovery_agent,
    data_analyst_agent,
    visualizer_agent,
    synthesizer_agent,
    prediction_agent,
)
from agents.eval_agent import eval_agent
from memory import memory_retrieval_agent, memory_store_agent


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def route_after_manager(state: AgentState) -> str:
    if state.get("error"):
        return "synthesizer"
    intent = state.get("intent", "conversational")
    if intent == "prediction_match":
        return "prediction_agent"
    if intent in ["data_request", "full_pipeline"]:
        return "data_discovery"
    # qualitative + conversational answer straight from the synthesizer
    # (qualitative uses narrative_context from the documents RAG layer; no SQL).
    return "synthesizer"


def route_after_data_analyst(state: AgentState) -> str:
    if state.get("error"):
        return "synthesizer"
    if state.get("intent") == "full_pipeline":
        return "visualizer"
    return "synthesizer"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def create_graph(variant: str = "semi_control") -> StateGraph:
    """
    Create the compiled LangGraph workflow.

    Args:
        variant: Data analyst variant - "full_control" | "semi_control" | "no_control"

    Returns:
        Compiled StateGraph ready for execution
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("memory_retrieval", memory_retrieval_agent)
    workflow.add_node("manager",          manager_agent)
    workflow.add_node("data_discovery",   data_discovery_agent)
    workflow.add_node("data_analyst",     lambda s: data_analyst_agent(s, variant=variant))
    workflow.add_node("visualizer",       visualizer_agent)
    workflow.add_node("prediction_agent", prediction_agent)
    workflow.add_node("synthesizer",      synthesizer_agent)
    workflow.add_node("eval_agent",       eval_agent)
    workflow.add_node("memory_store",     memory_store_agent)

    workflow.set_entry_point("memory_retrieval")

    workflow.add_edge("memory_retrieval", "manager")

    workflow.add_conditional_edges(
        "manager",
        route_after_manager,
        {
            "data_discovery":   "data_discovery",
            "prediction_agent": "prediction_agent",
            "synthesizer":      "synthesizer",
        },
    )

    workflow.add_edge("data_discovery", "data_analyst")

    workflow.add_conditional_edges(
        "data_analyst",
        route_after_data_analyst,
        {
            "visualizer":  "visualizer",
            "synthesizer": "synthesizer",
        },
    )

    # Prediction agent flows straight to the synthesizer (no viz step for v1).
    workflow.add_edge("prediction_agent", "synthesizer")

    workflow.add_edge("visualizer",   "synthesizer")
    workflow.add_edge("synthesizer",  "eval_agent")
    workflow.add_edge("eval_agent",   "memory_store")
    workflow.add_edge("memory_store", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_agent(
    user_query: str,
    variant: str = "semi_control",
    verbose: bool = False,
    initial_state: dict = None,
    model: str = None,
    experiment: str = "live",
    condition: str = "mas",
    bandit=None,
    bandit_context: str = "data_request",
) -> dict:
    import time
    from state import create_initial_state
    from config import reset_token_usage, get_token_usage, set_model_override

    if initial_state is None:
        initial_state = create_initial_state(user_query)

    # ── Phase E: optional router bandit picks the (model, variant) arm ──────────
    # Off by default (bandit=None) so existing callers are unaffected. Intent isn't
    # known until the manager runs, so selection uses `bandit_context` as the context
    # hint; after the turn we update the bandit under the *realized* intent + reward.
    # The chosen arm overrides the `model`/`variant` args for this turn.
    if bandit is not None:
        model, variant = bandit.select(bandit_context)
        if verbose:
            print(f"[bandit] context={bandit_context} -> model={model} variant={variant}")

    initial_state["variant"] = variant

    # A3: per-turn token accounting + model arm. reset BEFORE any agent runs.
    reset_token_usage()
    set_model_override(model)  # None clears -> agents use AGENT_DEFAULTS

    graph = create_graph(variant=variant)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Query: {user_query}")
        print(f"{'='*60}\n")

    node_order: list[str] = []
    _t0 = time.perf_counter()
    final_state = None
    for step_output in graph.stream(initial_state):
        node_name = list(step_output.keys())[0]
        node_order.append(node_name)
        if verbose:
            if node_name == "memory_retrieval":
                node_state = step_output[node_name]
                ctx  = len(node_state.get("memory_context", []))
                warn = len(node_state.get("memory_warnings", []))
                hit  = node_state.get("sql_cache_hit", False)
                print(f"✓ MEMORY_RETRIEVAL  context={ctx}  warnings={warn}  sql_cache={'HIT' if hit else 'miss'}")
            elif node_name == "data_analyst":
                node_state = step_output[node_name]
                passed  = node_state.get("validation_passed")
                retries = node_state.get("validation_retries", 0)
                status  = "PASS" if passed else "FAIL"
                print(f"✓ DATA_ANALYST  validation={status}  retries={retries}")
            elif node_name == "prediction_agent":
                node_state = step_output[node_name]
                if node_state.get("error"):
                    print(f"✓ PREDICTION_AGENT  error={node_state['error'][:80]}")
                else:
                    md = node_state.get("prediction_metadata", {})
                    probs = md.get("probabilities", {})
                    print(f"✓ PREDICTION_AGENT  H={probs.get('home_win', 0):.2f} "
                          f"D={probs.get('draw', 0):.2f} A={probs.get('away_win', 0):.2f}")
            elif node_name == "eval_agent":
                node_state = step_output[node_name]
                score  = node_state.get("eval_score", 1.0)
                issue  = node_state.get("eval_correction", "")
                status = "OK" if score == 1.0 else ("WARN" if score == 0.5 else "FAIL")
                print(f"✓ EVAL_AGENT  status={status}  score={score}" + (f"  issue={issue[:60]}" if issue else ""))
            else:
                print(f"✓ {node_name.upper()} completed")

        final_state = step_output[node_name]

    if verbose:
        print(f"\n{'='*60}")
        print("Final Response:")
        print(f"{'='*60}")
        print(final_state.get("final_response", "No response generated"))
        print()

    # ── A3: emit one trajectory_log row (best-effort; never breaks the turn) ──
    # Written here (NOT in a graph node) so blobs/DataFrames never go through state.
    try:
        _emit_trajectory(
            final_state or initial_state,
            user_query=user_query,
            variant=variant,
            model=model,
            experiment=experiment,
            condition=condition,
            latency_ms=int((time.perf_counter() - _t0) * 1000),
            token_usage=get_token_usage(),
            node_order=node_order,
        )
    except Exception:
        pass

    # ── Phase E: update the bandit with the realized (intent, arm, reward) ──────
    # Best-effort; a learning failure must never break the turn. Reward is shaped
    # from the turn's eval_score (+ optional thumbs/cost/latency via the bandit's
    # own weights). Keyed on the *realized* intent, not the selection hint.
    if bandit is not None and final_state is not None:
        try:
            bandit.observe(
                final_state.get("intent"), model, variant,
                eval_score=final_state.get("eval_score"),
                token_cost=int(get_token_usage().get("total", 0)),
                latency_ms=int((time.perf_counter() - _t0) * 1000),
            )
        except Exception:
            pass

    return final_state


def _emit_trajectory(state, *, user_query, variant, model, experiment, condition,
                     latency_ms, token_usage, node_order) -> None:
    """Assemble + write the per-turn trajectory row. Best-effort; failures are swallowed
    by the caller. Captures only JSON-safe scalars (no DataFrames)."""
    from memory.trajectory_log import log_trajectory, build_arm

    intent = state.get("intent")
    # `model` is the configured arm value; agents resolve it via the ContextVar override.
    model_arm = model or "claude"
    context_features = {
        "n_chars": len(user_query or ""),
        "n_words": len((user_query or "").split()),
        "is_pl_related": state.get("is_premier_league_related"),
        "sql_cache_hit": state.get("sql_cache_hit"),
        "n_memory_warnings": len(state.get("memory_warnings", []) or []),
    }
    full_trajectory = {
        "nodes": node_order,
        "sql_query": (state.get("sql_query") or "")[:500],
        "validation_retries": state.get("validation_retries"),
        "validation_passed": state.get("validation_passed"),
        "needs_clarification": state.get("needs_clarification"),
        "error_stage": state.get("error_stage"),
        "prediction_type": (state.get("query_parameters", {}) or {}).get("prediction_type"),
    }
    log_trajectory({
        "query_id":   state.get("memory_id"),
        "session_id": state.get("session_id"),
        "turn_index": state.get("turn_index"),
        "experiment": experiment,
        "condition":  condition,
        "model":      model_arm,
        "variant":    variant,
        "intent":     intent,
        "arm":        build_arm(model_arm, variant, intent),
        "context_features":     context_features,
        "full_trajectory_json": full_trajectory,
        "latency_ms": latency_ms,
        "token_cost": int(token_usage.get("total", 0)),
        "eval_score": state.get("eval_score"),
    })


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from memory.vector_store import memory_stats

    print("Testing LangGraph Multi-Agent System (agent_v4 - with prediction)\n")
    print(f"Memory store stats: {memory_stats()}\n")

    test_queries = [
        "Hello!",
        "How many points did Arsenal get in 2023_2024?",
        "Show me a chart of Man City's points over the last 3 seasons",
        "Predict Arsenal vs Chelsea",
        "Will Liverpool beat Man City?",
    ]

    for query in test_queries:
        result = run_agent(query, verbose=True)
        if result.get("intent"):
            print(f"Intent:        {result['intent']}")
        if result.get("eval_score") is not None:
            print(f"Eval score:    {result['eval_score']}")
        if result.get("eval_correction"):
            print(f"Eval issue:    {result['eval_correction'][:100]}")
        print("\n" + "="*60 + "\n")

    print(f"Memory store stats after run: {memory_stats()}")
