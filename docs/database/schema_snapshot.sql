
-- Block 1 - Competitions

CREATE TABLE competitions (
    competition_id   SERIAL PRIMARY KEY,
    league_code      VARCHAR(10)  NOT NULL,
    league_name      VARCHAR(100) NOT NULL,
    country          VARCHAR(50)  NOT NULL,
    tier             SMALLINT     DEFAULT 1
);

INSERT INTO competitions (league_code, league_name, country, tier) VALUES
('ENG-PL', 'Premier League', 'England', 1);


-- Block 2 — Seasons

CREATE TABLE seasons (
    season_id       SERIAL PRIMARY KEY,
    competition_id  INT         NOT NULL REFERENCES competitions(competition_id),
    season          VARCHAR(9)  NOT NULL,
    start_date      DATE,
    end_date        DATE,
    UNIQUE (competition_id, season)
);

INSERT INTO seasons (competition_id, season, start_date, end_date) VALUES
(1, '2020-2021', '2020-09-12', '2021-05-23'),
(1, '2021-2022', '2021-08-13', '2022-05-22'),
(1, '2022-2023', '2022-08-05', '2023-05-28'),
(1, '2023-2024', '2023-08-11', '2024-05-19'),
(1, '2024-2025', '2024-08-16', '2025-05-25');


-- Block 3 — Players and Teams

CREATE TABLE players (
    player_id       INT          PRIMARY KEY,
    player_name     VARCHAR(100) NOT NULL,
    nationality     VARCHAR(50),
    birth_year      SMALLINT,
    height          SMALLINT,
    foot            VARCHAR(5)
);

CREATE TABLE teams (
    team_id         SERIAL PRIMARY KEY,
    team_name       VARCHAR(100) NOT NULL UNIQUE
);

INSERT INTO teams (team_name) VALUES
('Arsenal'),
('Aston Villa'),
('Bournemouth'),
('Brentford'),
('Brighton'),
('Burnley'),
('Chelsea'),
('Crystal Palace'),
('Everton'),
('Fulham'),
('Ipswich Town'),
('Leeds United'),
('Leicester City'),
('Liverpool'),
('Luton Town'),
('Manchester City'),
('Manchester United'),
('Newcastle United'),
('Norwich City'),
('Nottingham Forest'),
('Sheffield United'),
('Southampton'),
('Tottenham Hotspur'),
('Watford'),
('West Bromwich Albion'),
('West Ham United'),
('Wolves');


-- Block 4 — Matches

CREATE TABLE matches (
    game_id                 INT          PRIMARY KEY,
    season_id               INT          NOT NULL REFERENCES seasons(season_id),
    matchweek               SMALLINT,
    match_date              DATE,
    kickoff_time            TIME,
    home_team_id            INT          REFERENCES teams(team_id),
    away_team_id            INT          REFERENCES teams(team_id),
    home_score              SMALLINT,
    away_score              SMALLINT,
    ft_result               CHAR(1),
    ht_home_score           SMALLINT,
    ht_away_score           SMALLINT,
    ht_result               CHAR(1),
    home_formation          VARCHAR(10),
    away_formation          VARCHAR(10),
    venue                   VARCHAR(100),
    attendance_m            INT,
    referee                 VARCHAR(100),
    home_shots              SMALLINT,
    away_shots              SMALLINT,
    home_shots_on_target    SMALLINT,
    away_shots_on_target    SMALLINT,
    home_corners            SMALLINT,
    away_corners            SMALLINT,
    home_fouls              SMALLINT,
    away_fouls              SMALLINT,
    home_yellow_cards       SMALLINT,
    away_yellow_cards       SMALLINT,
    home_red_cards          SMALLINT,
    away_red_cards          SMALLINT,
    home_touches            SMALLINT,
    away_touches            SMALLINT,
    home_tackles            SMALLINT,
    away_tackles            SMALLINT,
    home_interceptions      SMALLINT,
    away_interceptions      SMALLINT,
    home_clearances         SMALLINT,
    away_clearances         SMALLINT,
    home_aerials_won        SMALLINT,
    away_aerials_won        SMALLINT,
    home_long_balls         SMALLINT,
    away_long_balls         SMALLINT,
    home_crosses            SMALLINT,
    away_crosses            SMALLINT,
    home_goal_kicks         SMALLINT,
    away_goal_kicks         SMALLINT,
    home_throw_ins          SMALLINT,
    away_throw_ins          SMALLINT,
    avg_home_odds           NUMERIC(5,2),
    avg_draw_odds           NUMERIC(5,2),
    avg_away_odds           NUMERIC(5,2),
    avg_over25_odds         NUMERIC(5,2),
    avg_under25_odds        NUMERIC(5,2)
);


-- Block 5 — Player Season Stats

CREATE TABLE player_season_stats (
    id                          SERIAL PRIMARY KEY,
    player_id                   INT          NOT NULL REFERENCES players(player_id),
    season_id                   INT          NOT NULL REFERENCES seasons(season_id),
    team_id                     INT          REFERENCES teams(team_id),
    age                         SMALLINT,
    matches_played_pss          SMALLINT,
    starts                      SMALLINT,
    minutes_pss                 INT,
    goals_pss                   SMALLINT,
    assists_pss                 SMALLINT,
    yellow_cards_pss            SMALLINT,
    red_cards_pss               SMALLINT,
    shots_pss                   SMALLINT,
    shots_on_target_pss         SMALLINT,
    xg_pss                      NUMERIC(6,3),
    xa_pss                      NUMERIC(6,3),
    npxg_pss                    NUMERIC(6,3),
    xgchain_pss                 NUMERIC(6,3),
    xgbuildup_pss               NUMERIC(6,3),
    key_passes_pss              SMALLINT,
    non_penalty_goals_pss       SMALLINT,
    fouls_committed             SMALLINT,
    fouls_drawn_pss             SMALLINT,
    interceptions_pss           SMALLINT,
    tackles_won                 SMALLINT,
    offsides_pss                SMALLINT,
    crosses                     SMALLINT,
    -- GK only (NULL for outfield players)
    saves_pss                   SMALLINT,
    clean_sheet                 SMALLINT,
    shots_on_tgt_against        SMALLINT,
    save_pct_pss                NUMERIC(5,2),
    penalties_faced             SMALLINT,
    penalty_saves               SMALLINT,
    UNIQUE (player_id, season_id, team_id)
);

