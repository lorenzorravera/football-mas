"""
Single-LLM baselines for the session-memory experiment (Phase C, C3).

Reconstructed from the till/agent_v5 single-LLM-+-tools design (that code is off-limits
to import and lives against a separate data layer). Two modes, chosen per the approved
"Both" decision:

  stateless : each turn is a fresh LLM+tool call with NO prior-turn context.
              Tests whether the MAS's structured memory adds carry-over a memoryless
              agent cannot have.
  history   : each turn receives the FULL prior conversation (questions, answers, and
              any error notes) in-context, like a normal chatbot. Tests whether the
              MAS's structured retrieval beats naive raw-history stuffing.

The "tool" is a single read-only SQL executor (SELECT/WITH only) over the same Aiven DB
the MAS queries — kept self-contained here (own psycopg2 read-only cursor) to avoid the
fragile `db.connection` import and stay inside Ethan/.

Token accounting reuses config's per-turn accumulator so single-LLM token_cost is
comparable to the MAS arms in the trajectory log.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Literal, Optional

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import call_llm, reset_token_usage, get_token_usage

# Schema context: reuse the MAS's loader (pulls the live schema). Fall back to a minimal
# hint if it can't load, so the baseline still runs.
try:
    from schema_loader import get_schema_context
    _SCHEMA = get_schema_context(include_views=True, include_indexes=False)
except Exception:
    _SCHEMA = "(schema unavailable — infer from standard Premier League tables)"

MAX_STEPS = 4  # max SQL round-trips before the model must answer

_SYSTEM = f"""You are a Premier League data assistant with ONE tool: a read-only SQL
executor over a PostgreSQL database (SELECT/WITH only).

Database schema:
{_SCHEMA}

Protocol — every reply MUST be exactly one of:
  SQL: <a single read-only SELECT/WITH query>
  ANSWER: <your final natural-language answer to the user's latest question>

Rules:
- The DB is multi-league; ALWAYS scope to the Premier League by joining competitions and
  filtering league_code = 'ENG-PL'. Season format is 'YYYY-YYYY' (e.g. '2023-2024').
- Issue SQL to get facts; once you have them, reply with ANSWER.
- You have at most {MAX_STEPS} SQL calls; then you must ANSWER with what you know.
"""

# Module-level read-only connection (lazy).
_ro_conn = None


def _get_ro_conn():
    global _ro_conn
    if _ro_conn is None or _ro_conn.closed:
        uri = os.getenv("DATABASE_URI")
        if not uri:
            raise ValueError("DATABASE_URI not set")
        _ro_conn = psycopg2.connect(uri)
        _ro_conn.set_session(readonly=True, autocommit=True)
    return _ro_conn


def _run_sql_readonly(sql: str, max_rows: int = 200) -> str:
    """Execute a read-only query; return a compact text rendering of the rows."""
    s = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        return "ERROR: only SELECT/WITH queries are allowed."
    try:
        conn = _get_ro_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(s)
            rows = cur.fetchmany(max_rows)
        if not rows:
            return "RESULT: (no rows)"
        cols = list(rows[0].keys())
        lines = [" | ".join(cols)]
        for r in rows:
            lines.append(" | ".join(str(r[c]) for c in cols))
        return "RESULT:\n" + "\n".join(lines)
    except Exception as exc:
        return f"ERROR: {exc}"


def _history_block(prior_turns: list[dict]) -> str:
    """Render prior turns (with any error notes) for the history baseline."""
    if not prior_turns:
        return ""
    parts = ["Conversation so far:"]
    for t in prior_turns:
        parts.append(f"User: {t.get('query','')}")
        if t.get("error_note"):
            parts.append(f"(note: a prior attempt errored — {t['error_note']})")
        parts.append(f"Assistant: {t.get('answer','')}")
    return "\n".join(parts) + "\n\n"


def run_single_llm(
    query: str,
    model: str = "claude",
    mode: Literal["stateless", "history"] = "stateless",
    prior_turns: Optional[list[dict]] = None,
) -> dict:
    """
    Answer one turn with a single LLM + the read-only SQL tool.

    prior_turns (history mode only): list of {query, answer, error_note?} for earlier turns.
    Returns {answer, sql_calls, n_steps, token_cost}.
    """
    reset_token_usage()
    convo = _history_block(prior_turns or []) if mode == "history" else ""
    user_msg = f"{convo}User question: {query}"

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    sql_calls: list[str] = []
    answer = ""
    for _ in range(MAX_STEPS + 1):
        reply = call_llm(messages, model_name=model, temperature=0.0).strip()
        messages.append({"role": "assistant", "content": reply})

        m = re.match(r"(?is)^\s*SQL:\s*(.+)$", reply)
        if m:
            sql = m.group(1).strip()
            sql_calls.append(sql)
            result = _run_sql_readonly(sql)
            messages.append({"role": "user", "content": result})
            continue

        m = re.match(r"(?is)^\s*ANSWER:\s*(.+)$", reply)
        answer = m.group(1).strip() if m else reply
        break

    return {
        "answer": answer,
        "sql_calls": sql_calls,
        "n_steps": len(sql_calls),
        "token_cost": get_token_usage().get("total", 0),
    }
