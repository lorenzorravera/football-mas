"""
A2/A3 verification — token accounting + trajectory logging (no LLM/API cost).

Asserts:
  1. reset_token_usage / _accumulate_usage / get_token_usage accumulate correctly.
  2. log_trajectory writes exactly one row that reads back with the right fields.
  3. update_thumbs patches the thumbs onto that row.

Cleans up the test row. Needs DATABASE_URI (migration add_trajectory_log.sql applied).

Run:  cd Ethan/agent_v4 && python eval/tests/test_trajectory_capture.py
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from config import reset_token_usage, get_token_usage, _accumulate_usage
from memory.trajectory_log import log_trajectory, update_thumbs, build_arm
from memory.vector_store_pg import _get_conn


class _FakeUsage:
    prompt_tokens = 100
    completion_tokens = 40
    total_tokens = 140


class _FakeResponse:
    usage = _FakeUsage()


def main() -> int:
    # 1. token accounting
    reset_token_usage()
    _accumulate_usage(_FakeResponse())
    _accumulate_usage(_FakeResponse())
    usage = get_token_usage()
    assert usage["total"] == 280, f"expected 280, got {usage}"
    assert usage["prompt"] == 200 and usage["completion"] == 80, usage
    print(f"✓ token accounting: {usage}")

    # 2. trajectory write
    qid = str(uuid.uuid4())
    ok = log_trajectory({
        "query_id": qid, "experiment": "selftest", "condition": "mas",
        "model": "claude", "variant": "no_control", "intent": "data_request",
        "context_features": {"n_words": 7},
        "full_trajectory_json": {"nodes": ["manager", "data_analyst", "synthesizer"]},
        "latency_ms": 4321, "token_cost": usage["total"], "eval_score": 1.0,
    })
    assert ok, "log_trajectory returned False"

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT arm, token_cost, eval_score, thumbs FROM trajectory_log WHERE query_id = %s",
                (qid,),
            )
            row = cur.fetchone()
        assert row is not None, "trajectory row not found"
        assert row[0] == build_arm("claude", "no_control", "data_request"), row
        assert row[1] == 280 and abs(row[2] - 1.0) < 1e-6, row
        assert row[3] is None, "thumbs should be NULL before feedback"
        print(f"✓ trajectory row written: arm={row[0]} token_cost={row[1]} eval={row[2]}")

        # 3. thumbs patch
        assert update_thumbs(qid, 1), "update_thumbs returned False"
        with conn.cursor() as cur:
            cur.execute("SELECT thumbs FROM trajectory_log WHERE query_id = %s", (qid,))
            assert cur.fetchone()[0] == 1, "thumbs not patched"
        print("✓ thumbs patched onto trajectory row")
        print("\n✓ A2/A3 capture verified")
        return 0
    finally:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM trajectory_log WHERE query_id = %s", (qid,))


if __name__ == "__main__":
    sys.exit(main())
