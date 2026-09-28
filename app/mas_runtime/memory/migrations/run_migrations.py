"""
Apply all *.sql migrations in this directory, in sorted filename order, against
DATABASE_URI. Every migration is written to be idempotent (ADD COLUMN IF NOT EXISTS,
CREATE TABLE IF NOT EXISTS, ...), so re-running is safe.

Usage:
    cd Ethan/agent_v4
    python memory/migrations/run_migrations.py
"""

import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

_HERE = Path(__file__).parent


def main() -> int:
    # override=True so the .env wins over any stale placeholder in the shell env.
    load_dotenv(_HERE.parent.parent / ".env", override=True)
    import os

    uri = os.getenv("DATABASE_URI")
    if not uri:
        print("✗ DATABASE_URI not set (expected in Ethan/agent_v4/.env)")
        return 1

    sql_files = sorted(_HERE.glob("*.sql"))
    if not sql_files:
        print("No .sql migrations found.")
        return 0

    conn = psycopg2.connect(uri)
    conn.autocommit = True
    try:
        for f in sql_files:
            print(f"→ applying {f.name} ...")
            with conn.cursor() as cur:
                cur.execute(f.read_text())
            print(f"  ✓ {f.name}")
    finally:
        conn.close()

    print("✓ all migrations applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
