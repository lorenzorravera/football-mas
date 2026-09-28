# Session memory experiment — results (n=55, 2026-07-01)

Multi-step within-session carry-over, 4 arms (`mas_memory`, `mas_no_memory`,
`single_llm_stateless`, `single_llm_history`), scored on **beneficiary** turns (the turns that
should reuse what an earlier turn established). Primary metric = mean verdict score
(correct=1.0 / partial=0.5 / wrong=0.0). Reproduce with
`python eval/session_runner.py && python eval/session_report.py`.

**Scaled from n=19 → n=55** (correction 9→20, cache 5→18, conversation 5→17) to power the
Wilcoxon test; the suite is generated + DB-validated by `eval/gen_sessions.py`. The headline
effect of the scaling: **conversation reference-resolution vs the stateless single-LLM is now
statistically significant (p=0.0002)**, where at n=5 it was only directional (p=0.125).

## Headline — paired Δ (mas_memory − baseline) on beneficiary turns

| sub-experiment (n) | vs single_llm_stateless | vs single_llm_history | vs mas_no_memory |
|---|---|---|---|
| **conversation** (17) | **+0.574**  (p=**0.0002**) | −0.397  (p=0.0068) | +0.147  (p=0.078) |
| **correction** (20) | +0.100  (p=0.50) | +0.225  (p=0.125) | +0.200  (p=0.125) |
| **cache** (18) | +0.000 | +0.000 | +0.000 |

Significant at α=0.05: **conversation vs stateless** (memory beats no-context reference
resolution) and **conversation vs full-history** (full transcript beats sparse memory — the
expected *negative*). Everything else is directional but under the bar; see per-family notes.

## Per-arm beneficiary accuracy

| arm | correction (21 turns) | conversation (34 turns) | cache (18 turns) |
|---|---|---|---|
| **mas_memory** | **0.952** | **0.574** | 0.944 |
| mas_no_memory | 0.714 | 0.426 | 0.944 |
| single_llm_stateless | 0.857 | **0.000** | 0.944 |
| single_llm_history | 0.714 | **0.971** | 0.944 |

## What each sub-experiment shows

- **conversation (the significant result):** the stateless single-LLM scores **0.000** on
  beneficiary turns — it structurally cannot resolve "they / their / that team" with no prior
  context. `mas_memory` recovers this to **0.574** from pgvector conversation memory (Δ=+0.574 vs
  stateless, **p=0.0002**, n=34 beneficiary turns) and beats `mas_no_memory` (0.426) by +0.147.
  It does *not* beat `single_llm_history` (0.971), which carries the entire transcript in-context —
  Δ=−0.397, p=0.0068 — an honest, expected result: sparse retrieved memory is weaker than the full
  transcript at reference resolution, but costs far fewer tokens (see `trajectory_log`). The
  scaling from n=5→17 is what moved this from "directional" to "significant."

- **correction:** `mas_memory` is best (0.952 vs 0.714 for `mas_no_memory`/`history`), and the
  memory-isolating comparison holds at **Δ=+0.200 vs `mas_no_memory`** — but not significantly
  (p=0.125). The magnitude fell vs the n=9 pilot (+0.222) because the broadened template mix
  (wins / clean-sheet / player-join / team-sum) includes pitfalls the base agent already solves
  *without* carried memory — so those sessions are ties (Δ=0) that memory can't improve. Note the
  stateless arm scores 0.857 here (each beneficiary turn is self-contained SQL, unlike
  conversation), which is why Δ vs stateless is only +0.10. The decisive sessions remain the
  **referee non-breaking-space** and **team home+away summation** pitfalls, where only the memory
  arm carries the harness-seeded lesson to a different entity — genuine transfer, not recall. See
  `session_runner._seed_correction` for the honest-caveat design (the rule-based eval_agent can't
  detect wrong-but-self-consistent SQL, so the harness supplies the failure signal).

- **cache:** Δ=0.000 accuracy on every arm — **by design**, now confirmed at n=18. The cache's
  payoff is latency/tokens (in `trajectory_log`, `experiment='session_eval'`), not accuracy; equal
  accuracy is the success condition (it must not change answers). All arms sit at 0.944 (one
  near-repeat family is uniformly partial across every arm, so the paired Δ is still exactly 0).

## Takeaways for the write-up

1. **Within-session conversation memory measurably and significantly helps** reference resolution
   over a stateless agent (+0.574, p=0.0002) while using far fewer tokens than full-history.
2. **Correction memory helps directionally** (+0.20 vs `mas_no_memory`) but the effect is
   concentrated in genuinely hard pitfalls; a base agent already handles many SQL patterns, so a
   broad suite dilutes the mean. Not significant at this n.
3. **Cache is accuracy-neutral by design** — its win lives in the cost columns, not here.

## The SQL-cache bug this experiment surfaced (and the fix)

The **first** full run (at n=19) gave the OPPOSITE correction result — `mas_memory` Δ=−0.278 vs
`mas_no_memory`. Investigation (per-session SQL diff) showed it was **not** the correction
mechanism: it was **SQL-cache cross-entity reuse**. The cache keys on query *embedding*
similarity (≥0.88), but the cached SQL has literal team/season/metric values hardcoded, so a
structurally-identical but different-entity follow-up silently reran the wrong query:

| session | beneficiary asked | reran (cached trigger SQL) |
|---|---|---|
| cleansheet | Liverpool, 2024-25 | Arsenal, 2023-24 |
| playerjoin | Liverpool top scorer | Manchester City's |
| teamseason_03 | Liverpool **yellow** cards | Chelsea **red** cards |

**Fix:** an entity-consistency guard in `memory/vector_store_pg.py::query_sql_cache`
(`_cache_consistency_ok`) — even above the similarity threshold, a hit is rejected when the
season / metric / team in the new query doesn't match the cached one. Validated: rejects all 3
cross-entity reuses, allows all legitimate cache near-repeats (so the cache sub-experiment keeps
its latency win).

> Takeaway: the experiment's real contribution is twofold — (1) within-session
> conversation/correction memory helps a strong base agent on the turns designed to need it
> (conversation significantly so at n=55), and (2) the harness caught a genuine memory-safety bug
> (semantic SQL cache reusing entity-mismatched queries) that a single-shot eval would have missed.
