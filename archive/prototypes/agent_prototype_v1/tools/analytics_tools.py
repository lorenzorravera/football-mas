"""
Analytics Tools Module

Pure functions for computing statistics and metrics from raw match data.
No LLM calls, no visualization - just calculations.
"""

import pandas as pd
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# TEAM-LEVEL ANALYTICS
# ============================================================================

def compute_team_stats(matches_df: pd.DataFrame, team: str) -> Dict[str, Any]:
    """
    Calculate comprehensive statistics for a single team.
    
    Args:
        matches_df: Raw match data
        team: Team name
        
    Returns:
        Dictionary with all team statistics
    """
    home = matches_df[matches_df['HomeTeam'] == team].copy()
    away = matches_df[matches_df['AwayTeam'] == team].copy()
    
    # Results
    home_wins = len(home[home['FTR'] == 'H'])
    home_draws = len(home[home['FTR'] == 'D'])
    home_losses = len(home[home['FTR'] == 'A'])
    
    away_wins = len(away[away['FTR'] == 'A'])
    away_draws = len(away[away['FTR'] == 'D'])
    away_losses = len(away[away['FTR'] == 'H'])
    
    total_wins = home_wins + away_wins
    total_draws = home_draws + away_draws
    total_losses = home_losses + away_losses
    total_matches = len(home) + len(away)
    
    # Goals
    goals_scored = int(home['FTHG'].sum() + away['FTAG'].sum())
    goals_conceded = int(home['FTAG'].sum() + away['FTHG'].sum())
    goal_difference = goals_scored - goals_conceded
    
    # Points
    points = (total_wins * 3) + total_draws
    
    # Shots
    shots = int(home['HS'].sum() + away['AS'].sum())
    shots_on_target = int(home['HST'].sum() + away['AST'].sum())
    
    # Clean sheets
    clean_sheets = int(len(home[home['FTAG'] == 0]) + len(away[away['FTHG'] == 0]))
    
    return {
        "team": team,
        "matches_played": total_matches,
        "wins": total_wins,
        "draws": total_draws,
        "losses": total_losses,
        "goals_scored": goals_scored,
        "goals_conceded": goals_conceded,
        "goal_difference": goal_difference,
        "points": points,
        "win_rate": round(total_wins / total_matches, 3) if total_matches > 0 else 0,
        "points_per_game": round(points / total_matches, 2) if total_matches > 0 else 0,
        "goals_per_game": round(goals_scored / total_matches, 2) if total_matches > 0 else 0,
        "clean_sheets": clean_sheets,
        "shots": shots,
        "shots_on_target": shots_on_target,
        "home_record": {"wins": home_wins, "draws": home_draws, "losses": home_losses},
        "away_record": {"wins": away_wins, "draws": away_draws, "losses": away_losses}
    }


def compute_team_form(matches_df: pd.DataFrame, team: str, last_n: int = 5) -> Dict[str, Any]:
    """
    Calculate recent form for a team.
    
    Args:
        matches_df: Raw match data (sorted by date descending)
        team: Team name
        last_n: Number of recent matches
        
    Returns:
        Dictionary with form string and recent results
    """
    team_matches = matches_df[
        (matches_df['HomeTeam'] == team) | (matches_df['AwayTeam'] == team)
    ].head(last_n)
    
    if len(team_matches) == 0:
        return {"form_string": "", "form_points": 0, "recent_results": []}
    
    results = []
    points = 0
    recent_results = []
    
    for _, match in team_matches.iterrows():
        is_home = match['HomeTeam'] == team
        opponent = match['AwayTeam'] if is_home else match['HomeTeam']
        
        if is_home:
            result = 'W' if match['FTR'] == 'H' else 'D' if match['FTR'] == 'D' else 'L'
            team_goals = match['FTHG']
            opp_goals = match['FTAG']
        else:
            result = 'W' if match['FTR'] == 'A' else 'D' if match['FTR'] == 'D' else 'L'
            team_goals = match['FTAG']
            opp_goals = match['FTHG']
        
        results.append(result)
        points += 3 if result == 'W' else 1 if result == 'D' else 0
        
        recent_results.append({
            "opponent": opponent,
            "result": result,
            "score": f"{int(team_goals)}-{int(opp_goals)}",
            "home_away": "H" if is_home else "A",
            "date": match['Date'].strftime('%Y-%m-%d')
        })
    
    return {
        "form_string": ''.join(results),
        "form_points": points,
        "recent_results": recent_results
    }


