"""
Synthesizer Agent - Generate final natural language response.

Responsibilities:
1. Take data results (and visualization if present)
2. Generate natural language explanation
3. Answer the user's original question
4. Provide context and insights
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState
from config import call_llm, get_agent_model


def _synth_max_tokens():
    """Cap synthesizer output during the cache experiment (its costliest call).
    Returns None in normal operation so default behavior is unchanged."""
    return 500 if os.getenv("EVAL_MODE") == "cache_experiment" else None


def _format_narrative(narrative_context, max_docs: int = 4, max_chars: int = 700) -> str:
    """Format retrieved `documents` passages for prompt injection. Empty string
    when there is no narrative context (so the caller can branch on it)."""
    if not narrative_context:
        return ""
    blocks = []
    for i, d in enumerate(narrative_context[:max_docs], 1):
        src = d.get("source", "") or ""
        txt = (d.get("text", "") or "")[:max_chars].strip()
        blocks.append(f"[{i}] ({src})\n{txt}")
    return "\n\n".join(blocks)


def synthesizer_agent(state: AgentState) -> AgentState:
    """
    Synthesizer agent: generate final natural language response.

    Args:
        state: Current agent state with all previous outputs

    Returns:
        Updated state with final_response
    """
    user_query = state["user_query"]
    intent = state.get("intent", "conversational")
    data_result = state.get("data_result")
    sql_query = state.get("sql_query", "")
    viz_type = state.get("viz_type")
    error = state.get("error")

    # Pass through clarification questions without re-synthesizing
    if state.get("needs_clarification"):
        return state

    # Handle errors
    if error:
        state["final_response"] = error
        return state

    # Handle conversational intent (no data needed)
    if intent == "conversational":
        prompt = f"""You are a helpful Premier League analytics assistant.

The user asked: "{user_query}"

This is a conversational query that doesn't require data analysis.

Respond naturally and helpfully. If they're greeting you, greet back. If they're asking off-topic questions, politely redirect them to ask about Premier League statistics.

Keep your response concise (2-3 sentences max)."""

        model = get_agent_model("synthesizer")
        messages = [{"role": "user", "content": prompt}]
        response = call_llm(messages, model=model, temperature=0.3, max_tokens=_synth_max_tokens())

        state["final_response"] = response.strip()
        return state

    # Handle qualitative intent (narrative/explanatory — answered from the documents
    # RAG layer, no SQL). Grounded: answer ONLY from retrieved passages, never invent.
    if intent == "qualitative":
        passages = _format_narrative(state.get("narrative_context", []))
        if not passages:
            state["final_response"] = (
                "I don't have any written background on that in my narrative knowledge "
                "base yet, so I can't answer it reliably. You could ask for a specific "
                "statistic instead, which I can pull from the database."
            )
            return state

        prompt = f"""You are a Premier League analytics assistant answering a QUALITATIVE question.

The user asked: "{user_query}"

Answer using ONLY the retrieved passages below.

Ground every sentence in the passages. Do NOT state any specific detail — a scoreline, a
competition stage/round (e.g. "semi-final", "quarter-final"), a date, a number, a transfer
fee, a manager or player name — unless it appears explicitly in the passages. If a detail is
not there, omit it or say the passages don't specify it. Do not fill gaps from prior
knowledge. Before finishing, drop any claim you cannot point to in the text above.

Retrieved passages:
{passages}

Write a concise, well-structured answer (3-6 sentences) grounded strictly in the passages
above. Do not cite passage numbers or mention "retrieved passages" — just answer naturally."""

        model = get_agent_model("synthesizer")
        messages = [{"role": "user", "content": prompt}]
        try:
            # temperature 0 for qualitative: minimise associative drift beyond the passages.
            response = call_llm(messages, model=model, temperature=0.0, max_tokens=_synth_max_tokens())
            state["final_response"] = response.strip()
        except Exception as e:
            state["final_response"] = f"I couldn't generate a response: {str(e)}"
            state["error"] = str(e)
            state["error_stage"] = "synthesizer"
        return state

    # Handle data_request or full_pipeline
    if data_result is None or data_result.empty:
        state["final_response"] = (
            "I couldn't find any data matching your query. "
            "Please try rephrasing or check if the teams/seasons exist in our database."
        )
        return state

    # ── Memory context: surface relevant past turns ─────────────────── ← MEMORY
    memory_context = state.get("memory_context", [])
    memory_block = ""
    if memory_context:
        ctx_lines = "\n".join(
            f"  Q: {m['query']}\n  A: {m['response'][:200]}"
            for m in memory_context[:2]
        )
        memory_block = f"""
