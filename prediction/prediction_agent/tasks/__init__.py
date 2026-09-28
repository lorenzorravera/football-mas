"""
Task registry population (D0/D1). Importing this package registers every prediction task,
so the agent dispatcher and training CLI can resolve them by `prediction_type`.

Add a new forecasting capability = add a TaskSpec here (+ a feature builder/model). No
graph or agent changes required.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .registry import TaskSpec, register, get, all_tasks, task_names  # noqa: F401
from .base import GenericPrediction


# ---------------------------------------------------------------------------
# Q4 — home/away dependency: a COMPUTED index task (no training).
# ---------------------------------------------------------------------------

def _home_away_dependency(entity: str, season: Optional[str] = None) -> GenericPrediction:
    """Home-reliance index = home_points / (home_points + away_points) for the team's
    most recent season (or a given season). Flags teams over-reliant on home form."""
    from prediction_agent.features.team_season_features import load_team_season_frame
    df = load_team_season_frame()
    sub = df[df["team"].str.lower() == (entity or "").strip().lower()]
    if season:
        sub = sub[sub["season"] == season]
    if sub.empty:
        raise ValueError(f"no team-season row for {entity!r}"
                         + (f" in {season}" if season else ""))
    row = sub.sort_values("season").iloc[-1]
    idx = float(row["home_reliance_index"])
    # League-typical home share is ~0.60; flag clear over-reliance.
    label = "over_reliant_on_home" if idx >= 0.65 else "balanced"
    return GenericPrediction(
        task_name="home_away_dependency", entity=row["team"], target_type="index",
        probabilities={"home_reliance_index": idx},  # numeric index surfaced here
        prediction=label, confidence=float("nan"), model_version="v1",
    )


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

register(TaskSpec(
    name="season_class", description="Forecast a team's next-season class "
    "(top4 / european / mid_table / relegation).",
    granularity="team_season", target_type="classification",
    artefact="team_season_class_v1.pkl",
    aliases=("prediction_season_class", "season_outcome", "relegation_risk", "title_contender"),
    intents=("Will Arsenal finish top four next season?",
             "Who is most likely to be relegated next season?"),
))

register(TaskSpec(
    name="position_movement", description="Forecast whether a team moves ≥5 league "
    "positions next season (up5 / down5 / stable).",
    granularity="team_season", target_type="classification",
    artefact="team_position_movement_v1.pkl",
    aliases=("prediction_movement", "league_movement"),
    intents=("Which teams will improve the most next season?",
             "Is Chelsea likely to climb the table next season?"),
))

register(TaskSpec(
    name="turnaround", description="Forecast a team's next-season points change "
    "(Δpoints) from over/under-performance signals.",
    granularity="team_season", target_type="regression",
    artefact="team_turnaround_v1.pkl",
    aliases=("prediction_turnaround", "points_change"),
    intents=("Which overperforming teams are likely to decline next season?",),
))

register(TaskSpec(
    name="home_away_dependency", description="Index of a team's reliance on home form "
    "(home_points share); flags teams vulnerable away from home.",
    granularity="team_season", target_type="index",
    compute_fn=_home_away_dependency,
    aliases=("prediction_home_dependency", "home_reliance"),
    intents=("Which teams rely too much on home form?",),
))

# The existing match-outcome model — registered for discoverability; the agent dispatches
# 'match' granularity through the existing MatchOutcomePredictor path.
register(TaskSpec(
    name="match_outcome", description="Forecast a single fixture (home/draw/away).",
    granularity="match", target_type="classification", artefact="match_outcome_v1.pkl",
    aliases=("prediction_match", "match_result"),
    intents=("Predict Arsenal vs Chelsea", "Will Liverpool beat Man City?"),
))


# ---------------------------------------------------------------------------
# D4 — player suite, advanced team tasks, in-game events, explanation.
# Computed tasks point compute_fn at tasks/computed.py (rich (df, meta) handlers); the
# dispatcher routes them by granularity. Model-backed tasks carry an artefact.
# ---------------------------------------------------------------------------
from . import computed as _computed  # noqa: E402

# Q7 — player value detection (value-for-money + risk) — computed index.
register(TaskSpec(
    name="player_value", description="Rank players by performance impact relative to market "
    "value, age and availability; flag high-upside-high-risk and decline-prone players.",
    granularity="player_season", target_type="index", compute_fn=_computed.player_value,
    aliases=("prediction_player_value", "player_value_detection", "value_for_money", "bargain_players"),
    intents=("Which players are the best value for money?",
             "Which attractive players carry high injury/decline risk?"),
))

# Q7c — player decline — model-backed classification.
register(TaskSpec(
    name="player_decline", description="Forecast which players are most likely to decline next "
    "season (output drop + falling minutes) from age, minutes, injuries and recent output.",
    granularity="player_season", target_type="classification", artefact="player_decline_v1.pkl",
    aliases=("prediction_player_decline", "decline_risk"),
    intents=("Which players are most likely to decline next season?",
             "Is Salah likely to decline next season?"),
))

# Q6 — player impact on team class — computed counterfactual on season_class.
register(TaskSpec(
    name="player_team_impact", description="How much a specific player changes his team's "
    "next-season class probability (counterfactual removal of his attacking output).",
    granularity="player_season", target_type="index", compute_fn=_computed.player_team_impact,
    aliases=("prediction_player_impact", "player_class_impact"),
    intents=("How much does Salah improve Liverpool's top-four chances?",),
))

# Q12 — team-context fit after transfer — computed style-fit.
register(TaskSpec(
    name="transfer_fit", description="How well a player's profile fits a destination team's "
    "style vs his current club.",
    granularity="player_transfer", target_type="index", compute_fn=_computed.transfer_fit,
    aliases=("prediction_transfer_fit", "team_fit"),
    intents=("How well would Mbappé fit at Arsenal?",),
))

# Q11 — cross-league performance translation — model-backed regression (inference via computed).
register(TaskSpec(
    name="cross_league_translation", description="Predict how much of a player's output "
    "translates after moving between top-5 leagues (output retention).",
    granularity="player_transfer", target_type="regression",
    artefact="cross_league_translation_v1.pkl", compute_fn=_computed.cross_league_forecast,
    aliases=("prediction_cross_league", "league_translation"),
    intents=("How would Mbappé perform if he moved to the Premier League?",
             "Will Wirtz maintain his output in England?"),
))

# Q5 — squad availability impact — computed index.
register(TaskSpec(
    name="squad_availability", description="How much injuries/absences depress a team's expected "
    "points (minutes-weighted availability index).",
    granularity="team_season", target_type="index", compute_fn=_computed.squad_availability,
    aliases=("prediction_squad_availability", "injury_impact", "availability_impact"),
    intents=("Which team is most hurt by injuries this season?",
             "How many points have injuries cost Tottenham?"),
))

# Q10 — stakeholder (strategic) value — computed index.
register(TaskSpec(
    name="stakeholder_value", description="Club strategic-value index from sporting success, "
    "attendance, squad value and player development.",
    granularity="team_season", target_type="index", compute_fn=_computed.stakeholder_value,
    aliases=("prediction_stakeholder_value", "club_value", "strategic_value"),
    intents=("Which clubs have the highest strategic value?",),
))

# Q9 — in-game event impact — computed lookup over the event table.
register(TaskSpec(
    name="event_impact", description="How much an early goal, half-time lead or red card shifts "
    "the final result probabilities (empirical conditional distribution).",
    granularity="match_event", target_type="index", compute_fn=_computed.event_impact_scenario,
    aliases=("prediction_event_impact", "in_game_impact"),
    intents=("How much does an early goal change the result?",
             "What happens to win probability after a red card?"),
))

# Q14 — model explanation — a meta capability (handled directly by the dispatcher, which attaches
# top driving factors + confidence to any model-backed forecast).
register(TaskSpec(
    name="explain", description="Explain a forecast: the top driving factors and the model's "
    "confidence.",
    granularity="meta", target_type="index",
    aliases=("prediction_explain", "why", "explanation", "drivers"),
    intents=("Why did the model predict that?", "What factors drive this forecast?"),
))
