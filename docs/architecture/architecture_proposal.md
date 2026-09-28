# ARCHITECTURE_PROPOSAL — agent_v5 MAS

**Author:** Claude Code · **Date:** 2026-06-03
**Status:** 🔴 PROPOSAL — *do not build until Till approves.*
**Inputs:** `V4_NOTES.md`, `results/phase0/audit_report.md`, `Claude_specs.md`.

This proposes the v5 design: keep Ethan's v4 strong core, make the two required changes
(fold debate into the analyst; memory off-by-default), rationalise the eval/validation agents,
and **rebuild the data layer for the new schema** — without over-engineering. v5 is an *eval
harness around the MAS*, not a maximal new MAS.

---

## 0. The decision that reshapes everything: rebuild the data layer (NOT in the spec)

Phase 0 confirmed (see `V4_NOTES.md` §7): **all of v4's SQL targets an older schema that does not
exist in the live DB.** `league_table`, `match_team_stats`, `points_adjustments`, `referees`,
`matches.match_id/ft_home_goals` are gone; the live DB uses `team_season_standings`/`vw_team_season_summary`,
`matches.game_id/home_score/away_score/referee(text)`, deductions baked into `tss_points`, and
**hyphen** season strings (`2023-2024`, latest `2024-2025`).

**Proposal:** treat the *data layer* as new work, the *orchestration layer* as reuse.
- Rebuild `tools/schema_context.py` from the **live** schema (introspected + the metadata doc),
  with caveats: points deductions in `tss_points`; season format `YYYY-YYYY`; "last"=2024-2025
  and **no 2025-26 data**; prefer IDs over names; partitioned event tables are large.
