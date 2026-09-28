import sys, os; _here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, _here); [sys.path.remove(p) for p in sys.path[1:] if "till" in p and "tools" in p.split("/")]
"""
eval_cache_sweep.py — three-tier SQL-cache similarity sweep on the 46-question golden set.

Demonstrates that the sql_cache is SELECTIVE: it reuses cached SQL for genuine repeats
(Tier 1) and light rewords (Tier 2), and correctly REFUSES near-misses with a different
entity/season (Tier 3). The payoff is latency + token cost amortization, not accuracy.

Protocol (single process, so the in-DB cache persists Run 1 -> Run 2):
  0. reset sql_cache (true cold start). conversation/correction tables untouched.
  1. RUN 1 (cold): all golden questions, no_control, cache active -> cache fills.
  2. RUN 2 (warm): per question, Tier 1 (exact), Tier 2 (reword), Tier 3 (near-miss).
  3. Score Tier 1/2 vs golden ground_truth.json; Tier 3 vs its own tier3_sql (derived live).

Memory isolation: EVAL_MODE=cache_experiment keeps sql_cache live but disables
conversation_memory + correction_memory reads AND writes, so any warm-run saving is
attributable to the cache alone. correction_memory must stay frozen (~186 rows).

Synthesizer output is capped at 500 tokens under this flag (its costliest call).

Live streaming: every query result prints the moment it completes (flush=True),
with a running tally every 10 queries.

Usage:
  cd Ethan/agent_v4
  python eval_cache_sweep.py --smoke      # 3 questions x (1 cold + 3 tiers) = 12 runs, then STOP
  python eval_cache_sweep.py              # full 46 cold + 138 warm
"""

import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT))

VARIANT_MAP   = HERE / "variant_map.json"
RUN1_CSV      = HERE / "run1_cold.csv"
RUN2_CSV      = HERE / "run2_tiered.csv"
SUMMARY_TXT   = HERE / "cache_sweep_summary.txt"

SMOKE_QIDS = ["Q02", "Q09", "Q19"]

# ---------------------------------------------------------------------------
# Reuse the EXACT scorer + loaders from the prior ablation.
# Importing it sets EVAL_MODE=golden as a side effect — we override immediately after.
# (agents read os.getenv("EVAL_MODE") at call time, so the override takes effect.)
# ---------------------------------------------------------------------------
from eval_memory_ablation import score_answer, load_golden_set, load_ground_truth  # noqa: E402
os.environ["EVAL_MODE"] = "cache_experiment"   # <-- the whole point; override golden

from graph import run_agent                                       # noqa: E402
from db.connection import read_sql                                # noqa: E402
from memory.vector_store_pg import (                              # noqa: E402
    memory_stats, reset_collection, _get_conn, _embed,
)
import config                                                     # noqa: E402

assert os.getenv("EVAL_MODE") == "cache_experiment", "EVAL_MODE must be cache_experiment"

# ---------------------------------------------------------------------------
# Token capture: wrap config.completion so we record usage per LLM call.
# config.call_llm resolves `completion` from config's module namespace at call
# time, so reassigning config.completion intercepts every call. No production edit.
# ---------------------------------------------------------------------------
_real_completion = config.completion
_tok = {"in": 0, "out": 0, "calls": 0, "hit_429": False}


def _tok_reset():
    _tok.update({"in": 0, "out": 0, "calls": 0, "hit_429": False})


def _is_rate_limit(e_or_text) -> bool:
    s = str(e_or_text).lower()
    return "rate_limit" in s or "ratelimit" in s or "429" in s


def _wrapped_completion(*a, **k):
    try:
        resp = _real_completion(*a, **k)
    except Exception as e:
        if _is_rate_limit(e):
            _tok["hit_429"] = True
        raise
    try:
        u = resp.usage
        _tok["in"]  += int(getattr(u, "prompt_tokens", 0) or 0)
        _tok["out"] += int(getattr(u, "completion_tokens", 0) or 0)
        _tok["calls"] += 1
    except Exception:
        pass
    return resp


config.completion = _wrapped_completion

