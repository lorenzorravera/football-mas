"""
Match-outcome model (H/D/A) — training + persistence.

This fills the D0 reproducibility gap: the shipped artefacts
(`match_outcome_v1.pkl` / `..._with_odds.pkl`) were previously NOT regenerable
from source. `train_match_outcome()` + `save()` here reconstruct the exact
architecture those bundles carry, so a fresh `python scripts/train_match_outcome.py`
reproduces an equivalent model.

Architecture (recovered from the shipped artefact):
  CalibratedClassifierCV(                       # isotonic calibration, cv=3
      estimator=StackingClassifier(             # cv=5, stack_method=predict_proba
          estimators=[
              ('lr',   Pipeline[StandardScaler, LogisticRegression(max_iter=2000)]),
              ('xgb',  XGBClassifier(...)),
              ('lgbm', LGBMClassifier(...)),
          ],
          final_estimator=Pipeline[StandardScaler, LogisticRegression(max_iter=2000)],
      ),
      method='isotonic', cv=3,
  )

Labels are encoded H/D/A -> 0/1/2 (the `label_map` the inference wrapper expects).
A temporal holdout (the latest season) is scored for honest, out-of-sample metrics;
the deployed model is then refit on ALL rows.

Bundle schema (consumed by inference.match_outcome.MatchOutcomePredictor.load):
  {model, feature_columns, label_map, version, metrics}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

VERSION = "v1"

# H/D/A -> integer. Fixed so the inference wrapper can resolve proba columns.
LABEL_MAP: dict[str, int] = {"H": 0, "D": 1, "A": 2}

# Random seed for the tree learners + calibration splits, so re-training is
# deterministic (the originally-shipped artefact used unseeded estimators; we
# seed for reproducibility, which is the whole point of this module).
RANDOM_STATE = 0

# Hyperparameters recovered from the shipped artefact. Kept as named constants
# so the architecture is explicit and re-training reproduces the same model.
_XGB_PARAMS = dict(
    n_estimators=150,
    max_depth=5,
    learning_rate=0.01,
    subsample=0.8,
    colsample_bytree=1.0,
    reg_lambda=10,
    objective="multi:softprob",
    eval_metric="mlogloss",
    tree_method="hist",
    random_state=RANDOM_STATE,
)
_LGBM_PARAMS = dict(
    n_estimators=150,
    max_depth=4,
    learning_rate=0.1387,
    num_leaves=42,
    subsample=0.623,
    colsample_bytree=0.634,
    reg_lambda=2.89,
    reg_alpha=8.07,
    min_child_samples=57,
    objective="multiclass",
    random_state=RANDOM_STATE,
    verbose=-1,
)


@dataclass
class MatchOutcomeResult:
    """Bundle of everything `save()` persists, plus holdout metrics."""
    model: CalibratedClassifierCV
    feature_columns: list[str]
    label_map: dict[str, int]
    version: str
    metrics: dict = field(default_factory=dict)


def _lr_pipeline() -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(max_iter=2000)),
    ])


def _build_stack() -> StackingClassifier:
    """The (uncalibrated) stacked ensemble: LR + XGBoost + LightGBM, blended by
    a logistic meta-learner over their predicted probabilities."""
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier

    estimators = [
        ("lr", _lr_pipeline()),
        ("xgb", XGBClassifier(**_XGB_PARAMS)),
        ("lgbm", LGBMClassifier(**_LGBM_PARAMS)),
    ]
    return StackingClassifier(
        estimators=estimators,
        final_estimator=_lr_pipeline(),
        stack_method="predict_proba",
        cv=5,
        n_jobs=None,
    )


def _new_model() -> CalibratedClassifierCV:
    """Isotonic-calibrated stacked ensemble — one fresh, unfitted instance."""
    return CalibratedClassifierCV(estimator=_build_stack(), method="isotonic", cv=3)


def _multiclass_brier(y_idx: np.ndarray, proba: np.ndarray) -> float:
    """Elementwise multiclass Brier (mean over n*3 cells) — matches the metric
    stored in the shipped artefact and reported by the backtest script."""
    n = len(y_idx)
    onehot = np.zeros((n, proba.shape[1]), dtype=float)
    onehot[np.arange(n), y_idx] = 1.0
    return float(np.mean((proba - onehot) ** 2))


def train_match_outcome(
    features: pd.DataFrame,
    *,
    feature_columns: Sequence[str],
    target_column: str = "ft_result",
    holdout_seasons: Sequence[str] = ("2024-2025",),
) -> MatchOutcomeResult:
    """
    Train the calibrated stacked H/D/A classifier.

    Scores a temporal holdout (rows whose `season` is in `holdout_seasons`) for
    honest out-of-sample metrics, then refits on ALL usable rows for the
    deployed artefact.

    `features` is the output of features.match_features.build_match_features.
    Rows with NaN in any required feature (warm-up matches, missing odds for the
    odds model) are dropped first.
    """
    feature_columns = list(feature_columns)

    usable = features.dropna(subset=list(feature_columns) + [target_column]).copy()
    dropped = len(features) - len(usable)
    if dropped:
        log.info("Dropped %d rows with NaN in features/target", dropped)
    if usable.empty:
        raise ValueError("No usable rows after dropping NaNs.")

    y = usable[target_column].map(LABEL_MAP)
    if y.isna().any():
        bad = sorted(usable.loc[y.isna(), target_column].unique())
        raise ValueError(f"Unmapped target labels {bad}; expected H/D/A.")
    y = y.astype(int)
    X = usable[feature_columns]

    holdout_seasons = set(holdout_seasons)
    test_mask = usable["season"].isin(holdout_seasons)
    train_mask = ~test_mask

    metrics: dict = {"n_total": int(len(usable))}

    # --- Out-of-sample evaluation on the temporal holdout ---
    if test_mask.sum() > 0 and train_mask.sum() > 0:
        eval_model = _new_model()
        eval_model.fit(X[train_mask], y[train_mask])
        proba = eval_model.predict_proba(X[test_mask])
        y_test = y[test_mask].to_numpy()
        preds = proba.argmax(axis=1)
        metrics.update(
            accuracy=float(accuracy_score(y_test, preds)),
            log_loss=float(log_loss(y_test, proba, labels=[0, 1, 2])),
            brier=_multiclass_brier(y_test, proba),
            n_train=int(train_mask.sum()),
            n_test=int(test_mask.sum()),
        )
        log.info("Holdout %s: acc=%.3f log_loss=%.4f brier=%.4f (n_train=%d n_test=%d)",
                 sorted(holdout_seasons), metrics["accuracy"], metrics["log_loss"],
                 metrics["brier"], metrics["n_train"], metrics["n_test"])
    else:
        log.warning("Holdout %s yields no train/test split; skipping OOS metrics.",
                    sorted(holdout_seasons))

    # --- Deployed model: refit on ALL usable rows ---
    final = _new_model()
    final.fit(X, y)

    return MatchOutcomeResult(
        model=final,
        feature_columns=feature_columns,
        label_map=dict(LABEL_MAP),
        version=VERSION,
        metrics=metrics,
    )


def save(result: MatchOutcomeResult, path: str) -> None:
    """Persist a trained result as the joblib bundle the inference wrapper loads."""
    import joblib
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": result.model,
        "feature_columns": list(result.feature_columns),
        "label_map": dict(result.label_map),
        "version": result.version,
        "metrics": dict(result.metrics),
    }, path)
    log.info("Saved match-outcome model -> %s", path)
