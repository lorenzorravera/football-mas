"""
Visualizer Agent Module

Creates visualizations based on analytics results. Calls tools from viz_tools
module based on query type.
"""

from typing import Dict, Any, List
import plotly.graph_objects as go
import logging
from tools.viz_tools import (
    create_team_stats_card,
    create_team_stats_bar,
    create_form_chart,
    create_comparison_bar,
    create_comparison_table,
    create_league_table,
    create_top_performers_bar,
    create_head_to_head_summary,
    create_head_to_head_table
)

logger = logging.getLogger(__name__)


def execute(state: Dict[str, Any]) -> List[go.Figure]:
    """
    Generate visualizations based on analytics results.
    
    Args:
        state: Current MAS state with analytics_results
        
    Returns:
        List of Plotly Figure objects
    """
    analytics = state["analytics_results"]
    query_type = analytics["query_type"]
    
    logger.info(f"Creating visualizations for: {query_type}")
    
    try:
        figures = []
        
        # Single team
        if query_type == "single_team":
            if analytics["team_stats"]:
                figures.append(create_team_stats_card(analytics["team_stats"]))
                figures.append(create_team_stats_bar(analytics["team_stats"]))
            
            if analytics["form_analysis"]:
                team = analytics["team_stats"]["team"]
                figures.append(create_form_chart(analytics["form_analysis"], team))
        
        # Team comparison
        elif query_type == "comparison":
            if analytics["comparison"]:
                figures.append(create_comparison_table(analytics["comparison"]))
                figures.append(create_comparison_bar(analytics["comparison"]))
        
        # Head-to-head
        elif query_type == "head_to_head":
            if analytics["head_to_head"]:
                figures.append(create_head_to_head_summary(analytics["head_to_head"]))
                figures.append(create_head_to_head_table(analytics["head_to_head"]))
        
        # Rankings / League table
        elif query_type == "ranking":
            if analytics["league_table"] is not None:
                figures.append(create_league_table(analytics["league_table"]))
            
            if analytics["top_performers"] is not None:
                # Extract metric from top_performers dataframe columns
                metric_cols = [col for col in analytics["top_performers"].columns 
                             if col not in ['rank', 'team', 'matches_played']]
                if metric_cols:
                    metric = metric_cols[0]
                    figures.append(create_top_performers_bar(analytics["top_performers"], metric))
        
        # Trend
        elif query_type == "trend":
            if analytics["team_stats"]:
                figures.append(create_team_stats_card(analytics["team_stats"]))
            
            if analytics["form_analysis"]:
                team = analytics["team_stats"]["team"]
                figures.append(create_form_chart(analytics["form_analysis"], team))
        
        # Fallback if no visualizations
        if not figures:
            fig = go.Figure()
            fig.update_layout(
                title="No visualizations available",
                annotations=[dict(
                    text="Unable to generate visualizations from available data",
                    showarrow=False,
                    font=dict(size=14)
                )]
            )
            figures.append(fig)
        
        logger.info(f"Created {len(figures)} visualizations")
        
        return figures
        
    except Exception as e:
        logger.error(f"Visualization failed: {str(e)}")
        raise Exception(f"Visualizer Agent failed: {str(e)}")