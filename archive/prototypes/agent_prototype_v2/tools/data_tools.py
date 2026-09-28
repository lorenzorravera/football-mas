"""
Data Tools Module

Pure functions for loading and filtering Premier League match data.
Now queries PostgreSQL via the db module instead of local CSV files.
No LLM calls, no analytics - just data retrieval.
"""

import pandas as pd
import logging
from typing import List, Optional
from db import read_sql

logger = logging.getLogger(__name__)

# Season format in the database is "YYYY_YYYY"
VALID_SEASONS = [
    "2021_2022",
    "2022_2023",
    "2023_2024",
    "2024_2025",
    "2025_2026",
]


def get_all_seasons() -> List[str]:
    """Get list of available seasons from the database."""
    try:
        df = read_sql("SELECT season FROM seasons ORDER BY season")
        return df["season"].tolist()
    except Exception as e:
        logger.warning(f"Could not load seasons: {e}")
        return VALID_SEASONS


def get_all_teams() -> List[str]:
    """Get list of all unique teams from the database."""
    try:
        df = read_sql("SELECT team_name FROM teams ORDER BY team_name")
        return df["team_name"].tolist()
    except Exception as e:
        logger.warning(f"Could not load teams: {e}")
        return []


def load_season_data(season: str) -> pd.DataFrame:
    """
    Load match data for a specific season.

    Args:
        season: Season identifier in YYYY_YYYY format (e.g. "2024_2025")

    Returns:
        DataFrame with match data including team names
    """
    query = """
        SELECT
            m.match_id,
            m.match_date AS date,
            m.kickoff_time,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            m.ft_home_goals,
            m.ft_away_goals,
            m.ft_result,
            m.ht_home_goals,
            m.ht_away_goals,
            m.ht_result,
            r.referee_name AS referee,
            s.season
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.team_id
        JOIN teams at ON m.away_team_id = at.team_id
        JOIN referees r ON m.referee_id = r.referee_id
        JOIN seasons s ON m.season_id = s.season_id
        WHERE s.season = :season
        ORDER BY m.match_date
    """
    df = read_sql(query, params={"season": season})

    if df.empty:
        raise ValueError(f"No data found for season: {season}")

    logger.info(f"Loaded {len(df)} matches from {season}")
    return df


def load_all_seasons() -> pd.DataFrame:
    """Load and combine all available seasons."""
    query = """
        SELECT
            m.match_id,
            m.match_date AS date,
            m.kickoff_time,
            ht.team_name AS home_team,
            at.team_name AS away_team,
            m.ft_home_goals,
            m.ft_away_goals,
            m.ft_result,
            m.ht_home_goals,
            m.ht_away_goals,
            m.ht_result,
            r.referee_name AS referee,
            s.season
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.team_id
        JOIN teams at ON m.away_team_id = at.team_id
        JOIN referees r ON m.referee_id = r.referee_id
        JOIN seasons s ON m.season_id = s.season_id
        ORDER BY m.match_date
    """
    df = read_sql(query)

    if df.empty:
        raise Exception("No data could be loaded")

    logger.info(f"Loaded {len(df)} total matches across all seasons")
    return df


def filter_by_teams(df: pd.DataFrame, teams: List[str]) -> pd.DataFrame:
    """
    Filter matches involving specific teams.

    Args:
        df: Match data (from load_season_data or load_all_seasons)
        teams: List of team names (empty list = all teams)

    Returns:
        Filtered DataFrame
    """
    if not teams:
        return df

    mask = df["home_team"].isin(teams) | df["away_team"].isin(teams)
    filtered = df[mask].copy()

    logger.info(f"Filtered to {len(filtered)} matches for {teams}")
    return filtered


def filter_by_opponent(df: pd.DataFrame, team: str, opponent: str) -> pd.DataFrame:
    """
    Filter head-to-head matches between two specific teams.

    Args:
        df: Match data
        team: First team name
        opponent: Second team name

    Returns:
        Filtered DataFrame with only matches between these two teams
    """
    mask = (
        (df["home_team"] == team) & (df["away_team"] == opponent)
    ) | (
        (df["home_team"] == opponent) & (df["away_team"] == team)
    )

    filtered = df[mask].copy()
    logger.info(f"Found {len(filtered)} matches between {team} and {opponent}")
    return filtered


def filter_by_date_range(
    df: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Filter matches within a date range.

    Args:
        df: Match data
        start_date: Start date in YYYY-MM-DD format or None
        end_date: End date in YYYY-MM-DD format or None

    Returns:
        Filtered DataFrame
    """
    if start_date:
        df = df[df["date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["date"] <= pd.to_datetime(end_date)]
    return df


def get_last_n_matches(
    df: pd.DataFrame, team: Optional[str] = None, n: int = 5
) -> pd.DataFrame:
    """
    Get last N matches for a team (or overall if no team specified).

    Args:
        df: Match data
        team: Team name or None for all matches
        n: Number of matches to return

    Returns:
        DataFrame with last N matches sorted by date descending
    """
    if team:
        mask = (df["home_team"] == team) | (df["away_team"] == team)
        df = df[mask]

    result = df.sort_values("date", ascending=False).head(n)
    logger.info(f"Retrieved last {n} matches" + (f" for {team}" if team else ""))
    return result


def load_team_stats(season: Optional[str] = None) -> pd.DataFrame:
    """
    Load per-team per-match stats from match_team_stats.
    This is the main table for analytics — one row per team per match.

    Args:
        season: Optional season filter in YYYY_YYYY format

    Returns:
        DataFrame with team-level stats for each match
    """
    query = """
        SELECT
            mts.match_team_stat_id,
            mts.match_id,
            t.team_name AS team,
            opp.team_name AS opponent,
            mts.is_home,
            m.match_date AS date,
            s.season,
            mts.goals_scored,
            mts.goals_conceded,
            mts.shots,
            mts.shots_on_target,
            mts.fouls,
            mts.corners,
            mts.yellow_cards,
            mts.red_cards,
            mts.points
        FROM match_team_stats mts
        JOIN teams t ON mts.team_id = t.team_id
        JOIN teams opp ON mts.opponent_id = opp.team_id
        JOIN matches m ON mts.match_id = m.match_id
        JOIN seasons s ON m.season_id = s.season_id
        {where_clause}
        ORDER BY m.match_date
    """
    if season:
        query = query.format(where_clause="WHERE s.season = :season")
        df = read_sql(query, params={"season": season})
    else:
        query = query.format(where_clause="")
        df = read_sql(query)

    logger.info(f"Loaded {len(df)} team-match stat rows" + (f" for {season}" if season else ""))
    return df


def load_league_table(season: str) -> pd.DataFrame:
    """
    Load the pre-built league table view for a completed season.
    Note: do NOT use this for mid-season or 'as of date' queries.

    Args:
        season: Season in YYYY_YYYY format (e.g. "2023_2024")

    Returns:
        DataFrame with full league standings
    """
    query = """
        SELECT *
        FROM league_table
        WHERE season = :season
        ORDER BY points DESC, gd DESC, gf DESC
    """
    df = read_sql(query, params={"season": season})
    logger.info(f"Loaded league table for {season} ({len(df)} teams)")
    return df