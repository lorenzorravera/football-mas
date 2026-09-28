"""
agent_v3 evaluation against the golden set.

Runs all 20 test queries through agent_v3 and compares against
expected outputs from till/eval/golden_set/test_cases.json +
eval_golden_set.csv.

Scoring:
  correct   — key numerical values match expected output
  partial   — some values correct, some wrong
  wrong     — output present but incorrect
  refused   — agent returned no data or an error

Usage:
  cd Ethan/agent_v3
  python eval_runner.py

Output:
  eval_results.csv  — per-query results
  eval_summary.txt  — accuracy summary vs v2 baseline
"""

import sys
import json
import time
import csv
import re
from pathlib import Path
from datetime import datetime

# Add paths
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph import run_agent

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
GOLDEN_SET_DIR = Path(__file__).parent.parent.parent / "till" / "eval" / "golden_set"
TEST_CASES     = GOLDEN_SET_DIR / "test_cases.json"
GOLDEN_CSV     = GOLDEN_SET_DIR / "eval_golden_set.csv"
OUTPUT_CSV     = Path(__file__).parent / "eval_results.csv"
OUTPUT_SUMMARY = Path(__file__).parent / "eval_summary.txt"

# ---------------------------------------------------------------------------
# v2 baseline for comparison (from meeting slides)
# ---------------------------------------------------------------------------
V2_BASELINE = {
    "full_control":  7 / 20,   # 35%
    "semi_control":  10 / 20,  # 50%
    "no_control":    13 / 20,  # 65%
}

# ---------------------------------------------------------------------------
# Load golden set
# ---------------------------------------------------------------------------

def load_test_cases() -> list[dict]:
    with open(TEST_CASES) as f:
        return json.load(f)


def load_expected_outputs() -> dict:
    """Load expected outputs from CSV keyed by test id."""
    expected = {}
    with open(GOLDEN_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                expected[row["id"]] = json.loads(row["expected_output"])
            except Exception:
                expected[row["id"]] = {}
    return expected


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

def extract_numbers(text: str) -> set:
    """Extract all numbers from a string for fuzzy matching."""
    return set(re.findall(r"\d+\.?\d*", str(text)))


def score_result(test_id: str, query: str, agent_response: str,
                 agent_data, expected: dict) -> tuple[str, str]:
    """
    Score a single result.

    Returns (verdict, reasoning) where verdict is one of:
      correct / partial / wrong / refused
    """
    # Refused / error
    if not agent_response or "failed" in agent_response.lower() or "error" in agent_response.lower():
        return "refused", "Agent returned error or empty response"

    if agent_data is None or (hasattr(agent_data, "empty") and agent_data.empty):
        # Edge cases: T19 (Norwich not in league) — empty is correct
        if test_id == "T19":
            return "correct", "Correctly returned empty result for team not in league"
        # T20 (who's the best team) — any reasonable answer is fine
        if test_id == "T20":
            if agent_response and len(agent_response) > 20:
                return "correct", "Provided reasonable answer to subjective query"
        return "refused", "No data returned"

    # Extract expected key numbers
    expected_data = expected.get("data", expected)
    expected_nums = extract_numbers(json.dumps(expected_data))

    # Extract numbers from agent response + data
    agent_text = agent_response + str(agent_data.to_dict() if hasattr(agent_data, "to_dict") else agent_data)
    agent_nums = extract_numbers(agent_text)

    if not expected_nums:
        # No numbers to check (e.g. T20) — presence of answer is enough
        return "correct", "No numerical verification needed"

    # Calculate overlap
    overlap = expected_nums & agent_nums
    overlap_pct = len(overlap) / len(expected_nums) if expected_nums else 0

    if overlap_pct >= 0.80:
        return "correct", f"{len(overlap)}/{len(expected_nums)} key numbers matched"
    elif overlap_pct >= 0.40:
        return "partial", f"{len(overlap)}/{len(expected_nums)} key numbers matched"
    else:
        return "wrong", f"Only {len(overlap)}/{len(expected_nums)} key numbers matched"


# ---------------------------------------------------------------------------
# Main eval runner
# ---------------------------------------------------------------------------

def run_evaluation(variant: str = "no_control") -> dict:
    print(f"\n{'='*60}")
    print(f"agent_v3 Evaluation — variant: {variant}")
    print(f"{'='*60}\n")

    test_cases = load_test_cases()
    expected   = load_expected_outputs()

    results = []
    counts  = {"correct": 0, "partial": 0, "wrong": 0, "refused": 0}

    for i, tc in enumerate(test_cases):
        test_id    = tc["id"]
        query      = tc["query"]
        category   = tc["category"]
        difficulty = tc["difficulty"]

        print(f"[{i+1:02d}/20] {test_id} ({difficulty}) — {query[:60]}...")

        start = time.time()
        try:
            result = run_agent(query, variant=variant, verbose=False)
            latency = round(time.time() - start, 2)

            response  = result.get("final_response", "")
            data      = result.get("data_result")
            sql       = result.get("sql_query", "")
            cache_hit = result.get("sql_cache_hit", False)
            error     = result.get("error")

            if error:
                verdict   = "refused"
                reasoning = error[:100]
            else:
                verdict, reasoning = score_result(
                    test_id, query, response, data, expected.get(test_id, {})
                )

        except Exception as e:
            latency   = round(time.time() - start, 2)
            verdict   = "refused"
            reasoning = str(e)[:100]
            response  = ""
            sql       = ""
            cache_hit = False

        counts[verdict] += 1
        icon = {"correct": "✅", "partial": "⚠️", "wrong": "❌", "refused": "🚫"}[verdict]
        print(f"         {icon} {verdict.upper():<8} {latency:5.1f}s  cache={'HIT' if cache_hit else 'miss'}")

        results.append({
            "id":         test_id,
            "category":   category,
            "difficulty": difficulty,
            "query":      query,
            "verdict":    verdict,
            "reasoning":  reasoning,
            "latency_s":  latency,
            "cache_hit":  cache_hit,
            "sql":        (sql or "")[:200],
            "response":   (response or "")[:300],
        })

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
    total    = len(results)
    correct  = counts["correct"]
    accuracy = correct / total

    summary = f"""
agent_v3 Evaluation Summary
============================
Variant:    {variant}
Run date:   {datetime.now().strftime('%Y-%m-%d %H:%M')}
Total:      {total}

Results:
  Correct:  {counts['correct']:2d} / {total}  ({counts['correct']/total:.0%})
  Partial:  {counts['partial']:2d} / {total}  ({counts['partial']/total:.0%})
  Wrong:    {counts['wrong']:2d} / {total}  ({counts['wrong']/total:.0%})
  Refused:  {counts['refused']:2d} / {total}  ({counts['refused']/total:.0%})

vs v2 baseline ({variant}):
  v2:       {V2_BASELINE.get(variant, 0):.0%}
  v3:       {accuracy:.0%}
  delta:    {accuracy - V2_BASELINE.get(variant, 0):+.0%}

Cache hits: {sum(1 for r in results if r['cache_hit'])} / {total}
Avg latency: {sum(r['latency_s'] for r in results)/total:.1f}s
"""

    print(summary)
    with open(OUTPUT_SUMMARY, "w") as f:
        f.write(summary)

    print(f"\nResults saved to: {OUTPUT_CSV}")
    print(f"Summary saved to: {OUTPUT_SUMMARY}")

    return {"counts": counts, "accuracy": accuracy, "results": results}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Run no_control (best v2 variant) for direct comparison
    run_evaluation(variant="no_control")
