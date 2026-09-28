"""
eval/runner.py — DoF experiment runner (Phase 5).

The DoF experiment is the MAS run at three analyst autonomy levels × three models. Each
(question × mode × model × repeat) is executed via run_mas(experiment="dof", analyst_mode=mode)
and the raw run is PERSISTED to results/runs/dof/ BEFORE any scoring (spec persistence rule).

Usage:
  python -m eval.runner pilot                 # claude × 3 modes × 3 questions
  python -m eval.runner full [repeats]        # all models × 3 modes × all 46 questions
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from config import MODEL_FAMILIES
from conditions.mas_runner import run_mas
from conditions.single_llm import (run_single_llm_tools, run_single_llm_rawdata,
                                   run_single_llm_rawdata_prediction)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "results" / "golden" / "golden_set.json"
PRED_GOLDEN = ROOT / "results" / "golden" / "prediction_golden.json"
DOF_DIR = ROOT / "results" / "runs" / "dof"
MVS_DIR = ROOT / "results" / "runs" / "mas_vs_single"
PRED_DIR = ROOT / "results" / "runs" / "prediction"
MODES = ["controlled", "semi", "autonomous"]
PRED_CONDITIONS = ["mas", "single_llm_tools", "single_llm_rawdata"]

# MAS-vs-single conditions. MAS uses the chosen DoF-winner analyst mode (autonomous, per Till).
MVS_ANALYST_MODE = "autonomous"
MVS_CONDITIONS = {
    "mas": lambda q, model, qid, rep: run_mas(q, model=model, analyst_mode=MVS_ANALYST_MODE,
                                              experiment="mas_vs_single", question_id=qid, repeat=rep),
    "single_llm_tools": lambda q, model, qid, rep: run_single_llm_tools(q, model=model, question_id=qid, repeat=rep),
    "single_llm_rawdata": lambda q, model, qid, rep: run_single_llm_rawdata(q, model=model, question_id=qid, repeat=rep),
}
PILOT_QUESTIONS = ["Q02", "Q09", "Q24"]   # Q02/Q09 in-coverage; Q24 out-of-coverage (controlled should struggle)


def load_golden() -> list[dict]:
    return json.load(open(GOLDEN))["items"]


def _run_one(question: str, model: str, mode: str, qid: str, rep: int, attempts: int = 3) -> dict:
    """Run one MAS pass with retries + backoff on transient errors (helps rate limits, not hard quota)."""
    last = None
    backoff = [10, 30]
    for a in range(attempts):
        try:
            return run_mas(question, model=model, analyst_mode=mode,
                           experiment="dof", question_id=qid, repeat=rep)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            if a < attempts - 1:
                time.sleep(backoff[min(a, len(backoff) - 1)])
    # both attempts failed → persist an error record so the batch continues and is resumable
    return {"question_id": qid, "question": question, "experiment": "dof",
            "condition": f"dof_{mode}", "analyst_mode": mode, "model": model, "repeat": rep,
            "error": last, "answer": "", "tool_sequence": [], "sql": None, "template": None,
            "low_confidence": True, "trace": []}


def run_dof(models: list[str], modes: list[str] = MODES, question_ids: list[str] | None = None,
            repeats: int = 1, overwrite: bool = False) -> list[dict]:
    DOF_DIR.mkdir(parents=True, exist_ok=True)
    items = load_golden()
    if question_ids:
        items = [it for it in items if it["id"] in question_ids]
    total = len(models) * len(modes) * len(items) * repeats
    print(f"DoF runner: {len(models)} models × {len(modes)} modes × {len(items)} questions × {repeats} "
          f"repeats = {total} runs (resume={'off' if overwrite else 'on'})\n")

    summary, n, errors = [], 0, 0
    for model in models:
        for mode in modes:
            for it in items:
                for rep in range(repeats):
                    n += 1
                    out_path = DOF_DIR / f"{it['id']}_dof_{mode}_{model}_r{rep}.json"
                    if out_path.exists() and not overwrite:
                        try:
                            rec = json.loads(out_path.read_text())
                            summary.append({"id": it["id"], "mode": mode, "model": model, "repeat": rep,
                                            "tool_sequence": rec.get("tool_sequence", []),
                                            "cached": True, "error": rec.get("error")})
                            print(f"[{n}/{total}] {it['id']:4} {mode:11} {model:8} r{rep}  CACHED")
                            continue
                        except Exception:
                            pass  # corrupt file → re-run
                    t = time.time()
                    rec = _run_one(it["question"], model, mode, it["id"], rep)
                    out_path.write_text(json.dumps(rec, indent=2, default=str))  # persist BEFORE scoring
                    err = rec.get("error")
                    errors += bool(err)
                    summary.append({"id": it["id"], "mode": mode, "model": model, "repeat": rep,
                                    "tool_sequence": rec.get("tool_sequence", []),
                                    "answer": rec.get("answer", "")[:70], "error": err})
                    tag = "ERROR" if err else f"tools={rec.get('tool_sequence')}"
                    print(f"[{n}/{total}] {it['id']:4} {mode:11} {model:8} r{rep} "
                          f"({round(time.time()-t,1)}s) {tag}")
                    if not err:
                        print(f"        -> {rec.get('answer','')[:90]!r}")
                    else:
                        print(f"        -> ERROR: {str(err)[:90]}")
    print(f"\nDone: {n} runs, {errors} errors.")
    return summary


def _run_cond(fn, cond: str, model: str, q: str, qid: str, rep: int, attempts: int = 3) -> dict:
    """Run one MAS-vs-single condition with retries + backoff; normalize record fields."""
    last, backoff = None, [10, 30]
    for a in range(attempts):
        try:
            rec = fn(q, model, qid, rep)
            rec["experiment"] = "mas_vs_single"
            rec["condition"] = cond
            rec["repeat"] = rep
            return rec
        except Exception as e:  # noqa: BLE001
            last = str(e)
            if a < attempts - 1:
                time.sleep(backoff[min(a, len(backoff) - 1)])
    return {"question_id": qid, "question": q, "experiment": "mas_vs_single", "condition": cond,
            "model": model, "repeat": rep, "error": last, "answer": "", "tool_sequence": [], "trace": []}


def run_mas_vs_single(models: list[str], conditions: list[str] | None = None,
                      question_ids: list[str] | None = None, repeats: int = 1,
                      overwrite: bool = False) -> list[dict]:
    MVS_DIR.mkdir(parents=True, exist_ok=True)
    conds = conditions or list(MVS_CONDITIONS)
    items = load_golden()
    if question_ids:
        items = [it for it in items if it["id"] in question_ids]
    total = len(models) * len(conds) * len(items) * repeats
    print(f"MAS-vs-single: {len(models)} models × {len(conds)} conditions × {len(items)} questions × "
          f"{repeats} repeats = {total} runs (MAS analyst_mode={MVS_ANALYST_MODE}, resume="
          f"{'off' if overwrite else 'on'})\n")
    summary, n, errors = [], 0, 0
    for model in models:
        for cond in conds:
            for it in items:
                for rep in range(repeats):
                    n += 1
                    out = MVS_DIR / f"{it['id']}_{cond}_{model}_r{rep}.json"
                    if out.exists() and not overwrite:
                        try:
                            rec = json.loads(out.read_text())
                            summary.append({"id": it["id"], "condition": cond, "error": rec.get("error")})
                            print(f"[{n}/{total}] {it['id']:4} {cond:20} {model:7} r{rep}  CACHED")
                            continue
                        except Exception:
                            pass
                    t = time.time()
                    rec = _run_cond(MVS_CONDITIONS[cond], cond, model, it["question"], it["id"], rep)
                    out.write_text(json.dumps(rec, indent=2, default=str))
                    err = rec.get("error")
                    errors += bool(err)
                    summary.append({"id": it["id"], "condition": cond, "error": err})
                    tag = "ERROR" if err else f"tools={rec.get('tool_sequence')}"
                    print(f"[{n}/{total}] {it['id']:4} {cond:20} {model:7} r{rep} "
                          f"({round(time.time()-t,1)}s) {tag}")
                    if not err:
                        print(f"        -> {rec.get('answer','')[:90]!r}")
                    else:
                        print(f"        -> ERROR: {str(err)[:90]}")
    print(f"\nDone: {n} runs, {errors} errors.")
    return summary


def _run_prediction_cond(cond: str, it: dict, model: str, rep: int) -> dict:
    if cond == "mas":
        return run_mas(it["question"], model=model, analyst_mode="autonomous",
                       experiment="prediction", question_id=it["id"], repeat=rep)
    if cond == "single_llm_tools":
        return run_single_llm_tools(it["question"], model=model, question_id=it["id"],
                                    repeat=rep, experiment="prediction")
    return run_single_llm_rawdata_prediction(
        it["question"], it["home_team"], it["away_team"], it["match_date"],
        model=model, question_id=it["id"], repeat=rep, experiment="prediction")


def run_prediction(models: list[str] | None = None, conditions: list[str] | None = None,
                   repeats: int = 1, overwrite: bool = False) -> list[dict]:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    models = models or ["claude"]
    conds = conditions or PRED_CONDITIONS
    items = json.loads(PRED_GOLDEN.read_text())["items"]
    total = len(models) * len(conds) * len(items) * repeats
    print(f"Prediction slice: {len(models)} models × {len(conds)} conditions × {len(items)} questions "
          f"× {repeats} repeats = {total} runs\n")
    summary, n, errors = [], 0, 0
    for model in models:
        for cond in conds:
            for it in items:
                for rep in range(repeats):
                    n += 1
                    out = PRED_DIR / f"{it['id']}_{cond}_{model}_r{rep}.json"
                    if out.exists() and not overwrite:
                        print(f"[{n}/{total}] {it['id']} {cond:20} {model} r{rep}  CACHED")
                        continue
                    t = time.time()
                    try:
                        rec = _run_prediction_cond(cond, it, model, rep)
                    except Exception as e:  # noqa: BLE001
                        rec = {"question_id": it["id"], "question": it["question"],
                               "experiment": "prediction", "condition": cond, "model": model,
                               "repeat": rep, "error": str(e)[:200], "answer": "",
                               "prediction_vector": None, "tool_sequence": []}
                    out.write_text(json.dumps(rec, indent=2, default=str))
                    err = rec.get("error")
                    errors += bool(err)
                    pv = rec.get("prediction_vector")
                    print(f"[{n}/{total}] {it['id']} {cond:20} {model} r{rep} "
                          f"({round(time.time()-t,1)}s) {'ERROR '+str(err)[:60] if err else 'vec='+str(pv)}")
    print(f"\nDone: {n} runs, {errors} errors.")
    return summary


def _acceptance(summary: list[dict]) -> None:
    bad = []
    for s in summary:
        if s["mode"] == "controlled" and "run_sql" in s["tool_sequence"]:
            bad.append(f"{s['id']}/{s['model']}: controlled used run_sql")
        if s["mode"] == "autonomous" and "use_template" in s["tool_sequence"]:
            bad.append(f"{s['id']}/{s['model']}: autonomous used use_template")
    print("\nACCEPTANCE:", "OK — tool-access differences hold" if not bad else f"VIOLATIONS: {bad}")


def delete_tokenless_mvs_single(dry: bool = False) -> int:
    """Delete MAS-vs-single single-LLM runs that lack token_usage (or errored), so a resumed
    run (no overwrite) re-fills ONLY those — used to finish token capture after a quota interruption."""
    n = 0
    for cond in ("single_llm_tools", "single_llm_rawdata"):
        for f in MVS_DIR.glob(f"*_{cond}_claude_r0.json"):
            r = json.loads(f.read_text())
            if r.get("error") or not (r.get("token_usage") or {}).get("total"):
                n += 1
                if not dry:
                    f.unlink()
    return n


def delete_error_runs() -> int:
    """Delete DoF run files that hold an error record, so a resumed 'full' re-runs exactly those."""
    deleted = 0
    for f in DOF_DIR.glob("*_dof_*_r*.json"):
        try:
            if json.loads(f.read_text()).get("error"):
                f.unlink(); deleted += 1
        except Exception:
            pass
    return deleted


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    if cmd == "pilot":
        s = run_dof(models=["claude"], question_ids=PILOT_QUESTIONS, repeats=1)
        _acceptance(s)
    elif cmd == "full":
        reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        s = run_dof(models=MODEL_FAMILIES, repeats=reps)
        _acceptance(s)
    elif cmd == "mas-vs-single":
        reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        run_mas_vs_single(models=["claude"], repeats=reps)
    elif cmd == "prediction":
        reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        run_prediction(models=["claude"], repeats=reps)
    elif cmd == "retry-mvs-tokens":
        d = delete_tokenless_mvs_single()
        print(f"Deleted {d} token-less single-LLM runs; re-running them (resume, no overwrite)...")
        run_mas_vs_single(models=["claude"],
                          conditions=["single_llm_tools", "single_llm_rawdata"], repeats=1)
    elif cmd == "retry-errors":
        d = delete_error_runs()
        print(f"Deleted {d} error-record files. Re-run `python -m eval.runner full 1` to refill them "
              "(resume keeps the good runs).")
    else:
        print(__doc__)
