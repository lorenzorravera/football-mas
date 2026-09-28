# Coverage matrix (CANDIDATE — generated before any DoF runs)

In-coverage: **28** · Out-of-coverage: **18** · Total: 46

Coverage decided by template-vs-ground-truth matching (NOT agent runtime). A question is in-coverage iff some template's output reproduces the frozen ground truth. Computed-column answers (e.g. home−away gap, goals−xG) and league-wide aggregates with no entity are out-of-coverage by design (no template reproduces them).

## Template library (intent — these are realistic, not strawmen)

| template | intent |
|---|---|
| `league_table` | Full final league table for a season (rank, record, goals, points). |
| `team_season_summary` | One team's season summary incl. home/away points & goals, possession. |
| `home_away_table` | Teams ranked by a home/away split metric for a season. |
| `player_season_leaders` | Top players by a season stat (goals, assists, minutes, cards, shots). |
| `player_team_leaders` | Top players at a specific club by a season stat. |
| `team_stat_leaders` | Teams ranked by a team-season stat (cards, goals, shots, possession). |
| `head_to_head` | All matches between two teams in a season. |
| `match_results` | Matches in a season ordered by home win margin (biggest wins). |
| `market_value_leaders` | Players ranked by latest market value. |
| `market_value_team_leaders` | Players at a club ranked by latest market value. |
| `player_match_leaders` | Top single-match player performances in a season (e.g. most goals in a game). |
| `transfer_leaders` | Largest incoming transfer fees to Premier League clubs (optionally per season). |

## Per-question labels

_Note: 'matched templates' is the value-containment superset; for some questions a template appears incidentally because the answer string/number occurs in its output. The in/out label is the frozen artifact._

| id | category | diff | answer | label | matched templates |
|---|---|---|---|---|---|
| Q01 | team_league_outcomes | simple | scalar | ✅ in | league_table, home_away_table, team_stat_leaders, match_results, transfer_leaders |
| Q02 | team_league_outcomes | simple | scalar | ✅ in | league_table, team_season_summary |
| Q03 | team_league_outcomes | medium | ranking | ✅ in | league_table |
| Q04 | team_league_outcomes | medium | table | ✅ in | league_table |
| Q05 | team_league_outcomes | medium | scalar | ✅ in | league_table, home_away_table, team_stat_leaders, match_results, transfer_leaders |
| Q06 | team_league_outcomes | edge_case | table | — out | — |
| Q07 | team_league_outcomes | hard | table | — out | — |
| Q08 | team_league_outcomes | simple | table | ✅ in | league_table |
| Q09 | player_season_aggregates | simple | scalar | ✅ in | player_season_leaders |
| Q10 | player_season_aggregates | medium | ranking | ✅ in | player_season_leaders |
| Q11 | player_season_aggregates | medium | scalar | ✅ in | player_season_leaders |
| Q12 | player_season_aggregates | edge_case | scalar | ✅ in | player_season_leaders |
| Q13 | player_season_aggregates | medium | scalar | ✅ in | player_season_leaders |
| Q14 | player_season_aggregates | medium | scalar | ✅ in | player_season_leaders, player_team_leaders |
| Q15 | player_season_aggregates | medium | table | ✅ in | player_season_leaders |
| Q16 | home_away_splits | medium | scalar | ✅ in | home_away_table |
| Q17 | home_away_splits | medium | scalar | ✅ in | home_away_table |
| Q18 | home_away_splits | hard | scalar | — out | — |
| Q19 | home_away_splits | simple | scalar | ✅ in | team_season_summary, home_away_table |
| Q20 | home_away_splits | medium | scalar | ✅ in | home_away_table |
| Q21 | disciplinary | medium | scalar | ✅ in | team_stat_leaders |
| Q22 | disciplinary | medium | scalar | ✅ in | player_season_leaders |
| Q23 | disciplinary | medium | scalar | ✅ in | team_stat_leaders |
| Q24 | disciplinary | medium | scalar | — out | — |
| Q25 | disciplinary | edge_case | scalar | — out | — |
| Q26 | xg_performance | hard | scalar | — out | — |
| Q27 | xg_performance | hard | scalar | — out | — |
| Q28 | xg_performance | medium | table | — out | — |
| Q29 | xg_performance | hard | scalar | — out | — |
| Q30 | xg_performance | hard | scalar | — out | — |
| Q31 | market_transfers | medium | scalar | ✅ in | market_value_leaders |
| Q32 | market_transfers | hard | table | ✅ in | transfer_leaders |
| Q33 | market_transfers | medium | scalar | ✅ in | transfer_leaders |
| Q34 | market_transfers | hard | scalar | — out | — |
| Q35 | market_transfers | medium | table | ✅ in | market_value_leaders, market_value_team_leaders |
| Q36 | availability | medium | scalar | — out | — |
| Q37 | availability | hard | scalar | — out | — |
| Q38 | availability | hard | scalar | — out | — |
| Q39 | availability | medium | scalar | — out | — |
| Q40 | event_player_match | hard | scalar | ✅ in | player_season_leaders |
| Q41 | event_player_match | medium | table | ✅ in | player_match_leaders |
| Q42 | event_player_match | hard | scalar | — out | — |
| Q43 | event_player_match | medium | scalar | — out | — |
| Q44 | event_player_match | medium | table | ✅ in | match_results |
| Q45 | edge_case | edge_case | scalar | ✅ in | team_season_summary, player_team_leaders |
| Q46 | edge_case | edge_case | scalar | — out | — |