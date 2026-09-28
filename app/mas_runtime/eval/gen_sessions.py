"""
Generate + validate session datasets for the multi-step memory experiment (Phase C).

Renders parameterized ground_truth_sql from a handful of SQL-pitfall templates (referee
non-breaking-space, team home+away summation, total-wins H/A, clean sheets, player-name
join, standings lookups), executes each read-only against the DB, and writes the JSON
session files whose every ground_truth_sql returns a non-empty result. Prints a
validation table; exits non-zero if any session fails.

This is how the scaled session suite under eval/sessions/ was produced — re-run to
regenerate or extend. Idempotent (overwrites the same filenames). The 4 hand-written
starter sessions (correction_referee_01, correction_teamseason_01, cache_table_01,
conversation_team_player_01) are NOT emitted here; this script only adds the scaled set.

Usage:  cd Ethan/agent_v4 && python eval/gen_sessions.py
"""
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv

AGENT = Path(__file__).resolve().parent.parent
load_dotenv(AGENT / ".env", override=True)
import psycopg2, psycopg2.extras

OUT = AGENT / "eval" / "sessions"

# ---- SQL templates -------------------------------------------------------

_JOINS = ("JOIN seasons s ON m.season_id = s.season_id "
          "JOIN competitions c ON s.competition_id = c.competition_id")
_PL = "c.league_code = 'ENG-PL'"

def ref_sql(metric, season, referee):
    # Referee non-breaking-space pitfall: must REPLACE(chr(160)).
    return (f"SELECT SUM(m.home_{metric} + m.away_{metric}) AS total "
            f"FROM matches m {_JOINS} "
            f"WHERE {_PL} AND s.season = '{season}' "
            f"AND REPLACE(m.referee, chr(160), chr(32)) = '{referee}';")

def teamsum_sql(metric, season, team):
    # Home+away summation pitfall: a team's per-match stat lives in home_* OR away_*.
    base = (f"SELECT m.{{side}}_{metric} AS v FROM matches m {_JOINS} "
            f"JOIN teams t ON m.{{tid}} = t.team_id "
            f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}'")
    return (f"SELECT SUM(v) AS total FROM ("
            f"{base.format(side='home', tid='home_team_id')} UNION ALL "
            f"{base.format(side='away', tid='away_team_id')}) x;")

def wins_sql(season, team):
    # Total wins = home wins (ft_result='H') + away wins (ft_result='A').
    h = (f"SELECT 1 FROM matches m {_JOINS} JOIN teams t ON m.home_team_id = t.team_id "
         f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}' AND m.ft_result = 'H'")
    a = (f"SELECT 1 FROM matches m {_JOINS} JOIN teams t ON m.away_team_id = t.team_id "
         f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}' AND m.ft_result = 'A'")
    return f"SELECT COUNT(*) AS wins FROM ({h} UNION ALL {a}) x;"

def cleansheet_sql(season, team):
    # Clean sheet = opponent scored 0, across home and away fixtures.
    h = (f"SELECT 1 FROM matches m {_JOINS} JOIN teams t ON m.home_team_id = t.team_id "
         f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}' AND m.away_score = 0")
    a = (f"SELECT 1 FROM matches m {_JOINS} JOIN teams t ON m.away_team_id = t.team_id "
         f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}' AND m.home_score = 0")
    return f"SELECT COUNT(*) AS clean_sheets FROM ({h} UNION ALL {a}) x;"

def topscorer_join_sql(season, team):
    # Player-name join pitfall: name lives in `players`, goals in player_season_stats,
    # scoped to PL season via seasons->competitions.
    return ("SELECT p.player_name, SUM(pss.goals_pss) AS goals "
            "FROM player_season_stats pss "
            "JOIN players p ON pss.player_id = p.player_id "
            "JOIN seasons s ON pss.season_id = s.season_id "
            "JOIN competitions c ON s.competition_id = c.competition_id "
            "JOIN teams t ON pss.team_id = t.team_id "
            f"WHERE {_PL} AND s.season = '{season}' AND t.team_name = '{team}' "
            "GROUP BY p.player_name ORDER BY goals DESC LIMIT 1;")