# ============================================================================
# LEAGUE-LEVEL ANALYTICS
# ============================================================================

def compute_league_table(matches_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate league table with standings.
    
    Args:
        matches_df: Raw match data
        
    Returns:
        DataFrame with league standings
    """
    teams = sorted(set(matches_df['HomeTeam'].tolist() + matches_df['AwayTeam'].tolist()))
    
    table_data = []
    for team in teams:
        stats = compute_team_stats(matches_df, team)
        table_data.append(stats)
    
    table_df = pd.DataFrame(table_data)
    
    # Sort by points, goal difference, goals scored
    table_df = table_df.sort_values(
        by=['points', 'goal_difference', 'goals_scored'],
        ascending=[False, False, False]
    ).reset_index(drop=True)
    
    table_df.insert(0, 'position', range(1, len(table_df) + 1))
    
    logger.info(f"Generated league table with {len(table_df)} teams")
    
    return table_df


def compute_top_performers(matches_df: pd.DataFrame, metric: str, n: int = 10) -> pd.DataFrame:
    """
    Get top N teams by a specific metric.
    
    Args:
        matches_df: Raw match data
        metric: Metric to rank by (points, goals_scored, wins, etc.)
        n: Number of teams to return
        
    Returns:
        DataFrame with top performers
    """
    teams = sorted(set(matches_df['HomeTeam'].tolist() + matches_df['AwayTeam'].tolist()))
    
    rankings = []
    for team in teams:
        stats = compute_team_stats(matches_df, team)
        rankings.append(stats)
    
    df = pd.DataFrame(rankings)
    
    # Sort by metric
    if metric not in df.columns:
        raise ValueError(f"Invalid metric: {metric}")
    
    df = df.sort_values(by=metric, ascending=False).head(n).reset_index(drop=True)
    df.insert(0, 'rank', range(1, len(df) + 1))
    
    logger.info(f"Generated top {n} by {metric}")
    
    return df


# ============================================================================
# COMPARISON ANALYTICS
# ============================================================================

def compare_teams(matches_df: pd.DataFrame, teams: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Compare statistics across multiple teams.
    
    Args:
        matches_df: Raw match data
        teams: List of team names
        
    Returns:
        Dictionary mapping team names to their stats
    """
    comparison = {}
    
    for team in teams:
        comparison[team] = compute_team_stats(matches_df, team)
    
    logger.info(f"Compared {len(teams)} teams")
    
    return comparison


def compute_head_to_head(matches_df: pd.DataFrame, team_a: str, team_b: str) -> Dict[str, Any]:
    """
    Compute head-to-head record between two teams.
    
    Args:
        matches_df: Raw match data (should already be filtered to these teams)
        team_a: First team
        team_b: Second team
        
    Returns:
        Dictionary with head-to-head statistics
    """
    if len(matches_df) == 0:
        return {
            "team_a": team_a,
            "team_b": team_b,
            "total_matches": 0,
            "team_a_wins": 0,
            "team_b_wins": 0,
            "draws": 0
        }
    
    team_a_wins = 0
    team_b_wins = 0
    draws = 0
    team_a_goals = 0
    team_b_goals = 0
    
    for _, match in matches_df.iterrows():
        if match['HomeTeam'] == team_a:
            team_a_goals += match['FTHG']
            team_b_goals += match['FTAG']
            if match['FTR'] == 'H':
                team_a_wins += 1
            elif match['FTR'] == 'A':
                team_b_wins += 1
            else:
                draws += 1
        else:  # team_b is home
            team_b_goals += match['FTHG']
            team_a_goals += match['FTAG']
            if match['FTR'] == 'H':
                team_b_wins += 1
            elif match['FTR'] == 'A':
                team_a_wins += 1
            else:
                draws += 1
    
    return {
        "team_a": team_a,
        "team_b": team_b,
        "total_matches": len(matches_df),
        "team_a_wins": team_a_wins,
        "team_b_wins": team_b_wins,
        "draws": draws,
        "team_a_goals": int(team_a_goals),
        "team_b_goals": int(team_b_goals)
    }