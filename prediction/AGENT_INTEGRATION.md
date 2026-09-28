# Agent Integration Notes

This file documents how `prediction_agent/` plugs into the existing
LangGraph pipeline at `ethan/agent-v4/`. It is NOT a code file — it's
a checklist for the integration sprint (Week 1 of the phased plan).

## The integration seam

The agent's `prediction_agent` node (sibling to `data_analyst`) imports
`MatchOutcomePredictor` from `prediction_agent.inference.match_outcome`
and calls it during the `predict` step of its internal flow.

```python
# In ethan/agent-v4/agent/nodes/prediction.py (to be created)

from prediction_agent.inference.match_outcome import MatchOutcomePredictor

# Load once at module import (or via dependency injection at graph build)
_match_predictor: MatchOutcomePredictor | None = None

def _get_match_predictor() -> MatchOutcomePredictor:
    global _match_predictor
    if _match_predictor is None:
        _match_predictor = MatchOutcomePredictor.load("artefacts/match_outcome_v1.pkl")
    return _match_predictor


def prediction_node(state: AgentState) -> AgentState:
    """LangGraph node: route to the right predictor based on intent."""
    intent = state["intent"]  # set by the router

    if intent == "prediction_match":
        # Build features from current team state via SQL queries.
        # This is the only LLM-touching step: the LLM extracts entities
        # (home team, away team, match date) from the user query.
        features = build_match_features_for_query(state)
        prediction = _get_match_predictor().predict_from_features(
            features,
            home_team=state["home_team"],
            away_team=state["away_team"],
        )
        state["prediction_result"] = prediction.as_dict()
    elif intent == "prediction_player":
        ...  # Phase 2 of Week 2
    elif intent == "prediction_transfer":
        ...  # cohort retrieval; Phase 2 of Week 2
    return state
```

## Feature retrieval at inference time

`build_match_features_for_query` is the runtime mirror of the training
feature pipeline. It must produce features in the SAME schema as
`features/match_features.py` does at training time. Suggested approach:

1. Maintain a `team_state` cache (in-memory or in a Postgres table)
   that's updated after every completed match.
2. At inference, query the cache for both teams' current Elo, rolling
   form, last-match-date.
3. Compose into a feature dict matching `FEATURE_COLUMNS`.

A cleaner alternative for v1: rerun `build_match_features` on the full
match history including the most recent gameweek, then take the row
corresponding to the upcoming fixture. Slower (~1s per query) but
guarantees train/inference parity.

## Where the artefact lives at runtime

The agent's Docker image (or Railway deployment) needs `artefacts/match_outcome_v1.pkl`
on disk. Options:

- **Pull at startup** from GitHub Releases via `gh release download` in the Dockerfile.
- **Bake into the image** by copying during `docker build`.

Recommend the first: smaller images, easier model updates without rebuild.

## Eval Agent integration

Per the project memory, the Eval Agent is rule-based and consistency-checks
numbers in the synthesizer's output against `data_result` from the SQL path.
For predictions, extend it to:

1. Check that prediction probabilities sum to 1.0 ± 0.01.
2. Check that the synthesizer's natural-language description matches the
   highest-probability outcome.
3. Post-match: compare predicted probabilities to realised outcomes;
   write deltas to `correction_memory` with `source="live"` and
   `intent="prediction_match"` for the prediction agent to retrieve later.

## Eval Runner integration

Add prediction queries to `eval_runner.py`'s golden set with
`source="golden_test"` tagging (per the existing convention) so they
don't pollute `correction_memory`. Example queries:

- "Predict the outcome of Arsenal vs Chelsea on 2024-03-15"
   (ground truth: known historical result; use only pre-2024-03-15 data)
- "What's the probability of a draw between Man City and Liverpool
   given current form?" (probability calibration check)
