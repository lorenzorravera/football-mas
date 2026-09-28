"""
Team-season feature builder (D1) — shared by the Q1–Q4 team-season tasks.

Builds one strictly-causal feature row per (team, season N) from the four team-season
tables, and attaches NEXT-season (N+1) targets so a model learns to forecast the upcoming
season from what is known at the end of the current one.

Targets attached:
  next_rank, next_points        season N+1 outcomes (NULL if team not in PL N+1)
  delta_rank  = next_rank - rank (positive = dropped places)
  delta_points = next_points - points
  season_class                  4-class bucket of next_rank (top4 / european / mid / relegation)
  movement_class                'up5' | 'down5' | 'stable' (≥5 place swing)
  home_reliance_index           current-season home dependency (for the computed Q4 task)

Data: ENG-PL only, 2020-21..2024-25 (5 seasons → ~80 N→N+1 transitions). Small, so models
are honestly illustrative; train with leave-one-season-out / latest-season holdout and report
calibration. Connection uses DATABASE_URI directly (team-season tables live there).
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2


# Curated numeric feature set (season N). Kept explicit to control NaNs + ordering.
FEATURE_COLUMNS = [
    "rank", "points", "goals_for", "goals_against", "goal_difference",
    "wins", "draws", "losses", "top_scorer_goals", "attendance",
    "home_points", "away_points", "home_goals_for", "away_goals_for",
    "home_goals_against", "away_goals_against", "home_away_point_gap",
    "possession", "average_age", "players_used", "shots", "shots_on_target",
    "goals_per_shot", "clean_sheets", "save_percentage",
    "yellow_cards", "red_cards", "fouls_committed",
    "opp_shots", "opp_goals", "opp_possession",
]

_QUERY = """
    SELECT s.season AS season, tss.team_id AS team_id, tss.tss_team AS team,
        tss.tss_rank AS rank, tss.tss_points AS points,
        tss.tss_goals_for AS goals_for, tss.tss_goals_against AS goals_against,
        tss.tss_goal_difference AS goal_difference,
        tss.tss_wins AS wins, tss.tss_draws AS draws, tss.tss_losses AS losses,
        tss.tss_top_scorer_goals AS top_scorer_goals, tss.tss_attendance AS attendance,
        ha.tshas_home_points AS home_points, ha.tshas_away_points AS away_points,
        ha.tshas_home_goals_for AS home_goals_for, ha.tshas_away_goals_for AS away_goals_for,
        ha.tshas_home_goals_against AS home_goals_against,
        ha.tshas_away_goals_against AS away_goals_against,
        f.tssf_possession_percentage AS possession, f.tssf_average_age AS average_age,
        f.tssf_players_used AS players_used, f.tssf_shots AS shots,
        f.tssf_shots_on_target AS shots_on_target, f.tssf_goals_per_shot AS goals_per_shot,
        f.tssf_clean_sheets AS clean_sheets, f.tssf_save_percentage AS save_percentage,
        f.tssf_yellow_cards AS yellow_cards, f.tssf_red_cards AS red_cards,
        f.tssf_fouls_committed AS fouls_committed,
        a.tssa_shots AS opp_shots, a.tssa_goals AS opp_goals,
        a.tssa_possession_percentage AS opp_possession
    FROM team_season_standings tss
    JOIN seasons s ON tss.season_id = s.season_id
    JOIN competitions c ON s.competition_id = c.competition_id
    LEFT JOIN team_season_home_away_standings ha
        ON ha.team_id = tss.team_id AND ha.season_id = tss.season_id
    LEFT JOIN team_season_stats_for f
        ON f.team_id = tss.team_id AND f.season_id = tss.season_id
    LEFT JOIN team_season_stats_against a
        ON a.team_id = tss.team_id AND a.season_id = tss.season_id
    WHERE c.league_code = 'ENG-PL'
    ORDER BY tss.team_id, s.season
"""


def _connect():
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError("DATABASE_URI not set")
    return psycopg2.connect(uri)


def _engine():
    """SQLAlchemy engine for pandas.read_sql (psycopg2 connections raise a
    UserWarning under modern pandas). Falls back to a raw psycopg2 connection
    if SQLAlchemy isn't installed."""
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError("DATABASE_URI not set")
    try:
        from sqlalchemy import create_engine
    except ImportError:
        return psycopg2.connect(uri)
    # SQLAlchemy 2.x rejects the legacy "postgres://" scheme Aiven hands out.
    if uri.startswith("postgres://"):
        uri = "postgresql+psycopg2://" + uri[len("postgres://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg2://" + uri[len("postgresql://"):]
    return create_engine(uri)


def season_class(rank: float) -> Optional[str]:
    if rank is None or (isinstance(rank, float) and np.isnan(rank)):
        return None
    r = int(rank)
    if r <= 4:
        return "top4"
    if r <= 7:
        return "european"
    if r <= 17:
        return "mid_table"
    return "relegation"


def movement_class(delta_rank: float) -> Optional[str]:
    if delta_rank is None or (isinstance(delta_rank, float) and np.isnan(delta_rank)):
        return None
    if delta_rank <= -5:      # next_rank lower number = moved UP ≥5 places
        return "up5"
    if delta_rank >= 5:
        return "down5"
    return "stable"


def load_team_season_frame() -> pd.DataFrame:
    """Raw per-(team, season) rows with derived features (no targets yet)."""
    eng = _engine()
    try:
        df = pd.read_sql(_QUERY, eng)
    finally:
        eng.dispose() if hasattr(eng, "dispose") else eng.close()

    # Derived features
    df["home_away_point_gap"] = df["home_points"] - df["away_points"]
    tot = (df["home_points"] + df["away_points"]).replace(0, np.nan)
    df["home_reliance_index"] = (df["home_points"] / tot).round(3)

    # Coerce features numeric; median-fill residual NaNs so models never see NaN.
    for c in FEATURE_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(df[FEATURE_COLUMNS].median(numeric_only=True))
    return df


def build_team_season_features() -> pd.DataFrame:
    """Per-(team, season N) features + next-season (N+1) targets. Returns ALL rows;
    rows with a NULL next_rank are inference-only (team's final observed season)."""
    df = load_team_season_frame().sort_values(["team_id", "season"]).reset_index(drop=True)

    # Next-season targets via per-team shift on the season-ordered frame.
    df["next_rank"] = df.groupby("team_id")["rank"].shift(-1)
    df["next_points"] = df.groupby("team_id")["points"].shift(-1)
    df["next_season"] = df.groupby("team_id")["season"].shift(-1)
    df["delta_rank"] = df["next_rank"] - df["rank"]
    df["delta_points"] = df["next_points"] - df["points"]
    df["season_class"] = df["next_rank"].apply(season_class)
    df["movement_class"] = df["delta_rank"].apply(movement_class)
    return df


def training_frame() -> pd.DataFrame:
    """Only rows with a known next season (usable for supervised training)."""
    df = build_team_season_features()
    return df[df["next_rank"].notna()].reset_index(drop=True)


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[2] / "agent_v4" / ".env", override=True) \
        if (Path(__file__).resolve().parents[2] / "agent_v4").exists() else None
    f = build_team_season_features()
    print("rows:", len(f), "| trainable:", f["next_rank"].notna().sum())
    print(f[["season", "team", "rank", "next_rank", "season_class", "movement_class"]].head(12).to_string(index=False))
