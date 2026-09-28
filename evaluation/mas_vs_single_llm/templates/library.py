"""
templates/library.py — purpose-built parameterized SQL templates (Phase 3).

These are the `use_template(name, params)` tools the CONTROLLED and SEMI-CONTROLLED SQL
agents call (Phase 4). They are written to look like what a sensible analytics engineer would
build for common Premier League questions — NOT strawmen. Each documents its intent.

Coverage (Phase 3) is decided by running these templates and matching their output against the
frozen golden ground truth — never by what an agent does at runtime.

Conventions (same as the golden set):
  * canonical team names via a `teams` join; hyphenated seasons; deductions already in tss_points.
  * metric/column names come ONLY from per-template whitelists (never free-form) so the generated
    SQL is injection-safe; season/team are passed as bound params.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Template:
    name: str
    intent: str
    entity_params: list[str]                 # which of season/team/team_a/team_b it needs
    build: Callable[[dict], tuple[str, dict]]  # params -> (sql, bound_params)
    metrics: dict[str, str] = field(default_factory=dict)  # metric label -> column (optional)
    default_top_n: int = 50


# --------------------------------------------------------------------------- #
# Builders. Each returns (sql, bound_params). `p` carries season/team/metric_col/top_n.
# --------------------------------------------------------------------------- #
def _league_table(p):
    return (
        "SELECT st.tss_rank, t.team_name, st.tss_wins, st.tss_draws, st.tss_losses, "
        "st.tss_goals_for, st.tss_goals_against, st.tss_goal_difference, st.tss_points "
        "FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id "
        "JOIN seasons s ON s.season_id=st.season_id WHERE s.season=:season ORDER BY st.tss_rank",
        {"season": p["season"]},
    )


def _team_season_summary(p):
    return (
        "SELECT t.team_name, v.vwtss_rank, v.vwtss_points, v.vwtss_goals_for, v.vwtss_goals_against, "
        "v.vwtss_goal_difference, v.vwtss_home_points, v.vwtss_away_points, v.vwtss_home_goals_for, "
        "v.vwtss_away_goals_for, v.vwtss_possession_percentage_for "
        "FROM vw_team_season_summary v JOIN teams t ON t.team_id=v.vwtss_team_id "
        "WHERE t.team_name=:team AND v.vwtss_season=:season",
        {"team": p["team"], "season": p["season"]},
    )


def _home_away_table(p):
    col = p["metric_col"]
    return (
        f"SELECT t.team_name, ha.{col} AS metric FROM team_season_home_away_standings ha "
        "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
        f"WHERE s.season=:season ORDER BY ha.{col} DESC, t.team_name LIMIT {int(p['top_n'])}",
        {"season": p["season"]},
    )


def _player_season_leaders(p):
    col = p["metric_col"]
    return (
        f"SELECT p.player_name, SUM(pss.{col}) AS metric FROM player_season_stats pss "
        "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
        f"WHERE s.season=:season GROUP BY p.player_id, p.player_name "
        f"HAVING SUM(pss.{col}) IS NOT NULL ORDER BY metric DESC, p.player_name LIMIT {int(p['top_n'])}",
        {"season": p["season"]},
    )


def _player_team_leaders(p):
    col = p["metric_col"]
    return (
        f"SELECT p.player_name, SUM(pss.{col}) AS metric FROM player_season_stats pss "
        "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
        "JOIN teams t ON t.team_id=pss.team_id WHERE s.season=:season AND t.team_name=:team "
        f"GROUP BY p.player_id, p.player_name ORDER BY metric DESC, p.player_name LIMIT {int(p['top_n'])}",
        {"season": p["season"], "team": p["team"]},
    )


def _team_stat_leaders(p):
    col = p["metric_col"]
    return (
        f"SELECT t.team_name, sf.{col} AS metric FROM team_season_stats_for sf "
        "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
        f"WHERE s.season=:season ORDER BY sf.{col} DESC, t.team_name LIMIT {int(p['top_n'])}",
        {"season": p["season"]},
    )


def _head_to_head(p):
    return (
        "SELECT m.match_date, ht.team_name AS home, at.team_name AS away, m.home_score, m.away_score, m.ft_result "
        "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
        "JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id "
        "WHERE s.season=:season AND ((ht.team_name=:team_a AND at.team_name=:team_b) "
        "OR (ht.team_name=:team_b AND at.team_name=:team_a)) ORDER BY m.match_date",
        {"season": p["season"], "team_a": p["team_a"], "team_b": p["team_b"]},
    )


def _match_results(p):
    # biggest home wins by margin
    return (
        "SELECT ht.team_name AS home_team, at.team_name AS away_team, m.home_score, m.away_score "
        "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
        "JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id "
        f"WHERE s.season=:season ORDER BY (m.home_score-m.away_score) DESC, m.home_score DESC LIMIT {int(p['top_n'])}",
        {"season": p["season"]},
    )


def _market_value_leaders(p):
    return (
        "SELECT p.player_name, mv.market_value FROM player_market_values mv "
        "JOIN players p ON p.player_id=mv.player_id "
        "WHERE (mv.player_id, mv.date_unix) IN (SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) "
        f"ORDER BY mv.market_value DESC, p.player_name LIMIT {int(p['top_n'])}",
        {},
    )


def _market_value_team_leaders(p):
    return (
        "SELECT p.player_name, mv.market_value FROM player_market_values mv "
        "JOIN players p ON p.player_id=mv.player_id "
        "JOIN player_season_stats pss ON pss.player_id=mv.player_id JOIN teams t ON t.team_id=pss.team_id "
        "WHERE t.team_name=:team AND (mv.player_id, mv.date_unix) IN "
        "(SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) "
        f"GROUP BY p.player_name, mv.market_value ORDER BY mv.market_value DESC, p.player_name LIMIT {int(p['top_n'])}",
        {"team": p["team"]},
    )


def _player_match_leaders(p):
    col = p["metric_col"]
    return (
        f"SELECT p.player_name, pmp.game_id, pmp.{col} AS metric FROM player_match_performance pmp "
        "JOIN players p ON p.player_id=pmp.player_id "
        f"WHERE pmp.season=:season AND pmp.league_code='ENG-PL' "
        f"ORDER BY pmp.{col} DESC, p.player_name LIMIT {int(p['top_n'])}",
        {"season": p["season"]},
    )


def _transfer_leaders(p):
    season_clause = "AND tr.season=:season " if p.get("season") else ""
    bound = {"season": p["season"]} if p.get("season") else {}
    return (
        "SELECT p.player_name, tr.from_team, tr.to_team, tr.season, tr.transfer_fee "
        "FROM player_transfers tr JOIN players p ON p.player_id=tr.player_id "
        "WHERE tr.to_team IN (SELECT team_name FROM teams) AND tr.transfer_fee IS NOT NULL "
        f"{season_clause}ORDER BY tr.transfer_fee DESC, p.player_name LIMIT {int(p['top_n'])}",
        bound,
    )


TEMPLATES: dict[str, Template] = {
    "league_table": Template(
        "league_table", "Full final league table for a season (rank, record, goals, points).",
        ["season"], _league_table),
    "team_season_summary": Template(
        "team_season_summary", "One team's season summary incl. home/away points & goals, possession.",
        ["team", "season"], _team_season_summary),
    "home_away_table": Template(
        "home_away_table", "Teams ranked by a home/away split metric for a season.",
        ["season"], _home_away_table,
        metrics={"home_points": "tshas_home_points", "away_points": "tshas_away_points",
                 "home_wins": "tshas_home_wins", "away_wins": "tshas_away_wins",
                 "home_goals_for": "tshas_home_goals_for", "away_goals_for": "tshas_away_goals_for"}),
    "player_season_leaders": Template(
        "player_season_leaders", "Top players by a season stat (goals, assists, minutes, cards, shots).",
        ["season"], _player_season_leaders,
        metrics={"goals": "goals_pss", "assists": "assists_pss", "minutes": "minutes_pss",
                 "yellow_cards": "yellow_cards_pss", "red_cards": "red_cards_pss", "shots": "shots_pss"}),
    "player_team_leaders": Template(
        "player_team_leaders", "Top players at a specific club by a season stat.",
        ["team", "season"], _player_team_leaders,
        metrics={"goals": "goals_pss", "assists": "assists_pss", "minutes": "minutes_pss"}),
    "team_stat_leaders": Template(
        "team_stat_leaders", "Teams ranked by a team-season stat (cards, goals, shots, possession).",
        ["season"], _team_stat_leaders,
        metrics={"yellow_cards": "tssf_yellow_cards", "red_cards": "tssf_red_cards",
                 "goals": "tssf_goals", "shots": "tssf_shots", "possession": "tssf_possession_percentage"}),
    "head_to_head": Template(
        "head_to_head", "All matches between two teams in a season.",
        ["team_a", "team_b", "season"], _head_to_head),
    "match_results": Template(
        "match_results", "Matches in a season ordered by home win margin (biggest wins).",
        ["season"], _match_results),
    "market_value_leaders": Template(
        "market_value_leaders", "Players ranked by latest market value.",
        [], _market_value_leaders),
    "market_value_team_leaders": Template(
        "market_value_team_leaders", "Players at a club ranked by latest market value.",
        ["team"], _market_value_team_leaders),
    "player_match_leaders": Template(
        "player_match_leaders", "Top single-match player performances in a season (e.g. most goals in a game).",
        ["season"], _player_match_leaders,
        metrics={"match_goals": "match_goals", "match_assists": "match_assists"}),
    "transfer_leaders": Template(
        "transfer_leaders", "Largest incoming transfer fees to Premier League clubs (optionally per season).",
        [], _transfer_leaders),
}


if __name__ == "__main__":
    from tools.run_sql import run_sql
    print(f"{len(TEMPLATES)} templates\n")
    # smoke test a few
    checks = [
        ("league_table", {"season": "2023-2024", "top_n": 50}),
        ("player_season_leaders", {"season": "2023-2024", "metric_col": "goals_pss", "top_n": 5}),
        ("team_stat_leaders", {"season": "2023-2024", "metric_col": "tssf_yellow_cards", "top_n": 3}),
        ("market_value_leaders", {"top_n": 3}),
    ]
    for name, p in checks:
        sql, bound = TEMPLATES[name].build({**p})
        res = run_sql(sql, params=bound, max_rows=5)
        print(f"{name}: {res['row_count']} rows; first={res['rows'][0] if res['rows'] else None}")
