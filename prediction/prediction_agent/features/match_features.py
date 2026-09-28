"""
Feature engineering for match outcome prediction.

Input: matches DataFrame from aiven_loader.load_matches() joined with
       team-match xG from aiven_loader.join_matches_with_xg().

Design principles (unchanged from v0):
  1. No data leakage. Every feature for match M uses ONLY information
     available before M's kickoff. Rolling windows are strictly causal.
  2. Single pass over chronologically sorted matches, accumulating
     per-team state.

What's new vs v0:
  - Uses Aiven schema column names (home_team_id, away_team_id, home_score,
    away_score, ft_result, home_shots, away_shots, home_shots_on_target,
    away_shots_on_target).
  - xG-based features when team-match xG aggregation is available:
    rolling xG for/against (5-match).
  - Two feature sets exposed:
      FEATURE_COLUMNS_NO_ODDS  — for Path A (paper-honest, no market signal)
      FEATURE_COLUMNS_WITH_ODDS — for Path B (ablation with bookmaker odds)
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


# ----- Elo -----

ELO_K = 20.0
ELO_HOME_ADV = 65.0
ELO_INIT = 1500.0


def _elo_expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _elo_update(home_elo: float, away_elo: float, home_goals: int, away_goals: int
                ) -> tuple[float, float]:
    if home_goals > away_goals:
        home_score, away_score = 1.0, 0.0
    elif home_goals < away_goals:
        home_score, away_score = 0.0, 1.0
    else:
        home_score = away_score = 0.5
    expected_home = _elo_expected(home_elo + ELO_HOME_ADV, away_elo)
    goal_diff = abs(home_goals - away_goals)
    mov_mult = np.log(max(goal_diff, 1) + 1)
    delta = ELO_K * mov_mult * (home_score - expected_home)
    return home_elo + delta, away_elo - delta


# ----- Rolling state per team -----

@dataclass
class _TeamState:
    elo: float = ELO_INIT
    last_match_date: Optional[pd.Timestamp] = None
    # Each recent entry: (points, goals_for, goals_against,
    #                     shots_for, shots_against, xg_for, xg_against)
    recent: deque = field(default_factory=lambda: deque(maxlen=5))

    def rest_days(self, current_date: pd.Timestamp) -> float:
        if self.last_match_date is None:
            return 14.0
        return (current_date - self.last_match_date).days

    def form_features(self) -> dict[str, float]:
        if not self.recent:
            return {
                "form_pts_5": 0.0,
                "goals_for_5": 0.0, "goals_against_5": 0.0,
                "shots_for_5": 0.0, "shots_against_5": 0.0,
                "xg_for_5": 0.0, "xg_against_5": 0.0,
            }
        arr = np.array(self.recent, dtype=float)
        return {
            "form_pts_5": float(arr[:, 0].sum()),
            "goals_for_5": float(arr[:, 1].sum()),
            "goals_against_5": float(arr[:, 2].sum()),
            "shots_for_5": float(arr[:, 3].sum()),
            "shots_against_5": float(arr[:, 4].sum()),
            "xg_for_5": float(arr[:, 5].sum()),
            "xg_against_5": float(arr[:, 6].sum()),
        }


def build_match_features(matches: pd.DataFrame) -> pd.DataFrame:
    """
    Given matches (with optional xG columns from join_matches_with_xg),
    produce causal features.
    """
    df = matches.copy()
    df["match_date"] = pd.to_datetime(df["match_date"])
    df = df.sort_values(["match_date", "game_id"]).reset_index(drop=True)

    has_xg = "home_team_xg" in df.columns and "away_team_xg" in df.columns
    has_odds = all(c in df.columns for c in ("avg_home_odds", "avg_draw_odds", "avg_away_odds"))

    states: dict[int, _TeamState] = defaultdict(_TeamState)
    rows: list[dict] = []

    for _, m in df.iterrows():
        home_id, away_id = int(m["home_team_id"]), int(m["away_team_id"])
        home_state, away_state = states[home_id], states[away_id]
        match_date = m["match_date"]

        home_feats = home_state.form_features()
        away_feats = away_state.form_features()

        row = {
            "game_id": int(m["game_id"]),
            "season": m["season"],
            "match_date": match_date,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_elo": home_state.elo,
            "away_elo": away_state.elo,
            "home_elo_diff": home_state.elo - away_state.elo,
            "home_rest_days": home_state.rest_days(match_date),
            "away_rest_days": away_state.rest_days(match_date),
            "home_rest_advantage": (
                home_state.rest_days(match_date) - away_state.rest_days(match_date)
            ),
            **{f"home_{k}": v for k, v in home_feats.items()},
            **{f"away_{k}": v for k, v in away_feats.items()},
            "home_score": m["home_score"],
            "away_score": m["away_score"],
            "ft_result": m["ft_result"],
        }
        if has_odds:
            # Convert decimal odds to probabilities, then normalize to remove
            # the bookmaker's overround (vig). Raw 1/odds sums to ~1.05-1.10;
            # we want three features that sum to 1.0 representing the
            # bookmaker's "true" probability after stripping the margin.
            ho = m["avg_home_odds"]
            do = m["avg_draw_odds"]
            ao = m["avg_away_odds"]
            if pd.notna(ho) and pd.notna(do) and pd.notna(ao) and ho > 0 and do > 0 and ao > 0:
                p_h, p_d, p_a = 1.0 / float(ho), 1.0 / float(do), 1.0 / float(ao)
                total = p_h + p_d + p_a
                row["implied_home_prob"] = p_h / total
                row["implied_draw_prob"] = p_d / total
                row["implied_away_prob"] = p_a / total
            else:
                row["implied_home_prob"] = np.nan
                row["implied_draw_prob"] = np.nan
                row["implied_away_prob"] = np.nan
        rows.append(row)

        # ----- Post-match state update -----
        fthg = int(m["home_score"])
        ftag = int(m["away_score"])
        hs = float(m.get("home_shots", 0) or 0)
        a_s = float(m.get("away_shots", 0) or 0)
        if has_xg:
            hxg = float(m.get("home_team_xg", 0) or 0)
            axg = float(m.get("away_team_xg", 0) or 0)
        else:
            hxg = axg = 0.0

        home_pts = 3 if fthg > ftag else (1 if fthg == ftag else 0)
        away_pts = 3 if ftag > fthg else (1 if fthg == ftag else 0)

        home_state.recent.append((home_pts, fthg, ftag, hs, a_s, hxg, axg))
        away_state.recent.append((away_pts, ftag, fthg, a_s, hs, axg, hxg))

        new_home_elo, new_away_elo = _elo_update(
            home_state.elo, away_state.elo, fthg, ftag
        )
        home_state.elo = new_home_elo
        away_state.elo = new_away_elo
        home_state.last_match_date = match_date
        away_state.last_match_date = match_date

    out = pd.DataFrame(rows)

    # Drop warm-up matches where a team has no recorded form.
    if has_xg:
        warmup_mask = (
            (out["home_form_pts_5"] == 0) & (out["home_shots_for_5"] == 0) &
            (out["home_xg_for_5"] == 0)
        ) | (
            (out["away_form_pts_5"] == 0) & (out["away_shots_for_5"] == 0) &
            (out["away_xg_for_5"] == 0)
        )
    else:
        warmup_mask = (
            (out["home_form_pts_5"] == 0) & (out["home_shots_for_5"] == 0)
        ) | (
            (out["away_form_pts_5"] == 0) & (out["away_shots_for_5"] == 0)
        )
    out = out[~warmup_mask].reset_index(drop=True)
    return out


# ----- Feature column lists -----

FEATURE_COLUMNS_NO_ODDS: list[str] = [
    "home_elo", "away_elo", "home_elo_diff",
    "home_rest_days", "away_rest_days", "home_rest_advantage",
    "home_form_pts_5", "away_form_pts_5",
    "home_goals_for_5", "home_goals_against_5",
    "away_goals_for_5", "away_goals_against_5",
    "home_shots_for_5", "home_shots_against_5",
    "away_shots_for_5", "away_shots_against_5",
    "home_xg_for_5", "home_xg_against_5",
    "away_xg_for_5", "away_xg_against_5",
]

FEATURE_COLUMNS_WITH_ODDS: list[str] = FEATURE_COLUMNS_NO_ODDS + [
    "implied_home_prob", "implied_draw_prob", "implied_away_prob",
]
