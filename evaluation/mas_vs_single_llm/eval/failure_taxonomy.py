"""
eval/failure_taxonomy.py — classify SEMI-controlled failures from their traces (Phase 5/6, Table 2).

For each semi-controlled run that did not score 'correct', classify the failure from the routing
decision (template vs SQL, recorded in the trace) + coverage label:

  A chose_template_when_sql_needed : routed to a template on an OUT-of-coverage question (no template
                                     reproduces it) — a routing error.
  B chose_wrong_template_or_params : routed to a template on an IN-coverage question (a template
                                     exists) but the choice/params were wrong.
  C template_failed_fell_back_sql  : template errored → fell back to free SQL, still wrong (the
                                     templated path produced a wrong/empty result).
  D sql_generation_wrong           : routed to free SQL but the generated SQL was wrong (not a
                                     template-routing failure).
  E error_or_unclassified          : run errored or no route recorded.
"""

from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

from eval.score import _load, score_run_text

ROOT = Path(__file__).resolve().parent.parent
DOF = ROOT / "results" / "runs" / "dof"
STATS_DIR = ROOT / "results" / "stats"


def _route(rec: dict):
    for t in rec.get("trace", []):
        if t.get("node") == "data_analyst" and "route" in t:
            return (t["route"] or {}).get("approach")
    return None


def classify(rec: dict, coverage: str | None) -> str:
    if rec.get("error"):
        return "E_error_or_unclassified"
    approach = _route(rec)
    ts = rec.get("tool_sequence", [])
    if approach == "template":
        if "run_sql" in ts:
            return "C_template_failed_fell_back_sql"
        if coverage == "out_of_coverage":
            return "A_chose_template_when_sql_needed"
        return "B_chose_wrong_template_or_params"
    if approach == "sql":
        return "D_sql_generation_wrong"
    return "E_error_or_unclassified"


def run(models: list[str] | None = None) -> dict:
    gold, gt, cov = _load()
    models = models or ["claude", "gpt", "gemini"]
    by_model = defaultdict(Counter)
    failures = []
    for f in glob.glob(str(DOF / "*_dof_semi_*_r*.json")):
        rec = json.loads(Path(f).read_text())
        model = rec.get("model")
        if model not in models:
            continue
        if score_run_text(rec, gold, gt) == "correct":
            continue
        c = cov.get(rec["question_id"])
        bucket = classify(rec, c)
        by_model[model][bucket] += 1
        failures.append({"id": rec["question_id"], "model": model, "coverage": c,
                         "route": _route(rec), "bucket": bucket})
    out = {"by_model": {m: dict(c) for m, c in by_model.items()},
           "total": dict(sum(by_model.values(), Counter())), "failures": failures}
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    (STATS_DIR / "semi_failure_taxonomy.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    out = run()
    print("Semi-controlled failure taxonomy (by model):")
    buckets = ["A_chose_template_when_sql_needed", "B_chose_wrong_template_or_params",
               "C_template_failed_fell_back_sql", "D_sql_generation_wrong", "E_error_or_unclassified"]
    print(f"  {'model':8}" + "".join(f"{b.split('_')[0]:>4}" for b in buckets) + "  total")
    for m, c in out["by_model"].items():
        tot = sum(c.values())
        print(f"  {m:8}" + "".join(f"{c.get(b,0):>4}" for b in buckets) + f"   {tot}")
    print("\n  legend:", " | ".join(b for b in buckets))
    print("  TOTAL:", out["total"])