CREATE INDEX ON player_season_stats (player_id);
CREATE INDEX ON player_season_stats (season_id);
CREATE INDEX ON player_season_stats (team_id);


-- Block 6 — Player Season Splits

CREATE TABLE player_season_splits (
    id                          SERIAL PRIMARY KEY,
    player_id                   INT         NOT NULL REFERENCES players(player_id),
    season_id                   INT         NOT NULL REFERENCES seasons(season_id),
    group_type                  VARCHAR(50) NOT NULL,
    group_name                  VARCHAR(50) NOT NULL,
    matches_played_pssp         SMALLINT,
    minutes_pssp                INT,
    goals_pssp                  SMALLINT,
    assists_pssp                SMALLINT,
    yellow_cards_pssp           SMALLINT,
    red_cards_pssp              SMALLINT,
    shots_pssp                  SMALLINT,
    xg_pssp                     NUMERIC(6,3),
    xa_pssp                     NUMERIC(6,3),
    npxg_pssp                   NUMERIC(6,3),
    xgchain_pssp                NUMERIC(6,3),
    xgbuildup_pssp              NUMERIC(6,3),
    key_passes_pssp             SMALLINT,
    non_penalty_goals_pssp      SMALLINT,
    UNIQUE (player_id, season_id, group_type, group_name)
);

CREATE INDEX ON player_season_splits (player_id);
CREATE INDEX ON player_season_splits (season_id);
CREATE INDEX ON player_season_splits (group_type);


-- Block 7 — Player Match Performance (Partitioned)

CREATE TABLE player_match_performance (
    player_id                           INT          NOT NULL,
    game_id                             INT          NOT NULL,
    season                              VARCHAR(9)   NOT NULL,
    league_code                         VARCHAR(10)  NOT NULL,
    position                            VARCHAR(10),
    minutes_played                      SMALLINT,
    match_goals                         SMALLINT,
    match_assists                       SMALLINT,
    match_shots                         SMALLINT,
    shots_on_target_pmp                 SMALLINT,
    xg_pmp                              NUMERIC(5,3),
    xa_pmp                              NUMERIC(5,3),
    npxg_pmp                            NUMERIC(5,3),
    xgchain_pmp                         NUMERIC(5,3),
    xgbuildup_pmp                       NUMERIC(5,3),
    key_passes_pmp                      SMALLINT,
    non_penalty_goals_pmp               SMALLINT,
    yellow_cards_pmp                    SMALLINT,
    red_cards_pmp                       SMALLINT,
    fouls                               SMALLINT,
    fouls_drawn_pmp                     SMALLINT,
    tackles_won                         SMALLINT,
    interceptions_pmp                   SMALLINT,
    crosses                             SMALLINT,
    offsides_pmp                        SMALLINT,
    own_goals                           SMALLINT,
    pens_made                           SMALLINT,
    pens_att                            SMALLINT,
    pens_won                            SMALLINT,
    pens_conceded                       SMALLINT,
    gk_saves                            SMALLINT,
    gk_goals_against                    SMALLINT,
    gk_save_pct                         NUMERIC(4,1),
    gk_shots_on_tgt_against             SMALLINT,
    PRIMARY KEY (player_id, game_id, season, league_code)
) PARTITION BY LIST (league_code);

CREATE TABLE player_match_performance_eng_pl
    PARTITION OF player_match_performance
    FOR VALUES IN ('ENG-PL')
    PARTITION BY LIST (season);

CREATE TABLE player_match_performance_eng_pl_2020_2021
    PARTITION OF player_match_performance_eng_pl
    FOR VALUES IN ('2020-2021');

CREATE TABLE player_match_performance_eng_pl_2021_2022
    PARTITION OF player_match_performance_eng_pl
    FOR VALUES IN ('2021-2022');

CREATE TABLE player_match_performance_eng_pl_2022_2023
    PARTITION OF player_match_performance_eng_pl
    FOR VALUES IN ('2022-2023');

CREATE TABLE player_match_performance_eng_pl_2023_2024
    PARTITION OF player_match_performance_eng_pl
    FOR VALUES IN ('2023-2024');

CREATE TABLE player_match_performance_eng_pl_2024_2025
    PARTITION OF player_match_performance_eng_pl
    FOR VALUES IN ('2024-2025');

CREATE INDEX ON player_match_performance (player_id);
CREATE INDEX ON player_match_performance (game_id);
CREATE INDEX ON player_match_performance (season);
CREATE INDEX ON player_match_performance (league_code);


-- Block 8 — Match Events (Partitioned)

