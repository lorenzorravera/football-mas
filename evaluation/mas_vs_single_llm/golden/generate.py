"""
golden/generate.py — DRAFT golden-set questions + canonical SQL  (Phase 2).

Status: CANDIDATE, not frozen. Till reviews/approves the SQL, then `build_ground_truth.py`
executes it and we FREEZE golden_set.json + ground_truth.json.

Authoring conventions (all verified against the live schema in Phase 0/1):
  * Season label is hyphenated 'YYYY-YYYY'. Latest season = 2024-2025 (no 2025-26 data).
  * Filter teams by JOINing `teams` on team_id and using the CANONICAL `teams.team_name`
    (e.g. 'Manchester United', NOT the denormalised 'Manchester Utd' in tss_team).
  * Point deductions are already inside tss_points (Everton −8, Forest −4 in 2023-2024).
  * Referee text uses a non-breaking space → normalise with replace(referee, chr(160), ' ').
  * Player-season totals SUM across team rows (handles mid-season transfers, e.g. Cole Palmer).
  * Every canonical_sql is a single read-only SELECT/WITH (executed via tools.run_sql).

Each item: id, question, category, difficulty, gt_type, answer_type, canonical_sql.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "results" / "golden"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Reusable fragments
TEAM = "JOIN teams t ON t.team_id = {a}.team_id"
SEAS = "JOIN seasons s ON s.season_id = {a}.season_id"

DRAFT_ITEMS: list[dict] = [
    # ───────────────────────── Team / league outcomes ─────────────────────────
    dict(id="Q01", category="team_league_outcomes", difficulty="simple",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team won the Premier League in 2024-2025?",
         canonical_sql="SELECT t.team_name FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2024-2025' AND st.tss_rank=1"),
    dict(id="Q02", category="team_league_outcomes", difficulty="simple",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many points did Arsenal finish with in the 2023-2024 season?",
         canonical_sql="SELECT st.tss_points FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2023-2024' AND t.team_name='Arsenal'"),
    dict(id="Q03", category="team_league_outcomes", difficulty="medium",
         gt_type="deterministic_sql", answer_type="ranking",
         question="Give the full 2022-2023 Premier League final table (rank, team, points).",
         canonical_sql="SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2022-2023' ORDER BY st.tss_rank"),
    dict(id="Q04", category="team_league_outcomes", difficulty="medium",
         gt_type="deterministic_sql", answer_type="table",
         question="Which three teams were relegated from the Premier League in 2023-2024?",
         canonical_sql="SELECT t.team_name, st.tss_rank FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2023-2024' AND st.tss_rank >= 18 ORDER BY st.tss_rank"),
    dict(id="Q05", category="team_league_outcomes", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team had the best goal difference in 2024-2025?",
         canonical_sql="SELECT t.team_name FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2024-2025' ORDER BY st.tss_goal_difference DESC, t.team_name LIMIT 1"),
    dict(id="Q06", category="team_league_outcomes", difficulty="edge_case",
         gt_type="multi_step", answer_type="table",
         question="How many points did Everton actually finish 2023-2024 with, and how many would they "
                  "have had without the points deduction?",
         canonical_sql="SELECT st.tss_points AS actual_points, (3*st.tss_wins + st.tss_draws) AS points_without_deduction "
                       "FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id "
                       "JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND t.team_name='Everton'"),
    dict(id="Q07", category="team_league_outcomes", difficulty="hard",
         gt_type="deterministic_sql", answer_type="table",
         question="What is the highest points total achieved by any team in a single season across 2020-2021 to 2024-2025?",
         canonical_sql="SELECT t.team_name, s.season, st.tss_points FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "ORDER BY st.tss_points DESC, t.team_name LIMIT 1"),
    dict(id="Q08", category="team_league_outcomes", difficulty="simple",
         gt_type="deterministic_sql", answer_type="table",
         question="Which teams finished in the top four in 2021-2022?",
         canonical_sql="SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2021-2022' AND st.tss_rank <= 4 ORDER BY st.tss_rank"),

    # ───────────────────────── Player season aggregates ─────────────────────────
    dict(id="Q09", category="player_season_aggregates", difficulty="simple",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Who was the top goalscorer in the 2023-2024 Premier League season, and how many goals did they score?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name "
                       "ORDER BY goals DESC, p.player_name LIMIT 1"),
    dict(id="Q10", category="player_season_aggregates", difficulty="medium",
         gt_type="deterministic_sql", answer_type="ranking",
         question="List the top five goalscorers in 2024-2025 with their goal totals.",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name "
                       "ORDER BY goals DESC, p.player_name LIMIT 5"),
    dict(id="Q11", category="player_season_aggregates", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Who provided the most assists in 2023-2024?",
         canonical_sql="SELECT p.player_name, SUM(pss.assists_pss) AS assists FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name "
                       "ORDER BY assists DESC, p.player_name LIMIT 1"),
    dict(id="Q12", category="player_season_aggregates", difficulty="edge_case",
         gt_type="multi_step", answer_type="scalar",
         question="How many league goals did Cole Palmer score in total in 2023-2024 (across all clubs he played for that season)?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS total_goals FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' AND p.player_name='Cole Palmer' GROUP BY p.player_id, p.player_name"),
    dict(id="Q13", category="player_season_aggregates", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which player played the most minutes in 2022-2023?",
         canonical_sql="SELECT p.player_name, SUM(pss.minutes_pss) AS minutes FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2022-2023' GROUP BY p.player_id, p.player_name "
                       "ORDER BY minutes DESC, p.player_name LIMIT 1"),
    dict(id="Q14", category="player_season_aggregates", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Who was Liverpool's top scorer in 2024-2025?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "JOIN teams t ON t.team_id=pss.team_id "
                       "WHERE s.season='2024-2025' AND t.team_name='Liverpool' "
                       "GROUP BY p.player_id, p.player_name ORDER BY goals DESC, p.player_name LIMIT 1"),
    dict(id="Q15", category="player_season_aggregates", difficulty="medium",
         gt_type="deterministic_sql", answer_type="table",
         question="Which players scored at least 20 league goals in 2024-2025?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name "
                       "HAVING SUM(pss.goals_pss) >= 20 ORDER BY goals DESC, p.player_name"),

    # ───────────────────────── Home / away splits ─────────────────────────
    dict(id="Q16", category="home_away_splits", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team earned the most home points in 2024-2025?",
         canonical_sql="SELECT t.team_name, ha.tshas_home_points AS home_points FROM team_season_home_away_standings ha "
                       "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
                       "WHERE s.season='2024-2025' ORDER BY home_points DESC, t.team_name LIMIT 1"),
    dict(id="Q17", category="home_away_splits", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team recorded the most away wins in 2023-2024?",
         canonical_sql="SELECT t.team_name, ha.tshas_away_wins AS away_wins FROM team_season_home_away_standings ha "
                       "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
                       "WHERE s.season='2023-2024' ORDER BY away_wins DESC, t.team_name LIMIT 1"),
    dict(id="Q18", category="home_away_splits", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which team had the biggest gap between home points and away points in 2023-2024?",
         canonical_sql="SELECT t.team_name, (ha.tshas_home_points - ha.tshas_away_points) AS home_away_gap "
                       "FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id "
                       "JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2023-2024' "
                       "ORDER BY home_away_gap DESC, t.team_name LIMIT 1"),
    dict(id="Q19", category="home_away_splits", difficulty="simple",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many home points did Arsenal earn in 2023-2024?",
         canonical_sql="SELECT ha.tshas_home_points FROM team_season_home_away_standings ha "
                       "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
                       "WHERE s.season='2023-2024' AND t.team_name='Arsenal'"),
    dict(id="Q20", category="home_away_splits", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team scored the most home goals in 2024-2025?",
         canonical_sql="SELECT t.team_name, ha.tshas_home_goals_for AS home_goals FROM team_season_home_away_standings ha "
                       "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
                       "WHERE s.season='2024-2025' ORDER BY home_goals DESC, t.team_name LIMIT 1"),

    # ───────────────────────── Disciplinary ─────────────────────────
    dict(id="Q21", category="disciplinary", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team received the most yellow cards in 2023-2024?",
         canonical_sql="SELECT t.team_name, sf.tssf_yellow_cards AS yellows FROM team_season_stats_for sf "
                       "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
                       "WHERE s.season='2023-2024' ORDER BY yellows DESC, t.team_name LIMIT 1"),
    dict(id="Q22", category="disciplinary", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which player received the most yellow cards in 2023-2024?",
         canonical_sql="SELECT p.player_name, SUM(pss.yellow_cards_pss) AS yellows FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name "
                       "ORDER BY yellows DESC, p.player_name LIMIT 1"),
    dict(id="Q23", category="disciplinary", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which team picked up the most red cards in 2024-2025?",
         canonical_sql="SELECT t.team_name, sf.tssf_red_cards AS reds FROM team_season_stats_for sf "
                       "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
                       "WHERE s.season='2024-2025' ORDER BY reds DESC, t.team_name LIMIT 1"),
    dict(id="Q24", category="disciplinary", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many red cards were shown in total across the league in 2023-2024?",
         canonical_sql="SELECT SUM(sf.tssf_red_cards) AS total_red_cards FROM team_season_stats_for sf "
                       "JOIN seasons s ON s.season_id=sf.season_id WHERE s.season='2023-2024'"),
    dict(id="Q25", category="disciplinary", difficulty="edge_case",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many Premier League matches did referee Anthony Taylor officiate in 2023-2024?",
         canonical_sql="SELECT COUNT(*) AS matches_officiated FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                       "WHERE s.season='2023-2024' AND replace(m.referee, chr(160), ' ') = 'Anthony Taylor'"),

    # ───────────────────────── xG over/under-performance (multi-step) ─────────────────────────
    dict(id="Q26", category="xg_performance", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Among players with at least 10 goals in 2023-2024, who overperformed their xG by the most (goals minus xG)?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
                       "ROUND(SUM(pss.goals_pss) - SUM(pss.xg_pss),2) AS overperformance FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name "
                       "HAVING SUM(pss.goals_pss) >= 10 ORDER BY overperformance DESC, p.player_name LIMIT 1"),
    dict(id="Q27", category="xg_performance", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Among players with at least 10 goals in 2023-2024, who underperformed their xG by the most (xG minus goals)?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
                       "ROUND(SUM(pss.xg_pss) - SUM(pss.goals_pss),2) AS underperformance FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name "
                       "HAVING SUM(pss.goals_pss) >= 10 ORDER BY underperformance DESC, p.player_name LIMIT 1"),
    dict(id="Q28", category="xg_performance", difficulty="medium",
         gt_type="multi_step", answer_type="table",
         question="How many goals did Erling Haaland score in 2023-2024 versus his xG, and what was the difference?",
         canonical_sql="SELECT SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
                       "ROUND(SUM(pss.goals_pss) - SUM(pss.xg_pss),2) AS difference FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' AND p.player_name='Erling Haaland' GROUP BY p.player_id"),
    dict(id="Q29", category="xg_performance", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Among players with at least 15 xG in 2024-2025, who had the highest goals-to-xG ratio?",
         canonical_sql="SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
                       "ROUND(SUM(pss.goals_pss)/NULLIF(SUM(pss.xg_pss),0),3) AS goals_per_xg FROM player_season_stats pss "
                       "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name "
                       "HAVING SUM(pss.xg_pss) >= 15 ORDER BY goals_per_xg DESC, p.player_name LIMIT 1"),
    dict(id="Q30", category="xg_performance", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which team had the most non-penalty expected goals (npxG) from its players combined in 2023-2024?",
         canonical_sql="SELECT t.team_name, ROUND(SUM(pss.npxg_pss),2) AS team_npxg FROM player_season_stats pss "
                       "JOIN teams t ON t.team_id=pss.team_id JOIN seasons s ON s.season_id=pss.season_id "
                       "WHERE s.season='2023-2024' GROUP BY t.team_id, t.team_name ORDER BY team_npxg DESC, t.team_name LIMIT 1"),

    # ───────────────────────── Market value / transfers ─────────────────────────
    dict(id="Q31", category="market_transfers", difficulty="medium",
         gt_type="multi_step", answer_type="scalar",
         question="Which player has the highest market value (most recent valuation on record)?",
         canonical_sql="SELECT p.player_name, mv.market_value FROM player_market_values mv "
                       "JOIN players p ON p.player_id=mv.player_id "
                       "WHERE (mv.player_id, mv.date_unix) IN (SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) "
                       "ORDER BY mv.market_value DESC, p.player_name LIMIT 1"),
    dict(id="Q32", category="market_transfers", difficulty="hard",
         gt_type="deterministic_sql", answer_type="table",
         question="What are the five largest transfer fees paid by a Premier League club (incoming transfers) in the data?",
         canonical_sql="SELECT p.player_name, tr.from_team, tr.to_team, tr.season, tr.transfer_fee "
                       "FROM player_transfers tr JOIN players p ON p.player_id=tr.player_id "
                       "WHERE tr.to_team IN (SELECT team_name FROM teams) AND tr.transfer_fee IS NOT NULL "
                       "ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 5"),
    dict(id="Q33", category="market_transfers", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="What was the most expensive incoming transfer to a Premier League club in the 2023-2024 season window?",
         canonical_sql="SELECT p.player_name, tr.to_team, tr.transfer_fee FROM player_transfers tr "
                       "JOIN players p ON p.player_id=tr.player_id "
                       "WHERE tr.season='2023-2024' AND tr.to_team IN (SELECT team_name FROM teams) AND tr.transfer_fee IS NOT NULL "
                       "ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 1"),
    dict(id="Q34", category="market_transfers", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="What is Chelsea's total recorded incoming transfer spend across all seasons in the data?",
         canonical_sql="SELECT SUM(tr.transfer_fee) AS total_spend FROM player_transfers tr "
                       "WHERE tr.to_team='Chelsea' AND tr.transfer_fee IS NOT NULL"),
    dict(id="Q35", category="market_transfers", difficulty="medium",
         gt_type="deterministic_sql", answer_type="table",
         question="List the three players with the highest market value at Manchester City (most recent valuation).",
         canonical_sql="SELECT p.player_name, mv.market_value FROM player_market_values mv "
                       "JOIN players p ON p.player_id=mv.player_id "
                       "JOIN player_season_stats pss ON pss.player_id=mv.player_id "
                       "JOIN teams t ON t.team_id=pss.team_id "
                       "WHERE t.team_name='Manchester City' "
                       "AND (mv.player_id, mv.date_unix) IN (SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) "
                       "GROUP BY p.player_name, mv.market_value ORDER BY mv.market_value DESC, p.player_name LIMIT 3"),

    # ───────────────────────── Availability / injuries ─────────────────────────
    dict(id="Q36", category="availability", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="Which player missed the most games in a single injury spell in 2023-2024?",
         canonical_sql="SELECT p.player_name, pis.games_missed FROM player_injury_spells pis "
                       "JOIN players p ON p.player_id=pis.player_id WHERE pis.season='2023-2024' "
                       "ORDER BY pis.games_missed DESC NULLS LAST, p.player_name LIMIT 1"),
    dict(id="Q37", category="availability", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which player missed the most total days to injury across all spells in 2023-2024?",
         canonical_sql="SELECT p.player_name, SUM(pis.days_missed) AS total_days_missed FROM player_injury_spells pis "
                       "JOIN players p ON p.player_id=pis.player_id WHERE pis.season='2023-2024' "
                       "GROUP BY p.player_id, p.player_name ORDER BY total_days_missed DESC NULLS LAST, p.player_name LIMIT 1"),
    dict(id="Q38", category="availability", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which club had the most separate injury spells recorded in 2023-2024?",
         canonical_sql="SELECT pis.team, COUNT(*) AS spells FROM player_injury_spells pis "
                       "WHERE pis.season='2023-2024' GROUP BY pis.team ORDER BY spells DESC, pis.team LIMIT 1"),
    dict(id="Q39", category="availability", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many injury spells were recorded for Brentford players in 2023-2024?",
         canonical_sql="SELECT COUNT(*) AS spells FROM player_injury_spells pis "
                       "WHERE pis.season='2023-2024' AND pis.team='Brentford'"),

    # ───────────────────────── Event-level & player-match ─────────────────────────
    dict(id="Q40", category="event_player_match", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which player attempted the most shots (from event data) in 2023-2024?",
         canonical_sql="SELECT p.player_name, COUNT(*) AS shots FROM match_events e "
                       "JOIN players p ON p.player_id=e.player_id "
                       "WHERE e.season='2023-2024' AND e.league_code='ENG-PL' AND e.is_shot = TRUE "
                       "GROUP BY p.player_id, p.player_name ORDER BY shots DESC, p.player_name LIMIT 1"),
    dict(id="Q41", category="event_player_match", difficulty="medium",
         gt_type="deterministic_sql", answer_type="table",
         question="What is the most goals scored by a single player in one match in 2024-2025?",
         canonical_sql="SELECT p.player_name, pmp.game_id, pmp.match_goals FROM player_match_performance pmp "
                       "JOIN players p ON p.player_id=pmp.player_id "
                       "WHERE pmp.season='2024-2025' AND pmp.league_code='ENG-PL' "
                       "ORDER BY pmp.match_goals DESC, p.player_name LIMIT 5"),
    dict(id="Q42", category="event_player_match", difficulty="hard",
         gt_type="multi_step", answer_type="scalar",
         question="Which player committed the most fouls in 2023-2024 (summed across matches)?",
         canonical_sql="SELECT p.player_name, SUM(pmp.fouls) AS fouls FROM player_match_performance pmp "
                       "JOIN players p ON p.player_id=pmp.player_id "
                       "WHERE pmp.season='2023-2024' AND pmp.league_code='ENG-PL' "
                       "GROUP BY p.player_id, p.player_name "
                       "HAVING SUM(pmp.fouls) IS NOT NULL ORDER BY fouls DESC, p.player_name LIMIT 1"),
    dict(id="Q43", category="event_player_match", difficulty="medium",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many shot events resulted in a goal (is_goal) in 2024-2025?",
         canonical_sql="SELECT COUNT(*) AS goal_events FROM match_events e "
                       "WHERE e.season='2024-2025' AND e.league_code='ENG-PL' AND e.is_goal = TRUE"),
    dict(id="Q44", category="event_player_match", difficulty="medium",
         gt_type="deterministic_sql", answer_type="table",
         question="What was the biggest home win (by goal margin) in 2024-2025?",
         canonical_sql="SELECT ht.team_name AS home_team, at.team_name AS away_team, m.home_score, m.away_score "
                       "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                       "JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id "
                       "WHERE s.season='2024-2025' ORDER BY (m.home_score - m.away_score) DESC, m.home_score DESC LIMIT 1"),

    # ───────────────────────── Edge cases ─────────────────────────
    dict(id="Q45", category="edge_case", difficulty="edge_case",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many points did Norwich City get in the 2024-2025 Premier League season?",
         canonical_sql="SELECT st.tss_points FROM team_season_standings st "
                       "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
                       "WHERE s.season='2024-2025' AND t.team_name='Norwich City'"),
    dict(id="Q46", category="edge_case", difficulty="edge_case",
         gt_type="deterministic_sql", answer_type="scalar",
         question="How many matches in the 2020-2021 season have a recorded attendance figure?",
         canonical_sql="SELECT COUNT(*) AS matches_with_attendance FROM matches m JOIN seasons s ON s.season_id=m.season_id "
                       "WHERE s.season='2020-2021' AND m.attendance_m IS NOT NULL"),
]


def write_golden_set() -> Path:
    """Write the CANDIDATE golden set (no ground truth yet, no hash)."""
    from golden.schema import GoldenItem
    items = [GoldenItem(**it).to_dict() for it in DRAFT_ITEMS]
    out = OUT_DIR / "golden_set.candidate.json"
    out.write_text(json.dumps({"frozen": False, "items": items}, indent=2))
    return out


if __name__ == "__main__":
    path = write_golden_set()
    from collections import Counter
    cats = Counter(it["category"] for it in DRAFT_ITEMS)
    diff = Counter(it["difficulty"] for it in DRAFT_ITEMS)
    print(f"{len(DRAFT_ITEMS)} candidate items -> {path}")
    print("by category:", dict(cats))
    print("by difficulty:", dict(diff))
