"""
Database connection module for all agents.
Uses SQLAlchemy for flexibility with pandas and raw SQL.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get database URI from environment
DATABASE_URI = os.getenv("DATABASE_URI")

_engine: Engine | None = None


def get_engine() -> Engine:
    """
    Get or create a SQLAlchemy engine (singleton pattern).
    Reuses the same engine across calls for connection pooling.
    """
    global _engine

    if _engine is None:
        if not DATABASE_URI:
            raise ValueError(
                "DATABASE_URI not found. "
                "Make sure you have a .env file with DATABASE_URI set."
            )
        _engine = create_engine(
            DATABASE_URI,
            pool_pre_ping=True,  # Verify connections before using
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_connection():
    """
    Get a new connection from the engine.
    Use as context manager: with get_connection() as conn: ...
    """
    return get_engine().connect()


def test_connection() -> bool:
    """
    Test if the database connection is working.
    Returns True if successful, raises exception otherwise.
    """
    try:
        with get_connection() as conn:
            conn.execute(text("SELECT 1"))
        print("✓ Database connection successful")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        raise


def execute_query(query: str, params: dict = None):
    """
    Execute a raw SQL query and return results.

    Args:
        query: SQL query string
        params: Optional dict of parameters for parameterized queries

    Returns:
        List of rows as dictionaries
    """
    with get_connection() as conn:
        result = conn.execute(text(query), params or {})
        if result.returns_rows:
            return [dict(row._mapping) for row in result]
        conn.commit()
        return None


# For convenience with pandas
def read_sql(query: str, params: dict = None):
    """
    Execute a query and return results as a pandas DataFrame.

    Args:
        query: SQL query string
        params: Optional dict of parameters

    Returns:
        pandas DataFrame
    """
    import pandas as pd

    with get_connection() as conn:
        return pd.read_sql(text(query), conn, params=params)


if __name__ == "__main__":
    # Quick test when run directly
    test_connection()