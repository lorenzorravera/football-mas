"""
International Football Results → PostgreSQL Migration
====================================================

Loads the last N years (default 10) of the Kaggle dataset
``martj42/international-football-results-from-1872-to-2017`` into the Aiven
Postgres DB as a set of dedicated ``intl_*`` tables.

Design goals (per the project metadata's "future extension" note):
  - National-team data lives in its OWN dimension tables so it never
    contaminates the existing club `teams` / `players` / `matches` schema.
  - Additive & self-contained: this script only DROPs and CREATEs `intl_*`
    objects. It NEVER touches the club tables. Safe to run against the live DB.
  - Idempotent: re-running drops and rebuilds the `intl_*` tables cleanly.

Tables created:
  intl_tournaments   (dimension: 'FIFA World Cup', 'Friendly', 'UEFA Euro', ...)
  intl_teams         (dimension: national teams, e.g. 'Brazil', 'Germany')
  intl_matches       (fact: one row per match)
  intl_goalscorers   (fact: one row per goal; from goalscorers.csv)
  intl_shootouts     (fact: one row per match decided on penalties)

Usage:
  # 1. Install + authenticate Kaggle (one-time):
  #    pip install kagglehub
  #    (place kaggle.json in ~/.kaggle/ or set KAGGLE_USERNAME / KAGGLE_KEY)
  # 2. Ensure DATABASE_URI is set (reads Ethan/agent_v4/.env by default).
  # 3. Run:
  #    python Ethan/data_prep/migrate_international_to_postgres.py
  #
  # Options:
  #    --years 10          number of trailing years to load (default 10)
  #    --path /some/dir    use already-downloaded CSVs instead of kagglehub
  #    --dry-run           transform + print summary, do NOT write to the DB
"""

from __future__ import annotations

import argparse
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


# =============================================================================
# CONFIG
# =============================================================================

# Reuse the same .env the agent uses so we hit the same Aiven instance.
# override=True so the real URI in .env wins over any placeholder already
# exported in the shell (e.g. DATABASE_URI='postgres://...').
load_dotenv(Path(__file__).resolve().parents[1] / "agent_v4" / ".env", override=True)

KAGGLE_SLUG = "martj42/international-football-results-from-1872-to-2017"


# =============================================================================
# PHASE 1: DDL — create ONLY the intl_* objects (club schema is untouched)
# =============================================================================

DDL_STATEMENTS = """
-- Drop existing intl_* objects only (reverse dependency order).
DROP TABLE IF EXISTS intl_shootouts   CASCADE;
DROP TABLE IF EXISTS intl_goalscorers CASCADE;
DROP TABLE IF EXISTS intl_matches     CASCADE;
DROP TABLE IF EXISTS intl_teams       CASCADE;
DROP TABLE IF EXISTS intl_tournaments CASCADE;

-- Tournaments (competition dimension: 'FIFA World Cup', 'Friendly', ...)
CREATE TABLE intl_tournaments (
    intl_tournament_id SERIAL PRIMARY KEY,
    tournament_name    VARCHAR(120) UNIQUE NOT NULL
);

-- National teams
CREATE TABLE intl_teams (
    intl_team_id SERIAL PRIMARY KEY,
    team_name    VARCHAR(80) UNIQUE NOT NULL
);

-- Matches (one row per international fixture)
CREATE TABLE intl_matches (
    intl_match_id      SERIAL PRIMARY KEY,
    match_date         DATE NOT NULL,
    home_team_id       INT  NOT NULL REFERENCES intl_teams(intl_team_id),
    away_team_id       INT  NOT NULL REFERENCES intl_teams(intl_team_id),
    home_score         SMALLINT NOT NULL,
    away_score         SMALLINT NOT NULL,
    ft_result          CHAR(1)  NOT NULL,   -- H / D / A (from regulation score)
    intl_tournament_id INT  NOT NULL REFERENCES intl_tournaments(intl_tournament_id),
    city               VARCHAR(120),
    country            VARCHAR(80),         -- host country
    neutral            BOOLEAN  NOT NULL,   -- was it played on neutral ground?
    UNIQUE (match_date, home_team_id, away_team_id)
);

-- Goalscorers (one row per goal). Nullable minute (some rows lack it).
CREATE TABLE intl_goalscorers (
    intl_goal_id    SERIAL PRIMARY KEY,
    intl_match_id   INT NOT NULL REFERENCES intl_matches(intl_match_id),
    scoring_team_id INT NOT NULL REFERENCES intl_teams(intl_team_id),
    scorer          VARCHAR(120),
    minute          SMALLINT,
    own_goal        BOOLEAN NOT NULL DEFAULT FALSE,
    penalty         BOOLEAN NOT NULL DEFAULT FALSE
);

-- Shootouts (one row per match decided on penalties)
CREATE TABLE intl_shootouts (
    intl_match_id        INT PRIMARY KEY REFERENCES intl_matches(intl_match_id),
    winner_team_id       INT NOT NULL REFERENCES intl_teams(intl_team_id),
    first_shooter_team_id INT REFERENCES intl_teams(intl_team_id)
);

-- Indexes for common query patterns
CREATE INDEX idx_intl_matches_date        ON intl_matches(match_date);
CREATE INDEX idx_intl_matches_home        ON intl_matches(home_team_id);
CREATE INDEX idx_intl_matches_away        ON intl_matches(away_team_id);
CREATE INDEX idx_intl_matches_tournament  ON intl_matches(intl_tournament_id);
CREATE INDEX idx_intl_goals_match         ON intl_goalscorers(intl_match_id);
CREATE INDEX idx_intl_goals_team          ON intl_goalscorers(scoring_team_id);
"""


