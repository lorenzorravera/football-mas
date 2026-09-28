# V4_NOTES — Inspection of Ethan's `agent_v4/` (basis for v5)

**Author:** Claude Code · **Date:** 2026-06-03
**Source read:** `Ethan/agent_v4/` (the *richer* v4 — debate/eval/validation agents + memory).
**Purpose:** Phase 0a deliverable. Ground truth for the Phase 0.5 architecture proposal.
**Read-only:** nothing in `Ethan/` (or any other teammate folder) was modified.

> ⚠️ There are **two** `agent_v4` folders in the repo. `till/agent_v4/` is a *simpler* 5-agent
> version (manager / data_discovery / data_analyst / synthesizer / visualizer, no memory).
> **`Ethan/agent_v4/` is the basis for v5** — it adds the debate, eval, validation agents and the
> pgvector memory layer. All notes below describe Ethan's version.

---

## 1. LangGraph topology (what actually runs)

From `Ethan/agent_v4/graph.py` → `create_graph(variant)`:

```
memory_retrieval                    (entry)
   → manager
        ├─ error OR conversational ─────────────► synthesizer
        └─ data_request | full_pipeline ──► data_discovery
   data_discovery
        → data_analyst                 (validation + retry loop INTERNAL to this node)
              ├─ error ────────────────────────► synthesizer
              ├─ full_pipeline ──► visualizer ──► synthesizer
              └─ data_request ─────────────────► synthesizer
   synthesizer
        → eval_agent                   (rule-based post-check, writes correction memory)
        → memory_store
        → END
```

`variant` ("full_control" | "semi_control" | "no_control") is bound into the `data_analyst`
node via a lambda; everything else is identical across variants. `run_agent()` streams the graph
and returns the final state dict.

### 🚩 Discrepancy #1 — the debate agent is **NOT in the graph**
The spec (constraint 2, Phase 0.5 decision 1) says *"a separate debate agent writes two SQL
queries and, if they match, passes the result to the data analyst."* **That is not the wired
behaviour.** `agents/debate_agent.py` exists and is fully implemented, but:
- `agents/__init__.py` does **not** export it, and `graph.py` never adds a `debate` node.
- The `debate_*` fields in `state.py` are initialised in `create_initial_state()` and then
  **never read** anywhere in the live pipeline.

