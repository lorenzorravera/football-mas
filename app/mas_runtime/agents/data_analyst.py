"""
Data Analyst Agent - Three variants for SQL generation.

PHASE 3: Three Data Analyst Variants
1. FULL CONTROL: Only uses 10 predetermined SQL functions
2. SEMI CONTROL: Can use functions OR generate custom SQL (LLM decides)
3. NO CONTROL: Always generates custom SQL

Variant is selected via function parameter (from Chat Profile in Phase 4).
"""
import re

import sys
from pathlib import Path
import pandas as pd
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from state import AgentState
from config import call_llm, get_agent_model
from schema_loader import get_schema_context, get_season_names
from db.connection import read_sql
FUNCTION_REGISTRY = {}; safe_call_function = lambda f, p: __import__("pandas").DataFrame()


def _generate_clarification_question(user_query: str, reasoning: str, params: dict) -> str:
    """
    Ask the LLM to produce a targeted follow-up question when no function matched.

    Args:
        user_query: The original user question
        reasoning: The LLM's explanation of why no function matched
        params: Parameters already extracted by the manager

    Returns:
        A concise follow-up question string
    """
    available_seasons = ", ".join(get_season_names())

    prompt = f"""You are a Premier League analytics assistant.

A user asked: "{user_query}"

You tried to answer it using available data functions but couldn't, because: {reasoning}
Parameters already extracted: {params}

Ask ONE concise follow-up question to get the missing information needed to answer the query.

Rules:
- Be specific about what is missing (e.g. which season, which team, which metric)
- If a season is missing or ambiguous, list the available ones: {available_seasons}
- Do NOT explain why you couldn't answer — just ask what you need
- Maximum 2 sentences

Example: "Which season are you interested in? Available seasons: 2021_2022, 2022_2023, 2023_2024, 2024_2025, 2025_2026"
"""
    model = get_agent_model("synthesizer")
    return call_llm([{"role": "user", "content": prompt}], model=model, temperature=0.3)


# =============================================================================
# VARIANT 1: FULL CONTROL (Structured)
# =============================================================================

def _full_control_analyst(state: AgentState) -> AgentState:
    """
    Full Control variant: ONLY uses predetermined functions.

    The LLM maps the user query to one of 10 predefined functions.
    No custom SQL generation allowed.
    """
    user_query = state["user_query"]
    params = state.get("query_parameters", {})

    # Build function selection prompt
    functions_desc = """
Available Functions:

1. get_league_standings(season, as_of_date=None)
   - Get league table for a season
   - Example: "What's the league table for 2023_2024?"

2. get_team_season_stats(team_name, season)
   - Comprehensive stats for a team in a season
   - Example: "How did Arsenal perform in 2023_2024?"

3. get_head_to_head(team_a, team_b, season=None)
   - H2H record between two teams
   - Example: "Arsenal vs Man City head to head"

4. get_team_form(team_name, last_n_matches=5, season=None)
   - Recent form for a team
   - Example: "Liverpool's last 5 matches"

5. get_top_scorers(season, top_n=10, home_away="both")
   - Top goal-scoring teams
   - Example: "Top 5 scorers in 2024_2025"

6. get_defensive_rankings(season, metric="goals_conceded", top_n=10)
   - Best defensive teams
   - Example: "Teams with best defense this season"

7. get_match_history(team_name, season, opponent=None, home_away=None, date_from=None, date_to=None)
   - Match listing with filters
   - Example: "All Chelsea home games in 2024_2025"

8. compare_teams(team_a, team_b, season)
   - Side-by-side team comparison
   - Example: "Compare Liverpool and Man City"

9. get_referee_stats(referee_name, season=None)
   - Referee performance stats
   - Example: "M Oliver's card statistics"

10. get_season_aggregates(season)
    - League-wide statistics
    - Example: "Average goals per game this season"
"""

    prompt = f"""You are a data analyst with access to ONLY these 10 predetermined functions.

{functions_desc}

User Query: "{user_query}"
Extracted Parameters: {params}

Your job:
1. Select the BEST function to answer the query
2. Extract the required parameters
3. Return the function call in JSON format

Respond with ONLY this JSON (no explanations):
{{
    "function": "function_name",
    "params": {{
        "param1": "value1",
        "param2": "value2"
    }},
    "reasoning": "why this function"
}}

If NO function can answer the query, respond:
{{
    "function": "none",
    "params": {{}},
    "reasoning": "explanation"
}}

Examples:

Query: "What's the league table for 2023_2024?"
{{
    "function": "get_league_standings",
    "params": {{"season": "2023_2024"}},
    "reasoning": "Direct match to standings function"
}}

Query: "How many points did Arsenal get in 2023_2024?"
{{
    "function": "get_team_season_stats",
    "params": {{"team_name": "Arsenal", "season": "2023_2024"}},
    "reasoning": "Team stats includes points"
}}

Now analyze the user's query."""

    model = get_agent_model("data_analyst")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=0.0)

        # Parse JSON response
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            response_clean = "\n".join(lines[1:-1])

        function_call = json.loads(response_clean)

        function_name = function_call.get("function")
        function_params = function_call.get("params", {})

        if function_name == "none" or function_name not in FUNCTION_REGISTRY:
            reasoning = function_call.get("reasoning", "the query didn't match any available function")
            clarification = _generate_clarification_question(user_query, reasoning, params)
            state["final_response"] = clarification
            state["needs_clarification"] = True
            return state

        # Execute the function (safe_call_function handles alias/param mismatches)
        func = FUNCTION_REGISTRY[function_name]
        data_result = safe_call_function(func, function_params)

        # Create SQL description (for transparency)
        sql_description = f"Function: {function_name}({', '.join(f'{k}={v}' for k, v in function_params.items())})"

        state["sql_query"] = sql_description
        state["data_result"] = data_result

    except Exception as e:
        state["error"] = f"Function execution failed: {str(e)}"
        state["error_stage"] = "data_analyst"
        state["sql_query"] = ""
        state["data_result"] = pd.DataFrame()

    return state


