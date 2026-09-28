"""
Prediction Agent - Match outcome forecasting.

Sibling to data_analyst in the graph. Triggered when the manager classifies
intent as `prediction_match`. It forecasts a single fixture and writes a
1-row DataFrame to `data_result` (same field shape as data_analyst), so the
synthesizer, eval_agent and memory_store need no prediction-specific code.

How features are built (config A - train/inference parity by construction):
    This node reuses the EXACT training pipeline from the prediction_agent
    package: load_matches + load_team_match_xg + join_matches_with_xg +
    build_match_features. It does NOT approximate xG. A synthetic "future
    fixture" row is appended to the real match history; build_match_features
    computes that row's features from the accumulated pre-kickoff state of
    both teams (rolling-5 form, Elo, rest, true rolling-5 xG). Because the
    same feature engine produces both training and inference vectors, there
    is no train/inference skew.

Model artefact:
    Defaults to the no-odds model (match_outcome_v1.pkl). The with-odds model
    cannot serve a future fixture (no pre-match odds exist for an unplayed
    game), so it is intentionally not the default. To swap models later, set
    PREDICTION_AGENT_ARTEFACT - the node builds the full feature frame and the
    predictor selects the columns it was trained on. If the chosen artefact
    needs a feature this node can't supply (e.g. implied odds probabilities),
    the parity guard raises a clear error rather than feeding the model NaNs.

Environment:
    The aiven_loader reads STATS_DATABASE_URI (preferred) or DATABASE_URI.
    Point one of them at the stats warehouse (matches, player_match_performance,
    teams). If your stats tables live in the same Aiven instance as the
    pgvector memory, DATABASE_URI already covers it.

State written:
    data_result          1-row DataFrame: home_team, away_team, home_win_pct,
                         draw_pct, away_win_pct, confidence, model_version
    sql_query            "PREDICTION: match_outcome_<version> (home vs away)"
    prediction_metadata  dict: model_version, team ids/names, probabilities,
                         confidence, feature snapshot
    error / error_stage  set on any failure (synthesizer surfaces it)
"""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Make sibling modules (state, config) importable when run inside agent_v4.
sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState

# Prediction package (pip-installed as `prediction-agent`, importable anywhere).
from prediction_agent.inference.match_outcome import (
    MatchOutcomePredictor,
    MatchPrediction,
)
from prediction_agent.features.match_features import build_match_features
from prediction_agent.data import aiven_loader

# Multi-task framework (D0/D1): registry + generic predictor + team-season features.
from prediction_agent.tasks import get as get_task
from prediction_agent.tasks.base import GenericPredictor
from prediction_agent.features.team_season_features import build_team_season_features

# D4: computed player/team/event tasks + the model-explanation capability.
from prediction_agent.tasks import computed as d4
from prediction_agent.explanation.explain import explain_generic

log = logging.getLogger(__name__)

# Cached team-season feature frame (one DB hit per process).
_ts_frame: Optional[pd.DataFrame] = None


def _get_ts_frame() -> pd.DataFrame:
    global _ts_frame
    if _ts_frame is None:
        _ts_frame = build_team_season_features()
    return _ts_frame


# ---------------------------------------------------------------------------
# Cached resources - loaded once per process.
# ---------------------------------------------------------------------------

_predictor: Optional[MatchOutcomePredictor] = None
_history: Optional[pd.DataFrame] = None        # matches joined with team xG
_teams: Optional[pd.DataFrame] = None          # team_id, team_name


def _artefact_path() -> Path:
    """Resolve the model artefact. Env override wins; default is the no-odds model."""
    env = os.getenv("PREDICTION_AGENT_ARTEFACT")
    if env:
        return Path(env)
    # prediction_agent.__file__ -> <root>/prediction_agent/prediction_agent/__init__.py
    import prediction_agent as _pkg
    project_dir = Path(_pkg.__file__).resolve().parent.parent  # <root>/prediction_agent
    return project_dir / "artefacts" / "match_outcome_v1.pkl"