- Rebuild the predefined functions as the Phase-3 **templates** against the new schema.
- One identical `schema_context` string is injected into **every** condition (no condition gets a
  richer schema — spec's core parity rule).

This is the single biggest delta from the spec's "just reuse v4" assumption. Everything below
assumes it.

---

## 1. Proposed v5 node topology

**Scored MAS (autonomous condition, `memory_enabled = false`) — the lean path:**

```
manager → data_discovery → data_analyst → synthesizer → END
                              │
                              └─ self-debate loop (dual-SQL → converge) + empty-result retry
```

**Full system blueprint (memory ON — preserved as a toggle, used for the paper's system
description, NOT for scored runs):**

```
memory_retrieval → manager → data_discovery → data_analyst → synthesizer → eval_agent → memory_store → END
```

The two topologies are the **same graph** built by one factory with flags
(`memory_enabled`, `eval_enabled`); when `memory_enabled=false` the `memory_retrieval`,
`memory_store`, and `eval_agent` nodes are **simply not added** to the graph (guarantees no
warming — see §4). `visualizer` is removed from the eval path entirely (no-viz; constraint 4).

Routing is inherited from v4 (manager→synthesizer on conversational/error; analyst→synthesizer).
For eval, inputs are analytics questions, so the live path is the straight line above.

---

## 2. Every v4 agent → keep / modify / merge / cut

| v4 component | Verdict | One-line justification |
|---|---|---|
| `manager` | **Modify** | Keep intent+param extraction; fix season format to hyphen; pin "current" to 2024-2025 (no 2025-26 data). |
| `data_discovery` | **Keep (light)** | Cheap table/column shortlist; harmless, mild benefit. Could be merged into analyst later if it adds no measured value (defer — don't over-engineer now). |
| `data_analyst` (3 variants) | **Modify** | Reuse the full/semi/no structure; rebuild SQL for new schema; add self-debate loop (§3). This is the DoF engine. |
| `debate_agent` | **Cut as node / absorb** | Already unwired (V4_NOTES §1). Its dual-SQL + result-agreement idea moves *inside* the analyst (§3). Delete the standalone node + dead `debate_*` state. |
| `validation_agent` | **Merge → simplify** | Fold its only live behaviour (empty-result → retry) into the analyst loop. No separate module/LLM check. |
| `eval_agent` | **Cut from scored path** | Rule-based, no in-run self-correction; its only effect is feeding `correction_memory` (memory = off). Keep it behind the memory toggle for the blueprint; its number-consistency idea is reused **offline** in `score.py`, cleanly separating runtime from offline scoring (kills the circularity concern, spec decision 2). |
| `synthesizer` | **Keep** | Final NL answer; already constrained to "use only the data". |
| `visualizer` | **Cut from eval** | No-viz eval (constraint 4); remains in the deployed app, off the scored path. |
| `memory/*` (retrieval, store, pgvector) | **Keep as toggle, OFF for scored** | Part of blueprint; constraint 10. Off-by-default via flag (§4). |
| `config.py` LiteLLM | **Modify** | Add Gemini route; pin exact version strings in manifest; wire Langfuse (currently commented out). |
| `db/connection.py` | **Wrap** | Reuse engine; expose only via read-only `run_sql` (SELECT/WITH-only + statement timeout). |

---

## 3. Self-debate loop (required change #1) — design

Replaces the standalone debate agent. Applies **wherever the analyst writes free-form SQL**:
the autonomous mode (always), the semi mode (when it chooses custom SQL), and the MAS analyst.
It does **not** apply to template-only paths (controlled mode), which have no free SQL to debate.

**Loop:**
1. Generate **two independent SQL candidates** A and B (two separate LLM calls, same prompt,
   low temp ≈ 0.3 per Phase 5 so routing/generation variance is real, not zero).
2. Execute both via `run_sql`.
3. **Convergence test = result-set match** (recommended over SQL-string match — two different
   correct queries should count as agreement). Canonicalise each result: same column set,
   numerics rounded to a fixed tolerance, rows compared as an order-insensitive multiset (unless
   the question is explicitly "ranked/ordered", in which case order matters). `empty == empty` agrees.
4. **Agree →** proceed with that result set.
5. **Disagree →** the analyst *debates itself*: re-prompt with both candidate SQLs + their result
   summaries, asked to reconcile into a new pair. Repeat up to **`MAX_DEBATE_ITERS = 2`**.
6. **Never converged →** return best-effort (prefer a non-empty, schema-valid candidate) flagged
   `low_confidence = true` in the run record. Never hang.
7. Also retains the **empty-result retry** (from `validation_agent`): an empty result is treated
   as non-convergent and triggers a regeneration with a hint.

**Tracing:** each iteration logged (iteration index, SQL_A, SQL_B, agreement bool, row counts,
final decision, low_confidence). Captured in Langfuse and mirrored into the run JSON so Phase 5/6
can analyse debate iterations.

Open recommendation: result-set tolerance = round floats to 2 dp; `MAX_DEBATE_ITERS = 2`.
(Confirm — see §6.)

---

## 4. Memory toggle (required change #3) — design

**Flag:** `memory_enabled: bool` in `config.py`, default **`False`**, recorded in every run record
and in `manifest.json` for every scored phase.

**When `False` (all scored runs):**
- The graph factory **does not add** `memory_retrieval`, `memory_store`, or `eval_agent` nodes.
  (Not "add them but return early" — physically absent, so nothing can warm.)
- `cached_sql`/`memory_*` are never populated, so the analyst's cache fast-path is inert.
- No pgvector reads or writes occur during the run.

**When `True` (blueprint / optional experiments only):** the full bracketed topology runs.

**Verification (so we can *prove* it isn't warming mid-run):**
- Startup assertion: scored runners assert `memory_enabled is False`.
- A test that runs the *same* question twice under scored config and asserts (a) `sql_cache_hit`
  is always `False`, and (b) the pgvector `sql_cache` row count is unchanged before/after.
- `manifest.json` carries `memory_enabled: false` per scored phase (spec persistence rule).

Nothing is deleted — the memory modules stay vendored and runnable for the paper's blueprint.

---

## 5. Anti-over-engineering choices (required #4)

- **Cut from the scored path:** visualizer, eval_agent (kept only as a memory-toggle/offline idea),
  standalone debate node, the SQL-cache fast-path, conversational branch (eval inputs are all
  data questions).
- **Defer:** merging `data_discovery` into the analyst (keep it; revisit only if it shows no
  measured benefit), the prediction slice (Phase 7 stub now, run later).
- **Single source of truth:** one `run_sql`, one `schema_context`, one tool registry shared by all
  conditions — the only thing that varies between conditions is **which tools are registered**
  (the spec's load-bearing parity rule).

Net scored MAS = 4 live nodes (manager, data_discovery, data_analyst+self-debate, synthesizer).

---

## 6. Open questions for Till

1. **eval_agent:** OK to **cut it from the scored MAS** (kept behind the memory toggle for the
   blueprint; its number-consistency check reused offline in `score.py`)? Or do you want it kept
   as an active node even in scored runs? *(My recommendation: cut from scored path.)*
2. **Scope of data:** golden set restricted to **ENG-PL, seasons 2020-21 … 2024-25** (the only data
   present). Confirm "current/this season" questions are pinned to **2024-2025** (no 2025-26 data).
3. **Self-debate params:** result-set match with floats rounded to 2 dp, order-insensitive except
   for explicitly ranked questions; `MAX_DEBATE_ITERS = 2`; best-effort+`low_confidence` on
   non-convergence. Confirm or adjust.
4. **Self-debate scope:** confirm it applies only where the analyst writes free SQL (autonomous
   always, semi when custom, MAS analyst) and **not** to template-only controlled mode.
5. **Models (latest per family):** propose pinning — Claude `claude-opus-4-8` (or a Sonnet tier for
   cost), GPT (`gpt-5`-class), Gemini (`gemini-2.5`-class) — exact LiteLLM IDs to be confirmed at
   Phase 1 / manifest time. Any required version constraints for the paper?
6. **Data-layer rebuild (§0):** confirm you accept that the templates + `schema_context` + the
   analyst's SQL are **rebuilt for the new schema** (not ported from v4), since v4's SQL can't run
   on this DB.
7. **Langfuse:** wire it for real (keys are in `till/.env`), or capture the structured trace
   ourselves into the run JSON? *(Recommendation: wire Langfuse AND persist a self-contained trace
   in each run record, so scoring never depends on Langfuse availability — matters for headless/
   Batch runs.)*

---

## 7. If approved — first build steps (Phase 1, not started)

1. Vendor the minimal v4 orchestration modules into `till/agent_v5/` (graph/state/config/agents,
   memory as a toggled package) — `Ethan/` untouched.
2. `tools/run_sql.py` (read-only SELECT/WITH + timeout, wrapping `db/connection`), verified on the
   2023-24 table with Everton/Forest deductions reflected; non-SELECT rejected (spec Phase 1 gate).
3. `tools/schema_context.py` rebuilt from the live schema; `tools/predict_match_outcome.py` stub.
4. `golden/schema.py` `GoldenItem` scaffold.
Then STOP for Phase 2 (golden set) per the freeze order.