# =============================================================================
# VARIANT 2: SEMI CONTROL (Hybrid)
# =============================================================================

def _semi_control_analyst(state: AgentState) -> AgentState:
    """
    Semi Control variant: Can use functions OR generate custom SQL.

    The LLM first checks if a function matches. If yes, use it.
    If no good match, generate custom SQL instead.
    """
    user_query = state["user_query"]
    params = state.get("query_parameters", {})
    schema = get_schema_context(include_views=True, include_indexes=False)

    # ── Validation hint (injected on retry) ── ← VALIDATION
    validation_hint = state.get("validation_hint", "")
    hint_block = (
        f"\n⚠️ Previous attempt was rejected by the validation agent: {validation_hint}\n"
        "You MUST generate a different approach (different function or different SQL) this time.\n"
        if validation_hint else ""
    )

    # Build decision prompt
    functions_desc = """
Available Functions (use EXACT parameter names):

1. get_league_standings(season, as_of_date=None)
   - Season standings with points adjustments
   - Example: "What's the league table for 2023_2024?"

2. get_team_season_stats(team_name, season)
   - Comprehensive stats for a team in a season
   - Example: "How did Arsenal perform in 2023_2024?"

3. get_head_to_head(team_a, team_b, season=None)
   - H2H record between two teams
   - Example: "Arsenal vs Man City head to head"

4. get_team_form(team_name, last_n_matches=5, season=None)
   - Recent form for a team
   - Example: "Liverpool's last 5 matches"

5. get_top_scorers(season, top_n=10, home_away="both")
   - Top goal-scoring teams
   - Example: "Top 5 scorers in 2024_2025"

6. get_defensive_rankings(season, metric="goals_conceded", top_n=10)
   - Best defensive teams
   - Example: "Teams with best defense this season"

7. get_match_history(team_name, season, opponent=None, home_away=None, date_from=None, date_to=None)
   - Match listing with filters
   - Example: "All Chelsea home games in 2024_2025"

8. compare_teams(team_a, team_b, season)
   - Side-by-side team comparison
   - Example: "Compare Liverpool and Man City in 2023_2024"

9. get_referee_stats(referee_name, season=None)
   - Referee performance stats
   - Example: "M Oliver's card statistics"

10. get_season_aggregates(season)
    - League-wide statistics
    - Example: "Average goals per game in 2024_2025"
"""

    prompt = f"""You are a hybrid data analyst with two options:
{hint_block}
OPTION 1: Use one of these predetermined functions:
{functions_desc}

OPTION 2: Write custom SQL if no function matches well.

Database Schema:
{schema}

User Query: "{user_query}"
Parameters: {params}

Decision Process:
1. Check if ANY function is a GOOD match (>80% confidence)
2. If yes, use the function with the EXACT parameter names shown above
3. If no, write custom SQL instead

Respond in JSON:
{{
    "approach": "function" OR "custom_sql",
    "function_name": "..." (if approach=function),
    "function_params": {{...}} (if approach=function, use exact param names),
    "sql_query": "..." (if approach=custom_sql),
    "reasoning": "why this approach"
}}

Examples:

Query: "What's the league table for 2024_2025?"
{{
    "approach": "function",
    "function_name": "get_league_standings",
    "function_params": {{"season": "2024_2025"}},
    "reasoning": "Perfect match to standings function"
}}

Query: "How many points did Arsenal get in 2023_2024?"
{{
    "approach": "function",
    "function_name": "get_team_season_stats",
    "function_params": {{"team_name": "Arsenal", "season": "2023_2024"}},
    "reasoning": "Team stats includes points"
}}

Query: "Which team had the most corners in games officiated by M Oliver?"
{{
    "approach": "custom_sql",
    "sql_query": "SELECT t.team_name, SUM(mts.corners) as total_corners FROM match_team_stats mts JOIN teams t ON mts.team_id = t.team_id JOIN matches m ON mts.match_id = m.match_id JOIN referees r ON m.referee_id = r.referee_id WHERE r.referee_name = 'M Oliver' GROUP BY t.team_name ORDER BY total_corners DESC LIMIT 1;",
    "reasoning": "Complex query combining referee and corners - no matching function"
}}

Now decide for this query."""

    model = get_agent_model("data_analyst")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=0.0)

        # Parse JSON
        response_clean = response.strip()
        if response_clean.startswith("```"):
            lines = response_clean.split("\n")
            response_clean = "\n".join(lines[1:-1])

        decision = json.loads(response_clean)
        approach = decision.get("approach")

        if approach == "function":
            function_name = decision.get("function_name")
            function_params = decision.get("function_params", {})

            if function_name not in FUNCTION_REGISTRY:
                raise ValueError(f"Unknown function: {function_name}")

            func = FUNCTION_REGISTRY[function_name]
            data_result = safe_call_function(func, function_params)

            sql_description = f"Function: {function_name}({', '.join(f'{k}={v}' for k, v in function_params.items())})"
            state["sql_query"] = sql_description

        else:  # custom_sql
            sql_query = decision.get("sql_query", "")

            if not sql_query:
                raise ValueError("No SQL query provided")

            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
            data_result = read_sql(sql_query)
            state["sql_query"] = sql_query

        state["data_result"] = data_result

    except Exception as e:
        state["error"] = f"Hybrid analysis failed: {str(e)}"
        state["error_stage"] = "data_analyst"
        state["sql_query"] = ""
        state["data_result"] = pd.DataFrame()

    return state