Relevant past interactions (for continuity — do NOT repeat these verbatim):
{ctx_lines}

"""

    # Build synthesis prompt
    data_preview = data_result.head(20).to_string()
    data_shape = f"{data_result.shape[0]} rows, {data_result.shape[1]} columns"

    # ── Prediction enrichment (Phase 2): only for forecast turns. Attaches the
    #    model's own top driving factors + as_of-gated narrative CONTEXT. The
    #    narrative is deliberately framed as background, NOT a model input (the
    #    model uses only structured features). Empty/absent for plain data turns,
    #    so ordinary data answers are unchanged. ──────────────────────────────
    prediction_meta = state.get("prediction_metadata") or {}
    explanation_block = ""
    narrative_block = ""
    if prediction_meta:
        expl = prediction_meta.get("explanation") or {}
        factors = expl.get("top_factors") or []
        if factors:
            fl = "; ".join(f"{f['feature']} ({f['direction']})" for f in factors[:5])
            explanation_block = (
                f"\nModel's top driving factors "
                f"(method: {expl.get('method', 'n/a')}): {fl}\n")
        narrative = _format_narrative(state.get("narrative_context", []))
        if narrative:
            narrative_block = (
                "\nPre-match narrative context (RETRIEVED TEXT — background shown "
                "ALONGSIDE the forecast; the model did NOT use it, so do not present it "
                "as a model input):\n" + narrative + "\n")

    prompt = f"""You are a Premier League analytics assistant.

The user asked: "{user_query}"

You queried the database and found this data:

Data ({data_shape}):
{data_preview}

SQL Query Used:
{sql_query}
{explanation_block}{narrative_block}
{f"Visualization: A {viz_type} chart was generated." if viz_type else ""}

{memory_block}Generate a natural language response that:
1. Directly answers the user's question
2. Highlights key findings from the data
3. Provides relevant context or insights
4. Is concise and easy to understand (3-5 sentences)

Important:
- Use ONLY the data shown above (no training data knowledge)
- State numbers precisely as they appear in the data
- If the data is surprising or interesting, mention it
- Don't mention the SQL query in your response
- Don't say "based on the data" - just state the facts
{"- If driving factors are given, briefly name the top 1-2. If narrative context is given, you MAY add it as background but make clear it is context, not something the model used." if prediction_meta else ""}

Example:

Query: "How many points did Arsenal get in 2023_2024?"
Data: points = 89
Response: "Arsenal finished the 2023_2024 season with 89 points, securing second place in the Premier League. This was a strong performance, just 2 points behind the champions."

Now generate your response."""

    model = get_agent_model("synthesizer")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=0.3, max_tokens=_synth_max_tokens())
        state["final_response"] = response.strip()
    except Exception as e:
        state["final_response"] = f"I found the data but couldn't generate a response: {str(e)}"
        state["error"] = str(e)
        state["error_stage"] = "synthesizer"

    return state


if __name__ == "__main__":
    # Test the synthesizer agent
    from state import create_initial_state
    import pandas as pd

    # Test with data
    test_data = pd.DataFrame({
        "team_name": ["Arsenal"],
        "points": [89]
    })

    test_state = create_initial_state("How many points did Arsenal get in 2023_2024?")
    test_state["intent"] = "data_request"
    test_state["data_result"] = test_data
    test_state["sql_query"] = "SELECT team_name, points FROM league_table WHERE team_name = 'Arsenal' AND season = '2023_2024';"

    print("Testing Synthesizer Agent...")
    result = synthesizer_agent(test_state)

    print(f"\nFinal Response:\n{result.get('final_response', 'N/A')}")

    # Test conversational
    conv_state = create_initial_state("Hello!")
    conv_state["intent"] = "conversational"
    conv_result = synthesizer_agent(conv_state)

    print(f"\nConversational Response:\n{conv_result.get('final_response', 'N/A')}")