def _get_predictor() -> MatchOutcomePredictor:
    global _predictor
    if _predictor is None:
        path = _artefact_path()
        if not path.exists():
            raise FileNotFoundError(
                f"Match outcome artefact not found at {path}. "
                "Train it first: `make train-match-outcome` from prediction_agent/."
            )
        _predictor = MatchOutcomePredictor.load(path)
        log.info("Loaded predictor %s (%d features)",
                 _predictor.version, len(_predictor.feature_columns))
    return _predictor


def _get_history() -> pd.DataFrame:
    """Load + join all match history with team xG, once per process."""
    global _history
    if _history is None:
        matches = aiven_loader.load_matches()
        team_xg = aiven_loader.load_team_match_xg()
        _history = aiven_loader.join_matches_with_xg(matches, team_xg)
        log.info("Loaded %d historical matches for prediction features", len(_history))
    return _history


def _get_teams() -> pd.DataFrame:
    global _teams
    if _teams is None:
        _teams = aiven_loader.load_teams()
    return _teams


def refresh_caches() -> None:
    """Clear cached history/teams/predictor (call after retraining or new data)."""
    global _predictor, _history, _teams, _ts_frame
    _predictor = _history = _teams = _ts_frame = None


# ---------------------------------------------------------------------------
# Team name resolution -> team_id.
# ---------------------------------------------------------------------------

_NAME_ALIASES = {
    "manchester united": "Manchester Utd", "man united": "Manchester Utd",
    "man utd": "Manchester Utd", "manchester utd": "Manchester Utd",
    "manchester city": "Manchester City", "man city": "Manchester City",
    "newcastle united": "Newcastle Utd", "newcastle utd": "Newcastle Utd",
    "newcastle": "Newcastle Utd", "nottingham forest": "Nott'ham Forest",
    "nottm forest": "Nott'ham Forest", "spurs": "Tottenham",
    "tottenham hotspur": "Tottenham", "west ham united": "West Ham",
    "west ham": "West Ham", "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves", "leeds united": "Leeds Utd",
    "brighton and hove albion": "Brighton", "brighton & hove albion": "Brighton",
    "afc bournemouth": "Bournemouth",
}


def _resolve_team(name: str) -> Optional[tuple[int, str]]:
    """Return (team_id, canonical_team_name) for a user-supplied name, or None."""
    if not name:
        return None
    teams = _get_teams()
    canonical = _NAME_ALIASES.get(name.strip().lower(), name.strip())

    exact = teams[teams["team_name"].str.lower() == canonical.lower()]
    if not exact.empty:
        row = exact.iloc[0]
        return int(row["team_id"]), row["team_name"]

    contains = teams[teams["team_name"].str.lower().str.contains(canonical.lower(), regex=False)]
    if not contains.empty:
        row = contains.iloc[0]
        return int(row["team_id"]), row["team_name"]

    return None


# ---------------------------------------------------------------------------
# Feature building for the requested fixture (config A).
# ---------------------------------------------------------------------------

def _build_feature_row(home_id: int, away_id: int) -> pd.Series:
    """
    Append a synthetic future fixture to the real (xG-joined) history, run the
    shared feature engine, and return the synthetic row's feature vector.

    The synthetic row's own scores/xG are dummies; build_match_features uses
    them only in the post-match state update, which for the final row is
    discarded. The features themselves come from each team's accumulated
    pre-kickoff state - i.e. current strength.
    """
    history = _get_history()
    last_date = pd.to_datetime(history["match_date"]).max()

    synthetic = {col: np.nan for col in history.columns}
    synthetic.update({
        "game_id": -1,
        "season": history["season"].iloc[-1],
        "match_date": last_date + pd.Timedelta(days=7),
        "home_team_id": home_id,
        "away_team_id": away_id,
        # Dummies so the discarded post-match update doesn't crash on NaN casts.
        "home_score": 0, "away_score": 0, "ft_result": "D",
        "home_shots": 0, "away_shots": 0,
        "home_shots_on_target": 0, "away_shots_on_target": 0,
        "home_team_xg": 0, "away_team_xg": 0,
    })

    combined = pd.concat([history, pd.DataFrame([synthetic])], ignore_index=True)
    feats = build_match_features(combined)

    pred_row = feats[feats["game_id"] == -1]
    if pred_row.empty:
        raise RuntimeError(
            "Could not build a feature vector for this fixture - one or both "
            "teams have too little recent match history (warmup window)."
        )
    return pred_row.iloc[0]


