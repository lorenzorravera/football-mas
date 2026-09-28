"""
Visualization Tools Module

Pure functions for creating Plotly charts and tables. No LLM calls, no analytics.
"""

import plotly.graph_objects as go
import pandas as pd
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# ============================================================================
# SINGLE TEAM VISUALIZATIONS
# ============================================================================

def create_team_stats_card(team_stats: Dict[str, Any]) -> go.Figure:
    """Create summary table for team statistics."""
    team = team_stats["team"]
    
    metrics = [
        "Matches Played", "Points", "Goal Difference", 
        "Goals Scored", "Goals Conceded", "Win Rate",
        "Points Per Game", "Clean Sheets"
    ]
    
    values = [
        team_stats["matches_played"],
        team_stats["points"],
        team_stats["goal_difference"],
        team_stats["goals_scored"],
        team_stats["goals_conceded"],
        f"{team_stats['win_rate']:.1%}",
        f"{team_stats['points_per_game']:.2f}",
        team_stats["clean_sheets"]
    ]
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=["<b>Metric</b>", "<b>Value</b>"],
            fill_color='paleturquoise',
            align='left',
            font=dict(size=14)
        ),
        cells=dict(
            values=[metrics, values],
            fill_color='lavender',
            align='left',
            font=dict(size=12)
        )
    )])
    
    fig.update_layout(title=f"{team} - Season Statistics", height=400)
    
    return fig


def create_team_stats_bar(team_stats: Dict[str, Any]) -> go.Figure:
    """Create bar chart for team match results."""
    team = team_stats["team"]
    
    fig = go.Figure(data=[
        go.Bar(
            x=["Wins", "Draws", "Losses"],
            y=[team_stats["wins"], team_stats["draws"], team_stats["losses"]],
            marker_color=['green', 'orange', 'red'],
            text=[team_stats["wins"], team_stats["draws"], team_stats["losses"]],
            textposition='auto'
        )
    ])
    
    fig.update_layout(
        title=f"{team} - Match Results",
        xaxis_title="Result",
        yaxis_title="Matches",
        template="plotly_white",
        height=400
    )
    
    return fig


def create_form_chart(form_analysis: Dict[str, Any], team: str) -> go.Figure:
    """Create visualization for recent form."""
    recent_results = form_analysis["recent_results"]
    
    if not recent_results:
        fig = go.Figure()
        fig.update_layout(title=f"{team} - No Recent Matches")
        return fig
    
    matches = [f"vs {r['opponent']}" for r in recent_results]
    results = [r['result'] for r in recent_results]
    scores = [r['score'] for r in recent_results]
    
    color_map = {'W': 'green', 'D': 'orange', 'L': 'red'}
    colors = [color_map[r] for r in results]
    
    fig = go.Figure(data=[
        go.Bar(
            x=matches,
            y=[3 if r == 'W' else 1 if r == 'D' else 0 for r in results],
            marker_color=colors,
            text=[f"{r}<br>{s}" for r, s in zip(results, scores)],
            textposition='auto'
        )
    ])
    
    fig.update_layout(
        title=f"{team} - Recent Form: {form_analysis['form_string']} ({form_analysis['form_points']} pts)",
        xaxis_title="Match",
        yaxis_title="Points",
        yaxis=dict(tickvals=[0, 1, 3], ticktext=['Loss', 'Draw', 'Win']),
        template="plotly_white",
        height=400
    )
    
    return fig


# ============================================================================
# COMPARISON VISUALIZATIONS
# ============================================================================

def create_comparison_bar(comparison: Dict[str, Dict]) -> go.Figure:
    """Create grouped bar chart comparing teams."""
    teams = list(comparison.keys())
    
    wins = [comparison[team]["wins"] for team in teams]
    draws = [comparison[team]["draws"] for team in teams]
    losses = [comparison[team]["losses"] for team in teams]
    
    fig = go.Figure(data=[
        go.Bar(name='Wins', x=teams, y=wins, marker_color='green'),
        go.Bar(name='Draws', x=teams, y=draws, marker_color='orange'),
        go.Bar(name='Losses', x=teams, y=losses, marker_color='red')
    ])
    
    fig.update_layout(
        title="Team Comparison - Match Results",
        xaxis_title="Team",
        yaxis_title="Matches",
        barmode='group',
        template="plotly_white",
        height=500
    )
    
    return fig


