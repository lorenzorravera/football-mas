"""
A1 verification — memory namespacing / cross-session isolation.

Asserts:
  1. A correction written under session X is retrievable when querying scoped to X.
  2. The same row is NOT visible when querying scoped to a different session Y.
  3. The same row is NOT visible in LIVE mode (session_id=None) — eval rows excluded.
  4. purge_session(X) deletes only X's rows; Y's rows survive.
  5. purge_source('live'/'legacy') is refused (protects production rows).

Uses source='eval_session' + unique session ids and cleans up after, so it never
pollutes live memory. Needs DATABASE_URI (migration add_session_source.sql applied).

Run:  cd Ethan/agent_v4 && python eval/tests/test_session_isolation.py
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from memory.vector_store_pg import (
    store_correction, query_correction_memory, purge_session, purge_source,
)


def main() -> int:
    sid_x = f"test_{uuid.uuid4()}"
    sid_y = f"test_{uuid.uuid4()}"
    q_x = "How many corners did referee A Taylor's matches have in 2023-2024?"
    q_y = "Which player scored the most headers in 2022-2023?"

    store_correction(
        memory_id=str(uuid.uuid4()), user_query=q_x,
        error_type="test", error_message="boom-x", bad_sql="SELECT 1",
        stage="test", session_id=sid_x, source="eval_session",
    )
    store_correction(
        memory_id=str(uuid.uuid4()), user_query=q_y,
        error_type="test", error_message="boom-y", bad_sql="SELECT 2",
        stage="test", session_id=sid_y, source="eval_session",
    )

    try:
        # 1. scoped to X -> sees X
        hits_x = query_correction_memory(q_x, n_results=5, session_id=sid_x)
        assert any(h["error_message"] == "boom-x" for h in hits_x), "X not visible in X scope"

        # 2. scoped to Y -> does NOT see X
        hits_y = query_correction_memory(q_x, n_results=5, session_id=sid_y)
        assert not any(h["error_message"] == "boom-x" for h in hits_y), "X leaked into Y scope"

        # 3. live (no session) -> does NOT see eval rows
        hits_live = query_correction_memory(q_x, n_results=5, session_id=None)
        assert not any(h["error_message"] == "boom-x" for h in hits_live), "eval row leaked to LIVE"

        # 4. purge X only
        deleted = purge_session(sid_x)
        assert deleted["correction_memory"] >= 1, "purge_session(X) deleted nothing"
        assert not query_correction_memory(q_x, n_results=5, session_id=sid_x), "X survived purge"
        assert query_correction_memory(q_y, n_results=5, session_id=sid_y), "Y wrongly purged with X"

        # 5. protected sources refuse purge
        for protected in ("live", "legacy"):
            try:
                purge_source(protected)
                raise AssertionError(f"purge_source({protected!r}) should have raised")
            except ValueError:
                pass

        print("✓ session isolation, scoped purge, and source protection all hold")
        return 0
    finally:
        purge_session(sid_x)
        purge_session(sid_y)


if __name__ == "__main__":
    sys.exit(main())
