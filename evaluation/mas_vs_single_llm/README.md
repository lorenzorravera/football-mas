# agent_v5 — MAS-vs-Single-LLM eval harness (MLSA26)

Eval-only harness around the Premier League MAS. **No Modal / Chainlit / UI** — this folder only
produces the experiment results and tables for the paper. Basis for the MAS is `Ethan/agent_v4/`
(vendored in here; `Ethan/` itself is read-only). Full spec: `Claude_specs.md`.

## Experiment (9 scored cells + DoF sub-experiment)
{Claude, GPT, Gemini} × {MAS (memory OFF), single-LLM + same tools, single-LLM + raw data},
plus controlled / semi-controlled / autonomous SQL analysed by template **coverage**.

## Status (2026-06-03)
- ✅ Phase 0 — `V4_NOTES.md`, DB audit (`results/phase0/audit_report.md`, all PASS).
- ✅ Phase 0.5 — `ARCHITECTURE_PROPOSAL.md` (approved by Till: eval_agent cut from scored MAS;
  data layer rebuilt for the new schema; self-debate loop; ENG-PL 2020-21…2024-25 scope).
- ✅ Phase 1 — shared tool layer + golden scaffold (this commit).
- ⏭️ Phase 2 — golden set (NEEDS TILL: drafts/approves ~45 questions; hand-authors canonical_sql). FREEZE.

## Layout
```
Claude_specs.md, football_prediction_database_metadata.md   # inputs (from Till)
V4_NOTES.md, ARCHITECTURE_PROPOSAL.md                        # Phase 0a / 0.5
.env                                  # DATABASE_URI (GITIGNORED — never commit)
phase0/audit.py                       # read-only DB audit
tools/
  run_sql.py            # THE single read-only DB entry (SELECT/WITH only, timeout, JSON out)
  schema_context.py     # one canonical schema string for ALL prompts (+ schema_snapshot.json)
  predict_match_outcome.py  # STUB prediction tool — signature LOCKED
golden/schema.py        # GoldenItem data model
results/phase0/         # audit_report.md, audit_results.json
```

## How to run (from this directory, repo venv)
```bash
cd till/agent_v5
../../.venv/bin/python phase0/audit.py                 # Phase 0 audit -> results/phase0/
../../.venv/bin/python -m tools.run_sql                # acceptance: standings + read-only guard
../../.venv/bin/python -m tools.schema_context         # (re)build schema_snapshot.json + preview
../../.venv/bin/python -m tools.predict_match_outcome  # stub sanity
../../.venv/bin/python -m golden.schema                # GoldenItem sanity
```

## Hard rules
- One DB code path: everything goes through `tools/run_sql.py` (read-only).
- Identical tool registration across conditions — the ONLY thing that may differ between
  conditions is orchestration + which tools are registered.
- Memory OFF for all scored runs (toggle preserved, defaulted off).
- Never edit a frozen artifact (golden set, ground truth, coverage labels) after it's committed.
- v4's SQL targets an OLD schema — the data layer is rebuilt here for the live schema (see `V4_NOTES.md` §7).
