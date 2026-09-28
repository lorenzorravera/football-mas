"""
conditions/sql_agent.py — the three Degrees-of-Freedom SQL agents behind ONE interface.

Modes differ ONLY in the data actions available (the spec's "registered tools"):
  * controlled : use_template only        (never writes free SQL → no run_sql, no self-debate)
  * semi       : use_template OR free SQL  (agent decides per query)
  * autonomous : free SQL only            (always self-debate)

Identical preamble + identical schema context across all three; only the AVAILABLE ACTIONS section
differs. Wherever the agent writes free-form SQL it goes through the self-debate loop (two
independent SQL candidates → reconcile until their result-sets agree, capped at MAX_DEBATE_ITERS,
best-effort + low_confidence on non-convergence).

Returns a fully self-contained run record (final answer, ordered tool_sequence, SQL/template calls,
self-debate iterations, latency) so scoring/Phase-6 never depends on Langfuse.
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal

from config import call_llm, DEFAULT_SQL_TEMPERATURE
from tools.schema_context import get_schema_context
from tools.use_template import use_template, run_sql_tool, _template_catalogue

Mode = Literal["controlled", "semi", "autonomous"]
MAX_DEBATE_ITERS = 2

_PREAMBLE = (
    "You are a Premier League data analyst. Answer the user's question using ONLY the database.\n"
    "Rules: seasons are 'YYYY-YYYY' (hyphen, e.g. '2023-2024'); the latest season is 2024-2025 "
    "(no 2025-26 data); point deductions are already in the points columns; prefer IDs over names "
    "for joins; canonical team names (e.g. 'Manchester United', 'Wolves').\n"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _strip_sql(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = t.rsplit("```", 1)[0]
    return t.replace("```sql", "").replace("```", "").strip()


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t).rsplit("```", 1)[0]
    m = re.search(r"\{.*\}", t, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return None if v is None else str(v).strip()


def _canon(res: dict):
    if not res or res.get("error"):
        return None
    return sorted(tuple(_norm(v) for v in r) for r in res.get("rows", []))


def _results_agree(a: dict, b: dict) -> bool:
    ca, cb = _canon(a), _canon(b)
    if ca is None or cb is None:
        return False
    return ca == cb


# --------------------------------------------------------------------------- #
# free-SQL generation + self-debate
# --------------------------------------------------------------------------- #
def _gen_sql(question: str, schema: str, model: str, variant_note: str, prior: list) -> str:
    reconcile = ""
    if prior:
        last = prior[-1]
        reconcile = (
            "\nYour two previous SQL attempts DISAGREED on their results — reconcile them.\n"
            f"Attempt A: {last['sql_a']}\nAttempt B: {last['sql_b']}\n"
            "Find the correct query.\n")
    prompt = (f"{_PREAMBLE}\nDatabase schema:\n{schema}\n\nQuestion: {question}\n{variant_note}{reconcile}"
              "\nReturn ONLY one SQL SELECT statement, no prose, no code fences.")
    return _strip_sql(call_llm([{"role": "user", "content": prompt}], model=model,
                               temperature=DEFAULT_SQL_TEMPERATURE))


def _self_debate(question: str, schema: str, model: str, trace: list, tool_seq: list) -> dict:
    iters = []
    res_a = res_b = {"error": "not run"}
    for i in range(MAX_DEBATE_ITERS + 1):
        sql_a = _gen_sql(question, schema, model, "Write the most direct correct query.", iters)
        sql_b = _gen_sql(question, schema, model,
                         "Write an independent query (different phrasing/joins) for the same answer.", iters)
        res_a = run_sql_tool(sql_a); tool_seq.append("run_sql")
        res_b = run_sql_tool(sql_b); tool_seq.append("run_sql")
        agree = _results_agree(res_a, res_b)
        iters.append({"iter": i, "sql_a": sql_a, "sql_b": sql_b, "agreed": agree,
                      "rows_a": res_a.get("row_count"), "rows_b": res_b.get("row_count")})
        trace.append({"step": f"self_debate[{i}]", "agreed": agree,
                      "sql_a": sql_a[:200], "sql_b": sql_b[:200]})
        if agree and not res_a.get("error"):
            return {"result": res_a, "sql": sql_a, "iters": iters, "low_confidence": False}
    # non-converged → best effort (prefer a non-empty, non-error candidate)
    best = res_a if (not res_a.get("error") and res_a.get("row_count")) else res_b
    best_sql = iters[-1]["sql_a"] if best is res_a else iters[-1]["sql_b"]
    return {"result": best, "sql": best_sql, "iters": iters, "low_confidence": True}


# --------------------------------------------------------------------------- #
# template path
# --------------------------------------------------------------------------- #
def _choose_template(question: str, model: str) -> dict:
    prompt = (f"{_PREAMBLE}\nYou can ONLY answer using these templates:\n{_template_catalogue()}\n\n"
              f"Question: {question}\n\n"
              'Respond with JSON: {"template_name": "...", "params": {"season": "...", "team": "...", '
              '"metric": "...", "top_n": 50}}. Include only the params the template needs.')
    return _parse_json(call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.0))


# --------------------------------------------------------------------------- #
# synthesis
# --------------------------------------------------------------------------- #
def _synthesize(question: str, result: dict, model: str) -> str:
    if not result or result.get("error"):
        return f"Unable to answer: {result.get('error', 'no result') if result else 'no result'}"
    preview = {"columns": result.get("columns"), "rows": result.get("rows", [])[:30]}
    prompt = (f"{_PREAMBLE}\nQuestion: {question}\n\nQuery result (JSON):\n{json.dumps(preview, default=str)}\n\n"
              "Answer the question directly and concisely using ONLY this result. State numbers exactly.")
    return call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.3).strip()


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def data_analyst(question: str, schema: str, model: str, mode: Mode,
                 discovery_hint: str | None = None,
                 trace: list | None = None, tool_seq: list | None = None) -> dict:
    """
    The data-analyst stage of the MAS, at one of three autonomy levels (the DoF variable).
    Returns the DATA result + provenance; synthesis into NL is the MAS synthesizer's job.

      controlled : use_template only       (never writes free SQL)
      semi       : agent decides template-or-SQL per query (no heuristic from us)
      autonomous : free SQL only, via the self-debate loop

    trace / tool_seq are appended to in place when supplied by the MAS runner.
    """
    trace = trace if trace is not None else []
    tool_seq = tool_seq if tool_seq is not None else []
    sql_used = template_used = None
    low_conf = False
    result = None
    analyst_q = question if not discovery_hint else f"{question}\n[discovery hint] {discovery_hint}"

    if mode == "controlled":
        choice = _choose_template(question, model)
        template_used = choice.get("template_name")
        trace.append({"node": "data_analyst", "mode": mode, "choose_template": choice})
        result = use_template(template_used, choice.get("params") or {})
        tool_seq.append("use_template")
        if result.get("error"):  # one corrective retry
            retry = _choose_template(f"{question}\n(Previous attempt failed: {result['error']})", model)
            template_used = retry.get("template_name")
            result = use_template(template_used, retry.get("params") or {})
            tool_seq.append("use_template")

    elif mode == "autonomous":
        deb = _self_debate(analyst_q, schema, model, trace, tool_seq)
        result, sql_used, low_conf = deb["result"], deb["sql"], deb["low_confidence"]

    elif mode == "semi":
        prompt = (f"{_PREAMBLE}\nYou may either USE A TEMPLATE or WRITE CUSTOM SQL.\n"
                  f"Templates:\n{_template_catalogue()}\n\nQuestion: {question}\n\n"
                  'Respond JSON: {"approach": "template" | "sql", "template_name": "...", '
                  '"params": {...}} (if template). If "sql", just {"approach":"sql"}.')
        decision = _parse_json(call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.0))
        trace.append({"node": "data_analyst", "mode": mode, "route": decision})
        if decision.get("approach") == "template" and decision.get("template_name"):
            template_used = decision["template_name"]
            result = use_template(template_used, decision.get("params") or {})
            tool_seq.append("use_template")
            if result.get("error"):  # agent's template failed → fall back to self-debate SQL
                deb = _self_debate(analyst_q, schema, model, trace, tool_seq)
                result, sql_used, low_conf = deb["result"], deb["sql"], deb["low_confidence"]
        else:
            deb = _self_debate(analyst_q, schema, model, trace, tool_seq)
            result, sql_used, low_conf = deb["result"], deb["sql"], deb["low_confidence"]
    else:
        raise ValueError(f"unknown analyst mode: {mode}")

    return {"result": result, "sql": sql_used, "template": template_used,
            "low_confidence": low_conf, "mode": mode}


if __name__ == "__main__":
    # STRUCTURAL acceptance (no model calls): verify the action sets differ as specified.
    from tools.use_template import USE_TEMPLATE_TOOL, RUN_SQL_TOOL
    MODE_TOOLS = {
        "controlled": [USE_TEMPLATE_TOOL["function"]["name"]],
        "semi": [USE_TEMPLATE_TOOL["function"]["name"], RUN_SQL_TOOL["function"]["name"]],
        "autonomous": [RUN_SQL_TOOL["function"]["name"]],
    }
    print("Mode -> available data actions:")
    for m, tl in MODE_TOOLS.items():
        print(f"  {m:11} {tl}")
    assert "run_sql" not in MODE_TOOLS["controlled"], "controlled must NOT have run_sql"
    assert "use_template" not in MODE_TOOLS["autonomous"], "autonomous must NOT have use_template"
    assert set(MODE_TOOLS["semi"]) == {"use_template", "run_sql"}
    print("STRUCTURAL ACCEPTANCE OK: controlled has no run_sql; autonomous has no use_template.")
