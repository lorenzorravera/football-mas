import sys, os; _here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, _here); [sys.path.remove(p) for p in sys.path[1:] if "till" in p and "tools" in p.split("/")]
"""
eval_memory_ablation.py — memory augmentation experiment on the 46-question golden set.

Runs two arms back-to-back on every question:
  ARM A: memory ON  (normal graph — memory_retrieval + memory_store + eval_agent active)
  ARM B: memory OFF (graph without memory nodes — baseline)

The 46 questions come from till/agent_v5/results/golden/golden_set.json (Till's v5 golden set).
Ground truth comes from till/agent_v5/results/golden/ground_truth.json.

Scoring (aligned with Till's eval/score.py):
  correct  — key numbers + names from ground truth appear in the answer (80%+ match)
  partial  — some match (40–80%)
  wrong    — less than 40%
  refused  — empty answer or error

Season format note: Till's golden set uses YYYY-YYYY (hyphen). Your manager prompt uses
YYYY_YYYY (underscore) internally, but the questions themselves are passed as-is. The manager
will resolve them correctly from the question text since it parses natural language.

Output:
  eval_memory_ablation_results.csv  — per-question, per-arm results
  eval_memory_ablation_summary.txt  — accuracy comparison table

Usage:
  cd Ethan/agent_v4
  python eval_memory_ablation.py

EVAL_MODE guard: correction_memory writes during this run are tagged source='ablation_eval'
and will NOT bleed into live memory (the existing EVAL_MODE=golden guard handles this if set).
"""

import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent  # Ethan/agent_v4/
REPO_ROOT = HERE.parent.parent  # repo root
GOLDEN_SET = REPO_ROOT / "till" / "agent_v5" / "results" / "golden" / "golden_set.json"
GROUND_TRUTH = REPO_ROOT / "till" / "agent_v5" / "results" / "golden" / "ground_truth.json"
OUTPUT_CSV = HERE / "eval_memory_ablation_results.csv"
OUTPUT_SUMMARY = HERE / "eval_memory_ablation_summary.txt"

# ---------------------------------------------------------------------------
# Add agent_v4 to path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

# Set eval mode to prevent correction_memory leaking into live store
os.environ["EVAL_MODE"] = "golden"

from graph import run_agent
from litellm.exceptions import RateLimitError as LiteLLMRateLimitError

def _run_with_backoff(fn, *args, max_retries=4, **kwargs):
    """Retry on 429 with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except (LiteLLMRateLimitError, Exception) as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                wait = 30 * (attempt + 1)
                print(f"  ⏳ Rate limited (attempt {attempt+1}), waiting {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Max retries exceeded on rate limit")

# ---------------------------------------------------------------------------
# Load golden set + ground truth
# ---------------------------------------------------------------------------

def load_golden_set() -> list[dict]:
    with open(GOLDEN_SET) as f:
        data = json.load(f)
    return data["items"]


def load_ground_truth() -> dict:
    with open(GROUND_TRUTH) as f:
        data = json.load(f)
    return {it["id"]: it.get("ground_truth") for it in data["items"]}


# ---------------------------------------------------------------------------
# Scoring (aligned with Till's eval/score.py logic)
# ---------------------------------------------------------------------------

def _nums(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", str(text))]


def _num_in(target: float, pool: list[float]) -> bool:
    tol = max(0.5, abs(target) * 0.01)
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


_DENIAL = ["no data", "not in", "didn't", "did not", "no record", "not present",
           "not available", "weren't", "were not", "wasn't", "not found", "no results"]


def score_answer(answer: str, gt: dict | None) -> str:
    """Score the answer text against ground truth rows."""
    if not answer or not answer.strip():
        return "refused"

    # Empty ground truth (e.g. team not in league)
    if not gt or gt.get("row_count", 0) == 0:
        al = answer.lower()
        return "correct" if any(p in al for p in _DENIAL) else "wrong"

    gt_rows = gt.get("rows", [])
    if not gt_rows:
        return "refused"

    al = answer.lower()
    a_nums = _nums(answer)
    covered = 0
    for row in gt_rows:
        nums, strs = _cells(row)
        nums_ok = all(_num_in(n, a_nums) for n in nums) if nums else True
        strs_ok = all(s in al for s in strs) if strs else True
        if nums_ok and strs_ok:
            covered += 1

    ratio = covered / len(gt_rows) if gt_rows else 0
    if ratio >= 0.80:
        return "correct"
    elif ratio >= 0.40:
        return "partial"
    return "wrong"


# ---------------------------------------------------------------------------
# Graph with memory OFF (patch memory nodes to no-ops)
# ---------------------------------------------------------------------------

def run_agent_no_memory(user_query: str, variant: str = "no_control") -> dict:
    """Run agent with memory disabled via state flag."""
    from state import create_initial_state
    initial_state = create_initial_state(user_query)
    initial_state["eval_no_memory"] = True
    return run_agent(user_query, variant=variant, verbose=False, initial_state=initial_state)


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_ablation(variant: str = "no_control") -> dict:
    print(f"\n{'='*70}")
    print(f"Memory Ablation Eval — variant: {variant}")
    print(f"Golden set: {GOLDEN_SET}")
    print(f"{'='*70}\n")

    questions = load_golden_set()
    ground_truth = load_ground_truth()

    print(f"Loaded {len(questions)} questions\n")

    results = []
    counts = {
        "memory_on":  {"correct": 0, "partial": 0, "wrong": 0, "refused": 0},
        "memory_off": {"correct": 0, "partial": 0, "wrong": 0, "refused": 0},
    }
    latencies = {"memory_on": [], "memory_off": []}

    for i, item in enumerate(questions):
        qid = item["id"]
        question = item["question"]
        category = item.get("category", "")
        difficulty = item.get("difficulty", "")
        gt = ground_truth.get(qid)

        print(f"[{i+1:02d}/46] {qid} ({difficulty}) — {question[:65]}...")

        row = {
            "id": qid,
            "category": category,
            "difficulty": difficulty,
            "question": question,
        }

        # ── ARM A: memory ON ──────────────────────────────────────────────
        try:
            t0 = time.time()
            result_on = _run_with_backoff(run_agent, question, variant=variant, verbose=False)
            lat_on = round(time.time() - t0, 2)
            answer_on = result_on.get("final_response", "")
            error_on = result_on.get("error", "")
            verdict_on = "refused" if error_on else score_answer(answer_on, gt)
        except Exception as e:
            lat_on = 0
            answer_on = ""
            error_on = str(e)[:120]
            verdict_on = "refused"

        counts["memory_on"][verdict_on] += 1
        latencies["memory_on"].append(lat_on)

        icon_on = {"correct": "✅", "partial": "⚠️", "wrong": "❌", "refused": "🚫"}[verdict_on]
        print(f"         memory ON : {icon_on} {verdict_on:<8} {lat_on:5.1f}s")

        row.update({
            "verdict_memory_on": verdict_on,
            "latency_on": lat_on,
            "answer_on": (answer_on or "")[:300],
            "error_on": error_on,
        })

        # ── ARM B: memory OFF ─────────────────────────────────────────────
        try:
            t0 = time.time()
            result_off = _run_with_backoff(run_agent_no_memory, question, variant=variant)
            lat_off = round(time.time() - t0, 2)
            answer_off = result_off.get("final_response", "")
            error_off = result_off.get("error", "")
            verdict_off = "refused" if error_off else score_answer(answer_off, gt)
        except Exception as e:
            import traceback; traceback.print_exc()
            lat_off = 0
            answer_off = ""
            error_off = str(e)[:120]
            verdict_off = "refused"

        counts["memory_off"][verdict_off] += 1
        latencies["memory_off"].append(lat_off)

        icon_off = {"correct": "✅", "partial": "⚠️", "wrong": "❌", "refused": "🚫"}[verdict_off]
        print(f"         memory OFF: {icon_off} {verdict_off:<8} {lat_off:5.1f}s")

        row.update({
            "verdict_memory_off": verdict_off,
            "latency_off": lat_off,
            "answer_off": (answer_off or "")[:300],
            "error_off": error_off,
            "delta": "improved" if verdict_on == "correct" and verdict_off != "correct"
                     else "regressed" if verdict_off == "correct" and verdict_on != "correct"
                     else "same",
        })

        results.append(row)
        time.sleep(20)  # ~3 questions/min, well under 30k TPM
        print()

    # ---------------------------------------------------------------------------
    # Write CSV
    # ---------------------------------------------------------------------------
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    total = len(results)

    def acc(c): return f"{c['correct']}/{total} ({c['correct']/total:.0%})"
    def avg_lat(lats): return f"{sum(lats)/len(lats):.1f}s" if lats else "N/A"

    improved  = sum(1 for r in results if r["delta"] == "improved")
    regressed = sum(1 for r in results if r["delta"] == "regressed")

    summary = f"""
