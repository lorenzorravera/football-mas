"""
Inference wrapper for match outcome prediction.

This is the seam between the training pipeline and the agent. The agent's
prediction_agent node imports this class and never touches training code.

Stability guarantee: the public API (load, predict, predict_batch) is
versioned. If the underlying model artefact changes (e.g. new features),
the class loads the artefact's `feature_columns` from the pickle and
adapts — the agent code does not change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchPrediction:
    """Structured prediction output. The synthesizer formats this for the user."""
    home_team: str
    away_team: str
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    model_version: str
    # Confidence = max probability. Calibrated, so directly interpretable.
    confidence: float

    def as_dict(self) -> dict:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_win": round(self.home_win_prob, 3),
            "draw": round(self.draw_prob, 3),
            "away_win": round(self.away_win_prob, 3),
            "confidence": round(self.confidence, 3),
            "model_version": self.model_version,
        }


class MatchOutcomePredictor:
    """
    Predicts H/D/A probabilities for a given match.

    Usage:
        predictor = MatchOutcomePredictor.load("artefacts/match_outcome_v1.pkl")
        result = predictor.predict_from_features(feature_row)
    """

    def __init__(self, model, feature_columns: list[str],
                 label_map: dict[str, int], version: str):
        self._model = model
        self._feature_columns = feature_columns
        self._label_map = label_map
        # Inverse map: integer -> label
        self._inv_label_map = {v: k for k, v in label_map.items()}
        self._version = version

    @classmethod
    def load(cls, path: str | Path) -> "MatchOutcomePredictor":
        import joblib
        bundle = joblib.load(path)
        return cls(
            model=bundle["model"],
            feature_columns=bundle["feature_columns"],
            label_map=bundle["label_map"],
            version=bundle.get("version", "unknown"),
        )

    @property
    def feature_columns(self) -> list[str]:
        return list(self._feature_columns)

    @property
    def version(self) -> str:
        return self._version

    def predict_from_features(self, feature_row: dict | pd.Series,
                              home_team: str = "", away_team: str = ""
                              ) -> MatchPrediction:
        """
        Predict from a fully-specified feature row. This is the path used
        by the agent: the prediction_agent node builds features from
        current team state (rolling form, Elo, rest) and passes them here.
        """
        # Build the feature vector in the order the model expects. Use a 1-row
        # DataFrame (not a bare ndarray) so the fitted feature names are kept —
        # silences sklearn's "X does not have valid feature names" warning.
        x = pd.DataFrame(
            [[float(feature_row[c]) for c in self._feature_columns]],
            columns=self._feature_columns,
        )

        proba = self._model.predict_proba(x)[0]  # shape (3,)

        # Resolve which index is H/D/A
        h_idx = self._label_map["H"]
        d_idx = self._label_map["D"]
        a_idx = self._label_map["A"]

        return MatchPrediction(
            home_team=home_team,
            away_team=away_team,
            home_win_prob=float(proba[h_idx]),
            draw_prob=float(proba[d_idx]),
            away_win_prob=float(proba[a_idx]),
            model_version=self._version,
            confidence=float(proba.max()),
        )

    def predict_batch(self, feature_df: pd.DataFrame) -> list[MatchPrediction]:
        """Batch inference for evaluation/backtesting."""
        x = feature_df[self._feature_columns].astype(float)
        proba = self._model.predict_proba(x)

        h_idx = self._label_map["H"]
        d_idx = self._label_map["D"]
        a_idx = self._label_map["A"]

        out: list[MatchPrediction] = []
        for i, row in feature_df.reset_index(drop=True).iterrows():
            out.append(MatchPrediction(
                home_team=row.get("HomeTeam", ""),
                away_team=row.get("AwayTeam", ""),
                home_win_prob=float(proba[i, h_idx]),
                draw_prob=float(proba[i, d_idx]),
                away_win_prob=float(proba[i, a_idx]),
                model_version=self._version,
                confidence=float(proba[i].max()),
            ))
        return out