# ---------------------------------------------------------------------------
# Main node entry point.
# ---------------------------------------------------------------------------

def _predict_match(state: AgentState) -> AgentState:
    """Forecast a single fixture outcome (the original match-outcome path)."""
    teams = state.get("query_parameters", {}).get("teams", []) or []

    if len(teams) < 2:
        state["error"] = (
            f"I need two teams to predict a match. You mentioned: {teams or 'none'}. "
            "Try something like 'Predict Arsenal vs Chelsea'."
        )
        state["error_stage"] = "prediction_agent"
        return state

    home_name, away_name = teams[0], teams[1]

    home = _resolve_team(home_name)
    if home is None:
        state["error"] = f"I couldn't find a team called '{home_name}' in the database."
        state["error_stage"] = "prediction_agent"
        return state
    away = _resolve_team(away_name)
    if away is None:
        state["error"] = f"I couldn't find a team called '{away_name}' in the database."
        state["error_stage"] = "prediction_agent"
        return state

    home_id, home_canonical = home
    away_id, away_canonical = away

    # Build features using the shared training pipeline.
    try:
        feature_row = _build_feature_row(home_id, away_id)
    except Exception as exc:
        state["error"] = f"Couldn't build features for this prediction: {exc}"
        state["error_stage"] = "prediction_agent"
        return state

    # Run the model.
    try:
        predictor = _get_predictor()

        # Parity guard: the artefact must get exactly the features it trained on.
        needed = predictor.feature_columns
        missing = [c for c in needed if c not in feature_row.index]
        nan_valued = [c for c in needed
                      if c in feature_row.index and pd.isna(feature_row[c])]
        if missing or nan_valued:
            raise ValueError(
                "Feature mismatch between this artefact and the inference pipeline. "
                f"Missing: {missing or 'none'}. Unavailable (NaN): {nan_valued or 'none'}. "
                "This usually means a with-odds model was loaded - it needs pre-match "
                "odds that don't exist for an unplayed fixture. Use the no-odds artefact "
                "for live prediction."
            )

        feature_dict = {c: float(feature_row[c]) for c in needed}
        prediction: MatchPrediction = predictor.predict_from_features(
            feature_dict, home_team=home_canonical, away_team=away_canonical,
        )
    except Exception as exc:
        state["error"] = f"Prediction model failed: {exc}"
        state["error_stage"] = "prediction_agent"
        return state

    # Write tabular result in the same shape data_analyst produces.
    state["data_result"] = pd.DataFrame([{
        "home_team":     home_canonical,
        "away_team":     away_canonical,
        "home_win_pct":  round(prediction.home_win_prob * 100, 1),
        "draw_pct":      round(prediction.draw_prob * 100, 1),
        "away_win_pct":  round(prediction.away_win_prob * 100, 1),
        "confidence":    round(prediction.confidence, 3),
        "model_version": prediction.model_version,
    }])
    state["sql_query"] = (
        f"PREDICTION: match_outcome_{prediction.model_version} "
        f"({home_canonical} vs {away_canonical})"
    )
    state["prediction_metadata"] = {
        "model_version":  prediction.model_version,
        "home_team_id":   home_id,
        "away_team_id":   away_id,
        "home_team_name": home_canonical,
        "away_team_name": away_canonical,
        "probabilities": {
            "home_win": prediction.home_win_prob,
            "draw":     prediction.draw_prob,
            "away_win": prediction.away_win_prob,
        },
        "confidence": prediction.confidence,
        "features":   feature_dict,
    }

    # ── Phase 2.1: feature attribution (Q14) — now non-empty for the calibrated
    #     stacking model via the ensemble base-learner proxy. Best-effort. ──────
    try:
        from prediction_agent.explanation.explain import explain_prediction
        label_map = predictor._label_map               # {'H':0,'D':1,'A':2}
        classes = [k for k, _ in sorted(label_map.items(), key=lambda kv: kv[1])]
        probs = {"H": prediction.home_win_prob, "D": prediction.draw_prob,
                 "A": prediction.away_win_prob}
        pred_label = max(probs, key=probs.get)
        state["prediction_metadata"]["explanation"] = explain_prediction(
            predictor._model, needed, feature_dict, classes=classes,
            target_type="classification", predicted_class=pred_label, top_k=5)
    except Exception:
        pass

    # ── Phase 2.2: as_of-GATED narrative retrieval for the forecast. This OVERRIDES
    #     the ungated narrative from memory_retrieval so a forecast can never be
    #     wrapped in post-kickoff (leaking) text. kickoff mirrors _build_feature_row
    #     (last history date + 7 days). Best-effort; empty on any miss. ───────────
    try:
        from memory.vector_store_pg import query_documents
        kickoff = (pd.to_datetime(_get_history()["match_date"]).max()
                   + pd.Timedelta(days=7)).date()
        state["narrative_context"] = query_documents(
            f"{home_canonical} vs {away_canonical}", as_of=kickoff, n_results=3)
    except Exception:
        state["narrative_context"] = []
    return state


