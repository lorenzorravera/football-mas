"""
Premier League CSV → PostgreSQL Migration Script (3NF)
=====================================================

Transforms a flat match-level CSV into a normalized relational schema:
  - leagues          (dimension)
  - seasons          (dimension, FK → leagues)
  - teams            (dimension)
  - referees         (dimension)
  - matches          (fact, FKs → seasons, teams, referees)
  - match_team_stats (fact, FKs → matches, teams; two rows per match)
  - points_adjustments (manual overrides for PL-imposed deductions)
  - league_table     (view for easy standings queries)

Usage:
  1. Set your Aiven PostgreSQL connection string in the CONFIG section below
  2. Place 'premier_league_merged.csv' in the same directory (or update CSV_PATH)
  3. Run: python migrate_to_postgres.py

The script is idempotent — it drops and recreates all objects on each run.
"""

import os
from pathlib import Path
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


# =============================================================================
# CONFIG
# =============================================================================

load_dotenv(Path(__file__).parent.parent / ".env")
CONNECTION_STRING = os.getenv("DATABASE_URI")
CSV_PATH = Path(__file__).parent / "premier_league_merged.csv"


# =============================================================================
# PHASE 1: DDL — Create Tables
# =============================================================================

DDL_STATEMENTS = """
-- Drop existing objects (reverse dependency order)
DROP VIEW  IF EXISTS league_table CASCADE;
DROP TABLE IF EXISTS points_adjustments CASCADE;
DROP TABLE IF EXISTS match_team_stats CASCADE;
DROP TABLE IF EXISTS matches CASCADE;
DROP TABLE IF EXISTS referees CASCADE;
DROP TABLE IF EXISTS teams CASCADE;
DROP TABLE IF EXISTS seasons CASCADE;
DROP TABLE IF EXISTS leagues CASCADE;

-- Leagues (e.g. E0 = Premier League)
CREATE TABLE leagues (
    league_id   SERIAL PRIMARY KEY,
    league_code VARCHAR(10) UNIQUE NOT NULL,  -- e.g. 'E0'
    league_name VARCHAR(100) NOT NULL          -- e.g. 'Premier League'
);

-- Teams
CREATE TABLE teams (
    team_id   SERIAL PRIMARY KEY,
    team_name VARCHAR(50) UNIQUE NOT NULL
);

-- Referees
CREATE TABLE referees (
    referee_id   SERIAL PRIMARY KEY,
    referee_name VARCHAR(100) UNIQUE NOT NULL
);

-- Seasons (one row per league-season combination)
CREATE TABLE seasons (
    season_id   SERIAL PRIMARY KEY,
    season      VARCHAR(9) NOT NULL,        -- e.g. '2021_2022'
    league_id   INT NOT NULL REFERENCES leagues(league_id),
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    UNIQUE (season, league_id)
);

-- Matches (one row per match)
CREATE TABLE matches (
    match_id      SERIAL PRIMARY KEY,
    season_id     INT  NOT NULL REFERENCES seasons(season_id),
    match_date    DATE NOT NULL,
    kickoff_time  TIME,
    home_team_id  INT  NOT NULL REFERENCES teams(team_id),
    away_team_id  INT  NOT NULL REFERENCES teams(team_id),
    referee_id    INT  NOT NULL REFERENCES referees(referee_id),
    ft_home_goals SMALLINT NOT NULL,
    ft_away_goals SMALLINT NOT NULL,
    ft_result     CHAR(1) NOT NULL,         -- H / D / A
    ht_home_goals SMALLINT NOT NULL,
    ht_away_goals SMALLINT NOT NULL,
    ht_result     CHAR(1) NOT NULL
);

-- Match Team Stats (two rows per match — one per team)
-- This is the key design: eliminates home/away branching in queries
CREATE TABLE match_team_stats (
    match_team_stat_id SERIAL PRIMARY KEY,
    match_id           INT      NOT NULL REFERENCES matches(match_id),
    team_id            INT      NOT NULL REFERENCES teams(team_id),
    opponent_id        INT      NOT NULL REFERENCES teams(team_id),
    is_home            BOOLEAN  NOT NULL,
    goals_scored       SMALLINT NOT NULL,
    goals_conceded     SMALLINT NOT NULL,
    shots              SMALLINT NOT NULL,
    shots_on_target    SMALLINT NOT NULL,
    fouls              SMALLINT NOT NULL,
    corners            SMALLINT NOT NULL,
    yellow_cards       SMALLINT NOT NULL,
    red_cards          SMALLINT NOT NULL,
    points             SMALLINT NOT NULL,     -- 3 = win, 1 = draw, 0 = loss
    UNIQUE (match_id, team_id)
);

-- Points Adjustments (for league-imposed deductions)
-- Applied at the season level, not per-match
CREATE TABLE points_adjustments (
    adjustment_id SERIAL PRIMARY KEY,
    team_id       INT NOT NULL REFERENCES teams(team_id),
    season_id     INT NOT NULL REFERENCES seasons(season_id),
    adjustment    INT NOT NULL,               -- negative for deductions
    reason        VARCHAR(255) NOT NULL
);

-- Indexes for common query patterns
CREATE INDEX idx_matches_season       ON matches(season_id);
CREATE INDEX idx_matches_date         ON matches(match_date);
CREATE INDEX idx_matches_home_team    ON matches(home_team_id);
CREATE INDEX idx_matches_away_team    ON matches(away_team_id);
CREATE INDEX idx_mts_match            ON match_team_stats(match_id);
CREATE INDEX idx_mts_team             ON match_team_stats(team_id);
CREATE INDEX idx_mts_team_match       ON match_team_stats(team_id, match_id);

-- League Table View
-- Computes standings with PL tiebreaker rules: points → GD → GF
-- Includes points adjustments (deductions) when they exist
CREATE VIEW league_table AS
SELECT
    s.season,
    t.team_name,
    COUNT(*)                                           AS played,
    SUM(CASE WHEN mts.goals_scored > mts.goals_conceded  THEN 1 ELSE 0 END) AS won,
    SUM(CASE WHEN mts.goals_scored = mts.goals_conceded  THEN 1 ELSE 0 END) AS drawn,
    SUM(CASE WHEN mts.goals_scored < mts.goals_conceded  THEN 1 ELSE 0 END) AS lost,
    SUM(mts.goals_scored)                              AS gf,
    SUM(mts.goals_conceded)                            AS ga,
    SUM(mts.goals_scored) - SUM(mts.goals_conceded)   AS gd,
    SUM(mts.points) + COALESCE(pa.total_adjustment, 0) AS points,
    COALESCE(pa.total_adjustment, 0)                   AS points_adjustment
FROM match_team_stats mts
JOIN matches m   ON mts.match_id = m.match_id
JOIN seasons s   ON m.season_id  = s.season_id
JOIN teams   t   ON mts.team_id  = t.team_id
LEFT JOIN (
    SELECT team_id, season_id, SUM(adjustment) AS total_adjustment
    FROM points_adjustments
    GROUP BY team_id, season_id
) pa ON pa.team_id = mts.team_id AND pa.season_id = m.season_id
GROUP BY s.season, t.team_name, pa.total_adjustment
ORDER BY s.season, points DESC, gd DESC, gf DESC;
"""


