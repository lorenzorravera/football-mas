# Football Prediction Database Metadata & Data Dictionary

This document explains the database structure, loader assumptions, relationships and variable-level meanings for the football performance prediction project. It is written for modelling teammates who need to understand what data exists before building prediction agents and evaluation pipelines.

## Executive summary

The current database is a multi-layer football analytics warehouse. It starts with stable reference tables for competitions, seasons, teams and players. It then adds match-level data, team-season data, player-season data, player-match data, event-level data, market values, transfers, injuries, and flexible computed model outputs. Materialized views combine these raw tables into modelling-ready datasets.

The current seeded competition is Premier League (`ENG-PL`) with seasons from 2020-2021 through 2024-2025, but the schema is designed to extend to additional leagues using `competitions`, `seasons`, `league_code` and partitioned performance/event tables.

## Data layers

1. **Reference layer**: `competitions`, `seasons`, `players`, `teams`. These provide stable IDs and canonical labels.
2. **Match layer**: `matches`, enriched by `vw_match_summary`. This covers fixtures, outcomes, formations, match stats, attendance, referee and betting odds.
3. **Team-season layer**: `team_season_standings`, `team_season_home_away_standings`, `team_season_stats_for`, `team_season_stats_against`, joined through `vw_team_season_summary`. This supports season outcome, relegation, title/top-four, overperformance, home/away dependency and team-context models.
4. **Player performance layer**: `player_season_stats`, `player_season_splits`, `player_match_performance`, and related player views. This supports player impact, decline, breakout, role/context and match-level contribution models.
5. **Event layer**: `match_events`. This is the most granular layer and supports sequence modelling, shot/pass/location features, pressure patterns and in-game event impact.
6. **Market/availability/movement layer**: `player_market_values`, `player_transfers`, `player_injury_spells`. This supports valuation, transfer success, availability, risk and squad planning models.
7. **Model output layer**: `computed_metrics`. This can store predictions, risk scores, feature explanations and model outputs as JSONB.

## Relational architecture

- `competitions` → `seasons`: one competition has many seasons.
- `seasons` → `matches`: one season has many matches.
- `teams` → `matches`: teams appear as home and away teams through `home_team_id` and `away_team_id`.
- `players` → `player_season_stats`, `player_match_performance`, `player_market_values`, `player_transfers`, `player_injury_spells`: player IDs connect performance, valuation, movement and availability.
- `teams` + `seasons` → team-season tables: the four team-season tables are keyed by `team_id` and `season_id`.
- `matches` → `player_match_performance` and `match_events`: `game_id` links match-level, player-match and event-level data.

## Loader mechanics and assumptions

- Loader input folder: `/home/oai/Downloads/sql_ready_exports/pl`.
- Default league code: `ENG-PL`. This is added when a CSV does not carry a league code.
- The loader builds lookup maps from `seasons` and `teams` before loading match and downstream tables.
- Team-name aliases are used to map common source variants like `Manchester Utd`, `Newcastle Utd`, `Nottm Forest`, and `West Ham` to canonical team names.
- Integer-like float columns are cast to nullable integers where possible.
- Most tables use `ON CONFLICT ... DO UPDATE`; some seed/reference or event tables use `DO NOTHING` depending on the configuration.
- Materialized views are refreshed at the end of the load process.

### CSV-to-table loading plan

| CSV stem | Target table | Conflict key | Updates on conflict |
|---|---|---|---|
| `competitions.csv` | `competitions` | `league_code` | `True` |
| `seasons.csv` | `seasons` | `competition_id, season` | `False` |
| `teams.csv` | `teams` | `team_name` | `False` |
| `player_profile.csv` | `players` | `player_id` | `True` |
| `matches.csv` | `matches` | `game_id` | `True` |
| `team_season_standings.csv` | `team_season_standings` | `team_id, season_id` | `True` |
| `team_season_home_away_standings.csv` | `team_season_home_away_standings` | `team_id, season_id` | `True` |
| `team_season_stats_for.csv` | `team_season_stats_for` | `team_id, season_id` | `True` |
| `team_season_stats_against.csv` | `team_season_stats_against` | `team_id, season_id` | `True` |
| `player_season_stats.csv` | `player_season_stats` | `player_id, season_id, team_id` | `True` |
| `player_season_splits.csv` | `player_season_splits` | `player_id, season_id, group_type, group_name` | `True` |
| `player_match_performance.csv` | `player_match_performance` | `player_id, game_id, season, league_code` | `True` |
| `match_events.csv` | `match_events` | `game_id, player_id, minute, expanded_minute, type, season, league_code` | `False` |
| `player_market_values.csv` | `player_market_values` | `player_id, date_unix` | `True` |
| `player_transfers.csv` | `player_transfers` | `player_id, transfer_date, from_team, to_team` | `True` |
| `player_injury_spells.csv` | `player_injury_spells` | `player_id, season, from_matchweek, league_code` | `True` |

## Naming conventions

- Shared relational IDs use stable names: `player_id`, `team_id`, `season_id`, `competition_id`, `game_id`.
- Table-specific metric columns use prefixes to prevent ambiguity when joining wide datasets:
  - `pss_` = player season stats.
  - `pssp_` = player season split.
  - `pmp_` = player match performance.
  - `tss_` = team season standings.
  - `tshas_` = team season home/away standings.
  - `tssf_` = team season stats for.
  - `tssa_` = team season stats against.
  - `vwtss_` = team season summary view.
- View columns may use a view prefix such as `vwtss_` to show that the variable is a derived/joined output from `vw_team_season_summary`.

## Table-by-table metadata

### `competitions`

League/competition master table. It identifies each domestic league or competition and is the top-level parent for seasons. This is the starting point for future multi-league expansion.

**Loader source:** `competitions.csv`.
**Conflict key:** `league_code`. **Update existing rows:** `True`.
**Loader transformation notes:** Loaded from competitions.csv. Conflict key: league_code. Rows update on conflict.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `competition_id` | `SERIAL` | `PRIMARY KEY` | Internal identifier for the competition/league. Used to connect seasons to competitions. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `league_code` | `VARCHAR(10)` | `NOT NULL` | Short competition code, currently defaulting to ENG-PL for Premier League records; key for multi-league expansion. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `league_name` | `VARCHAR(100)` | `NOT NULL` | Human-readable name of the competition or league. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `country` | `VARCHAR(50)` | `NOT NULL` | Country associated with the competition. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tier` | `SMALLINT` | `DEFAULT 1` | Competition tier level; useful when adding lower divisions or cross-league comparisons. | Contextual feature or metadata; evaluate usefulness depending on the model target. |

### `seasons`

Season calendar table. Each row links one competition to one season string and its start/end dates. It allows the same season label to exist across multiple competitions.

**Loader source:** `seasons.csv`.
**Conflict key:** `competition_id, season`. **Update existing rows:** `False`.
**Constraints:**
- `UNIQUE (competition_id, season)`
**Loader transformation notes:** Loaded from seasons.csv. Conflict key: competition_id + season. Existing rows are kept.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `season_id` | `SERIAL` | `PRIMARY KEY` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `competition_id` | `INT` | `NOT NULL REFERENCES competitions(competition_id)` | Internal identifier for the competition/league. Used to connect seasons to competitions. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `start_date` | `DATE` | `` | Season start date. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `end_date` | `DATE` | `` | Season end date, or injury spell end date depending on table context. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |

### `players`

Player identity/profile table. It stores stable player-level attributes that do not change match by match, such as name, nationality, birth year, height and preferred foot.

**Loader source:** `player_profile.csv`.
**Conflict key:** `player_id`. **Update existing rows:** `True`.
**Loader transformation notes:** Loaded from player_profile.csv into players. Conflict key: player_id. Rows update on conflict.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `player_id` | `INT` | `PRIMARY KEY` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_name` | `VARCHAR(100)` | `NOT NULL` | Human-readable player name. Useful for display and loader validation; player_id should be used for joins. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `nationality` | `VARCHAR(50)` | `` | Player nationality. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `birth_year` | `SMALLINT` | `` | Player year of birth; can be used to derive approximate age. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `height` | `SMALLINT` | `` | Player height, likely in centimetres depending on source. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `foot` | `VARCHAR(5)` | `` | Player preferred foot. | Contextual feature or metadata; evaluate usefulness depending on the model target. |

