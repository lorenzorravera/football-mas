"""
Trajectory log (A2) — per-turn substrate for the router bandit (Phase E) and the
Phase-5 preference model.

One row per turn, written from graph.run_agent() AFTER the LangGraph stream completes
(NOT threaded through AgentState — LangGraph v1.0.10 cannot reliably serialize large
blobs / DataFrames in state). Thumbs arrive later (async, from the Chainlit feedback
handler) and patch the row in place.

Logging-first: this records from day one so the bandit/preference-model data exists
before either is built. Writes are best-effort — a logging failure must never break a
user turn — but unlike memory we surface a one-line warning so silent data loss is
visible during development.

Schema: see memory/migrations/add_trajectory_log.sql
"""

import json
import logging
from datetime import datetime, UTC
from typing import Optional

from memory.vector_store_pg import _get_conn

log = logging.getLogger(__name__)


def build_arm(model: Optional[str], variant: Optional[str], intent: Optional[str]) -> str:
    """Canonical arm key for the bandit: 'model|variant|intent'."""
    return f"{model or 'unknown'}|{variant or 'unknown'}|{intent or 'unknown'}"


# Columns the table accepts, in insert order. query_id is required.
_COLUMNS = (
    "query_id", "session_id", "turn_index", "experiment", "condition",
    "model", "variant", "intent", "arm",
    "context_features", "full_trajectory_json",
    "thumbs", "latency_ms", "token_cost", "eval_score",
)
_JSONB_COLUMNS = {"context_features", "full_trajectory_json"}


def log_trajectory(record: dict) -> bool:
    """
    Upsert one trajectory row. `record` may contain any subset of _COLUMNS; query_id
    is required. `arm` is derived from model/variant/intent if not supplied.

    Returns True on success, False on failure (best-effort — never raises).
    """
    query_id = record.get("query_id")
    if not query_id:
        log.warning("trajectory_log: skipping record with no query_id")
        return False

    record = dict(record)
    record.setdefault("arm", build_arm(
        record.get("model"), record.get("variant"), record.get("intent")))
    record.setdefault("ts", datetime.now(UTC))

    cols = [c for c in _COLUMNS if c in record] + ["ts"]
    placeholders = ", ".join("%s::jsonb" if c in _JSONB_COLUMNS else "%s" for c in cols)
    values = [
        json.dumps(record[c]) if c in _JSONB_COLUMNS else record[c]
        for c in cols
    ]
    # ON CONFLICT update everything except the PK so a re-emit refreshes the row.
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "query_id")

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO trajectory_log ({', '.join(cols)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT (query_id) DO UPDATE SET {updates}",
                values,
            )
        return True
    except Exception as exc:  # best-effort, but visible
        log.warning("trajectory_log: insert failed for %s: %s", query_id, exc)
        return False


def update_thumbs(query_id: str, score: int) -> bool:
    """Patch the thumbs (+1/-1) onto an existing trajectory row. Best-effort."""
    if not query_id:
        return False
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE trajectory_log SET thumbs = %s WHERE query_id = %s",
                (score, query_id),
            )
            return cur.rowcount > 0
    except Exception as exc:
        log.warning("trajectory_log: thumbs update failed for %s: %s", query_id, exc)
        return False


if __name__ == "__main__":
    import uuid
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env")

    qid = str(uuid.uuid4())
    ok = log_trajectory({
        "query_id": qid,
        "experiment": "selftest",
        "condition": "mas",
        "model": "claude", "variant": "no_control", "intent": "data_request",
        "context_features": {"n_words": 5},
        "full_trajectory_json": {"nodes": ["manager", "data_analyst"]},
        "latency_ms": 1234, "token_cost": 567, "eval_score": 1.0,
    })
    print("log_trajectory:", ok)
    print("update_thumbs:", update_thumbs(qid, 1))
