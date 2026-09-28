"""
Analytics Agent Module

Computes statistics and metrics from raw match data. Calls tools from
analytics_tools module based on query type.
"""

from typing import Dict, Any
import logging
from tools.analytics_tools import (
    compute_team_stats,
    compute_team_form,
    compute_league_table,
    compute_top_performers,
    compare_teams,
    compute_head_to_head
)

logger = logging.getLogger(__name__)


def execute(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute analytics based on query type.
    
    Args:
        state: Current MAS state with raw_data and parsed_query
        
    Returns:
        Dictionary with computed analytics results
    """
    raw_data = state["raw_data"]
    parsed_query = state["parsed_query"]
    
    matches_df = raw_data["matches"]
    query_type = parsed_query["query_type"]
    teams = parsed_query.get("teams", [])
    metrics = parsed_query.get("metrics", [])
    
    logger.info(f"Computing analytics for: {query_type}")
    
    try:
        result = {
            "query_type": query_type,
            "team_stats": None,
            "comparison": None,
            "league_table": None,
            "top_performers": None,
            "head_to_head": None,
            "form_analysis": None
        }
        
        # Single team analysis
        if query_type == "single_team" and teams:
            team = teams[0]
            result["team_stats"] = compute_team_stats(matches_df, team)
            result["form_analysis"] = compute_team_form(matches_df, team)
        
        # Team comparison
        elif query_type == "comparison" and teams:
            result["comparison"] = compare_teams(matches_df, teams)
        
        # Head-to-head
        elif query_type == "head_to_head" and teams:
            team_a = teams[0]
            team_b = parsed_query.get("opponent")
            result["head_to_head"] = compute_head_to_head(matches_df, team_a, team_b)
        
        # Rankings / League table
        elif query_type == "ranking":
            if not metrics or "points" in metrics or "table" in metrics:
                result["league_table"] = compute_league_table(matches_df)
            else:
                # Top N by specific metric
                metric = metrics[0]
                n = parsed_query.get("filters", {}).get("top_n", 10)
                result["top_performers"] = compute_top_performers(matches_df, metric, n)
        
        # Trend (treat as single team for now)
        elif query_type == "trend" and teams:
            team = teams[0]
            result["team_stats"] = compute_team_stats(matches_df, team)
            result["form_analysis"] = compute_team_form(matches_df, team, last_n=10)
        
        logger.info(f"Analytics computed successfully")
        
        return result
        
    except Exception as e:
        logger.error(f"Analytics computation failed: {str(e)}")
        raise Exception(f"Analytics Agent failed: {str(e)}")