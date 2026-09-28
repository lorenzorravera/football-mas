"""
Database module for shared access across all agents.

Usage:
    from db import get_engine, get_connection, read_sql, execute_query

    # With pandas
    df = read_sql("SELECT * FROM matches LIMIT 10")

    # Raw query
    results = execute_query("SELECT COUNT(*) FROM players")

    # With SQLAlchemy connection
    with get_connection() as conn:
        conn.execute(...)
"""

from .connection import (
    get_engine,
    get_connection,
    test_connection,
    execute_query,
    read_sql,
)

__all__ = [
    "get_engine",
    "get_connection",
    "test_connection",
    "execute_query",
    "read_sql",
]