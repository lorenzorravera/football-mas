"""
In-game event-state feature builder (D4, Q9) — how mid-game events shift the result.

One row per ENG-PL match with the in-game STATE features that the literature shows move the
final result, plus the final result target:

  fg_home, fg_away          first goal scored by home / away (0/0 = goalless-so-far baseline)
  fg_early                  that first goal came in the first 15 minutes
  fg_first_half             that first goal came before half-time
  ht_lead_home, ht_lead_away   team leading at half-time (0/0 = level)
  red_home, red_away        team received ≥1 red card in the match

First goal (side + minute) is extracted from match_events (Goal / OwnGoal, own goals credited to
the opponent); half-time lead and red-card flags come from the matches table. Target = ft_result
(H/D/A). The model trained on this (models/event_impact.py) yields, for any scenario, the result
distribution and its delta vs the neutral (all-zero) baseline.

Coverage: ENG-PL, 2020-21..2024-25 (~1900 matches).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from prediction_agent.features.player_season_features import _read_sql

FEATURE_COLUMNS = [
    "fg_home", "fg_away", "fg_early", "fg_first_half",
    "ht_lead_home", "ht_lead_away", "red_home", "red_away",
]

# match_events.team_id is NULL — the scoring side is carried only as the `team` NAME, so we
# resolve home/away by joining the home/away team NAMES from the teams table.
_MATCHES_Q = """
    SELECT m.game_id, ht.team_name AS home_team_name, at.team_name AS away_team_name,
        m.ht_home_score, m.ht_away_score, m.ft_result,
        m.home_red_cards, m.away_red_cards
    FROM matches m
    JOIN seasons s ON m.season_id = s.season_id
    JOIN competitions c ON s.competition_id = c.competition_id
    JOIN teams ht ON m.home_team_id = ht.team_id
    JOIN teams at ON m.away_team_id = at.team_id
    WHERE c.league_code = 'ENG-PL'
"""

# Earliest goal per game: minute, scoring team NAME, own-goal flag.
_FIRST_GOAL_Q = """
    SELECT DISTINCT ON (game_id)
        game_id, minute, team AS fg_team, (type = 'OwnGoal') AS own_goal
    FROM match_events_eng_pl
    WHERE is_goal = true OR type = 'OwnGoal'
    ORDER BY game_id, minute, second
"""


def build_event_frame() -> pd.DataFrame:
    m = _read_sql(_MATCHES_Q)
    fg = _read_sql(_FIRST_GOAL_Q)

    df = m.merge(fg, on="game_id", how="left")

    # Resolve which side scored first by NAME. Own goal counts for the opponent.
    scored_home_team = df["fg_team"].astype(str).str.lower() == df["home_team_name"].str.lower()
    # for a normal goal: scorer side is the team; for own goal: the OTHER side scores
    first_is_home = np.where(df["own_goal"].fillna(False),
                             ~scored_home_team, scored_home_team)
    has_fg = df["minute"].notna()
    df["fg_home"] = (has_fg & first_is_home).astype(int)
    df["fg_away"] = (has_fg & ~first_is_home).astype(int)
    df["fg_early"] = (has_fg & (df["minute"] <= 15)).astype(int)
    df["fg_first_half"] = (has_fg & (df["minute"] <= 45)).astype(int)

    ht_h = pd.to_numeric(df["ht_home_score"], errors="coerce")
    ht_a = pd.to_numeric(df["ht_away_score"], errors="coerce")
    df["ht_lead_home"] = (ht_h > ht_a).astype(int)
    df["ht_lead_away"] = (ht_a > ht_h).astype(int)
    df["red_home"] = (pd.to_numeric(df["home_red_cards"], errors="coerce").fillna(0) > 0).astype(int)
    df["red_away"] = (pd.to_numeric(df["away_red_cards"], errors="coerce").fillna(0) > 0).astype(int)

    df = df[df["ft_result"].isin(["H", "D", "A"])].reset_index(drop=True)
    return df


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    env = Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env"
    if env.exists():
        load_dotenv(env, override=True)
    df = build_event_frame()
    print("matches:", len(df))
    print("base result rates:", df["ft_result"].value_counts(normalize=True).round(3).to_dict())
    print("P(H | home scores first):",
          round(df[df.fg_home == 1]["ft_result"].eq("H").mean(), 3))
    print("P(H | home leads at HT):",
          round(df[df.ht_lead_home == 1]["ft_result"].eq("H").mean(), 3))
    print("P(H | away red card):",
          round(df[df.red_away == 1]["ft_result"].eq("H").mean(), 3))
