"""
eval/extended_stats.py — paired McNemar (EXACT binomial) on the DATA-ANALYSIS questions only.

Compares MAS vs single-LLM-with-tools on the 30 DA questions (and on the out-of-coverage subset,
where the MAS effect is expected to live). Every condition saw the SAME questions → outcomes are
PAIRED. The discordant count is small, so we use the EXACT binomial McNemar (scipy binomtest on the
discordant pairs), NOT the chi-square approximation (invalid at small n).

Reads correctness from disk (results/scores/extended_da_scores.json, produced by extended_score.py)
so this step never re-runs a model. Writes results/stats/extended_mcnemar.json.

NOTE: no significance test is run on the prediction questions — by construction MAS and single+tools
call the same predict_match_outcome and return identical vectors, so discordant pairs are 0 and a
paired test is degenerate. Prediction is reported descriptively (see extended_score.py / the report).
"""

from __future__ import annotations

import json
from pathlib import Path

from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parent.parent
DA_SCORES = ROOT / "results" / "scores" / "extended_da_scores.json"
STATS = ROOT / "results" / "stats"

A_COND, B_COND = "mas", "single_llm_tools"


def _correctness() -> tuple[dict, dict, dict]:
    """Return (mas_map, tools_map, coverage) keyed by qid; correctness is 1/0, errors excluded."""
    rows = json.loads(DA_SCORES.read_text())["scores"]
    a, b, cov = {}, {}, {}
    for r in rows:
        if r["verdict"] == "error":
            continue
        cov[r["id"]] = r["coverage"]
        if r["condition"] == A_COND:
            a[r["id"]] = r["correct"]
        elif r["condition"] == B_COND:
            b[r["id"]] = r["correct"]
    return a, b, cov


def _mcnemar(a: dict, b: dict, qids: list[str]) -> dict:
    common = [q for q in qids if q in a and q in b]
    both_right = sum(a[q] == 1 and b[q] == 1 for q in common)
    a_only = sum(a[q] == 1 and b[q] == 0 for q in common)     # MAS right, single wrong  (= b in McNemar)
    b_only = sum(a[q] == 0 and b[q] == 1 for q in common)     # MAS wrong, single right  (= c in McNemar)
    both_wrong = sum(a[q] == 0 and b[q] == 0 for q in common)
    b_disc, c_disc = a_only, b_only
    n_disc = b_disc + c_disc
    # EXACT binomial McNemar: two-sided test that discordant splits are 50/50.
    p_exact = binomtest(min(b_disc, c_disc), n_disc, 0.5).pvalue if n_disc > 0 else 1.0
    # McNemar odds ratio = b/c (ratio of discordant directions); report a plain description too.
    if c_disc == 0 and b_disc == 0:
        odds = None
    elif c_disc == 0:
        odds = float("inf")
    else:
        odds = round(b_disc / c_disc, 3)
    acc_a = round(sum(a[q] for q in common) / len(common), 3) if common else None
    acc_b = round(sum(b[q] for q in common) / len(common), 3) if common else None
    return {
        "n": len(common),
        "contingency": {"both_right": both_right, "mas_only_right": a_only,
                        "single_only_right": b_only, "both_wrong": both_wrong},
        "b_mas_only": b_disc, "c_single_only": c_disc, "n_discordant": n_disc,
        "mcnemar_exact_p": round(float(p_exact), 4),
        "mcnemar_odds_ratio": odds,
        "acc_mas": acc_a, "acc_single_tools": acc_b,
        "acc_delta": round((acc_a - acc_b), 3) if (acc_a is not None and acc_b is not None) else None,
        "significant_at_0.05": bool(p_exact < 0.05),
    }


def run() -> dict:
    a, b, cov = _correctness()
    all_q = sorted(set(a) & set(b))
    out_q = [q for q in all_q if cov.get(q) == "out_of_coverage"]
    in_q = [q for q in all_q if cov.get(q) == "in_coverage"]
    out = {
        "comparison": f"{A_COND} vs {B_COND}", "test": "McNemar exact (binomial), two-sided",
        "overall": _mcnemar(a, b, all_q),
        "in_coverage": _mcnemar(a, b, in_q),
        "out_of_coverage": _mcnemar(a, b, out_q),
    }
    STATS.mkdir(parents=True, exist_ok=True)
    (STATS / "extended_mcnemar.json").write_text(json.dumps(out, indent=2))
    return out


def _print(out: dict) -> None:
    print(f"McNemar exact — {out['comparison']} (DA questions only)\n")
    for scope in ("overall", "out_of_coverage", "in_coverage"):
        s = out[scope]
        c = s["contingency"]
        print(f"[{scope}]  n={s['n']}")
        print(f"  contingency: both_right={c['both_right']}  MAS_only={c['mas_only_right']}  "
              f"single_only={c['single_only_right']}  both_wrong={c['both_wrong']}")
        print(f"  b (MAS-only right)={s['b_mas_only']}  c (single-only right)={s['c_single_only']}  "
              f"discordant={s['n_discordant']}")
        print(f"  acc: MAS={s['acc_mas']}  single+tools={s['acc_single_tools']}  Δ={s['acc_delta']}")
        print(f"  McNemar exact p={s['mcnemar_exact_p']}  OR(b/c)={s['mcnemar_odds_ratio']}  "
              f"{'SIGNIFICANT' if s['significant_at_0.05'] else 'not significant'} at α=0.05\n")


if __name__ == "__main__":
    _print(run())