# =============================================================================
# PHASE 2: Transform — CSVs → normalized DataFrames (filtered to last N years)
# =============================================================================

def _read_csvs(data_dir: Path) -> dict:
    """Read the three source CSVs. goalscorers/shootouts are optional."""
    results_path = data_dir / "results.csv"
    if not results_path.exists():
        raise FileNotFoundError(f"results.csv not found in {data_dir}")
    out = {"results": pd.read_csv(results_path, parse_dates=["date"])}

    for name in ("goalscorers", "shootouts"):
        p = data_dir / f"{name}.csv"
        out[name] = pd.read_csv(p, parse_dates=["date"]) if p.exists() else None
        if out[name] is None:
            print(f"  ! {name}.csv not found — skipping that table")
    return out


def load_and_transform(data_dir: Path, cutoff: date) -> dict:
    """Read CSVs, filter to date >= cutoff, and build normalized DataFrames."""
    print(f"Reading CSVs from {data_dir} ...")
    raw = _read_csvs(data_dir)

    results = raw["results"]
    print(f"  → {len(results):,} total matches in results.csv "
          f"({results['date'].min().date()} → {results['date'].max().date()})")

    # --- Filter matches to the trailing window ---
    results = results[results["date"].dt.date >= cutoff].copy()
    print(f"  → {len(results):,} matches on/after {cutoff}")

    # Drop unplayed/scheduled fixtures (the CSV includes future dates with no
    # score yet). We only load matches that have a final result.
    unplayed = results[["home_score", "away_score"]].isna().any(axis=1).sum()
    if unplayed:
        print(f"  → dropping {unplayed:,} unplayed/scheduled fixtures (no score)")
        results = results.dropna(subset=["home_score", "away_score"])
    results = results.sort_values("date").reset_index(drop=True)
    print(f"  → {len(results):,} played matches to load")
    if results.empty:
        raise RuntimeError("No played matches after the cutoff date — nothing to load.")

    # Match key used to join goalscorers/shootouts back to matches.
    # NB: no leading underscore — itertuples() mangles such column names.
    def key(df):
        return (df["date"].dt.strftime("%Y-%m-%d") + "|"
                + df["home_team"] + "|" + df["away_team"])
    results["matchkey"] = key(results)
    # Rare genuine duplicates exist (same date + same two teams). Keep the
    # first so one fixture = one row, matching the intl_matches UNIQUE key.
    dupes = results.duplicated(subset=["matchkey"]).sum()
    if dupes:
        print(f"  → dropping {dupes:,} duplicate fixture rows (same date + teams)")
        results = results.drop_duplicates(subset=["matchkey"], keep="first")
        results = results.reset_index(drop=True)
    valid_keys = set(results["matchkey"])

    # --- Tournaments dimension ---
    tournaments = sorted(results["tournament"].dropna().unique())
    tournaments_df = pd.DataFrame({"tournament_name": tournaments})
    tournaments_df.index += 1
    tournaments_df.index.name = "intl_tournament_id"
    tour_to_id = {n: i for i, n in enumerate(tournaments, start=1)}

    # --- Teams dimension (union of every team referenced in-range) ---
    team_set = set(results["home_team"]) | set(results["away_team"])
    gs = raw["goalscorers"]
    so = raw["shootouts"]
    if gs is not None:
        gs = gs[key(gs).isin(valid_keys)].copy()
        gs["matchkey"] = key(gs)
        team_set |= set(gs["team"].dropna())
    if so is not None:
        so = so[key(so).isin(valid_keys)].copy()
        so["matchkey"] = key(so)
        team_set |= set(so["winner"].dropna())
        team_set |= set(so["first_shooter"].dropna())

    teams = sorted(t for t in team_set if isinstance(t, str) and t)
    teams_df = pd.DataFrame({"team_name": teams})
    teams_df.index += 1
    teams_df.index.name = "intl_team_id"
    team_to_id = {n: i for i, n in enumerate(teams, start=1)}

    # --- Matches fact ---
    def ft_result(hs, aws):
        return "H" if hs > aws else ("A" if hs < aws else "D")

    matches_rows = []
    key_to_match_id = {}
    for match_id, row in enumerate(results.itertuples(index=False), start=1):
        key_to_match_id[row.matchkey] = match_id
        matches_rows.append({
            "intl_match_id":      match_id,
            "match_date":         row.date.date(),
            "home_team_id":       team_to_id[row.home_team],
            "away_team_id":       team_to_id[row.away_team],
            "home_score":         int(row.home_score),
            "away_score":         int(row.away_score),
            "ft_result":          ft_result(row.home_score, row.away_score),
            "intl_tournament_id": tour_to_id[row.tournament],
            "city":               None if pd.isna(row.city) else str(row.city),
            "country":            None if pd.isna(row.country) else str(row.country),
            "neutral":            bool(row.neutral),
        })
    matches_df = pd.DataFrame(matches_rows)

    # --- Goalscorers fact ---
    goals_df = pd.DataFrame()
    if gs is not None and not gs.empty:
        rows = []
        for row in gs.itertuples(index=False):
            team = getattr(row, "team", None)
            if not isinstance(team, str) or team not in team_to_id:
                continue
            minute = getattr(row, "minute", None)
            rows.append({
                "intl_match_id":   key_to_match_id[row.matchkey],
                "scoring_team_id": team_to_id[team],
                "scorer":          None if pd.isna(getattr(row, "scorer", None)) else str(row.scorer),
                "minute":          None if pd.isna(minute) else int(minute),
                "own_goal":        bool(getattr(row, "own_goal", False)),
                "penalty":         bool(getattr(row, "penalty", False)),
            })
        goals_df = pd.DataFrame(rows)
        print(f"  → {len(goals_df):,} goal rows in range")

    # --- Shootouts fact ---
    shootouts_df = pd.DataFrame()
    if so is not None and not so.empty:
        rows = []
        for row in so.itertuples(index=False):
            winner = getattr(row, "winner", None)
            if not isinstance(winner, str) or winner not in team_to_id:
                continue
            first = getattr(row, "first_shooter", None)
            rows.append({
                "intl_match_id":         key_to_match_id[row.matchkey],
                "winner_team_id":        team_to_id[winner],
                "first_shooter_team_id": team_to_id[first] if isinstance(first, str) and first in team_to_id else None,
            })
        shootouts_df = pd.DataFrame(rows).drop_duplicates(subset=["intl_match_id"])
        print(f"  → {len(shootouts_df):,} shootout rows in range")

    print(f"  → {len(teams):,} national teams, {len(tournaments):,} tournaments, "
          f"{len(matches_df):,} matches")

    return {
        "intl_tournaments": tournaments_df,
        "intl_teams":       teams_df,
        "intl_matches":     matches_df,
        "intl_goalscorers": goals_df,
        "intl_shootouts":   shootouts_df,
    }