CREATE TABLE match_events (
    event_id                BIGSERIAL,
    season                  VARCHAR(9)   NOT NULL,
    league_code             VARCHAR(10)  NOT NULL,
    game_id                 INT,
    period                  VARCHAR(20),
    minute                  INT,
    second                  NUMERIC(5,1),
    expanded_minute         INT,
    type                    VARCHAR(50),
    outcome_type            VARCHAR(50),
    team_id                 INT,
    team                    VARCHAR(100),
    player_id               INT,
    player_name             VARCHAR(100),
    x                       NUMERIC(5,2),
    y                       NUMERIC(5,2),
    end_x                   NUMERIC(5,2),
    end_y                   NUMERIC(5,2),
    goal_mouth_y            NUMERIC(5,2),
    goal_mouth_z            NUMERIC(5,2),
    blocked_x               NUMERIC(5,2),
    blocked_y               NUMERIC(5,2),
    is_touch                BOOLEAN,
    is_shot                 BOOLEAN,
    is_goal                 BOOLEAN,
    related_event_id        BIGINT,
    related_player_id       INT,
    pass_length             NUMERIC(5,2),
    pass_angle              NUMERIC(6,3),
    pass_end_x              NUMERIC(5,2),
    pass_end_y              NUMERIC(5,2),
    zone                    VARCHAR(20),
    player_caught_offside   BOOLEAN,
    blocked_cross           BOOLEAN,
    body_part_1             VARCHAR(30),
    body_part_2             VARCHAR(30),
    pass_type_1             VARCHAR(30),
    pass_type_2             VARCHAR(30),
    pass_type_3             VARCHAR(30),
    pass_type_4             VARCHAR(30),
    pass_type_5             VARCHAR(30),
    pass_quality_1          VARCHAR(30),
    pass_quality_2          VARCHAR(30),
    pass_quality_3          VARCHAR(30),
    pass_quality_4          VARCHAR(30),
    pass_quality_5          VARCHAR(30),
    pass_quality_6          VARCHAR(30),
    shot_zone_1             VARCHAR(30),
    shot_direction_1        VARCHAR(30),
    shot_qualifier_1        VARCHAR(30),
    shot_qualifier_2        VARCHAR(30),
    shot_qualifier_3        VARCHAR(30),
    shot_qualifier_4        VARCHAR(30),
    shot_qualifier_5        VARCHAR(30),
    keeper_save_type_1      VARCHAR(30),
    keeper_save_type_2      VARCHAR(30),
    keeper_save_type_3      VARCHAR(30),
    keeper_save_type_4      VARCHAR(30),
    foul_type_1             VARCHAR(30),
    situation               VARCHAR(50),
    shot_type               VARCHAR(50),
    player_assisted         VARCHAR(100),
    last_action             VARCHAR(50),
    PRIMARY KEY (event_id, season, league_code)
) PARTITION BY LIST (league_code);

-- ── Premier League ────────────────────────────────────────────────────────────
CREATE TABLE match_events_eng_pl
    PARTITION OF match_events
    FOR VALUES IN ('ENG-PL')
    PARTITION BY LIST (season);

CREATE TABLE match_events_eng_pl_2020_2021
    PARTITION OF match_events_eng_pl
    FOR VALUES IN ('2020-2021');

CREATE TABLE match_events_eng_pl_2021_2022
    PARTITION OF match_events_eng_pl
    FOR VALUES IN ('2021-2022');

CREATE TABLE match_events_eng_pl_2022_2023
    PARTITION OF match_events_eng_pl
    FOR VALUES IN ('2022-2023');

CREATE TABLE match_events_eng_pl_2023_2024
    PARTITION OF match_events_eng_pl
    FOR VALUES IN ('2023-2024');

CREATE TABLE match_events_eng_pl_2024_2025
    PARTITION OF match_events_eng_pl
    FOR VALUES IN ('2024-2025');

-- indexes
CREATE INDEX ON match_events (game_id);
CREATE INDEX ON match_events (player_id);
CREATE INDEX ON match_events (season);
CREATE INDEX ON match_events (league_code);
CREATE INDEX ON match_events (type);

CREATE INDEX ON match_events (player_id, game_id)
    WHERE is_shot = TRUE;

CREATE INDEX ON match_events (player_id, game_id)
    WHERE is_goal = TRUE;


-- Block 9 — Supporting Tables

-- ── Player Market Values ──────────────────────────────────────────────────────
CREATE TABLE player_market_values (
    player_id       INT             NOT NULL REFERENCES players(player_id),
    date_unix       BIGINT          NOT NULL,
    market_value    NUMERIC(12,2),
    PRIMARY KEY (player_id, date_unix)
);

CREATE INDEX ON player_market_values (player_id);

-- ── Player Transfers ──────────────────────────────────────────────────────────
CREATE TABLE player_transfers (
    transfer_id     SERIAL PRIMARY KEY,
    player_id       INT             REFERENCES players(player_id),
    season          VARCHAR(9),
    transfer_date   DATE,
    from_team       VARCHAR(100),
    to_team         VARCHAR(100),
    transfer_type   VARCHAR(50),
    transfer_fee    NUMERIC(12,2),
    UNIQUE (player_id, transfer_date, from_team, to_team)
);

CREATE INDEX ON player_transfers (player_id);
CREATE INDEX ON player_transfers (season);

-- ── Player Injury Spells ──────────────────────────────────────────────────────
CREATE TABLE player_injury_spells (
    spell_id            SERIAL PRIMARY KEY,
    player_id           INT             REFERENCES players(player_id),
    player_name         VARCHAR(100),
    season              VARCHAR(9),
    league_code         VARCHAR(10),
    team                VARCHAR(100),
    from_matchweek      SMALLINT,
    to_matchweek        SMALLINT,
    from_date           DATE,
    end_date            DATE,
    games_missed        SMALLINT,
    days_missed         SMALLINT,
    injury_reason       VARCHAR(200),
    UNIQUE (player_id, season, from_matchweek, league_code)
);

CREATE INDEX ON player_injury_spells (player_id);
CREATE INDEX ON player_injury_spells (season);
CREATE INDEX ON player_injury_spells (league_code);

-- ── Computed Metrics ──────────────────────────────────────────────────────────
CREATE TABLE computed_metrics (
    metric_id       UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type     VARCHAR(20)     NOT NULL,
    entity_id       INT             NOT NULL,
    metric_name     VARCHAR(100)    NOT NULL,
    metric_value    JSONB           NOT NULL,
    parameters      JSONB,
    computed_at     TIMESTAMPTZ     DEFAULT now(),
    source_query    TEXT,
    UNIQUE (entity_type, entity_id, metric_name, parameters)
);

CREATE INDEX ON computed_metrics (entity_type, entity_id);
CREATE INDEX ON computed_metrics (metric_name);


-- Block 10 — Materialized Views (Level 3)

