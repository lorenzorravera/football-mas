"""
eval/langfuse_tokens.py — pull per-run COST + token usage from Langfuse (Phase 6 cost column).

LiteLLM logs token usage to Langfuse and Langfuse computes per-trace cost. Runs from run_mas (and now
the single-LLM conditions) set a trace context with id '<experiment>|<condition>|<model>|<qid>|r<rep>'
and tags [experiment, condition, model]. We page through traces FILTERED BY TAG (gentle on the API:
~10 pages vs 460 per-trace calls), reading each trace's total_cost (+ token totals if present), and
aggregate per experiment/condition/model. Retries + pacing handle the flaky/rate-limited instance.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env"); load_dotenv(ROOT.parent / ".env")
STATS_DIR = ROOT / "results" / "stats"
CACHE = STATS_DIR / "trace_cost.json"
TAGS = ["dof", "mas_vs_single"]


def _g(obj, *names):
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else getattr(obj, n, None)
        if v not in (None, 0):
            return v
    return None


def _trace_tokens(t):
    u = _g(t, "usage")
    if isinstance(u, dict):
        return u.get("total") or u.get("totalTokens")
    return _g(t, "total_tokens", "totalTokens")


def pull() -> dict:
    from langfuse import Langfuse
    lf = Langfuse(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"), secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                  host=os.getenv("LANGFUSE_BASE_URL"), timeout=30)
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    per_trace: dict = {}
    debugged = False
    for tag in TAGS:
        page = 1
        while True:
            data = None
            for attempt in range(5):
                try:
                    res = lf.fetch_traces(limit=50, page=page, tags=[tag])
                    data = res.data if hasattr(res, "data") else res
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt < 4:
                        time.sleep([3, 6, 12, 24][attempt])
                    else:
                        print(f"  tag={tag} page={page} failed after retries: {str(e)[:80]}")
            if not data:
                break
            if not debugged:
                t0 = data[0]
                attrs = [a for a in dir(t0) if not a.startswith("_") and "token" in a.lower()
                         or a in ("total_cost", "totalCost", "cost", "usage")]
                print(f"  (trace field probe: {attrs})")
                debugged = True
            for t in data:
                tid = _g(t, "id")
                if not tid or "|" not in str(tid):
                    continue
                per_trace[tid] = {"cost": _g(t, "total_cost", "totalCost", "cost"),
                                  "tokens": _trace_tokens(t)}
            print(f"  tag={tag} page={page}: {len(data)} traces ({len(per_trace)} labelled total)")
            page += 1
            time.sleep(0.5)
    CACHE.write_text(json.dumps(per_trace, indent=2))
    return per_trace


def pull_trace_tokens(trace_ids: list[str], out_path: Path) -> dict:
    """Sum per-observation token usage for specific trace_ids (targeted; gentle on the API).
    Used to recover tokens for runs that predate local token capture (e.g. the MAS SQL condition)."""
    from langfuse import Langfuse
    lf = Langfuse(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"), secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                  host=os.getenv("LANGFUSE_BASE_URL"), timeout=30)
    cache = json.loads(out_path.read_text()) if out_path.exists() else {}
    todo = [t for t in trace_ids if t not in cache or cache[t].get("error")]
    print(f"{len(trace_ids)} trace_ids; {len(todo)} to fetch ({len(cache)} cached)")
    for n, tid in enumerate(todo, 1):
        rec = None
        for attempt in range(4):
            try:
                obs = lf.fetch_observations(trace_id=tid)
                od = obs.data if hasattr(obs, "data") else obs
                i = o = t = 0
                for ob in od:
                    ii, oo, tt = _usage(ob); i += ii; o += oo; t += tt
                rec = {"input": i, "output": o, "total": t, "calls": len(od)}
                break
            except Exception as e:  # noqa: BLE001
                if attempt < 3:
                    time.sleep([5, 15, 30][attempt])
                else:
                    rec = {"error": str(e)[:80]}
        cache[tid] = rec
        time.sleep(1.0)   # pace to respect the flaky/rate-limited instance
        if n % 10 == 0:
            out_path.write_text(json.dumps(cache, indent=2)); print(f"  {n}/{len(todo)} fetched")
    out_path.write_text(json.dumps(cache, indent=2))
    return cache


def _usage(o):  # observation usage → (input, output, total)
    u = getattr(o, "usage", None)
    if not u:
        return 0, 0, 0
    g = (lambda k: (u.get(k) if isinstance(u, dict) else getattr(u, k, None)))
    i, oo = g("input") or 0, g("output") or 0
    return i, oo, (g("total") or (i + oo))


def aggregate(per_trace: dict) -> dict:
    by = defaultdict(lambda: {"cost": [], "tokens": []})
    for tid, d in per_trace.items():
        parts = tid.split("|")
        if len(parts) < 3:
            continue
        key = f"{parts[0]}/{parts[1]}/{parts[2]}"
        if d.get("cost") is not None:
            by[key]["cost"].append(d["cost"])
        if d.get("tokens"):
            by[key]["tokens"].append(d["tokens"])
    out = {}
    for k, v in sorted(by.items()):
        n = len(v["cost"]) or len(v["tokens"])
        out[k] = {"n_runs": n,
                  "avg_cost_usd": round(sum(v["cost"]) / len(v["cost"]), 4) if v["cost"] else None,
                  "total_cost_usd": round(sum(v["cost"]), 2) if v["cost"] else None,
                  "avg_tokens": round(sum(v["tokens"]) / len(v["tokens"])) if v["tokens"] else None}
    return out


if __name__ == "__main__":
    pt = pull()
    print(f"\npulled {len(pt)} labelled traces -> {CACHE}\n")
    agg = aggregate(pt)
    print(f"{'experiment/condition/model':46}{'runs':6}{'avg_cost$':11}{'avg_tokens':12}{'total_cost$':10}")
    for k, a in agg.items():
        print(f"{k:46}{a['n_runs']:<6}{str(a['avg_cost_usd']):11}{str(a['avg_tokens']):12}{a['total_cost_usd']}")
