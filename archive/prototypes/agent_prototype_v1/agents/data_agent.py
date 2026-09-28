"""
Data Agent Module

Fetches raw match data based on parsed query. Calls tools from data_tools
module but performs no analytics or aggregations.
"""

from typing import Dict, Any
import logging
from tools.data_tools import (
    load_season_data,
    load_all_seasons,
    filter_by_teams,
    filter_by_opponent,
    filter_by_date_range,
    get_last_n_matches
)

logger = logging.getLogger(__name__)


def execute(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch raw match data based on parsed query.
    
    Args:
        state: Current MAS state with parsed_query from Manager Agent
        
    Returns:
        Dictionary with:
        {
            "matches": DataFrame with raw match data,
            "metadata": dict with data summary
        }
    """
    parsed_query = state["parsed_query"]
    
    teams = parsed_query.get("teams", [])
    opponent = parsed_query.get("opponent")
    season = parsed_query.get("season", "2024-25")
    date_range = parsed_query.get("date_range", {})
    
    logger.info(f"Fetching data: season={season}, teams={teams}")
    
    try:
        # Load data
        if season == "all":
            matches_df = load_all_seasons()
        else:
            matches_df = load_season_data(season)
        
        # Apply filters
        if opponent:
            # Head-to-head query
            matches_df = filter_by_opponent(matches_df, teams[0] if teams else None, opponent)
        elif teams:
            # Specific teams
            matches_df = filter_by_teams(matches_df, teams)
        
        # Date filtering
        date_type = date_range.get("type", "full_season")
        
        if date_type == "last_n_games":
            n_games = date_range.get("n_games", 5)
            team = teams[0] if teams else None
            matches_df = get_last_n_matches(matches_df, team, n_games)
        elif date_type == "custom":
            start_date = date_range.get("start_date")
            end_date = date_range.get("end_date")
            matches_df = filter_by_date_range(matches_df, start_date, end_date)
        
        # Sort by date
        matches_df = matches_df.sort_values('Date', ascending=False).reset_index(drop=True)
        
        # Create metadata
        metadata = {
            "total_matches": len(matches_df),
            "seasons": sorted(matches_df['Season'].unique().tolist()) if 'Season' in matches_df.columns else [season],
            "teams": sorted(set(matches_df['HomeTeam'].tolist() + matches_df['AwayTeam'].tolist())),
            "date_range": {
                "earliest": matches_df['Date'].min().strftime('%Y-%m-%d') if len(matches_df) > 0 else None,
                "latest": matches_df['Date'].max().strftime('%Y-%m-%d') if len(matches_df) > 0 else None
            }
        }
        
        logger.info(f"Fetched {len(matches_df)} matches")
        
        return {
            "matches": matches_df,
            "metadata": metadata
        }
        
    except Exception as e:
        logger.error(f"Data fetch failed: {str(e)}")
        raise Exception(f"Data Agent failed: {str(e)}")