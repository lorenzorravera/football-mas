"""
eval/tables.py — regenerate the paper tables from stored runs/scores (Phase 6).

Reads results/runs + frozen ground truth (no model calls; numbers are never hand-edited). Emits
Markdown to results/tables/:
  table1_dof_coverage.md       DoF accuracy by model × variant × coverage
  table2_failure_taxonomy.md   semi-controlled failure taxonomy
  table3_mas_vs_single.md      MAS vs single-LLM-tools vs single-LLM-raw (by category + latency)
  table4_judge_agreement.md    judge–human agreement (N/A for this golden set — see note)
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

from eval.score import _load, score_run_text
from eval import failure_taxonomy

ROOT = Path(__file__).resolve().parent.parent
DOF = ROOT / "results" / "runs" / "dof"
MVS = ROOT / "results" / "runs" / "mas_vs_single"
TABLES = ROOT / "results" / "tables"
MODELS = ["claude", "gpt", "gemini"]
MODES = ["controlled", "semi", "autonomous"]
MVS_CONDS = ["mas", "single_llm_tools", "single_llm_rawdata"]


def _acc(flags):
    flags = [f for f in flags if f is not None]
    return f"{sum(flags)}/{len(flags)} ({100*sum(flags)/len(flags):.0f}%)" if flags else "—"


def table1_dof_coverage(gold, gt, cov) -> str:
    cell = defaultdict(lambda: defaultdict(list))
    counts = defaultdict(int)
    for f in glob.glob(str(DOF / "*_dof_*_r*.json")):
        r = json.loads(Path(f).read_text())
        if r.get("error"):
            counts[(r["model"], r.get("analyst_mode") or r.get("mode"), "err")] += 1
            continue
        m = r.get("analyst_mode") or r.get("mode")
        cell[(r["model"], m)][cov.get(r["question_id"])].append(int(score_run_text(r, gold, gt) == "correct"))
    L = ["# Table 1 — DoF accuracy by model × analyst variant × coverage", "",
         "Same MAS, only the data-analyst autonomy varies. (answer-text scoring)", "",
         "| model | variant | in-coverage | out-of-coverage | overall |", "|---|---|---|---|---|"]
    for model in MODELS:
        for mode in MODES:
            ins = cell[(model, mode)].get("in_coverage", [])
            outs = cell[(model, mode)].get("out_of_coverage", [])
            note = ""
            if counts.get((model, mode, "err")):
                note = f" _(+{counts[(model, mode, 'err')]} quota-errored, excluded)_"
            L.append(f"| {model} | {mode} | {_acc(ins)} | {_acc(outs)} | {_acc(ins+outs)}{note} |")
    return "\n".join(L) + "\n"


def table2_failure_taxonomy() -> str:
    out = failure_taxonomy.run()
    buckets = [("A", "chose template when SQL needed"), ("B", "wrong template / params"),
               ("C", "template failed → SQL fallback, still wrong"), ("D", "free-SQL generation wrong"),
               ("E", "errored / unclassified")]
    key = {"A": "A_chose_template_when_sql_needed", "B": "B_chose_wrong_template_or_params",
           "C": "C_template_failed_fell_back_sql", "D": "D_sql_generation_wrong",
           "E": "E_error_or_unclassified"}
    L = ["# Table 2 — Semi-controlled failure taxonomy", "",
         "Classification of every semi-controlled run that did not score correct.", "",
         "| code | failure mode | " + " | ".join(MODELS) + " | total |", "|---|---|" + "---|" * (len(MODELS) + 1)]
    tot_all = out["total"]
    for code, desc in buckets:
        row = f"| {code} | {desc} |"
        for m in MODELS:
            row += f" {out['by_model'].get(m, {}).get(key[code], 0)} |"
        row += f" {tot_all.get(key[code], 0)} |"
        L.append(row)
    return "\n".join(L) + "\n"


def table3_mas_vs_single(gold, gt, cov) -> str:
    by = defaultdict(lambda: defaultdict(list))
    lat = defaultdict(list)
    tok = defaultdict(list)
    cats = set()
    # MAS-condition tokens were recovered from Langfuse (predate local capture).
    mas_tok_path = ROOT / "results" / "stats" / "mas_token_usage.json"
    mas_tok = json.loads(mas_tok_path.read_text()) if mas_tok_path.exists() else {}
    for f in glob.glob(str(MVS / "*_claude_r*.json")):
        r = json.loads(Path(f).read_text())
        c = r.get("condition")
        qid = r["question_id"]
        cat = gold[qid]["category"]; cats.add(cat)
        v = int(score_run_text(r, gold, gt) == "correct") if not r.get("error") else None
        by[c]["overall"].append(v)
        by[c][cov.get(qid)].append(v)
        by[c][("cat", cat)].append(v)
        if r.get("latency_s"):
            lat[c].append(r["latency_s"])
        t = (r.get("token_usage") or {}).get("total")
        if t is None and c == "mas":   # fall back to Langfuse-pulled MAS tokens
            t = (mas_tok.get(r.get("langfuse_trace_id"), {}) or {}).get("total")
        if t:
            tok[c].append(t)
    L = ["# Table 3 — MAS vs single-LLM (Claude; MAS analyst_mode = autonomous)", "",
         "| condition | overall | in-cov | out-of-cov | avg tokens | avg latency |",
         "|---|---|---|---|---|---|"]
    label = {"mas": "MAS (autonomous)", "single_llm_tools": "single-LLM + tools",
             "single_llm_rawdata": "single-LLM + raw data"}
    for c in MVS_CONDS:
        al = lat.get(c, [])
        tk = tok.get(c, [])
        avg_tok = f"{round(sum(tk)/len(tk)):,}" if tk else "—"
        L.append(f"| {label[c]} | {_acc(by[c]['overall'])} | {_acc(by[c].get('in_coverage', []))} | "
                 f"{_acc(by[c].get('out_of_coverage', []))} | {avg_tok} | {(sum(al)/len(al) if al else 0):.1f}s |")
    L += ["", "### By category", "", "| category | " + " | ".join(label[c] for c in MVS_CONDS) + " |",
          "|---|" + "---|" * len(MVS_CONDS)]
    for cat in sorted(cats):
        L.append(f"| {cat} | " + " | ".join(_acc(by[c].get(("cat", cat), [])) for c in MVS_CONDS) + " |")
    L += ["", "_Tokens: single-LLM from local capture; MAS recovered from Langfuse. "
          "raw-data uses ~9x the tokens (~230k/run — the inlined player_season table dominates) and is "
          "both costly and unstable across runs; it also scores 0% on availability/market/transfers "
          "(those tables aren't inlined). Numbers are single-repeat (n=46), so treat as directional._"]
    return "\n".join(L) + "\n"


def table4_judge_agreement() -> str:
    return ("# Table 4 — Judge–human agreement\n\n"
            "**N/A for this golden set.** All 46 questions have deterministic SQL ground truth and are "
            "scored programmatically (scalar / ranking / table / denial) against frozen `ground_truth.json` "
            "— no LLM-as-judge was used, so there is no judge-vs-human agreement to report. The LLM judge "
            "(different model family) is reserved for genuine free-text questions, of which there are none "
            "here. If free-text items are added later, `eval/judge_validation.py` populates this table.\n")


def regenerate() -> None:
    gold, gt, cov = _load()
    TABLES.mkdir(parents=True, exist_ok=True)
    outputs = {
        "table1_dof_coverage.md": table1_dof_coverage(gold, gt, cov),
        "table2_failure_taxonomy.md": table2_failure_taxonomy(),
        "table3_mas_vs_single.md": table3_mas_vs_single(gold, gt, cov),
        "table4_judge_agreement.md": table4_judge_agreement(),
    }
    for name, content in outputs.items():
        (TABLES / name).write_text(content)
        print(f"wrote {name}")
    (TABLES / "ALL_TABLES.md").write_text("\n\n---\n\n".join(outputs.values()))
    print(f"wrote ALL_TABLES.md -> {TABLES}")


if __name__ == "__main__":
    regenerate()
    print("\n" + (TABLES / "ALL_TABLES.md").read_text())
