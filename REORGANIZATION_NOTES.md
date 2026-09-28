# Repository Reorganization Notes

## Old → new top-level mapping

| Original location | New location | Meaning |
|---|---|---|
| `Ethan/agent_v4/` | `app/mas_runtime/` | End-to-end MAS runtime |
| `till/agent_v5/` | `evaluation/mas_vs_single_llm/` | Final evaluation harness |
| `prediction_agent/` | `prediction/` | Prediction package |
| `Lorenzo/v1/` | `archive/prototypes/agent_prototype_v1/` | Early prototype |
| `Lorenzo/v2/` | `archive/prototypes/agent_prototype_v2/` | Later pre-v4 prototype |
| `Ethan/data_prep/` | `data_pipeline/ingestion/` | Early ingestion utilities |
| `Ethan/data/` | `data/legacy_premier_league_extracts/` | Legacy local data extracts |
| `Ethan/WebScraper.ipynb` | `notebooks/exploration/web_scraper.ipynb` | Scraping exploration |
| `Ethan/adk_agents.ipynb` | `notebooks/exploration/agent_experiments.ipynb` | Early agent experiments |
| root reports / `Paper/` | `docs/` | Reports, presentation, publication material |

## What was deliberately removed

- Contributor-name folders at the top level.
- One broken legacy symlink (`Ethan/db -> ../till/db`) that did not resolve in the downloaded ZIP.
- A duplicate separately attached copy of the final report, if byte-identical to the report already in the repository.

## What was deliberately not rewritten

The contents of source code, experiment outputs and historical documentation were not semantically rewritten. Some old comments or run commands can therefore refer to historical paths. This avoids accidentally changing experimental provenance or code behaviour while still giving the repository a clean functional structure.