def standings_sql(season, col, *, team=None, rank=None):
    where = f"{_PL} AND s.season = '{season}'"
    if team is not None:
        where += f" AND tss_team = '{team}'"
    if rank is not None:
        where += f" AND tss_rank = {rank}"
    return (f"SELECT {col} FROM team_season_standings tss "
            "JOIN seasons s ON tss.season_id = s.season_id "
            "JOIN competitions c ON s.competition_id = c.competition_id "
            f"WHERE {where};")

# ---- Session definitions -------------------------------------------------

def turn(i, role, query, sql):
    return {"turn_index": i, "role": role, "query": query, "ground_truth_sql": sql}

# General, instructive fixes seeded into correction memory by the harness when a
# trigger turn is judged WRONG against ground truth (see session_runner._run_mas_arm).
# Deliberately general (name the technique, not the exact answer) so the beneficiary
# must still write correct SQL for a different entity — genuine transfer, not recall.
LESSON = {
    "referee": ("Referee names in the matches table are stored with a NON-BREAKING SPACE "
                "(Unicode chr(160)) between first and last name, not a normal space. A filter "
                "like WHERE m.referee = 'First Last' (normal space) matches 0 rows and silently "
                "returns NULL/0. Always normalize first: "
                "WHERE REPLACE(m.referee, chr(160), chr(32)) = 'First Last'."),
    "teamsum": ("A team's per-match stat lives in EITHER the home_* column (when it played at "
                "home) OR the away_* column (when away) of the wide matches table. Summing only "
                "one side undercounts. Union both: SUM of home_<metric> WHERE home_team_id=team "
                "plus away_<metric> WHERE away_team_id=team."),
    "wins":    ("A team's total wins = home wins (ft_result='H' where it is home_team_id) PLUS "
                "away wins (ft_result='A' where it is away_team_id). ft_result is from the HOME "
                "team's perspective, so counting only one side undercounts."),
    "cleansheet": ("A clean sheet = the opponent scored 0. In the wide matches table that is "
                   "away_score=0 in the team's HOME games and home_score=0 in its AWAY games — "
                   "count across BOTH sides."),
    "playerjoin": ("Player names are NOT in player_season_stats (it keys on player_id). Join "
                   "players p ON pss.player_id = p.player_id for the name, SUM goals_pss per "
                   "player, and PL-scope via seasons -> competitions league_code='ENG-PL'."),
}

SESSIONS = []

# ===== CORRECTION (headline) =====
SESSIONS.append({
    "session_id": "correction_referee_02", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["referee"],
    "description": "Referee non-breaking-space pitfall (variant 2): yellow then red cards, different referees/seasons. Same fix as referee_01 should transmit.",
    "turns": [
        turn(0, "trigger", "How many yellow cards in total were shown in matches refereed by Paul Tierney in the 2023-2024 Premier League season?",
             ref_sql("yellow_cards", "2023-2024", "Paul Tierney")),
        turn(1, "beneficiary", "How many total red cards were shown in matches refereed by Simon Hooper in the 2024-2025 Premier League season?",
             ref_sql("red_cards", "2024-2025", "Simon Hooper")),
    ]})
SESSIONS.append({
    "session_id": "correction_referee_03", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["referee"],
    "description": "Referee nbsp pitfall (variant 3): shots, two beneficiaries across refs/seasons.",
    "turns": [
        turn(0, "trigger", "How many total shots were taken in matches refereed by Anthony Taylor in the 2022-2023 Premier League season?",
             ref_sql("shots", "2022-2023", "Anthony Taylor")),
        turn(1, "beneficiary", "How many total fouls were committed in matches refereed by Michael Oliver in the 2023-2024 Premier League season?",
             ref_sql("fouls", "2023-2024", "Michael Oliver")),
        turn(2, "beneficiary", "And how many corners in total were there in matches refereed by Chris Kavanagh in the 2024-2025 Premier League season?",
             ref_sql("corners", "2024-2025", "Chris Kavanagh")),
    ]})
