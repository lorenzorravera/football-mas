"""
Aiven Postgres schema discovery.

Inspects the connected database and produces a markdown report of:
  - All tables (name, row count)
  - Column schemas (name, type, nullable)
  - Sample row from each table
  - Presence check for tables the prediction agent expects

Usage:
    export DATABASE_URI="postgres://..."
    python3 scripts/inspect_aiven.py > aiven_schema_report.md

The script is READ-ONLY. It only runs SELECT and information_schema queries.
"""

from __future__ import annotations

import os
import sys
from contextlib import closing

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)


# Tables we expect to exist for the prediction agent and bandit work.
# Marked as "core" (must exist) vs "extended" (needed for richer prediction).
EXPECTED_TABLES = {
    # Core football data — assumed present
    "matches": "core",
    "match_team_stats": "core",
    "teams": "core",
    "referees": "core",
    "seasons": "core",
    "leagues": "core",
    "points_adjustments": "core",
    # Extended — may or may not exist yet
    "match_xg_stats": "extended",
    "players": "extended",
    "player_match_stats": "extended",
    "injuries": "extended",
    "match_weather": "extended",
    "predictions": "extended",
    # Memory layer — assumed present
    "conversation_memory": "memory",
    "sql_cache": "memory",
    "correction_memory": "memory",
    "feedback": "memory",
}


def get_connection():
    uri = os.environ.get("DATABASE_URI")
    if not uri:
        print("ERROR: DATABASE_URI environment variable not set.", file=sys.stderr)
        print("       export DATABASE_URI='postgres://...' first.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(uri)


def list_tables(cur) -> list[str]:
    """Return all user tables in the current schema (excluding system tables)."""
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    return [r["table_name"] for r in cur.fetchall()]


def get_columns(cur, table: str) -> list[dict]:
    """Return column metadata for a table."""
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
    """, (table,))
    return cur.fetchall()


def get_row_count(cur, table: str) -> int | None:
    """Exact row count. Cheap for tables under ~1M rows."""
    try:
        cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier(table)))
        return cur.fetchone()["n"]
    except Exception as exc:
        return None


def get_sample(cur, table: str, n: int = 1) -> list[dict]:
    """One sample row. Tells us what the data actually looks like."""
    try:
        cur.execute(sql.SQL("SELECT * FROM {} LIMIT %s").format(sql.Identifier(table)),
                    (n,))
        return cur.fetchall()
    except Exception:
        return []


def get_date_range(cur, table: str, date_col: str) -> tuple | None:
    """For temporal tables, find min/max of a date column."""
    try:
        cur.execute(sql.SQL("SELECT MIN({c}) AS lo, MAX({c}) AS hi FROM {t}").format(
            c=sql.Identifier(date_col), t=sql.Identifier(table)))
        row = cur.fetchone()
        return (row["lo"], row["hi"]) if row else None
    except Exception:
        return None


def render_report(conn) -> str:
    """Build the markdown report. Returns a string."""
    out: list[str] = []
    out.append("# Aiven schema discovery report\n")

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        actual = set(list_tables(cur))
        expected = set(EXPECTED_TABLES.keys())

        # ----- Presence summary -----
        out.append("## Table presence summary\n")
        out.append("| Table | Category | Present? |")
        out.append("|---|---|---|")
        for name in sorted(expected):
            category = EXPECTED_TABLES[name]
            present = "✅" if name in actual else "❌"
            out.append(f"| `{name}` | {category} | {present} |")
        unexpected = actual - expected
        if unexpected:
            out.append("\n**Unexpected tables (in DB but not in our list):**")
            for name in sorted(unexpected):
                out.append(f"- `{name}`")

        # ----- Per-table detail -----
        out.append("\n## Per-table detail\n")
        for name in sorted(actual):
            cols = get_columns(cur, name)
            row_count = get_row_count(cur, name)
            sample = get_sample(cur, name, n=1)

            out.append(f"### `{name}`")
            if row_count is not None:
                out.append(f"**Rows:** {row_count:,}")
            out.append("\n**Columns:**\n")
            out.append("| Column | Type | Nullable | Default |")
            out.append("|---|---|---|---|")
            for c in cols:
                default = c["column_default"] or ""
                # Truncate long defaults
                if len(str(default)) > 30:
                    default = str(default)[:27] + "..."
                out.append(f"| `{c['column_name']}` | {c['data_type']} | {c['is_nullable']} | {default} |")

            # Date range probe for tables that look temporal
            for date_col in ("match_date", "created_at", "start_date", "date"):
                if any(c["column_name"] == date_col for c in cols):
                    dr = get_date_range(cur, name, date_col)
                    if dr and dr[0] is not None:
                        out.append(f"\n**Date range** (`{date_col}`): {dr[0]} → {dr[1]}")
                    break

            if sample:
                out.append("\n**Sample row:**\n")
                out.append("```")
                for k, v in sample[0].items():
                    val = str(v)
                    if len(val) > 80:
                        val = val[:77] + "..."
                    out.append(f"  {k}: {val}")
                out.append("```")
            out.append("")

    return "\n".join(out)


def main() -> None:
    conn = get_connection()
    try:
        report = render_report(conn)
        print(report)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