# ---------------------------------------------------------------------------
# Cold-run = WRITE-ONLY: patch memory_agent's bound query_sql_cache to return None
# during Run 1 so the cache fills with each question's OWN correct SQL (clean
# cache-free baseline, no intra-cold collisions). Restored before Run 2.
# Harness-only — no production edit. The WRITE path stays active.
# ---------------------------------------------------------------------------
import memory.memory_agent as _mem_agent                           # noqa: E402
_real_qsc = _mem_agent.query_sql_cache


def disable_cache_reads():
    _mem_agent.query_sql_cache = lambda *a, **k: None


def enable_cache_reads():
    _mem_agent.query_sql_cache = _real_qsc

# ---------------------------------------------------------------------------
# Independent cache probe — proves a hit references a real DB row.
# Mirrors query_sql_cache() but also returns the row id.
# ---------------------------------------------------------------------------
def cache_probe(query_text: str):
    """Return (row_id, similarity, cached_query) for the nearest sql_cache row, or (None, None, None)."""
    try:
        emb = _embed(query_text)
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, query, (embedding <=> %s::vector) AS dist "
                "FROM sql_cache ORDER BY embedding <=> %s::vector LIMIT 1",
                (str(emb), str(emb)),
            )
            r = cur.fetchone()
        if not r:
            return None, None, None
        rid, q, dist = r
        sim = round(1.0 - float(dist) / 2.0, 4)
        return rid, sim, q
    except Exception:
        return None, None, None


def all_three_counts() -> dict:
    return memory_stats()  # {"conversation_memory": n, "sql_cache": n, "correction_memory": n}


# ---------------------------------------------------------------------------
# Timed run with 429 handling: latency EXCLUDES backoff sleeps.
# Each attempt is timed individually; only the successful attempt's wall time is
# recorded. query_429 flags if any attempt saw a rate-limit (contaminated latency).
# ---------------------------------------------------------------------------
def run_timed(question: str, variant: str = "no_control", max_retries: int = 4):
    query_429 = False
    for attempt in range(max_retries):
        _tok_reset()
        t0 = time.time()
        try:
            state = run_agent(question, variant=variant, verbose=False)
        except Exception as e:
            if _is_rate_limit(e):
                query_429 = True
                wait = 20 * (attempt + 1)
                print(f"     429 backoff {wait}s (attempt {attempt+1})...", flush=True)
                time.sleep(wait)        # OUTSIDE any measured window
                continue
            # non-rate hard error
            return ({"error": str(e)[:200], "final_response": ""},
                    round(time.time() - t0, 2), True, dict(_tok))
        lat = round(time.time() - t0, 2)
        toks = dict(_tok)
        if toks["hit_429"]:
            query_429 = True
        err = state.get("error") or ""
        # A 429 swallowed into state.error mid-pipeline -> retry clean
        if err and _is_rate_limit(err) and attempt < max_retries - 1:
            wait = 20 * (attempt + 1)
            print(f"     429 in-pipeline, backoff {wait}s (attempt {attempt+1})...", flush=True)
            time.sleep(wait)
            continue
        return state, lat, query_429, toks
    return ({"error": "max retries on rate limit", "final_response": ""}, 0.0, True, dict(_tok))


# ---------------------------------------------------------------------------
# Ground truth for Tier 3 (near-miss): execute its own tier3_sql live.
# Returns a gt dict matching ground_truth.json shape, or None on failure.
# ---------------------------------------------------------------------------
def derive_gt(tier3_sql: str):
    try:
        df = read_sql(tier3_sql)
        rows = df.values.tolist()
        return {
            "columns": list(df.columns),
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
        }
    except Exception as e:
        print(f"     ! tier3_sql failed to derive GT: {str(e)[:80]}", flush=True)
        return None


# ---------------------------------------------------------------------------
# Per-query execution + record building
# ---------------------------------------------------------------------------
VERDICT_ICON = {"correct": "OK ", "partial": "PRT", "wrong": "XX ", "refused": "REF", "na": "-- "}


