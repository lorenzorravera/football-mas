# Premier League MAS vs Single-LLM — Experiment Build Spec

**For: Claude Code**
**Author: Till**
**Target venue: MLSA26 (European Conference on ML for Sports Analytics)**

---

## 0. Hard constraints — read first

1. **Create a new folder `agent_v5/` next to the existing `agent_v4/`** (Till will confirm the exact parent path when seeding this spec). Put ALL new code in `agent_v5/`. Do NOT modify any existing folder — `agent_v4/`, earlier agent_vN folders, `data_prep/`, or any teammate's folder (e.g. Ethan's). They are **read-only reference only**.
2. **Inspect Ethan's `agent_v4/` BEFORE writing anything — it is the BASIS for v5.** There are two v4-like versions in the repo; the one that matters is **Ethan's v4**, which is richer: beyond the manager / data_discovery / data_analyst / synthesizer / visualizer agents, it adds a **debate agent, an eval agent, a validation agent**, and the **memory retrieval + correction** layer. v5 inherits this lineage. Read its `graph.py` (LangGraph topology), `state.py`, every file in `agents/`, `tools/`, `config.py`, `schema_loader.py`, and any memory module. **Mirror its real structure and naming. The folder layout in this spec is a suggested starting point, NOT a prescription — defer to what Ethan's v4 actually does and adapt.** If this spec contradicts that code, the code wins; note the discrepancy to Till.
3. **Reuse v4, don't reinvent.** Where v4 already has working pieces (DB connection logic, schema loader, LiteLLM routing, the data_analyst SQL variants), build `agent_v5` on top of or by importing/adapting them rather than rewriting from scratch. The goal is an eval harness around the existing MAS, not a new MAS.
4. **This is eval-only. Ignore deployment.** Do NOT touch or build Modal / `modal_app.py` / Chainlit `app.py` / UI concerns. We only care about producing the experiment results and tables for the paper. Runs can be plain scripts/notebooks.
5. **Never edit a frozen artifact after it is committed.** Frozen artifacts (golden set, ground truth, coverage labels) carry a hash and a generation timestamp. If a change seems needed, stop and ask Till — do not silently regenerate.
6. **One database code path.** All DB access for the eval goes through a single read-only `run_sql` entry point in `agent_v5/`. No eval file opens a DB connection directly. If v4 already centralizes DB access, wrap/reuse it.
7. **Read-only DB access.** `run_sql` must reject anything that is not a single `SELECT`/`WITH` statement, and must set a statement timeout. Agents never mutate the database.
8. **Persist everything before scoring.** Every raw run is written to disk before any scoring happens. Scores are derived from stored raw runs + stored ground truth — never recomputed by re-running models.
9. **No work on the prediction models themselves.** The prediction tool is a STUB in this build (see Phase 7). Ethan's real models arrive later.
10. **Memory is OFF for all scored runs — but kept as an option.** Ethan's v4 has a memory/correction layer. v5 must preserve the *option* to run with persistent memory (it's part of the system blueprint for the paper), but every **scored** eval run executes with memory disabled via a clean flag (e.g. `memory_enabled: false`). Do not delete the memory capability; just ensure it's off and verifiably not warming mid-run for scored conditions.
11. Ask before installing new heavy dependencies. Prefer the stack already in use: LangGraph, LiteLLM, Langfuse, psycopg/SQLAlchemy, pandas, scipy.
12. Commit in the phase order below. Do not start a phase until the previous phase's acceptance criteria pass and Till has reviewed any gating output (especially Phase 0 and the freeze steps).

---

## Project goal (so you understand the "why")

We are testing **when a Multi-Agent System (MAS) beats a single LLM** on football data analytics, and isolating *orchestration* from *data/tool access*. Three scored conditions, three models each (9 cells):

| | MAS (autonomous, memory OFF) | Single LLM + same tools | Single LLM + raw data only |
|---|---|---|---|
| Claude | ✓ | ✓ | ✓ |
| GPT | ✓ | ✓ | ✓ |
| Gemini | ✓ | ✓ | ✓ |

Plus a **degrees-of-freedom (DoF) sub-experiment** (SQL questions only): controlled / semi-controlled / autonomous SQL agents, analyzed by template **coverage** (in vs out).

The single biggest correctness rule of the whole project: **the only thing that may differ between conditions is orchestration and tool registration. Tool access must be identical at the interface level.** If you ever write condition-specific tool logic, stop — that is a confound.

