"""
eval/extended_score.py — score the extended-set runs against the frozen v2 ground truth.

Scores are derived ONLY from stored raw runs + frozen ground_truth_v2.json (never by re-running a
model). DA correctness uses the condition-agnostic answer-text scorer (eval.score.score_run_text),
so MAS / single+tools / single+rawdata are judged on the SAME basis (their final answer text).

Outputs (one row per question × condition), written to results/scores/:
  * extended_da_scores.json    — id, condition, category, coverage, verdict, correct(bool),
                                 raw_answerable(bool), tokens, latency_s, error
  * extended_pred_scores.json  — id, condition, prediction_vector, delegated(bool),
                                 fidelity(bool|None), brier, tokens, latency_s, error
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.score import score_run_text, _brier, _fidelity

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "results" / "golden" / "golden_set_v2.json"
GT = ROOT / "results" / "golden" / "ground_truth_v2.json"
PRED = ROOT / "results" / "golden" / "prediction_golden_v2.json"
DA_DIR = ROOT / "results" / "runs" / "extended_da"
PRED_DIR = ROOT / "results" / "runs" / "extended_pred"
SCORES = ROOT / "results" / "scores"

# The single_llm_rawdata dump inlines only these ENG-PL team/player-season tables. A question is
# answerable from the dump iff its category is one of these — EXCEPT Q25 (referee counts) whose
# source (matches.referee) is not in the dump.
RAW_DUMP_CATEGORIES = {"team_league_outcomes", "player_season_aggregates",
                       "home_away_splits", "disciplinary", "xg_performance"}
RAW_UNANSWERABLE_IDS = {"Q25"}   # referee data absent from the dump


def _load_da():
    gold = {it["id"]: it for it in json.loads(GOLDEN.read_text())["items"]}
    gt = {it["id"]: it.get("ground_truth") for it in json.loads(GT.read_text())["items"]}
    return gold, gt


def _raw_answerable(item: dict) -> bool:
    return item["category"] in RAW_DUMP_CATEGORIES and item["id"] not in RAW_UNANSWERABLE_IDS


def score_da() -> list[dict]:
    gold, gt = _load_da()
    SCORES.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(DA_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        qid = rec.get("question_id")
        if qid not in gold:
            continue
        verdict = score_run_text(rec, gold, gt)
        rows.append({
            "id": qid, "condition": rec.get("condition"),
            "category": gold[qid]["category"], "coverage": gold[qid]["coverage_label"],
            "answer_type": gold[qid]["answer_type"], "difficulty": gold[qid]["difficulty"],
            "raw_answerable": _raw_answerable(gold[qid]),
            "verdict": verdict, "correct": int(verdict == "correct"),
            "tokens": (rec.get("token_usage") or {}).get("total"),
            "latency_s": rec.get("latency_s"), "error": rec.get("error"), "file": path.name,
        })
    (SCORES / "extended_da_scores.json").write_text(json.dumps({"scores": rows}, indent=2))
    return rows


def _delegated(rec: dict) -> bool:
    """Did the condition delegate to the predict_match_outcome model?"""
    if "predict_match_outcome" in (rec.get("tool_sequence") or []):
        return True
    # MAS prediction path records the model vector without a named tool_sequence entry in older recs
    if rec.get("condition") == "mas" and rec.get("prediction_vector") is not None:
        return True
    return False


def score_pred() -> list[dict]:
    gold = {it["id"]: it for it in json.loads(PRED.read_text())["items"]}
    SCORES.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(PRED_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        qid = rec.get("question_id")
        g = gold.get(qid)
        if not g:
            continue
        vec = rec.get("prediction_vector")
        cond = rec.get("condition")
        rows.append({
            "id": qid, "condition": cond, "prediction_vector": vec,
            "delegated": _delegated(rec),
            "fidelity": (_fidelity(vec, g.get("model_gt")) if cond != "single_llm_rawdata" else None),
            "brier": _brier(vec, g["actual_onehot"]),
            "actual": g["actual"], "model_gt": {k: g["model_gt"].get(k) for k in ("home_win", "draw", "away_win")},
            "tokens": (rec.get("token_usage") or {}).get("total"),
            "latency_s": rec.get("latency_s"), "error": rec.get("error"), "file": path.name,
        })
    (SCORES / "extended_pred_scores.json").write_text(json.dumps({"scores": rows}, indent=2))
    return rows


def _acc(rows, pred=lambda r: True):
    sel = [r for r in rows if pred(r) and r["verdict"] != "error"]
    c = sum(r["correct"] for r in sel)
    return c, len(sel), (100 * c / len(sel) if sel else 0.0)


def summarize():
    da = score_da()
    pred = score_pred()
    conds = ["mas", "single_llm_tools", "single_llm_rawdata"]
    print("=== DA accuracy (answer-text scorer) ===")
    print(f"{'condition':22}{'overall':16}{'in_coverage':16}{'out_of_coverage':18}{'raw_answerable':16}")
    for c in conds:
        rc = [r for r in da if r["condition"] == c]
        o = _acc(rc); i = _acc(rc, lambda r: r["coverage"] == "in_coverage")
        ot = _acc(rc, lambda r: r["coverage"] == "out_of_coverage")
        ra = _acc(rc, lambda r: r["raw_answerable"])
        print(f"{c:22}{f'{o[0]}/{o[1]} ({o[2]:.0f}%)':16}{f'{i[0]}/{i[1]} ({i[2]:.0f}%)':16}"
              f"{f'{ot[0]}/{ot[1]} ({ot[2]:.0f}%)':18}{f'{ra[0]}/{ra[1]} ({ra[2]:.0f}%)':16}")
    print("\n=== Prediction ===")
    print(f"{'condition':22}{'n':4}{'delegated':12}{'fidelity':12}{'mean_brier':12}")
    for c in conds:
        rc = [r for r in pred if r["condition"] == c and not r["error"]]
        deleg = sum(r["delegated"] for r in rc)
        fids = [r["fidelity"] for r in rc if r["fidelity"] is not None]
        briers = [r["brier"] for r in rc if r["brier"] is not None]
        fid_s = f"{sum(fids)}/{len(fids)}" if fids else "n/a"
        mb = f"{sum(briers)/len(briers):.4f}" if briers else "n/a"
        print(f"{c:22}{len(rc):<4}{f'{deleg}/{len(rc)}':12}{fid_s:12}{mb:12}")
    # identical-vector check MAS vs single_llm_tools
    by = {}
    for r in pred:
        by.setdefault(r["id"], {})[r["condition"]] = r["prediction_vector"]
    ident = sum(1 for q, d in by.items() if d.get("mas") == d.get("single_llm_tools") and d.get("mas") is not None)
    print(f"\nMAS vs single_llm_tools identical forecast vectors: {ident}/{len(by)}")


if __name__ == "__main__":
    summarize()