### `teams`

Team identity table. It stores canonical team names and internal team IDs used by match, team-season and player-season data.

**Loader source:** `teams.csv`.
**Conflict key:** `team_name`. **Update existing rows:** `False`.
**Loader transformation notes:** Loaded from teams.csv. Conflict key: team_name. Existing rows are kept.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `team_id` | `SERIAL` | `PRIMARY KEY` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `team_name` | `VARCHAR(100)` | `NOT NULL UNIQUE` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |

### `matches`

Match-level table. One row per match, including date, teams, scores, formations, venue, attendance, referee, team box-score statistics and average betting odds.

**Loader source:** `matches.csv`.
**Conflict key:** `game_id`. **Update existing rows:** `True`.
**Loader transformation notes:** Loaded from matches.csv. Loader renames date→match_date, start_time→kickoff_time, avgh/avgd/avga→average odds, avg_2_5/avg_2_5.1→over/under 2.5 odds. It maps season to season_id and home_team/away_team to IDs, normalizes attendance, drops unresolved season rows, and keeps only schema columns.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `game_id` | `INT` | `PRIMARY KEY` | Unique match/game identifier used as the main match key across match-level, player-match and event-level data. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `matchweek` | `SMALLINT` | `` | League matchweek/round number. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `match_date` | `DATE` | `` | Calendar date of the match. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `kickoff_time` | `TIME` | `` | Kickoff time of the match. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_team_id` | `INT` | `REFERENCES teams(team_id)` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `away_team_id` | `INT` | `REFERENCES teams(team_id)` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `home_score` | `SMALLINT` | `` | Home team goals at full time or half time depending on prefix. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_score` | `SMALLINT` | `` | Away team goals at full time or half time depending on prefix. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `ft_result` | `CHAR(1)` | `` | Result code at full time or half time, usually H/D/A or equivalent source code. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `ht_home_score` | `SMALLINT` | `` | Home team goals at full time or half time depending on prefix. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `ht_away_score` | `SMALLINT` | `` | Away team goals at full time or half time depending on prefix. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `ht_result` | `CHAR(1)` | `` | Result code at full time or half time, usually H/D/A or equivalent source code. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_formation` | `VARCHAR(10)` | `` | Team tactical formation string for the match. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_formation` | `VARCHAR(10)` | `` | Team tactical formation string for the match. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `venue` | `VARCHAR(100)` | `` | Stadium or venue name. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `attendance_m` | `INT` | `` | Attendance figure. Can proxy crowd size, match importance and fan engagement. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `referee` | `VARCHAR(100)` | `` | Match referee. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_shots` | `SMALLINT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_shots` | `SMALLINT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_shots_on_target` | `SMALLINT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_shots_on_target` | `SMALLINT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_corners` | `SMALLINT` | `` | Corner kicks. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_corners` | `SMALLINT` | `` | Corner kicks. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_fouls` | `SMALLINT` | `` | Source-provided field. See table context and prefix notes for interpretation. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_fouls` | `SMALLINT` | `` | Source-provided field. See table context and prefix notes for interpretation. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_yellow_cards` | `SMALLINT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_yellow_cards` | `SMALLINT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_red_cards` | `SMALLINT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_red_cards` | `SMALLINT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_touches` | `SMALLINT` | `` | Team/player touches. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_touches` | `SMALLINT` | `` | Team/player touches. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_tackles` | `SMALLINT` | `` | Source-provided field. See table context and prefix notes for interpretation. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_tackles` | `SMALLINT` | `` | Source-provided field. See table context and prefix notes for interpretation. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_interceptions` | `SMALLINT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `away_interceptions` | `SMALLINT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `home_clearances` | `SMALLINT` | `` | Clearances. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_clearances` | `SMALLINT` | `` | Clearances. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_aerials_won` | `SMALLINT` | `` | Aerial duels won. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_aerials_won` | `SMALLINT` | `` | Aerial duels won. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_long_balls` | `SMALLINT` | `` | Long balls attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_long_balls` | `SMALLINT` | `` | Long balls attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_crosses` | `SMALLINT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_crosses` | `SMALLINT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_goal_kicks` | `SMALLINT` | `` | Goal kicks. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_goal_kicks` | `SMALLINT` | `` | Goal kicks. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `home_throw_ins` | `SMALLINT` | `` | Throw-ins. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `away_throw_ins` | `SMALLINT` | `` | Throw-ins. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `avg_home_odds` | `NUMERIC(5,2)` | `` | Average betting-market odds. Useful as external market expectation, calibration benchmark and upset detection feature. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `avg_draw_odds` | `NUMERIC(5,2)` | `` | Average betting-market odds. Useful as external market expectation, calibration benchmark and upset detection feature. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `avg_away_odds` | `NUMERIC(5,2)` | `` | Average betting-market odds. Useful as external market expectation, calibration benchmark and upset detection feature. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `avg_over25_odds` | `NUMERIC(5,2)` | `` | Average betting-market odds. Useful as external market expectation, calibration benchmark and upset detection feature. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `avg_under25_odds` | `NUMERIC(5,2)` | `` | Average betting-market odds. Useful as external market expectation, calibration benchmark and upset detection feature. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `player_season_stats`

Player-by-season-by-team aggregate performance table. One row represents a player’s league-season output for one club/team context.

**Loader source:** `player_season_stats.csv`.
**Conflict key:** `player_id, season_id, team_id`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (player_id, season_id, team_id)`
**Loader transformation notes:** Loaded from player_season_stats.csv. Loader renames selected source abbreviations, maps season/team to IDs, and keeps only schema columns. Conflict key: player_id + season_id + team_id.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `id` | `SERIAL` | `PRIMARY KEY` | Source-provided field. See table context and prefix notes for interpretation. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_id` | `INT` | `NOT NULL REFERENCES players(player_id)` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `team_id` | `INT` | `REFERENCES teams(team_id)` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `age` | `SMALLINT` | `` | Age measure. At player level it is player age; at team level it is average squad/team age. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `matches_played_pss` | `SMALLINT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `starts` | `SMALLINT` | `` | Number of starts in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `minutes_pss` | `INT` | `` | Minutes played or accumulated minutes in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `goals_pss` | `SMALLINT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `assists_pss` | `SMALLINT` | `` | Assists in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `yellow_cards_pss` | `SMALLINT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `red_cards_pss` | `SMALLINT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `shots_pss` | `SMALLINT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `shots_on_target_pss` | `SMALLINT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xg_pss` | `NUMERIC(6,3)` | `` | Expected goals metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xa_pss` | `NUMERIC(6,3)` | `` | Expected assists metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `npxg_pss` | `NUMERIC(6,3)` | `` | Non-penalty expected goals. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgchain_pss` | `NUMERIC(6,3)` | `` | xGChain: possession-chain involvement metric crediting players involved in moves that generate xG. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgbuildup_pss` | `NUMERIC(6,3)` | `` | xGBuildup: build-up contribution to possessions that generate xG, typically excluding final shot/assist actions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `key_passes_pss` | `SMALLINT` | `` | Key passes; passes leading directly to a shot. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `non_penalty_goals_pss` | `SMALLINT` | `` | Penalty goals scored/made. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `fouls_committed` | `SMALLINT` | `` | Fouls committed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `fouls_drawn_pss` | `SMALLINT` | `` | Fouls won/drawn. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `interceptions_pss` | `SMALLINT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tackles_won` | `SMALLINT` | `` | Tackles won. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `offsides_pss` | `SMALLINT` | `` | Offside events. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `crosses` | `SMALLINT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `saves_pss` | `SMALLINT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `clean_sheet` | `SMALLINT` | `` | Clean sheet count or clean sheet percentage depending on column name. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `shots_on_tgt_against` | `SMALLINT` | `` | Shots on target faced/allowed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `save_pct_pss` | `NUMERIC(5,2)` | `` | Goalkeeper/team save percentage. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `penalties_faced` | `SMALLINT` | `` | Penalties faced by goalkeeper/team. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `penalty_saves` | `SMALLINT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `player_season_splits`

Player seasonal split table. It stores player performance split by a grouping dimension, such as home/away, position, competition segment or other source-defined grouping.

**Loader source:** `player_season_splits.csv`.
**Conflict key:** `player_id, season_id, group_type, group_name`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (player_id, season_id, group_type, group_name)`
**Loader transformation notes:** Loaded from player_season_splits.csv. Loader maps season to season_id and drops player_name, season and league_code. Conflict key: player_id + season_id + group_type + group_name.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `id` | `SERIAL` | `PRIMARY KEY` | Source-provided field. See table context and prefix notes for interpretation. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_id` | `INT` | `NOT NULL REFERENCES players(player_id)` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `group_type` | `VARCHAR(50)` | `NOT NULL` | Split dimension type for player season splits. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `group_name` | `VARCHAR(50)` | `NOT NULL` | Specific split bucket/value for the split dimension. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `matches_played_pssp` | `SMALLINT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `minutes_pssp` | `INT` | `` | Minutes played or accumulated minutes in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `goals_pssp` | `SMALLINT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `assists_pssp` | `SMALLINT` | `` | Assists in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `yellow_cards_pssp` | `SMALLINT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `red_cards_pssp` | `SMALLINT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `shots_pssp` | `SMALLINT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xg_pssp` | `NUMERIC(6,3)` | `` | Expected goals metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xa_pssp` | `NUMERIC(6,3)` | `` | Expected assists metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `npxg_pssp` | `NUMERIC(6,3)` | `` | Non-penalty expected goals. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgchain_pssp` | `NUMERIC(6,3)` | `` | xGChain: possession-chain involvement metric crediting players involved in moves that generate xG. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgbuildup_pssp` | `NUMERIC(6,3)` | `` | xGBuildup: build-up contribution to possessions that generate xG, typically excluding final shot/assist actions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `key_passes_pssp` | `SMALLINT` | `` | Key passes; passes leading directly to a shot. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `non_penalty_goals_pssp` | `SMALLINT` | `` | Penalty goals scored/made. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `player_match_performance`

