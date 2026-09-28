"""
golden/build_ground_truth.py — execute every canonical_sql and capture ground truth (Phase 2).

Status: CANDIDATE. Produces, in results/golden/:
  * ground_truth.candidate.json   — each item + its executed structured result
  * appendix_canonical_sql.md     — question → SQL → result (paper appendix draft)
and prints a review summary for Till.

Ground truth = the RESULT of running canonical_sql (never an AI prose answer).
FREEZE (hash + timestamp + git commit) happens only AFTER Till approves — in a separate step.
"""

from __future__ import annotations

import json
from pathlib import Path

from golden.generate import DRAFT_ITEMS, write_golden_set, OUT_DIR
from tools.run_sql import run_sql, SqlNotAllowed

# Items where an empty result is the CORRECT answer (intentional edge cases).
EXPECT_EMPTY = {"Q45"}   # Norwich City were not in the PL in 2024-2025


def _run_item(item: dict) -> dict:
    sql = item.get("canonical_sql")
    out = dict(item)
    if not sql:
        out["status"] = "no_sql"
        out["ground_truth"] = None
        return out
    try:
        res = run_sql(sql, max_rows=100)
        out["ground_truth"] = {
            "columns": res["columns"],
            "rows": res["rows"],
            "row_count": res["row_count"],
            "truncated": res["truncated"],
        }
        if res["row_count"] == 0:
            out["status"] = "empty_expected" if item["id"] in EXPECT_EMPTY else "EMPTY"
        else:
            out["status"] = "ok"
    except (SqlNotAllowed, Exception) as e:  # noqa: BLE001 - capture any DB error for review
        out["ground_truth"] = None
        out["status"] = "ERROR"
        out["error"] = str(e)[:300]
    return out


def _render_result(gt: dict | None, limit: int = 8) -> str:
    if not gt:
        return "_(no result)_"
    cols = gt["columns"]
    rows = gt["rows"][:limit]
    if gt["row_count"] == 0:
        return "_(empty result set)_"
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    more = f"\n_…{gt['row_count'] - limit} more rows_" if gt["row_count"] > limit else ""
    return "\n".join([head, sep, *body]) + more


def build() -> dict:
    write_golden_set()  # ensure golden_set.candidate.json exists
    results = [_run_item(it) for it in DRAFT_ITEMS]

    (OUT_DIR / "ground_truth.candidate.json").write_text(
        json.dumps({"frozen": False, "items": results}, indent=2, default=str))

    # appendix
    L = ["# Appendix — Golden set: question → canonical SQL → result (CANDIDATE)", "",
         "_Not frozen. Ground truth is the result of running each canonical SQL._", ""]
    for r in results:
        L += [f"## {r['id']} — {r['category']} ({r['difficulty']}, {r['gt_type']}/{r['answer_type']})",
              "", f"**Q:** {r['question']}", "", f"**Status:** `{r['status']}`", "",
              "```sql", r.get("canonical_sql") or "(none)", "```", "",
              _render_result(r.get("ground_truth")), ""]
        if r.get("error"):
            L += [f"> ⚠️ ERROR: {r['error']}", ""]
    (OUT_DIR / "appendix_canonical_sql.md").write_text("\n".join(L))

    # console summary
    from collections import Counter
    status = Counter(r["status"] for r in results)
    print(f"{len(results)} items executed. status = {dict(status)}\n")
    print(f"{'id':5} {'cat':24} {'diff':10} {'status':14} rows  preview")
    for r in results:
        gt = r.get("ground_truth") or {}
        n = gt.get("row_count", 0)
        prev = ""
        if gt.get("rows"):
            prev = " | ".join(str(v) for v in gt["rows"][0])[:60]
        print(f"{r['id']:5} {r['category'][:24]:24} {r['difficulty']:10} {r['status']:14} {n:4}  {prev}")
    print(f"\nWrote:\n  {OUT_DIR/'ground_truth.candidate.json'}\n  {OUT_DIR/'appendix_canonical_sql.md'}")
    return {"status_counts": dict(status), "results": results}


if __name__ == "__main__":
    build()