SESSIONS.append({
    "session_id": "correction_teamseason_02", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["teamsum"],
    "description": "Team home+away summation pitfall (variant 2): shots then corners, different teams/seasons.",
    "turns": [
        turn(0, "trigger", "How many shots did Manchester City take in total during the 2023-2024 Premier League season?",
             teamsum_sql("shots", "2023-2024", "Manchester City")),
        turn(1, "beneficiary", "How many corners did Arsenal win in total across the 2024-2025 Premier League season?",
             teamsum_sql("corners", "2024-2025", "Arsenal")),
    ]})
SESSIONS.append({
    "session_id": "correction_teamseason_03", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["teamsum"],
    "description": "Team home+away summation pitfall (variant 3): red cards then yellow cards.",
    "turns": [
        turn(0, "trigger", "How many red cards did Chelsea receive in total during the 2023-2024 Premier League season?",
             teamsum_sql("red_cards", "2023-2024", "Chelsea")),
        turn(1, "beneficiary", "How many yellow cards did Liverpool pick up across the 2024-2025 Premier League season?",
             teamsum_sql("yellow_cards", "2024-2025", "Liverpool")),
    ]})
SESSIONS.append({
    "session_id": "correction_wins_01", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["wins"],
    "description": "Total-wins pitfall: a team's wins = home wins (ft_result='H') + away wins (ft_result='A'); naive query counts only one perspective.",
    "turns": [
        turn(0, "trigger", "How many matches did Manchester United win in total in the 2023-2024 Premier League season?",
             wins_sql("2023-2024", "Manchester United")),
        turn(1, "beneficiary", "How many games did Newcastle United win across the whole 2024-2025 Premier League season?",
             wins_sql("2024-2025", "Newcastle United")),
    ]})
SESSIONS.append({
    "session_id": "correction_cleansheet_01", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["cleansheet"],
    "description": "Clean-sheet pitfall: clean sheet = opponent scored 0, counted across both home and away fixtures (away_score=0 at home, home_score=0 away).",
    "turns": [
        turn(0, "trigger", "How many clean sheets did Arsenal keep in the 2023-2024 Premier League season?",
             cleansheet_sql("2023-2024", "Arsenal")),
        turn(1, "beneficiary", "How many clean sheets did Liverpool manage in the 2024-2025 Premier League season?",
             cleansheet_sql("2024-2025", "Liverpool")),
    ]})
SESSIONS.append({
    "session_id": "correction_playerjoin_01", "sub_experiment": "correction", "variant": "no_control",
    "correction_lesson": LESSON["playerjoin"],
    "description": "Player-name join pitfall: player_season_stats keys on player_id; the name lives in `players`, goals must be summed per player and PL-scoped via seasons->competitions.",
    "turns": [
        turn(0, "trigger", "Who was Manchester City's top scorer in the 2023-2024 Premier League season, and how many league goals did they score?",
             topscorer_join_sql("2023-2024", "Manchester City")),
        turn(1, "beneficiary", "Who top-scored for Liverpool in the 2024-2025 Premier League season and with how many goals?",
             topscorer_join_sql("2024-2025", "Liverpool")),
    ]})

# ===== CACHE (reworded near-repeats) =====
SESSIONS.append({
    "session_id": "cache_topscorer_01", "sub_experiment": "cache", "variant": "no_control",
    "description": "Near-repeat: the league's overall top scorer, reworded. Accuracy unchanged; win is cache reuse.",
    "turns": [
        turn(0, "trigger", "Who was the top goal scorer in the 2023-2024 Premier League season and how many did they score?",
             standings_sql("2023-2024", "tss_top_scorer_name, tss_top_scorer_goals", rank=1)),
        turn(1, "beneficiary", "In the 2023-2024 Premier League, which player scored the most goals for the champions, and how many?",
             standings_sql("2023-2024", "tss_top_scorer_name, tss_top_scorer_goals", rank=1)),
    ]})
