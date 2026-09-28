"""
Manager Agent - Intent classification and query validation.

Responsibilities:
1. Classify intent: conversational | data_request | prediction_match
   (full_pipeline is pre-set by app.py, never produced by the LLM here)
2. Validate query is Premier League related
3. Extract query parameters (teams, seasons, metrics)
4. Route to appropriate next node
"""

import sys
import json
from datetime import date
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from state import AgentState
from config import call_llm, get_agent_model
from schema_loader import get_season_names


def _get_season_context() -> dict:
    """
    Compute current and adjacent seasons from today's date.

    Premier League seasons start in August, so:
    - Aug-Jul of the following year = one season (e.g. 2025-2026)

    Returns dict with keys: current, last, two_seasons_ago, next, available
    """
    today = date.today()
    year = today.year
    if today.month >= 8:
        current_year = year
    else:
        current_year = year - 1

    def fmt(y: int) -> str:
        return f"{y}-{y + 1}"

    return {
        "current": fmt(current_year),
        "last": fmt(current_year - 1),
        "two_seasons_ago": fmt(current_year - 2),
        "next": fmt(current_year + 1),
        "available": get_season_names(),
    }


def manager_agent(state: AgentState) -> AgentState:
    """
    Manager agent: classify intent and validate query.

    If intent is already set in state (pre-classified by app.py after asking the
    user), skip the LLM classification and return immediately - the param
    extraction and PL-validation have already been done.

    Args:
        state: Current agent state with user_query

    Returns:
        Updated state with intent, is_premier_league_related, query_parameters
    """
    # Skip LLM call if intent was already determined interactively in app.py
    if state.get("intent") in ("data_request", "full_pipeline", "prediction_match"):
        return state

    user_query = state["user_query"]

    # Compute season context from today's date
    seasons = _get_season_context()

    # Build classification prompt
    prompt = f"""You are a routing agent for a Premier League analytics system.

Your job is to:
1. Determine if the query is Premier League related
2. Classify the user's intent
3. Extract relevant parameters, resolving ALL relative time references to concrete season IDs

Today's date: {date.today().isoformat()}
Current season: {seasons['current']}
Last season: {seasons['last']}
Two seasons ago: {seasons['two_seasons_ago']}
Available seasons: {', '.join(seasons['available'])}

User Query: "{user_query}"

Analyze this query and respond in this EXACT format:

IS_PREMIER_LEAGUE: [yes/no]
INTENT: [conversational/data_request/prediction_match/qualitative]
REASON: [brief explanation]
PARAMETERS: [JSON object with extracted entities]

Intent definitions:
- conversational: Greetings, follow-ups, off-topic, or queries not needing data
- data_request: Any RETROSPECTIVE query answered from data already in the database
                (past results, season stats, head-to-heads, league tables, etc.)
- prediction_match: A FORECAST of a future/upcoming outcome. This covers a single MATCH
                    result ("predict X vs Y", "will X beat Y") AND season-level forecasts
                    (final position, top-four/relegation, whether a team will improve or
                    decline next season, next-season points, home/away reliance).
- qualitative: An EXPLANATORY or NARRATIVE question whose answer is prose, not a number or
               table — describing a player's style, the story/context of a season, why a
               narrative unfolded. Answered from written match/season narratives and player
               bios (not the numeric database). Choose this only when a statistic/table would
               NOT answer the question. For qualitative, put any named team in `teams` and any
               named player in `players` so the relevant narrative can be retrieved.

Parameters to extract (if applicable):
- teams: list of team names mentioned
- seasons: list of seasons in YYYY-YYYY format (ALWAYS resolve relative references)
- metrics: stats requested (goals, points, wins, etc.)
- date_range: time period if specified
- players: list of player names mentioned (for player-level predictions)
- destination: a destination TEAM name for a transfer-fit question ("fit at X")
- destination_league: a destination LEAGUE for a cross-league move
  (one of ENG-PL, ESP-LL, ITA-SA, GER-BL, FRA-L1)

CRITICAL - Prediction vs retrospective:
- Future-tense or hypothetical -> prediction_match
    "Will Arsenal beat Chelsea?"
    "Who is going to win the next Liverpool match?"
    "What's the probability of a draw between Man City and Spurs?"
    "Predict Arsenal vs Newcastle"
- Past-tense or factual -> data_request
    "Did Arsenal beat Chelsea last season?"
    "How many points did Liverpool get in 2023-2024?"
    "What was the result of the last Man City vs Spurs match?"
- For prediction_match, ALSO set "prediction_type" in PARAMETERS to ONE of:
    "match_outcome"        single fixture (needs two teams in `teams`)
    "season_class"         next-season class: title/top-four/European/relegation
    "position_movement"    will a team move up/down >=5 places next season
    "turnaround"           over/under-performer decline/recovery; next-season points change
    "home_away_dependency" is a team over-reliant on home form
    "player_value"         best value-for-money / high-risk / undervalued PLAYERS
    "player_decline"       which PLAYER(S) likely to decline next season
    "player_team_impact"   how much one PLAYER changes his team's top-four/relegation odds
    "transfer_fit"         how well a PLAYER fits a destination TEAM's style
    "cross_league_translation"  how a PLAYER's output translates moving to another LEAGUE
    "squad_availability"   how much injuries/absences cost a TEAM in points
    "stakeholder_value"    a club's strategic value (sport+attendance+squad value+development)
    "event_impact"         how an early goal / red card / half-time lead shifts a result
    "explain"             a "why / what factors / how confident" question about a forecast
  For match_outcome put both teams in `teams`. For team-season types put the team in `teams`
  if one is named; leave `teams` empty for league-wide questions. For PLAYER types put the
  player in `players`; for transfer_fit also set `destination` (team); for
  cross_league_translation set `destination_league`. A "why/what factors" question that names
  another prediction → keep that prediction_type and the user query triggers the explanation.

CRITICAL - Season resolution rules (for data_request):
- "this season" / "current season" -> "{seasons['current']}"
- "last season" / "previous season" / "last year" -> "{seasons['last']}"
- "2 seasons ago" / "two seasons ago" -> "{seasons['two_seasons_ago']}"
- A bare 4-digit year like "2024" -> "2024-2025" (starting year)
- A bare 2-digit year like "24" or "24/25" -> "2024-2025" (starting year, century = 2000s)
- If no season is mentioned and the query needs one, use "{seasons['current']}"
- NEVER output "last season", "this season", or any relative reference - always use the YYYY-YYYY format

Examples:

Query: "Hello, how are you?"
IS_PREMIER_LEAGUE: no
INTENT: conversational
REASON: Greeting, not related to football
PARAMETERS: {{}}

Query: "How many points did Arsenal get in 2023-2024?"
IS_PREMIER_LEAGUE: yes
INTENT: data_request
REASON: Asks for specific historical data
PARAMETERS: {{"teams": ["Arsenal"], "seasons": ["2023-2024"], "metrics": ["points"]}}

Query: "Which team scored the most goals last season?"
IS_PREMIER_LEAGUE: yes
INTENT: data_request
REASON: Asks for specific data about last season
PARAMETERS: {{"seasons": ["{seasons['last']}"], "metrics": ["goals"]}}

Query: "Will Arsenal beat Chelsea next weekend?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Forecast question about a future match
PARAMETERS: {{"teams": ["Arsenal", "Chelsea"], "prediction_type": "match_outcome"}}

Query: "Predict Manchester City vs Tottenham"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Direct forecast request
PARAMETERS: {{"teams": ["Manchester City", "Tottenham"], "prediction_type": "match_outcome"}}

Query: "Will Aston Villa finish in the top four next season?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Season-level class forecast for one team
PARAMETERS: {{"teams": ["Aston Villa"], "prediction_type": "season_class"}}

Query: "Who is most likely to be relegated next season?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: League-wide season-class forecast
PARAMETERS: {{"prediction_type": "season_class"}}

Query: "Which teams are most likely to climb the table next season?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: League-wide position-movement forecast
PARAMETERS: {{"prediction_type": "position_movement"}}

Query: "Which players are the best value for money in the Premier League?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Player value-for-money detection
PARAMETERS: {{"prediction_type": "player_value"}}

Query: "How much does Mohamed Salah improve Liverpool's top-four chances?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Player impact on team class
PARAMETERS: {{"players": ["Mohamed Salah"], "prediction_type": "player_team_impact"}}

Query: "How would Florian Wirtz perform if he moved to the Premier League?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: Cross-league performance translation
PARAMETERS: {{"players": ["Florian Wirtz"], "destination_league": "ENG-PL", "prediction_type": "cross_league_translation"}}

Query: "How much does an early goal change the result of a match?"
IS_PREMIER_LEAGUE: yes
INTENT: prediction_match
REASON: In-game event impact
PARAMETERS: {{"prediction_type": "event_impact"}}

Query: "Describe Mohamed Salah's playing style."
IS_PREMIER_LEAGUE: yes
INTENT: qualitative
REASON: Asks for a narrative description, not a statistic
PARAMETERS: {{"players": ["Mohamed Salah"]}}

Query: "What was the story of Arsenal's 2024-2025 season?"
IS_PREMIER_LEAGUE: yes
INTENT: qualitative
REASON: Narrative/explanatory question about a season, answered from prose
PARAMETERS: {{"teams": ["Arsenal"], "seasons": ["2024-2025"]}}

Query: "What's the capital of France?"
IS_PREMIER_LEAGUE: no
INTENT: conversational
REASON: Not related to Premier League
PARAMETERS: {{}}

Now analyze the user's query."""

    # Call LLM with manager model
    model = get_agent_model("manager")
    messages = [{"role": "user", "content": prompt}]
    response = call_llm(messages, model=model, temperature=0.0)

    # Parse response
    lines = response.strip().split("\n")
    parsed = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()

    # Extract fields
    is_pl_related = parsed.get("IS_PREMIER_LEAGUE", "no").lower() == "yes"
    intent = parsed.get("INTENT", "conversational").lower()

    # Ensure intent is valid (prediction_match + qualitative on the allowlist)
    if intent not in ["conversational", "data_request", "prediction_match", "qualitative"]:
        intent = "conversational"

    # Parse parameters
    params_str = parsed.get("PARAMETERS", "{}")
    try:
        params = json.loads(params_str)
    except Exception:
        params = {}

    # Update state
    state["is_premier_league_related"] = is_pl_related
    state["intent"] = intent  # type: ignore
    state["query_parameters"] = params

    # If not PL-related, set error
    if not is_pl_related:
        state["error"] = (
            "I can only answer questions about the Premier League. "
            "Please ask about Premier League teams, matches, or statistics."
        )
        state["error_stage"] = "manager"

    return state


if __name__ == "__main__":
    # Test the manager agent
    from state import create_initial_state

    test_queries = [
        "Hello!",
        "How many points did Arsenal get in 2023-2024?",
        "Show me a chart of Liverpool's goals over time",
        "Will Arsenal beat Chelsea?",
        "Predict Man City vs Tottenham",
        "What's the weather like?",
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}")

        state = create_initial_state(query)
        result = manager_agent(state)

        print(f"PL Related: {result['is_premier_league_related']}")
        print(f"Intent: {result.get('intent', 'N/A')}")
        print(f"Parameters: {result.get('query_parameters', {})}")
        if result.get("error"):
            print(f"Error: {result['error']}")