---

## Folder layout (SUGGESTED — defer to v4's real structure)

This is a starting suggestion only. **First inspect Ethan's `agent_v4/` and mirror its real conventions** (it has `agents/`, `tools/`, `graph.py`, `state.py`, `config.py`, `schema_loader.py`, plus debate/eval/validation agents and a memory module). Adapt the names below to match, and follow the **approved architecture from Phase 0.5**. The point is an eval harness in `agent_v5/` that drives the v5 MAS — not a reinvented system. No Modal, no Chainlit, no UI.

```
agent_v5/
  README.md                 # what this is, how to run each phase
  config.py                 # reuse/adapt v4's LiteLLM routing; pin model version strings
  manifest.py               # writes/updates results/manifest.json
  tools/
    run_sql.py              # THE single read-only DB entry point (wrap/reuse v4's DB logic)
    schema_context.py       # one canonical schema string for all prompts (reuse v4 schema_loader)
    predict_match_outcome.py# STUB prediction tool (fixed dummy vector)
  phase0/
    audit.py                # DB completeness + integrity + EDA
  golden/
    schema.py               # GoldenItem data model
    generate.py             # question drafting + canonical_sql authoring
    build_ground_truth.py   # runs canonical_sql, freezes ground truth
  templates/
    library.py              # ~10-12 purpose-built parameterized SQL templates
    label_coverage.py       # freezes in/out-of-coverage labels
  conditions/
    sql_agent.py            # 3 DoF variants behind one interface (mode switch)
    mas_runner.py           # drives the designated v4 MAS, memory off
    single_llm.py           # single-LLM + tools, and + raw-data, conditions
  eval/
    runner.py               # live runs (MAS + tool-using conditions)
    batch_runner.py         # Batch API for raw-data / no-live-loop conditions
    score.py                # programmatic scoring + LLM-judge for free-text only
    judge_validation.py     # judge vs human agreement on a sample
    failure_taxonomy.py     # classify semi-controlled failures from traces
    stats.py                # paired tests, effect sizes, breakdowns
    tables.py               # regenerate the 4 paper tables
  results/                  # ALL outputs land here (see structure below)
```

Note: the 3 DoF SQL variants likely already exist in some form inside Ethan's v4 `data_analyst.py` (full / semi / no control). **Check before building** — adapt what's there (plus the self-debate loop) rather than duplicating it.

### `results/` structure (create and respect exactly)

```
results/
  phase0/        audit_report.md, audit_results.json
  golden/        golden_set.json (FROZEN+hashed), ground_truth.json (FROZEN+hashed), appendix_canonical_sql.md
  templates/     coverage_labels.json (FROZEN+hashed), coverage_matrix.md
  runs/
    dof/         one JSON per run: {question_id, condition, model, repeat, answer, tool_sequence, tokens, latency, timestamp}
    mas_vs_single/
    prediction/  (filled later when models land)
  traces/        exported Langfuse traces per run_id
  scores/        per-run scores, judge verdicts, judge_validation.json
  stats/         aggregates, paired-test outputs, effect sizes
  tables/        table1_dof_coverage, table2_failure_taxonomy, table3_mas_vs_single, table4_judge_agreement
  manifest.json  run config, model version strings, temperature, repeat count, git commit + date per phase, memory_enabled flag
```

**Persistence rules (enforce in code):**
- Write each raw run to `results/runs/.../` *before* scoring it.
- Scores read from `results/runs/` + `results/golden/ground_truth.json`. They never call a model.
- Tables read from `results/stats/`. Never hand-edit a number into a table.
- `manifest.json` records, per phase: git commit hash, date, model version strings, temperature, repeat count, the designated v5 MAS version, and `memory_enabled: false` for all scored runs. Frozen files record their own SHA256.

---

## Phase 0 — Inspect Ethan's v4, then DB audit, integrity, EDA (RUN FIRST, GATES EVERYTHING)