# =============================================================================
# PHASE 3: Load — insert into PostgreSQL in FK-dependency order
# =============================================================================

def load_to_postgres(conn, data: dict) -> None:
    cur = conn.cursor()

    print("Inserting intl_tournaments...")
    df = data["intl_tournaments"]
    execute_values(cur,
        "INSERT INTO intl_tournaments (intl_tournament_id, tournament_name) VALUES %s",
        [(idx, row["tournament_name"]) for idx, row in df.iterrows()])

    print("Inserting intl_teams...")
    df = data["intl_teams"]
    execute_values(cur,
        "INSERT INTO intl_teams (intl_team_id, team_name) VALUES %s",
        [(idx, row["team_name"]) for idx, row in df.iterrows()])

    print("Inserting intl_matches...")
    df = data["intl_matches"]
    execute_values(cur,
        """INSERT INTO intl_matches
           (intl_match_id, match_date, home_team_id, away_team_id,
            home_score, away_score, ft_result, intl_tournament_id,
            city, country, neutral)
           VALUES %s""",
        [(r["intl_match_id"], r["match_date"], r["home_team_id"], r["away_team_id"],
          r["home_score"], r["away_score"], r["ft_result"], r["intl_tournament_id"],
          r["city"], r["country"], r["neutral"]) for _, r in df.iterrows()])

    if not data["intl_goalscorers"].empty:
        print("Inserting intl_goalscorers...")
        df = data["intl_goalscorers"]
        execute_values(cur,
            """INSERT INTO intl_goalscorers
               (intl_match_id, scoring_team_id, scorer, minute, own_goal, penalty)
               VALUES %s""",
            [(r["intl_match_id"], r["scoring_team_id"], r["scorer"],
              r["minute"], r["own_goal"], r["penalty"]) for _, r in df.iterrows()])

    if not data["intl_shootouts"].empty:
        print("Inserting intl_shootouts...")
        df = data["intl_shootouts"]
        # Cast to plain int/None: this frame has no text column, so iterrows()
        # would otherwise upcast every value to numpy float64 (None -> NaN),
        # which psycopg2 cannot adapt.
        execute_values(cur,
            """INSERT INTO intl_shootouts
               (intl_match_id, winner_team_id, first_shooter_team_id)
               VALUES %s""",
            [(int(r["intl_match_id"]), int(r["winner_team_id"]),
              None if pd.isna(r["first_shooter_team_id"]) else int(r["first_shooter_team_id"]))
             for _, r in df.iterrows()])

    # Reset sequences so future manual inserts don't collide.
    for table, id_col in [
        ("intl_tournaments", "intl_tournament_id"),
        ("intl_teams", "intl_team_id"),
        ("intl_matches", "intl_match_id"),
        ("intl_goalscorers", "intl_goal_id"),
    ]:
        cur.execute(f"""
            SELECT setval(pg_get_serial_sequence('{table}', '{id_col}'),
                          COALESCE((SELECT MAX({id_col}) FROM {table}), 0) + 1, false)
        """)

    conn.commit()
    cur.close()
    print("  → All intl_* data inserted.")


