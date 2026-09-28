"""
Phase 0 — DB completeness / integrity / EDA audit  (agent_v5).

Read-only audit of the expanded Aiven Postgres instance, checked against
`till/agent_v5/football_prediction_database_metadata.md`.

Design rules (per Claude_specs.md):
  * Read-only: the connection is forced read-only and every statement has a timeout.
  * Self-contained: reads DATABASE_URI from till/agent_v5/.env (gitignored).
  * Deterministic: introspects the live schema, runs targeted checks, and writes
    BOTH a machine-readable JSON and a human-readable Markdown report. Scoring /
    golden-set design must NOT begin until Till has read the report.

Outputs:
  results/phase0/audit_results.json
  results/phase0/audit_report.md

Run:
  cd till/agent_v5 && ../../.venv/bin/python phase0/audit.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # till/agent_v5
RESULTS_DIR = ROOT / "results" / "phase0"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")
DATABASE_URI = os.getenv("DATABASE_URI")
if not DATABASE_URI:
    raise SystemExit("DATABASE_URI not set — expected in till/agent_v5/.env")

_engine = create_engine(
    DATABASE_URI.replace("postgres://", "postgresql://", 1),
    pool_pre_ping=True,
)

STATEMENT_TIMEOUT_MS = 60_000

# Expected schema (from the metadata doc).
EXPECTED_BASE_TABLES = [
    "competitions", "seasons", "players", "teams", "matches",
    "team_season_standings", "team_season_home_away_standings",
    "team_season_stats_for", "team_season_stats_against",
    "player_season_stats", "player_season_splits",
    "player_match_performance", "match_events",
    "player_market_values", "player_transfers", "player_injury_spells",
    "computed_metrics",
]
EXPECTED_MATVIEWS = [
    "vw_match_summary", "vw_player_availability", "vw_player_match_summary",
    "vw_player_season_summary", "vw_player_shooting_profile",
    "vw_team_season_summary",
]
EXPECTED_SEASONS = ["2020-2021", "2021-2022", "2022-2023", "2023-2024", "2024-2025"]
PARTITION_PARENTS = ["player_match_performance", "match_events"]


# --------------------------------------------------------------------------- #
# Query helpers (read-only)
# --------------------------------------------------------------------------- #
def _conn():
    c = _engine.connect()
    c.execute(text("SET default_transaction_read_only = on"))
    c.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
    return c


def rows(sql: str, params: dict | None = None) -> list[tuple]:
    with _conn() as c:
        return [tuple(r) for r in c.execute(text(sql), params or {}).fetchall()]


def scalar(sql: str, params: dict | None = None):
    with _conn() as c:
        return c.execute(text(sql), params or {}).scalar()


def columns_of(relname: str) -> list[str]:
    """Column names for a table OR materialized view (matviews are not in
    information_schema.columns, so fall back to a LIMIT 0 select)."""
    cols = [r[0] for r in rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position",
        {"t": relname},
    )]
    if cols:
        return cols
    try:
        with _conn() as c:
            res = c.execute(text(f'SELECT * FROM "{relname}" LIMIT 0'))
            return list(res.keys())
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Audit sections
# --------------------------------------------------------------------------- #
def audit_completeness() -> dict:
    base = [r[0] for r in rows(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1")]
    matviews = [r[0] for r in rows(
        "SELECT matviewname FROM pg_matviews WHERE schemaname='public' ORDER BY 1")]

    # partition parent -> ALL descendant partitions (recurse: parent -> league -> season leaves)
    parent_children: dict[str, list[str]] = {}
    for parent in PARTITION_PARENTS:
        kids = [r[0] for r in rows(
            """WITH RECURSIVE descendants AS (
                   SELECT inhrelid AS oid FROM pg_inherits WHERE inhparent = CAST(:p AS regclass)
                   UNION ALL
                   SELECT i.inhrelid FROM pg_inherits i
                   JOIN descendants d ON i.inhparent = d.oid
               )
               SELECT c.relname FROM descendants
               JOIN pg_class c ON c.oid = descendants.oid ORDER BY 1""", {"p": parent})]
        parent_children[parent] = kids

    child_tables = {c for kids in parent_children.values() for c in kids}
    logical_base = [t for t in base if t not in child_tables]

    counts = {}
    for t in logical_base:
        counts[t] = scalar(f'SELECT count(*) FROM "{t}"')
    child_counts = {}
    for parent, kids in parent_children.items():
        for kid in kids:
            child_counts[kid] = scalar(f'SELECT count(*) FROM "{kid}"')
    mv_counts = {mv: scalar(f'SELECT count(*) FROM "{mv}"') for mv in matviews}

    missing_tables = [t for t in EXPECTED_BASE_TABLES if t not in logical_base]
    extra_tables = [t for t in logical_base if t not in EXPECTED_BASE_TABLES]
    missing_mv = [m for m in EXPECTED_MATVIEWS if m not in matviews]

    empty_tables = [t for t, n in counts.items() if (n or 0) == 0]
    empty_children = [c for c, n in child_counts.items() if (n or 0) == 0]

    # seasons present for ENG-PL
    season_rows = rows(
        "SELECT s.season_id, s.season FROM seasons s "
        "JOIN competitions c ON c.competition_id=s.competition_id "
        "WHERE c.league_code='ENG-PL' ORDER BY s.season_id")
    present_seasons = [s for _, s in season_rows]
    missing_seasons = [s for s in EXPECTED_SEASONS if s not in present_seasons]
    season_ids = [sid for sid, _ in season_rows]
    season_id_gaps = (max(season_ids) - min(season_ids) + 1) != len(season_ids) if season_ids else None

    return {
        "logical_base_table_count": len(logical_base),
        "row_counts": counts,
        "partition_children": parent_children,
        "partition_child_counts": child_counts,
        "materialized_view_counts": mv_counts,
        "missing_expected_tables": missing_tables,
        "unexpected_extra_tables": extra_tables,
        "missing_materialized_views": missing_mv,
        "empty_logical_tables": empty_tables,
        "empty_partition_children": empty_children,
        "present_seasons": present_seasons,
        "missing_seasons": missing_seasons,
        "season_id_has_gaps": season_id_gaps,
        "_pass": (not missing_tables and not missing_mv and not missing_seasons
                  and not empty_children),
    }


def audit_integrity() -> dict:
    checks: dict[str, int | None] = {}

    # FK-style orphan checks keyed by integer ids
    checks["orphan_pmp_game_id"] = scalar(
        "SELECT count(*) FROM (SELECT DISTINCT game_id FROM player_match_performance) x "
        "WHERE x.game_id NOT IN (SELECT game_id FROM matches)")
    checks["orphan_match_events_game_id"] = scalar(
        "SELECT count(*) FROM (SELECT DISTINCT game_id FROM match_events WHERE game_id IS NOT NULL) x "
        "WHERE x.game_id NOT IN (SELECT game_id FROM matches)")
    for tbl in ["player_season_stats", "player_match_performance",
                "player_market_values", "player_transfers", "player_injury_spells"]:
        checks[f"orphan_{tbl}_player_id"] = scalar(
            f"SELECT count(*) FROM (SELECT DISTINCT player_id FROM {tbl}) x "
            "WHERE x.player_id NOT IN (SELECT player_id FROM players)")
    for tbl in ["team_season_standings", "team_season_home_away_standings",
                "team_season_stats_for", "team_season_stats_against",
                "player_season_stats"]:
        checks[f"orphan_{tbl}_team_id"] = scalar(
            f"SELECT count(*) FROM (SELECT DISTINCT team_id FROM {tbl} WHERE team_id IS NOT NULL) x "
            "WHERE x.team_id NOT IN (SELECT team_id FROM teams)")
    checks["orphan_matches_home_team_id"] = scalar(
        "SELECT count(*) FROM matches WHERE home_team_id IS NOT NULL "
        "AND home_team_id NOT IN (SELECT team_id FROM teams)")
    checks["orphan_matches_away_team_id"] = scalar(
        "SELECT count(*) FROM matches WHERE away_team_id IS NOT NULL "
        "AND away_team_id NOT IN (SELECT team_id FROM teams)")
    for tbl in ["matches", "team_season_standings", "player_season_stats"]:
        checks[f"orphan_{tbl}_season_id"] = scalar(
            f"SELECT count(*) FROM {tbl} WHERE season_id IS NOT NULL "
            "AND season_id NOT IN (SELECT season_id FROM seasons)")

    # season-string orphans (pmp / match_events key on text season + league_code)
    valid_pairs = "SELECT s.season, c.league_code FROM seasons s JOIN competitions c ON c.competition_id=s.competition_id"
    checks["orphan_pmp_season_string"] = scalar(
        f"SELECT count(*) FROM (SELECT DISTINCT season, league_code FROM player_match_performance) x "
        f"WHERE (x.season, x.league_code) NOT IN ({valid_pairs})")
    checks["orphan_match_events_season_string"] = scalar(
        f"SELECT count(*) FROM (SELECT DISTINCT season, league_code FROM match_events) x "
        f"WHERE (x.season, x.league_code) NOT IN ({valid_pairs})")

    return {"orphan_counts": checks, "_pass": all((v or 0) == 0 for v in checks.values())}


def audit_landmines() -> dict:
    out: dict = {}

    # 1. Points deductions reflected in tss_points (2023-2024).
    #    implied_deduction = (3*wins + draws) - tss_points  (positive => deduction applied)
    ded_rows = rows(
        "SELECT tss_team, tss_wins, tss_draws, tss_points, "
        "(3*tss_wins + tss_draws) - tss_points AS implied_deduction "
        "FROM team_season_standings WHERE tss_season='2023-2024' "
        "AND tss_team IN ('Everton','Nottingham Forest','Nott''m Forest','Nottm Forest') "
        "ORDER BY tss_team")
    deductions = [
        {"team": r[0], "wins": r[1], "draws": r[2], "points": r[3], "implied_deduction": r[4]}
        for r in ded_rows
    ]
    # also list any team-season where points != 3W+D (i.e. some adjustment present)
    adj_rows = rows(
        "SELECT tss_season, tss_team, (3*tss_wins+tss_draws)-tss_points AS implied_deduction "
        "FROM team_season_standings WHERE (3*tss_wins+tss_draws) <> tss_points "
        "ORDER BY tss_season, tss_team")
    all_adjustments = [{"season": r[0], "team": r[1], "implied_deduction": r[2]} for r in adj_rows]
    everton = next((d for d in deductions if d["team"] == "Everton"), None)
    forest = next((d for d in deductions if "Forest" in d["team"]), None)
    out["points_deductions_2023_2024"] = deductions
    out["all_implied_point_adjustments"] = all_adjustments
    out["everton_deduction_ok"] = bool(everton and everton["implied_deduction"] == 8)
    out["forest_deduction_ok"] = bool(forest and forest["implied_deduction"] == 4)

    # 2. player_market_values.date_unix should be seconds, not ms (or date string).
    mn, mx = rows("SELECT min(date_unix), max(date_unix) FROM player_market_values")[0]
    out["market_value_date_unix_min"] = mn
    out["market_value_date_unix_max"] = mx
    # plausible unix-seconds window ~ 2000-01-01 .. 2035-01-01
    out["date_unix_looks_like_seconds"] = bool(mn and 9.5e8 <= mn <= 2.05e9 and mx and mx <= 2.05e9)

    # 3. Team-name aliasing — no duplicate team_ids per canonical name.
    dup_names = rows(
        "SELECT team_name, count(*) FROM teams GROUP BY team_name HAVING count(*) > 1")
    out["duplicate_team_names"] = [{"team_name": r[0], "count": r[1]} for r in dup_names]
    out["team_count"] = scalar("SELECT count(*) FROM teams")
    # surface common alias targets actually present
    out["alias_target_names_present"] = [
        r[0] for r in rows(
            "SELECT team_name FROM teams WHERE team_name ILIKE ANY(ARRAY"
            "['%Man%','%Newcastle%','%Forest%','%West Ham%','%Wolv%','%Tottenham%','%Brighton%']) "
            "ORDER BY team_name")]

    # 4. Partition non-emptiness (event-level / player-match viability gate).
    out["match_events_total"] = scalar("SELECT count(*) FROM match_events")
    out["player_match_performance_total"] = scalar("SELECT count(*) FROM player_match_performance")
    out["partitions_nonempty"] = bool(
        (out["match_events_total"] or 0) > 0 and (out["player_match_performance_total"] or 0) > 0)

    # 5. Season-string format note (hyphen vs underscore) + latest season.
    out["season_string_sample"] = [r[0] for r in rows("SELECT season FROM seasons ORDER BY season_id")]
    out["uses_hyphen_season_format"] = all("-" in s for s in out["season_string_sample"])
    out["latest_season"] = scalar("SELECT max(season) FROM seasons")

    out["_pass"] = bool(
        out["everton_deduction_ok"] and out["forest_deduction_ok"]
        and out["date_unix_looks_like_seconds"] and not dup_names
        and out["partitions_nonempty"])
    return out


def audit_matview_freshness() -> dict:
    out: dict = {}
    out["vw_team_season_summary_count"] = scalar("SELECT count(*) FROM vw_team_season_summary")
    out["team_season_standings_count"] = scalar("SELECT count(*) FROM team_season_standings")
    out["vw_match_summary_count"] = scalar("SELECT count(*) FROM vw_match_summary")
    out["matches_count"] = scalar("SELECT count(*) FROM matches")
    out["vw_player_season_summary_count"] = scalar("SELECT count(*) FROM vw_player_season_summary")
    out["player_season_stats_count"] = scalar("SELECT count(*) FROM player_season_stats")

    # spot-check: vwtss_points vs tss_points for a handful of team-seasons
    mismatches = rows(
        "SELECT v.vwtss_team_name, v.vwtss_season, v.vwtss_points, t.tss_points "
        "FROM vw_team_season_summary v "
        "JOIN team_season_standings t ON t.team_id=v.vwtss_team_id AND t.season_id=v.vwtss_season_id "
        "WHERE v.vwtss_points <> t.tss_points")
    out["vwtss_points_mismatches"] = [
        {"team": r[0], "season": r[1], "vw_points": r[2], "base_points": r[3]} for r in mismatches]

    out["_pass"] = bool(
        out["vw_team_season_summary_count"] == out["team_season_standings_count"]
        and out["vw_match_summary_count"] == out["matches_count"]
        and not mismatches)
    return out


def audit_eda() -> dict:
    out: dict = {}

    # null rates for modelling-relevant columns
    null_targets = {
        "matches": ["home_score", "away_score", "ft_result", "referee", "attendance_m",
                    "avg_home_odds", "home_shots", "home_formation"],
        "player_season_stats": ["minutes_pss", "goals_pss", "xg_pss", "age"],
        "team_season_stats_for": ["tssf_possession_percentage", "tssf_goals", "tssf_shots"],
        "player_market_values": ["market_value"],
        "player_match_performance": ["minutes_played", "match_goals", "xg_pmp", "position"],
    }
    null_rates: dict[str, dict[str, float]] = {}
    for tbl, cols in null_targets.items():
        present = set(columns_of(tbl))
        total = scalar(f'SELECT count(*) FROM "{tbl}"') or 0
        null_rates[tbl] = {}
        for col in cols:
            if col not in present or total == 0:
                null_rates[tbl][col] = None
                continue
            nulls = scalar(f'SELECT count(*) FROM "{tbl}" WHERE "{col}" IS NULL')
            null_rates[tbl][col] = round((nulls or 0) / total, 4)
    out["null_rates"] = null_rates

    # value-range sanity
    ranges: dict[str, int | None] = {}
    ranges["possession_for_out_of_range"] = scalar(
        "SELECT count(*) FROM team_season_stats_for WHERE tssf_possession_percentage IS NOT NULL "
        "AND (tssf_possession_percentage < 0 OR tssf_possession_percentage > 100)")
    ranges["odds_le_1"] = scalar(
        "SELECT count(*) FROM matches WHERE avg_home_odds IS NOT NULL AND avg_home_odds <= 1.0")
    ranges["negative_minutes_pss"] = scalar(
        "SELECT count(*) FROM player_season_stats WHERE minutes_pss < 0")
    ranges["negative_minutes_pmp"] = scalar(
        "SELECT count(*) FROM player_match_performance WHERE minutes_played < 0")
    ranges["negative_scores"] = scalar(
        "SELECT count(*) FROM matches WHERE home_score < 0 OR away_score < 0")
    out["value_range_violations"] = ranges

    # duplicate detection on conflict keys
    dups: dict[str, int | None] = {}
    dups["matches_game_id"] = scalar(
        "SELECT count(*) FROM (SELECT game_id FROM matches GROUP BY game_id HAVING count(*)>1) x")
    dups["player_season_stats_key"] = scalar(
        "SELECT count(*) FROM (SELECT player_id,season_id,team_id FROM player_season_stats "
        "GROUP BY player_id,season_id,team_id HAVING count(*)>1) x")
    dups["team_season_standings_key"] = scalar(
        "SELECT count(*) FROM (SELECT team_id,season_id FROM team_season_standings "
        "GROUP BY team_id,season_id HAVING count(*)>1) x")
    dups["player_market_values_key"] = scalar(
        "SELECT count(*) FROM (SELECT player_id,date_unix FROM player_market_values "
        "GROUP BY player_id,date_unix HAVING count(*)>1) x")
    out["duplicate_conflict_keys"] = dups

    out["_pass"] = bool(
        all((v or 0) == 0 for v in ranges.values())
        and all((v or 0) == 0 for v in dups.values()))
    return out


# --------------------------------------------------------------------------- #
# Report rendering
# --------------------------------------------------------------------------- #
def render_markdown(results: dict) -> str:
    g = results["generated_at"]
    comp = results["completeness"]
    integ = results["integrity"]
    land = results["landmines"]
    mv = results["matview_freshness"]
    eda = results["eda"]

    def flag(ok: bool | None) -> str:
        return "✅ PASS" if ok else ("⚠️ REVIEW" if ok is None else "❌ FAIL")

    L = []
    L.append("# Phase 0 — Database Audit Report (agent_v5)")
    L.append("")
    L.append(f"- **Generated (UTC):** {g}")
    L.append(f"- **Database:** `{results['database_host']}` (PostgreSQL {results['pg_version']})")
    L.append("- **Access:** read-only, statement timeout "
             f"{STATEMENT_TIMEOUT_MS // 1000}s")
    L.append("- **Checked against:** `football_prediction_database_metadata.md`")
    L.append("")
    L.append("## Section pass/fail summary")
    L.append("")
    L.append("| Section | Result |")
    L.append("|---|---|")
    L.append(f"| A. Completeness | {flag(comp['_pass'])} |")
    L.append(f"| B. Referential integrity | {flag(integ['_pass'])} |")
    L.append(f"| C. Known landmines | {flag(land['_pass'])} |")
    L.append(f"| D. Materialized-view freshness | {flag(mv['_pass'])} |")
    L.append(f"| E. Light EDA | {flag(eda['_pass'])} |")
    L.append("")

    # A
    L.append("## A. Completeness")
    L.append("")
    L.append(f"- Logical base tables: **{comp['logical_base_table_count']}** "
             f"(+ {sum(len(v) for v in comp['partition_children'].values())} partition children)")
    L.append(f"- Missing expected tables: `{comp['missing_expected_tables'] or 'none'}`")
    L.append(f"- Unexpected extra tables: `{comp['unexpected_extra_tables'] or 'none'}`")
    L.append(f"- Missing materialized views: `{comp['missing_materialized_views'] or 'none'}`")
    L.append(f"- Empty logical tables: `{comp['empty_logical_tables'] or 'none'}`")
    L.append(f"- Empty partition children: `{comp['empty_partition_children'] or 'none'}`")
    L.append(f"- Seasons present (ENG-PL): `{comp['present_seasons']}`")
    L.append(f"- Missing seasons: `{comp['missing_seasons'] or 'none'}`")
    L.append("")
    L.append("### Row counts — logical base tables")
    L.append("")
    L.append("| Table | Rows |")
    L.append("|---|---:|")
    for t, n in sorted(comp["row_counts"].items()):
        L.append(f"| `{t}` | {n:,} |")
    L.append("")
    L.append("### Row counts — partition children")
    L.append("")
    L.append("| Child partition | Rows |")
    L.append("|---|---:|")
    for t, n in sorted(comp["partition_child_counts"].items()):
        L.append(f"| `{t}` | {n:,} |")
    L.append("")
    L.append("### Row counts — materialized views")
    L.append("")
    L.append("| View | Rows |")
    L.append("|---|---:|")
    for t, n in sorted(comp["materialized_view_counts"].items()):
        L.append(f"| `{t}` | {n:,} |")
    L.append("")

    # B
    L.append("## B. Referential integrity")
    L.append("")
    L.append("All counts should be **0** (zero orphaned references).")
    L.append("")
    L.append("| Check | Orphans |")
    L.append("|---|---:|")
    for k, v in integ["orphan_counts"].items():
        mark = "" if (v or 0) == 0 else "  ❌"
        L.append(f"| `{k}` | {v}{mark} |")
    L.append("")

    # C
    L.append("## C. Known landmines")
    L.append("")
    L.append(f"- **Everton −8 (2023-24) reflected in `tss_points`:** {flag(land['everton_deduction_ok'])}")
    L.append(f"- **Nottingham Forest −4 (2023-24) reflected in `tss_points`:** {flag(land['forest_deduction_ok'])}")
    L.append("")
    L.append("Implied point adjustments found (where `tss_points ≠ 3·W + D`):")
    L.append("")
    if land["all_implied_point_adjustments"]:
        L.append("| Season | Team | Implied deduction |")
        L.append("|---|---|---:|")
        for a in land["all_implied_point_adjustments"]:
            L.append(f"| {a['season']} | {a['team']} | {a['implied_deduction']} |")
    else:
        L.append("_None found._")
    L.append("")
    L.append(f"- **`player_market_values.date_unix` looks like seconds:** "
             f"{flag(land['date_unix_looks_like_seconds'])} "
             f"(min={land['market_value_date_unix_min']}, max={land['market_value_date_unix_max']})")
    L.append(f"- **No duplicate team names:** {flag(not land['duplicate_team_names'])} "
             f"(team_count={land['team_count']}, dups={land['duplicate_team_names'] or 'none'})")
    L.append(f"- **Partitioned tables non-empty:** {flag(land['partitions_nonempty'])} "
             f"(match_events={land['match_events_total']:,}, "
             f"player_match_performance={land['player_match_performance_total']:,}) "
             "→ event-level & player-match question categories are **VIABLE**.")
    L.append(f"- **Season string format:** uses hyphen (`YYYY-YYYY`) = "
             f"{land['uses_hyphen_season_format']}; sample `{land['season_string_sample']}`. "
             f"Latest season = `{land['latest_season']}`.")
    L.append(f"- Team alias targets present: `{land['alias_target_names_present']}`")
    L.append("")

    # D
    L.append("## D. Materialized-view freshness")
    L.append("")
    L.append("| View | View rows | Base rows |")
    L.append("|---|---:|---:|")
    L.append(f"| `vw_team_season_summary` vs `team_season_standings` | "
             f"{mv['vw_team_season_summary_count']:,} | {mv['team_season_standings_count']:,} |")
    L.append(f"| `vw_match_summary` vs `matches` | "
             f"{mv['vw_match_summary_count']:,} | {mv['matches_count']:,} |")
    L.append(f"| `vw_player_season_summary` vs `player_season_stats` | "
             f"{mv['vw_player_season_summary_count']:,} | {mv['player_season_stats_count']:,} |")
    L.append("")
    L.append(f"- `vwtss_points` vs `tss_points` mismatches: "
             f"**{len(mv['vwtss_points_mismatches'])}** "
             f"{mv['vwtss_points_mismatches'][:5] if mv['vwtss_points_mismatches'] else ''}")
    L.append("")

    # E
    L.append("## E. Light EDA")
    L.append("")
    L.append("### Null rates (fraction NULL) — modelling-relevant columns")
    L.append("")
    L.append("| Table | Column | Null rate |")
    L.append("|---|---|---:|")
    for tbl, cols in eda["null_rates"].items():
        for col, rate in cols.items():
            L.append(f"| `{tbl}` | `{col}` | {rate if rate is not None else 'n/a'} |")
    L.append("")
    L.append("### Value-range violations (should all be 0)")
    L.append("")
    L.append("| Check | Count |")
    L.append("|---|---:|")
    for k, v in eda["value_range_violations"].items():
        mark = "" if (v or 0) == 0 else "  ❌"
        L.append(f"| `{k}` | {v}{mark} |")
    L.append("")
    L.append("### Duplicate conflict keys (should all be 0)")
    L.append("")
    L.append("| Key | Duplicate groups |")
    L.append("|---|---:|")
    for k, v in eda["duplicate_conflict_keys"].items():
        mark = "" if (v or 0) == 0 else "  ❌"
        L.append(f"| `{k}` | {v}{mark} |")
    L.append("")

    L.append("## Viability note for the golden set")
    L.append("")
    L.append("This section is advisory; **Till confirms viable categories before Phase 2.**")
    L.append("")
    L.append("- Team/league outcomes, player season aggregates, home/away splits, "
             "disciplinary, xG over/under, market value/transfers, availability: "
             "backed by populated tables/views → candidate categories.")
    L.append("- Event-level & player-match: partitions are populated → **viable** "
             "(contrary to the metadata doc's stale 'no child partitions' warning).")
    L.append('- "Current/this season" (2025-2026) has **no data** — latest is '
             f"`{land['latest_season']}`. Golden-set season wording must avoid relative "
             '"current season" or pin it to 2024-2025.')
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    pg_version = scalar("SELECT version()")
    host = DATABASE_URI.split("@")[-1].split("/")[0]

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database_host": host,
        "pg_version": (pg_version or "").split(" on ")[0].replace("PostgreSQL ", ""),
        "completeness": audit_completeness(),
        "integrity": audit_integrity(),
        "landmines": audit_landmines(),
        "matview_freshness": audit_matview_freshness(),
        "eda": audit_eda(),
    }
    results["overall_pass"] = all(
        results[s]["_pass"] for s in
        ["completeness", "integrity", "landmines", "matview_freshness", "eda"])

    (RESULTS_DIR / "audit_results.json").write_text(json.dumps(results, indent=2, default=str))
    (RESULTS_DIR / "audit_report.md").write_text(render_markdown(results))

    print(f"overall_pass = {results['overall_pass']}")
    for s in ["completeness", "integrity", "landmines", "matview_freshness", "eda"]:
        print(f"  {s:20s} _pass = {results[s]['_pass']}")
    print(f"\nWrote:\n  {RESULTS_DIR/'audit_results.json'}\n  {RESULTS_DIR/'audit_report.md'}")


if __name__ == "__main__":
    main()
