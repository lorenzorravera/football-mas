"""
D2 — calibration / accuracy eval for the team-season tasks.

Reports temporal-holdout metrics (train on early seasons, test on the latest transition):
  classification: accuracy, log-loss, multiclass Brier, + a reliability table
  regression:     MAE, R2

These models are trained on a small single-league sample (~56 train rows), so metrics are
honestly modest — the point is calibrated, reproducible reporting (the same machinery used
for match-outcome), not high accuracy. Mirrors prediction_figures.py for match-outcome.

Usage:  cd prediction_agent && python scripts/eval_tasks.py
"""

import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "Ethan" / "agent_v4" / ".env", override=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prediction_agent.models.team_season import (
    train_team_season_task, TASKS, HOLDOUT_FEATURE_SEASON, _new_model,
)
from prediction_agent.features.team_season_features import training_frame, FEATURE_COLUMNS


def _reliability(task_key: str, n_bins: int = 5) -> list[tuple]:
    """Confidence-vs-accuracy reliability for a classification task on the holdout."""
    target_col, target_type = TASKS[task_key]
    if target_type != "classification":
        return []
    df = training_frame().dropna(subset=[target_col]).reset_index(drop=True)
    tr, te = df["season"] < HOLDOUT_FEATURE_SEASON, df["season"] == HOLDOUT_FEATURE_SEASON
    if tr.sum() == 0 or te.sum() == 0:
        return []
    model = _new_model("classification")
    model.fit(df[FEATURE_COLUMNS][tr], df[target_col][tr])
    proba = model.predict_proba(df[FEATURE_COLUMNS][te])
    pred = model.predict(df[FEATURE_COLUMNS][te])
    conf = proba.max(axis=1)
    correct = (pred == df[target_col][te].values).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        m = (conf >= bins[i]) & (conf < bins[i + 1] if i < n_bins - 1 else conf <= bins[i + 1])
        if m.sum():
            out.append((f"{bins[i]:.1f}-{bins[i+1]:.1f}", int(m.sum()),
                        round(float(conf[m].mean()), 3), round(float(correct[m].mean()), 3)))
    return out


def _print_metrics(m: dict, keys) -> None:
    for key in keys:
        if key in m:
            print(f"    {key:18s}: {m[key]}")


def main() -> int:
    print("=" * 64)
    print("TEAM-SEASON TASKS — temporal-holdout calibration/accuracy")
    print(f"(train: seasons < {HOLDOUT_FEATURE_SEASON}; test: {HOLDOUT_FEATURE_SEASON}→next)")
    print("=" * 64)
    for k in TASKS:
        m = train_team_season_task(k, save=False)
        print(f"\n### {k}  [{m['target_type']}]  n_train={m['n_train']} n_test={m['n_test']}")
        _print_metrics(m, ("holdout_accuracy", "holdout_logloss", "holdout_brier",
                           "holdout_mae", "holdout_r2"))
        rel = _reliability(k)
        if rel:
            print("    reliability (conf_bin | n | mean_conf | accuracy):")
            for b, n, c, a in rel:
                print(f"      {b}  n={n:2d}  conf={c}  acc={a}")

    # D4 model-backed tasks (player decline / cross-league / in-game events).
    print("\n" + "=" * 64)
    print("D4 TASKS — holdout calibration/accuracy")
    print("=" * 64)
    from prediction_agent.models.player_season import train_player_task, TASKS as PL
    from prediction_agent.models import cross_league as xleague
    from prediction_agent.models import event_impact as eimpact

    for k in PL:
        m = train_player_task(k, save=False)
        print(f"\n### {k}  [{m['target_type']}]  n_train={m['n_train']} n_test={m['n_test']} "
              f"base_rate={m.get('base_rate')}")
        _print_metrics(m, ("holdout_accuracy", "holdout_logloss", "holdout_brier"))

    m = xleague.train(save=False)
    print(f"\n### cross_league_translation  [regression]  n_train={m['n_train']} "
          f"n_test={m['n_test']}  mean_retention={m.get('mean_retention')}")
    _print_metrics(m, ("holdout_mae", "baseline_mae", "holdout_r2"))

    m = eimpact.train(save=False)
    print(f"\n### event_impact  [lookup]  n_matches={m['n_matches']}  "
          f"n_scenarios={m['n_scenarios']}")
    print(f"    base_rates        : {m['base_rates']}")

    print("\nNote: small single-league samples → modest/illustrative metrics by design; the "
          "value is a calibrated, reproducible framework spanning team, player, transfer and "
          "in-game questions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
