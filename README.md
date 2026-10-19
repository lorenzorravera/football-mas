# Football Analytics Multi-Agent System — Capstone Repository

This is a reorganized snapshot of the LSE × Sky capstone repository.

## Repository map

```text
football_analytics_mas_capstone/
├── app/
│   └── mas_runtime/              # Full LangGraph runtime: agents, memory, Chainlit UI, eval utilities
├── evaluation/
│   └── mas_vs_single_llm/        # Final MAS-vs-single-LLM evaluation harness and golden sets
├── prediction/                   # Prediction package, trained artefacts, backtests and task registry
├── data_pipeline/
│   └── ingestion/                # Early/source-specific ingestion utilities
├── data/
│   └── legacy_premier_league_extracts/
├── notebooks/
│   └── exploration/              # Early scraping / agent experiments
├── docs/
│   ├── reports/                  # Draft + final group reports
│   ├── presentation/             # Final presentation
│   ├── publication/              # Paper/submission material
│   ├── architecture/             # Architecture notes/specs
│   ├── database/                 # Schema and DB metadata
│   └── reference/                # Study/reference summary supplied separately
└── archive/
    ├── prototypes/               # Earlier v1/v2 agent prototypes
    └── early_apps/               # Obsolete UI prototypes
```

## What is current vs archival?

- `app/mas_runtime/` contains the richest end-to-end runtime implementation, including LangGraph orchestration, memory, SQL analysis, synthesis, evaluation and Chainlit integration.
- `evaluation/mas_vs_single_llm/` contains the later paper/evaluation harness used for controlled comparisons, golden-set construction and experiment outputs.
- `prediction/` is the standalone prediction package integrated into the agent system.
- `archive/` is intentionally retained for provenance but should not be treated as the current architecture.

## Important note on historical path references

Some source comments and old experiment instructions still mention the original contributor-based paths. They are preserved inside legacy code for provenance. The top-level folder structure no longer uses contributor names. If running an old script, adjust any hard-coded relative path to the new layout.

## Attached reference files

Files that were shared separately during project review have been added under generic names in `docs/`. The separately attached final report was byte-identical to docs/reports/final_group_report.pdf and was deduplicated.

## Recommended reading order

1. `docs/reports/final_group_report.pdf`
2. `docs/reference/detailed_project_summary.pdf`
3. `docs/database/full_schema.yaml`
4. `app/mas_runtime/README.md`
5. `evaluation/mas_vs_single_llm/README.md`
6. `prediction/AGENT_INTEGRATION.md`

## Environment

The repository does **not** include `.env` files or API/database credentials. Supply secrets through environment variables when running the code.