# =============================================================================
# VARIANT 3: NO CONTROL (Agentic)
# =============================================================================

def _extract_sql(response: str) -> str:
    """Pull a clean SQL statement out of an LLM response that may contain prose
    and/or markdown code fences. Falls back to the stripped response."""
    text = response.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = m.group(1).strip() if m else text
    km = re.search(r"\b(WITH|SELECT)\b", candidate, re.IGNORECASE)
    if km:
        candidate = candidate[km.start():]
    return candidate.replace("```sql", "").replace("```", "").strip()


def _no_control_analyst(state: AgentState) -> AgentState:
    """
    No Control variant: Always generates custom SQL.

    The LLM writes SQL from scratch. Can read skills.md for guidance
    but doesn't execute predefined functions.
    """
    user_query = state["user_query"]
    params = state.get("query_parameters", {})
    schema = get_schema_context(include_views=True, include_indexes=False)

    # Load skills.md for reference
    skills_path = Path(__file__).parent.parent / "agent_tools" / "skills.md"
    with open(skills_path, "r") as f:
        skills_content = f.read()

    # ── Memory warnings ─────────────────────────────────────────────── ← MEMORY
    memory_warnings = state.get("memory_warnings", [])
    warnings_block = ""
    if memory_warnings:
        lines = "\n".join(
            f"  - [{w['stage']}] {w['error_message']}  (bad SQL: {w['bad_sql'][:100]})"
            for w in memory_warnings
        )
        warnings_block = f"\n⚠️  Past failures on similar queries — avoid these patterns:\n{lines}\n"

    # ── Validation hint (injected on retry) ── ← VALIDATION
    validation_hint = state.get("validation_hint", "")
    hint_block = (
        f"\n⚠️ Previous attempt was rejected by the validation agent: {validation_hint}\n"
        "You MUST write a different SQL query this time.\n"
        if validation_hint else ""
    )

    # Build SQL generation prompt
    prompt = f"""You are an expert SQL analyst for a Premier League PostgreSQL database.
{warnings_block}{hint_block}

Database Schema:
{schema}

Live-schema quick reference. 'league_table' and 'match_team_stats' do NOT exist. EVERY query below MUST join competitions and filter league_code = 'ENG-PL' (the DB is multi-league):
- Standings / relegation / top-four: team_season_standings (tss_rank, tss_team, tss_points, tss_goal_difference, tss_wins, tss_draws, tss_losses, tss_goals_for, tss_goals_against). Relegated = tss_rank IN (18,19,20); top four = tss_rank <= 4.
- Home/away splits: team_season_home_away_standings (tshas_home_points, tshas_home_wins, tshas_away_wins, tshas_home_goals, etc.). Join to seasons+competitions for the league filter.
- A team's top scorer: tss_top_scorer_name, tss_top_scorer_goals.
- Player goals/assists/minutes/cards: player_season_stats (pss_*) JOIN players p ON pss.player_id = p.player_id.
- Cards/fouls at team level live in the wide 'matches' table (home_yellow_cards/away_yellow_cards/home_red_cards/away_red_cards) and must be SUMMED across both home and away fixtures per team.
- Referee match counts: matches.referee (text), counted over PL matches only.
- Canonical season-scoping pattern (use for ALL of the above):
    JOIN seasons s ON <table>.season_id = s.season_id
    JOIN competitions c ON s.competition_id = c.competition_id
    WHERE c.league_code = 'ENG-PL' AND s.season = '2024-2025'

User Query: "{user_query}"
Extracted Parameters: {params}

Generate a SQL query to answer this question.

CRITICAL RULES:
1. ⚠️ CRITICAL — THE DB IS MULTI-LEAGUE. The season label (e.g. '2024-2025') is NOT unique to the Premier League; La Liga, Serie A etc. all have a '2024-2025' season. You MUST ALWAYS restrict to the Premier League, or you will get foreign teams (Real Madrid, Inter, Getafe).
   The ONLY safe way to scope a season is to join through competitions and filter league_code = 'ENG-PL':
     JOIN seasons s ON <table>.season_id = s.season_id
     JOIN competitions c ON s.competition_id = c.competition_id
     WHERE c.league_code = 'ENG-PL' AND s.season = '2024-2025'
   NEVER filter on a season label alone (e.g. WHERE tss_season = '2024-2025' is WRONG — it spans every league).
1. Use ONLY tables/columns from the schema above
2. Team names must match EXACTLY (e.g., "Man City" not "Manchester City")
3. Season format: "YYYY-YYYY" (e.g., "2023-2024") — HYPHEN, matching seasons.season in the live DB
4. ALWAYS use the season values from Extracted Parameters — do NOT re-interpret season
   references from the raw query text. The Extracted Parameters have already resolved
   shorthand like "23 season" or "last season" to the correct YYYY-YYYY identifier.
   Example: if params contains {{"seasons": ["2023-2024"]}}, use '2023-2024' in the SQL,
   NOT '2022-2023' even if the user wrote "23 season".
5. In this database the STARTING year identifies the season:
   "23 season" = 2023-2024, "24 season" = 2024-2025
6. Final league table = team_season_standings (tss_* columns). tss_points ALREADY includes point deductions. Filter by tss_season = '2023-2024'. There is NO 'league_table' view.
7. The 'matches' table is WIDE (one row per game): home_team_id/away_team_id, home_score/away_score, ft_result, referee (text). There is NO 'match_team_stats' table.
8. Return ONLY the SQL query, no explanations

Example:
Query: "Full 2023-2024 table"
SQL: SELECT tss_rank, tss_team, tss_points, tss_goal_difference FROM team_season_standings WHERE tss_season = '2023-2024' ORDER BY tss_rank;

Now generate SQL for the user's query.
Return ONLY the SQL, nothing else."""

    model = get_agent_model("data_analyst")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=0.0)

        # Extract SQL robustly: model may prepend prose ("Looking at the schema...")
        # and/or wrap the query in a ```sql fence.
        sql_query = _extract_sql(response)

        # Execute SQL
        data_result = read_sql(sql_query)

        state["sql_query"] = sql_query
        state["data_result"] = data_result

    except Exception as e:
        state["error"] = f"SQL generation/execution failed: {str(e)}"
        state["error_stage"] = "data_analyst"
        state["sql_query"] = ""
        state["data_result"] = pd.DataFrame()

    return state


