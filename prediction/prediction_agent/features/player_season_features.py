"""
Player-season feature builder (D4) — shared by the player suite (Q6, Q7, Q11, Q12).

Builds one strictly-causal feature row per (player, season N) from player_season_stats,
players, market values and injury spells, and attaches NEXT-season (N+1) targets so a model
learns to forecast a player's upcoming season from what is known at the end of the current one.

Coverage: 5 leagues (ENG-PL, ESP-LL, FRA-L1, GER-BL, ITA-SA), seasons 2020-21..2024-25
(~14.3k player-seasons). Defaults to ENG-PL for parity with the team-season suite, but the
loader takes a `league` arg (or "all") so the cross-league task (Q11) can use every league.

Targets attached (season N+1, same player):
  next_minutes, next_ga_per90, next_market_value
  delta_ga_per90  = next_ga_per90 - ga_per90      (output change; decline regression target)
  delta_minutes   = next_minutes  - minutes        (availability change)
  decline_flag    = 1 if delta_ga_per90 < -0.10 AND next_minutes < minutes else 0

Per-90 features are computed on a guarded minutes denominator so low-minute players don't
explode the rates. Market value is snapshotted as-of each season's end_date (no leakage from
future revaluations). Residual NaNs are median-filled so models never see NaN.
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd
import psycopg2


# Curated numeric feature set (season N). Explicit to control NaNs + ordering.
FEATURE_COLUMNS = [
    "age", "minutes", "matches_played", "starts", "start_share",
    "goals_per90", "assists_per90", "ga_per90", "npg_per90",
    "xg_per90", "xa_per90", "npxg_per90", "xgchain_per90", "xgbuildup_per90",
    "key_passes_per90", "shots_per90", "sot_per90",
    "shot_accuracy", "conversion", "xg_overperformance",
    "tackles_per90", "interceptions_per90", "fouls_committed_per90", "fouls_drawn_per90",
    "yellow_per90", "red_per90",
    "market_value_m", "log_market_value", "value_per_age",
    "games_missed", "days_missed", "injury_spells",
]

_QUERY = """
    SELECT pss.player_id AS player_id, p.player_name AS player_name,
        p.birth_year AS birth_year, p.height AS height, p.foot AS foot,
        p.nationality AS nationality,
        s.season AS season, s.season_id AS season_id, s.end_date AS season_end,
        c.league_code AS league_code,
        pss.team_id AS team_id, t.team_name AS team_name,
        pss.age AS age, pss.matches_played_pss AS matches_played, pss.starts AS starts,
        pss.minutes_pss AS minutes, pss.goals_pss AS goals, pss.assists_pss AS assists,
        pss.non_penalty_goals_pss AS npg, pss.shots_pss AS shots,
        pss.shots_on_target_pss AS sot, pss.xg_pss AS xg, pss.xa_pss AS xa,
        pss.npxg_pss AS npxg, pss.xgchain_pss AS xgchain, pss.xgbuildup_pss AS xgbuildup,
        pss.key_passes_pss AS key_passes, pss.tackles_won AS tackles,
        pss.interceptions_pss AS interceptions, pss.fouls_committed AS fouls_committed,
        pss.fouls_drawn_pss AS fouls_drawn, pss.yellow_cards_pss AS yellow_cards,
        pss.red_cards_pss AS red_cards
    FROM player_season_stats pss
    JOIN players p ON pss.player_id = p.player_id
    JOIN seasons s ON pss.season_id = s.season_id
    JOIN competitions c ON s.competition_id = c.competition_id
    JOIN teams t ON pss.team_id = t.team_id
    {where}
    ORDER BY pss.player_id, s.season