Memory Ablation Evaluation — {variant}
=======================================
Run date:    {datetime.now().strftime('%Y-%m-%d %H:%M')}
Golden set:  Till v5 ({total} questions, Q01-Q46)
Variant:     {variant}

┌─────────────────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────────┐
│                 │  correct     │  partial     │  wrong       │  refused     │  avg latency │
├─────────────────┼──────────────┼──────────────┼──────────────┼──────────────┼──────────────┤
│ Memory ON       │ {counts['memory_on']['correct']:>3}/{total} ({counts['memory_on']['correct']/total:.0%})  │ {counts['memory_on']['partial']:>3}/{total} ({counts['memory_on']['partial']/total:.0%})  │ {counts['memory_on']['wrong']:>3}/{total} ({counts['memory_on']['wrong']/total:.0%})  │ {counts['memory_on']['refused']:>3}/{total} ({counts['memory_on']['refused']/total:.0%})  │ {avg_lat(latencies['memory_on']):>12} │
│ Memory OFF      │ {counts['memory_off']['correct']:>3}/{total} ({counts['memory_off']['correct']/total:.0%})  │ {counts['memory_off']['partial']:>3}/{total} ({counts['memory_off']['partial']/total:.0%})  │ {counts['memory_off']['wrong']:>3}/{total} ({counts['memory_off']['wrong']/total:.0%})  │ {counts['memory_off']['refused']:>3}/{total} ({counts['memory_off']['refused']/total:.0%})  │ {avg_lat(latencies['memory_off']):>12} │
└─────────────────┴──────────────┴──────────────┴──────────────┴──────────────┴──────────────┘

Delta (memory ON vs OFF across {total} paired questions):
  Memory improved answer:  {improved:2d} questions
  Memory regressed answer: {regressed:2d} questions
  No change:               {total - improved - regressed:2d} questions

Note: these are INDEPENDENT queries (no session structure), so memory retrieval
hits are expected to be low. Session-structured ablation (correction_memory,
sql_cache) is the stronger experiment — see memory_ablation_design.md.
"""

    print(summary)
    with open(OUTPUT_SUMMARY, "w") as f:
        f.write(summary)

    print(f"Results: {OUTPUT_CSV}")
    print(f"Summary: {OUTPUT_SUMMARY}")

    return {"counts": counts, "results": results}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="no_control",
                        choices=["full_control", "semi_control", "no_control"])
    args = parser.parse_args()
    run_ablation(variant=args.variant)
