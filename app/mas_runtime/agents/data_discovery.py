"""
Data Discovery Agent - Identify relevant tables and columns.

Responsibilities:
1. Analyze user query and extracted parameters
2. Identify which tables are needed from the schema
3. Identify which columns are relevant
4. Provide schema context to Data Analyst
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState
from config import call_llm, get_agent_model
from schema_loader import get_schema_context, get_table_names


def data_discovery_agent(state: AgentState) -> AgentState:
    """
    Data Discovery agent: identify relevant tables and columns.

    Args:
        state: Current agent state with user_query and query_parameters

    Returns:
        Updated state with relevant_tables and relevant_columns
    """
    user_query = state["user_query"]
    params = state.get("query_parameters", {})

    # Get schema context
    schema_context = get_schema_context(include_views=True, include_indexes=False)
    available_tables = get_table_names()

    # Build discovery prompt
    prompt = f"""You are a data discovery agent for a Premier League database.

Your job is to identify which tables and columns are needed to answer the user's query.

Available tables: {', '.join(available_tables)}

Schema:
{schema_context}

User Query: "{user_query}"
Extracted Parameters: {params}

Analyze the query and respond in this EXACT format:

TABLES: [comma-separated list of table names needed]
COLUMNS: [JSON object mapping table -> list of columns]
REASONING: [brief explanation of why these tables/columns]

Guidelines:
1. league_table view is pre-built for season standings
2. match_team_stats has per-team stats (2 rows per match)
3. matches has match-level info (teams, date, scores)
4. Always include teams table if team names are mentioned
5. Always include seasons table if filtering by season
6. For aggregations, you'll need match_team_stats

Examples:

Query: "How many points did Arsenal get in 2023_2024?"
TABLES: league_table
COLUMNS: {{"league_table": ["team_name", "season", "points"]}}
REASONING: league_table view has pre-computed season points

Query: "Show me Liverpool's goals scored in each season"
TABLES: match_team_stats, seasons, teams, matches
COLUMNS: {{"match_team_stats": ["team_id", "goals_scored"], "seasons": ["season_id", "season"], "teams": ["team_id", "team_name"], "matches": ["match_id", "season_id"]}}
REASONING: Need to aggregate goals from match_team_stats, join with seasons for season names

Query: "Which referee gave the most red cards?"
TABLES: match_team_stats, referees, matches
COLUMNS: {{"match_team_stats": ["match_id", "red_cards"], "referees": ["referee_id", "referee_name"], "matches": ["match_id", "referee_id"]}}
REASONING: Aggregate red cards from match_team_stats, join with referees

Now analyze the user's query."""

    # Call LLM with data_discovery model
    model = get_agent_model("data_discovery")
    messages = [{"role": "user", "content": prompt}]
    response = call_llm(messages, model=model, temperature=0.0)

    # Parse response
    lines = response.strip().split("\n")
    parsed = {}
    current_key = None
    current_value = []

    for line in lines:
        if ":" in line and line.split(":")[0].strip().upper() in ["TABLES", "COLUMNS", "REASONING"]:
            if current_key:
                parsed[current_key] = "\n".join(current_value)
            key, value = line.split(":", 1)
            current_key = key.strip()
            current_value = [value.strip()]
        elif current_key:
            current_value.append(line)

    if current_key:
        parsed[current_key] = "\n".join(current_value)

    # Extract tables
    tables_str = parsed.get("TABLES", "")
    relevant_tables = [t.strip() for t in tables_str.split(",") if t.strip()]

    # Extract columns
    columns_str = parsed.get("COLUMNS", "{}")
    try:
        import json
        relevant_columns = json.loads(columns_str)
    except:
        # Fallback: assume all columns from relevant tables
        relevant_columns = {table: ["*"] for table in relevant_tables}

    # Update state
    state["relevant_tables"] = relevant_tables
    state["relevant_columns"] = relevant_columns

    return state


if __name__ == "__main__":
    # Test the data discovery agent
    from state import create_initial_state

    test_state = create_initial_state("How many points did Arsenal get in 2023_2024?")
    test_state["is_premier_league_related"] = True
    test_state["intent"] = "data_request"
    test_state["query_parameters"] = {
        "teams": ["Arsenal"],
        "seasons": ["2023_2024"],
        "metrics": ["points"]
    }

    print("Testing Data Discovery Agent...")
    result = data_discovery_agent(test_state)

    print(f"\nRelevant Tables: {result['relevant_tables']}")
    print(f"Relevant Columns: {result['relevant_columns']}")