Player-by-match performance table. One row represents a player’s output in a specific match, including attacking, defensive and goalkeeper metrics. The table is partitioned by league and season.

**Loader source:** `player_match_performance.csv`.
**Conflict key:** `player_id, game_id, season, league_code`. **Update existing rows:** `True`.
**Partitioning:** this is a partitioned parent table. Data is organized by league and/or season using child partitions.
**Constraints:**
- `PRIMARY KEY (player_id, game_id, season, league_code)`
**Loader transformation notes:** Loaded from player_match_performance.csv. Loader renames source match-player columns to pmp-compatible names, adds DEFAULT_LEAGUE if missing, and keeps only schema columns. Conflict key: player_id + game_id + season + league_code.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `player_id` | `INT` | `NOT NULL` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `game_id` | `INT` | `NOT NULL` | Unique match/game identifier used as the main match key across match-level, player-match and event-level data. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `league_code` | `VARCHAR(10)` | `NOT NULL` | Short competition code, currently defaulting to ENG-PL for Premier League records; key for multi-league expansion. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `position` | `VARCHAR(10)` | `` | Player position in the match. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `minutes_played` | `SMALLINT` | `` | Minutes played or accumulated minutes in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `match_goals` | `SMALLINT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `match_assists` | `SMALLINT` | `` | Assists in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `match_shots` | `SMALLINT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `shots_on_target_pmp` | `SMALLINT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xg_pmp` | `NUMERIC(5,3)` | `` | Expected goals metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xa_pmp` | `NUMERIC(5,3)` | `` | Expected assists metric. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `npxg_pmp` | `NUMERIC(5,3)` | `` | Non-penalty expected goals. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgchain_pmp` | `NUMERIC(5,3)` | `` | xGChain: possession-chain involvement metric crediting players involved in moves that generate xG. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `xgbuildup_pmp` | `NUMERIC(5,3)` | `` | xGBuildup: build-up contribution to possessions that generate xG, typically excluding final shot/assist actions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `key_passes_pmp` | `SMALLINT` | `` | Key passes; passes leading directly to a shot. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `non_penalty_goals_pmp` | `SMALLINT` | `` | Penalty goals scored/made. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `yellow_cards_pmp` | `SMALLINT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `red_cards_pmp` | `SMALLINT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `fouls` | `SMALLINT` | `` | Fouls committed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `fouls_drawn_pmp` | `SMALLINT` | `` | Fouls won/drawn. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tackles_won` | `SMALLINT` | `` | Tackles won. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `interceptions_pmp` | `SMALLINT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `crosses` | `SMALLINT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `offsides_pmp` | `SMALLINT` | `` | Offside events. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `own_goals` | `SMALLINT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `pens_made` | `SMALLINT` | `` | Penalty goals scored/made. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pens_att` | `SMALLINT` | `` | Penalties attempted. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pens_won` | `SMALLINT` | `` | Penalties won. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pens_conceded` | `SMALLINT` | `` | Penalties conceded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `gk_saves` | `SMALLINT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `gk_goals_against` | `SMALLINT` | `` | Goals conceded/against in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `gk_save_pct` | `NUMERIC(4,1)` | `` | Goalkeeper/team save percentage. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `gk_shots_on_tgt_against` | `SMALLINT` | `` | Shots on target faced/allowed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `match_events`

Event-level table. It stores granular in-match events with coordinates, outcomes, pass/shot qualifiers, body parts, zones, related players and contextual labels. This is the highest-resolution football data in the database.

