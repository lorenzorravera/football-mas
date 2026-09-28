"""
Smoke test for the inference wrapper.

Verifies that:
  1. The trained artefact loads cleanly.
  2. The predictor accepts a feature dict and returns a MatchPrediction.
  3. Probabilities sum to ~1.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from prediction_agent.inference.match_outcome import MatchOutcomePredictor


def synthetic_strong_home() -> dict:
    """A clearly home-favouring scenario for sanity-checking."""
    return {
        "home_elo": 1750.0, "away_elo": 1550.0, "home_elo_diff": 200.0,
        "home_rest_days": 7.0, "away_rest_days": 3.0, "home_rest_advantage": 4.0,
        "home_form_pts_5": 13.0, "away_form_pts_5": 5.0,
        "home_goals_for_5": 12.0, "home_goals_against_5": 3.0,
        "away_goals_for_5": 5.0, "away_goals_against_5": 8.0,
        "home_shots_for_5": 75.0, "home_shots_against_5": 40.0,
        "away_shots_for_5": 45.0, "away_shots_against_5": 65.0,
        "home_xg_for_5": 11.5, "home_xg_against_5": 3.2,
        "away_xg_for_5": 4.8, "away_xg_against_5": 9.1,
        # Path B only — present so the same dict works for both artefacts
        "implied_home_prob": 0.55, "implied_draw_prob": 0.25, "implied_away_prob": 0.20,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    artefacts = [
        ("Path A (no odds)", Path("artefacts/match_outcome_v1.pkl")),
        ("Path B (with odds)", Path("artefacts/match_outcome_v1_with_odds.pkl")),
    ]

    features = synthetic_strong_home()
    any_failed = False

    for label, path in artefacts:
        if not path.exists():
            print(f"[{label}] Missing artefact: {path}")
            continue

        predictor = MatchOutcomePredictor.load(path)
        # Pass the full feature dict — predictor selects what it needs
        # based on its persisted feature_columns list.
        try:
            prediction = predictor.predict_from_features(
                features, home_team="StrongHome", away_team="WeakAway"
            )
        except KeyError as exc:
            print(f"[{label}] FAIL: missing feature {exc}")
            any_failed = True
            continue

        total = (prediction.home_win_prob + prediction.draw_prob
                 + prediction.away_win_prob)
        print(f"[{label}] {prediction.as_dict()}  sum={total:.4f}")

        if not (0.99 < total < 1.01):
            print(f"[{label}] FAIL: probabilities do not sum to 1")
            any_failed = True
        elif prediction.home_win_prob < prediction.away_win_prob:
            print(f"[{label}] WARN: home not favoured in clearly home-favouring scenario")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
