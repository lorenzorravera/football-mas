"""
golden/prediction_set.py — the 4 prediction golden questions + frozen ground truth (Phase 7).

These are a SEPARATE frozen artifact from the 46 SQL items (never edits the frozen golden_set).
Each item: a real 2024-2025 holdout fixture. Ground truth has two parts:
  * model_gt    — the trained model's probability vector (run via the real predict tool); used for
                  TOOL-USE FIDELITY scoring (did MAS / single+tools call the model and report it right).
  * actual      — the realised result (H/D/A); used for FORECAST ACCURACY (Brier) across all conditions,
                  including the single-LLM-raw-data forecaster which never sees the model.

Run:  python -m golden.prediction_set        # builds + freezes results/golden/prediction_golden.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.predict_match_outcome import predict_match_outcome

OUT = Path(__file__).resolve().parent.parent / "results" / "golden"

# Real 2024-2025 fixtures (actuals from the backtest). Each exercises a different output facet.
PREDICTION_ITEMS = [
    dict(id="P01", category="prediction", difficulty="medium",
         question="Predict the outcome of Manchester United vs Fulham on 2024-08-16 — give the "
                  "home win, draw and away win probabilities.",
         home_team="Manchester United", away_team="Fulham", match_date="2024-08-16", actual="H",
         tests="full probability vector"),
    dict(id="P02", category="prediction", difficulty="medium",
         question="How likely is an Arsenal home win against Wolves on 2024-08-17, and how confident "
                  "is the model in its prediction?",
         home_team="Arsenal", away_team="Wolves", match_date="2024-08-17", actual="H",
         tests="strong favourite + confidence"),
    dict(id="P03", category="prediction", difficulty="medium",
         question="Who is more likely to win, Everton or Brighton, in their match at Everton on "
                  "2024-08-17?",
         home_team="Everton", away_team="Brighton", match_date="2024-08-17", actual="A",
         tests="most-likely outcome (away favourite)"),
    dict(id="P04", category="prediction", difficulty="hard",
         question="What probability does the model assign to a draw between Nottingham Forest and "
                  "Bournemouth on 2024-08-17?",
         home_team="Nottingham Forest", away_team="Bournemouth", match_date="2024-08-17", actual="D",
         tests="draw probability (model under-predicts draws)"),
]

_ONEHOT = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}  # order: home, draw, away


def _sha256(items: list) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_and_freeze() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "prediction_golden.json"
    items = []
    for it in PREDICTION_ITEMS:
        model_gt = predict_match_outcome(it["home_team"], it["away_team"], match_date=it["match_date"])
        items.append({**it, "answer_type": "probability_vector", "gt_type": "prediction",
                      "model_gt": model_gt, "actual_onehot": _ONEHOT[it["actual"]]})
    doc = {"frozen": True, "phase": "7", "artifact": "prediction_golden",
           "n_items": len(items), "sha256": _sha256(items), "items": items}
    if target.exists():
        existing = json.loads(target.read_text())
        if existing.get("sha256") == doc["sha256"]:
            print("unchanged (same sha256); not rewriting frozen file.")
            return existing
        raise SystemExit(f"Refusing to overwrite frozen {target.name} with different content. "
                         "Delete by hand to re-freeze.")
    target.write_text(json.dumps(doc, indent=2))
    return doc


if __name__ == "__main__":
    doc = build_and_freeze()
    print(f"FROZEN {doc['n_items']} prediction items  sha256={doc['sha256'][:16]}…\n")
    for it in doc["items"]:
        g = it["model_gt"]
        print(f"  {it['id']} {it['home_team']} vs {it['away_team']} ({it['match_date']}) "
              f"actual={it['actual']}  model: H={g.get('home_win')} D={g.get('draw')} A={g.get('away_win')}")