# =============================================================================
# MAIN DATA ANALYST AGENT
# =============================================================================

def data_analyst_agent(
    state: AgentState,
    variant: str = "semi_control"
) -> AgentState:
    """
    Data Analyst agent with three variants + SQL cache acceleration + validation retry.

    Validation is handled internally (not as a graph node) due to LangGraph
    v1.0.10 DataFrame serialization constraints. Retries up to MAX_RETRIES times
    if the result is empty, injecting a hint into the prompt each time.

    Args:
        state:   Current agent state (memory fields already populated)
        variant: "full_control", "semi_control", or "no_control"

    Returns:
        Updated state with sql_query, data_result, validation_passed
    """
    from agents.validation_agent import validate_result
    MAX_RETRIES = 2

    # ── SQL cache fast-path ── ← MEMORY
    cached_sql = state.get("cached_sql")
    if cached_sql and not cached_sql.startswith("Function:"):
        try:
            data_result = read_sql(cached_sql)
            if not data_result.empty:
                passed, hint = validate_result(state["user_query"], cached_sql, data_result)
                if passed:
                    state["sql_query"]        = cached_sql
                    state["data_result"]      = data_result
                    state["sql_cache_hit"]    = True
                    state["validation_passed"] = True
                    state["validation_hint"]   = ""
                    return state
        except Exception:
            pass
        state["sql_cache_hit"] = False

    # ── Variant dispatch with retry loop ── ← VALIDATION
    state["validation_hint"] = ""
    for attempt in range(MAX_RETRIES + 1):
        if variant == "full_control":
            state = _full_control_analyst(state)
        elif variant == "semi_control":
            state = _semi_control_analyst(state)
        elif variant == "no_control":
            state = _no_control_analyst(state)
        else:
            state["error"] = f"Unknown variant: {variant}"
            state["error_stage"] = "data_analyst"
            return state

        # Stop immediately on hard errors
        if state.get("error"):
            return state

        # Validate result
        passed, hint = validate_result(
            state["user_query"],
            state.get("sql_query", ""),
            state.get("data_result"),
        )

        state["validation_passed"]  = passed
        state["validation_retries"] = attempt
        state["validation_hint"]    = hint

        if passed:
            return state

        # On retry: clear stale data so variant regenerates fresh SQL
        if attempt < MAX_RETRIES:
            state["data_result"]  = None
            state["sql_query"]    = ""
            state["sql_cache_hit"] = False
            state["cached_sql"]    = None

    return state


if __name__ == "__main__":
    # Test all three variants
    from state import create_initial_state

    test_query = "What were Arsenal's points in 2023_2024?"

    print("Testing Data Analyst Variants\n")
    print("="*60)

    for variant in ["full_control", "semi_control", "no_control"]:
        print(f"\n{variant.upper().replace('_', ' ')}:")
        print("-"*60)

        state = create_initial_state(test_query)
        state["is_premier_league_related"] = True
        state["intent"] = "data_request"
        state["query_parameters"] = {"teams": ["Arsenal"], "seasons": ["2023_2024"]}
        state["relevant_tables"] = ["league_table"]

        result = data_analyst_agent(state, variant=variant)

        print(f"SQL/Function: {result.get('sql_query', 'N/A')}")
        if result.get("error"):
            print(f"Error: {result['error']}")
        else:
            print(f"Data shape: {result['data_result'].shape}")
            print(result['data_result'].head())
        print()