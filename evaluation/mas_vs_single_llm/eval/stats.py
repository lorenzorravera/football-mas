"""
eval/stats.py — paired statistics for the agent_v5 experiments (Phase 6).

Every condition sees the SAME questions, so comparisons are PAIRED. For binary correct/incorrect
outcomes we use:
  * McNemar's exact test (binomial on the discordant pairs) for the p-value, and
  * a paired bootstrap 95% CI on the accuracy difference (the effect size).

Reads stored runs (Claude) + frozen ground truth; derives correctness with the unified answer-text
scorer (eval.score.score_run_text). Writes results/stats/paired_tests.json. Never calls a model.
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

from eval.score import _load, score_run_text

ROOT = Path(__file__).resolve().parent.parent
DOF = ROOT / "results" / "runs" / "dof"
MVS = ROOT / "results" / "runs" / "mas_vs_single"
STATS_DIR = ROOT / "results" / "stats"
RNG = np.random.default_rng(42)


def correctness_matrix(model: str = "claude") -> tuple[dict, dict]:
    """condition -> {qid: 1/0} (errors excluded). DoF modes labelled MAS-<mode>; MVS keeps its names."""
    gold, gt, cov = _load()
    M: dict[str, dict[str, int]] = defaultdict(dict)
    for f in glob.glob(str(DOF / f"*_{model}_r*.json")):
        r = json.loads(Path(f).read_text())
        if r.get("error"):
            continue
        mode = r.get("analyst_mode") or r.get("mode")
        M[f"MAS-{mode}"][r["question_id"]] = int(score_run_text(r, gold, gt) == "correct")
    for f in glob.glob(str(MVS / f"*_{model}_r*.json")):
        r = json.loads(Path(f).read_text())
        if r.get("error"):
            continue
        M[r["condition"]][r["question_id"]] = int(score_run_text(r, gold, gt) == "correct")
    return M, cov


def _paired(a: dict, b: dict, qids: list[str]) -> dict:
    common = [q for q in qids if q in a and q in b]
    av = np.array([a[q] for q in common]); bv = np.array([b[q] for q in common])
    n = len(common)
    bb = int(np.sum((av == 1) & (bv == 0)))   # A right, B wrong
    cc = int(np.sum((av == 0) & (bv == 1)))   # A wrong, B right
    p = binomtest(min(bb, cc), bb + cc, 0.5).pvalue if (bb + cc) > 0 else 1.0
    delta = float(av.mean() - bv.mean()) if n else 0.0
    # paired bootstrap CI on the accuracy difference
    if n:
        idx = RNG.integers(0, n, size=(2000, n))
        boot = av[idx].mean(axis=1) - bv[idx].mean(axis=1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
    else:
        lo = hi = 0.0
    return {"n": n, "acc_a": round(float(av.mean()), 3) if n else None,
            "acc_b": round(float(bv.mean()), 3) if n else None,
            "delta": round(delta, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
            "discordant_a_gt_b": bb, "discordant_b_gt_a": cc, "mcnemar_p": round(float(p), 4)}


# comparisons that matter for the paper's claims
PAIRS = [
    ("mas", "single_llm_tools"),              # does MAS beat a single LLM with equal tools?
    ("single_llm_tools", "single_llm_rawdata"),  # tool/data-access effect
    ("mas", "single_llm_rawdata"),
    ("MAS-semi", "single_llm_tools"),         # best MAS config vs single+tools
    ("MAS-autonomous", "MAS-controlled"),     # DoF: autonomy effect
    ("MAS-semi", "MAS-controlled"),
    ("MAS-autonomous", "MAS-semi"),
]


def run(model: str = "claude") -> dict:
    M, cov = correctness_matrix(model)
    all_q = sorted({q for d in M.values() for q in d})
    in_q = [q for q in all_q if cov.get(q) == "in_coverage"]
    out_q = [q for q in all_q if cov.get(q) == "out_of_coverage"]
    out = {"model": model, "comparisons": []}
    for a, b in PAIRS:
        if a not in M or b not in M:
            continue
        out["comparisons"].append({
            "A": a, "B": b,
            "overall": _paired(M[a], M[b], all_q),
            "in_coverage": _paired(M[a], M[b], in_q),
            "out_of_coverage": _paired(M[a], M[b], out_q),
        })
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    (STATS_DIR / "paired_tests.json").write_text(json.dumps(out, indent=2))
    return out


def _print(out: dict) -> None:
    print(f"Paired tests (model={out['model']}; McNemar exact p, bootstrap 95% CI on Δacc=A−B)\n")
    print(f"{'A vs B':38}{'scope':17}{'accA':6}{'accB':6}{'Δ':7}{'95% CI':18}{'p':8}")
    for c in out["comparisons"]:
        for scope in ["overall", "in_coverage", "out_of_coverage"]:
            s = c[scope]
            ci = f"[{s['ci95'][0]:+.2f},{s['ci95'][1]:+.2f}]"
            sig = "*" if s["mcnemar_p"] < 0.05 else " "
            print(f"{c['A']+' vs '+c['B']:38}{scope:17}{str(s['acc_a']):6}{str(s['acc_b']):6}"
                  f"{s['delta']:+.2f}  {ci:18}{s['mcnemar_p']:.3f}{sig}")
        print()


if __name__ == "__main__":
    _print(run())