SESSIONS.append({
    "session_id": "cache_points_01", "sub_experiment": "cache", "variant": "no_control",
    "description": "Near-repeat: champion's points total, reworded.",
    "turns": [
        turn(0, "trigger", "How many points did Manchester City finish with in the 2023-2024 Premier League season?",
             standings_sql("2023-2024", "tss_points", team="Manchester City")),
        turn(1, "beneficiary", "What was Manchester City's final points tally in the 2023-2024 Premier League?",
             standings_sql("2023-2024", "tss_points", team="Manchester City")),
    ]})
SESSIONS.append({
    "session_id": "cache_relegated_01", "sub_experiment": "cache", "variant": "no_control",
    "description": "Near-repeat: which team finished bottom, reworded.",
    "turns": [
        turn(0, "trigger", "Which team finished bottom of the Premier League in the 2024-2025 season?",
             standings_sql("2024-2025", "tss_team", rank=20)),
        turn(1, "beneficiary", "Who came last in the 2024-2025 Premier League table?",
             standings_sql("2024-2025", "tss_team", rank=20)),
    ]})
SESSIONS.append({
    "session_id": "cache_goaldiff_01", "sub_experiment": "cache", "variant": "no_control",
    "description": "Near-repeat: champion's goal difference, reworded.",
    "turns": [
        turn(0, "trigger", "What goal difference did Liverpool end the 2024-2025 Premier League season with?",
             standings_sql("2024-2025", "tss_goal_difference", team="Liverpool")),
        turn(1, "beneficiary", "What was Liverpool's goal difference at the end of the 2024-2025 Premier League campaign?",
             standings_sql("2024-2025", "tss_goal_difference", team="Liverpool")),
    ]})

# ===== CONVERSATION (reference carry) =====
SESSIONS.append({
    "session_id": "conversation_relegated_01", "sub_experiment": "conversation", "variant": "no_control",
    "description": "Reference carry: turn 0 names the bottom team; follow-ups say 'they'/'their'.",
    "turns": [
        turn(0, "trigger", "Which team finished bottom of the 2023-2024 Premier League?",
             standings_sql("2023-2024", "tss_team", rank=20)),
        turn(1, "beneficiary", "How many goals did they concede that season?",
             standings_sql("2023-2024", "tss_goals_against", rank=20)),
        turn(2, "beneficiary", "And how many points did they finish on?",
             standings_sql("2023-2024", "tss_points", rank=20)),
    ]})
SESSIONS.append({
    "session_id": "conversation_runnerup_01", "sub_experiment": "conversation", "variant": "no_control",
    "description": "Reference carry: the runner-up team, then 'their' stats.",
    "turns": [
        turn(0, "trigger", "Who finished second in the 2024-2025 Premier League?",
             standings_sql("2024-2025", "tss_team", rank=2)),
        turn(1, "beneficiary", "How many goals did that team score across the season?",
             standings_sql("2024-2025", "tss_goals_for", rank=2)),
        turn(2, "beneficiary", "And how many matches did they win?",
             standings_sql("2024-2025", "tss_wins", rank=2)),
    ]})
SESSIONS.append({
    "session_id": "conversation_champion_01", "sub_experiment": "conversation", "variant": "no_control",
    "description": "Reference carry: champion, then 'their' goal difference and top scorer.",
    "turns": [
        turn(0, "trigger", "Who won the 2024-2025 Premier League title?",
             standings_sql("2024-2025", "tss_team", rank=1)),
        turn(1, "beneficiary", "What goal difference did they finish with?",
             standings_sql("2024-2025", "tss_goal_difference", rank=1)),
        turn(2, "beneficiary", "Who was their top scorer that season?",
             standings_sql("2024-2025", "tss_top_scorer_name, tss_top_scorer_goals", rank=1)),
    ]})
