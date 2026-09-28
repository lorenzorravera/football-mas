"""Baseline scoreboard for the match-outcome model.

Grouped bar chart: the live no-odds model vs a base-rate predictor and the
bookmaker's implied probabilities, on accuracy and Brier score (2024-2025
holdout, 379 fixtures). Numbers are read from backtest_summary.csv so the
figure never drifts from the reported table.
"""
import argparse
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

# arms to show, in order, mapped from the summary-csv "model" column -> label
ARMS = [("base rate", "Base rate"), ("no_odds (C)", "Model"), ("bookmaker", "Market")]
NAVY, GREY = "#1F3864", "#B0B0B0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="backtest_results/backtest_summary.csv")
    ap.add_argument("--out", default="backtest_results/baseline_scoreboard.pdf")
    a = ap.parse_args()

    df = pd.read_csv(a.csv).set_index("model")
    labels = [lab for _, lab in ARMS]
    acc = [df.loc[key, "accuracy"] for key, _ in ARMS]
    brier = [df.loc[key, "brier"] for key, _ in ARMS]

    x = range(len(labels))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.4, 3.2))

    for ax, vals, title, lo, hi in [
        (ax1, acc, "Accuracy (higher better)", 0.0, 0.6),
        (ax2, brier, "Brier score (lower better)", 0.0, 0.24),
    ]:
        # highlight the model bar in navy, baselines in grey
        colors = [NAVY if lab == "Model" else GREY for lab in labels]
        bars = ax.bar(x, vals, color=colors, width=0.62)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(title, fontsize=9)
        ax.set_ylim(lo, hi)
        ax.spines[["top", "right"]].set_visible(False)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.3f}",
                    ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    Path(a.out).parent.mkdir(exist_ok=True, parents=True)
    fig.savefig(a.out)
    fig.savefig(a.out.replace(".pdf", ".png"), dpi=150)
    print("figure ->", a.out)


if __name__ == "__main__":
    main()