-- ── vw_player_season_summary ──────────────────────────────────────────────────
CREATE MATERIALIZED VIEW vw_player_season_summary AS
SELECT
    p.player_id,
    p.player_name,
    p.nationality,
    p.birth_year,
    s.season,
    c.league_name,
    c.league_code,
    t.team_name                             AS team,
    pss.age,
    pss.matches_played_pss,
    pss.starts,
    pss.minutes_pss,
    pss.goals_pss,
    pss.assists_pss,
    pss.yellow_cards_pss,
    pss.red_cards_pss,
    pss.shots_pss,
    pss.shots_on_target_pss,
    pss.xg_pss,
    pss.xa_pss,
    pss.npxg_pss,
    pss.xgchain_pss,
    pss.xgbuildup_pss,
    pss.key_passes_pss,
    pss.non_penalty_goals_pss,
    pss.fouls_committed,
    pss.fouls_drawn_pss,
    pss.interceptions_pss,
    pss.tackles_won,
    pss.saves_pss,
    pss.clean_sheet,
    pss.save_pct_pss,
    mv.market_value
FROM player_season_stats pss
JOIN players        p   ON p.player_id      = pss.player_id
JOIN seasons        s   ON s.season_id      = pss.season_id
JOIN competitions   c   ON c.competition_id = s.competition_id
JOIN teams          t   ON t.team_id        = pss.team_id
LEFT JOIN LATERAL (
    SELECT market_value
    FROM player_market_values
    WHERE player_id = pss.player_id
    ORDER BY date_unix DESC
    LIMIT 1
) mv ON true
WITH DATA;

CREATE UNIQUE INDEX ON vw_player_season_summary (player_id, season, league_code, team);
CREATE INDEX ON vw_player_season_summary (player_id);
CREATE INDEX ON vw_player_season_summary (season);
CREATE INDEX ON vw_player_season_summary (league_code);
CREATE INDEX ON vw_player_season_summary (team);

-- ── vw_player_match_summary ───────────────────────────────────────────────────
CREATE MATERIALIZED VIEW vw_player_match_summary AS
SELECT
    pmp.player_id,
    p.player_name,
    pmp.season,
    pmp.league_code,
    pmp.game_id,
    m.matchweek,
    m.match_date,
    ht.team_name                            AS home_team,
    at.team_name                            AS away_team,
    m.home_score,
    m.away_score,
    m.ft_result,
    pmp.position,
    pmp.minutes_played,
    pmp.match_goals,
    pmp.match_assists,
    pmp.match_shots,
    pmp.shots_on_target_pmp,
    pmp.xg_pmp,
    pmp.xa_pmp,
    pmp.npxg_pmp,
    pmp.xgchain_pmp,
    pmp.xgbuildup_pmp,
    pmp.key_passes_pmp,
    pmp.yellow_cards_pmp,
    pmp.red_cards_pmp,
    pmp.fouls,
    pmp.fouls_drawn_pmp,
    pmp.tackles_won,
    pmp.interceptions_pmp,
    pmp.crosses,
    pmp.gk_saves,
    pmp.gk_goals_against,
    pmp.gk_save_pct
FROM player_match_performance pmp
JOIN players    p   ON p.player_id  = pmp.player_id
JOIN matches    m   ON m.game_id    = pmp.game_id
JOIN teams      ht  ON ht.team_id   = m.home_team_id
JOIN teams      at  ON at.team_id   = m.away_team_id
WITH DATA;

CREATE UNIQUE INDEX ON vw_player_match_summary (player_id, game_id, league_code);
CREATE INDEX ON vw_player_match_summary (player_id);
CREATE INDEX ON vw_player_match_summary (season);
CREATE INDEX ON vw_player_match_summary (league_code);
CREATE INDEX ON vw_player_match_summary (home_team);
CREATE INDEX ON vw_player_match_summary (away_team);

-- ── vw_player_shooting_profile ────────────────────────────────────────────────
CREATE MATERIALIZED VIEW vw_player_shooting_profile AS
SELECT
    me.player_id,
    me.player_name,
    me.season,
    me.league_code,
    me.game_id,
    me.minute,
    me.team,
    ht.team_name                            AS home_team,
    at.team_name                            AS away_team,
    me.x,
    me.y,
    me.end_x,
    me.end_y,
    me.is_goal,
    me.situation,
    me.shot_type,
    me.body_part_1                          AS body_part,
    me.shot_zone_1                          AS shot_zone,
    me.shot_direction_1                     AS shot_direction,
    me.player_assisted,
    me.last_action,
    me.goal_mouth_y,
    me.goal_mouth_z
FROM match_events me
JOIN matches    m   ON m.game_id    = me.game_id
                   AND m.season_id IN (
                       SELECT season_id FROM seasons s
                       JOIN competitions c ON c.competition_id = s.competition_id
                       WHERE c.league_code = me.league_code
                       AND s.season = me.season
                   )
JOIN teams      ht  ON ht.team_id   = m.home_team_id
JOIN teams      at  ON at.team_id   = m.away_team_id
WHERE me.is_shot = TRUE
WITH DATA;

CREATE UNIQUE INDEX ON vw_player_shooting_profile (player_id, game_id, minute, league_code);
CREATE INDEX ON vw_player_shooting_profile (player_id);
CREATE INDEX ON vw_player_shooting_profile (season);
CREATE INDEX ON vw_player_shooting_profile (league_code);
CREATE INDEX ON vw_player_shooting_profile (team);

-- ── vw_player_availability ────────────────────────────────────────────────────
CREATE MATERIALIZED VIEW vw_player_availability AS
SELECT
    p.player_id,
    p.player_name,
    pis.season,
    pis.league_code,
    pis.team,
    pis.from_matchweek,
    pis.to_matchweek,
    pis.from_date,
    pis.end_date,
    pis.games_missed,
    pis.days_missed,
    pis.injury_reason