SESSIONS.append({
    "session_id": "conversation_midtable_01", "sub_experiment": "conversation", "variant": "no_control",
    "description": "Reference carry across a named mid-table team set in turn 0.",
    "turns": [
        turn(0, "trigger", "Where did Brighton finish in the 2023-2024 Premier League table?",
             standings_sql("2023-2024", "tss_rank", team="Brighton")),
        turn(1, "beneficiary", "How many points did they get that season?",
             standings_sql("2023-2024", "tss_points", team="Brighton")),
        turn(2, "beneficiary", "And how many goals did they score?",
             standings_sql("2023-2024", "tss_goals_for", team="Brighton")),
    ]})

# ===== SCALED BATCH (2026-07-01): +N per family for statistical power =====
# The starter suite above is n=19 total (9 correction / 5 cache / 5 conversation,
# incl. the 4 hand-written starters). Each sub-experiment was under-powered
# (Wilcoxon p≈0.25–0.5). This batch lifts every family to ~18–20 sessions so the
# result is statistically defensible. Entities below are all validated live:
#   • referees per season taken from the >=15-match list (ENG-PL 2020-21..2024-25);
#   • team-JOIN templates use teams.team_name spelling ("Manchester United");
#   • standings templates use tss_team spelling ("Manchester Utd").
# All 5 PL seasons carry player_season_stats, so playerjoin works in any of them.

# -- natural-language phrasings (text only; validation checks the SQL, not the prose) --
_REF_PHRASE = {
    "yellow_cards": "yellow cards were shown", "red_cards": "red cards were shown",
    "shots": "shots were taken", "fouls": "fouls were committed",
    "corners": "corners were awarded",
}
_TEAMSUM_PHRASE = {
    "shots": "shots did {t} take", "corners": "corners did {t} win",
    "red_cards": "red cards did {t} receive", "yellow_cards": "yellow cards did {t} pick up",
    "fouls": "fouls did {t} commit",
}
_COL_PHRASE = {  # (primary phrasing, reworded near-repeat) for a team= standings lookup
    "tss_points": ("How many points did {t} finish with in the {s} Premier League season?",
                   "What was {t}'s final points tally in the {s} Premier League?"),
    "tss_goal_difference": ("What goal difference did {t} end the {s} Premier League season with?",
                            "What was {t}'s goal difference at the end of the {s} Premier League campaign?"),
    "tss_goals_for": ("How many goals did {t} score in the {s} Premier League season?",
                      "What was {t}'s total goals scored in the {s} Premier League?"),
    "tss_wins": ("How many matches did {t} win in the {s} Premier League season?",
                 "What was {t}'s win count in the {s} Premier League?"),
    "tss_attendance": ("What was {t}'s total home attendance in the {s} Premier League season?",
                       "How many fans in total attended {t}'s home games in the {s} Premier League?"),
}
# per-column phrasing for a 'they'/'that team' reference-carry follow-up
_CARRY_PHRASE = {
    "tss_goals_against": "How many goals did they concede that season?",
    "tss_goals_for": "How many goals did they score across the season?",
    "tss_points": "And how many points did they finish on?",
    "tss_wins": "And how many matches did they win?",
    "tss_losses": "How many games did they lose that season?",
    "tss_goal_difference": "What goal difference did they finish with?",
    "tss_rank": "Where did they finish in the table?",
    "tss_top_scorer_name, tss_top_scorer_goals": "Who was their top scorer that season?",
}

def _add_correction(sid, lesson_key, desc, template, trig, benes, trig_q, bene_q):
    turns = [turn(0, "trigger", trig_q, template(*trig))]
    for i, (b, q) in enumerate(zip(benes, bene_q), start=1):
        turns.append(turn(i, "beneficiary", q, template(*b)))
    SESSIONS.append({"session_id": sid, "sub_experiment": "correction", "variant": "no_control",
                     "correction_lesson": LESSON[lesson_key], "description": desc, "turns": turns})

