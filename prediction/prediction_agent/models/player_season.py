"""
Player-season models (D4) — the model-backed half of the player suite.

Tasks trained here:
  player_decline  (Q7c) classification: will a player's next-season output drop AND minutes
                        fall? (decline_flag). Drives the "most likely to decline" forecast and
                        the risk component of the player_value index.

The computed player tasks (player_value Q7a/b, player_team_impact Q6, transfer_fit Q12) live in
tasks/__init__.py and reuse the same feature builder / the season_class team model — no training.

Data: ENG-PL, 2020-21..2024-25, players with ≥450 minutes and a known next season
(~1.2k rows). Single league + noisy human target → honestly illustrative, like the team-season
suite. Temporal holdout (train < 2023-24, test on 2023-24→next); final fit on all rows.

Artefacts: artefacts/player_<task>_v1.pkl  (GenericPredictor bundle).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, log_loss

from prediction_agent.features.player_season_features import training_frame, FEATURE_COLUMNS
from prediction_agent.tasks.base import save_bundle

VERSION = "v1"
HOLDOUT_FEATURE_SEASON = "2023-2024"   # predict 2024-2025; train on earlier transitions

# task_key -> (target column, target_type)
TASKS = {
    "player_decline": ("decline_flag", "classification"),
}


def _multiclass_brier(y_true, proba, classes) -> float:
    idx = {c: i for i, c in enumerate(classes)}
    oh = np.zeros_like(proba)
    for r, y in enumerate(y_true):
        oh[r, idx[y]] = 1.0
    return float(np.mean(np.sum((proba - oh) ** 2, axis=1)))


def _new_model(target_type: str):
    # GB classifier handles the non-linear age/minutes/output interactions that drive decline,
    # then we keep an LR-comparable, regularised default for stability on the small sample.
    return Pipeline([
        ("scale", StandardScaler()),
        ("clf", GradientBoostingClassifier(random_state=0)),
    ])


def train_player_task(task_key: str, save: bool = True) -> dict:
    if task_key not in TASKS:
        raise ValueError(f"unknown player task {task_key!r}; have {list(TASKS)}")
    target_col, target_type = TASKS[task_key]

    df = training_frame()
    df = df.dropna(subset=[target_col]).reset_index(drop=True)
    df[target_col] = df[target_col].astype(int)
    X = df[FEATURE_COLUMNS]
    y = df[target_col]

    train = df["season"] < HOLDOUT_FEATURE_SEASON
    test = df["season"] == HOLDOUT_FEATURE_SEASON

    metrics = {"task": task_key, "target_type": target_type,
               "n_train": int(train.sum()), "n_test": int(test.sum()),
               "base_rate": round(float(y.mean()), 3)}

    if test.sum() > 0 and train.sum() > 0:
        model = _new_model(target_type)
        model.fit(X[train], y[train])
        classes = list(model.named_steps["clf"].classes_)
        proba = model.predict_proba(X[test])
        pred = model.predict(X[test])
        metrics["holdout_accuracy"] = round(float(accuracy_score(y[test], pred)), 3)
        try:
            metrics["holdout_logloss"] = round(float(log_loss(y[test], proba, labels=classes)), 3)
        except Exception:
            metrics["holdout_logloss"] = None
        metrics["holdout_brier"] = round(_multiclass_brier(list(y[test]), proba, classes), 3)

    final = _new_model(target_type)
    final.fit(X, y)
    classes = list(final.named_steps["clf"].classes_)

    if save:
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "artefacts" / f"{task_key}_{VERSION}.pkl"
        save_bundle(path, model=final, feature_columns=FEATURE_COLUMNS, classes=classes,
                    version=VERSION, task_name=task_key, target_type=target_type)
        metrics["artefact"] = str(path.name)
    return metrics


def train_all(save: bool = True) -> list[dict]:
    return [train_player_task(k, save=save) for k in TASKS]


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env", override=True)
    for m in train_all():
        print(m)