FROM player_injury_spells pis
JOIN players p ON p.player_id = pis.player_id
WITH DATA;

CREATE UNIQUE INDEX ON vw_player_availability (player_id, season, league_code, from_matchweek);
CREATE INDEX ON vw_player_availability (player_id);
CREATE INDEX ON vw_player_availability (season);
CREATE INDEX ON vw_player_availability (league_code);
CREATE INDEX ON vw_player_availability (team);

-- Block 10A — Team Season Source Tables
-- These four tables support vw_team_season_summary.
-- All columns are prefixed so their names do not repeat existing table/view columns.

CREATE TABLE team_season_standings (
    team_id INT NOT NULL REFERENCES teams(team_id),
    season_id INT NOT NULL REFERENCES seasons(season_id),

    tss_team VARCHAR(100) NOT NULL,
    tss_season VARCHAR(9) NOT NULL,

    tss_rank INT,
    tss_matches_played INT,
    tss_wins INT,
    tss_draws INT,
    tss_losses INT,
    tss_goals_for INT,
    tss_goals_against INT,
    tss_goal_difference INT,
    tss_points INT,
    tss_attendance INT,
    tss_goalkeeper_name VARCHAR(100),
    tss_notes TEXT,
    tss_top_scorer_name VARCHAR(100),
    tss_top_scorer_goals INT,

    UNIQUE (tss_team, tss_season),
    UNIQUE (team_id, season_id)
);

CREATE INDEX idx_tss_team_id
ON team_season_standings (team_id);

CREATE INDEX idx_tss_season_id
ON team_season_standings (season_id);

CREATE INDEX idx_tss_team
ON team_season_standings (tss_team);

CREATE INDEX idx_tss_season
ON team_season_standings (tss_season);



CREATE TABLE team_season_home_away_standings (
    team_id INT NOT NULL REFERENCES teams(team_id),
    season_id INT NOT NULL REFERENCES seasons(season_id),

    tshas_team VARCHAR(100) NOT NULL,
    tshas_season VARCHAR(9) NOT NULL,

    tshas_rank INT,

    tshas_home_matches_played INT,
    tshas_home_wins INT,
    tshas_home_draws INT,
    tshas_home_losses INT,
    tshas_home_goals_for INT,
    tshas_home_goals_against INT,
    tshas_home_goal_difference INT,
    tshas_home_points INT,

    tshas_away_matches_played INT,
    tshas_away_wins INT,
    tshas_away_draws INT,
    tshas_away_losses INT,
    tshas_away_goals_for INT,
    tshas_away_goals_against INT,
    tshas_away_goal_difference INT,
    tshas_away_points INT,

    UNIQUE (tshas_team, tshas_season),
    UNIQUE (team_id, season_id)
);

CREATE INDEX idx_tshas_team_id
ON team_season_home_away_standings (team_id);

CREATE INDEX idx_tshas_season_id
ON team_season_home_away_standings (season_id);

CREATE INDEX idx_tshas_team
ON team_season_home_away_standings (tshas_team);

CREATE INDEX idx_tshas_season
ON team_season_home_away_standings (tshas_season);



CREATE TABLE team_season_stats_for (
    team_id INT NOT NULL REFERENCES teams(team_id),
    season_id INT NOT NULL REFERENCES seasons(season_id),

    tssf_team VARCHAR(100) NOT NULL,
    tssf_season VARCHAR(9) NOT NULL,

    tssf_players_used INT,
    tssf_average_age NUMERIC(5,2),
    tssf_possession_percentage NUMERIC(5,2),

    tssf_matches_played INT,
    tssf_starts INT,
    tssf_minutes INT,

    tssf_goals INT,
    tssf_assists INT,
    tssf_goals_assists INT,
    tssf_non_penalty_goals INT,
    tssf_penalty_goals INT,
    tssf_penalties_attempted INT,

    tssf_yellow_cards INT,
    tssf_red_cards INT,

    tssf_goals_per90 NUMERIC(6,3),
    tssf_assists_per90 NUMERIC(6,3),
    tssf_goals_assists_per90 NUMERIC(6,3),
    tssf_non_penalty_goals_per90 NUMERIC(6,3),
    tssf_non_penalty_goals_assists_per90 NUMERIC(6,3),

    tssf_goals_allowed INT,
    tssf_goals_allowed_per90 NUMERIC(6,3),
    tssf_shots_on_target_against INT,
    tssf_saves INT,
    tssf_save_percentage NUMERIC(6,3),

    tssf_wins INT,
    tssf_draws INT,
    tssf_losses INT,

    tssf_clean_sheets INT,
    tssf_clean_sheet_percentage NUMERIC(6,3),

    tssf_penalties_faced INT,
    tssf_penalty_goals_allowed INT,
    tssf_penalty_saves INT,
    tssf_penalty_misses INT,
    tssf_penalty_save_percentage NUMERIC(6,3),

    tssf_nineties NUMERIC(6,2),

    tssf_shots INT,
    tssf_shots_on_target INT,
    tssf_shots_on_target_percentage NUMERIC(6,3),
    tssf_shots_per90 NUMERIC(6,3),
    tssf_shots_on_target_per90 NUMERIC(6,3),
    tssf_goals_per_shot NUMERIC(6,3),
    tssf_goals_per_shot_on_target NUMERIC(6,3),

    tssf_standard_penalty_goals INT,
    tssf_second_yellow_red_cards INT,

    tssf_fouls_committed INT,
    tssf_fouls_drawn INT,
    tssf_offsides INT,
    tssf_crosses INT,
    tssf_interceptions INT,
    tssf_tackles_won INT,

    tssf_penalties_won INT,
    tssf_penalties_conceded INT,
    tssf_own_goals INT,

    UNIQUE (tssf_team, tssf_season),
    UNIQUE (team_id, season_id)
);

CREATE INDEX idx_tssf_team_id
ON team_season_stats_for (team_id);

CREATE INDEX idx_tssf_season_id
ON team_season_stats_for (season_id);