# =============================================================================
# PHASE 2: Transform — CSV → Normalized DataFrames
# =============================================================================

def load_and_transform(csv_path: str) -> dict:
    """
    Reads the flat CSV and produces normalized DataFrames ready for insertion.
    Returns a dict of DataFrames keyed by table name.
    """
    print(f"Reading CSV from {csv_path}...")
    df = pd.read_csv(csv_path)
    print(f"  → {len(df)} matches loaded across {df['season'].nunique()} seasons")

    # --- Parse dates properly (DD/MM/YYYY → datetime) ---
    df["match_date"] = pd.to_datetime(df["match_date"], format="%d/%m/%Y")

    # --- Leagues ---
    leagues_df = pd.DataFrame({
        "league_code": ["E0"],
        "league_name": ["Premier League"],
    })
    leagues_df.index += 1
    leagues_df.index.name = "league_id"
    league_id_for_e0 = 1  # Only one league for now

    # --- Teams ---
    all_teams = sorted(set(df["home_team"].unique()) | set(df["away_team"].unique()))
    teams_df = pd.DataFrame({"team_name": all_teams})
    teams_df.index += 1
    teams_df.index.name = "team_id"
    team_name_to_id = {name: idx for idx, name in enumerate(all_teams, start=1)}

    # --- Referees ---
    all_referees = sorted(df["match_referee"].unique())
    referees_df = pd.DataFrame({"referee_name": all_referees})
    referees_df.index += 1
    referees_df.index.name = "referee_id"
    referee_name_to_id = {name: idx for idx, name in enumerate(all_referees, start=1)}

    # --- Seasons (derive start/end from actual match dates) ---
    season_dates = df.groupby("season")["match_date"].agg(["min", "max"]).reset_index()
    season_dates.columns = ["season", "start_date", "end_date"]
    season_dates = season_dates.sort_values("start_date").reset_index(drop=True)
    season_dates.index += 1
    season_dates.index.name = "season_id"
    season_dates["league_id"] = league_id_for_e0
    season_to_id = {row["season"]: idx for idx, row in season_dates.iterrows()}

    print(f"  → {len(all_teams)} teams, {len(all_referees)} referees, {len(season_dates)} seasons")
    for idx, row in season_dates.iterrows():
        print(f"    Season {row['season']}: {row['start_date'].date()} → {row['end_date'].date()}")

    # --- Matches ---
    matches_rows = []
    for i, row in df.iterrows():
        matches_rows.append({
            "season_id":     season_to_id[row["season"]],
            "match_date":    row["match_date"].date(),
            "kickoff_time":  row["match_kickoff_time"],
            "home_team_id":  team_name_to_id[row["home_team"]],
            "away_team_id":  team_name_to_id[row["away_team"]],
            "referee_id":    referee_name_to_id[row["match_referee"]],
            "ft_home_goals": row["full_time_home_team_goals"],
            "ft_away_goals": row["full_time_away_team_goals"],
            "ft_result":     row["full_time_result"],
            "ht_home_goals": row["half_time_home_team_goals"],
            "ht_away_goals": row["half_time_away_team_goals"],
            "ht_result":     row["half_time_result"],
        })
    matches_df = pd.DataFrame(matches_rows)
    matches_df.index += 1
    matches_df.index.name = "match_id"

    # --- Match Team Stats (two rows per match) ---
    def compute_points(scored, conceded):
        if scored > conceded:
            return 3
        elif scored == conceded:
            return 1
        else:
            return 0

    mts_rows = []
    for match_id, (i, row) in enumerate(df.iterrows(), start=1):
        home_id = team_name_to_id[row["home_team"]]
        away_id = team_name_to_id[row["away_team"]]
        home_goals = row["full_time_home_team_goals"]
        away_goals = row["full_time_away_team_goals"]

        # Home team row
        mts_rows.append({
            "match_id":        match_id,
            "team_id":         home_id,
            "opponent_id":     away_id,
            "is_home":         True,
            "goals_scored":    home_goals,
            "goals_conceded":  away_goals,
            "shots":           row["home_team_shots"],
            "shots_on_target": row["home_team_shots_on_target"],
            "fouls":           row["home_team_fouls_committed"],
            "corners":         row["home_team_corners"],
            "yellow_cards":    row["home_team_yellow_cards"],
            "red_cards":       row["home_team_red_cards"],
            "points":          compute_points(home_goals, away_goals),
        })

        # Away team row
        mts_rows.append({
            "match_id":        match_id,
            "team_id":         away_id,
            "opponent_id":     home_id,
            "is_home":         False,
            "goals_scored":    away_goals,
            "goals_conceded":  home_goals,
            "shots":           row["away_team_shots"],
            "shots_on_target": row["away_team_shots_on_target"],
            "fouls":           row["away_team_fouls_committed"],
            "corners":         row["away_team_corners"],
            "yellow_cards":    row["away_team_yellow_cards"],
            "red_cards":       row["away_team_red_cards"],
            "points":          compute_points(away_goals, home_goals),
        })

    mts_df = pd.DataFrame(mts_rows)

    # --- Points Adjustments (known PL deductions in our data range) ---
    adjustments = [
        {
            "team_name": "Everton",
            "season": "2023_2024",
            "adjustment": -6,
            "reason": "PSR breach (2021-22 assessment period) — original -10, reduced to -6 on appeal",
        },
        {
            "team_name": "Everton",
            "season": "2023_2024",
            "adjustment": -2,
            "reason": "PSR breach (2022-23 assessment period) — second charge",
        },
        {
            "team_name": "Nott'm Forest",
            "season": "2023_2024",
            "adjustment": -4,
            "reason": "PSR breach (2022-23 assessment period) — exceeded £61m threshold by £34.5m",
        },
    ]
    adj_rows = []
    for adj in adjustments:
        adj_rows.append({
            "team_id":    team_name_to_id[adj["team_name"]],
            "season_id":  season_to_id[adj["season"]],
            "adjustment": adj["adjustment"],
            "reason":     adj["reason"],
        })
    adj_df = pd.DataFrame(adj_rows)

    return {
        "leagues":            leagues_df,
        "teams":              teams_df,
        "referees":           referees_df,
        "seasons":            season_dates,
        "matches":            matches_df,
        "match_team_stats":   mts_df,
        "points_adjustments": adj_df,
    }


