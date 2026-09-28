"""
D0 — extensible multi-task prediction framework.

One inference shape for every forecasting task, mirroring the existing
MatchOutcomePredictor (load / predict_from_features / feature_columns / version) so the
agent's prediction node can dispatch over tasks uniformly and the synthesizer/eval/memory
need no per-task code.

A task is described by a TaskSpec (see registry.py). Models are simple sklearn
classifiers/regressors (tree/linear) bundled with their feature list + label order, so:
  - SHAP / feature_importances_ (future Q14 explanation) is cheap, and
  - calibration evals (Brier, reliability) work the same way as match-outcome.

Artefacts are joblib bundles:
  {model, feature_columns, classes, version, task_name, target_type}
target_type: 'classification' (predict_proba) | 'regression' (predict).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GenericPrediction:
    """Uniform output for any task. The dispatcher turns this into a 1-row DataFrame."""
    task_name: str
    entity: str                      # e.g. team name (or "Arsenal vs Chelsea")
    target_type: str                 # 'classification' | 'regression'
    probabilities: dict              # {class_label: prob} (empty for regression)
    prediction: Any                  # top class label, or regression value
    confidence: float                # max prob (classification) or NaN (regression)
    model_version: str

    def as_row(self) -> dict:
        row = {
            "task": self.task_name,
            "entity": self.entity,
            "prediction": self.prediction,
            "confidence": round(self.confidence, 3) if self.confidence == self.confidence else None,
            "model_version": self.model_version,
        }
        for k, v in self.probabilities.items():
            row[f"p_{k}"] = round(float(v), 3)
        return row


class GenericPredictor:
    """Loads a task artefact and scores a feature row, mirroring MatchOutcomePredictor."""

    def __init__(self, model, feature_columns, classes, version, task_name, target_type):
        self._model = model
        self._feature_columns = list(feature_columns)
        self._classes = list(classes) if classes is not None else []
        self._version = version
        self._task_name = task_name
        self._target_type = target_type

    @classmethod
    def load(cls, path: str | Path) -> "GenericPredictor":
        import joblib
        b = joblib.load(path)
        return cls(b["model"], b["feature_columns"], b.get("classes"),
                   b.get("version", "unknown"), b.get("task_name", "unknown"),
                   b.get("target_type", "classification"))

    @property
    def feature_columns(self) -> list[str]:
        return list(self._feature_columns)

    @property
    def version(self) -> str:
        return self._version

    def _vector(self, feature_row: dict | pd.Series) -> pd.DataFrame:
        # Return a 1-row DataFrame (not a bare ndarray) so the column names the
        # model was fitted with are preserved — silences sklearn's
        # "X does not have valid feature names" warning and guards against any
        # silent feature-order mismatch.
        values = [[float(feature_row[c]) for c in self._feature_columns]]
        return pd.DataFrame(values, columns=self._feature_columns)

    def predict_from_features(self, feature_row: dict | pd.Series, entity: str = "") -> GenericPrediction:
        x = self._vector(feature_row)
        if self._target_type == "classification":
            proba = self._model.predict_proba(x)[0]
            probs = {str(c): float(p) for c, p in zip(self._classes, proba)}
            top = max(probs, key=probs.get)
            conf = float(max(proba))
            pred = top
        else:
            pred = float(self._model.predict(x)[0])
            probs, conf = {}, float("nan")
        return GenericPrediction(
            task_name=self._task_name, entity=entity, target_type=self._target_type,
            probabilities=probs, prediction=pred, confidence=conf,
            model_version=self._version,
        )


def save_bundle(path: str | Path, *, model, feature_columns, classes,
                version, task_name, target_type, extra: Optional[dict] = None) -> None:
    import joblib
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model, "feature_columns": list(feature_columns),
        "classes": list(classes) if classes is not None else None,
        "version": version, "task_name": task_name, "target_type": target_type,
    }
    if extra:
        bundle.update(extra)   # e.g. base_rates for the event-impact task
    joblib.dump(bundle, path)