CREATE INDEX idx_tssf_team
ON team_season_stats_for (tssf_team);

CREATE INDEX idx_tssf_season
ON team_season_stats_for (tssf_season);



CREATE TABLE team_season_stats_against (
    team_id INT NOT NULL REFERENCES teams(team_id),
    season_id INT NOT NULL REFERENCES seasons(season_id),

    tssa_team VARCHAR(100) NOT NULL,
    tssa_season VARCHAR(9) NOT NULL,

    tssa_players_used INT,
    tssa_average_age NUMERIC(5,2),
    tssa_possession_percentage NUMERIC(5,2),

    tssa_matches_played INT,
    tssa_starts INT,
    tssa_minutes INT,

    tssa_goals INT,
    tssa_assists INT,
    tssa_goals_assists INT,
    tssa_non_penalty_goals INT,
    tssa_penalty_goals INT,
    tssa_penalties_attempted INT,

    tssa_yellow_cards INT,
    tssa_red_cards INT,

    tssa_goals_per90 NUMERIC(6,3),
    tssa_assists_per90 NUMERIC(6,3),
    tssa_goals_assists_per90 NUMERIC(6,3),
    tssa_non_penalty_goals_per90 NUMERIC(6,3),
    tssa_non_penalty_goals_assists_per90 NUMERIC(6,3),

    tssa_goals_allowed INT,
    tssa_goals_allowed_per90 NUMERIC(6,3),
    tssa_shots_on_target_against INT,
    tssa_saves INT,
    tssa_save_percentage NUMERIC(6,3),

    tssa_wins INT,
    tssa_draws INT,
    tssa_losses INT,

    tssa_clean_sheets INT,
    tssa_clean_sheet_percentage NUMERIC(6,3),

    tssa_penalties_faced INT,
    tssa_penalty_goals_allowed INT,
    tssa_penalty_saves INT,
    tssa_penalty_misses INT,
    tssa_penalty_save_percentage NUMERIC(6,3),

    tssa_nineties NUMERIC(6,2),

    tssa_shots INT,
    tssa_shots_on_target INT,
    tssa_shots_on_target_percentage NUMERIC(6,3),
    tssa_shots_per90 NUMERIC(6,3),
    tssa_shots_on_target_per90 NUMERIC(6,3),
    tssa_goals_per_shot NUMERIC(6,3),
    tssa_goals_per_shot_on_target NUMERIC(6,3),

    tssa_standard_penalty_goals INT,
    tssa_second_yellow_red_cards INT,

    tssa_fouls_committed INT,
    tssa_fouls_drawn INT,
    tssa_offsides INT,
    tssa_crosses INT,
    tssa_interceptions INT,
    tssa_tackles_won INT,

    tssa_penalties_won INT,
    tssa_penalties_conceded INT,
    tssa_own_goals INT,

    UNIQUE (tssa_team, tssa_season),
    UNIQUE (team_id, season_id)
);

CREATE INDEX idx_tssa_team_id
ON team_season_stats_against (team_id);

CREATE INDEX idx_tssa_season_id
ON team_season_stats_against (season_id);

CREATE INDEX idx_tssa_team
ON team_season_stats_against (tssa_team);