# ---- CORRECTION (+11 → 18 generated) ----
# referee nbsp pitfall, (metric, season, referee)
for sid, tr, be in [
    ("correction_referee_04", ("fouls", "2020-2021", "Michael Oliver"),   ("yellow_cards", "2021-2022", "Anthony Taylor")),
    ("correction_referee_05", ("corners", "2022-2023", "Robert Jones"),    ("shots", "2023-2024", "Andy Madley")),
    ("correction_referee_06", ("red_cards", "2021-2022", "Craig Pawson"),  ("fouls", "2024-2025", "Samuel Barrott")),
]:
    _add_correction(
        sid, "referee", "Referee nbsp pitfall (scaled): trigger then a different ref/season/metric beneficiary.",
        ref_sql, tr, [be],
        f"How many {_REF_PHRASE[tr[0]]} in total in matches refereed by {tr[2]} in the {tr[1]} Premier League season?",
        [f"How many {_REF_PHRASE[be[0]]} in total in matches refereed by {be[2]} in the {be[1]} Premier League season?"])

# team home+away summation pitfall, (metric, season, team[teams.team_name])
for sid, tr, be in [
    ("correction_teamsum_04", ("shots", "2021-2022", "Tottenham Hotspur"), ("corners", "2022-2023", "Newcastle United")),
    ("correction_teamsum_05", ("fouls", "2020-2021", "Leicester City"),    ("yellow_cards", "2023-2024", "Aston Villa")),
]:
    _add_correction(
        sid, "teamsum", "Team home+away summation pitfall (scaled).", teamsum_sql, tr, [be],
        f"How many {_TEAMSUM_PHRASE[tr[0]].format(t=tr[2])} in total during the {tr[1]} Premier League season?",
        [f"How many {_TEAMSUM_PHRASE[be[0]].format(t=be[2])} in total during the {be[1]} Premier League season?"])

# total-wins pitfall, (season, team)
for sid, tr, be in [
    ("correction_wins_02", ("2021-2022", "Liverpool"),       ("2022-2023", "Arsenal")),
    ("correction_wins_03", ("2020-2021", "Manchester City"), ("2024-2025", "Chelsea")),
]:
    _add_correction(
        sid, "wins", "Total-wins pitfall (scaled): home wins + away wins.", wins_sql, tr, [be],
        f"How many matches did {tr[1]} win in total in the {tr[0]} Premier League season?",
        [f"How many games did {be[1]} win across the whole {be[0]} Premier League season?"])

# clean-sheet pitfall, (season, team)
for sid, tr, be in [
    ("correction_cleansheet_02", ("2022-2023", "Newcastle United"), ("2023-2024", "Manchester City")),
    ("correction_cleansheet_03", ("2021-2022", "Manchester City"),  ("2024-2025", "Arsenal")),
]:
    _add_correction(
        sid, "cleansheet", "Clean-sheet pitfall (scaled): opponent scored 0 across both sides.", cleansheet_sql, tr, [be],
        f"How many clean sheets did {tr[1]} keep in the {tr[0]} Premier League season?",
        [f"How many clean sheets did {be[1]} manage in the {be[0]} Premier League season?"])

# player-name join pitfall, (season, team)
for sid, tr, be in [
    ("correction_playerjoin_02", ("2022-2023", "Arsenal"),   ("2023-2024", "Manchester City")),
    ("correction_playerjoin_03", ("2021-2022", "Liverpool"), ("2024-2025", "Nottingham Forest")),
]:
    _add_correction(
        sid, "playerjoin", "Player-name join pitfall (scaled).", topscorer_join_sql, tr, [be],
        f"Who was {tr[1]}'s top scorer in the {tr[0]} Premier League season, and how many league goals did they score?",
        [f"Who top-scored for {be[1]} in the {be[0]} Premier League season and with how many goals?"])

