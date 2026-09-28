# Phase 0 — Database Audit Report (agent_v5)

- **Generated (UTC):** 2026-06-03T11:22:53+00:00
- **Database:** `capstone-2-pl-agent.h.aivencloud.com:14390` (PostgreSQL 17.10)
- **Access:** read-only, statement timeout 60s
- **Checked against:** `football_prediction_database_metadata.md`

## Section pass/fail summary

| Section | Result |
|---|---|
| A. Completeness | ✅ PASS |
| B. Referential integrity | ✅ PASS |
| C. Known landmines | ✅ PASS |
| D. Materialized-view freshness | ✅ PASS |
| E. Light EDA | ✅ PASS |

## A. Completeness

- Logical base tables: **17** (+ 12 partition children)
- Missing expected tables: `none`
- Unexpected extra tables: `none`
- Missing materialized views: `none`
- Empty logical tables: `['computed_metrics']`
- Empty partition children: `none`
- Seasons present (ENG-PL): `['2020-2021', '2021-2022', '2022-2023', '2023-2024', '2024-2025']`
- Missing seasons: `none`

### Row counts — logical base tables

| Table | Rows |
|---|---:|
| `competitions` | 1 |
| `computed_metrics` | 0 |
| `match_events` | 2,969,929 |
| `matches` | 1,900 |
| `player_injury_spells` | 3,776 |
| `player_market_values` | 25,404 |
| `player_match_performance` | 53,903 |
| `player_season_splits` | 35,155 |
| `player_season_stats` | 2,800 |
| `player_transfers` | 10,327 |
| `players` | 1,265 |
| `seasons` | 5 |
| `team_season_home_away_standings` | 100 |
| `team_season_standings` | 100 |
| `team_season_stats_against` | 100 |
| `team_season_stats_for` | 100 |
| `teams` | 27 |

### Row counts — partition children

| Child partition | Rows |
|---|---:|
| `match_events_eng_pl` | 2,969,929 |
| `match_events_eng_pl_2020_2021` | 606,814 |
| `match_events_eng_pl_2021_2022` | 589,102 |
| `match_events_eng_pl_2022_2023` | 590,145 |
| `match_events_eng_pl_2023_2024` | 604,425 |
| `match_events_eng_pl_2024_2025` | 579,443 |
| `player_match_performance_eng_pl` | 53,903 |
| `player_match_performance_eng_pl_2020_2021` | 10,256 |
| `player_match_performance_eng_pl_2021_2022` | 10,259 |
| `player_match_performance_eng_pl_2022_2023` | 11,082 |
| `player_match_performance_eng_pl_2023_2024` | 10,973 |
| `player_match_performance_eng_pl_2024_2025` | 11,333 |

### Row counts — materialized views

| View | Rows |
|---|---:|
| `vw_match_summary` | 1,900 |
| `vw_player_availability` | 3,776 |
| `vw_player_match_summary` | 53,903 |
| `vw_player_season_summary` | 2,800 |
| `vw_player_shooting_profile` | 48,898 |
| `vw_team_season_summary` | 100 |

## B. Referential integrity

All counts should be **0** (zero orphaned references).

| Check | Orphans |
|---|---:|
| `orphan_pmp_game_id` | 0 |
| `orphan_match_events_game_id` | 0 |
| `orphan_player_season_stats_player_id` | 0 |
| `orphan_player_match_performance_player_id` | 0 |
| `orphan_player_market_values_player_id` | 0 |
| `orphan_player_transfers_player_id` | 0 |
| `orphan_player_injury_spells_player_id` | 0 |
| `orphan_team_season_standings_team_id` | 0 |
| `orphan_team_season_home_away_standings_team_id` | 0 |
| `orphan_team_season_stats_for_team_id` | 0 |
| `orphan_team_season_stats_against_team_id` | 0 |
| `orphan_player_season_stats_team_id` | 0 |
| `orphan_matches_home_team_id` | 0 |
| `orphan_matches_away_team_id` | 0 |
| `orphan_matches_season_id` | 0 |
| `orphan_team_season_standings_season_id` | 0 |
| `orphan_player_season_stats_season_id` | 0 |
| `orphan_pmp_season_string` | 0 |
| `orphan_match_events_season_string` | 0 |