CREATE INDEX idx_tssa_season
ON team_season_stats_against (tssa_season);
-- ── vw_team_season_summary ────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW vw_team_season_summary AS
SELECT
    t.team_id                                      AS vwtss_team_id,
    t.team_name                                    AS vwtss_team_name,
    s.season_id                                    AS vwtss_season_id,
    s.season                                       AS vwtss_season,
    c.competition_id                               AS vwtss_competition_id,
    c.league_name                                  AS vwtss_league_name,
    c.league_code                                  AS vwtss_league_code,

    st.tss_rank                                    AS vwtss_rank,
    st.tss_matches_played                          AS vwtss_matches_played,
    st.tss_wins                                    AS vwtss_wins,
    st.tss_draws                                   AS vwtss_draws,
    st.tss_losses                                  AS vwtss_losses,
    st.tss_points                                  AS vwtss_points,
    st.tss_goals_for                               AS vwtss_goals_for,
    st.tss_goals_against                           AS vwtss_goals_against,
    st.tss_goal_difference                         AS vwtss_goal_difference,
    st.tss_attendance                              AS vwtss_attendance,
    st.tss_goalkeeper_name                         AS vwtss_goalkeeper_name,
    st.tss_notes                                   AS vwtss_notes,
    st.tss_top_scorer_name                         AS vwtss_top_scorer_name,
    st.tss_top_scorer_goals                        AS vwtss_top_scorer_goals,

    ha.tshas_home_matches_played                   AS vwtss_home_matches_played,
    ha.tshas_home_wins                             AS vwtss_home_wins,
    ha.tshas_home_draws                            AS vwtss_home_draws,
    ha.tshas_home_losses                           AS vwtss_home_losses,
    ha.tshas_home_goals_for                        AS vwtss_home_goals_for,
    ha.tshas_home_goals_against                    AS vwtss_home_goals_against,
    ha.tshas_home_goal_difference                  AS vwtss_home_goal_difference,
    ha.tshas_home_points                           AS vwtss_home_points,

    ha.tshas_away_matches_played                   AS vwtss_away_matches_played,
    ha.tshas_away_wins                             AS vwtss_away_wins,
    ha.tshas_away_draws                            AS vwtss_away_draws,
    ha.tshas_away_losses                           AS vwtss_away_losses,
    ha.tshas_away_goals_for                        AS vwtss_away_goals_for,
    ha.tshas_away_goals_against                    AS vwtss_away_goals_against,
    ha.tshas_away_goal_difference                  AS vwtss_away_goal_difference,
    ha.tshas_away_points                           AS vwtss_away_points,

    sf.tssf_players_used                           AS vwtss_players_used_for,
    sf.tssf_average_age                            AS vwtss_average_age_for,
    sf.tssf_possession_percentage                  AS vwtss_possession_percentage_for,
    sf.tssf_matches_played                         AS vwtss_matches_played_for,
    sf.tssf_starts                                 AS vwtss_starts_for,
    sf.tssf_minutes                                AS vwtss_minutes_for,
    sf.tssf_goals                                  AS vwtss_goals_stat_for,
    sf.tssf_assists                                AS vwtss_assists_for,
    sf.tssf_goals_assists                          AS vwtss_goals_assists_for,
    sf.tssf_non_penalty_goals                      AS vwtss_non_penalty_goals_for,
    sf.tssf_penalty_goals                          AS vwtss_penalty_goals_for,
    sf.tssf_penalties_attempted                    AS vwtss_penalties_attempted_for,
    sf.tssf_yellow_cards                           AS vwtss_yellow_cards_for,
    sf.tssf_red_cards                              AS vwtss_red_cards_for,
    sf.tssf_goals_per90                            AS vwtss_goals_per90_for,
    sf.tssf_assists_per90                          AS vwtss_assists_per90_for,
    sf.tssf_goals_assists_per90                    AS vwtss_goals_assists_per90_for,
    sf.tssf_non_penalty_goals_per90                AS vwtss_non_penalty_goals_per90_for,
    sf.tssf_non_penalty_goals_assists_per90        AS vwtss_non_penalty_goals_assists_per90_for,
    sf.tssf_goals_allowed                          AS vwtss_goals_allowed_for,
    sf.tssf_goals_allowed_per90                    AS vwtss_goals_allowed_per90_for,
    sf.tssf_shots_on_target_against                AS vwtss_shots_on_target_against_for,
    sf.tssf_saves                                  AS vwtss_saves_for,
    sf.tssf_save_percentage                        AS vwtss_save_percentage_for,
    sf.tssf_wins                                   AS vwtss_wins_for,
    sf.tssf_draws                                  AS vwtss_draws_for,
    sf.tssf_losses                                 AS vwtss_losses_for,
    sf.tssf_clean_sheets                           AS vwtss_clean_sheets_for,
    sf.tssf_clean_sheet_percentage                 AS vwtss_clean_sheet_percentage_for,
    sf.tssf_penalties_faced                        AS vwtss_penalties_faced_for,
    sf.tssf_penalty_goals_allowed                  AS vwtss_penalty_goals_allowed_for,
    sf.tssf_penalty_saves                          AS vwtss_penalty_saves_for,
    sf.tssf_penalty_misses                         AS vwtss_penalty_misses_for,
    sf.tssf_penalty_save_percentage                AS vwtss_penalty_save_percentage_for,
    sf.tssf_nineties                               AS vwtss_nineties_for,
    sf.tssf_shots                                  AS vwtss_shots_for,
    sf.tssf_shots_on_target                        AS vwtss_shots_on_target_for,
    sf.tssf_shots_on_target_percentage             AS vwtss_shots_on_target_percentage_for,
    sf.tssf_shots_per90                            AS vwtss_shots_per90_for,
    sf.tssf_shots_on_target_per90                  AS vwtss_shots_on_target_per90_for,
    sf.tssf_goals_per_shot                         AS vwtss_goals_per_shot_for,
    sf.tssf_goals_per_shot_on_target               AS vwtss_goals_per_shot_on_target_for,
    sf.tssf_standard_penalty_goals                 AS vwtss_standard_penalty_goals_for,
    sf.tssf_second_yellow_red_cards                AS vwtss_second_yellow_red_cards_for,
    sf.tssf_fouls_committed                        AS vwtss_fouls_committed_for,
    sf.tssf_fouls_drawn                            AS vwtss_fouls_drawn_for,
    sf.tssf_offsides                               AS vwtss_offsides_for,
    sf.tssf_crosses                                AS vwtss_crosses_for,
    sf.tssf_interceptions                          AS vwtss_interceptions_for,
    sf.tssf_tackles_won                            AS vwtss_tackles_won_for,
    sf.tssf_penalties_won                          AS vwtss_penalties_won_for,
    sf.tssf_penalties_conceded                     AS vwtss_penalties_conceded_for,
    sf.tssf_own_goals                              AS vwtss_own_goals_for,

    sa.tssa_players_used                           AS vwtss_players_used_against,
    sa.tssa_average_age                            AS vwtss_average_age_against,
    sa.tssa_possession_percentage                  AS vwtss_possession_percentage_against,
    sa.tssa_matches_played                         AS vwtss_matches_played_against,
    sa.tssa_starts                                 AS vwtss_starts_against,
    sa.tssa_minutes                                AS vwtss_minutes_against,
    sa.tssa_goals                                  AS vwtss_goals_stat_against,
    sa.tssa_assists                                AS vwtss_assists_against,
    sa.tssa_goals_assists                          AS vwtss_goals_assists_against,
    sa.tssa_non_penalty_goals                      AS vwtss_non_penalty_goals_against,
    sa.tssa_penalty_goals                          AS vwtss_penalty_goals_against,
    sa.tssa_penalties_attempted                    AS vwtss_penalties_attempted_against,
    sa.tssa_yellow_cards                           AS vwtss_yellow_cards_against,
    sa.tssa_red_cards                              AS vwtss_red_cards_against,
    sa.tssa_goals_per90                            AS vwtss_goals_per90_against,
    sa.tssa_assists_per90                          AS vwtss_assists_per90_against,
    sa.tssa_goals_assists_per90                    AS vwtss_goals_assists_per90_against,
    sa.tssa_non_penalty_goals_per90                AS vwtss_non_penalty_goals_per90_against,
    sa.tssa_non_penalty_goals_assists_per90        AS vwtss_non_penalty_goals_assists_per90_against,
    sa.tssa_goals_allowed                          AS vwtss_goals_allowed_against,
    sa.tssa_goals_allowed_per90                    AS vwtss_goals_allowed_per90_against,
    sa.tssa_shots_on_target_against                AS vwtss_shots_on_target_against_stat,
    sa.tssa_saves                                  AS vwtss_saves_against,
    sa.tssa_save_percentage                        AS vwtss_save_percentage_against,
    sa.tssa_wins                                   AS vwtss_wins_against,
    sa.tssa_draws                                  AS vwtss_draws_against,
    sa.tssa_losses                                 AS vwtss_losses_against,
    sa.tssa_clean_sheets                           AS vwtss_clean_sheets_against,
    sa.tssa_clean_sheet_percentage                 AS vwtss_clean_sheet_percentage_against,
    sa.tssa_penalties_faced                        AS vwtss_penalties_faced_against,
    sa.tssa_penalty_goals_allowed                  AS vwtss_penalty_goals_allowed_against,
    sa.tssa_penalty_saves                          AS vwtss_penalty_saves_against,
    sa.tssa_penalty_misses                         AS vwtss_penalty_misses_against,
    sa.tssa_penalty_save_percentage                AS vwtss_penalty_save_percentage_against,
    sa.tssa_nineties                               AS vwtss_nineties_against,
    sa.tssa_shots                                  AS vwtss_shots_against,
    sa.tssa_shots_on_target                        AS vwtss_shots_on_target_against,
    sa.tssa_shots_on_target_percentage             AS vwtss_shots_on_target_percentage_against,
    sa.tssa_shots_per90                            AS vwtss_shots_per90_against,
    sa.tssa_shots_on_target_per90                  AS vwtss_shots_on_target_per90_against,
    sa.tssa_goals_per_shot                         AS vwtss_goals_per_shot_against,
    sa.tssa_goals_per_shot_on_target               AS vwtss_goals_per_shot_on_target_against,
    sa.tssa_standard_penalty_goals                 AS vwtss_standard_penalty_goals_against,
    sa.tssa_second_yellow_red_cards                AS vwtss_second_yellow_red_cards_against,
    sa.tssa_fouls_committed                        AS vwtss_fouls_committed_against,
    sa.tssa_fouls_drawn                            AS vwtss_fouls_drawn_against,
    sa.tssa_offsides                               AS vwtss_offsides_against,
    sa.tssa_crosses                                AS vwtss_crosses_against,
    sa.tssa_interceptions                          AS vwtss_interceptions_against,
    sa.tssa_tackles_won                            AS vwtss_tackles_won_against,
    sa.tssa_penalties_won                          AS vwtss_penalties_won_against,
    sa.tssa_penalties_conceded                     AS vwtss_penalties_conceded_against,
    sa.tssa_own_goals                              AS vwtss_own_goals_against