# ---- CACHE (+13 → 17 generated) ----  reworded near-repeat, SAME SQL both turns.
# team= lookups (tss_team spelling): (sid, season, team, column)
for sid, season, team, col in [
    ("cache_points_02",    "2022-2023", "Arsenal",         "tss_points"),
    ("cache_points_03",    "2021-2022", "Liverpool",       "tss_points"),
    ("cache_goaldiff_02",  "2022-2023", "Manchester City", "tss_goal_difference"),
    ("cache_goaldiff_03",  "2023-2024", "Arsenal",         "tss_goal_difference"),
    ("cache_wins_01",      "2023-2024", "Liverpool",       "tss_wins"),
    ("cache_wins_02",      "2024-2025", "Arsenal",         "tss_wins"),
    ("cache_goalsfor_01",  "2022-2023", "Manchester City", "tss_goals_for"),
    ("cache_goalsfor_02",  "2020-2021", "Manchester City", "tss_goals_for"),
    ("cache_attendance_01","2023-2024", "Manchester Utd",  "tss_attendance"),
]:
    qa, qb = (p.format(t=team, s=season) for p in _COL_PHRASE[col])
    sql = standings_sql(season, col, team=team)
    SESSIONS.append({"session_id": sid, "sub_experiment": "cache", "variant": "no_control",
        "description": f"Near-repeat ({col}), reworded. Accuracy unchanged; win is cache reuse.",
        "turns": [turn(0, "trigger", qa, sql), turn(1, "beneficiary", qb, sql)]})
# rank= lookups: champion / relegated / top scorer near-repeats
for sid, season, rank, col, qa, qb in [
    ("cache_topscorer_02", "2024-2025", 1, "tss_top_scorer_name, tss_top_scorer_goals",
     "Who was the top goal scorer in the 2024-2025 Premier League and how many did they score?",
     "In the 2024-2025 Premier League, which player scored the most league goals, and how many?"),
    ("cache_topscorer_03", "2022-2023", 1, "tss_top_scorer_name, tss_top_scorer_goals",
     "Who finished as the 2022-2023 Premier League's leading scorer, and with how many goals?",
     "Which player topped the 2022-2023 Premier League scoring charts, and on how many goals?"),
    ("cache_relegated_02", "2023-2024", 20, "tss_team",
     "Which team finished bottom of the 2023-2024 Premier League?",
     "Who came last in the 2023-2024 Premier League table?"),
    ("cache_champion_01",  "2021-2022", 1, "tss_team",
     "Who won the 2021-2022 Premier League title?",
     "Which club were crowned 2021-2022 Premier League champions?"),
]:
    sql = standings_sql(season, col, rank=rank)
    SESSIONS.append({"session_id": sid, "sub_experiment": "cache", "variant": "no_control",
        "description": f"Near-repeat (rank {rank} {col}), reworded.",
        "turns": [turn(0, "trigger", qa, sql), turn(1, "beneficiary", qb, sql)]})

# ---- CONVERSATION (+12 → 16 generated) ----  reference carry across 3 turns.
# rank-anchored: turn 0 identifies the team by finishing position, follow-ups say 'they'.
def _conv_rank(sid, season, rank, anchor_q, followups):
    turns = [turn(0, "trigger", anchor_q, standings_sql(season, "tss_team", rank=rank))]
    for i, col in enumerate(followups, start=1):
        turns.append(turn(i, "beneficiary", _CARRY_PHRASE[col], standings_sql(season, col, rank=rank)))
    SESSIONS.append({"session_id": sid, "sub_experiment": "conversation", "variant": "no_control",
        "description": f"Reference carry: rank {rank} team named in turn 0; follow-ups say 'they'.",
        "turns": turns})