So debate logic is **dead/unwired code today**. Consequence for v5: "fold debate into the data
analyst" is effectively a **net-new self-debate loop** (informed by `debate_agent.py`'s logic),
not a refactor of a running path. *(v4 code wins over the spec — flagging per the spec's own rule.)*

---

## 2. What each agent does (from the code, not guessed)

| Node | File | Role | LLM? |
|---|---|---|---|
| `memory_retrieval` | `memory/memory_agent.py` | Pre-pipeline; hydrates `memory_context`, `cached_sql` (+`sql_cache_hit`/`meta`), `memory_warnings` from pgvector. All best-effort (swallows errors). | embeds only |
| `manager` | `agents/manager.py` | Intent classification (`conversational`/`data_request`), PL-relatedness, param extraction. **Resolves relative seasons** ("last"/"current") to a concrete season via `_get_season_context()` (date-driven). Early-returns if `intent` was pre-set by app.py. | yes |
| `data_discovery` | `agents/data_discovery.py` | LLM picks `relevant_tables` + `relevant_columns` from the schema context. Output is advisory — the analyst regenerates SQL anyway. | yes |
| `data_analyst` | `agents/data_analyst.py` | 3 variants + SQL-cache fast-path + internal validation-retry loop (see §3). | yes |
| `visualizer` | `agents/visualizer.py` | Plotly chart generation (only on `full_pipeline`). **Out of scope for eval** (no-viz). | yes |
| `synthesizer` | `agents/synthesizer.py` | Final natural-language answer from `data_result` (head(20) preview) + memory context. Short-circuits on `needs_clarification`/`error`/empty. | yes |
| `eval_agent` | `agents/eval_agent.py` | **Rule-based, no LLM.** Post-response consistency check (see §4). | no |
| `memory_store` | `memory/memory_agent.py` | Persists turn to pgvector: conversation, sql_cache (success), correction (error). | embeds only |
| `validation_agent` | `agents/validation_agent.py` | **Not a node** — helper called inside `data_analyst` (see §3/§4). | no |

`config.AGENT_DEFAULTS` routes **every** agent to `"claude"` by default.

---

## 3. Data-analyst control variants (the DoF basis)

`data_analyst_agent(state, variant)` (`data_analyst.py:490`) dispatches to:

- **`_full_control_analyst`** — LLM maps the query to **one of 10 predefined functions**
  (`tools/sql_functions.py`), returns a JSON `{function, params}`. No custom SQL. If nothing
  matches → emits a clarification question (`needs_clarification=True`).
- **`_semi_control_analyst`** — LLM chooses per-query: use a predefined function **or** write
  custom SQL (`read_sql`). Routing is entirely the LLM's (no heuristics). This is the variant
  the DoF "failure taxonomy" (Phase 5) analyses.
- **`_no_control_analyst`** — always writes custom SQL from scratch; injects `skills.md` excerpts
  + `memory_warnings` into the prompt.

Wrapper behaviour (all variants):
1. **SQL-cache fast-path** — if `cached_sql` exists and isn't a `Function:` marker, it runs the
   cached SQL and, if non-empty + valid, **returns immediately, skipping LLM generation**.
   *(This is a cross-run contamination vector — see §6.)*
2. **Validation-retry loop** — up to `MAX_RETRIES = 2`. After each attempt it calls
   `validate_result()`; on failure it clears `data_result`/`sql_query` and re-prompts with a
   `validation_hint`. (`semi`/`no` inject the hint; `full` regenerates the function choice.)

The three variants map cleanly onto Phase 4's controlled / semi-controlled / autonomous modes.
**But** their SQL is keyed to the wrong schema (see §7), so the *structure* is reusable, the
*SQL/function bodies* are not.

### How the (unwired) debate agent generates/compares two SQL queries
`debate_agent.py` (for reference, since v5 absorbs this idea):
- `_generate_sql()` twice — **Path A at temperature 0.0, Path B at 0.2** — same prompt.
- Executes both via `read_sql`; compares with `_results_agree()` = **same shape AND
  equal sorted numeric-column sums (tol 0.01)**.
- If agreed → injects winning SQL into `cached_sql` so the analyst fast-paths it.
  If disagreed → sets `debate_agreed=False`.
- Skips entirely on a high-confidence cache hit (similarity ≥ 0.88).

This "result-set agreement" notion is a good seed for the v5 self-debate convergence test.

---

## 4. eval_agent vs validation_agent (Till's open question)

**`validation_agent.validate_result(query, sql, df)`** — a helper, **not a graph node**.
Today it only checks **`df` is non-empty** (returns a retry hint if empty). The original
LLM-based relevance check was **removed** (comment cites LangGraph DataFrame-serialization
constraints). So its live job is purely "empty result → retry". It runs *inside* the analyst loop.

**`eval_agent`** — a real graph node between `synthesizer` and `memory_store`. **Rule-based,
no LLM call.** It:
1. extracts numbers from `final_response` (regex) and compares them to numeric values in
   `data_result`;
2. handles the empty-result case (passes if the response correctly *denies* having data);
3. sets `eval_score ∈ {1.0, 0.5, 0.0}` + `eval_correction`;
4. on a problem, **writes to `correction_memory`** (so the next similar query is warned).

Roles overlap only loosely: validation gates *before* the answer (retry on empty), eval checks
*after* the answer (number consistency) and feeds memory. Neither sees the golden set.

### 🚩 Discrepancy #2 — circularity risk is LOW but present
The spec (Phase 0.5 decision 2) warns about runtime self-validation leaking into the offline
Phase 5 LLM-judge. Good news: **`eval_agent` uses no LLM** and **no golden set**, so there's no
direct circularity with the offline judge. Its only real effect is feeding `correction_memory`
— i.e. it's part of the **memory loop**, which must be OFF for scored runs (§6). For scored MAS
runs, the clean options are: keep the node but no-op its memory write under `memory_enabled=false`,
**or** drop it from the scored topology. (Decided in the proposal.)

---

## 5. DB access & schema loading

- **DB access:** all SQL goes through `till/db/connection.py` → `read_sql(query, params)`
  (SQLAlchemy engine singleton; rewrites `postgres://`→`postgresql://`; reads `DATABASE_URI`).
  `Ethan/agent_v4/` reaches it via a `db` **symlink → `../till/db`**.
  ⚠️ `read_sql` does **NOT** enforce read-only / SELECT-only / a statement timeout — the v5
  `run_sql` entry point must add those guards (spec constraints 6–7).
- **Schema loading:** `schema_loader.get_schema_context()` formats a **static YAML**
  (`till/db/schema_context.yaml`) into a prompt string. The *mechanism* is reusable; the
  *content* is the wrong schema (§7).

---

## 6. Memory + correction layer (and why it's a scored-run hazard)

`memory/vector_store_pg.py` — pgvector **on the same Aiven Postgres** as the data, embeddings via
`chromadb` `DefaultEmbeddingFunction` (all-MiniLM-L6-v2, 384-dim), `psycopg2` connection.
Three tables (+ a `feedback` table): `conversation_memory`, `sql_cache`, `correction_memory`.
Thresholds: SQL-cache 0.88, conversation 0.70, correction 0.75.

Flow: `memory_retrieval` (pre-manager) hydrates state → analyst uses `cached_sql` (fast-path,
skips LLM) and `memory_warnings` (prompt injection in `no_control`/debate) → `eval_agent` and
`memory_store` write back.

### 🚩 Discrepancy #3 / hazard — memory **warms within a run set**
Because `sql_cache` persists to a shared DB and is retrieved by semantic similarity (≥0.88),
running the 45 golden questions × 3 repeats with memory ON means **later repeats can reuse earlier
SQL** — a direct confound. Constraint 10 (memory OFF for scored runs, verifiably not warming) is
therefore essential. The toggle must disable **both** retrieval and store (and the eval_agent
write). The memory tables also live alongside the data tables, but they're separate relations so
the read-only `run_sql` data path is unaffected.

---

## 7. ⛔ HEADLINE FINDING — v4 targets a DIFFERENT (older) schema than the live DB

Every SQL surface in v4 — the 10 functions in `tools/sql_functions.py`, the prompts in
`data_analyst.py` / `debate_agent.py` / `data_discovery.py`, and `db/schema_context.yaml` —
is written against an **older, hand-modelled schema that does not exist in the new Aiven DB.**

| v4 assumes (OLD) | Actually in the live DB (NEW) |
|---|---|
| `league_table` (view) | ❌ does not exist → use `team_season_standings` / `vw_team_season_summary` |
| `match_team_stats` (2 rows/match) | ❌ does not exist → `matches` has `home_*`/`away_*` columns |
| `points_adjustments` (table) | ❌ does not exist → deductions baked into `tss_points` |
| `referees` (`referee_id`) | ❌ does not exist → `matches.referee` is a **text** column |
| `matches.match_id`, `ft_home_goals`, `ft_away_goals` | `matches.game_id`, `home_score`, `away_score`, `ft_result` |
| season format `2023_2024` (underscore) | **`2023-2024` (hyphen)** in `seasons.season`, `tss_season`, etc. |
| "current season" = 2025_2026 | latest season in DB = **`2024-2025`** (no 2025-26 data) |

Evidence: a repo-wide grep shows the **new** schema names (`vw_team_season_summary`,
`team_season_standings`, `game_id`, `tss_points`) appear **only in the two spec/metadata docs** —
in **no agent code anywhere** (v1, v2, both v4s all use the old names).

**Implication.** The spec's "reuse v4's schema loader / SQL functions" assumption is partly broken.
v5 must **rebuild the data layer against the new schema** (new `schema_context`, new templates /
predefined functions, season-format handling). This is the central thing the architecture proposal
must address, and it's real new work — not a thin wrapper.

---

## 8. Langfuse tracing — currently OFF

`config.py` has a `set_trace_context()` mechanism and a `_trace_id` ContextVar, **but the Langfuse
callback block is commented out** (`config.py:46–52`), so no traces are emitted today. The spec
(Phase 4) needs per-run capture of tool calls, args, returned rows, tool-call sequence, and
self-debate iterations → v5 must actually **wire tracing** (Langfuse keys are present in
`till/.env`), or capture this structured trace itself in the run records.

---

## 9. Models / LiteLLM routing

`config.MODEL_MAP = {"claude": "anthropic/claude-sonnet-4-20250514", "gpt4o": "gpt-4o"}`.
Only **Claude + GPT** today — **no Gemini**. The docstring mentions in-memory caching but there's
no caching code (consistent with project memory: LiteLLM caching disabled on Py3.13). For the
9-cell design v5 must add a **Gemini** route (key `GEMINI_API_KEY` is in `till/.env`) and pin exact
version strings in the manifest (per the "latest per family" decision; IDs to be confirmed).

---

## 10. Existing eval (`eval_runner.py`) — for reference only

Runs ~20 golden queries (`till/eval/golden_set/...`) through `run_agent`, scores by fuzzy
number-overlap (≥0.8 correct / ≥0.4 partial), single variant, vs a v2 baseline. This is the
*old* eval; v5 replaces it with the proper harness (deterministic ground truth, ≥3 repeats,
programmatic-first scoring, paired stats). Worth knowing the scoring pitfalls it shows
(number-overlap is noisy) — v5's `score.py` should be stricter (typed: scalar/ranking/table).

---

## 11. Reuse-vs-rebuild inventory (input to the proposal)

| Component | Verdict for v5 |
|---|---|
| `graph.py` topology, routing | **Reuse/adapt** (drop unwired debate; add self-debate inside analyst) |
| `state.py` | **Reuse/adapt** (prune dead `debate_*` if absorbed) |
| `config.py` LiteLLM routing | **Reuse + extend** (add Gemini; pin versions; wire Langfuse) |
| `db/connection.py` | **Reuse, wrap** in read-only `run_sql` (SELECT/WITH-only + timeout) |
| `schema_loader.py` mechanism | **Reuse mechanism** |
| `schema_context.yaml` content | **Rebuild** against new schema |
| `tools/sql_functions.py` (10 fns) | **Rebuild** as new-schema templates (Phase 3) |
| `tools/skills.md` | **Rebuild** against new schema |
| manager / data_discovery / synthesizer | **Reuse/adapt** (fix season format → hyphen; fix "current season") |
| data_analyst 3 variants | **Reuse structure**, rebuild SQL + add self-debate |
| visualizer | **Cut from eval** (no-viz) — keep available but off scored path |
| debate_agent | **Cut as node**; **absorb logic** into analyst self-debate |
| validation_agent | **Keep/simplify** (empty-result retry) — proposal decides |
| eval_agent | **Keep but gate** off memory for scored runs, OR cut — proposal decides |
| memory/* | **Keep as toggle, OFF for scored runs** (constraint 10) |

See `ARCHITECTURE_PROPOSAL.md` for the proposed v5 topology and the keep/modify/merge/cut table.
