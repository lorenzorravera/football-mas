"""
Cross-league translation model (D4, Q11) — predicts post-move output retention.

Regression target: ga_retention = after_ga_per90 / before_ga_per90 (clipped [0,3]). Predicts
how much of a player's goal+assist output translates after moving between top-5 leagues, from
the before-move profile + the league-strength differential + transfer fee.

Temporal holdout (train on before-seasons < 2023-24, test on 2023-24 moves); final fit on all
moves. Modest sample (~660 moves across 5 leagues) → illustrative, calibration reported honestly.

Artefact: artefacts/cross_league_translation_v1.pkl (GenericPredictor regression bundle).
"""

from __future__ import annotations

import numpy as np
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from prediction_agent.features.cross_league_features import training_frame, FEATURE_COLUMNS
from prediction_agent.tasks.base import save_bundle

VERSION = "v1"
HOLDOUT_FEATURE_SEASON = "2023-2024"
TASK = "cross_league_translation"


def _new_model():
    return Pipeline([
        ("scale", StandardScaler()),
        ("reg", GradientBoostingRegressor(random_state=0)),
    ])


def train(save: bool = True) -> dict:
    df = training_frame().dropna(subset=["ga_retention"]).reset_index(drop=True)
    X = df[FEATURE_COLUMNS]
    y = df["ga_retention"]

    train = df["season"] < HOLDOUT_FEATURE_SEASON
    test = df["season"] == HOLDOUT_FEATURE_SEASON
    metrics = {"task": TASK, "target_type": "regression",
               "n_train": int(train.sum()), "n_test": int(test.sum()),
               "mean_retention": round(float(y.mean()), 3)}

    if train.sum() > 0 and test.sum() > 0:
        model = _new_model()
        model.fit(X[train], y[train])
        pred = model.predict(X[test])
        metrics["holdout_mae"] = round(float(mean_absolute_error(y[test], pred)), 3)
        # Naive baseline: predict the train-mean retention for everyone.
        metrics["baseline_mae"] = round(
            float(mean_absolute_error(y[test], np.full(test.sum(), y[train].mean()))), 3)
        try:
            metrics["holdout_r2"] = round(float(r2_score(y[test], pred)), 3)
        except Exception:
            metrics["holdout_r2"] = None

    final = _new_model()
    final.fit(X, y)
    if save:
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "artefacts" / f"{TASK}_{VERSION}.pkl"
        save_bundle(path, model=final, feature_columns=FEATURE_COLUMNS, classes=None,
                    version=VERSION, task_name=TASK, target_type="regression")
        metrics["artefact"] = str(path.name)
    return metrics


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env", override=True)
    print(train())