# ---------------------------------------------------------------------------
# Multi-task dispatch (D1): select a prediction_type from the registry and route.
# ---------------------------------------------------------------------------

# Keyword cues per task (fallback when the manager didn't set prediction_type).
_TASK_KEYWORDS = [
    # D4 cues first (more specific) — players, transfers, injuries, events, value.
    (("value for money", "best value", "bargain", "undervalued", "overvalued",
      "worth their", "value relative", "attractive but"), "player_value"),
    (("most likely to decline", "player decline", "decline next season",
      "regress next season", "falling off"), "player_decline"),
    (("fit at", "fit in at", "context fit", "team fit", "profile fit",
      "fit the team"), "transfer_fit"),
    (("move to the premier", "moved to the premier", "moving to", "translate to",
      "cross-league", "another league", "different league", "in england", "in la liga",
      "in serie a", "in the bundesliga", "in ligue"), "cross_league_translation"),
    (("how much would", "player impact", "improve their chances", "improve the chances",
      "contribution to", "without him"), "player_team_impact"),
    (("injur", "absences", "availability", "suspensions", "squad availability",
      "missing players", "cost in points"), "squad_availability"),
    (("strategic value", "stakeholder", "club value", "most valuable club",
      "increase .* value"), "stakeholder_value"),
    (("early goal", "red card", "sent off", "scores first", "score first",
      "leading at half", "half-time lead", "in-game", "substitution"), "event_impact"),
    # team-season (existing).
    (("relegat", "go down", "drop out", "title", "top four", "top 4",
      "champions league", "finish", "european", "europa", "conference"), "season_class"),
    (("improve", "climb", "move up", "move down", "positions", "places",
      "rise", "fall", "jump"), "position_movement"),
    (("overperform", "underperform", "decline", "regress", "turnaround",
      "points next", "drop off", "bounce back"), "turnaround"),
    (("home form", "away form", "rely on home", "home reliance", "reliant on home",
      "vulnerable away", "at home"), "home_away_dependency"),
]


def _select_prediction_type(state: AgentState) -> str:
    """Resolve the task id. Manager-provided prediction_type wins; else keyword cues;
    else fall back to match (2 teams) or season_class."""
    params = state.get("query_parameters", {}) or {}
    pt = params.get("prediction_type")
    if pt and get_task(pt):
        return pt

    q = (state.get("user_query", "") or "").lower()
    teams = params.get("teams", []) or []
    if len(teams) >= 2 and any(w in q for w in (" vs ", " v ", "beat", "against", "draw between")):
        return "match_outcome"
    for kws, task in _TASK_KEYWORDS:
        if any(k in q for k in kws):
            return task
    return "match_outcome" if len(teams) >= 2 else "season_class"


def _find_team_row(name: str):
    """Latest team-season row for a user-supplied team name (alias-aware)."""
    df = _get_ts_frame()
    canonical = _NAME_ALIASES.get(name.strip().lower(), name.strip())
    sub = df[df["team"].str.lower() == canonical.lower()]
    if sub.empty:
        sub = df[df["team"].str.lower().str.contains(canonical.lower(), regex=False)]
    if sub.empty:
        return None
    return sub.sort_values("season").iloc[-1]


