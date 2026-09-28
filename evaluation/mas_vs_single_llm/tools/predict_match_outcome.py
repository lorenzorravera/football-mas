"""
predict_match_outcome — REAL match-outcome prediction tool (Phase 7).

Wraps the teammate's trained model in `prediction_agent/` (imported READ-ONLY — never edited).
Pipeline, mirroring training for train/inference parity:
  (home_team, away_team, match_date)
    → resolve team_ids
    → causal feature row from build_match_features over full history (cached)
    → MatchOutcomePredictor.predict_from_features  (artefacts/match_outcome_v1.pkl, no-odds live model)
    → {home_win, draw, away_win, confidence, model_version}

The signature/schema is the locked tool interface registered IDENTICALLY by the MAS prediction node
and the single-LLM+tools condition. `match_date` was added (the model is causal — it needs the date).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, TypedDict

from dotenv import load_dotenv

# Repo layout: till/agent_v5/tools/this.py → repo root is parents[3]; prediction_agent lives there.
_REPO = Path(__file__).resolve().parents[3]
_PRED_PKG = _REPO / "prediction_agent"
_ARTEFACT = _PRED_PKG / "artefacts" / "match_outcome_v1.pkl"   # no-odds / live model (Path C)
if str(_PRED_PKG) not in sys.path:
    sys.path.insert(0, str(_PRED_PKG))

# DATABASE_URI for the teammate's aiven_loader (read-only).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class MatchOutcomeProbabilities(TypedDict):
    home_win: float
    draw: float
    away_win: float


TOOL_SCHEMA = {
    "name": "predict_match_outcome",
    "description": (
        "Predict probabilities of each outcome (home win / draw / away win) for a Premier League "
        "fixture, using the trained match-outcome model. Returns three probabilities summing to 1.0 "
        "plus the model's confidence. Provide the match_date (the model is causal — it uses only data "
        "before that date)."),
    "input_schema": {
        "type": "object",
        "properties": {
            "home_team": {"type": "string", "description": "Home team canonical name, e.g. 'Manchester United'."},
            "away_team": {"type": "string", "description": "Away team canonical name, e.g. 'Fulham'."},
            "match_date": {"type": "string", "description": "Fixture date 'YYYY-MM-DD' (e.g. '2024-08-16')."},
            "season": {"type": "string", "description": "Optional season 'YYYY-YYYY'."},
        },
        "required": ["home_team", "away_team", "match_date"],
    },
}

# Module-level caches (built once per process).
_predictor = None
_feature_table = None   # pandas DataFrame of causal features for ALL historical fixtures
_teams = None           # {lower_name: team_id}


def _load_predictor():
    global _predictor
    if _predictor is None:
        from prediction_agent.inference.match_outcome import MatchOutcomePredictor
        _predictor = MatchOutcomePredictor.load(str(_ARTEFACT))
    return _predictor


def _build_feature_table():
    global _feature_table
    if _feature_table is None:
        from prediction_agent.data.aiven_loader import load_matches, load_team_match_xg, join_matches_with_xg
        from prediction_agent.features.match_features import build_match_features
        matches = load_matches()
        team_xg = load_team_match_xg()
        _feature_table = build_match_features(join_matches_with_xg(matches, team_xg))
    return _feature_table


def _teams_map() -> dict:
    global _teams
    if _teams is None:
        from tools.run_sql import run_sql
        rows = run_sql("SELECT team_id, team_name FROM teams")["rows"]
        _teams = {name.lower(): tid for tid, name in rows}
    return _teams


def _resolve_team_id(name: str) -> Optional[int]:
    if not name:
        return None
    m = _teams_map()
    key = name.strip().lower()
    if key in m:
        return m[key]
    # tolerant: substring either direction (handles 'Man United' vs 'Manchester United', 'Spurs', etc.)
    for tname, tid in m.items():
        if key in tname or tname in key:
            return tid
    return None


def predict_match_outcome(home_team: str, away_team: str,
                          match_date: Optional[str] = None,
                          season: Optional[str] = None) -> dict:
    """Predict H/D/A probabilities for a fixture. Returns the model output dict or {'error': ...}."""
    import pandas as pd
    try:
        hid, aid = _resolve_team_id(home_team), _resolve_team_id(away_team)
        if hid is None or aid is None:
            return {"error": f"could not resolve team(s): home={home_team!r}->{hid}, away={away_team!r}->{aid}"}
        feats = _build_feature_table()
        sel = feats[(feats["home_team_id"] == hid) & (feats["away_team_id"] == aid)]
        if match_date:
            sel = sel[pd.to_datetime(sel["match_date"]) == pd.to_datetime(match_date)]
        elif season:
            sel = sel[sel["season"] == season]
        if len(sel) == 0:
            return {"error": f"no fixture found for {home_team} vs {away_team} "
                             f"(date={match_date}, season={season})"}
        row = sel.iloc[0]
        out = _load_predictor().predict_from_features(row, home_team=home_team, away_team=away_team)
        return out.as_dict()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


if __name__ == "__main__":
    for h, a, d in [("Manchester United", "Fulham", "2024-08-16"),
                    ("Arsenal", "Wolves", "2024-08-17"),
                    ("Everton", "Brighton", "2024-08-17"),
                    ("Nottingham Forest", "Bournemouth", "2024-08-17")]:
        print(f"{h} vs {a} ({d}):", predict_match_outcome(h, a, d))
