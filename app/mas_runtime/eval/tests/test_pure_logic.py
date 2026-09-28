"""
Pure-logic checks for Phase A/B (NO DB, NO LLM) — fast sanity of the building blocks:
  - _scope_clause (memory namespacing: eval-scoped vs live-excludes-eval)
  - build_arm     (bandit arm key)
  - token accumulator (config per-turn token accounting)

Run:  cd Ethan/agent_v4 && python eval/tests/test_pure_logic.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main() -> int:
    from memory.vector_store_pg import _scope_clause, DEFAULT_EXCLUDE_SOURCES

    sql, p = _scope_clause("sess-123")
    assert sql == " AND session_id = %s" and p == ["sess-123"], (sql, p)

    sql, p = _scope_clause(None)
    assert "source IS NULL OR NOT (source = ANY(%s))" in sql and p == [["eval_session"]], (sql, p)

    sql, p = _scope_clause(None, exclude_sources=None)
    assert sql == "" and p == [], (sql, p)
    print(f"✓ _scope_clause (default excludes {DEFAULT_EXCLUDE_SOURCES})")

    from memory.trajectory_log import build_arm
    assert build_arm("claude", "no_control", "data_request") == "claude|no_control|data_request"
    assert build_arm(None, None, None) == "unknown|unknown|unknown"
    print("✓ build_arm")

    from config import reset_token_usage, get_token_usage, _accumulate_usage

    class _U:
        prompt_tokens = 10; completion_tokens = 5; total_tokens = 15

    class _R:
        usage = _U()

    reset_token_usage()
    _accumulate_usage(_R()); _accumulate_usage(_R())
    u = get_token_usage()
    assert u == {"prompt": 20, "completion": 10, "total": 30}, u
    print(f"✓ token accumulator: {u}")

    print("\n✓ ALL PURE-LOGIC CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