def create_comparison_table(comparison: Dict[str, Dict]) -> go.Figure:
    """Create table comparing key metrics."""
    teams = list(comparison.keys())
    
    table_data = {
        "Team": teams,
        "Points": [comparison[team]["points"] for team in teams],
        "GD": [comparison[team]["goal_difference"] for team in teams],
        "Goals": [comparison[team]["goals_scored"] for team in teams],
        "Win Rate": [f"{comparison[team]['win_rate']:.1%}" for team in teams],
        "PPG": [f"{comparison[team]['points_per_game']:.2f}" for team in teams]
    }
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[f"<b>{col}</b>" for col in table_data.keys()],
            fill_color='paleturquoise',
            align='center',
            font=dict(size=13)
        ),
        cells=dict(
            values=list(table_data.values()),
            fill_color='lavender',
            align='center',
            font=dict(size=12)
        )
    )])
    
    fig.update_layout(title="Team Comparison - Key Metrics", height=300)
    
    return fig


# ============================================================================
# LEAGUE TABLE / RANKINGS
# ============================================================================

def create_league_table(league_table_df: pd.DataFrame) -> go.Figure:
    """Create league table visualization."""
    display_cols = [
        "position", "team", "matches_played", "wins", "draws", "losses",
        "goals_scored", "goals_conceded", "goal_difference", "points"
    ]
    
    headers = ["Pos", "Team", "MP", "W", "D", "L", "GF", "GA", "GD", "Pts"]
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[f"<b>{h}</b>" for h in headers],
            fill_color='darkblue',
            align='center',
            font=dict(size=13, color='white')
        ),
        cells=dict(
            values=[league_table_df[col] for col in display_cols],
            fill_color='lavender',
            align='center',
            font=dict(size=11)
        )
    )])
    
    fig.update_layout(title="Premier League Table", height=600)
    
    return fig


def create_top_performers_bar(top_performers_df: pd.DataFrame, metric: str) -> go.Figure:
    """Create bar chart for top performers by metric."""
    fig = go.Figure(data=[
        go.Bar(
            x=top_performers_df["team"],
            y=top_performers_df[metric],
            marker_color='steelblue',
            text=top_performers_df[metric],
            textposition='auto'
        )
    ])
    
    fig.update_layout(
        title=f"Top Performers - {metric.replace('_', ' ').title()}",
        xaxis_title="Team",
        yaxis_title=metric.replace('_', ' ').title(),
        template="plotly_white",
        height=500
    )
    
    return fig


# ============================================================================
# HEAD-TO-HEAD
# ============================================================================

def create_head_to_head_summary(h2h: Dict[str, Any]) -> go.Figure:
    """Create head-to-head summary visualization."""
    team_a = h2h["team_a"]
    team_b = h2h["team_b"]
    
    # Results pie chart
    labels = [f"{team_a} Wins", "Draws", f"{team_b} Wins"]
    values = [h2h["team_a_wins"], h2h["draws"], h2h["team_b_wins"]]
    colors = ['green', 'orange', 'red']
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker_colors=colors,
        hole=0.3
    )])
    
    fig.update_layout(
        title=f"{team_a} vs {team_b} - Head to Head ({h2h['total_matches']} matches)",
        height=400
    )
    
    return fig


def create_head_to_head_table(h2h: Dict[str, Any]) -> go.Figure:
    """Create head-to-head statistics table."""
    team_a = h2h["team_a"]
    team_b = h2h["team_b"]
    
    table_data = {
        "Statistic": ["Matches", "Wins", "Draws", "Losses", "Goals Scored"],
        team_a: [
            h2h["total_matches"],
            h2h["team_a_wins"],
            h2h["draws"],
            h2h["team_b_wins"],
            h2h["team_a_goals"]
        ],
        team_b: [
            h2h["total_matches"],
            h2h["team_b_wins"],
            h2h["draws"],
            h2h["team_a_wins"],
            h2h["team_b_goals"]
        ]
    }
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=[f"<b>{col}</b>" for col in table_data.keys()],
            fill_color='paleturquoise',
            align='center',
            font=dict(size=13)
        ),
        cells=dict(
            values=list(table_data.values()),
            fill_color='lavender',
            align='center',
            font=dict(size=12)
        )
    )])
    
    fig.update_layout(title=f"{team_a} vs {team_b} - Statistics", height=300)
    
    return fig