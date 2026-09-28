"""
run_sql — THE single read-only database entry point for the agent_v5 eval.

Every DB access in the eval goes through here (spec constraints 6-7). Wraps the
existing SQLAlchemy engine logic (from till/db/connection.py) but adds:
  * read-only transaction (default_transaction_read_only = on)
  * statement timeout
  * SELECT/WITH-only validation (rejects multi-statement and any DML/DDL)
  * a structured JSON-friendly return: {columns, rows, row_count, truncated, sql}

No agent or eval file should open a DB connection directly.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# DATABASE_URI (note: not _URL) lives in the gitignored till/agent_v5/.env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
DATABASE_URI = os.getenv("DATABASE_URI")

STATEMENT_TIMEOUT_MS = 30_000   # hard per-statement ceiling
DEFAULT_MAX_ROWS = 1_000        # cap returned rows (applies identically to every condition)

# Keywords that must never appear as the leading token (defense-in-depth on top of
# the read-only transaction, which is the real guarantee).
_FORBIDDEN_LEADING = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "merge", "call", "do", "vacuum", "reindex",
    "refresh", "comment", "lock", "set", "begin", "commit", "rollback",
}

_engine: Engine | None = None


class SqlNotAllowed(ValueError):
    """Raised when a query is not a single read-only SELECT/WITH statement."""


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not DATABASE_URI:
            raise RuntimeError("DATABASE_URI not set — expected in till/agent_v5/.env")
        uri = DATABASE_URI.replace("postgres://", "postgresql://", 1)
        _engine = create_engine(uri, pool_pre_ping=True, pool_size=3, max_overflow=5)
    return _engine


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments and /* */ block comments for validation."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validate_read_only(sql: str) -> str:
    """
    Validate that `sql` is a single read-only SELECT/WITH statement.

    Returns the cleaned single-statement SQL (trailing ';' allowed, stripped).
    Raises SqlNotAllowed otherwise.
    """
    if not sql or not sql.strip():
        raise SqlNotAllowed("Empty query.")

    cleaned = _strip_sql_comments(sql)

    # Single statement only: at most one trailing semicolon.
    statements = [s for s in cleaned.split(";") if s.strip()]
    if len(statements) != 1:
        raise SqlNotAllowed(
            f"Only a single statement is allowed (found {len(statements)})."
        )
    stmt = statements[0].strip()

    leading = stmt.split(None, 1)[0].lower()
    if leading not in {"select", "with"}:
        if leading in _FORBIDDEN_LEADING:
            raise SqlNotAllowed(f"Statement type '{leading.upper()}' is not permitted (read-only).")
        raise SqlNotAllowed("Only SELECT / WITH queries are permitted.")

    return stmt


def run_sql(sql: str, params: dict | None = None, max_rows: int = DEFAULT_MAX_ROWS) -> dict:
    """
    Execute a read-only SELECT/WITH query and return a structured result.

    Args:
        sql:      a single SELECT/WITH statement
        params:   optional bound parameters (:name style)
        max_rows: cap on returned rows; result flagged `truncated` if exceeded

    Returns:
        {
          "columns":   [str, ...],
          "rows":      [[val, ...], ...],   # JSON-serialisable (Decimals/dates -> str)
          "row_count": int,                 # rows actually returned (<= max_rows)
          "truncated": bool,
          "sql":       str,                 # the validated statement
        }

    Raises:
        SqlNotAllowed if the query is not a single read-only SELECT/WITH.
    """
    stmt = validate_read_only(sql)
    eng = _get_engine()
    with eng.connect() as conn:
        conn.execute(text("SET default_transaction_read_only = on"))
        conn.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        result = conn.execute(text(stmt), params or {})
        columns = list(result.keys())
        fetched = result.fetchmany(max_rows + 1)

    truncated = len(fetched) > max_rows
    rows = [[_jsonable(v) for v in row] for row in fetched[:max_rows]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "sql": stmt,
    }


def run_sql_df(sql: str, params: dict | None = None):
    """Internal convenience: same validation, returns a pandas DataFrame (no row cap)."""
    import pandas as pd

    stmt = validate_read_only(sql)
    eng = _get_engine()
    with eng.connect() as conn:
        conn.execute(text("SET default_transaction_read_only = on"))
        conn.execute(text(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        return pd.read_sql(text(stmt), conn, params=params)


def _jsonable(v):
    """Coerce DB values to JSON-serialisable forms."""
    import datetime
    from decimal import Decimal

    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    return str(v)


if __name__ == "__main__":
    import json

    print("=== Phase 1 acceptance: 2023-24 standings with Everton/Forest deductions ===")
    res = run_sql(
        "SELECT tss_rank, tss_team, tss_wins, tss_draws, tss_losses, tss_points "
        "FROM team_season_standings WHERE tss_season = '2023-2024' "
        "ORDER BY tss_rank"
    )
    print(f"{res['row_count']} rows, columns={res['columns']}")
    for row in res["rows"]:
        flag = ""
        if row[1] in ("Everton", "Nottingham Forest"):
            implied = 3 * row[2] + row[3] - row[5]
            flag = f"   <-- implied deduction {implied}"
        print("  ", row, flag)

    print("\n=== read-only guard: non-SELECT statements must be rejected ===")
    for bad in ["DELETE FROM teams", "DROP TABLE matches",
                "SELECT 1; DROP TABLE teams", "UPDATE matches SET home_score=9"]:
        try:
            run_sql(bad)
            print(f"  ❌ NOT rejected: {bad!r}")
        except SqlNotAllowed as e:
            print(f"  ✅ rejected {bad!r:45s} -> {e}")
