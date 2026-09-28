"""
Model explanation (D4, Q14) — top driving factors + confidence for ANY model-backed forecast.

A dependency-free, model-agnostic local explainer that reads a fitted sklearn Pipeline
(StandardScaler → estimator) directly, so it works for every GenericPredictor task in the suite
(season_class, position_movement, turnaround, player_decline, cross_league_translation,
event_impact) with no extra packages (SHAP is not installed):

  - Linear estimators (LogisticRegression / linear regressors): the local contribution of a
    feature is coef · z, where z is the StandardScaler-standardised feature value. This is the
    EXACT additive decomposition of the model's decision function — no approximation.
  - Tree/ensemble estimators (GradientBoosting…): no exact additive local attribution without
    SHAP, so we use importance · z as a signed, directional proxy (magnitude from the global
    feature_importances_, sign from whether the feature is above/below its training mean).

Returns the top-k features by |contribution| with human-readable direction, plus a confidence
read (the model's own max class probability, or the spread for regressors). The label is honest
about which method produced the attribution.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np


def _unwrap(model):
    """Return (scaler_or_None, final_estimator) from a Pipeline, else (None, model)."""
    steps = getattr(model, "named_steps", None)
    if not steps:
        return None, model
    scaler = None
    est = model
    for name, step in steps.items():
        if hasattr(step, "transform") and hasattr(step, "mean_"):
            scaler = step
        else:
            est = step
    return scaler, est


def _standardize(scaler, x: np.ndarray) -> np.ndarray:
    if scaler is None:
        return x
    scale = getattr(scaler, "scale_", None)
    mean = getattr(scaler, "mean_", None)
    if mean is None or scale is None:
        return x
    return (x - mean) / np.where(scale == 0, 1.0, scale)


def _derive_importances(model) -> Optional[np.ndarray]:
    """Average feature_importances_ from any tree base learners reachable inside a
    model that exposes none at the top level — specifically the match-outcome model,
    a CalibratedClassifierCV(StackingClassifier(lr, xgb, lgbm)). Handles the calibrated
    wrapper, the stacking base learners, and Pipeline-wrapped bases. Returns a 1-D
    importance vector over the original features, or None if nothing is reachable.

    All reachable tree learners are trained on the SAME feature columns, so averaging
    their global importances is a coherent (directional) ensemble importance.
    """
    # Unwrap calibrated copies -> their inner estimators; else use the model itself.
    ccs = getattr(model, "calibrated_classifiers_", None)
    if ccs:
        estimators = [getattr(cc, "estimator", None) or getattr(cc, "base_estimator", None)
                      for cc in ccs]
    else:
        estimators = [model]

    imps: list[np.ndarray] = []
    for est in estimators:
        if est is None:
            continue
        named = getattr(est, "named_estimators_", None)
        bases = list(named.values()) if named else [est]
        for base in bases:
            steps = getattr(base, "named_steps", None)   # unwrap Pipeline -> final step
            b = list(steps.values())[-1] if steps else base
            fi = getattr(b, "feature_importances_", None)
            if fi is not None:
                imps.append(np.asarray(fi, dtype="float64"))
    if not imps:
        return None
    return np.mean(imps, axis=0)


def _shap_contrib(model, feature_columns, x: np.ndarray, predicted_class, classes) -> Optional[np.ndarray]:
    """Best-effort SHAP attribution for the predicted class. Returns None unless the
    `shap` package is installed AND the computation succeeds — so the dependency stays
    optional and this never breaks a forecast. Preferred over the importance proxy when
    available (faithful additive attribution)."""
    try:
        import shap  # optional dependency
        import pandas as pd
    except Exception:
        return None
    try:
        predict = lambda arr: model.predict_proba(pd.DataFrame(arr, columns=feature_columns))
        background = np.zeros((1, len(feature_columns)))
        explainer = shap.KernelExplainer(predict, background)
        sv = explainer.shap_values(x.reshape(1, -1), nsamples=100, silent=True)
        cls_list = list(classes) if classes is not None else list(range(len(sv)))
        ci = cls_list.index(predicted_class) if predicted_class in cls_list else 0
        return np.asarray(sv[ci]).ravel()
    except Exception:
        return None


def explain_prediction(model, feature_columns, feature_row, *, classes=None,
                       target_type: str = "classification", predicted_class=None,
                       top_k: int = 6) -> dict:
    """Explain one prediction. `model` is the fitted sklearn Pipeline/estimator.

    Returns: {method, predicted_class, confidence, top_factors: [{feature, value, direction,
    contribution}], note}.
    """
    x = np.array([float(feature_row[c]) for c in feature_columns], dtype="float64")
    scaler, est = _unwrap(model)
    z = _standardize(scaler, x)

    coef = getattr(est, "coef_", None)
    importances = getattr(est, "feature_importances_", None)

    method = None
    contrib = None
    if coef is not None:
        c = np.asarray(coef)
        if c.ndim == 2 and target_type == "classification":
            # pick the row for the predicted class (or the highest-margin class)
            cls_list = list(classes) if classes is not None else list(range(c.shape[0]))
            if predicted_class is not None and predicted_class in cls_list and c.shape[0] == len(cls_list):
                ci = cls_list.index(predicted_class)
            else:
                ci = int(np.argmax(np.abs(c).sum(axis=1))) if c.shape[0] > 1 else 0
            row = c[ci] if c.shape[0] > 1 else c[0]
        else:
            row = c.ravel()
        contrib = row * z
        method = "linear (coef·z, exact additive)"
    elif importances is not None:
        contrib = np.asarray(importances) * z
        method = "importance·z (directional proxy; SHAP unavailable)"
    else:
        # Ensemble with no top-level coef_/importances_ (the calibrated stacking
        # match-outcome model). Prefer real SHAP if the package is installed; else
        # derive importances from the reachable tree base learners so the attribution
        # is non-empty (directional proxy) instead of "unavailable".
        shap_contrib = _shap_contrib(model, feature_columns, x, predicted_class, classes)
        if shap_contrib is not None and shap_contrib.shape[0] == len(feature_columns):
            contrib = shap_contrib
            method = "shap (KernelExplainer over the calibrated ensemble; exact-ish additive)"
        else:
            derived = _derive_importances(est)
            if derived is not None and derived.shape[0] == len(feature_columns):
                contrib = derived * z
                method = "importance·z (ensemble tree base-learners; SHAP proxy)"
            else:
                method = "unavailable (model exposes neither coef_ nor feature_importances_)"

    factors = []
    if contrib is not None:
        order = np.argsort(np.abs(contrib))[::-1][:top_k]
        for i in order:
            factors.append({
                "feature": feature_columns[i],
                "value": round(float(x[i]), 3),
                "direction": "raises" if contrib[i] > 0 else "lowers",
                "contribution": round(float(contrib[i]), 4),
            })

    # Confidence read.
    confidence = None
    note = None
    try:
        if target_type == "classification" and hasattr(model, "predict_proba"):
            import pandas as pd
            proba = model.predict_proba(pd.DataFrame([x], columns=feature_columns))[0]
            confidence = round(float(np.max(proba)), 3)
            margin = float(np.sort(proba)[-1] - np.sort(proba)[-2]) if len(proba) > 1 else 1.0
            note = ("high-confidence" if confidence >= 0.6 and margin >= 0.25
                    else "low-confidence (classes close)" if margin < 0.12
                    else "moderate-confidence")
    except Exception:
        pass

    return {"method": method, "predicted_class": predicted_class,
            "confidence": confidence, "top_factors": factors, "note": note}


def explain_generic(predictor, feature_row, *, predicted_class=None, top_k: int = 6) -> dict:
    """Convenience wrapper for a GenericPredictor (or anything exposing _model,
    feature_columns, _classes, _target_type)."""
    model = getattr(predictor, "_model", predictor)
    cols = predictor.feature_columns
    classes = getattr(predictor, "_classes", None) or None
    ttype = getattr(predictor, "_target_type", "classification")
    return explain_prediction(model, cols, feature_row, classes=classes,
                              target_type=ttype, predicted_class=predicted_class, top_k=top_k)