def execute_query(qid: str, tier: str, question: str, gt, variant="no_control") -> dict:
    """Run one query, score it, probe the cache, print a live line, return a record dict."""
    # PRE-write probe: the nearest sql_cache row + similarity as it stands BEFORE this
    # query writes its own row — this is exactly what the pipeline's retrieval sees, and
    # proves a hit references a prior (Run-1) row rather than the query's own fresh write.
    probe_id, probe_sim, probe_q = cache_probe(question)

    state, lat, hit_429, toks = run_timed(question, variant=variant)

    answer = state.get("final_response", "") or ""
    error  = state.get("error", "") or ""
    sql    = state.get("sql_query", "") or ""
    cache_hit = bool(state.get("sql_cache_hit"))
    meta = state.get("sql_cache_meta") or {}
    pipe_sim = meta.get("similarity")
    cached_q = meta.get("cached_query", "") or probe_q
    # report the pre-write nearest similarity (clean); pipeline meta sim agrees on hits
    sim = probe_sim if probe_sim is not None else pipe_sim

    if gt is None:
        verdict = "refused" if error else "na"
    else:
        verdict = "refused" if error else score_answer(answer, gt)

    sql_present = bool(sql and not sql.startswith("Function:"))

    hitmark = "HIT " if cache_hit else "miss"
    simtxt  = f"{sim:.3f}" if isinstance(sim, (int, float)) else "  -  "
    rid     = (probe_id or "")[:18]
    flag429 = "  429!" if hit_429 else ""
    tlabel  = tier if tier else "cold"
    print(
        f"  {qid} | {tlabel:<5} | {VERDICT_ICON.get(verdict,'?')} {verdict:<7} "
        f"| {lat:6.2f}s | {hitmark} | sim={simtxt} | row={rid:<18} "
        f"| tok in/out={toks['in']}/{toks['out']} calls={toks['calls']}{flag429}",
        flush=True,
    )

    return {
        "id": qid,
        "tier": tlabel,
        "question": question,
        "verdict": verdict,
        "latency_s": lat,
        "hit_429": hit_429,
        "cache_hit": cache_hit,
        "similarity": round(sim, 4) if isinstance(sim, (int, float)) else "",
        "matched_row_id": probe_id or "",
        "matched_cached_query": (cached_q or probe_q or "")[:80],
        "llm_calls": toks["calls"],
        "input_tokens": toks["in"],
        "output_tokens": toks["out"],
        "total_tokens": toks["in"] + toks["out"],
        "sql_present": sql_present,
        "answer": answer[:300],
        "error": error[:160],
    }


# ---------------------------------------------------------------------------
# Aggregation helpers for the summary
# ---------------------------------------------------------------------------
def _avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else 0.0


