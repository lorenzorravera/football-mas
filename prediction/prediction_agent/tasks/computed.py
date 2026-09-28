"""
Computed prediction tasks (D4) — the index/counterfactual half of the new suite.

These need no training: they combine the shared feature builders with the already-trained
models (season_class, player_decline) to answer:

  player_value          (Q7a/b) value-for-money + risk flags relative to market value/age/availability
  player_team_impact     (Q6)    counterfactual Δ in a team's season-class probability if a player
                                  is removed (re-scores the season_class model)
  transfer_fit           (Q12)   style-fit of a player to a destination team vs his current club
  squad_availability     (Q5)    how much injuries/absences depress a team's expected points
  stakeholder_value      (Q10)   club strategic-value index (sport + attendance + squad value +
                                  development + transfer activity)

Each function returns (result_df, meta). result_df has one row for a single entity or N ranked
rows for a league-wide query, so the dispatcher renders them like any other prediction table.

Single-league (ENG-PL), 2020-21..2024-25 — illustrative and honestly calibrated, matching the
rest of the suite. Cached frames mean one DB hit per process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_ARTEFACTS = Path(__file__).resolve().parent.parent.parent / "artefacts"

# ---------------------------------------------------------------------------
# Cached frames (one DB hit per process).
# ---------------------------------------------------------------------------
_player_frame: Optional[pd.DataFrame] = None
_team_frame: Optional[pd.DataFrame] = None
_decline = None


def _players() -> pd.DataFrame:
    global _player_frame
    if _player_frame is None:
        from prediction_agent.features.player_season_features import build_player_season_features
        _player_frame = build_player_season_features("ENG-PL")
    return _player_frame


def _teams() -> pd.DataFrame:
    global _team_frame
    if _team_frame is None:
        from prediction_agent.features.team_season_features import build_team_season_features
        _team_frame = build_team_season_features()
    return _team_frame


def _decline_model():
    global _decline
    if _decline is None:
        p = _ARTEFACTS / "player_decline_v1.pkl"
        if p.exists():
            from prediction_agent.tasks.base import GenericPredictor
            _decline = GenericPredictor.load(p)
        else:
            _decline = False
    return _decline or None


def refresh_caches() -> None:
    global _player_frame, _team_frame, _decline
    _player_frame = _team_frame = _decline = None


def _latest(df: pd.DataFrame, name_col: str, name: str) -> Optional[pd.Series]:
    canonical = (name or "").strip().lower()
    sub = df[df[name_col].str.lower() == canonical]
    if sub.empty:
        sub = df[df[name_col].str.lower().str.contains(canonical, regex=False, na=False)]
    if sub.empty:
        return None
    # When several distinct names match a partial query (e.g. 'Mbappé' → Kylian vs a youth
    # namesake), prefer the most prominent player by total minutes, then their latest season.
    if sub[name_col].nunique() > 1 and "minutes" in sub.columns:
        prominent = sub.groupby(name_col)["minutes"].sum().idxmax()
        sub = sub[sub[name_col] == prominent]
    return sub.sort_values("season").iloc[-1]


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


# ===========================================================================
# Q7 — player value detection (value-for-money + risk)
# ===========================================================================

def _score_player_value(df: pd.DataFrame) -> pd.DataFrame:
    """Add value/risk columns to a player-season frame (current-season view)."""
    df = df.copy()
    # Attacking production proxy (per 90), availability-weighted.
    production = 0.6 * df["ga_per90"] + 0.25 * df["npxg_per90"] + 0.15 * df["xa_per90"]
    availability = (df["minutes"] / df["minutes"].max()).clip(0, 1)
    df["production"] = (production * (0.5 + 0.5 * availability)).round(3)
    # Impact per cost: production relative to (log) market value.
    df["value_score"] = (df["production"] / np.log1p(df["market_value_m"]).clip(lower=0.5)).round(3)
    df["value_pct"] = _pct_rank(df["value_score"]).round(3)

    # Decline probability from the trained model (risk component).
    dm = _decline_model()
    if dm is not None:
        df["decline_prob"] = [
            round(float(dm.predict_from_features(r).probabilities.get("1", 0.0)), 3)
            for _, r in df.iterrows()
        ]
    else:
        df["decline_prob"] = np.nan

    # Composite risk: age, injury load, decline prob, thin sample.
    age_risk = ((df["age"] - 28).clip(lower=0) / 8).clip(0, 1)
    inj_risk = (df["games_missed"] / 15).clip(0, 1)
    decline_risk = df["decline_prob"].fillna(df["decline_prob"].median())
    minutes_risk = (1 - availability).clip(0, 1) * 0.5
    df["risk_score"] = (0.30 * age_risk + 0.30 * inj_risk
                        + 0.30 * decline_risk + 0.10 * minutes_risk).round(3)

    def _label(row):
        hi_val = row["value_pct"] >= 0.70
        hi_risk = row["risk_score"] >= 0.50
        if hi_val and not hi_risk:
            return "undervalued_low_risk"
        if hi_val and hi_risk:
            return "high_upside_high_risk"
        if row["value_pct"] <= 0.30:
            return "overvalued"
        return "fair_value"
    df["label"] = df.apply(_label, axis=1)
    return df


def player_value(entity: Optional[str] = None, season: Optional[str] = None,
                 top_n: int = 15, query: str = "") -> tuple[pd.DataFrame, dict]:
    df = _players()
    df = df[df["next_minutes"].notna() | True]  # all rows; current-season view
    cur = df["season"].max() if not season else season
    view = df[df["season"] == cur].copy() if entity is None else df.copy()
    view = _score_player_value(view)

    cols = ["player_name", "team_name", "season", "age", "minutes", "ga_per90",
            "market_value_m", "production", "value_score", "value_pct",
            "decline_prob", "risk_score", "label"]

    if entity:
        row = _latest(view, "player_name", entity)
        if row is None:
            raise ValueError(f"no Premier League player matching {entity!r}")
        out = view[(view["player_name"] == row["player_name"])].sort_values("season").tail(1)
        out = out[cols].reset_index(drop=True)
        meta = {"task": "player_value", "scope": "player",
                "entity": str(row["player_name"]), "label": str(out.iloc[0]["label"])}
        return out, meta

    q = (query or "").lower()
    if any(k in q for k in ("risk", "risky", "declin", "injury")):
        view = view.sort_values("risk_score", ascending=False)
        sort_by = "risk_score"
    else:
        # best value: high value percentile among players with a real sample
        view = view[view["minutes"] >= 450].sort_values("value_score", ascending=False)
        sort_by = "value_score"
    out = view[cols].head(top_n).reset_index(drop=True)
    meta = {"task": "player_value", "scope": "league_wide", "season": str(cur),
            "sorted_by": sort_by, "n_entities": len(out)}
    return out, meta


# ===========================================================================
# Q6 — player impact on team class (counterfactual on season_class)
# ===========================================================================

def _season_class_predictor():
    from prediction_agent.tasks.base import GenericPredictor
    p = _ARTEFACTS / "team_season_class_v1.pkl"
    if not p.exists():
        raise FileNotFoundError("season_class model not trained; run train_tasks.py")
    return GenericPredictor.load(p)


def player_team_impact(entity: str, season: Optional[str] = None,
                       **_) -> tuple[pd.DataFrame, dict]:
    """Δ in the player's team next-season class probabilities if his attacking output is
    removed. Re-scores the season_class model on a counterfactual team-season row."""
    if not entity:
        raise ValueError("player_team_impact needs a player name")
    pf = _players()
    prow = _latest(pf, "player_name", entity)
    if prow is None:
        raise ValueError(f"no Premier League player matching {entity!r}")

    tf = _teams()
    trow = tf[(tf["team_id"] == prow["team_id"]) & (tf["season"] == prow["season"])]
    if trow.empty:
        raise ValueError(f"no team-season row for {prow['team_name']} {prow['season']}")
    trow = trow.iloc[0]

    pred = _season_class_predictor()
    feats = {c: float(trow[c]) for c in pred.feature_columns}
    base = pred.predict_from_features(feats, entity=str(trow["team"])).probabilities

    # Counterfactual: strip the player's goals from the team's attack. Goals removed reduce
    # goals_for and goal_difference; ~3 league points per net goal swing is a standard heuristic.
    cf = dict(feats)
    pg = float(prow["goals"])
    cf["goals_for"] = max(0.0, cf.get("goals_for", 0.0) - pg)
    cf["goal_difference"] = cf.get("goal_difference", 0.0) - pg
    if "top_scorer_goals" in cf:
        cf["top_scorer_goals"] = min(cf["top_scorer_goals"], cf["goals_for"])
    cf_probs = pred.predict_from_features(cf, entity=str(trow["team"])).probabilities

    classes = sorted(set(base) | set(cf_probs))
    rows = [{
        "team": str(trow["team"]), "season": str(trow["season"]),
        "player": str(prow["player_name"]), "player_goals": int(pg),
        **{f"p_{c}_with": round(base.get(c, 0.0), 3) for c in classes},
        **{f"p_{c}_without": round(cf_probs.get(c, 0.0), 3) for c in classes},
        **{f"delta_{c}": round(base.get(c, 0.0) - cf_probs.get(c, 0.0), 3) for c in classes},
    }]
    out = pd.DataFrame(rows)
    top4_delta = base.get("top4", 0.0) - cf_probs.get("top4", 0.0)
    releg_delta = cf_probs.get("relegation", 0.0) - base.get("relegation", 0.0)
    meta = {"task": "player_team_impact", "scope": "player",
            "entity": str(prow["player_name"]), "team": str(trow["team"]),
            "delta_p_top4": round(top4_delta, 3),
            "delta_p_relegation_if_removed": round(releg_delta, 3)}
    return out, meta


# ===========================================================================
# Q12 — team-context fit after transfer
# ===========================================================================

# Team style axes from team-season stats (z-scored within frame).
_STYLE_COLS = ["possession", "shots", "goals_per_shot", "goal_difference"]


def transfer_fit(entity: str, destination: Optional[str] = None,
                 **_) -> tuple[pd.DataFrame, dict]:
    """Style-fit of a player to a destination team vs his current club. Higher = the
    destination plays a style closer to where the player already produces."""
    if not entity or not destination:
        raise ValueError("transfer_fit needs a player name and a destination team "
                          "(e.g. 'how would Mbappé fit at Arsenal?')")
    # Look the player up across all 5 leagues — a transfer target need not already be in the PL.
    global _all_players
    if _all_players is None:
        from prediction_agent.features.player_season_features import build_player_season_features
        _all_players = build_player_season_features("all")
    prow = _latest(_all_players, "player_name", entity)
    if prow is None:
        raise ValueError(f"no player matching {entity!r} in the 5-league data")
    tf = _teams()
    cur = tf["season"].max()
    season_teams = tf[tf["season"] == cur].copy()
    if season_teams.empty:
        raise ValueError("no current-season team rows")

    # z-score team style axes for the current season.
    z = season_teams.copy()
    for c in _STYLE_COLS:
        mu, sd = z[c].mean(), z[c].std(ddof=0) or 1.0
        z[c + "_z"] = (z[c] - mu) / sd

    origin = _latest(season_teams, "team", str(prow["team_name"]))
    dest = _latest(season_teams, "team", destination)
    if dest is None:
        raise ValueError(f"no Premier League team matching {destination!r}")

    def _vec(team_row):
        rz = z[z["team_id"] == team_row["team_id"]].iloc[0]
        return np.array([rz[c + "_z"] for c in _STYLE_COLS])

    dvec = _vec(dest)
    # A player who produces (high ga_per90) fits attack-heavy sides; weight the axes by
    # the player's own attacking tilt so e.g. a high-volume scorer "wants" a high-shot side.
    tilt = float(np.tanh(prow["ga_per90"]))   # 0..1-ish attacking emphasis
    # Cosine similarity between destination style and an idealised "produces here" profile.
    ideal = np.array([0.2, 1.0, 0.6, 0.8]) * (0.5 + tilt)
    def _cos(a, b):
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        return float(np.dot(a, b) / (na * nb)) if na and nb else 0.0
    dest_score = round(_cos(dvec, ideal), 3)
    orig_score = round(_cos(_vec(origin), ideal), 3) if origin is not None else None

    fit_delta = round(dest_score - orig_score, 3) if orig_score is not None else None
    rows = [{
        "player": str(prow["player_name"]), "ga_per90": round(float(prow["ga_per90"]), 3),
        "current_team": str(prow["team_name"]), "destination": str(dest["team"]),
        "current_fit": orig_score, "destination_fit": dest_score, "fit_delta": fit_delta,
        "verdict": ("better fit" if (fit_delta or 0) > 0.03
                    else "worse fit" if (fit_delta or 0) < -0.03 else "similar fit"),
    }]
    meta = {"task": "transfer_fit", "scope": "player", "entity": str(prow["player_name"]),
            "destination": str(dest["team"]), "fit_delta": fit_delta}
    return pd.DataFrame(rows), meta


# ===========================================================================
# Q5 — squad availability impact
# ===========================================================================

def _squad_availability_frame() -> pd.DataFrame:
    """Per (team, season): minutes-weighted availability + injury load, joined to points."""
    pf = _players()
    # weight each player's lost availability by their minutes share within the team-season
    grp = pf.groupby(["team_id", "season"])
    rows = []
    for (tid, season), g in grp:
        total_min = g["minutes"].sum() or 1.0
        w = g["minutes"] / total_min
        games_missed_w = float((g["games_missed"] * w).sum())
        days_missed_w = float((g["days_missed"] * w).sum())
        # availability index: 1 - weighted share of a 38-game season missed
        avail = float(1 - (games_missed_w / 38.0))
        rows.append({"team_id": tid, "season": season,
                     "avail_index": round(max(0.0, min(1.0, avail)), 3),
                     "games_missed_w": round(games_missed_w, 2),
                     "days_missed_w": round(days_missed_w, 1)})
    sa = pd.DataFrame(rows)
    tf = _teams()[["team_id", "season", "team", "points"]]
    return sa.merge(tf, on=["team_id", "season"], how="left")


def squad_availability(entity: Optional[str] = None, season: Optional[str] = None,
                       top_n: int = 15, query: str = "") -> tuple[pd.DataFrame, dict]:
    sa = _squad_availability_frame()
    # Calibrate a points-per-availability slope across all team-seasons (illustrative).
    valid = sa.dropna(subset=["points"])
    if len(valid) >= 5 and valid["avail_index"].std(ddof=0) > 0:
        slope = float(np.polyfit(valid["avail_index"], valid["points"], 1)[0])
    else:
        slope = 0.0
    # Estimated points lost vs a fully-available squad (avail_index = 1.0).
    sa["est_points_lost"] = ((1.0 - sa["avail_index"]) * slope).round(2)

    cols = ["team", "season", "avail_index", "games_missed_w", "days_missed_w", "est_points_lost"]
    if entity:
        row = _latest(sa.rename(columns={"team": "team"}), "team", entity)
        if row is None:
            raise ValueError(f"no Premier League team matching {entity!r}")
        out = sa[(sa["team"] == row["team"])].sort_values("season").tail(1)[cols].reset_index(drop=True)
        meta = {"task": "squad_availability", "scope": "team", "entity": str(row["team"]),
                "points_per_availability_slope": round(slope, 1)}
        return out, meta

    cur = season or sa["season"].max()
    out = sa[sa["season"] == cur].sort_values("avail_index").head(top_n)[cols].reset_index(drop=True)
    meta = {"task": "squad_availability", "scope": "league_wide", "season": str(cur),
            "points_per_availability_slope": round(slope, 1), "n_entities": len(out)}
    return out, meta


# ===========================================================================
# Q10 — stakeholder (strategic) value
# ===========================================================================

def _stakeholder_frame() -> pd.DataFrame:
    tf = _teams()
    pf = _players()
    cur = tf["season"].max()
    teams = tf[tf["season"] == cur].copy()

    # Squad value + development signal from the player frame (same season).
    pcur = pf[pf["season"] == cur].copy()
    pcur["young_minutes"] = (pcur["age"] <= 23).astype(int) * pcur["minutes"]
    sv = pcur.groupby("team_id").agg(
        squad_value_m=("market_value_m", "sum"),
        avg_age=("age", "mean"),
        _young_min=("young_minutes", "sum"),
        _total_min=("minutes", "sum"),
    ).reset_index()
    sv["young_minutes_share"] = sv["_young_min"] / sv["_total_min"].clip(lower=1.0)
    sv = sv.drop(columns=["_young_min", "_total_min"])
    teams = teams.merge(sv, on="team_id", how="left")

    def _z(s):
        sd = s.std(ddof=0) or 1.0
        return (s - s.mean()) / sd

    teams["z_points"] = _z(teams["points"])
    teams["z_attendance"] = _z(teams["attendance"].fillna(teams["attendance"].median()))
    teams["z_squad_value"] = _z(teams["squad_value_m"].fillna(teams["squad_value_m"].median()))
    teams["z_development"] = _z(teams["young_minutes_share"].fillna(0))
    teams["stakeholder_value_index"] = (
        0.35 * teams["z_points"] + 0.20 * teams["z_attendance"]
        + 0.30 * teams["z_squad_value"] + 0.15 * teams["z_development"]
    ).round(3)
    return teams


def stakeholder_value(entity: Optional[str] = None, top_n: int = 20,
                      query: str = "", **_) -> tuple[pd.DataFrame, dict]:
    teams = _stakeholder_frame()
    cols = ["team", "season", "points", "attendance", "squad_value_m",
            "young_minutes_share", "stakeholder_value_index"]
    teams = teams.copy()
    teams["squad_value_m"] = teams["squad_value_m"].round(1)
    teams["young_minutes_share"] = teams["young_minutes_share"].round(3)

    if entity:
        row = _latest(teams, "team", entity)
        if row is None:
            raise ValueError(f"no Premier League team matching {entity!r}")
        out = teams[teams["team"] == row["team"]][cols].reset_index(drop=True)
        meta = {"task": "stakeholder_value", "scope": "team", "entity": str(row["team"]),
                "index": float(out.iloc[0]["stakeholder_value_index"])}
        return out, meta
    out = teams.sort_values("stakeholder_value_index", ascending=False)[cols].head(top_n).reset_index(drop=True)
    meta = {"task": "stakeholder_value", "scope": "league_wide",
            "season": str(teams["season"].iloc[0]), "n_entities": len(out)}
    return out, meta


# ===========================================================================
# Q9 — in-game event impact (scenario → result-probability shift)
# ===========================================================================

_event_table: Optional[dict] = None


def _event_lookup() -> dict:
    global _event_table
    if _event_table is None:
        import joblib
        p = _ARTEFACTS / "event_impact_v1.pkl"
        if not p.exists():
            raise FileNotFoundError("event_impact table not built; run train_tasks.py")
        _event_table = joblib.load(p)
    return _event_table


def event_impact_scenario(scenario: str, query: str = "") -> tuple[pd.DataFrame, dict]:
    """Empirical P(result | scenario) vs unconditional base rates, from the event lookup table.
    `scenario` is a key into the table (see parse_event_scenario)."""
    tbl = _event_lookup()
    base = tbl["base_rates"]
    scenarios = tbl["scenarios"]
    if scenario not in scenarios:
        avail = ", ".join(sorted(scenarios))
        raise ValueError(f"unknown event scenario {scenario!r}. Available: {avail}")
    entry = scenarios[scenario]
    dist = entry["dist"]
    label = {"H": "home_win", "D": "draw", "A": "away_win"}
    rows = [{
        "result": label[c],
        "baseline_pct": round(100 * base.get(c, 0.0), 1),
        "scenario_pct": round(100 * dist.get(c, 0.0), 1),
        "shift_pct": round(100 * (dist.get(c, 0.0) - base.get(c, 0.0)), 1),
    } for c in ("H", "D", "A")]
    out = pd.DataFrame(rows).sort_values("scenario_pct", ascending=False).reset_index(drop=True)
    meta = {"task": "event_impact", "scope": "scenario", "scenario": scenario,
            "description": entry["desc"], "n_matches": entry["n"],
            "baseline": {label[k]: v for k, v in base.items()},
            "conditional": {label[k]: v for k, v in dist.items()}}
    return out, meta


_all_players = None
_xleague_model = None


def cross_league_forecast(entity: str, dest_league: Optional[str] = None,
                          **_) -> tuple[pd.DataFrame, dict]:
    """Forecast a player's output retention if he moves to `dest_league` (default: the
    strongest OTHER top-5 league). Uses the trained cross_league_translation model."""
    global _all_players, _xleague_model
    from prediction_agent.features.cross_league_features import (
        FEATURE_COLUMNS as XCOLS, LEAGUE_STRENGTH)
    if not entity:
        raise ValueError("cross_league_forecast needs a player name")
    if _all_players is None:
        from prediction_agent.features.player_season_features import build_player_season_features
        _all_players = build_player_season_features("all")
    if _xleague_model is None:
        p = _ARTEFACTS / "cross_league_translation_v1.pkl"
        if not p.exists():
            raise FileNotFoundError("cross_league_translation model not trained")
        from prediction_agent.tasks.base import GenericPredictor
        _xleague_model = GenericPredictor.load(p)

    prow = _latest(_all_players, "player_name", entity)
    if prow is None:
        raise ValueError(f"no player matching {entity!r} in the 5-league data")

    # league_code isn't in FEATURE_COLUMNS; pull it from the row.
    from_league = str(prow.get("league_code", "ENG-PL"))
    from_strength = LEAGUE_STRENGTH.get(from_league, 0.85)
    if dest_league:
        dest_league = dest_league.upper().replace(" ", "-")
        if dest_league not in LEAGUE_STRENGTH:
            # accept friendly names
            alias = {"PREMIER-LEAGUE": "ENG-PL", "EPL": "ENG-PL", "LA-LIGA": "ESP-LL",
                     "SERIE-A": "ITA-SA", "BUNDESLIGA": "GER-BL", "LIGUE-1": "FRA-L1"}
            dest_league = alias.get(dest_league, dest_league)
    if not dest_league or dest_league not in LEAGUE_STRENGTH:
        # strongest league other than the origin
        dest_league = max((l for l in LEAGUE_STRENGTH if l != from_league),
                          key=lambda l: LEAGUE_STRENGTH[l])
    to_strength = LEAGUE_STRENGTH[dest_league]

    feats = {}
    for c in XCOLS:
        if c == "from_strength":
            feats[c] = from_strength
        elif c == "to_strength":
            feats[c] = to_strength
        elif c == "league_strength_delta":
            feats[c] = to_strength - from_strength
        elif c == "transfer_fee_m":
            feats[c] = 0.0
        else:
            feats[c] = float(prow[c]) if c in prow.index else 0.0

    retention = float(_xleague_model.predict_from_features(feats).prediction)
    cur_ga = float(prow["ga_per90"])
    rows = [{
        "player": str(prow["player_name"]), "from_league": from_league,
        "to_league": dest_league, "current_ga_per90": round(cur_ga, 3),
        "predicted_retention": round(retention, 3),
        "predicted_ga_per90": round(cur_ga * retention, 3),
        "verdict": ("improves" if retention > 1.05 else "declines" if retention < 0.9
                    else "maintains"),
    }]
    meta = {"task": "cross_league_translation", "scope": "player",
            "entity": str(prow["player_name"]), "from_league": from_league,
            "to_league": dest_league, "predicted_retention": round(retention, 3)}
    return pd.DataFrame(rows), meta


def parse_event_scenario(query: str) -> str:
    """Map a natural-language scenario to an event lookup-table key. Defaults to the most
    asked-about scenario (home scores first early) when nothing specific is detected."""
    q = (query or "").lower()
    away = "away" in q and "home" not in q
    ht_lead = any(w in q for w in ("lead at half", "leading at half", "ahead at half",
                                   "half-time lead", "halftime lead", "ht lead"))
    red = any(w in q for w in ("red card", "sent off", "dismissal", "down to ten", "down to 10"))
    first = any(w in q for w in ("score first", "scores first", "first goal", "opening goal",
                                 "1-0", "open the scoring", "early goal"))
    early = any(w in q for w in ("early", "first 15", "opening minutes", "within 15"))

    if ht_lead and red:
        return "home_leads_ht_away_red"
    if red:
        return "home_red_card" if (not away and "home" in q) else "away_red_card"
    if ht_lead:
        return "away_leads_ht" if away else "home_leads_ht"
    if first:
        if away:
            return "away_scores_first_early" if early else "away_scores_first"
        return "home_scores_first_early" if early else "home_scores_first"
    return "home_scores_first_early"