def _focus_sort_column(query: str, spec) -> Optional[str]:
    """Infer which probability column a league-wide query cares about, for sorting."""
    q = (query or "").lower()
    if spec.name == "season_class":
        if any(k in q for k in ("relegat", "go down", "drop out")):
            return "p_relegation"
        if any(k in q for k in ("top four", "top 4", "champions league", "title")):
            return "p_top4"
        if any(k in q for k in ("european", "europa", "conference")):
            return "p_european"
    if spec.name == "position_movement":
        if any(k in q for k in ("improve", "climb", "rise", "move up", "jump")):
            return "p_up5"
        if any(k in q for k in ("decline", "drop", "fall", "move down")):
            return "p_down5"
    return None


def _predict_team_season(state: AgentState, spec, want_explain: bool = False) -> AgentState:
    """Model-backed team-season task (Q1–Q3). One team → single forecast; no team →
    league-wide ranked table (e.g. 'who is most likely to be relegated next season?')."""
    artefact = spec.artefact_path()
    if not artefact or not artefact.exists():
        state["error"] = (f"The '{spec.name}' model isn't trained yet ({artefact}). "
                          "Run: python scripts/train_tasks.py from prediction_agent/.")
        state["error_stage"] = "prediction_agent"
        return state
    predictor = GenericPredictor.load(artefact)

    teams = state.get("query_parameters", {}).get("teams", []) or []

    if teams:
        rows = []
        row = _find_team_row(teams[0])
        if row is None:
            state["error"] = f"I couldn't find a Premier League team called '{teams[0]}'."
            state["error_stage"] = "prediction_agent"
            return state
        rows = [row]
    else:
        # League-wide: the CURRENT season's teams (most recent season in the frame),
        # forecasting their next season. (Not each team's own latest season, which would
        # mix in clubs relegated years ago.)
        df = _get_ts_frame()
        current = df["season"].max()
        rows = [r for _, r in df[df["season"] == current].iterrows()]

    out_rows = []
    for row in rows:
        feats = {c: float(row[c]) for c in predictor.feature_columns}
        pred = predictor.predict_from_features(feats, entity=str(row["team"]))
        rr = pred.as_row()
        rr["from_season"] = row["season"]
        out_rows.append(rr)

    result = pd.DataFrame(out_rows)
    sort_col = _focus_sort_column(state.get("user_query", ""), spec)
    if sort_col and sort_col in result.columns:
        result = result.sort_values(sort_col, ascending=False).reset_index(drop=True)

    state["data_result"] = result
    state["sql_query"] = (f"PREDICTION: {spec.name}_{predictor.version} "
                          f"({'league-wide' if not teams else result.iloc[0]['entity']})")
    meta = {
        "task": spec.name, "model_version": predictor.version,
        "scope": "team" if teams else "league_wide",
        "n_entities": len(result), "sorted_by": sort_col,
        "top": result.iloc[0].to_dict() if not result.empty else None,
    }

    # D3: single-team forecasts are persisted to computed_metrics and a prior (if any) is
    # surfaced for retrieve-before-forecast. League-wide tables are not persisted (noisy).
    if teams and len(rows) == 1:
        single = rows[0]
        probs = {k[2:]: v for k, v in result.iloc[0].items() if k.startswith("p_")}
        meta["entity_id"] = int(single["team_id"])
        meta["probabilities"] = probs
        meta["prediction"] = result.iloc[0]["prediction"]
        if want_explain:
            feats = {c: float(single[c]) for c in predictor.feature_columns}
            meta["explanation"] = _explain_model_task(
                spec, predictor, feats, result.iloc[0]["prediction"])
        try:
            from memory.prediction_feedback import persist_prediction, fetch_prior
            persist_prediction(spec.name, str(single["team"]), int(single["team_id"]),
                               metric_value=probs,
                               parameters={"model_version": predictor.version,
                                           "from_season": str(single["season"])})
            prior = fetch_prior(spec.name, int(single["team_id"]))
            if prior:
                meta["prior_forecast"] = prior.get("metric_value")
        except Exception:
            pass

    state["prediction_metadata"] = meta
    return state