**Loader source:** `match_events.csv`.
**Conflict key:** `game_id, player_id, minute, expanded_minute, type, season, league_code`. **Update existing rows:** `False`.
**Partitioning:** this is a partitioned parent table. Data is organized by league and/or season using child partitions.
**Constraints:**
- `UNIQUE (game_id, player_id, minute, expanded_minute, type, season, league_code)`
- `PRIMARY KEY (event_id, season, league_code)`
**Loader transformation notes:** Loaded from match_events.csv. Loader renames event qualifier columns, adds DEFAULT_LEAGUE if missing, converts boolean flags, and uses a temporary table + COPY for high-volume ingestion. Conflict key: game_id + player_id + minute + expanded_minute + type + season + league_code.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `event_id` | `BIGSERIAL` | `` | Unique event identifier within the event table; used as the primary event-level row key together with partition keys. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `league_code` | `VARCHAR(10)` | `NOT NULL` | Short competition code, currently defaulting to ENG-PL for Premier League records; key for multi-league expansion. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `game_id` | `INT` | `` | Unique match/game identifier used as the main match key across match-level, player-match and event-level data. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `period` | `VARCHAR(20)` | `` | Temporal marker within the match/event stream. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `minute` | `INT` | `` | Temporal marker within the match/event stream. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `second` | `INT` | `` | Temporal marker within the match/event stream. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `expanded_minute` | `INT` | `` | Temporal marker within the match/event stream. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `type` | `VARCHAR(50)` | `` | Event type label, such as pass, shot, foul, tackle or source-specific event category. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `outcome_type` | `VARCHAR(50)` | `` | Event outcome label, such as successful/unsuccessful or source-specific result. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `team_id` | `INT` | `` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `team` | `VARCHAR(100)` | `` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `player_id` | `INT` | `` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_name` | `VARCHAR(100)` | `` | Human-readable player name. Useful for display and loader validation; player_id should be used for joins. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `x` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `y` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `end_x` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `end_y` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `goal_mouth_y` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `goal_mouth_z` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `blocked_x` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `blocked_y` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `is_touch` | `BOOLEAN` | `` | Boolean indicator flag for the event category or outcome. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `is_shot` | `BOOLEAN` | `` | Boolean indicator flag for the event category or outcome. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `is_goal` | `BOOLEAN` | `` | Boolean indicator flag for the event category or outcome. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `related_event_id` | `BIGINT` | `` | Identifier for a related event/player referenced by this event. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `related_player_id` | `INT` | `` | Identifier for a related event/player referenced by this event. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `pass_length` | `NUMERIC(5,2)` | `` | Length of the pass event. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_angle` | `NUMERIC(6,3)` | `` | Angle of the pass event. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_end_x` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_end_y` | `NUMERIC(5,2)` | `` | Pitch or goalmouth coordinate associated with event start, end, block or shot destination. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `zone` | `VARCHAR(20)` | `` | Pitch zone or source-defined spatial bucket. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `player_caught_offside` | `BOOLEAN` | `` | Boolean indicating whether the player was caught offside. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `blocked_cross` | `BOOLEAN` | `` | Boolean indicating a blocked cross. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `body_part_1` | `VARCHAR(30)` | `` | Body part qualifier for an event. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `body_part_2` | `VARCHAR(30)` | `` | Body part qualifier for an event. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_type_1` | `VARCHAR(30)` | `` | Pass type qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_type_2` | `VARCHAR(30)` | `` | Pass type qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_type_3` | `VARCHAR(30)` | `` | Pass type qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_type_4` | `VARCHAR(30)` | `` | Pass type qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_type_5` | `VARCHAR(30)` | `` | Pass type qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_1` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_2` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_3` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_4` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_5` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `pass_quality_6` | `VARCHAR(30)` | `` | Pass quality qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_zone_1` | `VARCHAR(30)` | `` | Pitch zone or source-defined spatial bucket. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_direction_1` | `VARCHAR(30)` | `` | Shot direction qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_qualifier_1` | `VARCHAR(30)` | `` | Shot qualifier/descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_qualifier_2` | `VARCHAR(30)` | `` | Shot qualifier/descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_qualifier_3` | `VARCHAR(30)` | `` | Shot qualifier/descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_qualifier_4` | `VARCHAR(30)` | `` | Shot qualifier/descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_qualifier_5` | `VARCHAR(30)` | `` | Shot qualifier/descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `keeper_save_type_1` | `VARCHAR(30)` | `` | Goalkeeper save qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `keeper_save_type_2` | `VARCHAR(30)` | `` | Goalkeeper save qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `keeper_save_type_3` | `VARCHAR(30)` | `` | Goalkeeper save qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `keeper_save_type_4` | `VARCHAR(30)` | `` | Goalkeeper save qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `foul_type_1` | `VARCHAR(30)` | `` | Foul qualifier. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `situation` | `VARCHAR(50)` | `` | Game situation/context for the event, such as open play or set piece depending on source. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `shot_type` | `VARCHAR(50)` | `` | Shot type descriptor. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `player_assisted` | `VARCHAR(100)` | `` | Player credited with assisting or setting up the action, if available. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `last_action` | `VARCHAR(50)` | `` | Previous action before the shot/event, useful for sequence modelling. | Contextual feature or metadata; evaluate usefulness depending on the model target. |

### `player_market_values`

Player market value time series. One row is a player’s market valuation on a timestamp/date represented as Unix time.

**Loader source:** `player_market_values.csv`.
**Conflict key:** `player_id, date_unix`. **Update existing rows:** `True`.
**Constraints:**
- `PRIMARY KEY (player_id, date_unix)`
**Loader transformation notes:** Loaded from player_market_values.csv. Loader drops player_name, converts date_unix from date strings to Unix seconds when needed, and filters unknown player_id rows. Conflict key: player_id + date_unix.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `player_id` | `INT` | `NOT NULL REFERENCES players(player_id)` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `date_unix` | `BIGINT` | `NOT NULL` | Unix timestamp for market value observation date. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `market_value` | `NUMERIC(12,2)` | `` | Player market value at the timestamp. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `player_transfers`

Player transfer history. One row describes a transfer or movement event with source team, destination team, date, type and fee.

**Loader source:** `player_transfers.csv`.
**Conflict key:** `player_id, transfer_date, from_team, to_team`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (player_id, transfer_date, from_team, to_team)`
**Loader transformation notes:** Loaded from player_transfers.csv. Loader renames from_team_name/to_team_name and drops player_name; filters unknown player_id rows. Conflict key: player_id + transfer_date + from_team + to_team.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `transfer_id` | `SERIAL` | `PRIMARY KEY` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_id` | `INT` | `REFERENCES players(player_id)` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season` | `VARCHAR(9)` | `` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `transfer_date` | `DATE` | `` | Date of transfer/movement. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `from_team` | `VARCHAR(100)` | `` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `to_team` | `VARCHAR(100)` | `` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `transfer_type` | `VARCHAR(50)` | `` | Transfer type, such as permanent, loan, free transfer or source-specific label. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `transfer_fee` | `NUMERIC(12,2)` | `` | Transfer fee amount, numeric when available. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `player_injury_spells`

Player availability and injury table. One row describes a spell of absence with matchweek range, dates, games/days missed and injury reason.

**Loader source:** `player_injury_spells.csv`.
**Conflict key:** `player_id, season, from_matchweek, league_code`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (player_id, season, from_matchweek, league_code)`
**Loader transformation notes:** Loaded from player_injury_spells.csv. Loader adds DEFAULT_LEAGUE if missing, drops source spell_id and spans_next_season, and filters unknown player_id rows. Conflict key: player_id + season + from_matchweek + league_code.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `spell_id` | `SERIAL` | `PRIMARY KEY` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_id` | `INT` | `REFERENCES players(player_id)` | External/internal player identifier. Foreign key to players when constrained. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `player_name` | `VARCHAR(100)` | `` | Human-readable player name. Useful for display and loader validation; player_id should be used for joins. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `season` | `VARCHAR(9)` | `` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `league_code` | `VARCHAR(10)` | `` | Short competition code, currently defaulting to ENG-PL for Premier League records; key for multi-league expansion. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `team` | `VARCHAR(100)` | `` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `from_matchweek` | `SMALLINT` | `` | League matchweek/round number. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `to_matchweek` | `SMALLINT` | `` | League matchweek/round number. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `from_date` | `DATE` | `` | Start date of injury/absence spell. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `end_date` | `DATE` | `` | Season end date, or injury spell end date depending on table context. | Temporal feature; useful for recency weighting, trend construction and time-aware validation. |
| `games_missed` | `SMALLINT` | `` | Number of games missed during the injury/absence spell. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `days_missed` | `SMALLINT` | `` | Number of days missed during the injury/absence spell. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `injury_reason` | `VARCHAR(200)` | `` | Text label describing the injury or absence reason. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `computed_metrics`

Flexible model/output storage table. It can store generated metrics, scores, predictions and model artifacts as JSONB by entity type and entity ID.

**Constraints:**
- `UNIQUE (entity_type, entity_id, metric_name, parameters)`

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `metric_id` | `UUID` | `PRIMARY KEY DEFAULT gen_random_uuid()` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `entity_type` | `VARCHAR(20)` | `NOT NULL` | Entity category for a computed metric, e.g. player, team, match, season or transfer. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `entity_id` | `INT` | `NOT NULL` | Identifier column used for relational joins or entity tracking. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `metric_name` | `VARCHAR(100)` | `NOT NULL` | Name of the stored metric, prediction or score. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `metric_value` | `JSONB` | `NOT NULL` | JSONB payload containing the metric value or model output. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `parameters` | `JSONB` | `` | JSONB payload describing model parameters, filters or configuration used to compute the metric. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `computed_at` | `TIMESTAMPTZ` | `DEFAULT now()` | Timestamp when the metric was computed. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `source_query` | `TEXT` | `` | SQL or process description used to compute the metric. | Contextual feature or metadata; evaluate usefulness depending on the model target. |

### `team_season_standings`

Team final/season standings table. One row per team-season, including rank, points, record, goal difference, attendance and top scorer information.

**Loader source:** `team_season_standings.csv`.
**Conflict key:** `team_id, season_id`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (tss_team, tss_season)`
- `UNIQUE (team_id, season_id)`
**Loader transformation notes:** Loaded from team_season_standings.csv. Loader renames source standing columns to tss_* columns and maps tss_team + tss_season to team_id + season_id. Conflict key: team_id + season_id.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `team_id` | `INT` | `NOT NULL REFERENCES teams(team_id)` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `tss_team` | `VARCHAR(100)` | `NOT NULL` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tss_season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tss_rank` | `INT` | `` | League table rank/position for the team-season. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tss_matches_played` | `INT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tss_wins` | `INT` | `` | Number of wins in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_draws` | `INT` | `` | Number of draws in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_losses` | `INT` | `` | Number of losses in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_goals_for` | `INT` | `` | Goals scored by the team in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_goals_against` | `INT` | `` | Goals conceded/against in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_goal_difference` | `INT` | `` | Goals for minus goals against in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tss_points` | `INT` | `` | League points in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_attendance` | `INT` | `` | Attendance figure. Can proxy crowd size, match importance and fan engagement. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tss_goalkeeper_name` | `VARCHAR(100)` | `` | Main or source-listed goalkeeper for the team-season. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tss_notes` | `TEXT` | `` | Source notes or annotations. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tss_top_scorer_name` | `VARCHAR(100)` | `` | Top scorer information for the team-season. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tss_top_scorer_goals` | `INT` | `` | Top scorer information for the team-season. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `team_season_home_away_standings`

