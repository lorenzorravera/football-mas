"""
Cross-league move feature builder (D4, Q11) — performance translation across leagues.

A "cross-league move" is detected directly from consecutive player_season_stats rows whose
league_code changes (season N in league A → season N+1 in league B). This avoids brittle
team-name → league mapping; the transfer fee is merged in from player_transfers when present.

One row per move:
  before-season (league A) per-90 output + profile features, the league-strength differential,
  and the TARGET = post-move output retention.

Target:
  ga_retention = after_ga_per90 / max(before_ga_per90, FLOOR)   (clipped to [0, 3])
                 1.0 ≈ kept output, <1 declined, >1 improved.

League strength is a documented fixed prior (UEFA-coefficient era 2020–2025), surfaced as the
differential `league_strength_delta = to_strength - from_strength`. Negative = stepping up to a
stronger league (expected to suppress output); positive = stepping down.

Coverage: all 5 leagues, 2020-21..2024-25. Cross-league moves are a modest slice (~hundreds),
so the model is illustrative — the value is an honest, calibrated framework for the question.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from prediction_agent.features.player_season_features import load_player_season_frame

# Documented fixed prior: relative top-5 league strength (UEFA-coefficient era 2020–2025).
LEAGUE_STRENGTH = {
    "ENG-PL": 1.00, "ESP-LL": 0.93, "ITA-SA": 0.90, "GER-BL": 0.88, "FRA-L1": 0.82,
}

# before-move feature set (season N, league A).
FEATURE_COLUMNS = [
    "age", "minutes", "start_share",
    "ga_per90", "goals_per90", "assists_per90", "npxg_per90", "xa_per90",
    "key_passes_per90", "shots_per90", "shot_accuracy", "conversion", "xg_overperformance",
    "tackles_per90", "interceptions_per90",
    "market_value_m", "log_market_value",
    "from_strength", "to_strength", "league_strength_delta", "transfer_fee_m",
]

_RETENTION_FLOOR = 0.15   # avoid divide-by-zero blow-ups for near-zero before-output


def _transfer_fees() -> pd.DataFrame:
    """player_id, season → transfer_fee (millions). Season is the move season (N+1)."""
    from prediction_agent.features.player_season_features import _read_sql
    df = _read_sql(
        "SELECT player_id, season, MAX(transfer_fee) AS transfer_fee "
        "FROM player_transfers WHERE transfer_fee IS NOT NULL GROUP BY player_id, season"
    )
    df["transfer_fee_m"] = pd.to_numeric(df["transfer_fee"], errors="coerce") / 1e6
    return df[["player_id", "season", "transfer_fee_m"]]


def build_cross_league_moves() -> pd.DataFrame:
    """One row per detected cross-league move, with before-features + retention target."""
    df = load_player_season_frame(league="all").sort_values(
        ["player_id", "season"]).reset_index(drop=True)

    g = df.groupby("player_id")
    df["next_league"] = g["league_code"].shift(-1)
    df["next_ga_per90"] = g["ga_per90"].shift(-1)
    df["next_minutes"] = g["minutes"].shift(-1)
    df["next_season"] = g["season"].shift(-1)
    df["next_team"] = g["team_name"].shift(-1)

    moves = df[
        df["next_league"].notna()
        & (df["next_league"] != df["league_code"])
        & (df["minutes"] >= 450)             # meaningful before-sample
        & (df["next_minutes"] >= 270)        # actually featured after the move
    ].copy()

    moves["from_strength"] = moves["league_code"].map(LEAGUE_STRENGTH).fillna(0.85)
    moves["to_strength"] = moves["next_league"].map(LEAGUE_STRENGTH).fillna(0.85)
    moves["league_strength_delta"] = moves["to_strength"] - moves["from_strength"]

    fees = _transfer_fees()
    moves = moves.merge(
        fees.rename(columns={"season": "next_season"}),
        on=["player_id", "next_season"], how="left",
    )
    moves["transfer_fee_m"] = pd.to_numeric(moves["transfer_fee_m"], errors="coerce").fillna(0.0)

    moves["ga_retention"] = (
        moves["next_ga_per90"] / moves["ga_per90"].clip(lower=_RETENTION_FLOOR)
    ).clip(0, 3)

    for c in FEATURE_COLUMNS:
        moves[c] = pd.to_numeric(moves[c], errors="coerce")
    moves[FEATURE_COLUMNS] = moves[FEATURE_COLUMNS].fillna(
        moves[FEATURE_COLUMNS].median(numeric_only=True))
    return moves.reset_index(drop=True)


def training_frame() -> pd.DataFrame:
    return build_cross_league_moves()


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    env = Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env"
    if env.exists():
        load_dotenv(env, override=True)
    m = build_cross_league_moves()
    print("cross-league moves:", len(m))
    cols = ["player_name", "season", "league_code", "next_league", "ga_per90",
            "next_ga_per90", "league_strength_delta", "ga_retention"]
    print(m.sort_values("transfer_fee_m", ascending=False)[cols].head(10).to_string(index=False))
