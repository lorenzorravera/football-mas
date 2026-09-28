"""
eval/score.py — programmatic scoring of stored runs against frozen ground truth (Phase 5).

Scores are derived ONLY from stored raw runs + frozen ground_truth.json — never by re-running a model.

Scoring policy (Till approved keeping synthesizer reasoning, so the final ANSWER is what's judged):
  * scalar       : the ground-truth value(s) must appear in the final answer text (numeric tolerance;
                   name match case-insensitive). This credits the synthesizer's computed answer
                   (e.g. controlled summing per-team red cards to the league total).
  * ranking/table: the retrieved result_rows must contain the ground-truth rows (numeric tolerance) —
                   ordered for 'ranking'. (The prose can't list 20 rows; the produced data is judged.)
  * empty GT     : correct iff the answer acknowledges no data / not-present.
Verdicts: correct / partial / wrong / refused / error.
LLM-judge is reserved for genuine free-text (a different model family than the one evaluated); the
current golden set has none, so all 46 are scored programmatically.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "results" / "golden" / "golden_set.json"
GT = ROOT / "results" / "golden" / "ground_truth.json"
COV = ROOT / "results" / "templates" / "coverage_labels.json"
DOF_DIR = ROOT / "results" / "runs" / "dof"
SCORES_DIR = ROOT / "results" / "scores"

_DENIAL = ["no data", "not in", "didn't", "did not", "no record", "not present", "not available",
           "weren't", "were not", "wasn't", "not found", "no results", "not relegated", "not a premier"]


def _load():
    gold = {it["id"]: it for it in json.loads(GOLDEN.read_text())["items"]}
    gt = {it["id"]: it.get("ground_truth") for it in json.loads(GT.read_text())["items"]}
    cov = {it["id"]: it["coverage_label"] for it in json.loads(COV.read_text())["items"]}
    return gold, gt, cov


def _nums(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", str(text))]


def _num_in(target: float, pool: list[float]) -> bool:
    tol = max(0.5, abs(target) * 0.01)   # exact-ish for ints, 1% for larger/decimals
    return any(abs(target - p) <= tol for p in pool)


def _cells(row: list):
    nums, strs = [], []
    for v in row:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            nums.append(float(v))
        elif isinstance(v, str) and re.search(r"[A-Za-z]{3,}", v):
            strs.append(v.strip().lower())
    return nums, strs


def _score_scalar(answer: str, gt_row: list) -> str:
    gt_nums, gt_strs = _cells(gt_row)
    a_nums = _nums(answer)
    al = answer.lower()
    nums_ok = all(_num_in(n, a_nums) for n in gt_nums) if gt_nums else True
    strs_ok = all(s in al for s in gt_strs) if gt_strs else True
    if nums_ok and strs_ok:
        return "correct"
    if (gt_nums and any(_num_in(n, a_nums) for n in gt_nums)) or (gt_strs and any(s in al for s in gt_strs)):
        return "partial"
    return "wrong"


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return None if v is None else str(v).strip().lower()


def _score_table(result_rows, gt_rows) -> str:
    if not result_rows:
        return "wrong"
    out_sets = [{_norm(v) for v in r if v is not None} for r in result_rows]
    hits = 0
    for g in gt_rows:
        gsig = {_norm(v) for v in g if v is not None}
        if any(gsig <= s for s in out_sets):
            hits += 1
    if hits == len(gt_rows):
        return "correct"
    return "partial" if hits >= max(1, len(gt_rows) // 2) else "wrong"


def score_run(rec: dict, gold: dict, gt: dict) -> str:
    if rec.get("error"):
        return "error"
    answer = (rec.get("answer") or "").strip()
    if not answer:
        return "refused"
    qid = rec["question_id"]
    g = gt.get(qid)
    at = gold[qid]["answer_type"]
    if not g or g["row_count"] == 0:           # empty ground truth (e.g. Norwich not in PL)
        return "correct" if any(p in answer.lower() for p in _DENIAL) else "wrong"
    if at == "scalar":
        return _score_scalar(answer, g["rows"][0])
    return _score_table(rec.get("result_rows"), g["rows"])   # ranking / table → judge produced data


def _score_answer_coverage(answer: str, gt_rows: list) -> str:
    """Unified answer-text scoring (used for MAS-vs-single, where single-LLM has no result_rows):
    each ground-truth row's name(s) + value(s) must appear in the answer text. correct=all rows
    covered, partial=>=half, wrong=<half. Consistent across MAS / single+tools / single+raw."""
    al = answer.lower()
    a_nums = _nums(answer)
    covered = 0
    for row in gt_rows:
        nums, strs = _cells(row)
        nums_ok = all(_num_in(n, a_nums) for n in nums) if nums else True
        strs_ok = all(s in al for s in strs) if strs else True
        if nums_ok and strs_ok:
            covered += 1
    if covered == len(gt_rows):
        return "correct"
    return "partial" if covered >= max(1, len(gt_rows) // 2) else "wrong"


def score_run_text(rec: dict, gold: dict, gt: dict) -> str:
    """Score a run by its final ANSWER text (condition-agnostic)."""
    if rec.get("error"):
        return "error"
    answer = (rec.get("answer") or "").strip()
    if not answer:
        return "refused"
    qid = rec["question_id"]
    g = gt.get(qid)
    if not g or g["row_count"] == 0:
        return "correct" if any(p in answer.lower() for p in _DENIAL) else "wrong"
    return _score_answer_coverage(answer, g["rows"])


def score_mvs() -> dict:
    """Score the MAS-vs-single experiment (results/runs/mas_vs_single/) by answer text."""
    gold, gt, cov = _load()
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    mvs_dir = ROOT / "results" / "runs" / "mas_vs_single"
    per_run = []
    for path in sorted(mvs_dir.glob("*.json")):
        rec = json.loads(path.read_text())
        qid = rec.get("question_id")
        if qid not in gold:
            continue
        per_run.append({"id": qid, "condition": rec.get("condition"), "model": rec.get("model"),
                        "category": gold[qid]["category"], "coverage": cov.get(qid),
                        "verdict": score_run_text(rec, gold, gt),
                        "latency_s": rec.get("latency_s"), "error": rec.get("error")})
    (SCORES_DIR / "mvs_scores.json").write_text(json.dumps({"scores": per_run}, indent=2))
    return {"per_run": per_run}


def _aggregate_mvs(per_run: list[dict]) -> None:
    from collections import Counter, defaultdict
    def acc(rows):
        rows = [r for r in rows if r["verdict"] != "error"]
        c = sum(r["verdict"] == "correct" for r in rows)
        return f"{c}/{len(rows)} ({(100*c/len(rows) if rows else 0):.0f}%)"
    conds = ["mas", "single_llm_tools", "single_llm_rawdata"]
    bycond = defaultdict(list)
    for r in per_run:
        bycond[r["condition"]].append(r)
    print(f"\nTotal scored: {len(per_run)}  verdicts: {dict(Counter(r['verdict'] for r in per_run))}")
    print("\n=== MAS vs single — overall, by coverage, avg latency ===")
    for c in conds:
        rows = bycond.get(c, [])
        ins = [r for r in rows if r["coverage"] == "in_coverage"]
        outs = [r for r in rows if r["coverage"] == "out_of_coverage"]
        lat = [r["latency_s"] for r in rows if r.get("latency_s")]
        errs = sum(r["verdict"] == "error" for r in rows)
        print(f"  {c:20} overall={acc(rows):14} in={acc(ins):14} out={acc(outs):14} "
              f"avg_lat={(sum(lat)/len(lat) if lat else 0):5.1f}s errors={errs}")
    # by category
    cats = sorted({r["category"] for r in per_run})
    print("\n=== accuracy by category × condition ===")
    print(f"  {'category':26}" + "".join(f"{c.split('_')[-1][:8]:>10}" for c in conds))
    for cat in cats:
        line = f"  {cat:26}"
        for c in conds:
            line += f"{acc([r for r in bycond[c] if r['category']==cat]):>10}"
        print(line)


def score_dof() -> dict:
    gold, gt, cov = _load()
    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    per_run = []
    for path in sorted(DOF_DIR.glob("*_dof_*_r*.json")):
        rec = json.loads(path.read_text())
        qid = rec.get("question_id")
        if qid not in gold:
            continue
        verdict = score_run(rec, gold, gt)
        per_run.append({"id": qid, "mode": rec.get("analyst_mode") or rec.get("mode"),
                        "model": rec.get("model"), "repeat": rec.get("repeat", 0),
                        "coverage": cov.get(qid), "answer_type": gold[qid]["answer_type"],
                        "verdict": verdict, "file": path.name})
    (SCORES_DIR / "dof_scores.json").write_text(json.dumps({"scores": per_run}, indent=2))
    return {"per_run": per_run}


def _aggregate(per_run: list[dict]) -> None:
    def acc(rows):
        c = sum(r["verdict"] == "correct" for r in rows)
        return f"{c}/{len(rows)} ({(c/len(rows)*100 if rows else 0):.0f}%)"
    print(f"\nTotal scored: {len(per_run)}")
    from collections import Counter
    print("verdicts:", dict(Counter(r["verdict"] for r in per_run)))
    print("\nAccuracy by mode × coverage:")
    cells = defaultdict(list)
    for r in per_run:
        cells[(r["mode"], r["coverage"])].append(r)
    for mode in ["controlled", "semi", "autonomous"]:
        line = f"  {mode:11}"
        for c in ["in_coverage", "out_of_coverage"]:
            line += f"  {c}={acc(cells.get((mode, c), []))}"
        print(line)
    print("\nAccuracy by model:")
    bym = defaultdict(list)
    for r in per_run:
        bym[r["model"]].append(r)
    for m, rows in bym.items():
        print(f"  {m:8} {acc(rows)}")


def _brier(vec: dict, onehot: list) -> float | None:
    """Multiclass Brier = mean over {home,draw,away} of (p - y)^2 (matches the model's definition)."""
    if not vec:
        return None
    p = [vec.get("home_win", 0), vec.get("draw", 0), vec.get("away_win", 0)]
    return round(sum((pi - yi) ** 2 for pi, yi in zip(p, onehot)) / 3.0, 4)


def _fidelity(vec: dict, model_gt: dict, tol: float = 0.05) -> bool:
    """Did the condition report the model's vector? (within tol per component)."""
    if not vec or not model_gt or model_gt.get("error"):
        return False
    return all(abs(vec.get(k, 0) - model_gt.get(k, 0)) <= tol for k in ("home_win", "draw", "away_win"))


def score_prediction() -> dict:
    pred_dir = ROOT / "results" / "runs" / "prediction"
    gold = {it["id"]: it for it in
            json.loads((ROOT / "results" / "golden" / "prediction_golden.json").read_text())["items"]}
    per_run = []
    for path in sorted(pred_dir.glob("*.json")):
        rec = json.loads(path.read_text())
        qid = rec.get("question_id")
        g = gold.get(qid)
        if not g:
            continue
        vec = rec.get("prediction_vector")
        per_run.append({
            "id": qid, "condition": rec.get("condition"), "model": rec.get("model"),
            "prediction_vector": vec, "error": rec.get("error"),
            "brier": _brier(vec, g["actual_onehot"]),
            "fidelity": _fidelity(vec, g.get("model_gt")) if rec.get("condition") != "single_llm_rawdata" else None,
            "tokens": (rec.get("token_usage") or {}).get("total"),
            "latency_s": rec.get("latency_s"),
        })
    (SCORES_DIR / "prediction_scores.json").write_text(json.dumps({"scores": per_run}, indent=2))
    # reference: the model's own Brier on these 4 fixtures
    model_brier = [round(sum((v - y) ** 2 for v, y in zip(
        [g["model_gt"].get("home_win", 0), g["model_gt"].get("draw", 0), g["model_gt"].get("away_win", 0)],
        g["actual_onehot"])) / 3.0, 4) for g in gold.values() if not g["model_gt"].get("error")]
    return {"per_run": per_run, "model_ref_brier": round(sum(model_brier) / len(model_brier), 4) if model_brier else None}


def _aggregate_prediction(res: dict) -> None:
    from collections import defaultdict
    per_run = res["per_run"]
    by = defaultdict(list)
    for r in per_run:
        by[r["condition"]].append(r)
    print(f"Model reference Brier on the 4 fixtures: {res['model_ref_brier']}  (lower=better)\n")
    print(f"{'condition':22}{'n':4}{'avg_brier':11}{'fidelity':12}{'avg_tokens':12}{'avg_lat':8}")
    for c in ["mas", "single_llm_tools", "single_llm_rawdata"]:
        rows = by.get(c, [])
        briers = [r["brier"] for r in rows if r["brier"] is not None]
        fids = [r["fidelity"] for r in rows if r["fidelity"] is not None]
        toks = [r["tokens"] for r in rows if r.get("tokens")]
        lats = [r["latency_s"] for r in rows if r.get("latency_s")]
        fid_str = f"{sum(fids)}/{len(fids)}" if fids else "n/a"
        print(f"{c:22}{len(rows):<4}{(sum(briers)/len(briers) if briers else 0):<11.4f}"
              f"{fid_str:12}{(round(sum(toks)/len(toks)) if toks else 0):<12}"
              f"{(sum(lats)/len(lats) if lats else 0):.1f}s")
    print("\nPer-question vectors:")
    for r in per_run:
        print(f"  {r['id']} {r['condition']:20} vec={r['prediction_vector']} brier={r['brier']} fid={r['fidelity']}")


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "dof"
    if arg == "mvs":
        _aggregate_mvs(score_mvs()["per_run"])
    elif arg == "pred":
        _aggregate_prediction(score_prediction())
    else:
        _aggregate(score_dof()["per_run"])