Team-season home/away split table. One row per team-season with separate home and away records, goals and points.

**Loader source:** `team_season_home_away_standings.csv`.
**Conflict key:** `team_id, season_id`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (tshas_team, tshas_season)`
- `UNIQUE (team_id, season_id)`
**Loader transformation notes:** Loaded from team_season_home_away_standings.csv. Loader renames source home/away columns to tshas_* columns and maps team/season IDs. Conflict key: team_id + season_id.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `team_id` | `INT` | `NOT NULL REFERENCES teams(team_id)` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `tshas_team` | `VARCHAR(100)` | `NOT NULL` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tshas_season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_rank` | `INT` | `` | League table rank/position for the team-season. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_home_matches_played` | `INT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_home_wins` | `INT` | `` | Number of wins in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_home_draws` | `INT` | `` | Number of draws in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_home_losses` | `INT` | `` | Number of losses in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_home_goals_for` | `INT` | `` | Goals scored by the team in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_home_goals_against` | `INT` | `` | Goals conceded/against in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_home_goal_difference` | `INT` | `` | Goals for minus goals against in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_home_points` | `INT` | `` | League points in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_matches_played` | `INT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_away_wins` | `INT` | `` | Number of wins in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_draws` | `INT` | `` | Number of draws in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_losses` | `INT` | `` | Number of losses in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_goals_for` | `INT` | `` | Goals scored by the team in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_goals_against` | `INT` | `` | Goals conceded/against in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tshas_away_goal_difference` | `INT` | `` | Goals for minus goals against in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tshas_away_points` | `INT` | `` | League points in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `team_season_stats_for`

Team-season “for” performance table. Metrics describe what the team produced or recorded for itself: possession, attacking output, defensive/GK outputs, cards, shots, fouls and other team-level actions.

**Loader source:** `team_season_stats_for.csv`.
**Conflict key:** `team_id, season_id`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (tssf_team, tssf_season)`
- `UNIQUE (team_id, season_id)`
**Loader transformation notes:** Loaded from team_season_stats_for.csv. Loader renames source “for” team-stat columns to tssf_* columns and maps team/season IDs. Conflict key: team_id + season_id.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `team_id` | `INT` | `NOT NULL REFERENCES teams(team_id)` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `tssf_team` | `VARCHAR(100)` | `NOT NULL` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tssf_season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_players_used` | `INT` | `` | Number of different players used by a team in the season; proxy for rotation, depth and injuries. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_average_age` | `NUMERIC(5,2)` | `` | Age measure. At player level it is player age; at team level it is average squad/team age. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_possession_percentage` | `NUMERIC(5,2)` | `` | Possession percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_matches_played` | `INT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_starts` | `INT` | `` | Number of starts in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_minutes` | `INT` | `` | Minutes played or accumulated minutes in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_assists` | `INT` | `` | Assists in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_assists` | `INT` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_non_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalties_attempted` | `INT` | `` | Penalties attempted. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_yellow_cards` | `INT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_red_cards` | `INT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_per90` | `NUMERIC(6,3)` | `` | Goals per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_assists_per90` | `NUMERIC(6,3)` | `` | Assists per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_assists_per90` | `NUMERIC(6,3)` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_non_penalty_goals_per90` | `NUMERIC(6,3)` | `` | Non-penalty goals per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_non_penalty_goals_assists_per90` | `NUMERIC(6,3)` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_allowed` | `INT` | `` | Goals conceded/allowed in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_allowed_per90` | `NUMERIC(6,3)` | `` | Goals allowed per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_shots_on_target_against` | `INT` | `` | Shots on target faced/allowed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_saves` | `INT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_save_percentage` | `NUMERIC(6,3)` | `` | Goalkeeper/team save percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_wins` | `INT` | `` | Number of wins in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_draws` | `INT` | `` | Number of draws in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_losses` | `INT` | `` | Number of losses in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_clean_sheets` | `INT` | `` | Clean sheet count or clean sheet percentage depending on column name. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_clean_sheet_percentage` | `NUMERIC(6,3)` | `` | Clean sheet count or clean sheet percentage depending on column name. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalties_faced` | `INT` | `` | Penalties faced by goalkeeper/team. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_penalty_goals_allowed` | `INT` | `` | Goals conceded/allowed in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalty_saves` | `INT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalty_misses` | `INT` | `` | Penalties missed by opponents. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_penalty_save_percentage` | `NUMERIC(6,3)` | `` | Goalkeeper/team save percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_nineties` | `NUMERIC(6,2)` | `` | Number of 90-minute equivalents played. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_shots` | `INT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_shots_on_target` | `INT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_shots_on_target_percentage` | `NUMERIC(6,3)` | `` | Share of shots that were on target. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_shots_per90` | `NUMERIC(6,3)` | `` | Shots per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_shots_on_target_per90` | `NUMERIC(6,3)` | `` | Shots on target per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_per_shot` | `NUMERIC(6,3)` | `` | Goals divided by shots; finishing efficiency. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_goals_per_shot_on_target` | `NUMERIC(6,3)` | `` | Goals divided by shots on target; finishing efficiency on target. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_standard_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_second_yellow_red_cards` | `INT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_fouls_committed` | `INT` | `` | Fouls committed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_fouls_drawn` | `INT` | `` | Fouls won/drawn. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_offsides` | `INT` | `` | Offside events. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_crosses` | `INT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_interceptions` | `INT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_tackles_won` | `INT` | `` | Tackles won. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssf_penalties_won` | `INT` | `` | Penalties won. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_penalties_conceded` | `INT` | `` | Penalties conceded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssf_own_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

### `team_season_stats_against`

Team-season “against” table. Metrics describe what opponents produced against this team: opponent possession, opponent attacking output, conceded chance profile and defensive exposure.

**Loader source:** `team_season_stats_against.csv`.
**Conflict key:** `team_id, season_id`. **Update existing rows:** `True`.
**Constraints:**
- `UNIQUE (tssa_team, tssa_season)`
- `UNIQUE (team_id, season_id)`
**Loader transformation notes:** Loaded from team_season_stats_against.csv. Loader renames source “against” columns to tssa_* columns, strips leading "vs " from team names, and maps team/season IDs. Conflict key: team_id + season_id.

| Column | Type | Nullable / constraint notes | Meaning | Modelling use |
|---|---:|---|---|---|
| `team_id` | `INT` | `NOT NULL REFERENCES teams(team_id)` | Internal canonical team identifier. Foreign key to teams. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `season_id` | `INT` | `NOT NULL REFERENCES seasons(season_id)` | Internal identifier for a season within a competition. Foreign key to seasons. | Join key / entity identifier; generally not used as a direct predictive signal except for grouping. |
| `tssa_team` | `VARCHAR(100)` | `NOT NULL` | Human-readable team name. In final modelling, prefer team_id for joins and this field for audits/display. | Human-readable label for validation, display and audits; avoid using as numeric model feature. |
| `tssa_season` | `VARCHAR(9)` | `NOT NULL` | Season label in YYYY-YYYY format, used for human-readable filtering and mapping to season_id. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_players_used` | `INT` | `` | Number of different players used by a team in the season; proxy for rotation, depth and injuries. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_average_age` | `NUMERIC(5,2)` | `` | Age measure. At player level it is player age; at team level it is average squad/team age. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_possession_percentage` | `NUMERIC(5,2)` | `` | Possession percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_matches_played` | `INT` | `` | Number of matches played in this context. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_starts` | `INT` | `` | Number of starts in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_minutes` | `INT` | `` | Minutes played or accumulated minutes in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_assists` | `INT` | `` | Assists in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_assists` | `INT` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_non_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalties_attempted` | `INT` | `` | Penalties attempted. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_yellow_cards` | `INT` | `` | Yellow cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_red_cards` | `INT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_per90` | `NUMERIC(6,3)` | `` | Goals per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_assists_per90` | `NUMERIC(6,3)` | `` | Assists per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_assists_per90` | `NUMERIC(6,3)` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_non_penalty_goals_per90` | `NUMERIC(6,3)` | `` | Non-penalty goals per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_non_penalty_goals_assists_per90` | `NUMERIC(6,3)` | `` | Combined goals plus assists. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_allowed` | `INT` | `` | Goals conceded/allowed in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_allowed_per90` | `NUMERIC(6,3)` | `` | Goals allowed per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_shots_on_target_against` | `INT` | `` | Shots on target faced/allowed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_saves` | `INT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_save_percentage` | `NUMERIC(6,3)` | `` | Goalkeeper/team save percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_wins` | `INT` | `` | Number of wins in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_draws` | `INT` | `` | Number of draws in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_losses` | `INT` | `` | Number of losses in this context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_clean_sheets` | `INT` | `` | Clean sheet count or clean sheet percentage depending on column name. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_clean_sheet_percentage` | `NUMERIC(6,3)` | `` | Clean sheet count or clean sheet percentage depending on column name. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalties_faced` | `INT` | `` | Penalties faced by goalkeeper/team. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_penalty_goals_allowed` | `INT` | `` | Goals conceded/allowed in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalty_saves` | `INT` | `` | Goalkeeper saves. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalty_misses` | `INT` | `` | Penalties missed by opponents. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_penalty_save_percentage` | `NUMERIC(6,3)` | `` | Goalkeeper/team save percentage. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_nineties` | `NUMERIC(6,2)` | `` | Number of 90-minute equivalents played. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_shots` | `INT` | `` | Shot count in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_shots_on_target` | `INT` | `` | Shots on target in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_shots_on_target_percentage` | `NUMERIC(6,3)` | `` | Share of shots that were on target. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_shots_per90` | `NUMERIC(6,3)` | `` | Shots per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_shots_on_target_per90` | `NUMERIC(6,3)` | `` | Shots on target per 90 minutes. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_per_shot` | `NUMERIC(6,3)` | `` | Goals divided by shots; finishing efficiency. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_goals_per_shot_on_target` | `NUMERIC(6,3)` | `` | Goals divided by shots on target; finishing efficiency on target. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_standard_penalty_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_second_yellow_red_cards` | `INT` | `` | Red cards received. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_fouls_committed` | `INT` | `` | Fouls committed. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_fouls_drawn` | `INT` | `` | Fouls won/drawn. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_offsides` | `INT` | `` | Offside events. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_crosses` | `INT` | `` | Crosses attempted or recorded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_interceptions` | `INT` | `` | Interceptions. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_tackles_won` | `INT` | `` | Tackles won. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |
| `tssa_penalties_won` | `INT` | `` | Penalties won. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_penalties_conceded` | `INT` | `` | Penalties conceded. | Contextual feature or metadata; evaluate usefulness depending on the model target. |
| `tssa_own_goals` | `INT` | `` | Goals scored in the relevant context. | Potential predictive feature for team/player performance, risk scoring, availability, valuation or match outcome models. |

