import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "till" / "agent_v5"))

from tools.schema_context import get_schema_context as _till_get_schema

def get_schema_context(include_views=True, include_indexes=False):
    return _till_get_schema()

def get_season_names():
    import os, psycopg2
    conn = psycopg2.connect(os.environ['DATABASE_URI'])
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT season FROM seasons WHERE competition_id=1 ORDER BY season")
    return [r[0] for r in cur.fetchall()]

def get_table_info(table_name):
    return {}

def load_schema():
    return {}

def get_table_names():
    return [
        "competitions", "seasons", "teams", "players", "matches",
        "team_season_standings", "team_season_home_away_standings",
        "team_season_stats_for", "team_season_stats_against",
        "player_season_stats", "player_season_splits",
        "player_match_performance", "player_injury_spells",
        "player_market_values", "player_transfers", "match_events",
    ]
