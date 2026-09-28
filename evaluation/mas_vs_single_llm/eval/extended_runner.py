"""
eval/extended_runner.py — SINGLE-RUN rerun of all conditions on the EXTENDED v2 golden set.

Conditions (model = claude / Opus 4.8, per the brief):
  * mas                — the autonomous MAS (manager → discovery → data_analyst[autonomous] → synth).
  * single_llm_tools   — one LLM with the SAME tools (run_sql + predict_match_outcome), no orchestration.
  * single_llm_rawdata — one LLM, no tools, answering from an inlined ENG-PL data dump
                         (DA) / recent-form dump (prediction). Only the answerable subset applies.

Internal-consistency fix for the historical 40-vs-41 discrepancy (see the report): the autonomous
MAS is run EXACTLY ONCE per question here; there is no separate DoF-vs-MVS duplicate invocation, so
"the same config on the same question" yields one number by construction.

Persistence rule: every raw run is written to disk BEFORE any scoring, one file per
(question × condition): results/runs/extended_da/<QID>_<cond>_claude_r0.json and
results/runs/extended_pred/<PID>_<cond>_claude_r0.json. Resumable: an existing, non-error file is
kept; delete a file (or pass overwrite) to re-run just that cell.

Usage:
  python -m eval.extended_runner da           # 30 DA × 3 conditions
  python -m eval.extended_runner pred         # 30 prediction × 3 conditions
  python -m eval.extended_runner all          # both
  python -m eval.extended_runner da Q01 Q09   # only these DA ids (smoke test)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from conditions.mas_runner import run_mas
from conditions.single_llm import (run_single_llm_tools, run_single_llm_rawdata,
                                    run_single_llm_rawdata_prediction)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "results" / "golden" / "golden_set_v2.json"
PRED = ROOT / "results" / "golden" / "prediction_golden_v2.json"
DA_DIR = ROOT / "results" / "runs" / "extended_da"
PRED_DIR = ROOT / "results" / "runs" / "extended_pred"

MODEL = "claude"
DA_CONDITIONS = ["mas", "single_llm_tools", "single_llm_rawdata"]
PRED_CONDITIONS = ["mas", "single_llm_tools", "single_llm_rawdata"]


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text())["items"]


def _retry(fn, attempts: int = 3, backoff=(10, 30)):
    last = None
    for a in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = str(e)
            if a < attempts - 1:
                time.sleep(backoff[min(a, len(backoff) - 1)])
    raise RuntimeError(last)


def _run_da_cond(cond: str, it: dict) -> dict:
    q, qid = it["question"], it["id"]
    if cond == "mas":
        rec = run_mas(q, model=MODEL, analyst_mode="autonomous", experiment="extended_da",
                      question_id=qid, repeat=0)
    elif cond == "single_llm_tools":
        rec = run_single_llm_tools(q, model=MODEL, question_id=qid, repeat=0, experiment="extended_da")
    else:  # single_llm_rawdata
        rec = run_single_llm_rawdata(q, model=MODEL, question_id=qid, repeat=0)
        rec["experiment"] = "extended_da"
    rec["condition"] = cond
    return rec


def _run_pred_cond(cond: str, it: dict) -> dict:
    q, qid = it["question"], it["id"]
    if cond == "mas":
        rec = run_mas(q, model=MODEL, analyst_mode="autonomous", experiment="extended_pred",
                      question_id=qid, repeat=0)
    elif cond == "single_llm_tools":
        rec = run_single_llm_tools(q, model=MODEL, question_id=qid, repeat=0, experiment="extended_pred")
    else:  # single_llm_rawdata (LLM-as-forecaster, no model/tools)
        rec = run_single_llm_rawdata_prediction(
            q, it["home_team"], it["away_team"], it["match_date"], model=MODEL,
            question_id=qid, repeat=0, experiment="extended_pred")
    rec["condition"] = cond
    return rec


def _run_batch(items: list[dict], conditions: list[str], out_dir: Path, run_cond, overwrite: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(items) * len(conditions)
    n = errs = 0
    for cond in conditions:
        for it in items:
            n += 1
            out = out_dir / f"{it['id']}_{cond}_{MODEL}_r0.json"
            if out.exists() and not overwrite:
                try:
                    if not json.loads(out.read_text()).get("error"):
                        print(f"[{n}/{total}] {it['id']:4} {cond:20} CACHED")
                        continue
                except Exception:
                    pass
            t = time.time()
            try:
                rec = _retry(lambda: run_cond(cond, it))
            except Exception as e:  # noqa: BLE001
                rec = {"question_id": it["id"], "question": it["question"], "condition": cond,
                       "model": MODEL, "repeat": 0, "error": str(e)[:300], "answer": "",
                       "tool_sequence": [], "prediction_vector": None}
                errs += 1
            out.write_text(json.dumps(rec, indent=2, default=str))  # persist BEFORE scoring
            dt = round(time.time() - t, 1)
            tag = f"ERROR {str(rec.get('error'))[:50]}" if rec.get("error") else \
                  (f"vec={rec.get('prediction_vector')}" if rec.get("prediction_vector") is not None
                   else f"tools={rec.get('tool_sequence')}")
            print(f"[{n}/{total}] {it['id']:4} {cond:20} ({dt}s) {tag}")
            if not rec.get("error"):
                print(f"        -> {str(rec.get('answer',''))[:100]!r}")
    print(f"\nDone {out_dir.name}: {n} cells, {errs} errors.")


def run_da(question_ids: list[str] | None = None, overwrite: bool = False):
    items = _load(GOLDEN)
    if question_ids:
        items = [it for it in items if it["id"] in question_ids]
    print(f"Extended DA: {len(items)} questions × {len(DA_CONDITIONS)} conditions (model={MODEL})\n")
    _run_batch(items, DA_CONDITIONS, DA_DIR, _run_da_cond, overwrite)


def run_pred(question_ids: list[str] | None = None, overwrite: bool = False):
    items = _load(PRED)
    if question_ids:
        items = [it for it in items if it["id"] in question_ids]
    print(f"Extended prediction: {len(items)} questions × {len(PRED_CONDITIONS)} conditions (model={MODEL})\n")
    _run_batch(items, PRED_CONDITIONS, PRED_DIR, _run_pred_cond, overwrite)


# Priority order (credit-safe): finish EACH condition across BOTH question sets before starting the
# next, so if we run out of API credit the most important condition (MAS) is complete end-to-end.
CONDITION_PRIORITY = ["mas", "single_llm_tools", "single_llm_rawdata"]


def run_by_condition(overwrite: bool = False):
    da_items, pred_items = _load(GOLDEN), _load(PRED)
    for cond in CONDITION_PRIORITY:
        print(f"\n========== CONDITION: {cond}  (DA {len(da_items)} + pred {len(pred_items)}) ==========\n")
        _run_batch(da_items, [cond], DA_DIR, _run_da_cond, overwrite)
        _run_batch(pred_items, [cond], PRED_DIR, _run_pred_cond, overwrite)
        print(f"\n########## CONDITION COMPLETE: {cond} ##########\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    ids = [a for a in sys.argv[2:] if a not in ("--overwrite",)] or None
    ow = "--overwrite" in sys.argv
    if cmd == "all":                       # credit-safe: all MAS, then all tools, then all rawdata
        run_by_condition(ow)
    elif cmd == "da":
        run_da(ids, ow)
    elif cmd == "pred":
        run_pred(ids, ow)