# =============================================================================
# PHASE 4: Validate
# =============================================================================

def validate(conn) -> None:
    cur = conn.cursor()
    print("\n" + "=" * 60 + "\nVALIDATION\n" + "=" * 60)

    for table in ("intl_tournaments", "intl_teams", "intl_matches",
                  "intl_goalscorers", "intl_shootouts"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  ✓ {table}: {cur.fetchone()[0]:,} rows")

    cur.execute("SELECT MIN(match_date), MAX(match_date) FROM intl_matches")
    lo, hi = cur.fetchone()
    print(f"\n  Date range: {lo} → {hi}")

    print("\n  Top 5 tournaments by match count:")
    cur.execute("""
        SELECT t.tournament_name, COUNT(*) AS n
        FROM intl_matches m
        JOIN intl_tournaments t ON m.intl_tournament_id = t.intl_tournament_id
        GROUP BY t.tournament_name ORDER BY n DESC LIMIT 5
    """)
    for name, n in cur.fetchall():
        print(f"    {name:35s} {n:,}")

    print("\n  Spot check — a recent match with a readable join:")
    cur.execute("""
        SELECT m.match_date, h.team_name, m.home_score, m.away_score,
               a.team_name, t.tournament_name
        FROM intl_matches m
        JOIN intl_teams h ON m.home_team_id = h.intl_team_id
        JOIN intl_teams a ON m.away_team_id = a.intl_team_id
        JOIN intl_tournaments t ON m.intl_tournament_id = t.intl_tournament_id
        ORDER BY m.match_date DESC LIMIT 1
    """)
    r = cur.fetchone()
    if r:
        print(f"    {r[0]}: {r[1]} {r[2]}-{r[3]} {r[4]} ({r[5]})")

    cur.close()
    print("\n" + "=" * 60 + "\nDONE\n" + "=" * 60)


# =============================================================================
# MAIN
# =============================================================================

def resolve_data_dir(cli_path: str | None) -> Path:
    if cli_path:
        return Path(cli_path)
    import kagglehub
    print(f"Downloading {KAGGLE_SLUG} via kagglehub ...")
    return Path(kagglehub.dataset_download(KAGGLE_SLUG))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10, help="Trailing years to load")
    ap.add_argument("--path", default=None, help="Dir with already-downloaded CSVs")
    ap.add_argument("--dry-run", action="store_true", help="Transform only; no DB write")
    args = ap.parse_args()

    cutoff = date.today() - timedelta(days=365 * args.years)
    print("=" * 60)
    print(f"International Football → PostgreSQL  (last {args.years} years, "
          f"cutoff {cutoff})")
    print("=" * 60 + "\n")

    data_dir = resolve_data_dir(args.path)
    data = load_and_transform(data_dir, cutoff)

    if args.dry_run:
        print("\n[dry-run] Skipping DB write. Summary:")
        for name, df in data.items():
            print(f"  {name}: {len(df):,} rows")
        return

    conn_str = os.getenv("DATABASE_URI")
    if not conn_str:
        raise RuntimeError("DATABASE_URI not set (checked Ethan/agent_v4/.env).")

    print("\nConnecting to PostgreSQL...")
    conn = psycopg2.connect(conn_str)
    print("  → Connected.\n")
    try:
        print("Creating intl_* schema (DDL)...")
        cur = conn.cursor()
        cur.execute(DDL_STATEMENTS)
        conn.commit()
        cur.close()
        print("  → Schema created.\n")

        load_to_postgres(conn, data)
        validate(conn)
    finally:
        conn.close()
        print("\nConnection closed.")


if __name__ == "__main__":
    main()