# =============================================================================
# PHASE 3: Load — Insert into PostgreSQL
# =============================================================================

def load_to_postgres(conn, data: dict):
    """Inserts all DataFrames into PostgreSQL in FK-dependency order."""
    cur = conn.cursor()

    # --- Leagues ---
    print("Inserting leagues...")
    df = data["leagues"]
    execute_values(cur,
        "INSERT INTO leagues (league_id, league_code, league_name) VALUES %s",
        [(idx, row["league_code"], row["league_name"]) for idx, row in df.iterrows()]
    )

    # --- Teams ---
    print("Inserting teams...")
    df = data["teams"]
    execute_values(cur,
        "INSERT INTO teams (team_id, team_name) VALUES %s",
        [(idx, row["team_name"]) for idx, row in df.iterrows()]
    )

    # --- Referees ---
    print("Inserting referees...")
    df = data["referees"]
    execute_values(cur,
        "INSERT INTO referees (referee_id, referee_name) VALUES %s",
        [(idx, row["referee_name"]) for idx, row in df.iterrows()]
    )

    # --- Seasons ---
    print("Inserting seasons...")
    df = data["seasons"]
    execute_values(cur,
        "INSERT INTO seasons (season_id, season, league_id, start_date, end_date) VALUES %s",
        [(idx, row["season"], row["league_id"], row["start_date"].date(), row["end_date"].date())
         for idx, row in df.iterrows()]
    )

    # --- Matches ---
    print("Inserting matches...")
    df = data["matches"]
    execute_values(cur,
        """INSERT INTO matches (match_id, season_id, match_date, kickoff_time,
           home_team_id, away_team_id, referee_id,
           ft_home_goals, ft_away_goals, ft_result,
           ht_home_goals, ht_away_goals, ht_result)
           VALUES %s""",
        [(idx, row["season_id"], row["match_date"], row["kickoff_time"],
          row["home_team_id"], row["away_team_id"], row["referee_id"],
          row["ft_home_goals"], row["ft_away_goals"], row["ft_result"],
          row["ht_home_goals"], row["ht_away_goals"], row["ht_result"])
         for idx, row in df.iterrows()]
    )

    # --- Match Team Stats ---
    print("Inserting match_team_stats...")
    df = data["match_team_stats"]
    execute_values(cur,
        """INSERT INTO match_team_stats (match_id, team_id, opponent_id, is_home,
           goals_scored, goals_conceded, shots, shots_on_target,
           fouls, corners, yellow_cards, red_cards, points)
           VALUES %s""",
        [(row["match_id"], row["team_id"], row["opponent_id"], row["is_home"],
          row["goals_scored"], row["goals_conceded"], row["shots"], row["shots_on_target"],
          row["fouls"], row["corners"], row["yellow_cards"], row["red_cards"], row["points"])
         for _, row in df.iterrows()]
    )

    # --- Points Adjustments ---
    print("Inserting points_adjustments...")
    df = data["points_adjustments"]
    if not df.empty:
        execute_values(cur,
            """INSERT INTO points_adjustments (team_id, season_id, adjustment, reason)
               VALUES %s""",
            [(row["team_id"], row["season_id"], row["adjustment"], row["reason"])
             for _, row in df.iterrows()]
        )

    # --- Reset sequences to max ID + 1 ---
    for table, id_col in [
        ("leagues", "league_id"), ("teams", "team_id"),
        ("referees", "referee_id"), ("seasons", "season_id"),
        ("matches", "match_id"), ("match_team_stats", "match_team_stat_id"),
        ("points_adjustments", "adjustment_id"),
    ]:
        cur.execute(f"""
            SELECT setval(pg_get_serial_sequence('{table}', '{id_col}'),
                          COALESCE((SELECT MAX({id_col}) FROM {table}), 0) + 1, false)
        """)

    conn.commit()
    cur.close()
    print("  → All data inserted successfully.")


