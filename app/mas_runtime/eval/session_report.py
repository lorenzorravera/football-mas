"""
Session report (Phase C, C4) — per-session deltas + effect sizes, NOT one aggregate %.

Reads eval/results/session_results.csv (written by session_runner.py) and reports, per
sub-experiment, the paired comparison of MAS+memory against each single-LLM baseline:

  primary metric (per sub-experiment):
    correction    accuracy on BENEFICIARY turns (the turns that should reuse a stored
                  correction). This is the headline.
    conversation  accuracy on beneficiary (follow-up) turns.
    cache         accuracy on beneficiary (repeat) turns — equal-accuracy is the goal;
                  latency/token SAVINGS are read from trajectory_log (see note).
  guard metric:
    accuracy on non-beneficiary turns (trigger/filler) must not regress.

Effect size: paired per-session deltas (MAS+memory − baseline) on beneficiary turns,
with mean, a bootstrap 95% CI, and a Wilcoxon signed-rank p-value when scipy is present.

Usage:  cd Ethan/agent_v4 && python eval/session_report.py
"""

import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).parent
RESULTS_CSV = _HERE / "results" / "session_results.csv"

VERDICT_SCORE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0, "refused": 0.0}
BASELINES = ["single_llm_stateless", "single_llm_history", "mas_no_memory"]


def _load_rows():
    if not RESULTS_CSV.exists():
        print(f"No results at {RESULTS_CSV}. Run session_runner.py first.")
        sys.exit(1)
    with open(RESULTS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def _bootstrap_ci(deltas, n_boot=2000, seed=42):
    if not deltas:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(deltas)
    means = [sum(rng.choices(deltas, k=n)) / n for _ in range(n_boot)]
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    return (round(lo, 3), round(hi, 3))


def _wilcoxon(deltas):
    try:
        from scipy.stats import wilcoxon
        nz = [d for d in deltas if d != 0]
        if len(nz) < 1:
            return None
        return round(float(wilcoxon(nz).pvalue), 4)
    except Exception:
        return None


def _session_score(rows, session, arm, beneficiary_only):
    """Mean verdict-score for a (session, arm), optionally beneficiary turns only."""
    scores = [
        VERDICT_SCORE.get(r["verdict"], 0.0)
        for r in rows
        if r["session"] == session and r["arm"] == arm
        and r["verdict"] in VERDICT_SCORE
        and (not beneficiary_only or r.get("role") == "beneficiary")
    ]
    return _mean(scores) if scores else None


def report():
    rows = _load_rows()
    sub_exps = sorted({r["sub_experiment"] for r in rows})
    sessions_by_sub = defaultdict(set)
    for r in rows:
        sessions_by_sub[r["sub_experiment"]].add(r["session"])

    print("=" * 70)
    print("SESSION MEMORY EXPERIMENT — per-session paired deltas")
    print("=" * 70)

    for sub in sub_exps:
        sessions = sorted(sessions_by_sub[sub])
        print(f"\n### sub-experiment: {sub}   (n={len(sessions)} sessions)")
        for baseline in BASELINES:
            deltas, guard_deltas = [], []
            for s in sessions:
                mas = _session_score(rows, s, "mas_memory", beneficiary_only=True)
                base = _session_score(rows, s, baseline, beneficiary_only=True)
                if mas is not None and base is not None:
                    deltas.append(mas - base)
                # guard: non-beneficiary turns shouldn't regress
                mas_g = _session_score(rows, s, "mas_memory", beneficiary_only=False)
                base_g = _session_score(rows, s, baseline, beneficiary_only=False)
                if mas_g is not None and base_g is not None:
                    guard_deltas.append(mas_g - base_g)
            if not deltas:
                print(f"  vs {baseline:22s}: (no paired beneficiary turns)")
                continue
            ci = _bootstrap_ci(deltas)
            p = _wilcoxon(deltas)
            print(f"  vs {baseline:22s}: Δ(beneficiary)={_mean(deltas):+.3f} "
                  f"95%CI={ci} wilcoxon_p={p}  "
                  f"guardΔ(all)={_mean(guard_deltas):+.3f}")
        print("  note: cache savings (latency/tokens) live in trajectory_log "
              "(experiment='session_eval'); join on query_id for cost deltas.")


if __name__ == "__main__":
    report()
