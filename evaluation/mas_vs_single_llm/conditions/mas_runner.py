"""
conditions/mas_runner.py — drives the approved v5 Multi-Agent System (memory OFF).

Topology (eval_agent CUT; memory OFF — constraint 10):
    manager  →  data_discovery  →  data_analyst(mode)  →  synthesizer

The data_analyst runs at one of three autonomy levels (`analyst_mode`):
  * DoF experiment      : run this MAS with analyst_mode ∈ {controlled, semi, autonomous}; everything
                          else (manager/discovery/synthesizer) held identical → isolates analyst autonomy.
  * MAS-vs-single experiment : run this MAS at ONE chosen analyst_mode (the best from DoF) vs the two
                          single-LLM conditions.

Implemented as a deterministic function pipeline mirroring the approved LangGraph topology.
Sets a Langfuse trace context per run so all nested model calls group under one trace.
"""

from __future__ import annotations

import json
import time

from config import (call_llm, set_trace_context, clear_trace_context, get_token_usage,
                    LANGFUSE_ENABLED)
from conditions.sql_agent import _PREAMBLE, _parse_json, _synthesize, data_analyst
from tools.schema_context import get_schema_context
from tools.predict_match_outcome import predict_match_outcome

MEMORY_ENABLED = False   # constraint 10 — no memory read/write anywhere in this runner


def _manager(question: str, model: str) -> dict:
    prompt = (f"{_PREAMBLE}\nClassify and extract for this Premier League question.\n"
              f"Question: {question}\n\n"
              'Respond JSON: {"intent": "data_request" | "prediction_match" | "conversational", '
              '"seasons": ["YYYY-YYYY", ...], "teams": [...], "metrics": [...], '
              '"home_team": "...", "away_team": "...", "match_date": "YYYY-MM-DD"}. '
              "Use intent='prediction_match' ONLY when asked to forecast/predict a specific fixture's "
              "outcome; then fill home_team, away_team and match_date. "
              "Resolve 'this/current season' to 2024-2025 (latest data).")
    return _parse_json(call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.0))


def _synthesize_prediction(question: str, pred: dict, model: str) -> str:
    if not pred or pred.get("error"):
        return f"Unable to produce a prediction: {pred.get('error', 'no result') if pred else 'no result'}"
    prompt = (f"{_PREAMBLE}\nQuestion: {question}\n\nThe match-outcome model returned (probabilities):\n"
              f"{json.dumps(pred)}\n\nAnswer the question using these probabilities. State the three "
              "probabilities (home win / draw / away win) explicitly and the most likely outcome.")
    return call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.3).strip()


def _data_discovery(question: str, manager_out: dict, schema: str, model: str) -> dict:
    prompt = (f"{_PREAMBLE}\nDatabase schema:\n{schema}\n\nQuestion: {question}\n"
              f"Manager context: {json.dumps(manager_out)}\n\n"
              'Respond JSON: {"relevant_tables": [...], "notes": "short join/grain guidance"}.')
    return _parse_json(call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.0))


def run_mas(question: str, model: str, analyst_mode: str = "autonomous",
            experiment: str = "mas_vs_single", question_id: str = "", repeat: int = 0) -> dict:
    t0 = time.time()
    condition = f"dof_{analyst_mode}" if experiment == "dof" else "mas"
    trace_id = f"{experiment}|{condition}|{model}|{question_id}|r{repeat}"
    set_trace_context(trace_id, trace_name=condition, tags=[experiment, condition, str(model)])
    try:
        schema = get_schema_context()
        trace: list = []
        tool_seq: list = []

        mgr = _manager(question, model)
        trace.append({"node": "manager", "out": mgr})

        if mgr.get("intent") == "conversational":
            answer = call_llm([{"role": "user", "content": f"{_PREAMBLE}\n{question}"}], model=model)
            return _record(question_id, question, experiment, condition, analyst_mode, model,
                           answer, tool_seq, trace, t0, repeat, low_conf=False, mgr=mgr)

        if mgr.get("intent") == "prediction_match":
            # Prediction node (sibling to data_analyst): call the trained model via the tool.
            # The tool itself does the data→features retrieval, so the node is the prediction agent.
            home, away, date = mgr.get("home_team"), mgr.get("away_team"), mgr.get("match_date")
            pred = predict_match_outcome(home, away, match_date=date, season=(mgr.get("seasons") or [None])[0])
            tool_seq.append("predict_match_outcome")
            trace.append({"node": "prediction_agent", "fixture": [home, away, date], "prediction": pred})
            answer = _synthesize_prediction(question, pred, model)
            trace.append({"node": "synthesizer", "answer": answer[:160]})
            pv = {k: pred[k] for k in ("home_win", "draw", "away_win")} if not pred.get("error") else None
            return _record(question_id, question, experiment, condition, analyst_mode, model,
                           answer, tool_seq, trace, t0, repeat, low_conf=bool(pred.get("error")),
                           mgr=mgr, prediction_vector=pv)

        disc = _data_discovery(question, mgr, schema, model)
        trace.append({"node": "data_discovery", "out": disc})
        hint = f"relevant tables: {disc.get('relevant_tables')}; {disc.get('notes', '')}"

        da = data_analyst(question, schema, model, analyst_mode, discovery_hint=hint,
                          trace=trace, tool_seq=tool_seq)
        trace.append({"node": "data_analyst", "mode": analyst_mode,
                      "sql": (da["sql"] or "")[:200], "template": da["template"],
                      "low_confidence": da["low_confidence"]})

        answer = _synthesize(question, da["result"], model)
        trace.append({"node": "synthesizer", "answer": answer[:160]})
        return _record(question_id, question, experiment, condition, analyst_mode, model,
                       answer, tool_seq, trace, t0, repeat,
                       low_conf=da["low_confidence"], sql=da["sql"], template=da["template"],
                       result=da["result"], mgr=mgr)
    finally:
        clear_trace_context()


def _record(qid, question, experiment, condition, analyst_mode, model, answer, tool_seq, trace, t0,
            repeat, low_conf=False, sql=None, template=None, result=None, mgr=None,
            prediction_vector=None) -> dict:
    return {
        "question_id": qid, "question": question, "experiment": experiment, "condition": condition,
        "analyst_mode": analyst_mode, "model": model, "repeat": repeat,
        "memory_enabled": MEMORY_ENABLED, "langfuse_enabled": LANGFUSE_ENABLED,
        "langfuse_trace_id": f"{experiment}|{condition}|{model}|{qid}|r{repeat}",
        "answer": answer, "tool_sequence": tool_seq, "sql": sql, "template": template,
        "low_confidence": low_conf, "intent": (mgr or {}).get("intent"),
        "prediction_vector": prediction_vector,
        "result_columns": (result or {}).get("columns"),
        "result_rows": (result or {}).get("rows"),
        "result_row_count": (result or {}).get("row_count"),
        "trace": trace, "token_usage": get_token_usage(),
        "latency_s": round(time.time() - t0, 2),
    }


if __name__ == "__main__":
    print("MAS topology: manager -> data_discovery -> data_analyst(mode) -> synthesizer")
    print(f"memory_enabled = {MEMORY_ENABLED}; langfuse_enabled = {LANGFUSE_ENABLED}")
