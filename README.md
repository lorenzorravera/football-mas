# Football Analytics with Multi-Agent LLMs

**A conversational football analytics platform built with LangGraph, PostgreSQL and Chainlit, with a controlled comparison of multi-agent orchestration against single-LLM baselines.**

MSc Data Science capstone project at the London School of Economics, developed in a three-person team in collaboration with Sky. The system combines historical football data, natural-language SQL analytics, match prediction and evidence-based response generation. A separate evaluation harness investigates whether decomposing a question across specialised agents improves quality enough to justify additional inference cost.

## At a glance

| Component | What it does |
| --- | --- |
| Football data | Integrates match, player, team, event and transfer/injury information in PostgreSQL |
| Analytics | Discovers database context, produces SQL and summarises grounded results |
| Prediction | Dispatches forecasting questions to trained prediction tasks |
| Application | Runs a LangGraph workflow through a Chainlit chat interface |
| Evaluation | Compares a MAS with single-LLM alternatives using common datasets and tools |

## Architecture

The main application has the following routing structure (see [`graph.py`](app/mas_runtime/graph.py)):

```text
                          ┌─ data discovery → SQL analyst ─[visualizer]─┐
User → memory → manager ───┤                                            ├→ synthesizer → evaluation → memory store
                          ├─ prediction agent ──────────────────────────┤
                          └─ conversational response ───────────────────┘
```

The manager selects between analytical, visualisation, prediction and conversational requests. The data analyst supports different levels of freedom in how SQL is produced. The graph also contains memory retrieval, synthesis and answer-consistency checks. The full workflow depends on model credentials and an accessible PostgreSQL database.

> **Important:** The application under `app/mas_runtime/` and the controlled experiment under `evaluation/mas_vs_single_llm/` are *separate code paths*. The latter has its own SQL tool boundary and scoring logic; its metrics should not be interpreted as measurements of every optional feature in the live app.

## Data and modelling

The project worked with football information from WhoScored, Understat, FBref, Transfermarkt and Football-Data, integrating source-specific identifiers into a relational schema. See [`database_metadata.md`](docs/database/database_metadata.md) and [`full_schema.yaml`](docs/database/full_schema.yaml) for database context. Source coverage varies by competition and season, and the complete hosted database is **not included** here.

The standalone [`prediction/`](prediction/) package contains feature engineering, model training, task dispatch, inference scripts and backtest outputs. Its included `.pkl` models are historical research artifacts, not assurances of current predictive performance.

## Research: does a multi-agent architecture help?

The experimental harness implements multiple orchestration conditions, including a multi-agent design, a single LLM with shared tools and a single LLM given raw data context. The benchmark includes deterministic analytical and prediction-oriented football questions, with scored artifacts preserved under [`evaluation/mas_vs_single_llm/results/`](evaluation/mas_vs_single_llm/results/).

For the **deterministic evaluation**, the reported comparison between the multi-agent system and a single LLM with equivalent tools is:

| Measure | Multi-agent | Single LLM + tools |
| --- | ---: | ---: |
| Answer accuracy | 87% | 87% |
| Tokens | 32,324 | 22,150 |
| Latency | 16.7 s | 8.1 s |

**Takeaway:** On these analytical questions, decomposing execution into multiple agents did not improve accuracy and imposed a substantial latency and token overhead. This does not establish that multi-agent systems are never useful; rather, their extra complexity should be evaluated against capable, tool-using single-agent baselines.

The code and stored scores for the larger experimental matrix are available in the benchmark directory. The table above is a selected result, **not** a claim that every experiment or prediction benchmark produced the same outcome.

## Repository layout

```text
app/mas_runtime/                    LangGraph application, Chainlit interface and runtime tests
prediction/                         Prediction package, training, inference and backtests
evaluation/mas_vs_single_llm/       Controlled MAS / single-LLM benchmarking framework
data_pipeline/ingestion/            Database ingestion utilities
data/premier_league_extracts/       Small development extracts and source schema notes
docs/database/                     Database schema, metadata and SQL snapshot
docs/reports/project_report.pdf     Capstone report
docs/publication/                  Research manuscript and submission summary
```

The runtime and benchmark directories intentionally retain their import boundaries because the scripts use local imports; they have **not** been cosmetically relocated into a `src/` package without the accompanying import migration.

## Getting started

**Requirements:** Python 3.13 (as specified in the root `pyproject.toml`), [`uv`](https://docs.astral.sh/uv/), model-provider credentials and a PostgreSQL database containing the expected schema.

```bash
git clone https://github.com/lorenzorravera/football-mas.git
cd football-mas
uv sync
```

The repo includes [`app/mas_runtime/.chainlit/config.toml`](app/mas_runtime/.chainlit/config.toml), and the UI entry point is [`app/mas_runtime/app.py`](app/mas_runtime/app.py). The following illustrates the app entry point **after configuring** the required environment variables and database:

```bash
cd app/mas_runtime
uv run chainlit run app.py
```

The root dependency configuration references the local prediction package. The `uv.lock` originated with the research project and may need regeneration after changing the local package source path:

```bash
uv lock
uv sync
```

Do not expect the full service to run from the repository alone: some services, database tables and credentials are private and the included datasets are only limited development extracts. Review [`config.py`](app/mas_runtime/config.py) and the relevant database scripts before deployment. Never commit your `.env` file.

### Evaluation and results

The benchmarking implementation is under [`evaluation/mas_vs_single_llm/`](evaluation/mas_vs_single_llm/). See the source entry points [`eval/runner.py`](evaluation/mas_vs_single_llm/eval/runner.py) and [`eval/score.py`](evaluation/mas_vs_single_llm/eval/score.py), the [`golden/`](evaluation/mas_vs_single_llm/golden/) definitions, and the tables in [`results/tables/`](evaluation/mas_vs_single_llm/results/tables/).

The scored results and selected aggregated statistics are retained. Hundreds of per-question execution traces have been omitted from this portfolio-ready copy; they are not required to read the summary tables or examine the experiment implementation.

## Limitations

- Integration depends on external, heterogeneous football feeds and a separately hosted database.
- Some SQL-function routing variants in the app reference a function registry that was documented as incomplete; they should not be presented as fully operational without checking and repairing the wiring.
- The benchmark uses a bounded football question set, so findings should not be extrapolated to arbitrary agent tasks.
- Prediction artifacts and historical backtests are research-stage results, not real-time betting or forecasting services.
- The application and benchmark use related but distinct system implementations.

## Research artifacts

The full academic report is available at [`docs/reports/project_report.pdf`](docs/reports/project_report.pdf). Manuscript materials are retained under [`docs/publication/`](docs/publication/).