## C. Known landmines

- **Everton −8 (2023-24) reflected in `tss_points`:** ✅ PASS
- **Nottingham Forest −4 (2023-24) reflected in `tss_points`:** ✅ PASS

Implied point adjustments found (where `tss_points ≠ 3·W + D`):

| Season | Team | Implied deduction |
|---|---|---:|
| 2023-2024 | Everton | 8 |
| 2023-2024 | Nottingham Forest | 4 |

- **`player_market_values.date_unix` looks like seconds:** ✅ PASS (min=1096761600, max=1757548800)
- **No duplicate team names:** ✅ PASS (team_count=27, dups=none)
- **Partitioned tables non-empty:** ✅ PASS (match_events=2,969,929, player_match_performance=53,903) → event-level & player-match question categories are **VIABLE**.
- **Season string format:** uses hyphen (`YYYY-YYYY`) = True; sample `['2020-2021', '2021-2022', '2022-2023', '2023-2024', '2024-2025']`. Latest season = `2024-2025`.
- Team alias targets present: `['Brighton', 'Manchester City', 'Manchester United', 'Newcastle United', 'Nottingham Forest', 'Tottenham Hotspur', 'West Ham United', 'Wolves']`

## D. Materialized-view freshness

| View | View rows | Base rows |
|---|---:|---:|
| `vw_team_season_summary` vs `team_season_standings` | 100 | 100 |
| `vw_match_summary` vs `matches` | 1,900 | 1,900 |
| `vw_player_season_summary` vs `player_season_stats` | 2,800 | 2,800 |

- `vwtss_points` vs `tss_points` mismatches: **0** 

## E. Light EDA

### Null rates (fraction NULL) — modelling-relevant columns

| Table | Column | Null rate |
|---|---|---:|
| `matches` | `home_score` | 0.0 |
| `matches` | `away_score` | 0.0 |
| `matches` | `ft_result` | 0.0 |
| `matches` | `referee` | 0.0026 |
| `matches` | `attendance_m` | 0.1863 |
| `matches` | `avg_home_odds` | 0.0 |
| `matches` | `home_shots` | 0.0 |
| `matches` | `home_formation` | 0.0042 |
| `player_season_stats` | `minutes_pss` | 0.0 |
| `player_season_stats` | `goals_pss` | 0.0 |
| `player_season_stats` | `xg_pss` | 0.0664 |
| `player_season_stats` | `age` | 0.0004 |
| `team_season_stats_for` | `tssf_possession_percentage` | 0.0 |
| `team_season_stats_for` | `tssf_goals` | 0.0 |
| `team_season_stats_for` | `tssf_shots` | 0.0 |
| `player_market_values` | `market_value` | 0.0 |
| `player_match_performance` | `minutes_played` | 0.0017 |
| `player_match_performance` | `match_goals` | 0.0 |
| `player_match_performance` | `xg_pmp` | 0.0 |
| `player_match_performance` | `position` | 0.0 |

### Value-range violations (should all be 0)

| Check | Count |
|---|---:|
| `possession_for_out_of_range` | 0 |
| `odds_le_1` | 0 |
| `negative_minutes_pss` | 0 |
| `negative_minutes_pmp` | 0 |
| `negative_scores` | 0 |

### Duplicate conflict keys (should all be 0)

| Key | Duplicate groups |
|---|---:|
| `matches_game_id` | 0 |
| `player_season_stats_key` | 0 |
| `team_season_standings_key` | 0 |
| `player_market_values_key` | 0 |

## Viability note for the golden set

This section is advisory; **Till confirms viable categories before Phase 2.**

- Team/league outcomes, player season aggregates, home/away splits, disciplinary, xG over/under, market value/transfers, availability: backed by populated tables/views → candidate categories.
- Event-level & player-match: partitions are populated → **viable** (contrary to the metadata doc's stale 'no child partitions' warning).
- "Current/this season" (2025-2026) has **no data** — latest is `2024-2025`. Golden-set season wording must avoid relative "current season" or pin it to 2024-2025.