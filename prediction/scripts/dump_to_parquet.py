"""
Dump training data from Aiven to local parquet files.

Run this once per training session (or whenever Aiven data changes).
Subsequent training runs are file-based and reproducible.

Outputs (under --output-dir, default data/raw):
  - matches.parquet                          (all matches + joined xG)
  - matches_no_xg.parquet                    (matches alone, in case xG join fails)
  - teams.parquet, seasons.parquet           (reference)

Usage:
    export DATABASE_URI="postgres://..."
    python3 -m scripts.dump_to_parquet
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from prediction_agent.data.aiven_loader import (
    join_matches_with_xg,
    load_matches,
    load_seasons,
    load_team_match_xg,
    load_teams,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--league", default="ENG-PL")
    parser.add_argument("--seasons", nargs="*", default=None,
                        help="Season strings (e.g. 2020-2021). Default: all loaded seasons.")
    parser.add_argument("--skip-xg", action="store_true",
                        help="Skip xG aggregation (faster; useful for first-pass tests)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Reference tables — small, always pulled
    teams = load_teams()
    teams.to_parquet(args.output_dir / "teams.parquet", index=False)
    logging.info("Wrote teams.parquet (%d rows)", len(teams))

    seasons = load_seasons(args.league)
    seasons.to_parquet(args.output_dir / "seasons.parquet", index=False)
    logging.info("Wrote seasons.parquet (%d rows)", len(seasons))

    # Matches
    matches = load_matches(seasons=args.seasons, league_code=args.league)
    matches.to_parquet(args.output_dir / "matches_no_xg.parquet", index=False)
    logging.info("Wrote matches_no_xg.parquet (%d rows)", len(matches))

    if args.skip_xg:
        logging.info("Skipping xG aggregation (--skip-xg)")
        # Still produce matches.parquet (without xG) for downstream uniformity
        matches.to_parquet(args.output_dir / "matches.parquet", index=False)
        return

    # xG: aggregate from player_match_performance, then join into matches
    logging.info("Aggregating player_match_performance to team-match xG...")
    team_xg = load_team_match_xg(seasons=args.seasons, league_code=args.league)
    enriched = join_matches_with_xg(matches, team_xg)
    enriched.to_parquet(args.output_dir / "matches.parquet", index=False)
    logging.info("Wrote matches.parquet with xG (%d rows, %d columns)",
                 len(enriched), len(enriched.columns))


if __name__ == "__main__":
    main()
