# Table 3 — MAS vs single-LLM (Claude; MAS analyst_mode = autonomous)

| condition | overall | in-cov | out-of-cov | avg tokens | avg latency |
|---|---|---|---|---|---|
| MAS (autonomous) | 41/46 (89%) | 24/28 (86%) | 17/18 (94%) | 30,635 | 17.8s |
| single-LLM + tools | 38/46 (83%) | 23/28 (82%) | 15/18 (83%) | 24,740 | 10.5s |
| single-LLM + raw data | 16/46 (35%) | 13/28 (46%) | 3/18 (17%) | 229,749 | 4.5s |

### By category

| category | MAS (autonomous) | single-LLM + tools | single-LLM + raw data |
|---|---|---|---|
| availability | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) |
| disciplinary | 4/5 (80%) | 5/5 (100%) | 3/5 (60%) |
| edge_case | 2/2 (100%) | 1/2 (50%) | 1/2 (50%) |
| event_player_match | 3/5 (60%) | 4/5 (80%) | 0/5 (0%) |
| home_away_splits | 5/5 (100%) | 4/5 (80%) | 4/5 (80%) |
| market_transfers | 4/5 (80%) | 1/5 (20%) | 0/5 (0%) |
| player_season_aggregates | 6/7 (86%) | 7/7 (100%) | 1/7 (14%) |
| team_league_outcomes | 8/8 (100%) | 8/8 (100%) | 7/8 (88%) |
| xg_performance | 5/5 (100%) | 4/5 (80%) | 0/5 (0%) |

_Tokens: single-LLM from local capture; MAS recovered from Langfuse. raw-data uses ~9x the tokens (~230k/run — the inlined player_season table dominates) and is both costly and unstable across runs; it also scores 0% on availability/market/transfers (those tables aren't inlined). Numbers are single-repeat (n=46), so treat as directional._
