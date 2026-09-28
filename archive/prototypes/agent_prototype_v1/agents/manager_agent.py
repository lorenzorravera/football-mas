"""
Manager Agent Module

Parses user queries and extracts structured intent. The LangGraph workflow
handles all orchestration and routing between agents.
"""

from agents import call_llm, parse_llm_json
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a Premier League analytics query parser.

Available seasons: {seasons}
Available teams: {teams}

Query types:
- "single_team": Analysis of one team
- "comparison": Compare 2+ teams
- "head_to_head": Direct matchup between 2 teams  
- "ranking": League table or top N teams
- "trend": Performance over time

Available metrics: goals, shots, wins, losses, draws, points, goal_difference, 
shots_on_target, corners, fouls, cards, clean_sheets, win_rate, form, attendance

Respond with ONLY valid JSON in this format:
{{
    "query_type": "single_team" | "comparison" | "head_to_head" | "ranking" | "trend",
    "teams": ["Team1", "Team2"],
    "opponent": "Team" or null,
    "season": "2024-25" | "all",
    "date_range": {{
        "type": "full_season" | "last_n_games" | "custom",
        "n_games": 5 or null,
        "start_date": "YYYY-MM-DD" or null,
        "end_date": "YYYY-MM-DD" or null
    }},
    "metrics": ["metric1", "metric2"],
    "visualization_hint": "table" | "bar" | "line" | "comparison"
}}

Match team names exactly as they appear in the available teams list. Use null for unspecified parameters.

Examples:
- "Show Arsenal goals this season" → {{"query_type": "single_team", "teams": ["Arsenal"], "metrics": ["goals"], "season": "2024-25"}}
- "Compare Liverpool and Man City" → {{"query_type": "comparison", "teams": ["Liverpool", "Manchester City"], "season": "2024-25"}}
- "Top 5 scorers" → {{"query_type": "ranking", "teams": [], "metrics": ["goals"]}}
"""


def execute(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse user query into structured intent.
    
    Dynamically loads available teams and seasons from the data to ensure
    the LLM has accurate information about what data is available.
    
    Args:
        state: Current MAS state containing user_query
        
    Returns:
        Dictionary with parsed query intent
        
    Raises:
        Exception: If query parsing fails
    """
    user_query = state["user_query"]
    
    logger.info(f"Parsing query: {user_query}")
    
    try:
        # Import here to avoid circular dependencies
        from tools.data_tools import get_all_teams, get_all_seasons
        
        # Dynamically load available data
        teams = get_all_teams()
        seasons = get_all_seasons()
        
        # Format prompt with actual data
        formatted_prompt = SYSTEM_PROMPT.format(
            seasons=", ".join(seasons),
            teams=", ".join(teams)
        )
        
        response = call_llm(
            messages=[
                {"role": "system", "content": formatted_prompt},
                {"role": "user", "content": f"Parse this query: \"{user_query}\""}
            ],
            agent_name="manager_agent",
            temperature=0.2
        )
        
        intent = parse_llm_json(response)
        
        # Validate required fields
        required_fields = ["query_type", "teams", "season", "metrics"]
        missing = [f for f in required_fields if f not in intent]
        
        if missing:
            raise ValueError(f"Parsed intent missing required fields: {missing}")
        
        logger.info(f"Successfully parsed: {intent['query_type']} - Teams: {intent['teams']}")
        
        return intent
        
    except Exception as e:
        logger.error(f"Failed to parse query: {str(e)}")
        raise Exception(f"Manager Agent could not parse query: {str(e)}")