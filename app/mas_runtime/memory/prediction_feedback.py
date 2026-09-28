"""
D3 — post-outcome correction loop for predictions.

Two halves:
  1. persist_prediction()  — write each forecast to computed_metrics (the universal sink),
     so it can later be compared to the realised outcome. Also exposes fetch_prior() for
     retrieve-before-forecast.
  2. record_outcome_delta() — once the actual outcome is known (a finished fixture / a
     completed season, supplied by a backtest or a post-match job), score the forecast
     (Brier) and, if it was confidently wrong, write a note into correction_memory so the
     prediction agent is warned on similar future forecasts.

Connection uses DATABASE_URI directly (the package's aiven_writer prefers a STATS URI that
is a placeholder in this env). correction_memory writes reuse the namespaced store_correction
(source tag + session scope), so prediction misses live alongside SQL corrections.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

# Make `memory` importable whether this file is imported as memory.prediction_feedback
# (agent runtime) or run directly as a script (self-test).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.vector_store_pg import store_correction


def _conn():
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError("DATABASE_URI not set")
    c = psycopg2.connect(uri)
    c.autocommit = True
    return c


def persist_prediction(task: str, entity: str, entity_id: int, *,
                       metric_value: dict, parameters: Optional[dict] = None,
                       entity_type: str = "team") -> None:
    """Upsert a forecast into computed_metrics. Best-effort (never raises to caller)."""
    parameters = parameters or {}
    try:
        conn = _conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO computed_metrics
                    (entity_type, entity_id, metric_name, metric_value, parameters, computed_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (entity_type, entity_id, metric_name, parameters)
                DO UPDATE SET metric_value = EXCLUDED.metric_value,
                              computed_at = EXCLUDED.computed_at
            """, (entity_type, int(entity_id), task,
                  json.dumps({**metric_value, "entity": entity}),
                  json.dumps(parameters), datetime.now(UTC)))
        conn.close()
    except Exception:
        pass


def fetch_prior(task: str, entity_id: int, entity_type: str = "team") -> Optional[dict]:
    """Most recent stored forecast for (entity, task), or None. Retrieve-before-forecast."""
    try:
        conn = _conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT metric_value, parameters, computed_at
                FROM computed_metrics
                WHERE entity_type = %s AND entity_id = %s AND metric_name = %s
                ORDER BY computed_at DESC LIMIT 1
            """, (entity_type, int(entity_id), task))
            row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _brier(probs: dict, actual_label: str) -> float:
    """Multiclass Brier for a single forecast given the realised class label."""
    return round(sum((p - (1.0 if k == actual_label else 0.0)) ** 2
                     for k, p in probs.items()), 4)


def record_outcome_delta(task: str, entity: str, entity_id: int, *,
                         probabilities: dict, actual_label: str,
                         model_version: str = "v1", session_id: Optional[str] = None,
                         source: str = "live", miss_threshold: float = 0.4) -> dict:
    """
    Score a forecast against the realised outcome and persist the delta. If the model was
    confidently wrong (P(actual) < miss_threshold), write a correction so similar future
    forecasts are warned. Returns the delta dict. Used by backtests / post-match jobs.
    """
    p_actual = float(probabilities.get(actual_label, 0.0))
    brier = _brier(probabilities, actual_label)
    delta = {"task": task, "entity": entity, "actual": actual_label,
             "p_actual": round(p_actual, 4), "brier": brier,
             "predicted": max(probabilities, key=probabilities.get) if probabilities else None}

    persist_prediction(task + "_delta", entity, entity_id,
                       metric_value=delta, parameters={"model_version": model_version})

    if p_actual < miss_threshold:
        try:
            store_correction(
                memory_id=f"pred_{task}_{entity_id}_{actual_label}",
                user_query=f"{task} forecast for {entity}",
                error_type="prediction_miss",
                error_message=(f"{task}: predicted '{delta['predicted']}' but actual was "
                               f"'{actual_label}' (P(actual)={p_actual:.2f}, Brier={brier:.2f})"),
                bad_sql="", stage="prediction_agent",
                session_id=session_id, source=source,
            )
        except Exception:
            pass
    return delta


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)

    persist_prediction("season_class", "Test FC", 999999,
                       metric_value={"p_top4": 0.6, "p_relegation": 0.1})
    print("prior:", fetch_prior("season_class", 999999))
    d = record_outcome_delta("season_class", "Test FC", 999999,
                             probabilities={"top4": 0.6, "relegation": 0.1, "mid_table": 0.3},
                             actual_label="relegation")
    print("delta:", d)
    # cleanup
    conn = _conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM computed_metrics WHERE entity_id = 999999")
        cur.execute("DELETE FROM correction_memory WHERE id = 'pred_season_class_999999_relegation'")
    conn.close()
    print("✓ prediction_feedback self-test ok")
