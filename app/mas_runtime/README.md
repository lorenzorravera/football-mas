# agent_v4 — Premier League Analytics + Match Prediction

A 9-node [LangGraph](https://github.com/langchain-ai/langgraph) multi-agent system that
answers Premier League questions (text + optional Plotly viz) and forecasts match
outcomes. Part of the LSE group project *P13: LLM Agent for Forecasting Football*.

> See [`../CLAUDE.md`](../CLAUDE.md) for working guidance and [`../HANDOFF.md`](../HANDOFF.md)
> for current status. **This README describes the code as it actually runs** — earlier
> versions of this file described "agent_v3" with ChromaDB, which is no longer accurate.

---

## Architecture

**9-node pipeline** (see `graph.py`):

```
memory_retrieval → manager ┬─ data_discovery → data_analyst → [visualizer] ─┐
                           └─ prediction_agent ───────────────────────────►├─ synthesizer → eval_agent → memory_store → END
                              (conversational / error route straight to synthesizer)
```

The **manager** classifies intent into one of
`conversational | data_request | full_pipeline | prediction_match` and routes:

- `data_request` / `full_pipeline` → data_discovery → data_analyst (→ visualizer if viz requested)
- `prediction_match` → prediction_agent
- `conversational` / error → straight to synthesizer

After synthesis, **eval_agent** checks the response against the DB result (rule-based, no
LLM, no golden-set access) and **memory_store** persists the turn.

### Data-analyst variants (the core research question)

How much freedom to give the SQL-writing agent:

- **full_control** — only predefined SQL functions
- **semi_control** — functions *or* custom SQL (LLM decides)
- **no_control** — always writes custom SQL from scratch

Crossed with **2 models** (`claude` → `anthropic/claude-opus-4-8`, `gpt4o` → `gpt-4o`)
= 6 configurations benchmarked against a golden set.

> ⚠️ **Current limitation:** `FUNCTION_REGISTRY` in `data_analyst.py` is stubbed empty, so
> the function-call branch (all of `full_control`, and `semi_control`'s function path) is
> currently a no-op — only the custom-SQL paths actually execute. Restore the registry
> (wire it to `agent_tools/sql_functions.py`) to genuinely test the full/semi variants.

### Memory (pgvector on Aiven)

`memory/vector_store_pg.py` — PostgreSQL + pgvector, three tables:

| Table | Stores | Consumed by |
|---|---|---|
| `conversation_memory` | completed Q&A turns | synthesizer (continuity) |
| `sql_cache` | successful SQL keyed by query embedding | data_analyst (skip generation on hit) |
| `correction_memory` | failed queries / bad SQL | data_analyst (warn on similar) + eval_agent (writes) |

Cosine thresholds: sql_cache **0.88**, conversation **0.70**, correction **0.75**.
All memory calls are **best-effort** — any failure is swallowed so the pipeline never blocks.

> The local `memory_store/` directory (ChromaDB sqlite files) is **legacy** and unused by
> the pgvector path.

A fourth table, **`trajectory_log`** (`memory/trajectory_log.py`), records one row per
turn — `arm = model|variant|intent`, tokens, latency, `eval_score`, thumbs — written from
`run_agent()` *after* the graph stream (never threaded through `AgentState`). It is the
substrate for the **router bandit** (see Evaluation) and a future preference model.

### Prediction agent (multi-task)

`agents/prediction_agent.py` wraps the separate **`prediction_agent`** package
(repo root). The prediction node is a **dispatcher** over a task registry, not just match
outcome:

- **Match outcome** — builds features for an unplayed fixture with the *exact* training
  feature pipeline (train/inference parity by construction), runs the no-odds model
  (`match_outcome_v1.pkl`); a parity guard raises rather than feeding NaNs.
- **Team-season suite (Q1–Q4)** — `season_class`, `position_movement`, `turnaround`,
  `home_away_dependency`; single-team or league-wide ("who's most likely relegated?").
- **Player / cross-league / event / index tasks (Q5–Q12) + explanation (Q14)** — trained
  sklearn models, empirical lookup tables, and deterministic indices; see the package and
  `HANDOFF.md §0aa` for what each task is and how its numbers are produced.

The manager emits a `prediction_type`; the dispatcher routes to the right task. Models are
**honestly calibrated, illustrative** (small, mostly single-league samples) — the value is
breadth + framework, not headline accuracy.

---

## File structure

```
agent_v4/
├── app.py                 # Chainlit UI (model/variant settings, viz toggle, feedback)
├── graph.py               # LangGraph topology + run_agent() + CLI smoke test
├── state.py               # AgentState TypedDict (shared state)
├── config.py              # LiteLLM routing + call_llm()
├── schema_loader.py       # live DB schema (shim → ../../till/agent_v5)
├── agents/
│   ├── manager.py             # intent classification + PL validation + params
│   ├── data_discovery.py      # relevant tables/columns
│   ├── data_analyst.py        # 3 SQL variants + validation/retry loop
│   ├── visualizer.py          # Plotly generation
│   ├── prediction_agent.py    # match-outcome forecast
│   ├── synthesizer.py         # final NL response
│   └── eval_agent.py          # rule-based consistency check
├── memory/
│   ├── vector_store_pg.py     # pgvector store (live backend)
│   ├── memory_agent.py        # memory_retrieval / memory_store nodes
│   ├── trajectory_log.py      # per-turn arm/reward log (bandit substrate)
│   └── migrations/            # idempotent additive schema migrations
├── agent_tools/
│   ├── sql_functions.py       # predefined SQL functions
│   ├── viz_functions.py       # chart helpers
│   └── skills.md              # SQL reference for the no_control analyst
├── eval/                      # current eval harnesses (see Evaluation below)
│   ├── session_runner.py      # multi-step within-session memory experiment (4 arms)
│   ├── session_report.py      # paired deltas + bootstrap CI + Wilcoxon
│   ├── gen_sessions.py        # generates + DB-validates the session suite
│   ├── router_bandit.py       # Phase E: Thompson-Sampling contextual bandit
│   ├── bandit_eval.py         # bandit regret simulation + live posterior dump
│   └── tests/                 # DB/logic tests (run_all_tests.sh runs all)
├── run_all_tests.sh           # one-shot verification suite (no LLM cost)
└── eval_*.py / phase*.py      # legacy/pre-session diagnostic harnesses
```

---

## External dependencies

agent_v4 is **not self-contained**. It imports from siblings one level up:

- `../../till/agent_v5` — schema context (`schema_loader.py`)
- `../../till/db/connection.py` — `read_sql()` (`data_analyst.py`)
- `../../till/eval/golden_set/` — golden test cases (eval scripts)
- the `prediction_agent` package (repo root) — `pip install -e prediction_agent/`

---

## Setup & run

```bash
pip install langgraph chainlit litellm psycopg2-binary pandas plotly chromadb sentence-transformers python-dotenv
```

Create `.env` in this folder:

```bash
DATABASE_URI="postgres://..."        # Aiven PL warehouse + pgvector memory
STATS_DATABASE_URI="postgres://..."  # stats DB for prediction features (falls back to DATABASE_URI)
ANTHROPIC_API_KEY="sk-ant-..."
OPENAI_API_KEY="sk-proj-..."         # only needed for the gpt4o variant; config validates its presence
```

```bash
# CLI smoke test (5 sample queries incl. a prediction)
python graph.py

# Chat UI
chainlit run app.py --host 0.0.0.0 --port 8000     # → http://localhost:8000

# Single-node tests
python agents/manager.py
python agents/prediction_agent.py

# Verification suite (no LLM cost) — DB/logic tests incl. the bandit
./run_all_tests.sh            # or -q for quiet
```

---

## Evaluation

Current harnesses live under `eval/`.

### Session memory experiment (the headline)

Multi-step *within-session* carry-over across 4 arms (`mas_memory`, `mas_no_memory`,
single-LLM stateless, single-LLM full-history), over correction / cache / conversation
session families. See [`HANDOFF.md §4`](../HANDOFF.md) and
`eval/results/SESSION_RESULTS.md` for results.

```bash
python eval/gen_sessions.py                 # (re)generate + DB-validate the session suite
python eval/session_runner.py               # run all sessions, 4 arms (LLM cost)
python eval/session_report.py               # paired deltas + bootstrap CI + Wilcoxon
```

### Router bandit (Phase E)

A Thompson-Sampling **contextual** bandit over the `(model, variant)` action space,
conditioned on `intent`, learning from `trajectory_log` rewards (`eval_score`, optionally
thumbs/cost/latency). Off by default; pass a `RouterBandit` to `run_agent(..., bandit=...)`
to let it pick the arm and learn online.

```bash
python eval/bandit_eval.py          # regret simulation (golden-set reward) + live posteriors
python eval/bandit_eval.py --sim    # simulation only (no DB)
python eval/bandit_eval.py --live   # live trajectory_log posterior dump only
```

> **Data caveat:** the live `trajectory_log` is currently single-arm (the system has only
> run in one config), so the simulation grounds the mechanism in the golden-set accuracies
> while real multi-arm exploration data accrues. Turning the bandit on in `run_agent` is
> what populates the other arms.

### Legacy diagnostics

`eval_runner.py` (golden set), `eval_memory_ablation.py` (memory on/off — found *zero*
difference on independent queries, which is why the session experiment exists),
`eval_cache_sweep.py`, `phase*.py`. Pre-session; kept for reference.

---

## Notes

- Memory and prediction failures are non-fatal by design — keep it that way.
- `EVAL_MODE` env var changes memory behavior for experiments: `golden` bypasses sql_cache
  read/write; `cache_experiment` isolates sql_cache as the only active memory mechanism.
- Each agent file has a `__main__` self-test for isolated testing.
- `Dockerfile` still references old `agent_v3` paths and a missing `requirements.txt` —
  fix before any container deploy.