## Partitioned tables and child partitions

Two high-volume tables are partitioned: `player_match_performance` and `match_events`. Partitioning is important because it keeps large match/player/event datasets manageable as more leagues and seasons are added.

No child partitions were found in the parsed schema.

## Materialized views

Materialized views are precomputed modelling datasets. They denormalize key joins so model builders do not need to repeatedly join raw tables.

### `vw_player_season_summary`

Joined modelling view combining player profile, season, competition, team, player season stats and the latest market value available for the player.

**Approximate source join:** `player_season_stats pss JOIN players p ON p.player_id = pss.player_id JOIN seasons s ON s.season_id = pss.season_id JOIN competitions c ON c.competition_id = s.competition_id JOIN teams t ON t.team_id = pss.team_id LEFT JOIN LATERAL ( SELECT market_value FROM player_market_values WHERE player_id = pss.player_id ORDER BY date_unix DESC LIMIT 1 ) mv ON true`

**Columns exposed:**
- `player_id`, `player_name`, `nationality`, `birth_year`
- `season`, `league_name`, `league_code`, `team`
- `age`, `matches_played_pss`, `starts`, `minutes_pss`
- `goals_pss`, `assists_pss`, `yellow_cards_pss`, `red_cards_pss`
- `shots_pss`, `shots_on_target_pss`, `xg_pss`, `xa_pss`
- `npxg_pss`, `xgchain_pss`, `xgbuildup_pss`, `key_passes_pss`
- `non_penalty_goals_pss`, `fouls_committed`, `fouls_drawn_pss`, `interceptions_pss`
- `tackles_won`, `saves_pss`, `clean_sheet`, `save_pct_pss`
- `market_value`

### `vw_player_match_summary`

Joined modelling view for player-match rows, enriched with player name, match metadata, teams, score and match-level player performance.

**Approximate source join:** `player_match_performance pmp JOIN players p ON p.player_id = pmp.player_id JOIN matches m ON m.game_id = pmp.game_id JOIN teams ht ON ht.team_id = m.home_team_id JOIN teams at ON at.team_id = m.away_team_id`

**Columns exposed:**
- `player_id`, `player_name`, `season`, `league_code`
- `game_id`, `matchweek`, `match_date`, `home_team`
- `away_team`, `home_score`, `away_score`, `ft_result`
- `position`, `minutes_played`, `match_goals`, `match_assists`
- `match_shots`, `shots_on_target_pmp`, `xg_pmp`, `xa_pmp`
- `npxg_pmp`, `xgchain_pmp`, `xgbuildup_pmp`, `key_passes_pmp`
- `yellow_cards_pmp`, `red_cards_pmp`, `fouls`, `fouls_drawn_pmp`
- `tackles_won`, `interceptions_pmp`, `crosses`, `gk_saves`
- `gk_goals_against`, `gk_save_pct`

### `vw_player_shooting_profile`

Event-derived view focused on player shooting behaviour, aggregating shots, goals and shot locations/contexts from match events.

**Approximate source join:** `match_events me JOIN matches m ON m.game_id = me.game_id AND m.season_id IN ( SELECT season_id FROM seasons s JOIN competitions c ON c.competition_id = s.competition_id WHERE c.league_code = me.league_code AND s.season = me.season ) JOIN teams ht ON ht.team_id = m.home_team_id JOIN teams at ON at.team_id = m.away_team_id WHERE me.is_shot = TRUE`

**Columns exposed:**
- `player_id`, `player_name`, `season`, `league_code`
- `game_id`, `minute`, `team`, `home_team`
- `away_team`, `x`, `y`, `end_x`
- `end_y`, `is_goal`, `situation`, `shot_type`
- `body_part`, `shot_zone`, `shot_direction`, `player_assisted`
- `last_action`, `goal_mouth_y`, `goal_mouth_z`

### `vw_player_availability`

Availability view summarizing injury/absence burden by player, season and league.

**Approximate source join:** `player_injury_spells pis JOIN players p ON p.player_id = pis.player_id`

**Columns exposed:**
- `player_id`, `player_name`, `season`, `league_code`
- `team`, `from_matchweek`, `to_matchweek`, `from_date`
- `end_date`, `games_missed`, `days_missed`, `injury_reason`

### `vw_team_season_summary`

Joined modelling view combining team standing, home/away splits, team stats for, team stats against, season and league metadata.

**Approximate source join:** `team_season_standings st JOIN teams t ON t.team_id = st.team_id JOIN seasons s ON s.season_id = st.season_id JOIN competitions c ON c.competition_id = s.competition_id LEFT JOIN team_season_home_away_standings ha ON ha.team_id = st.team_id AND ha.season_id = st.season_id LEFT JOIN team_season_stats_for sf ON sf.team_id = st.team_id AND sf.season_id = st.season_id LEFT JOIN team_season_stats_against sa ON sa.team_id = st.team_id AND sa.season_id = st.season_id`