def _predict_index(state: AgentState, spec) -> AgentState:
    """Computed index task (Q4 home/away dependency) — no model."""
    teams = state.get("query_parameters", {}).get("teams", []) or []
    if not teams:
        state["error"] = f"I need a team to compute '{spec.name}'."
        state["error_stage"] = "prediction_agent"
        return state
    pred = spec.compute_fn(teams[0])
    state["data_result"] = pd.DataFrame([pred.as_row()])
    state["sql_query"] = f"PREDICTION: {spec.name} ({pred.entity})"
    state["prediction_metadata"] = {
        "task": spec.name, "entity": pred.entity, "target_type": "index",
        "prediction": pred.prediction, "probabilities": pred.probabilities,
        "model_version": pred.model_version,
    }
    return state


# ---------------------------------------------------------------------------
# D4 dispatch — player / transfer / event / computed-team tasks + explanation.
# ---------------------------------------------------------------------------

def _player_entity(state: AgentState) -> Optional[str]:
    """A player name from the manager's `players` param (preferred) or `teams` fallback."""
    params = state.get("query_parameters", {}) or {}
    players = params.get("players") or []
    if players:
        return players[0]
    return None


def _render(state: AgentState, df: pd.DataFrame, meta: dict, spec) -> AgentState:
    """Write a computed-task result in the same shape data_analyst produces."""
    state["data_result"] = df
    scope = meta.get("scope", "")
    label = meta.get("entity") or ("league-wide" if scope == "league_wide" else
                                   meta.get("scenario") or scope)
    state["sql_query"] = f"PREDICTION: {spec.name} ({label})"
    meta.setdefault("task", spec.name)
    state["prediction_metadata"] = meta
    return state


def _explain_model_task(spec, predictor: GenericPredictor, feature_dict: dict,
                        predicted_class) -> dict:
    """Top driving factors + confidence for a model-backed forecast (Q14)."""
    try:
        return explain_generic(predictor, feature_dict, predicted_class=predicted_class)
    except Exception as exc:  # explanation is best-effort, never blocks a forecast
        return {"method": "unavailable", "error": str(exc)}


def _predict_player_decline(state: AgentState, spec, want_explain: bool) -> AgentState:
    """Model-backed player task. One player → single forecast (+explanation); no player →
    league-wide ranked table by decline probability."""
    artefact = spec.artefact_path()
    if not artefact or not artefact.exists():
        raise FileNotFoundError(f"the '{spec.name}' model isn't trained ({artefact}).")
    predictor = GenericPredictor.load(artefact)
    frame = d4._players()
    cur = frame["season"].max()

    name = _player_entity(state)
    if name:
        row = d4._latest(frame, "player_name", name)
        if row is None:
            state["error"] = f"I couldn't find a player called '{name}'."
            state["error_stage"] = "prediction_agent"
            return state
        feats = {c: float(row[c]) for c in predictor.feature_columns}
        pred = predictor.predict_from_features(feats, entity=str(row["player_name"]))
        out = pd.DataFrame([{
            "player": str(row["player_name"]), "team": str(row["team_name"]),
            "season": str(row["season"]), "age": int(row["age"]),
            "decline_prediction": "likely_decline" if str(pred.prediction) == "1" else "no_decline",
            "decline_prob": round(pred.probabilities.get("1", 0.0), 3),
            "confidence": round(pred.confidence, 3),
        }])
        meta = {"task": spec.name, "scope": "player", "entity": str(row["player_name"]),
                "model_version": predictor.version,
                "decline_prob": round(pred.probabilities.get("1", 0.0), 3)}
        if want_explain:
            meta["explanation"] = _explain_model_task(spec, predictor, feats, pred.prediction)
        return _render(state, out, meta, spec)

    # League-wide: rank current-season players (≥450 min) by decline probability.
    sub = frame[(frame["season"] == cur) & (frame["minutes"] >= 450)]
    rows = []
    for _, r in sub.iterrows():
        feats = {c: float(r[c]) for c in predictor.feature_columns}
        p = predictor.predict_from_features(feats).probabilities.get("1", 0.0)
        rows.append({"player": str(r["player_name"]), "team": str(r["team_name"]),
                     "age": int(r["age"]), "minutes": int(r["minutes"]),
                     "ga_per90": round(float(r["ga_per90"]), 3), "decline_prob": round(p, 3)})
    out = pd.DataFrame(rows).sort_values("decline_prob", ascending=False).head(15).reset_index(drop=True)
    meta = {"task": spec.name, "scope": "league_wide", "season": str(cur),
            "model_version": predictor.version, "n_entities": len(out)}
    return _render(state, out, meta, spec)