FROM team_season_standings st
JOIN teams t
    ON t.team_id = st.team_id
JOIN seasons s
    ON s.season_id = st.season_id
JOIN competitions c
    ON c.competition_id = s.competition_id

LEFT JOIN team_season_home_away_standings ha
    ON ha.team_id = st.team_id
    AND ha.season_id = st.season_id

LEFT JOIN team_season_stats_for sf
    ON sf.team_id = st.team_id
    AND sf.season_id = st.season_id

LEFT JOIN team_season_stats_against sa
    ON sa.team_id = st.team_id
    AND sa.season_id = st.season_id

WITH DATA;

CREATE UNIQUE INDEX idx_vwtss_team_season_league
ON vw_team_season_summary (vwtss_team_id, vwtss_season_id, vwtss_competition_id);

CREATE INDEX idx_vwtss_season
ON vw_team_season_summary (vwtss_season);

CREATE INDEX idx_vwtss_league_code
ON vw_team_season_summary (vwtss_league_code);

CREATE INDEX idx_vwtss_team_name
ON vw_team_season_summary (vwtss_team_name);

CREATE INDEX idx_vwtss_points
ON vw_team_season_summary (vwtss_points);


-- ── vw_match_summary ─────────────────────────────────────────────────────────
CREATE MATERIALIZED VIEW vw_match_summary AS
SELECT
    m.game_id,
    s.season,
    c.league_name,
    c.league_code,
    m.matchweek,
    m.match_date,
    m.kickoff_time,
    ht.team_name                            AS home_team,
    at.team_name                            AS away_team,
    m.home_score,
    m.away_score,
    m.ft_result,
    m.ht_home_score,
    m.ht_away_score,
    m.ht_result,
    m.home_formation,
    m.away_formation,
    m.home_shots,
    m.away_shots,
    m.home_shots_on_target,
    m.away_shots_on_target,
    m.home_corners,
    m.away_corners,
    m.home_fouls,
    m.away_fouls,
    m.home_yellow_cards,
    m.away_yellow_cards,
    m.home_red_cards,
    m.away_red_cards,
    m.home_touches,
    m.away_touches,
    m.home_tackles,
    m.away_tackles,
    m.home_interceptions,
    m.away_interceptions,
    m.home_clearances,
    m.away_clearances,
    m.home_aerials_won,
    m.away_aerials_won,
    m.home_long_balls,
    m.away_long_balls,
    m.attendance_m,
    m.venue,
    m.referee,
    m.avg_home_odds,
    m.avg_draw_odds,
    m.avg_away_odds,
    m.avg_over25_odds,
    m.avg_under25_odds
FROM matches m
JOIN seasons        s   ON s.season_id      = m.season_id
JOIN competitions   c   ON c.competition_id = s.competition_id
JOIN teams          ht  ON ht.team_id       = m.home_team_id
JOIN teams          at  ON at.team_id       = m.away_team_id
WITH DATA;

CREATE UNIQUE INDEX ON vw_match_summary (game_id);
CREATE INDEX ON vw_match_summary (season);
CREATE INDEX ON vw_match_summary (league_code);
CREATE INDEX ON vw_match_summary (home_team);
CREATE INDEX ON vw_match_summary (away_team);
CREATE INDEX ON vw_match_summary (match_date);

-- Block 11 — Weekly Refresh via pg_cron removed because the target Aiven service does not currently expose the cron schema.