**Columns exposed:**
- `vwtss_team_id`, `vwtss_team_name`, `vwtss_season_id`, `vwtss_season`
- `vwtss_competition_id`, `vwtss_league_name`, `vwtss_league_code`, `vwtss_rank`
- `vwtss_matches_played`, `vwtss_wins`, `vwtss_draws`, `vwtss_losses`
- `vwtss_points`, `vwtss_goals_for`, `vwtss_goals_against`, `vwtss_goal_difference`
- `vwtss_attendance`, `vwtss_goalkeeper_name`, `vwtss_notes`, `vwtss_top_scorer_name`
- `vwtss_top_scorer_goals`, `vwtss_home_matches_played`, `vwtss_home_wins`, `vwtss_home_draws`
- `vwtss_home_losses`, `vwtss_home_goals_for`, `vwtss_home_goals_against`, `vwtss_home_goal_difference`
- `vwtss_home_points`, `vwtss_away_matches_played`, `vwtss_away_wins`, `vwtss_away_draws`
- `vwtss_away_losses`, `vwtss_away_goals_for`, `vwtss_away_goals_against`, `vwtss_away_goal_difference`
- `vwtss_away_points`, `vwtss_players_used_for`, `vwtss_average_age_for`, `vwtss_possession_percentage_for`
- `vwtss_matches_played_for`, `vwtss_starts_for`, `vwtss_minutes_for`, `vwtss_goals_stat_for`
- `vwtss_assists_for`, `vwtss_goals_assists_for`, `vwtss_non_penalty_goals_for`, `vwtss_penalty_goals_for`
- `vwtss_penalties_attempted_for`, `vwtss_yellow_cards_for`, `vwtss_red_cards_for`, `vwtss_goals_per90_for`
- `vwtss_assists_per90_for`, `vwtss_goals_assists_per90_for`, `vwtss_non_penalty_goals_per90_for`, `vwtss_non_penalty_goals_assists_per90_for`
- `vwtss_goals_allowed_for`, `vwtss_goals_allowed_per90_for`, `vwtss_shots_on_target_against_for`, `vwtss_saves_for`
- `vwtss_save_percentage_for`, `vwtss_wins_for`, `vwtss_draws_for`, `vwtss_losses_for`
- `vwtss_clean_sheets_for`, `vwtss_clean_sheet_percentage_for`, `vwtss_penalties_faced_for`, `vwtss_penalty_goals_allowed_for`
- `vwtss_penalty_saves_for`, `vwtss_penalty_misses_for`, `vwtss_penalty_save_percentage_for`, `vwtss_nineties_for`
- `vwtss_shots_for`, `vwtss_shots_on_target_for`, `vwtss_shots_on_target_percentage_for`, `vwtss_shots_per90_for`
- `vwtss_shots_on_target_per90_for`, `vwtss_goals_per_shot_for`, `vwtss_goals_per_shot_on_target_for`, `vwtss_standard_penalty_goals_for`
- `vwtss_second_yellow_red_cards_for`, `vwtss_fouls_committed_for`, `vwtss_fouls_drawn_for`, `vwtss_offsides_for`
- `vwtss_crosses_for`, `vwtss_interceptions_for`, `vwtss_tackles_won_for`, `vwtss_penalties_won_for`
- `vwtss_penalties_conceded_for`, `vwtss_own_goals_for`, `vwtss_players_used_against`, `vwtss_average_age_against`
- `vwtss_possession_percentage_against`, `vwtss_matches_played_against`, `vwtss_starts_against`, `vwtss_minutes_against`
- `vwtss_goals_stat_against`, `vwtss_assists_against`, `vwtss_goals_assists_against`, `vwtss_non_penalty_goals_against`
- `vwtss_penalty_goals_against`, `vwtss_penalties_attempted_against`, `vwtss_yellow_cards_against`, `vwtss_red_cards_against`
- `vwtss_goals_per90_against`, `vwtss_assists_per90_against`, `vwtss_goals_assists_per90_against`, `vwtss_non_penalty_goals_per90_against`
- `vwtss_non_penalty_goals_assists_per90_against`, `vwtss_goals_allowed_against`, `vwtss_goals_allowed_per90_against`, `vwtss_shots_on_target_against_stat`
- `vwtss_saves_against`, `vwtss_save_percentage_against`, `vwtss_wins_against`, `vwtss_draws_against`
- `vwtss_losses_against`, `vwtss_clean_sheets_against`, `vwtss_clean_sheet_percentage_against`, `vwtss_penalties_faced_against`
- `vwtss_penalty_goals_allowed_against`, `vwtss_penalty_saves_against`, `vwtss_penalty_misses_against`, `vwtss_penalty_save_percentage_against`
- `vwtss_nineties_against`, `vwtss_shots_against`, `vwtss_shots_on_target_against`, `vwtss_shots_on_target_percentage_against`
- `vwtss_shots_per90_against`, `vwtss_shots_on_target_per90_against`, `vwtss_goals_per_shot_against`, `vwtss_goals_per_shot_on_target_against`
- `vwtss_standard_penalty_goals_against`, `vwtss_second_yellow_red_cards_against`, `vwtss_fouls_committed_against`, `vwtss_fouls_drawn_against`
- `vwtss_offsides_against`, `vwtss_crosses_against`, `vwtss_interceptions_against`, `vwtss_tackles_won_against`
- `vwtss_penalties_won_against`, `vwtss_penalties_conceded_against`, `vwtss_own_goals_against`

### `vw_match_summary`

Joined modelling view combining match facts with readable season, league, home team and away team names.

**Approximate source join:** `matches m JOIN seasons s ON s.season_id = m.season_id JOIN competitions c ON c.competition_id = s.competition_id JOIN teams ht ON ht.team_id = m.home_team_id JOIN teams at ON at.team_id = m.away_team_id`

**Columns exposed:**
- `game_id`, `season`, `league_name`, `league_code`
- `matchweek`, `match_date`, `kickoff_time`, `home_team`
- `away_team`, `home_score`, `away_score`, `ft_result`
- `ht_home_score`, `ht_away_score`, `ht_result`, `home_formation`
- `away_formation`, `home_shots`, `away_shots`, `home_shots_on_target`
- `away_shots_on_target`, `home_corners`, `away_corners`, `home_fouls`
- `away_fouls`, `home_yellow_cards`, `away_yellow_cards`, `home_red_cards`
- `away_red_cards`, `home_touches`, `away_touches`, `home_tackles`
- `away_tackles`, `home_interceptions`, `away_interceptions`, `home_clearances`
- `away_clearances`, `home_aerials_won`, `away_aerials_won`, `home_long_balls`
- `away_long_balls`, `attendance_m`, `venue`, `referee`
- `avg_home_odds`, `avg_draw_odds`, `avg_away_odds`, `avg_over25_odds`
- `avg_under25_odds`

## Indexes

Indexes are defined to speed up joins, filtering and materialized-view refreshes. The most important modelling indexes are on player IDs, season IDs, team IDs, league codes, match IDs and time fields.