def tier_stats(rows: list[dict]) -> dict:
    n = len(rows)
    hits = sum(1 for r in rows if r["cache_hit"])
    sims = [r["similarity"] for r in rows if r["cache_hit"] and isinstance(r["similarity"], (int, float))]
    correct = sum(1 for r in rows if r["verdict"] == "correct")
    scored = sum(1 for r in rows if r["verdict"] in ("correct", "partial", "wrong", "refused"))
    n429 = sum(1 for r in rows if r["hit_429"])
    clean_lat = [r["latency_s"] for r in rows if not r["hit_429"]]
    return {
        "n": n,
        "hits": hits,
        "avg_sim_on_hit": _avg(sims),
        "avg_latency": _avg([r["latency_s"] for r in rows]),
        "avg_latency_clean": _avg(clean_lat),
        "n_429": n429,
        "avg_tokens": _avg([r["total_tokens"] for r in rows]),
        "avg_in": _avg([r["input_tokens"] for r in rows]),
        "avg_out": _avg([r["output_tokens"] for r in rows]),
        "correct": correct,
        "scored": scored,
    }


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------
def main(smoke: bool, sleep_s: float):
    print("=" * 80, flush=True)
    print(f"THREE-TIER SQL-CACHE SWEEP  |  {'SMOKE (3 q)' if smoke else 'FULL (46 q)'}  |  "
          f"variant=no_control  |  EVAL_MODE={os.getenv('EVAL_MODE')}", flush=True)
    print("=" * 80, flush=True)

    questions = load_golden_set()
    ground_truth = load_ground_truth()
    vmap = json.loads(VARIANT_MAP.read_text())["variants"]

    if smoke:
        questions = [q for q in questions if q["id"] in SMOKE_QIDS]

    qids = [q["id"] for q in questions]
    print(f"Questions: {len(questions)}  -> {qids}\n", flush=True)

    # ── Step 0: reset sql_cache, snapshot all three stores ────────────────
    print("[reset] TRUNCATE sql_cache (cold start). conversation/correction untouched.", flush=True)
    reset_collection("sql_cache")
    base_counts = all_three_counts()
    print(f"[counts @ start] {base_counts}", flush=True)
    assert base_counts["sql_cache"] == 0, "sql_cache should be empty after reset"
    corr_baseline = base_counts["correction_memory"]
    print()

    run1_rows, run2_rows = [], []

    # ── RUN 1 (cold) — WRITE-ONLY (reads disabled) for a clean baseline ───
    print("-" * 80, flush=True)
    print("RUN 1 (COLD, write-only) — cache reads OFF; each question generates its own SQL", flush=True)
    print("-" * 80, flush=True)
    disable_cache_reads()
    for i, item in enumerate(questions):
        qid = item["id"]
        gt = ground_truth.get(qid)
        rec = execute_query(qid, "", item["question"], gt)
        run1_rows.append(rec)
        if (i + 1) % 10 == 0:
            hh = sum(1 for r in run1_rows if r["cache_hit"])
            print(f"   ...Run1 tally: {hh}/{i+1} cache hits (cold write-only; must be 0). "
                  f"'sim' column shows nearest pre-write neighbour for info.", flush=True)
        time.sleep(sleep_s)
    enable_cache_reads()
    print("   [cache reads RE-ENABLED for Run 2]", flush=True)

    counts_after_run1 = all_three_counts()
    print(f"\n[counts @ after Run 1] {counts_after_run1}", flush=True)
    print(f"   sql_cache grew 0 -> {counts_after_run1['sql_cache']}  "
          f"(expected ~ number of non-empty SQL answers)", flush=True)
    print(f"   correction_memory: {corr_baseline} -> {counts_after_run1['correction_memory']}  "
          f"({'FROZEN OK' if counts_after_run1['correction_memory'] == corr_baseline else 'GREW — WRITE GATE BROKEN'})",
          flush=True)
    print(f"   conversation_memory: {base_counts['conversation_memory']} -> "
          f"{counts_after_run1['conversation_memory']}  "
          f"({'frozen' if counts_after_run1['conversation_memory'] == base_counts['conversation_memory'] else 'GREW'})",
          flush=True)

    # Show a few cached rows (real SQL + embedding present)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, LEFT(query,55), LEFT(sql_query,55), (embedding IS NOT NULL) "
                "FROM sql_cache ORDER BY created_at LIMIT 5"
            )
            print("\n[cached rows sample]", flush=True)
            for row in cur.fetchall():
                print(f"   id={row[0][:20]:<20} q='{row[1]}' sql='{row[2]}' emb={row[3]}", flush=True)
    except Exception as e:
        print(f"   ! could not sample cache rows: {e}", flush=True)
    print()

    # ── RUN 2 (warm) — Tier 1/2/3 per question ────────────────────────────
    print("-" * 80, flush=True)
    print("RUN 2 (WARM) — Tier 1 exact / Tier 2 reword / Tier 3 near-miss", flush=True)
    print("-" * 80, flush=True)

    tier_hit_tally = {"1": [0, 0], "2": [0, 0], "3": [0, 0]}  # [hits, total]
    seen = 0
    for item in questions:
        qid = item["id"]
        v = vmap[qid]
        gt_golden = ground_truth.get(qid)

        # Tier 1 — exact repeat (same answer as golden)
        rec1 = execute_query(qid, "T1", item["question"], gt_golden)
        rec1["variant_text"] = item["question"]
        run2_rows.append(rec1)
        tier_hit_tally["1"][0] += int(rec1["cache_hit"]); tier_hit_tally["1"][1] += 1

        # Tier 2 — light reword (same entity/season -> same golden answer)
        rec2 = execute_query(qid, "T2", v["tier2"], gt_golden)
        rec2["variant_text"] = v["tier2"]
        run2_rows.append(rec2)
        tier_hit_tally["2"][0] += int(rec2["cache_hit"]); tier_hit_tally["2"][1] += 1

        # Tier 3 — near-miss (different entity/season -> derive its OWN gt)
        gt3 = derive_gt(v["tier3_sql"])
        rec3 = execute_query(qid, "T3", v["tier3"], gt3)
        rec3["variant_text"] = v["tier3"]
        run2_rows.append(rec3)
        tier_hit_tally["3"][0] += int(rec3["cache_hit"]); tier_hit_tally["3"][1] += 1

        seen += 1
        if seen % 10 == 0:
            print(f"   ...tally @ {seen} q:  "
                  f"T1 {tier_hit_tally['1'][0]}/{tier_hit_tally['1'][1]} hits | "
                  f"T2 {tier_hit_tally['2'][0]}/{tier_hit_tally['2'][1]} hits | "
                  f"T3 {tier_hit_tally['3'][0]}/{tier_hit_tally['3'][1]} hits (want 0)", flush=True)
        time.sleep(sleep_s)

    final_counts = all_three_counts()
    print(f"\n[counts @ end] {final_counts}", flush=True)
    print(f"   correction_memory: baseline {corr_baseline} -> {final_counts['correction_memory']}  "
          f"({'FROZEN OK' if final_counts['correction_memory'] == corr_baseline else 'GREW — WRITE GATE BROKEN'})",
          flush=True)

    # ── Write CSVs ────────────────────────────────────────────────────────
    _write_csv(RUN1_CSV, run1_rows)
    _write_csv(RUN2_CSV, run2_rows)
    print(f"\n[wrote] {RUN1_CSV}", flush=True)
    print(f"[wrote] {RUN2_CSV}", flush=True)

    # ── Summary ───────────────────────────────────────────────────────────
    summary = build_summary(run1_rows, run2_rows, vmap, qids, corr_baseline, final_counts, smoke)
    SUMMARY_TXT.write_text(summary)
    print(f"[wrote] {SUMMARY_TXT}\n", flush=True)
    print(summary, flush=True)

    if smoke:
        print("\n" + "=" * 80, flush=True)
        print("SMOKE COMPLETE. Review the cache HITs, similarities, row growth, frozen", flush=True)
        print("correction count, and token capture above. Awaiting go-ahead for the full run.", flush=True)
        print("=" * 80, flush=True)


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0].keys())
    for r in rows:
        for c in r.keys():
            if c not in cols:
                cols.append(c)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build_summary(run1, run2, vmap, qids, corr_baseline, final_counts, smoke) -> str:
    t1 = tier_stats([r for r in run2 if r["tier"] == "T1"])
    t2 = tier_stats([r for r in run2 if r["tier"] == "T2"])
    t3 = tier_stats([r for r in run2 if r["tier"] == "T3"])
    cold = tier_stats(run1)
    N = len(run1)

    def row(label, s):
        return (f"| {label:<16} | {s['hits']:>3}/{s['n']:<3} | {s['avg_sim_on_hit']:>6.3f} "
                f"| {s['avg_latency']:>7.2f}s (clean {s['avg_latency_clean']:>6.2f}s, {s['n_429']} x429) "
                f"| {s['avg_tokens']:>7.0f} ({s['avg_in']:.0f}+{s['avg_out']:.0f}) "
                f"| {s['correct']:>3}/{s['scored']:<3} |")

    # Claims
    t12_hit_rate = (t1["hits"] + t2["hits"]) / max(1, (t1["n"] + t2["n"]))
    claim1 = "CONFIRMED" if t12_hit_rate >= 0.80 else "REFUTED"
    claim2 = "CONFIRMED" if t3["hits"] == 0 else f"REFUTED ({t3['hits']} false positives)"
    warm_lat = _avg([r["latency_s"] for r in run2 if not r["hit_429"]])
    warm_tok = _avg([r["total_tokens"] for r in run2])
    claim3_lat = "CONFIRMED" if warm_lat < cold["avg_latency_clean"] else "REFUTED"
    claim3_tok = "CONFIRMED" if warm_tok < cold["avg_tokens"] else "REFUTED"
    cold_acc = cold["correct"] / max(1, cold["scored"])
    t1_acc = t1["correct"] / max(1, t1["scored"])
    t2_acc = t2["correct"] / max(1, t2["scored"])
    claim4 = "CONFIRMED" if abs(t1_acc - cold_acc) <= 0.07 and abs(t2_acc - cold_acc) <= 0.07 else "CHECK"

    lines = []
    lines.append("THREE-TIER SQL-CACHE SIMILARITY SWEEP — SUMMARY")
    lines.append("=" * 64)
    lines.append(f"Run date:   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Mode:       {'SMOKE (3 questions)' if smoke else 'FULL (46 questions)'}")
    lines.append(f"Variant:    no_control   Model: claude-opus-4-8   EVAL_MODE: cache_experiment")
    lines.append(f"Isolation:  sql_cache live; conversation_memory + correction_memory reads/writes OFF")
    lines.append(f"Synth cap:  500 output tokens")
    lines.append("")
    lines.append("Per-tier cache behaviour:")
    lines.append("| Tier             | Hits     | AvgSim | Avg latency                         | Avg tokens (in+out)  | Accuracy |")
    lines.append("|------------------|----------|--------|-------------------------------------|----------------------|----------|")
    lines.append(row("0 cold baseline", cold))
    lines.append(row("1 exact repeat", t1))
    lines.append(row("2 light reword", t2))
    lines.append(row("3 near-miss", t3))
    lines.append("")
    lines.append("Notes:")
    lines.append("  - 'clean' latency excludes any query flagged x429 (rate-limit backoff is never")
    lines.append("    inside the measured window, but a mid-pipeline 429 still flags the query).")
    lines.append("  - AvgSim is over cache-HIT queries only.")
    lines.append("  - Tier 1/2 accuracy scored vs golden ground_truth.json; Tier 3 vs its own tier3_sql.")
    lines.append("")
    lines.append("CLAIMS:")
    lines.append(f"  1. Tier1+Tier2 reuse genuine repeats/rewords (hit rate {t12_hit_rate:.0%}): {claim1}")
    lines.append(f"     T1 {t1['hits']}/{t1['n']} hits, T2 {t2['hits']}/{t2['n']} hits.")
    lines.append(f"  2. Tier3 near-miss does NOT hit (guard holds): {claim2}")
    lines.append(f"     T3 {t3['hits']}/{t3['n']} hits (any hit = false positive @ 0.88 threshold).")
    lines.append(f"  3. Warm hits cut latency + tokens vs cold:")
    lines.append(f"     latency: warm {warm_lat:.2f}s vs cold {cold['avg_latency_clean']:.2f}s -> {claim3_lat}")
    lines.append(f"     tokens:  warm {warm_tok:.0f} vs cold {cold['avg_tokens']:.0f} -> {claim3_tok}")
    lines.append(f"  4. Accuracy unchanged across tiers: {claim4}")
    lines.append(f"     cold {cold['correct']}/{cold['scored']} ({cold_acc:.0%}), "
                 f"T1 {t1['correct']}/{t1['scored']} ({t1_acc:.0%}), "
                 f"T2 {t2['correct']}/{t2['scored']} ({t2_acc:.0%}).")
    lines.append("")
    lines.append(f"Memory hygiene: correction_memory baseline {corr_baseline} -> {final_counts['correction_memory']} "
                 f"({'FROZEN OK' if final_counts['correction_memory'] == corr_baseline else 'GREW — INVESTIGATE'})")
    lines.append("")
    lines.append("VARIANT MAP (auditable rewordings):")
    for qid in qids:
        v = vmap[qid]
        lines.append(f"  {qid}:")
        lines.append(f"    T2 reword:   {v['tier2']}")
        lines.append(f"    T3 nearmiss: {v['tier3']}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="run only 3 questions then stop")
    ap.add_argument("--sleep", type=float, default=5.0, help="inter-query pacing seconds")
    args = ap.parse_args()
    main(smoke=args.smoke, sleep_s=args.sleep)
