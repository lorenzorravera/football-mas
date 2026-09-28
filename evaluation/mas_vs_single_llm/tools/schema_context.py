"""
schema_context — ONE canonical schema string, injected identically into every prompt
and every condition (spec Phase 1: no condition gets a richer schema).

Rebuilt for the *new* expanded Aiven schema (v4's schema_context.yaml targeted an older,
non-existent schema — see V4_NOTES.md §7).

Design:
  * `build_snapshot()` introspects the live DB (tables/views + columns) once and writes
    `tools/schema_snapshot.json` (committed, so prompts don't need a live DB at call time).
  * Curated, hand-authored content (table purposes, prefix legend, caveats, relationships)
    is merged with the introspected columns by `get_schema_context()`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAPSHOT_PATH = HERE / "schema_snapshot.json"

# Tables to expose, in a sensible reading order (partition children are hidden — query the parent).
TABLE_ORDER = [
    "competitions", "seasons", "teams", "players", "matches",
    "team_season_standings", "team_season_home_away_standings",
    "team_season_stats_for", "team_season_stats_against",
    "player_season_stats", "player_season_splits",
    "player_match_performance", "match_events",
    "player_market_values", "player_transfers", "player_injury_spells",
    "computed_metrics",
    # International national-team dataset (separate domain from the club tables above).
    "intl_tournaments", "intl_teams", "intl_matches",
    "intl_goalscorers", "intl_shootouts",
]
VIEW_ORDER = [
    "vw_match_summary", "vw_team_season_summary", "vw_player_season_summary",
    "vw_player_match_summary", "vw_player_shooting_profile", "vw_player_availability",
]

TABLE_PURPOSE = {
    "competitions": "League master. FIVE leagues: ENG-PL (competition_id=1, league_code 'ENG-PL'), "
                    "ESP-LL, ITA-SA, GER-BL, FRA-L1. For Premier League questions, restrict to ENG-PL.",
    "seasons": "One row per competition-season (season_id PK, competition_id FK); season label is "
               "'YYYY-YYYY'. The SAME label (e.g. '2024-2025') exists once PER LEAGUE — filtering on "
               "season alone spans all five leagues, so ALWAYS also filter competition_id / league_code.",
    "teams": "Team identities (team_id ↔ canonical team_name), covering all five leagues.",
    "players": "Player profiles (stable attributes).",
    "matches": "One row per match (game_id PK). Home/away box-score columns, odds, referee (text), result.",
    "team_season_standings": "Final league table per team-season (tss_*). tss_points ALREADY includes point deductions.",
    "team_season_home_away_standings": "Home/away split of standings per team-season (tshas_*).",
    "team_season_stats_for": "Team-season stats the team produced (tssf_*): possession, shots, xG-less attacking/defensive output, cards.",
    "team_season_stats_against": "Team-season stats opponents produced against this team (tssa_*).",
    "player_season_stats": "Player-season aggregates per club (pss_*): goals, xG, xA, minutes, cards, GK stats.",
    "player_season_splits": "Player-season splits by group_type/group_name (pssp_*), e.g. home/away.",
    "player_match_performance": "Player-by-match performance (pmp_*). PARTITIONED by league+season; keyed on (player_id, game_id, season, league_code).",
    "match_events": "Event-level data (~3M rows). PARTITIONED by league+season; keyed on season+league_code text, linked to matches by game_id.",
    "player_market_values": "Player market-value time series. date_unix is Unix SECONDS.",
    "player_transfers": "Transfer history (from_team/to_team are text names).",
    "player_injury_spells": "Injury/absence spells with matchweek range and games/days missed.",
    "computed_metrics": "Model-output store (JSONB). Currently EMPTY — reserved for the prediction slice.",
    # --- International national-team dataset (Kaggle martj42), last ~10 years ---
    "intl_tournaments": "International competition dimension (tournament_name), e.g. 'FIFA World Cup', 'Friendly', 'UEFA Nations League'.",
    "intl_teams": "National teams (intl_team_id ↔ team_name, e.g. 'Brazil'). SEPARATE from the club `teams` table — do NOT join the two.",
    "intl_matches": "One row per international fixture (intl_match_id PK): match_date, home/away team ids, home_score/away_score, ft_result (H/D/A), tournament, city, host country, neutral flag.",
    "intl_goalscorers": "One row per goal in an international match: scoring_team_id, scorer, minute, own_goal, penalty flags.",
    "intl_shootouts": "One row per international match decided on penalties: winner_team_id, first_shooter_team_id.",
}

VIEW_PURPOSE = {
    "vw_match_summary": "matches joined to readable season/league/home/away team names.",
    "vw_team_season_summary": "team standings + home/away + stats-for + stats-against, one row per team-season (vwtss_*). vwtss_points includes deductions.",
    "vw_player_season_summary": "player-season stats + profile + latest market_value.",
    "vw_player_match_summary": "player-match performance enriched with match metadata + team names.",
    "vw_player_shooting_profile": "event-derived shooting profile (one row per shot).",
    "vw_player_availability": "injury/absence burden per player-season.",
}

COLUMN_PREFIX_LEGEND = """Column-prefix legend (helps disambiguate joined wide tables):
  tss_   = team_season_standings      tshas_ = team_season_home_away_standings
  tssf_  = team_season_stats_for       tssa_  = team_season_stats_against
  pss_   = player_season_stats         pssp_  = player_season_splits
  pmp_   = player_match_performance     vwtss_ = vw_team_season_summary"""

RELATIONSHIPS = """Key relationships:
  competitions(competition_id) ─< seasons(season_id) ─< matches(game_id)
  teams(team_id) appears as matches.home_team_id / matches.away_team_id
  matches(game_id) ─< player_match_performance(game_id), match_events(game_id)
  players(player_id) ─< player_season_stats, player_match_performance, player_market_values,
                        player_transfers, player_injury_spells
  team-season tables key on (team_id, season_id); player_season_stats on (player_id, season_id, team_id)
  match_events / player_match_performance also carry text (season, league_code) — join via seasons.season + competitions.league_code
  International (separate domain): intl_teams(intl_team_id) is home_team_id/away_team_id on intl_matches;
    intl_tournaments(intl_tournament_id) ─< intl_matches; intl_matches(intl_match_id) ─< intl_goalscorers, intl_shootouts.
    intl_teams are NATIONAL teams and are NOT related to the club `teams`/`players` tables."""

CAVEATS = """IMPORTANT caveats (read before writing SQL):
  • Season label format is 'YYYY-YYYY' with a HYPHEN (e.g. '2023-2024'). NOT an underscore.
  • The club dataset covers FIVE leagues (ENG-PL, ESP-LL, ITA-SA, GER-BL, FRA-L1), seasons
    2020-2021 … 2024-2025. This is a PREMIER LEAGUE system: unless a question explicitly names
    another league, scope EVERY query to ENG-PL by joining seasons→competitions and filtering
    competitions.league_code='ENG-PL' (equivalently seasons.competition_id=1). Team-season and
    player-season tables join to seasons(season_id); the partitioned match_events /
    player_match_performance tables also carry a league_code text column ('ENG-PL'). Filtering on
    season alone (without the competition filter) returns all five leagues and is a common error.
  • The latest season is 2024-2025; there is NO 2025-2026 league table data, so "this/current
    season" must be read as 2024-2025. (player_transfers may list later transfer windows — filter
    by season if a question is season-specific.)
  • Point deductions are ALREADY baked into tss_points / vwtss_points (e.g. Everton −8 and
    Nottingham Forest −4 in 2023-2024). Do NOT subtract them again. There is no points_adjustments table.
  • There is NO league_table view, NO match_team_stats table, NO referees table. Use
    team_season_standings / vw_team_season_summary for tables; matches.referee is a TEXT column;
    matches stores home_*/away_* columns (one row per match) with game_id PK, home_score/away_score, ft_result.
  • Prefer IDs over names for joins (team_id, season_id, player_id, game_id); names are for display.
  • match_events (~3M rows) and player_match_performance are large & partitioned — always filter by
    season (+ league_code) and avoid unbounded scans.
  • player_market_values.date_unix is Unix SECONDS (convert with to_timestamp(date_unix)).
  • The intl_* tables hold INTERNATIONAL (national-team) results from the Kaggle martj42 dataset,
    last ~10 years (match_date 2016-07-03 … present). This is a SEPARATE domain: national teams
    (intl_teams) are unrelated to the club teams/players above — never join across the two."""


# --------------------------------------------------------------------------- #
def build_snapshot() -> dict:
    """Introspect the live DB and write tools/schema_snapshot.json. Needs DB access."""
    from tools.run_sql import run_sql  # local import to avoid DB dependency at module import

    snapshot: dict = {"tables": {}, "views": {}}
    for t in TABLE_ORDER:
        r = run_sql(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position",
            params={"t": t}, max_rows=500)
        snapshot["tables"][t] = [{"name": c, "type": d} for c, d in r["rows"]]
    for v in VIEW_ORDER:
        # matviews aren't in information_schema.columns -> LIMIT 0 select
        r = run_sql(f'SELECT * FROM "{v}" WHERE false', max_rows=0)
        snapshot["views"][v] = [{"name": c} for c in r["columns"]]
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))
    return snapshot


def _load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return build_snapshot()
    return json.loads(SNAPSHOT_PATH.read_text())


def get_schema_context(include_columns: bool = True) -> str:
    """Return the single canonical schema string for prompts (all conditions share this)."""
    snap = _load_snapshot()
    L = ["# Premier League Analytics Database (PostgreSQL)",
         "Multi-league club DB (ENG-PL, ESP-LL, ITA-SA, GER-BL, FRA-L1), seasons 2020-2021 … 2024-2025.",
         "This is a PREMIER LEAGUE system — scope every query to ENG-PL "
         "(competitions.league_code='ENG-PL' / seasons.competition_id=1) unless another league is named.", "",
         COLUMN_PREFIX_LEGEND, "", "## Tables", ""]

    for t in TABLE_ORDER:
        L.append(f"### {t}")
        if t in TABLE_PURPOSE:
            L.append(TABLE_PURPOSE[t])
        if include_columns and snap["tables"].get(t):
            cols = ", ".join(f"{c['name']}" for c in snap["tables"][t])
            L.append(f"columns: {cols}")
        L.append("")

    L += ["## Materialized views", ""]
    for v in VIEW_ORDER:
        L.append(f"### {v}")
        if v in VIEW_PURPOSE:
            L.append(VIEW_PURPOSE[v])
        if include_columns and snap["views"].get(v):
            cols = ", ".join(c["name"] for c in snap["views"][v])
            L.append(f"columns: {cols}")
        L.append("")

    L += ["## Relationships", "", RELATIONSHIPS, "", "## Caveats", "", CAVEATS]
    return "\n".join(L)


if __name__ == "__main__":
    snap = build_snapshot()
    n_tab = len(snap["tables"])
    n_view = len(snap["views"])
    ctx = get_schema_context()
    print(f"Snapshot written: {n_tab} tables, {n_view} views -> {SNAPSHOT_PATH}")
    print(f"Schema context length: {len(ctx)} chars\n")
    print(ctx[:1600] + "\n...\n")
    print(ctx[-900:])
