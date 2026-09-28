"""
Interim session report — reads the per-session transcripts already written under
eval/results/session_runs/ (which land incrementally, one JSON per arm as each session
finishes) and prints the same per-sub-experiment paired deltas as session_report.py.

Use this to see results WHILE session_runner.py is still running, before the final
session_results.csv is written. Once the full run finishes, prefer session_report.py.

    cd Ethan/agent_v4 && python eval/session_report_partial.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.session_report import (
    VERDICT_SCORE, BASELINES, _mean, _bootstrap_ci, _wilcoxon, _session_score,
)

_HERE = Path(__file__).parent
RUNS = _HERE / "results" / "session_runs"


def _load_rows():
    """Flatten session_runs/*.json into the same row shape session_report expects."""
    rows = []
    for f in sorted(RUNS.glob("*.json")):
        d = json.loads(f.read_text())
        for t in d["turns"]:
            rows.append({
                "session": d["session"],
                "sub_experiment": d.get("sub_experiment"),
                "arm": d["arm"],
                "turn_index": str(t.get("turn_index")),
                "role": t.get("role"),
                "verdict": t.get("verdict"),
                "reason": t.get("reason"),
            })
    return rows


def report():
    rows = _load_rows()
    if not rows:
        print(f"No transcripts yet in {RUNS}.")
        return

    # Only score sessions that have ALL FOUR arms present (a fair paired comparison);
    # report how many are still partial.
    arms_by_session = defaultdict(set)
    for r in rows:
        arms_by_session[r["session"]].add(r["arm"])
    ALL = {"mas_memory", "mas_no_memory", "single_llm_stateless", "single_llm_history"}
    complete = {s for s, a in arms_by_session.items() if ALL <= a}
    partial = sorted(set(arms_by_session) - complete)

    sessions_by_sub = defaultdict(set)
    for r in rows:
        if r["session"] in complete:
            sessions_by_sub[r["sub_experiment"]].add(r["session"])

    print("=" * 72)
    print("INTERIM SESSION REPORT (partial — from session_runs/ transcripts)")
    print(f"complete sessions (all 4 arms): {len(complete)} | "
          f"still partial: {len(partial)} {partial if partial else ''}")
    print("=" * 72)

    for sub in sorted(sessions_by_sub):
        sessions = sorted(sessions_by_sub[sub])
        print(f"\n### sub-experiment: {sub}   (n={len(sessions)} complete sessions)")
        for baseline in BASELINES:
            deltas, guard = [], []
            for s in sessions:
                mas = _session_score(rows, s, "mas_memory", beneficiary_only=True)
                base = _session_score(rows, s, baseline, beneficiary_only=True)
                if mas is not None and base is not None:
                    deltas.append(mas - base)
                mas_g = _session_score(rows, s, "mas_memory", beneficiary_only=False)
                base_g = _session_score(rows, s, baseline, beneficiary_only=False)
                if mas_g is not None and base_g is not None:
                    guard.append(mas_g - base_g)
            if not deltas:
                print(f"  vs {baseline:22s}: (no paired beneficiary turns yet)")
                continue
            print(f"  vs {baseline:22s}: Δ(beneficiary)={_mean(deltas):+.3f} "
                  f"95%CI={_bootstrap_ci(deltas)} wilcoxon_p={_wilcoxon(deltas)}  "
                  f"guardΔ(all)={_mean(guard):+.3f}")


if __name__ == "__main__":
    report()