def _predict_computed_d4(state: AgentState, spec) -> AgentState:
    """Computed D4 task (player_value, player_team_impact, transfer_fit, cross_league,
    squad_availability, stakeholder_value, event_impact). Routes args by task name."""
    params = state.get("query_parameters", {}) or {}
    query = state.get("user_query", "") or ""
    teams = params.get("teams") or []
    player = _player_entity(state)
    name = spec.name

    if name == "event_impact":
        scenario = d4.parse_event_scenario(query)
        df, meta = d4.event_impact_scenario(scenario, query=query)
    elif name == "player_value":
        df, meta = d4.player_value(entity=player, query=query)
    elif name == "player_team_impact":
        if not player:
            state["error"] = ("I need a player name for player-impact "
                              "(e.g. 'how much does Salah improve Liverpool?').")
            state["error_stage"] = "prediction_agent"
            return state
        df, meta = d4.player_team_impact(player)
    elif name == "transfer_fit":
        dest = params.get("destination") or (teams[0] if teams else None)
        if not player or not dest:
            state["error"] = ("Transfer-fit needs a player and a destination team "
                              "(e.g. 'how would Mbappé fit at Arsenal?').")
            state["error_stage"] = "prediction_agent"
            return state
        df, meta = d4.transfer_fit(player, destination=dest)
    elif name == "cross_league_translation":
        if not player:
            state["error"] = ("Cross-league translation needs a player "
                              "(e.g. 'how would Mbappé do in the Premier League?').")
            state["error_stage"] = "prediction_agent"
            return state
        df, meta = d4.cross_league_forecast(player, dest_league=params.get("destination_league"))
    elif name == "squad_availability":
        df, meta = d4.squad_availability(entity=(teams[0] if teams else None), query=query)
    elif name == "stakeholder_value":
        df, meta = d4.stakeholder_value(entity=(teams[0] if teams else None), query=query)
    else:
        raise ValueError(f"no computed handler for task '{name}'")
    return _render(state, df, meta, spec)


def prediction_agent(state: AgentState) -> AgentState:
    """Prediction node (dispatcher): pick a task from the registry and route to the right
    handler (match / team-season / player / transfer / event / computed). Defaults to
    match-outcome for back-compat. Attaches a model explanation (Q14) when asked."""
    q = (state.get("user_query", "") or "").lower()
    want_explain = any(k in q for k in ("why", "what factors", "which factors", "explain",
                                        "driving", "drivers", "how confident", "what's driving"))

    pt = _select_prediction_type(state)
    spec = get_task(pt)

    # A bare "explain" request → resolve the underlying task from keyword cues.
    if spec is not None and spec.name == "explain":
        want_explain = True
        for kws, task in _TASK_KEYWORDS:
            if any(k in q for k in kws):
                spec, pt = get_task(task), task
                break
        else:
            spec, pt = get_task("season_class"), "season_class"

    if spec is None or spec.granularity == "match":
        return _predict_match(state)

    try:
        if spec.granularity in ("player_season", "player_transfer", "match_event"):
            if spec.artefact and spec.name == "player_decline":
                return _predict_player_decline(state, spec, want_explain)
            return _predict_computed_d4(state, spec)
        # team_season:
        if spec.target_type == "index":
            if spec.name in ("squad_availability", "stakeholder_value"):
                return _predict_computed_d4(state, spec)
            return _predict_index(state, spec)
        return _predict_team_season(state, spec, want_explain=want_explain)
    except Exception as exc:
        state["error"] = f"Prediction failed for task '{pt}': {exc}"
        state["error_stage"] = "prediction_agent"
        return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from state import create_initial_state

    test = create_initial_state("Predict Arsenal vs Chelsea")
    test["query_parameters"] = {"teams": ["Arsenal", "Chelsea"]}
    test["intent"] = "prediction_match"
    test["is_premier_league_related"] = True

    result = prediction_agent(test)
    if result.get("error"):
        print("Error:", result["error"])
    else:
        print(result["data_result"].to_string(index=False))
        print("Sentinel:", result["sql_query"])
        print("Metadata keys:", list(result["prediction_metadata"].keys()))
