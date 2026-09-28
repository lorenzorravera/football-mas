"""
Team-season models (D1) — Q1–Q4, trained with one generic routine.

Tasks:
  season_class       (Q1) classification: next-season bucket (top4/european/mid/relegation)
  position_movement  (Q2) classification: ≥5-place swing next season (up5/down5/stable)
  turnaround         (Q3) regression:     next-season points change (Δpoints), driven by
                                          over/under-performance (process vs outcome features)
  home_away_dependency (Q4) is a COMPUTED index task (no training) — see tasks/__init__.py.

Data is small (~73 N→N+1 transitions, ENG-PL only) so models are illustrative; we use a
temporal holdout (train on early seasons, test on the latest) and report calibration
(multiclass Brier, log-loss) honestly. Final artefacts are fit on all trainable rows.

Artefacts: artefacts/team_<task>_v1.pkl  (GenericPredictor bundle).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, r2_score

from prediction_agent.features.team_season_features import training_frame, FEATURE_COLUMNS
from prediction_agent.tasks.base import save_bundle

VERSION = "v1"
HOLDOUT_FEATURE_SEASON = "2023-2024"   # predict 2024-2025; train on earlier transitions

# task_key -> (target column, target_type)
TASKS = {
    "season_class":      ("season_class",   "classification"),
    "position_movement": ("movement_class", "classification"),
    "turnaround":        ("delta_points",   "regression"),
}


def _multiclass_brier(y_true, proba, classes) -> float:
    idx = {c: i for i, c in enumerate(classes)}
    oh = np.zeros_like(proba)
    for r, y in enumerate(y_true):
        oh[r, idx[y]] = 1.0
    return float(np.mean(np.sum((proba - oh) ** 2, axis=1)))


def _new_model(target_type: str):
    if target_type == "classification":
        return Pipeline([
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ])
    return Pipeline([
        ("scale", StandardScaler()),
        ("reg", GradientBoostingRegressor(random_state=0)),
    ])


def train_team_season_task(task_key: str, save: bool = True) -> dict:
    if task_key not in TASKS:
        raise ValueError(f"unknown team-season task {task_key!r}; have {list(TASKS)}")
    target_col, target_type = TASKS[task_key]

    df = training_frame().dropna(subset=[target_col]).reset_index(drop=True)
    X = df[FEATURE_COLUMNS]
    y = df[target_col]

    train = df["season"] < HOLDOUT_FEATURE_SEASON
    test = df["season"] == HOLDOUT_FEATURE_SEASON

    metrics = {"task": task_key, "target_type": target_type,
               "n_train": int(train.sum()), "n_test": int(test.sum())}

    model = _new_model(target_type)
    if test.sum() > 0 and train.sum() > 0:
        model.fit(X[train], y[train])
        if target_type == "classification":
            classes = list(model.named_steps["clf"].classes_)
            proba = model.predict_proba(X[test])
            pred = model.predict(X[test])
            metrics["holdout_accuracy"] = round(float(accuracy_score(y[test], pred)), 3)
            try:
                metrics["holdout_logloss"] = round(
                    float(log_loss(y[test], proba, labels=classes)), 3)
            except Exception:
                metrics["holdout_logloss"] = None
            metrics["holdout_brier"] = round(_multiclass_brier(list(y[test]), proba, classes), 3)
        else:
            pred = model.predict(X[test])
            metrics["holdout_mae"] = round(float(mean_absolute_error(y[test], pred)), 3)
            try:
                metrics["holdout_r2"] = round(float(r2_score(y[test], pred)), 3)
            except Exception:
                metrics["holdout_r2"] = None

    # Final fit on ALL trainable rows for deployment.
    final = _new_model(target_type)
    final.fit(X, y)
    classes = list(final.named_steps["clf"].classes_) if target_type == "classification" else None

    if save:
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "artefacts" / f"team_{task_key}_{VERSION}.pkl"
        save_bundle(path, model=final, feature_columns=FEATURE_COLUMNS, classes=classes,
                    version=VERSION, task_name=task_key, target_type=target_type)
        metrics["artefact"] = str(path.name)
    return metrics


def train_all(save: bool = True) -> list[dict]:
    return [train_team_season_task(k, save=save) for k in TASKS]


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env", override=True)
    for m in train_all():
        print(m)
