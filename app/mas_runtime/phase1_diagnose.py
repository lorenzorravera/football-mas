"""
Phase 1 — diagnose the 6 genuine misses (no seeding).
Runs each 3x through no_control with memory EMPTY (eval_no_memory=True, which also
prevents any store writes), captures SQL/data/response, scores vs ground_truth.json.
EVAL_MODE=golden so the sql_cache stays off.
"""
import os, json, warnings, traceback
os.environ["EVAL_MODE"] = "golden"
warnings.filterwarnings("ignore")

import pandas as pd
from state import create_initial_state
from graph import run_agent
from db.connection import read_sql

REPO = "/Users/ethanbensadoun/P13_2025-26_LLMAgentForecastingFootball"
GS = json.load(open(f"{REPO}/till/agent_v5/results/golden/golden_set.json"))
GT = json.load(open(f"{REPO}/till/agent_v5/results/golden/ground_truth.json"))
gs_items = {it["id"]: it for it in GS["items"]}
gt_items = {it["id"]: it.get("ground_truth") for it in GT["items"]}

QIDS = ["Q13", "Q21", "Q25", "Q28", "Q40", "Q45"]
N_RUNS = 3

# ---- scorer (copied from eval_memory_ablation.score_answer) ----
import re
def _nums(text):
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", str(text))]
def _num_in(target, pool):
    tol = max(0.5, abs(target) * 0.01)
    return any(abs(target - p) <= tol for p in pool)
def _cells(row):
    nums, strs = [], []
    for v in row:
        if isinstance(v, bool): continue
        if isinstance(v, (int, float)): nums.append(float(v))
        elif isinstance(v, str) and re.search(r"[A-Za-z]{3,}", v): strs.append(v.strip().lower())
    return nums, strs
_DENIAL = ["no data","not in","didn't","did not","no record","not present",
           "not available","weren't","were not","wasn't","not found","no results"]
def score_answer(answer, gt):
    if not answer or not answer.strip(): return "refused"
    if not gt or gt.get("row_count", 0) == 0:
        al = answer.lower()
        return "correct" if any(p in al for p in _DENIAL) else "wrong"
    gt_rows = gt.get("rows", [])
    if not gt_rows: return "refused"
    al = answer.lower(); a_nums = _nums(answer); covered = 0
    for row in gt_rows:
        nums, strs = _cells(row)
        nums_ok = all(_num_in(n, a_nums) for n in nums) if nums else True
        strs_ok = all(s in al for s in strs) if strs else True
        if nums_ok and strs_ok: covered += 1
    ratio = covered / len(gt_rows) if gt_rows else 0
    return "correct" if ratio >= 0.80 else ("partial" if ratio >= 0.40 else "wrong")

def df_brief(df):
    if df is None: return "None"
    if not isinstance(df, pd.DataFrame): return f"<{type(df).__name__}>"
    if df.empty: return "EMPTY DataFrame"
    return f"shape={df.shape} cols={list(df.columns)} head={df.head(3).to_dict('records')}"

results = {}
for qid in QIDS:
    item = gs_items[qid]; q = item["question"]; gt = gt_items[qid]
    print(f"\n{'='*78}\n{qid} | {item['difficulty']} | {item['category']}\n  Q: {q}", flush=True)
    # canonical sanity
    try:
        canon = read_sql(item["canonical_sql"])
        print(f"  CANONICAL -> {df_brief(canon)}", flush=True)
    except Exception as e:
        print(f"  CANONICAL ERROR: {e}", flush=True)
    print(f"  GT: {json.dumps(gt)}", flush=True)
    runs = []
    for i in range(N_RUNS):
        try:
            st = create_initial_state(q)
            st["eval_no_memory"] = True
            out = run_agent(q, variant="no_control", verbose=False, initial_state=st)
            sql = out.get("sql_query", "")
            dr = out.get("data_result")
            resp = out.get("final_response", "")
            err = out.get("error")
            retries = out.get("validation_retries", 0)
            verdict = "refused" if err else score_answer(resp, gt)
            runs.append({"sql": sql, "data": df_brief(dr), "resp": resp,
                         "error": err, "retries": retries, "verdict": verdict})
            print(f"\n  --- run {i+1}: verdict={verdict} retries={retries} err={err}", flush=True)
            print(f"      SQL: {' '.join(sql.split())[:400]}", flush=True)
            print(f"      DATA: {df_brief(dr)}", flush=True)
            print(f"      RESP: {resp[:280]}", flush=True)
        except Exception as e:
            runs.append({"error": f"EXC: {e}", "verdict": "refused", "trace": traceback.format_exc()})
            print(f"  --- run {i+1}: EXCEPTION {e}", flush=True)
    verds = [r["verdict"] for r in runs]
    fail_n = sum(1 for v in verds if v != "correct")
    print(f"\n  >> {qid} verdicts={verds}  fails={fail_n}/{N_RUNS}", flush=True)
    results[qid] = {"question": q, "gt": gt, "canonical_sql": item["canonical_sql"], "runs": runs, "verdicts": verds}

json.dump(results, open("phase1_results.json", "w"), indent=2, default=str)
print("\n\nWROTE phase1_results.json", flush=True)