**Step 0a — Inspect the existing MAS (Ethan's v4).** Before any DB work, read Ethan's `agent_v4/` end to end: `graph.py`, `state.py`, every file in `agents/` (manager, data_discovery, data_analyst, synthesizer, visualizer, **debate, eval, validation**), `tools/`, `config.py`, `schema_loader.py`, and the **memory / correction** module. Write a short `agent_v5/V4_NOTES.md` summarizing: the LangGraph topology and node order; what each agent does (be specific about what the **debate**, **eval**, and **validation** agents actually do — read the code, don't guess); how the data_analyst's control variants work; how the debate agent currently generates and compares its two SQL queries; how the memory retrieval + correction layer works; how DB access and schema loading happen; and how Langfuse tracing is wired. This document is the input to Phase 0.5 (architecture proposal) and the foundation every later phase builds on. Flag anything in this spec that contradicts the real code.

**Step 0b — DB audit.** A teammate loaded a heavily expanded Aiven instance. We have NOT verified it. Do not design the golden set until this passes and Till has read the report.

Build `phase0/audit.py` to check against the metadata doc (Till will provide it in `till/`):

- **Completeness:** all 15 base tables + 6 materialized views exist. Row count per table. Seasons 2020-21 → 2024-25 for `ENG-PL` present, no missing season_ids. Flag empty/surprising tables.
- **Referential integrity:** orphan `game_id` in player_match_performance / match_events not in matches; orphan player_id / team_id / season_id across performance tables; count silent drops (loader mixes `DO UPDATE` and `DO NOTHING`).
- **Known landmines:** Everton −8 and Forest −4 in 2023-24 reflected in `tss_points`; `player_market_values.date_unix` is real Unix seconds; team-name aliasing left no duplicate team_ids (Man Utd etc.); **verify the two partitioned tables `player_match_performance` and `match_events` are NOT empty** (metadata doc warns "No child partitions were found in the parsed schema" — if these are empty, event-level and player-match question categories are dead and must be excluded from the golden set).
- **Materialized-view freshness:** spot-check a `vw_team_season_summary` aggregate against summing underlying tables.
- **Light EDA:** null rates per modelling-relevant column; value-range sanity (possession 0–100, odds > 1.0, no negative minutes); duplicate detection on conflict keys.

**Output:** `results/phase0/audit_report.md` (human-readable, feeds the paper's data section) + `results/phase0/audit_results.json`.

**Acceptance:** report states per-table pass/fail with counts and flags every integrity violation. **STOP after this phase and wait for Till to confirm which question categories are viable before starting Phase 2.**

---

## Phase 0.5 — Propose the v5 architecture (DESIGN STEP — Till approves before any building)

Using `V4_NOTES.md`, write `agent_v5/ARCHITECTURE_PROPOSAL.md` proposing the v5 design. This is a **proposal for Till to review and approve — do NOT build v5 until he signs off.** The goal is to keep Ethan's v4's strong core, fix two specific things, and rationalize the parts whose purpose is unclear — without over-engineering.

**Required design decisions to address in the proposal:**

1. **Fold debate into the data analyst (required change).** Currently a separate debate agent writes two SQL queries and, if they match, passes the result to the data analyst. Move this *inside* the data analyst: the data analyst generates **two independent SQL queries**; if they agree, proceed; if they disagree, the analyst **debates itself** (re-generates / reconciles) until it converges on two matching queries, then proceeds. Propose a concrete loop: how convergence is defined (exact result-set match? normalized SQL match? — recommend result-set match, since two different SQL strings can be equally correct), a **max-iteration cap** with a sensible fallback when it never converges (e.g. return best-effort + flag low-confidence), and how this is traced in Langfuse. Remove the standalone debate node if it's fully absorbed.

2. **Investigate and rationalize the eval agent and validation agent (open question).** Till is unsure what these do. From the code, state precisely what each does today, whether their roles overlap, and whether each should be: kept as-is, merged, simplified, or cut. Be opinionated but justify from the code. Watch for a specific risk: **if the eval/validation agent uses an LLM to judge answer correctness at runtime, that must NOT leak into or resemble the offline LLM-as-judge scoring in Phase 5** — keep runtime self-validation and offline scoring clearly separate, or a reviewer will question circularity. Flag this explicitly if relevant.

3. **Keep memory optional, off for eval (required).** Preserve the persistent memory + correction layer as a *toggle*, defaulted **off** for all scored runs (constraint 10). Propose the cleanest flag/config to disable it such that nothing warms mid-run. Don't delete it — it's part of the blueprint described in the paper.

4. **Don't over-engineer.** The deliverable is an eval-ready MAS, not a maximal one. If a v4 component adds complexity without clear value for the experiment, propose simplifying or deferring it. Justify additions; prefer the minimal system that supports the three scored conditions and the DoF sub-experiment.

**Proposal must include:** the proposed v5 node topology (diagram or ordered list), a table of every v4 agent → {keep / modify / merge / cut} with one-line justification each, the self-debate loop design, the memory toggle design, and any open questions for Till.

**Acceptance:** `ARCHITECTURE_PROPOSAL.md` exists and covers all four decisions above. **STOP and wait for Till's approval before building v5.** Once approved, the approved topology supersedes the suggested layout in this spec.

---

## Phase 1 — Shared tool layer + golden-set scaffold

- `tools/run_sql.py`: single read-only entry to Aiven via `DATABASE_URI` (note: `DATABASE_URI`, not `DATABASE_URL`). Reject non-SELECT/WITH; statement timeout; return rows as JSON + row count.
- `tools/schema_context.py`: one canonical schema string injected into ALL prompts (tables, views, key caveats: points deductions, "current"=2025-26 / "last"=2024-25, prefer IDs over names). Every condition gets the identical schema context — no condition gets a richer schema.
- `tools/predict_match_outcome.py`: STUB returning a fixed dummy probability vector `{home_win, draw, away_win}` with the final tool schema/signature locked now so both architectures register the identical tool.
- `golden/schema.py`: `GoldenItem` = `id, question, category, difficulty, gt_type (deterministic_sql | multi_step | prediction), canonical_sql (nullable), ground_truth (nullable), coverage_label (nullable), answer_type (scalar | ranking | table | probability_vector)`.

**Refactor note:** inspect how v4 connects to the DB (likely in `sql_functions.py` / `config.py` / `schema_loader.py`). Route the eval's DB access through `tools/run_sql.py` so there is one read-only code path. Reuse v4's connection + schema logic rather than rewriting it. Do NOT edit v4 itself — `agent_v5` imports from or re-implements based on v4, leaving v4 untouched. If importing across folders is awkward, copy the minimal needed logic into `agent_v5` and note it.

**Acceptance:** `run_sql` returns a correct 2023-24 table with Everton/Forest deductions reflected; non-SELECT statements are rejected.

---

## Phase 2 — Deterministic golden set + canonical-SQL ground truth

Scope to ONLY the categories Phase 0 validated.

- `golden/generate.py`: Till drafts/approves ~45 SQL-answerable questions (AI may draft the natural-language wording; **canonical_sql is hand-authored/approved by Till**). Categories: team/league outcomes (`vw_team_season_summary`), player season aggregates (`vw_player_season_summary`), home/away splits, disciplinary, xG over/underperformance (multi-step), market value/transfers, availability. Span difficulty simple → edge-case.
- `golden/build_ground_truth.py`: execute every `canonical_sql`, store structured result as ground truth, emit `results/golden/appendix_canonical_sql.md` (question → SQL → result) for the paper appendix.

**Ground truth = the result of running canonical_sql. Never an AI prose answer.**

**Acceptance:** every non-prediction item has a runnable `canonical_sql` and stored structured ground truth; appendix generates. **FREEZE** `golden_set.json` and `ground_truth.json` (write SHA256 + timestamp + git commit to manifest). Do not edit after this.

---

## Phase 3 — Purpose-built templates + FROZEN coverage labels

- `templates/library.py`: ~10-12 parameterized SQL templates that look like what a sensible engineer would write (top-N league table, team-season summary, head-to-head, player-season stat leaders, home/away comparison, disciplinary leaders, etc.). **Designed to deliberately cover ~20-25 golden questions and leave ~20-25 uncovered**, aiming for both coverage cells ≥ ~18 questions. Document each template's intent (pre-empt "strawman templates" critique).
- `templates/label_coverage.py`: for every (question, template) pair, run the template with best-effort parameter binding and check whether ANY template reproduces the canonical ground truth. Emit `coverage_label ∈ {in_coverage, out_of_coverage}` per question + a coverage matrix for the appendix.

**Coverage is decided here by template-vs-ground-truth matching — NEVER by what an agent does at runtime.** Add a header to the frozen file stating it was generated before any DoF runs, with the git commit hash.

**Acceptance:** `results/templates/coverage_labels.json` FROZEN (hash+timestamp+commit), roughly balanced split, coverage matrix emitted. Do not edit after this.

---

## Phase 4 — Three DoF variants behind one interface

**Build on the approved v5 architecture (Phase 0.5).** The three control variants (full / semi / no control) likely already exist in Ethan's v4 `data_analyst.py` — adapt those, now including the self-debate loop from the approved proposal. Expose them through one interface in `conditions/sql_agent.py` with a `mode` switch; the ONLY difference between modes is registered tools:
- **controlled:** only `use_template(template_name, params)`. No `run_sql`.
- **semi-controlled:** both `use_template` and `run_sql`. Agent decides per query — routing is entirely the agent's; no heuristics from us.
- **autonomous:** only `run_sql`. No template access.

Identical system prompt across all three except the tool list. Same model, same schema context. The self-debate loop (data analyst generating + reconciling two queries) applies wherever the analyst writes free-form SQL.

`conditions/mas_runner.py`: drives the **approved v5 MAS**, memory disabled (`memory_enabled: false`), verified not to warm mid-run. `conditions/single_llm.py`: (a) single LLM with the same tools (`run_sql` + `predict_match_outcome`) via native function-calling; (b) single LLM with raw data only (inlined text dump + schema, no tools, no DB, no web).

Ensure Langfuse captures per run: tool called, arguments, returned rows, tool-call sequence, and (for the analyst) self-debate iterations. Reuse v4's tracing setup.

**Acceptance:** same question through all three DoF modes yields three traces with expected tool-access differences (controlled never calls run_sql; autonomous never calls use_template).

---

## Phase 5 — Eval harness: repeats, programmatic scoring, taxonomy

- `eval/runner.py`: runs (question × condition × model × repeat), **≥3 repeats**. Temperature fixed; run SQL-generating paths at low temp ~0.3 (not 0) to surface routing variance. Record final answer, tool-call sequence, tokens, latency. Write each raw run to `results/runs/` BEFORE scoring.
- `eval/score.py`: **programmatic first** — scalar = exact/tolerance; ranking = ordered-set; table = row-set with numeric tolerance. LLM-as-judge ONLY for genuine free-text, and the judge must be a **different model family** than the one evaluated (no Claude judging Claude). Score against stored ground truth.
- `eval/judge_validation.py`: on ~15-20 items, compare judge verdicts to Till's; report agreement → `results/scores/judge_validation.json`.
- `eval/failure_taxonomy.py`: for every semi-controlled failure, classify from the trace: (a) chose template when free SQL would've worked, (b) chose wrong template, (c) chose correctly but template result wrong.

**Acceptance:** results dataframe keyed by (question, condition, model, repeat) with score/tokens/latency/tool-sequence; populated semi-controlled failure taxonomy.

---

## Phase 6 — Batch runner + stats + paper tables

- `eval/batch_runner.py`: use Batch APIs for the no-live-loop conditions (raw-data single LLM especially). MAS + tool-using conditions run live. DoF ≈ 45 × 3 variants × 3 models × 3 repeats ≈ 1,215 runs + the MAS-vs-single comparison on top — batch keeps cost sane.
- `eval/stats.py`: mean ± std per cell; **paired** test across architectures (Wilcoxon signed-rank or per-question paired bootstrap — same questions through every condition). Report effect sizes, not just p-values. Break out by category × difficulty and by in/out-of-coverage.
- `eval/tables.py`: regenerate from `results/stats/`:
  1. DoF accuracy by variant × coverage (2×3).
  2. Semi-controlled failure taxonomy.
  3. MAS vs single-LLM-tools vs single-LLM-raw, by category, with tokens + latency.
  4. Judge–human agreement.

**Acceptance:** all four tables regenerate with one command from stored results.

---

## Phase 7 — Prediction slice (LATER, do not block on this)

Build the interface now (Phase 1 stub), run later. When Ethan's models land: swap the stub in `tools/predict_match_outcome.py` for the real model, fill prediction ground truth in `results/runs/prediction/`, run ONLY that slice. Frame as **tool-use fidelity** (did the system retrieve + report the prediction correctly), NOT forecast accuracy — unless proper Brier/calibration scoring against held-out results is added, which is separate. Prediction questions are excluded from the DoF experiment.

---

## Freeze order (load-bearing — violate nothing)

Phase 0 audit reviewed by Till → Phase 2 ground truth FROZEN → Phase 3 coverage labels FROZEN → then Phase 5/6 runs. Never regenerate a frozen artifact after runs begin. If something looks wrong in a frozen file, STOP and ask Till.

## When in doubt

Stop and ask Till rather than guessing — especially before: modifying anything outside `agent_v5/`, installing dependencies, regenerating a frozen file, or changing a tool's interface (which would break condition parity). When this spec and v4's actual code disagree, v4 wins — note the discrepancy and ask.