| Table/View | Index name | Unique | Columns |
|---|---|---:|---|
| `player_season_stats` | `(unnamed)` | `False` | `player_id` |
| `player_season_stats` | `(unnamed)` | `False` | `season_id` |
| `player_season_stats` | `(unnamed)` | `False` | `team_id` |
| `player_season_splits` | `(unnamed)` | `False` | `player_id` |
| `player_season_splits` | `(unnamed)` | `False` | `season_id` |
| `player_season_splits` | `(unnamed)` | `False` | `group_type` |
| `player_match_performance` | `(unnamed)` | `False` | `player_id` |
| `player_match_performance` | `(unnamed)` | `False` | `game_id` |
| `player_match_performance` | `(unnamed)` | `False` | `season` |
| `player_match_performance` | `(unnamed)` | `False` | `league_code` |
| `match_events` | `(unnamed)` | `False` | `game_id` |
| `match_events` | `(unnamed)` | `False` | `player_id` |
| `match_events` | `(unnamed)` | `False` | `season` |
| `match_events` | `(unnamed)` | `False` | `league_code` |
| `match_events` | `(unnamed)` | `False` | `type` |
| `player_market_values` | `(unnamed)` | `False` | `player_id` |
| `player_transfers` | `(unnamed)` | `False` | `player_id` |
| `player_transfers` | `(unnamed)` | `False` | `season` |
| `player_injury_spells` | `(unnamed)` | `False` | `player_id` |
| `player_injury_spells` | `(unnamed)` | `False` | `season` |
| `player_injury_spells` | `(unnamed)` | `False` | `league_code` |
| `computed_metrics` | `(unnamed)` | `False` | `entity_type, entity_id` |
| `computed_metrics` | `(unnamed)` | `False` | `metric_name` |
| `vw_player_season_summary` | `(unnamed)` | `True` | `player_id, season, league_code, team` |
| `vw_player_season_summary` | `(unnamed)` | `False` | `player_id` |
| `vw_player_season_summary` | `(unnamed)` | `False` | `season` |
| `vw_player_season_summary` | `(unnamed)` | `False` | `league_code` |
| `vw_player_season_summary` | `(unnamed)` | `False` | `team` |
| `vw_player_match_summary` | `(unnamed)` | `True` | `player_id, game_id, league_code` |
| `vw_player_match_summary` | `(unnamed)` | `False` | `player_id` |
| `vw_player_match_summary` | `(unnamed)` | `False` | `season` |
| `vw_player_match_summary` | `(unnamed)` | `False` | `league_code` |
| `vw_player_match_summary` | `(unnamed)` | `False` | `home_team` |
| `vw_player_match_summary` | `(unnamed)` | `False` | `away_team` |
| `vw_player_shooting_profile` | `(unnamed)` | `True` | `player_id, game_id, minute, league_code` |
| `vw_player_shooting_profile` | `(unnamed)` | `False` | `player_id` |
| `vw_player_shooting_profile` | `(unnamed)` | `False` | `season` |
| `vw_player_shooting_profile` | `(unnamed)` | `False` | `league_code` |
| `vw_player_shooting_profile` | `(unnamed)` | `False` | `team` |
| `vw_player_availability` | `(unnamed)` | `True` | `player_id, season, league_code, from_matchweek` |
| `vw_player_availability` | `(unnamed)` | `False` | `player_id` |
| `vw_player_availability` | `(unnamed)` | `False` | `season` |
| `vw_player_availability` | `(unnamed)` | `False` | `league_code` |
| `vw_player_availability` | `(unnamed)` | `False` | `team` |
| `team_season_standings` | `idx_tss_team_id` | `False` | `team_id` |
| `team_season_standings` | `idx_tss_season_id` | `False` | `season_id` |
| `team_season_standings` | `idx_tss_team` | `False` | `tss_team` |
| `team_season_standings` | `idx_tss_season` | `False` | `tss_season` |
| `team_season_home_away_standings` | `idx_tshas_team_id` | `False` | `team_id` |
| `team_season_home_away_standings` | `idx_tshas_season_id` | `False` | `season_id` |
| `team_season_home_away_standings` | `idx_tshas_team` | `False` | `tshas_team` |
| `team_season_home_away_standings` | `idx_tshas_season` | `False` | `tshas_season` |
| `team_season_stats_for` | `idx_tssf_team_id` | `False` | `team_id` |
| `team_season_stats_for` | `idx_tssf_season_id` | `False` | `season_id` |
| `team_season_stats_for` | `idx_tssf_team` | `False` | `tssf_team` |
| `team_season_stats_for` | `idx_tssf_season` | `False` | `tssf_season` |
| `team_season_stats_against` | `idx_tssa_team_id` | `False` | `team_id` |
| `team_season_stats_against` | `idx_tssa_season_id` | `False` | `season_id` |
| `team_season_stats_against` | `idx_tssa_team` | `False` | `tssa_team` |
| `team_season_stats_against` | `idx_tssa_season` | `False` | `tssa_season` |
| `vw_team_season_summary` | `idx_vwtss_team_season_league` | `True` | `vwtss_team_id, vwtss_season_id, vwtss_competition_id` |
| `vw_team_season_summary` | `idx_vwtss_season` | `False` | `vwtss_season` |
| `vw_team_season_summary` | `idx_vwtss_league_code` | `False` | `vwtss_league_code` |
| `vw_team_season_summary` | `idx_vwtss_team_name` | `False` | `vwtss_team_name` |
| `vw_team_season_summary` | `idx_vwtss_points` | `False` | `vwtss_points` |
| `vw_match_summary` | `(unnamed)` | `True` | `game_id` |
| `vw_match_summary` | `(unnamed)` | `False` | `season` |
| `vw_match_summary` | `(unnamed)` | `False` | `league_code` |
| `vw_match_summary` | `(unnamed)` | `False` | `home_team` |
| `vw_match_summary` | `(unnamed)` | `False` | `away_team` |
| `vw_match_summary` | `(unnamed)` | `False` | `match_date` |

## Modelling-ready feature families

### Season/team outcome models
Use `vw_team_season_summary`, `matches`/`vw_match_summary`, and team-season raw tables. Candidate targets include title/top-four/Europe/mid-table/relegation classes, league-position movement, collapse risk, turnaround probability and over/underperformance.

Important feature groups: points, rank, goal difference, goals for/against, home/away points, shot volume, shots on target, possession, save percentage, clean sheets, fouls/cards, average age, players used, attendance and betting odds.

### Player impact and recruitment models
Use `vw_player_season_summary`, `player_match_performance`, `player_market_values`, `player_transfers` and `player_injury_spells`. Candidate targets include player impact on team trajectory, high-risk/high-upside signings, undervalued players, decline risk, breakout potential and cross-league transferability once more leagues are added.

Important feature groups: goals, assists, xG, xA, non-penalty goals, xGChain, xGBuildup, key passes, shots, defensive actions, minutes, starts, age, market value, transfer fee, injury days/games missed and availability.

### Match prediction models
Use `matches`, `vw_match_summary`, recent rolling team features from team-season/match tables, and player availability/performance tables. Candidate targets include home/draw/away probabilities, expected goals/scoreline, upset probability and betting-market deviation.

Important feature groups: home/away team IDs, recent form, matchweek, venue, attendance, referee, formations, team shots/cards/fouls/corners, average odds and availability-adjusted player strength.

### Event and in-game models
Use `match_events` and `player_match_performance`. Candidate targets include event impact on final result, shot quality, possession-chain value, pressure sequences, red-card/early-goal impact and tactical style effectiveness.

Important feature groups: event type, outcome, coordinates, minute/period, pass length/angle/end location, shot zone/direction/qualifiers, body part, related players/events, blocked crosses, offside flags and goal flags.

### Market, transfer and stakeholder models
Use player valuation, transfers, injuries, attendance and team/player performance summaries. Candidate targets include value growth, transfer success, post-transfer performance translation, stakeholder value and squad-risk profiles.

## Data quality and modelling caveats

- Do not use human-readable names as model features when IDs are available; names are mainly for display and audit.
- Build time-aware features only using data available before the prediction date. Do not let future season totals leak into match or early-season predictions.
- Betting odds are powerful benchmark features but can dominate models; decide whether the model should predict independently from odds or be calibrated against market expectations.
- `player_match_performance` and `match_events` can be extremely large; prefer aggregated features or materialized intermediate features for model training.
- Injury, transfer and market-value data must be aligned by date. For example, use market value available before the prediction date, not latest value after the event.
- When adding more leagues, validate that team naming, league codes, season labels and competition IDs are consistent before loading.
- For cross-league transferability questions, explicitly model source league, destination league, old-team context, new-team context and role similarity.
- For international tournament extensions, create separate `competitions` entries or a tournament table that can link national-team games back to club/player records without contaminating domestic league features.

## Recommended next metadata extensions

1. Add row counts per table after loading from Aiven using `SELECT COUNT(*)`.
2. Add source provenance for every CSV: source website/API, extraction date, seasons covered and known gaps.
3. Add units for every coordinate and market/transfer money field once confirmed from source documentation.
4. Add a feature registry for model-ready derived variables, especially rolling form, player availability, squad strength and cross-league adjustment factors.
5. Add international tournament tables before collecting Euros, Copa America, AFCON and World Cup data, with clear links to `players`, `competitions`, `seasons` and national teams.