# =============================================================================
# PHASE 4: Validate — Sanity checks
# =============================================================================

def validate(conn):
    """Runs post-insertion checks to verify data integrity."""
    cur = conn.cursor()
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    # Row counts
    checks = {
        "leagues":            (1, "="),
        "teams":              (27, "="),
        "referees":           (None, ">0"),
        "seasons":            (5, "="),
        "matches":            (1759, "="),
        "match_team_stats":   (3518, "="),  # 2 × 1759
        "points_adjustments": (3, "="),
    }
    all_passed = True
    for table, (expected, op) in checks.items():
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        actual = cur.fetchone()[0]
        if op == "=" and actual != expected:
            print(f"  ✗ {table}: expected {expected}, got {actual}")
            all_passed = False
        elif op == ">0" and actual <= 0:
            print(f"  ✗ {table}: expected > 0, got {actual}")
            all_passed = False
        else:
            print(f"  ✓ {table}: {actual} rows")

    # Spot check: Brentford 2-0 Arsenal, first match of 2021-22
    print("\nSpot check — Brentford 2-0 Arsenal (13 Aug 2021):")
    cur.execute("""
        SELECT ht.team_name AS home, at.team_name AS away,
               m.ft_home_goals, m.ft_away_goals, m.ft_result
        FROM matches m
        JOIN teams ht ON m.home_team_id = ht.team_id
        JOIN teams at ON m.away_team_id = at.team_id
        WHERE m.match_date = '2021-08-13'
          AND ht.team_name = 'Brentford'
    """)
    row = cur.fetchone()
    if row and row[2] == 2 and row[3] == 0 and row[4] == "H":
        print(f"  ✓ {row[0]} {row[2]}-{row[3]} {row[1]} (result: {row[4]})")
    else:
        print(f"  ✗ Unexpected result: {row}")
        all_passed = False

    # Verify match_team_stats unpivot: same match, both team perspectives
    print("\nSpot check — match_team_stats for same match:")
    cur.execute("""
        SELECT t.team_name, mts.is_home, mts.goals_scored, mts.goals_conceded, mts.points
        FROM match_team_stats mts
        JOIN teams t ON mts.team_id = t.team_id
        WHERE mts.match_id = 1
        ORDER BY mts.is_home DESC
    """)
    rows = cur.fetchall()
    for r in rows:
        label = "HOME" if r[1] else "AWAY"
        print(f"  ✓ {r[0]} ({label}): scored {r[2]}, conceded {r[3]}, points {r[4]}")

    # League table check: 2021-22 full season, verify 20 teams with 38 games each
    print("\nLeague table check — 2021_2022 (should be 20 teams, 38 games each):")
    cur.execute("""
        SELECT team_name, played, points, gd
        FROM league_table
        WHERE season = '2021_2022'
        ORDER BY points DESC, gd DESC, gf DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    for r in rows:
        print(f"  {r[0]:20s} P:{r[1]}  Pts:{r[2]}  GD:{r[3]:+d}")

    cur.execute("""
        SELECT COUNT(*), MIN(played), MAX(played)
        FROM league_table WHERE season = '2021_2022'
    """)
    team_count, min_p, max_p = cur.fetchone()
    if team_count == 20 and min_p == 38 and max_p == 38:
        print(f"  ✓ {team_count} teams, all with {min_p} matches played")
    else:
        print(f"  ✗ Expected 20 teams with 38 games, got {team_count} teams ({min_p}-{max_p} games)")
        all_passed = False

    # Points deduction check: Everton 2023-24 should show -8 adjustment
    print("\nPoints adjustment check — Everton 2023_2024:")
    cur.execute("""
        SELECT team_name, points, points_adjustment
        FROM league_table
        WHERE season = '2023_2024' AND team_name = 'Everton'
    """)
    row = cur.fetchone()
    if row and row[2] == -8:
        print(f"  ✓ {row[0]}: {row[1]} pts (adjustment: {row[2]})")
    else:
        print(f"  ✗ Unexpected: {row}")
        all_passed = False

    # "As of date" query: demonstrate mid-season table
    print("\nSample query — League table as of 2024-01-01 (2023_2024 season):")
    cur.execute("""
        SELECT t.team_name,
               COUNT(*) AS played,
               SUM(mts.points) + COALESCE(pa.total_adjustment, 0) AS points,
               SUM(mts.goals_scored) - SUM(mts.goals_conceded) AS gd
        FROM match_team_stats mts
        JOIN matches m  ON mts.match_id = m.match_id
        JOIN seasons s  ON m.season_id  = s.season_id
        JOIN teams   t  ON mts.team_id  = t.team_id
        LEFT JOIN (
            SELECT team_id, season_id, SUM(adjustment) AS total_adjustment
            FROM points_adjustments GROUP BY team_id, season_id
        ) pa ON pa.team_id = mts.team_id AND pa.season_id = m.season_id
        WHERE s.season = '2023_2024'
          AND m.match_date <= '2024-01-01'
        GROUP BY t.team_name, pa.total_adjustment
        ORDER BY points DESC, gd DESC
        LIMIT 5
    """)
    for r in cur.fetchall():
        print(f"  {r[0]:20s} P:{r[1]}  Pts:{r[2]}  GD:{r[3]:+d}")

    cur.close()
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL CHECKS PASSED ✓")
    else:
        print("SOME CHECKS FAILED — review output above")
    print("=" * 60)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("Premier League → PostgreSQL Migration")
    print("=" * 60 + "\n")

    # Connect
    print("Connecting to PostgreSQL...")
    conn = psycopg2.connect(CONNECTION_STRING)
    print("  → Connected.\n")

    # Phase 1: Create schema
    print("Creating schema (DDL)...")
    cur = conn.cursor()
    cur.execute(DDL_STATEMENTS)
    conn.commit()
    cur.close()
    print("  → Schema created.\n")

    # Phase 2: Transform
    data = load_and_transform(CSV_PATH)
    print()

    # Phase 3: Load
    load_to_postgres(conn, data)

    # Phase 4: Validate
    validate(conn)

    conn.close()
    print("\nDone. Connection closed.")


if __name__ == "__main__":
    main()