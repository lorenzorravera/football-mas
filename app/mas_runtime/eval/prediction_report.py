"""
Prediction eval report (Workstream B3).

Reads the end-to-end routing/plausibility results (`prediction_results.csv`) and joins the
leakage-free MODEL-LEVEL holdout metrics (`model_holdout_metrics.json`) so one table shows,
per capability: did the MAS route + produce a valid forecast, AND (where scoreable) how good
the underlying model is versus a trivial baseline.

Usage:  cd Ethan/agent_v4 && python eval/prediction_report.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).parent
RESULTS_CSV = _HERE / "results" / "prediction_results.csv"
METRICS = _HERE / "results" / "model_holdout_metrics.json"


def main() -> int:
    if not RESULTS_CSV.exists():
        print(f"No {RESULTS_CSV} — run eval/prediction_runner.py first.")
        return 1
    rows = list(csv.DictReader(open(RESULTS_CSV)))
    metrics = json.loads(METRICS.read_text())["tasks"] if METRICS.exists() else {}

    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(r)

    print("=" * 100)
    print("PREDICTION EVAL — end-to-end routing/plausibility  +  model-level holdout metric")
    print("=" * 100)
    print(f"{'capability':26}{'route':7}{'plaus':7}{'model holdout (leakage-free)':40}")
    print("-" * 100)
    tot_r = tot_p = tot_n = 0
    for task, rs in by_task.items():
        n = len(rs)
        route = sum(1 for r in rs if r["routing_ok"] == "True")
        plaus = sum(1 for r in rs if r.get("plausible") == "True")
        tot_r += route; tot_p += plaus; tot_n += n
        m = metrics.get(task)
        if m:
            if "accuracy" in m:
                cell = f"acc={m['accuracy']} brier={m.get('brier','-')} — {m['verdict']}"
            elif "mae" in m:
                cell = f"mae={m['mae']} r2={m.get('r2','-')} — {m['verdict']}"
            else:
                cell = m.get("verdict", "")
        else:
            cell = "(routing/plausibility only)"
        print(f"{task:26}{route}/{n:<5}{plaus}/{n:<5}{cell[:40]}")
    print("-" * 100)
    print(f"{'TOTAL':26}{tot_r}/{tot_n:<5}{tot_p}/{tot_n:<5}")
    print()

    # surface any failures explicitly
    fails = [r for r in rows if r["routing_ok"] != "True" or r.get("plausible") == "False"]
    if fails:
        print("FAILURES / findings:")
        for r in fails:
            print(f"  [{r['task']}] route={r['routing_ok']} plaus={r.get('plausible')} "
                  f"resolved={r['resolved']} note={r.get('note','')[:60]} :: {r['query'][:55]}")
    else:
        print("No routing/plausibility failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
