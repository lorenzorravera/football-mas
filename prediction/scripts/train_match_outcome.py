"""
Train the match outcome ensemble.

Trains TWO models for ablation:
  - match_outcome_v1.pkl           (Path A: no odds, paper-honest)
  - match_outcome_v1_with_odds.pkl (Path B: with odds as feature)

Both use the same architecture (LR + XGBoost + LightGBM stacked, isotonic
calibration); they differ only in feature set.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from prediction_agent.features.match_features import (
    FEATURE_COLUMNS_NO_ODDS,
    FEATURE_COLUMNS_WITH_ODDS,
    build_match_features,
)
from prediction_agent.models.match_outcome import save, train_match_outcome


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, default=Path("data/raw/matches.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("artefacts"))
    parser.add_argument("--holdout-seasons", nargs="+", default=["2024-2025"])
    parser.add_argument("--skip-odds", action="store_true",
                        help="Train only Path A")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.matches.exists():
        raise SystemExit(f"Missing {args.matches}. Run dump_to_parquet first.")

    matches = pd.read_parquet(args.matches)
    logging.info("Loaded %d matches", len(matches))

    features = build_match_features(matches)
    logging.info("Built %d feature rows (after warmup drop)", len(features))

    logging.info("=== Training Path A (no odds) ===")
    result_a = train_match_outcome(
        features,
        feature_columns=FEATURE_COLUMNS_NO_ODDS,
        target_column="ft_result",
        holdout_seasons=tuple(args.holdout_seasons),
    )
    save(result_a, str(args.output_dir / "match_outcome_v1.pkl"))
    logging.info("Path A metrics: %s", result_a.metrics)

    if args.skip_odds:
        return

    if not all(c in features.columns for c in
               ("implied_home_prob", "implied_draw_prob", "implied_away_prob")):
        logging.warning("Odds-derived features missing; skipping Path B")
        return

    logging.info("=== Training Path B (with odds) ===")
    result_b = train_match_outcome(
        features,
        feature_columns=FEATURE_COLUMNS_WITH_ODDS,
        target_column="ft_result",
        holdout_seasons=tuple(args.holdout_seasons),
    )
    save(result_b, str(args.output_dir / "match_outcome_v1_with_odds.pkl"))
    logging.info("Path B metrics: %s", result_b.metrics)

    logging.info("=== Comparison ===")
    logging.info("Path A (no odds):    acc=%.3f  brier=%.4f  log_loss=%.4f",
                 result_a.metrics.get("accuracy", 0),
                 result_a.metrics.get("brier", 0),
                 result_a.metrics.get("log_loss", 0))
    logging.info("Path B (with odds):  acc=%.3f  brier=%.4f  log_loss=%.4f",
                 result_b.metrics.get("accuracy", 0),
                 result_b.metrics.get("brier", 0),
                 result_b.metrics.get("log_loss", 0))


if __name__ == "__main__":
    main()