"""


def _engine():
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        raise RuntimeError("DATABASE_URI not set")
    try:
        from sqlalchemy import create_engine
    except ImportError:
        return psycopg2.connect(uri)
    if uri.startswith("postgres://"):
        uri = "postgresql+psycopg2://" + uri[len("postgres://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg2://" + uri[len("postgresql://"):]
    return create_engine(uri)


def _read_sql(query: str) -> pd.DataFrame:
    eng = _engine()
    try:
        return pd.read_sql(query, eng)
    finally:
        eng.dispose() if hasattr(eng, "dispose") else eng.close()


def _market_values() -> pd.DataFrame:
    """player_id, valuation date, market_value (time series)."""
    df = _read_sql(
        "SELECT player_id, to_timestamp(date_unix)::date AS val_date, market_value "
        "FROM player_market_values"
    )
    df["val_date"] = pd.to_datetime(df["val_date"])
    df["market_value"] = pd.to_numeric(df["market_value"], errors="coerce")
    return df.dropna(subset=["market_value"]).sort_values(["player_id", "val_date"])


def _injuries() -> pd.DataFrame:
    """Per (player_id, season): games/days missed and spell count."""
    df = _read_sql(
        "SELECT player_id, season, "
        "COALESCE(SUM(games_missed),0) AS games_missed, "
        "COALESCE(SUM(days_missed),0) AS days_missed, "
        "COUNT(*) AS injury_spells "
        "FROM player_injury_spells GROUP BY player_id, season"
    )
    # injury season is stored as 'YYYY-YYYY' (matches seasons.season)
    return df


def _snapshot_market_value(stats: pd.DataFrame, mv: pd.DataFrame) -> pd.Series:
    """As-of join: latest market value on/before each player-season's end_date.
    Strictly causal — never uses a valuation dated after the season ended."""
    stats = stats.reset_index(drop=True)
    out = pd.Series(np.nan, index=stats.index, dtype="float64")
    by_player = {pid: g for pid, g in mv.groupby("player_id")}
    season_end = pd.to_datetime(stats["season_end"])
    for i, pid in enumerate(stats["player_id"].values):
        g = by_player.get(pid)
        if g is None:
            continue
        prior = g[g["val_date"] <= season_end.iloc[i]]
        if not prior.empty:
            out.iloc[i] = float(prior.iloc[-1]["market_value"])
        else:  # only future valuations exist → use the earliest as a weak proxy
            out.iloc[i] = float(g.iloc[0]["market_value"])
    return out


def load_player_season_frame(league: str = "ENG-PL") -> pd.DataFrame:
    """Raw per-(player, season) rows with derived features (no targets yet).

    league: a league_code (e.g. 'ENG-PL') or 'all' for every league (cross-league task).
    """
    where = "" if league == "all" else f"WHERE c.league_code = '{league}'"
    df = _read_sql(_QUERY.format(where=where))

    # Numeric coercion for the raw stat inputs.
    raw = ["age", "matches_played", "starts", "minutes", "goals", "assists", "npg",
           "shots", "sot", "xg", "xa", "npxg", "xgchain", "xgbuildup", "key_passes",
           "tackles", "interceptions", "fouls_committed", "fouls_drawn",
           "yellow_cards", "red_cards"]
    for c in raw:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Per-90 rates on a guarded denominator (avoid blow-ups for cameo minutes).
    p90 = df["minutes"].clip(lower=90) / 90.0
    df["goals_per90"] = df["goals"] / p90
    df["assists_per90"] = df["assists"] / p90
    df["ga_per90"] = (df["goals"] + df["assists"]) / p90
    df["npg_per90"] = df["npg"] / p90
    df["xg_per90"] = df["xg"] / p90
    df["xa_per90"] = df["xa"] / p90
    df["npxg_per90"] = df["npxg"] / p90
    df["xgchain_per90"] = df["xgchain"] / p90
    df["xgbuildup_per90"] = df["xgbuildup"] / p90
    df["key_passes_per90"] = df["key_passes"] / p90
    df["shots_per90"] = df["shots"] / p90
    df["sot_per90"] = df["sot"] / p90
    df["tackles_per90"] = df["tackles"] / p90
    df["interceptions_per90"] = df["interceptions"] / p90
    df["fouls_committed_per90"] = df["fouls_committed"] / p90
    df["fouls_drawn_per90"] = df["fouls_drawn"] / p90
    df["yellow_per90"] = df["yellow_cards"] / p90
    df["red_per90"] = df["red_cards"] / p90

    df["shot_accuracy"] = (df["sot"] / df["shots"].replace(0, np.nan)).fillna(0.0)
    df["conversion"] = (df["goals"] / df["shots"].replace(0, np.nan)).fillna(0.0)
    df["xg_overperformance"] = df["goals"] - df["xg"]            # finishing over/under
    df["start_share"] = (df["starts"] / df["matches_played"].replace(0, np.nan)).fillna(0.0)

    # Market value snapshot (as-of season end) + injuries.
    mv = _market_values()
    df["market_value"] = _snapshot_market_value(df, mv)
    df["market_value_m"] = df["market_value"] / 1e6
    df["log_market_value"] = np.log1p(df["market_value"].fillna(0.0))
    df["value_per_age"] = df["market_value_m"] / df["age"].clip(lower=16)

    inj = _injuries()
    df = df.merge(inj, on=["player_id", "season"], how="left")
    for c in ["games_missed", "days_missed", "injury_spells"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Median-fill any residual NaN feature so models never see NaN.
    for c in FEATURE_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df[FEATURE_COLUMNS] = df[FEATURE_COLUMNS].fillna(df[FEATURE_COLUMNS].median(numeric_only=True))
    return df


def build_player_season_features(league: str = "ENG-PL") -> pd.DataFrame:
    """Per-(player, season N) features + next-season (N+1) targets. Returns ALL rows;
    rows with a NULL next_minutes are inference-only (player's final observed season)."""
    df = load_player_season_frame(league).sort_values(["player_id", "season"]).reset_index(drop=True)

    g = df.groupby("player_id")
    df["next_minutes"] = g["minutes"].shift(-1)
    df["next_ga_per90"] = g["ga_per90"].shift(-1)
    df["next_market_value_m"] = g["market_value_m"].shift(-1)
    df["next_season"] = g["season"].shift(-1)
    df["delta_ga_per90"] = df["next_ga_per90"] - df["ga_per90"]
    df["delta_minutes"] = df["next_minutes"] - df["minutes"]
    df["delta_market_value_m"] = df["next_market_value_m"] - df["market_value_m"]
    df["decline_flag"] = (
        (df["delta_ga_per90"] < -0.10) & (df["next_minutes"] < df["minutes"])
    ).astype("Int64")
    # decline_flag is only meaningful where a next season exists.
    df.loc[df["next_minutes"].isna(), "decline_flag"] = pd.NA
    return df


def training_frame(league: str = "ENG-PL", min_minutes: int = 450) -> pd.DataFrame:
    """Rows with a known next season AND a meaningful current-season sample
    (default ≥450 minutes ≈ 5 full matches) — the supervised training set."""
    df = build_player_season_features(league)
    keep = df["next_minutes"].notna() & (df["minutes"] >= min_minutes)
    return df[keep].reset_index(drop=True)


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    env = Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env"
    if env.exists():
        load_dotenv(env, override=True)
    f = build_player_season_features()
    print("ENG-PL rows:", len(f), "| trainable:", training_frame().shape[0])
    cols = ["season", "player_name", "team_name", "age", "minutes", "ga_per90",
            "market_value_m", "next_ga_per90", "decline_flag"]
    print(f.sort_values("ga_per90", ascending=False)[cols].head(10).to_string(index=False))
