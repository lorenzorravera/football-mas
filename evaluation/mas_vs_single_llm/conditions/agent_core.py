"""
conditions/agent_core.py — a provider-agnostic native function-calling loop.

Used by the single-LLM-with-tools condition (and reusable elsewhere). Registers a chosen subset of
tools, lets the model call them, executes them, and feeds results back until the model produces a
final answer. Records the ordered tool_sequence + a self-contained trace.
"""

from __future__ import annotations

import json
import time

from config import call_llm, call_llm_tools, DEFAULT_SQL_TEMPERATURE
from tools.use_template import TOOL_REGISTRY


def _summarize(result) -> str:
    if isinstance(result, dict):
        if "error" in result:
            return f"error: {result['error']}"
        if "row_count" in result:
            return f"{result['row_count']} rows, cols={result.get('columns')}"
    return str(result)[:120]


def run_tool_agent(question: str, model: str, system_prompt: str, tool_names: list[str],
                   max_steps: int = 8, question_id: str = "", condition: str = "single_llm_tools") -> dict:
    t0 = time.time()
    tools = [TOOL_REGISTRY[n][1] for n in tool_names]
    fns = {n: TOOL_REGISTRY[n][0] for n in tool_names}

    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": question}]
    tool_seq: list[str] = []
    trace: list[dict] = []
    answer = ""
    prediction_vector = None   # captured if predict_match_outcome is called

    for step in range(max_steps):
        msg = call_llm_tools(messages, model=model, tools=tools, temperature=DEFAULT_SQL_TEMPERATURE)
        tcs = getattr(msg, "tool_calls", None)
        messages.append(msg.model_dump() if hasattr(msg, "model_dump")
                        else {"role": "assistant", "content": msg.content or ""})
        if not tcs:
            answer = msg.content or ""
            break
        for tc in tcs:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_seq.append(name)
            result = fns[name](**args) if name in fns else {"error": f"tool '{name}' not available"}
            if isinstance(result, dict) and all(k in result for k in ("home_win", "draw", "away_win")):
                prediction_vector = {k: result[k] for k in ("home_win", "draw", "away_win")}
            trace.append({"step": step, "tool": name, "args": args, "result": _summarize(result)})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, default=str)[:6000]})
    else:
        # hit max_steps without a final answer → force one
        answer = call_llm(messages + [{"role": "user", "content": "Give your final answer now, concisely."}],
                          model=model)

    return {
        "question_id": question_id, "question": question, "condition": condition, "model": model,
        "answer": answer, "tool_sequence": tool_seq, "trace": trace,
        "prediction_vector": prediction_vector,
        "latency_s": round(time.time() - t0, 2),
    }
