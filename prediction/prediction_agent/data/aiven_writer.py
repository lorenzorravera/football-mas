"""
Aiven writer: persist predictions into the `computed_metrics` table.

The metadata describes computed_metrics as a flexible model/output store:
  metric_id (UUID), entity_type, entity_id, metric_name, metric_value (JSONB),
  parameters (JSONB), computed_at, source_query

We use it as the predictions sink. One write pattern:

  entity_type='match'
  entity_id=<game_id>
  metric_name='predicted_outcome_v1'  (versioned per model)
  metric_value={"home_win": 0.52, "draw": 0.24, "away_win": 0.24, "confidence": 0.52}
  parameters={"features": [...], "model_artefact": "match_outcome_v1.pkl"}

The agent's prediction_node calls store_prediction() after each forecast.
Later the eval agent reads from this table to compute post-match calibration.

CRITICAL: there is a UNIQUE constraint on (entity_type, entity_id, metric_name,
parameters). To support re-predictions (e.g. agent gets called twice for the
same match), use ON CONFLICT DO UPDATE.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

log = logging.getLogger(__name__)


@contextmanager
def _connection() -> Iterator:
    """Same connection logic as the loader — prefer STATS_DATABASE_URI,
    fall back to DATABASE_URI."""
    import psycopg2
    uri = os.environ.get("STATS_DATABASE_URI") or os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError(
            "Neither STATS_DATABASE_URI nor DATABASE_URI is set."
        )
    conn = psycopg2.connect(uri)
    try:
        yield conn
    finally:
        conn.close()


def store_prediction(entity_type: str, entity_id: int,
                     metric_name: str, metric_value: dict,
                     parameters: Optional[dict] = None,
                     source_query: Optional[str] = None,
                     ) -> None:
    """
    Upsert a prediction into computed_metrics.

    `entity_type` examples: 'match', 'player', 'transfer'.
    `metric_name` should be versioned: 'predicted_outcome_v1',
    'predicted_player_goals_v1', etc. This lets ablations live side by side
    (v1 with odds, v1_no_odds) without overwriting each other.
    """
    parameters = parameters or {}
    query = """
        INSERT INTO computed_metrics
            (entity_type, entity_id, metric_name, metric_value, parameters, source_query)
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s)
        ON CONFLICT (entity_type, entity_id, metric_name, parameters)
        DO UPDATE SET
            metric_value = EXCLUDED.metric_value,
            computed_at = now(),
            source_query = EXCLUDED.source_query
    """
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (
                entity_type, entity_id, metric_name,
                json.dumps(metric_value),
                json.dumps(parameters),
                source_query,
            ))
        conn.commit()
    log.debug("Stored prediction: %s/%s/%s", entity_type, entity_id, metric_name)


def fetch_predictions(entity_type: str, metric_name: str,
                      entity_ids: Optional[list[int]] = None) -> list[dict]:
    """
    Read predictions back. Used by the eval agent for post-match calibration.

    Returns a list of dicts: [{entity_id, metric_value, parameters, computed_at}].
    """
    if entity_ids:
        query = """
            SELECT entity_id, metric_value, parameters, computed_at
            FROM computed_metrics
            WHERE entity_type = %s AND metric_name = %s
              AND entity_id = ANY(%s)
            ORDER BY entity_id
        """
        params: tuple = (entity_type, metric_name, entity_ids)
    else:
        query = """
            SELECT entity_id, metric_value, parameters, computed_at
            FROM computed_metrics
            WHERE entity_type = %s AND metric_name = %s
            ORDER BY entity_id
        """
        params = (entity_type, metric_name)

    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [
        {
            "entity_id": r[0],
            "metric_value": r[1],   # already a dict (JSONB)
            "parameters": r[2],
            "computed_at": r[3],
        }
        for r in rows
    ]
