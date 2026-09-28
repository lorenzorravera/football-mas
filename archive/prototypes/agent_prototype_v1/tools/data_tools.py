"""
Data Tools Module

Pure functions for loading and filtering Premier League match data.
No LLM calls, no analytics - just data retrieval.
"""

import pandas as pd
import os
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = "data/raw"
SEASON_FILES = {
    "2020-21": "FD20.csv",
    "2021-22": "FD21.csv",
    "2022-23": "FD22.csv",
    "2023-24": "FD23.csv",
    "2024-25": "FD24.csv"
}


def get_all_seasons() -> List[str]:
    """Get list of available seasons."""
    return list(SEASON_FILES.keys())


def get_all_teams() -> List[str]:
    """Get list of all unique teams from the data."""
    try:
        # Load most recent season to get current teams
        df = load_season_data("2024-25")
        teams = sorted(set(df['HomeTeam'].tolist() + df['AwayTeam'].tolist()))
        return teams
    except Exception as e:
        logger.warning(f"Could not load teams: {e}")
        return []


def load_season_data(season: str) -> pd.DataFrame:
    """
    Load match data for a specific season.
    
    Args:
        season: Season identifier (e.g., "2024-25")
        
    Returns:
        DataFrame with raw match data
    """
    if season not in SEASON_FILES:
        raise ValueError(f"Invalid season: {season}")
    
    filepath = os.path.join(DATA_DIR, SEASON_FILES[season])
    
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Data file not found: {filepath}")
    
    df = pd.read_csv(filepath)
    df['Date'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')
    df['Season'] = season
    
    logger.info(f"Loaded {len(df)} matches from {season}")
    
    return df


def load_all_seasons() -> pd.DataFrame:
    """Load and combine all available seasons."""
    all_data = []
    
    for season in SEASON_FILES.keys():
        try:
            df = load_season_data(season)
            all_data.append(df)
        except Exception as e:
            logger.warning(f"Could not load {season}: {e}")
    
    if not all_data:
        raise Exception("No data could be loaded")
    
    combined = pd.concat(all_data, ignore_index=True)
    logger.info(f"Loaded {len(combined)} total matches")
    
    return combined


def filter_by_teams(df: pd.DataFrame, teams: List[str]) -> pd.DataFrame:
    """
    Filter matches involving specific teams.
    
    Args:
        df: Match data
        teams: List of team names (empty list = all teams)
        
    Returns:
        Filtered DataFrame
    """
    if not teams:
        return df
    
    mask = df['HomeTeam'].isin(teams) | df['AwayTeam'].isin(teams)
    filtered = df[mask].copy()
    
    logger.info(f"Filtered to {len(filtered)} matches for {teams}")
    
    return filtered


def filter_by_opponent(df: pd.DataFrame, team: str, opponent: str) -> pd.DataFrame:
    """
    Filter matches between two specific teams (head-to-head).
    
    Args:
        df: Match data
        team: First team
        opponent: Second team
        
    Returns:
        Filtered DataFrame with only matches between these teams
    """
    mask = (
        ((df['HomeTeam'] == team) & (df['AwayTeam'] == opponent)) |
        ((df['HomeTeam'] == opponent) & (df['AwayTeam'] == team))
    )
    
    filtered = df[mask].copy()
    logger.info(f"Found {len(filtered)} matches between {team} and {opponent}")
    
    return filtered


def filter_by_date_range(df: pd.DataFrame, start_date: Optional[str] = None, 
                        end_date: Optional[str] = None) -> pd.DataFrame:
    """
    Filter matches within date range.
    
    Args:
        df: Match data
        start_date: Start date (YYYY-MM-DD) or None
        end_date: End date (YYYY-MM-DD) or None
        
    Returns:
        Filtered DataFrame
    """
    if start_date:
        df = df[df['Date'] >= pd.to_datetime(start_date)]
    
    if end_date:
        df = df[df['Date'] <= pd.to_datetime(end_date)]
    
    return df


def get_last_n_matches(df: pd.DataFrame, team: Optional[str] = None, n: int = 5) -> pd.DataFrame:
    """
    Get last N matches for a team (or overall if no team specified).
    
    Args:
        df: Match data (should be sorted by date)
        team: Team name or None for all matches
        n: Number of matches
        
    Returns:
        DataFrame with last N matches
    """
    if team:
        mask = (df['HomeTeam'] == team) | (df['AwayTeam'] == team)
        df = df[mask]
    
    # Sort by date descending and take top N
    result = df.sort_values('Date', ascending=False).head(n)
    
    logger.info(f"Retrieved last {n} matches" + (f" for {team}" if team else ""))
    
    return result