for sid, season, rank, aq, fus in [
    ("conversation_champion_02", "2022-2023", 1, "Who won the 2022-2023 Premier League title?",
     ["tss_goal_difference", "tss_top_scorer_name, tss_top_scorer_goals"]),
    ("conversation_champion_03", "2020-2021", 1, "Who were the 2020-2021 Premier League champions?",
     ["tss_points", "tss_wins"]),
    ("conversation_runnerup_02", "2022-2023", 2, "Who finished second in the 2022-2023 Premier League?",
     ["tss_goals_for", "tss_losses"]),
    ("conversation_runnerup_03", "2023-2024", 2, "Who were the runners-up in the 2023-2024 Premier League?",
     ["tss_goals_against", "tss_points"]),
    ("conversation_relegated_02", "2024-2025", 20, "Which team finished bottom of the 2024-2025 Premier League?",
     ["tss_goals_against", "tss_points"]),
    ("conversation_relegated_03", "2021-2022", 20, "Who came last in the 2021-2022 Premier League?",
     ["tss_points", "tss_wins"]),
    ("conversation_topfour_01", "2023-2024", 4, "Who finished fourth in the 2023-2024 Premier League?",
     ["tss_points", "tss_goal_difference"]),
    ("conversation_thirdplace_01", "2024-2025", 3, "Who finished third in the 2024-2025 Premier League?",
     ["tss_goal_difference", "tss_goals_for"]),
]:
    _conv_rank(sid, season, rank, aq, fus)

# team-anchored: turn 0 names a mid-table team explicitly, follow-ups say 'they'.
def _conv_team(sid, season, team, anchor_q, followups):
    turns = [turn(0, "trigger", anchor_q, standings_sql(season, "tss_rank", team=team))]
    for i, col in enumerate(followups, start=1):
        turns.append(turn(i, "beneficiary", _CARRY_PHRASE[col], standings_sql(season, col, team=team)))
    SESSIONS.append({"session_id": sid, "sub_experiment": "conversation", "variant": "no_control",
        "description": f"Reference carry across a named team ({team}) set in turn 0.",
        "turns": turns})

for sid, season, team, fus in [
    ("conversation_midtable_02", "2024-2025", "Fulham",           ["tss_points", "tss_goals_for"]),
    ("conversation_midtable_03", "2022-2023", "Brentford",        ["tss_points", "tss_wins"]),
    ("conversation_team_01",     "2023-2024", "Newcastle United", ["tss_points", "tss_goals_for"]),
    ("conversation_team_02",     "2021-2022", "West Ham United",  ["tss_points", "tss_goals_against"]),
]:
    _conv_team(sid, season, team, f"Where did {team} finish in the {season} Premier League table?", fus)

# ---- Validate + write ----------------------------------------------------

def main():
    conn = psycopg2.connect(os.environ["DATABASE_URI"])
    ok, bad = [], []
    for sess in SESSIONS:
        sess_ok = True
        for t in sess["turns"]:
            try:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(t["ground_truth_sql"].rstrip(";"))
                    rows = cur.fetchall()
                conn.rollback()
                nonempty = bool(rows) and any(
                    any(v is not None for v in r.values()) for r in rows)
                status = "OK" if nonempty else "EMPTY"
            except Exception as e:
                conn.rollback()
                status = f"ERR:{str(e).splitlines()[0][:60]}"
                nonempty = False
            mark = "✓" if nonempty else "✗"
            print(f"  {mark} {sess['session_id']} t{t['turn_index']:<2} [{status}] "
                  f"{(rows[0] if nonempty else '')}"[:110])
            if not nonempty:
                sess_ok = False
        (ok if sess_ok else bad).append(sess["session_id"])
        if sess_ok:
            path = OUT / f"{sess['session_id']}.json"
            keys = ["session_id", "sub_experiment", "variant"]
            if "correction_lesson" in sess:
                keys.append("correction_lesson")
            keys += ["description", "turns"]
            path.write_text(json.dumps({k: sess[k] for k in keys}, indent=2) + "\n")
    print(f"\nWROTE {len(ok)} sessions; FAILED {len(bad)}: {bad}")
    conn.close()
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
