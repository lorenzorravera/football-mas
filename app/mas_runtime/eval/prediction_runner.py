"""
End-to-end prediction eval runner (Workstream B).

Drives every registered prediction capability THROUGH THE FULL MAS (`run_agent`) so the
manager's intent/entity routing, the prediction dispatcher, the task handler, and the model
are all exercised together — the first end-to-end coverage of the forecasting path (only
node-level dispatch unit-tests existed before, `eval/tests/test_prediction_dispatch.py`).

What it scores (per question):
  - routing_ok   : did the resolved prediction_type match the fixture's expected task?
  - plausible    : is the produced forecast well-formed for that task's score_mode?
  - error        : any pipeline error string.

What it deliberately does NOT score: realised-label accuracy/Brier. The deployed artefacts
are refit on ALL rows and the agent forecasts the latest season -> next (label unavailable or
leaked), so leakage-free accuracy is measured at the MODEL level instead (eval_tasks.py /
backtest_match_outcome.py, summarised in Ethan/PREDICTION_ROBUSTNESS.md). This family answers
"does the agent route to the right capability and return a valid forecast", not "is the number
right".

Usage:  cd Ethan/agent_v4 && python eval/prediction_runner.py [--task season_class] [--dispatch-only]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from state import create_initial_state
from graph import run_agent
from agents.prediction_agent import _select_prediction_type, prediction_agent

_HERE = Path(__file__).parent
FIXTURES = _HERE / "prediction_sessions" / "tasks.json"
RESULTS_DIR = _HERE / "results" / "prediction_runs"
RESULTS_CSV = _HERE / "results" / "prediction_results.csv"

_SENTINEL_RE = re.compile(r"PREDICTION:\s*([a-z_]+?)(?:_v\d+)?\s*\(")


def _resolved_task(final: dict) -> str | None:
    """The task the agent actually dispatched. metadata['task'] is authoritative for every
    handler except match-outcome, which only leaves it in the sentinel — parse both."""
    md = final.get("prediction_metadata") or {}
    if md.get("task"):
        return md["task"]
    m = _SENTINEL_RE.search(final.get("sql_query", "") or "")
    return m.group(1) if m else None


def _cols(dr) -> list:
    """DataFrame columns as a plain list — never eval a pandas Index for truthiness (ambiguous)."""
    if dr is not None and hasattr(dr, "columns"):
        return [str(c) for c in dr.columns]
    return []


def _plausible(mode: str, final: dict) -> tuple[bool, str]:
    """Task-appropriate output-shape / plausibility check. Returns (ok, note)."""
    if final.get("error"):
        return False, f"error: {str(final['error'])[:80]}"
    md = final.get("prediction_metadata") or {}
    dr = final.get("data_result")
    n_rows = 0 if dr is None else (len(dr) if hasattr(dr, "__len__") else 1)

    if mode in ("probs_hda", "probs_class"):
        probs = md.get("probabilities")
        # single-entity forecast carries a probabilities dict; league-wide carries a p_*-column table
        if isinstance(probs, dict) and probs:
            s = sum(float(v) for v in probs.values())
            return (abs(s - 1.0) < 0.05, f"probs sum={s:.3f} keys={list(probs.items())[:1]}")
        cols = _cols(dr)
        has_p = any(c.startswith("p_") for c in cols)
        return (has_p and n_rows > 0, f"league-wide table rows={n_rows} p_cols={has_p}")
    if mode == "point_estimate":
        pred = md.get("prediction")
        return (n_rows > 0 or pred is not None, f"rows={n_rows} prediction={pred}")
    if mode == "index":
        cols = _cols(dr)
        has_idx = md.get("target_type") == "index" or any("index" in c for c in cols)
        return (n_rows > 0 and (has_idx or bool(md)), f"rows={n_rows} index={has_idx}")
    if mode == "explain":
        expl = md.get("explanation")
        ok = bool(expl) and (len(expl) if hasattr(expl, "__len__") else True)
        return (bool(ok), f"explanation_present={bool(expl)}")
    # "nonempty"
    return (n_rows > 0, f"rows={n_rows}")


def _dispatch_pt(query: str) -> str | None:
    """Deterministic keyword-cascade routing (no LLM) — a free cross-check that isolates the
    keyword router from the manager's LLM entity extraction."""
    st = create_initial_state(query)
    try:
        return _select_prediction_type(st)
    except Exception:
        return None


def run(task_filter: str | None, dispatch_only: bool) -> list[dict]:
    fixtures = json.loads(FIXTURES.read_text())
    rows: list[dict] = []
    transcripts: list[dict] = []
    for block in fixtures["tasks"]:
        task = block["task"]
        if task_filter and task != task_filter:
            continue
        expected = block["expected_prediction_type"]
        mode = block["score_mode"]
        for i, qobj in enumerate(block["questions"]):
            query = qobj["query"]
            print(f"  [{task}] {query[:70]}")
            dispatch_pt = _dispatch_pt(query)
            if dispatch_only:
                rows.append({"task": task, "query": query, "score_mode": mode,
                             "expected": expected, "resolved": dispatch_pt,
                             "routing_ok": dispatch_pt == expected, "plausible": None,
                             "note": "dispatch-only (no agent run)", "error": None})
                continue
            try:
                final = run_agent(user_query=query, variant="no_control", model="claude",
                                  experiment="prediction_eval", condition="mas", verbose=False)
                resolved = _resolved_task(final)
                err = final.get("error")
                # plausibility is isolated: a scorer bug must never discard a valid routing result
                try:
                    plausible, note = _plausible(mode, final)
                except Exception as sexc:
                    plausible, note = False, f"scorer-exception: {str(sexc)[:70]}"
                transcripts.append({
                    "task": task, "query": query, "resolved": resolved,
                    "sentinel": (final.get("sql_query") or "")[:120],
                    "final_response": (final.get("final_response") or "")[:400],
                    "prediction_metadata_keys": list((final.get("prediction_metadata") or {}).keys()),
                    "error": err,
                })
            except Exception as exc:
                resolved, plausible, note, err = None, False, f"agent-exception: {str(exc)[:80]}", str(exc)[:120]
            rows.append({"task": task, "query": query, "score_mode": mode,
                         "expected": expected, "resolved": resolved,
                         "routing_ok": resolved == expected,
                         "dispatch_pt": dispatch_pt, "dispatch_ok": dispatch_pt == expected,
                         "plausible": plausible, "note": note, "error": err})
    # persist
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if transcripts:
        (RESULTS_DIR / "transcripts.json").write_text(json.dumps(transcripts, indent=2, default=str))
    if rows:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_CSV, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=None, help="run only this task block")
    ap.add_argument("--dispatch-only", action="store_true",
                    help="deterministic keyword routing only, no agent/LLM calls")
    args = ap.parse_args()
    rows = run(args.task, args.dispatch_only)
    n = len(rows)
    route = sum(1 for r in rows if r["routing_ok"])
    plaus = sum(1 for r in rows if r.get("plausible"))
    print(f"\n{route}/{n} routed correctly; {plaus}/{n} plausible. CSV -> {RESULTS_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
