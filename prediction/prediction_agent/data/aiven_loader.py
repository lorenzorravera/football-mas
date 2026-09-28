"""
Aiven Postgres loader for the prediction agent's training pipeline.

Pulls matches, player-match performance (for xG aggregation), transfers,
injuries, and reference tables from the stats database. Returns clean
DataFrames keyed by integer IDs (never by name — per the metadata caveat).

Connection is read from DATABASE_URI. The functions here are read-only.

Why a separate loader (not direct queries from training scripts):
  - All SQL lives in one place; schema changes touch one file.
  - Easy to dump to parquet (see scripts/dump_to_parquet.py) for
    reproducible offline training.
  - The agent at inference time uses different code paths (live queries
    via the existing data_analyst), not this loader.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

import pandas as pd

log = logging.getLogger(__name__)

# Default league. Metadata confirms ENG-PL is the only loaded league for now.
DEFAULT_LEAGUE = "ENG-PL"


@contextmanager
def _connection() -> Iterator:
    """Yield a psycopg2 connection. Imported lazily so the module loads
    without psycopg2 installed (e.g. when only the inference wrapper is used).

    Prefers STATS_DATABASE_URI (the dedicated stats Postgres for matches,
    player data, transfers, etc.) and falls back to DATABASE_URI for
    backward compatibility with environments that only set one URI.
    """
    import psycopg2

    def _valid(u: str | None) -> bool:
        # Guard against an unexpanded placeholder like STATS_DATABASE_URI="$DATABASE_URI":
        # it is set-but-not-a-DSN, which would defeat the plain `or` fallback and crash
        # psycopg2 with 'invalid dsn'. Require a real postgres URI scheme.
        return bool(u) and "://" in u and not u.lstrip().startswith("$")

    stats = os.environ.get("STATS_DATABASE_URI")
    uri = stats if _valid(stats) else os.environ.get("DATABASE_URI")
    if not _valid(uri):
        raise RuntimeError(
            "Neither STATS_DATABASE_URI nor DATABASE_URI is set to a valid postgres URI. "
            "Export a real DSN (postgres://...) before training/inference."
        )
    conn = psycopg2.connect(uri)
    try:
        yield conn
    finally:
        conn.close()


def load_matches(seasons: Optional[list[str]] = None,
                 league_code: str = DEFAULT_LEAGUE) -> pd.DataFrame:
    """
    Load the matches table joined to seasons (for human-readable season label).

    Returns one row per match with:
      game_id, season, match_date, matchweek, home_team_id, away_team_id,
      home_score, away_score, ft_result, home_shots, away_shots,
      home_shots_on_target, away_shots_on_target, home_corners, away_corners,
      avg_home_odds, avg_draw_odds, avg_away_odds, ...

    `seasons` filter is on the season string (e.g. ["2020-2021", "2021-2022"]).
    """
    where_clauses = ["c.league_code = %s"]
    params: list = [league_code]
    if seasons:
        where_clauses.append("s.season = ANY(%s)")
        params.append(seasons)

    query = f"""
        SELECT
            m.game_id,
            s.season,
            s.season_id,
            m.match_date,
            m.matchweek,
            m.kickoff_time,
            m.home_team_id,
            m.away_team_id,
            m.home_score,
            m.away_score,
            m.ft_result,
            m.ht_home_score,
            m.ht_away_score,
            m.home_shots,
            m.away_shots,
            m.home_shots_on_target,
            m.away_shots_on_target,
            m.home_corners,
            m.away_corners,
            m.home_fouls,
            m.away_fouls,
            m.home_yellow_cards,
            m.away_yellow_cards,
            m.home_red_cards,
            m.away_red_cards,
            m.avg_home_odds,
            m.avg_draw_odds,
            m.avg_away_odds,
            m.avg_over25_odds,
            m.avg_under25_odds,
            m.attendance_m,
            m.referee
        FROM matches m
        JOIN seasons s ON m.season_id = s.season_id
        JOIN competitions c ON s.competition_id = c.competition_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY m.match_date, m.game_id
    """

    with _connection() as conn:
        df = pd.read_sql(query, conn, params=params)
    log.info("Loaded %d matches", len(df))
    return df


def load_team_match_xg(seasons: Optional[list[str]] = None,
                       league_code: str = DEFAULT_LEAGUE) -> pd.DataFrame:
    """
    Aggregate player-match xG up to team-match level.

    For each (game_id, team), returns:
      total_xg, total_npxg, total_xa, total_xgchain, total_xgbuildup,
      total_key_passes, total_shots, total_shots_on_target.

    The team for each player-match is derived from the matches table: a
    player's team in a given match is the home or away team. We need a
    separate join to figure out which side each player was on. The metadata
    doesn't expose this directly on player_match_performance, so we infer
    via the player_season_stats table (player_id × season_id → team_id),
    then map to home/away by comparing against the match's team IDs.

    This is the one piece of feature engineering that requires real
    thought; everything else is mechanical.
    """
    where_clauses = ["c.league_code = %s"]
    params: list = [league_code]
    if seasons:
        where_clauses.append("s.season = ANY(%s)")
        params.append(seasons)

    # Strategy:
    #   1. For each (player_id, season_id), find their team_id from player_season_stats.
    #      If a player played for multiple teams in a season, pick the team
    #      with the most starts — best heuristic without per-match team info.
    #   2. Join player_match_performance to (player_id, season_id) → team_id.
    #   3. Aggregate up to (game_id, team_id).
    #   4. Classify each row as home or away by comparing to matches.
    #
    # Result: one row per (game_id, side) with team-aggregated xG metrics.

    query = f"""
        WITH
        player_team_in_season AS (
            -- For each (player, season), pick the team where they had most starts.
            SELECT DISTINCT ON (pss.player_id, pss.season_id)
                pss.player_id,
                pss.season_id,
                pss.team_id
            FROM player_season_stats pss
            ORDER BY pss.player_id, pss.season_id, pss.starts DESC NULLS LAST
        ),
        player_match_with_team AS (
            SELECT
                pmp.game_id,
                pmp.player_id,
                ptis.team_id,
                pmp.xg_pmp,
                pmp.npxg_pmp,
                pmp.xa_pmp,
                pmp.xgchain_pmp,
                pmp.xgbuildup_pmp,
                pmp.key_passes_pmp,
                pmp.match_shots,
                pmp.shots_on_target_pmp,
                pmp.minutes_played
            FROM player_match_performance pmp
            JOIN competitions c ON c.league_code = pmp.league_code
            JOIN seasons s
                ON s.season = pmp.season
               AND s.competition_id = c.competition_id
            JOIN player_team_in_season ptis
                ON ptis.player_id = pmp.player_id
               AND ptis.season_id = s.season_id
            WHERE {' AND '.join(where_clauses)}
        ),
        team_match_aggregated AS (
            SELECT
                game_id,
                team_id,
                COALESCE(SUM(xg_pmp), 0)::float       AS team_xg,
                COALESCE(SUM(npxg_pmp), 0)::float     AS team_npxg,
                COALESCE(SUM(xa_pmp), 0)::float       AS team_xa,
                COALESCE(SUM(xgchain_pmp), 0)::float  AS team_xgchain,
                COALESCE(SUM(xgbuildup_pmp), 0)::float AS team_xgbuildup,
                COALESCE(SUM(key_passes_pmp), 0)::int AS team_key_passes,
                COALESCE(SUM(match_shots), 0)::int    AS team_total_shots,
                COALESCE(SUM(shots_on_target_pmp), 0)::int AS team_total_sot,
                COALESCE(SUM(minutes_played), 0)::int AS team_total_minutes
            FROM player_match_with_team
            GROUP BY game_id, team_id
        )
        SELECT
            tma.*,
            CASE
                WHEN m.home_team_id = tma.team_id THEN 'home'
                WHEN m.away_team_id = tma.team_id THEN 'away'
                ELSE 'unknown'
            END AS side
        FROM team_match_aggregated tma
        JOIN matches m ON m.game_id = tma.game_id
    """

    with _connection() as conn:
        df = pd.read_sql(query, conn, params=params)
    log.info("Loaded %d team-match xG rows", len(df))

    # Drop the rare 'unknown' rows (player whose season-team didn't match this
    # game's home/away — typically mid-season transfers in the same league).
    unknowns = (df["side"] == "unknown").sum()
    if unknowns:
        log.warning("Dropping %d team-match rows with unknown side (mid-season transfers?)", unknowns)
        df = df[df["side"] != "unknown"].copy()
    return df


def join_matches_with_xg(matches: pd.DataFrame, team_xg: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot team_xg to home/away columns and merge into matches.
    Result has one row per match with home_team_xg, away_team_xg, etc.
    """
    metric_cols = [c for c in team_xg.columns
                   if c not in ("game_id", "team_id", "side")]

    # Pivot: one column per (side, metric)
    pivot = team_xg.pivot(index="game_id", columns="side", values=metric_cols)
    # Flatten the MultiIndex columns: e.g. ('team_xg', 'home') -> 'home_team_xg'
    pivot.columns = [f"{side}_{metric}" for metric, side in pivot.columns]
    pivot = pivot.reset_index()

    merged = matches.merge(pivot, on="game_id", how="left")

    # Fill missing xG (matches with no player_match_performance loaded) with 0.
    # In practice, this should never happen for ENG-PL; if it does we want to know.
    xg_cols = [c for c in merged.columns if c.startswith(("home_team_", "away_team_"))]
    missing = merged[xg_cols].isna().any(axis=1).sum()
    if missing:
        log.warning("%d matches have missing xG aggregations; filling with 0", missing)
        merged[xg_cols] = merged[xg_cols].fillna(0)
    return merged


def load_teams() -> pd.DataFrame:
    """Reference table. Used to map team_id → team_name for display only."""
    with _connection() as conn:
        return pd.read_sql("SELECT team_id, team_name FROM teams ORDER BY team_id", conn)


def load_seasons(league_code: str = DEFAULT_LEAGUE) -> pd.DataFrame:
    """Reference table."""
    with _connection() as conn:
        return pd.read_sql(
            """
            SELECT s.season_id, s.season, s.start_date, s.end_date, c.league_code
            FROM seasons s
            JOIN competitions c ON s.competition_id = c.competition_id
            WHERE c.league_code = %s
            ORDER BY s.start_date
            """, conn, params=(league_code,))
