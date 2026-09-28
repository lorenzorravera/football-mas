"""
Backtest the match-outcome models on a held-out season (offline evaluation).

Paper/evaluation tool — NOT part of the agent graph, never seen by a user.
Reads the same parquet the model trained on (so the holdout is identical to
what training excluded), scores the models, and writes per-fixture CSVs.

Includes two reference baselines (base rate, bookmaker) and an optional
draw-boost decision-rule sweep.

Run from the prediction_agent/ project dir:
    python scripts/backtest_match_outcome.py --matches prediction_agent/data/raw/matches.parquet
    python scripts/backtest_match_outcome.py --matches prediction_agent/data/raw/matches.parquet --draw-sweep
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from prediction_agent.features.match_features import build_match_features
from prediction_agent.inference.match_outcome import MatchOutcomePredictor

log = logging.getLogger("backtest")

LABELS = ["H", "D", "A"]
LABEL_IDX = {"H": 0, "D": 1, "A": 2}


def _score(proba: np.ndarray, y_true_idx: np.ndarray, draw_boost: float = 1.0) -> dict:
    """proba: (n,3) in [H,D,A] order. y_true_idx: (n,) actual class indices."""
    n = len(y_true_idx)
    onehot = np.zeros((n, 3), dtype=float)
    onehot[np.arange(n), y_true_idx] = 1.0

    # Decision rule: optionally inflate draw score before argmax. Only changes
    # the picked class (accuracy); probabilities are untouched, so Brier and
    # log_loss still reflect the model's true probabilistic output.
    decision = proba.copy()
    decision[:, 1] *= draw_boost
    preds = decision.argmax(axis=1)
    accuracy = float((preds == y_true_idx).mean())

    brier_elementwise = float(np.mean((proba - onehot) ** 2))
    brier_perfixture = float(np.mean(((proba - onehot) ** 2).sum(axis=1)))
    ll = float(log_loss(y_true_idx, proba, labels=[0, 1, 2]))

    return {
        "accuracy": accuracy,
        "brier": brier_elementwise,
        "brier_perfixture": brier_perfixture,
        "log_loss": ll,
        "n": n,
    }


def _run_one(label: str, artefact: Path, holdout: pd.DataFrame,
             team_names: dict, out_csv: Path, draw_boost: float = 1.0):
    """Score one artefact on the holdout; write its per-fixture CSV."""
    if not artefact.exists():
        log.warning("[%s] artefact not found: %s — skipping", label, artefact)
        return None

    predictor = MatchOutcomePredictor.load(artefact)
    needed = predictor.feature_columns
    missing = [c for c in needed if c not in holdout.columns]
    if missing:
        log.warning("[%s] holdout missing features %s — skipping", label, missing)
        return None
    usable = holdout.dropna(subset=needed)
    dropped = len(holdout) - len(usable)
    if dropped:
        log.info("[%s] dropped %d holdout rows with NaN in required features", label, dropped)

    preds = predictor.predict_batch(usable)
    proba = np.array([[p.home_win_prob, p.draw_prob, p.away_win_prob] for p in preds])
    y_idx = usable["ft_result"].map(LABEL_IDX).to_numpy()
    metrics = _score(proba, y_idx, draw_boost=draw_boost)
    metrics["model"] = label

    _decision = proba.copy()
    _decision[:, 1] *= draw_boost
    pred_labels = [LABELS[i] for i in _decision.argmax(axis=1)]
    df = pd.DataFrame({
        "season":     usable["season"].values,
        "match_date": usable["match_date"].values,
        "home_team":  [team_names.get(int(t), str(t)) for t in usable["home_team_id"]],
        "away_team":  [team_names.get(int(t), str(t)) for t in usable["away_team_id"]],
        "p_home":     proba[:, 0],
        "p_draw":     proba[:, 1],
        "p_away":     proba[:, 2],
        "predicted":  pred_labels,
        "actual":     usable["ft_result"].values,
        "correct":    [p == a for p, a in zip(pred_labels, usable["ft_result"].values)],
        "model":      label,
    })
    df.to_csv(out_csv, index=False)
    log.info("[%s] wrote %d rows -> %s", label, len(df), out_csv)

    try:
        saved = joblib.load(artefact).get("metrics", {})
        if "brier" in saved:
            log.info("[%s] saved-at-train brier=%.4f acc=%.3f  |  backtest brier=%.4f acc=%.3f",
                     label, saved.get("brier", float("nan")), saved.get("accuracy", float("nan")),
                     metrics["brier"], metrics["accuracy"])
    except Exception:
        pass

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=Path, default=Path("data/raw/matches.parquet"))
    parser.add_argument("--teams", type=Path, default=None,
                        help="Defaults to teams.parquet next to --matches.")
    parser.add_argument("--artefacts-dir", type=Path, default=Path("artefacts"))
    parser.add_argument("--holdout-seasons", nargs="+", default=["2024-2025"])
    parser.add_argument("--output-dir", type=Path, default=Path("backtest_results"))
    parser.add_argument("--draw-boost", type=float, default=1.0,
                        help="Multiplier on draw probability in the argmax decision (1.0 = none).")
    parser.add_argument("--draw-sweep", action="store_true",
                        help="Print accuracy/draw-recall across a range of draw boosts.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.matches.exists():
        raise SystemExit(f"Missing {args.matches}. Run dump_to_parquet first.")

    matches = pd.read_parquet(args.matches)
    features = build_match_features(matches)
    holdout = features[features["season"].isin(args.holdout_seasons)].copy()
    if holdout.empty:
        raise SystemExit(f"No rows for holdout {args.holdout_seasons}. "
                         f"Available: {sorted(features['season'].unique())}")
    log.info("Holdout %s: %d fixtures", args.holdout_seasons, len(holdout))

    team_names = {}
    teams_path = args.teams or (args.matches.parent / "teams.parquet")
    if teams_path.exists():
        t = pd.read_parquet(teams_path)
        team_names = dict(zip(t["team_id"].astype(int), t["team_name"]))
    else:
        log.warning("teams parquet not found at %s — CSV will show team IDs", teams_path)

    y_idx_full = holdout["ft_result"].map(LABEL_IDX).to_numpy()
    rows = []

    # Baseline 1: base rate (train-season class frequencies)
    train_df = features[~features["season"].isin(args.holdout_seasons)]
    freq = (train_df["ft_result"].map(LABEL_IDX)
            .value_counts(normalize=True).reindex([0, 1, 2]).fillna(0.0).to_numpy())
    base_proba = np.tile(freq, (len(holdout), 1))
    m_base = _score(base_proba, y_idx_full)
    m_base["model"] = "base rate"
    rows.append(m_base)

    # Baseline 2: bookmaker-implied
    odds_cols = ["implied_home_prob", "implied_draw_prob", "implied_away_prob"]
    if all(c in holdout.columns for c in odds_cols):
        odds_h = holdout.dropna(subset=odds_cols)
        if len(odds_h):
            book_proba = odds_h[odds_cols].to_numpy(dtype=float)
            y_odds = odds_h["ft_result"].map(LABEL_IDX).to_numpy()
            m_book = _score(book_proba, y_odds)
            m_book["model"] = "bookmaker"
            rows.append(m_book)

    # Trained models
    r_c = _run_one("no_odds (C)", args.artefacts_dir / "match_outcome_v1.pkl",
                   holdout, team_names, args.output_dir / "backtest_no_odds.csv",
                   draw_boost=args.draw_boost)
    if r_c:
        rows.append(r_c)
    r_b = _run_one("with_odds (B)", args.artefacts_dir / "match_outcome_v1_with_odds.pkl",
                   holdout, team_names, args.output_dir / "backtest_with_odds.csv",
                   draw_boost=args.draw_boost)
    if r_b:
        rows.append(r_b)

    if not rows:
        raise SystemExit("No artefacts could be scored. Train them first: make train-match-outcome")

    summary = pd.DataFrame(rows)[["model", "n", "accuracy", "brier", "brier_perfixture", "log_loss"]]
    summary.to_csv(args.output_dir / "backtest_summary.csv", index=False)

    print("\n" + "=" * 72)
    print(f"BACKTEST — holdout {args.holdout_seasons} (out-of-sample)")
    print("=" * 72)
    print(f"{'model':<16}{'n':>6}{'accuracy':>11}{'brier':>10}{'brier/fix':>11}{'log_loss':>11}")
    print("-" * 72)
    for r in rows:
        print(f"{r['model']:<16}{r['n']:>6}{r['accuracy']:>11.3f}"
              f"{r['brier']:>10.4f}{r['brier_perfixture']:>11.4f}{r['log_loss']:>11.4f}")
    print("=" * 72)
    if r_c and r_b:
        d_acc = r_b["accuracy"] - r_c["accuracy"]
        d_brier = r_c["brier"] - r_b["brier"]
        print(f"Odds effect (B - C):  accuracy {d_acc:+.3f}   brier {d_brier:+.4f} "
              f"({'odds help' if d_brier > 0 else 'odds do not help'})")
        print("Note: C serves live; B is backtest-only (needs pre-match odds).")
    if args.draw_boost != 1.0:
        print(f"(decision rule: draw probability x{args.draw_boost} before argmax)")
    print(f"\nPer-fixture CSVs + summary written to {args.output_dir}/\n")

    if args.draw_sweep:
        art = args.artefacts_dir / "match_outcome_v1.pkl"
        if art.exists():
            predictor = MatchOutcomePredictor.load(art)
            usable = holdout.dropna(subset=predictor.feature_columns)
            preds = predictor.predict_batch(usable)
            proba = np.array([[p.home_win_prob, p.draw_prob, p.away_win_prob] for p in preds])
            y_idx = usable["ft_result"].map(LABEL_IDX).to_numpy()
            draw_mask = (y_idx == 1)

            print("DRAW-BOOST SWEEP (no-odds model)")
            print("-" * 56)
            print(f"{'boost':>7}{'accuracy':>11}{'draw_recall':>13}{'%pred draw':>13}")
            print("-" * 56)
            for boost in [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0]:
                dec = proba.copy()
                dec[:, 1] *= boost
                p = dec.argmax(axis=1)
                acc = float((p == y_idx).mean())
                draw_recall = float((p[draw_mask] == 1).mean()) if draw_mask.any() else 0.0
                pct_draw = float((p == 1).mean())
                print(f"{boost:>7.1f}{acc:>11.3f}{draw_recall:>13.3f}{pct_draw:>13.3f}")
            print("-" * 56)
            print("CAUTION: sweep is on the TEST holdout, so the best boost here is\n"
                  "optimistic. For the paper, pick the boost on a validation season\n"
                  "(e.g. 2023-2024) and report the chosen value on 2024-2025.\n")


if __name__ == "__main__":
    main()
