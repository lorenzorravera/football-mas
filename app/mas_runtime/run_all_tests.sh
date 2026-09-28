#!/usr/bin/env bash
#
# run_all_tests.sh — one-shot runner for the agent_v4 verification suite.
#
# Runs the four DB-backed / pure-logic tests (NO LLM cost) and reports a
# pass/fail summary. Each test self-cleans its temp rows and calls
# load_dotenv(override=True), so a stale shell DATABASE_URI doesn't matter.
#
# Usage (from Ethan/agent_v4/):
#     ./run_all_tests.sh           # run all four
#     ./run_all_tests.sh -q        # quiet: only show the summary + failures
#
# Exit code: 0 if every test passes, 1 otherwise.

set -u

cd "$(dirname "$0")"

QUIET=0
[ "${1:-}" = "-q" ] && QUIET=1

# Pick a python: prefer an active venv, else python3.
PY="${PYTHON:-python}"
command -v "$PY" >/dev/null 2>&1 || PY="python3"

TESTS=(
  test_pure_logic
  test_session_isolation
  test_trajectory_capture
  test_prediction_dispatch
  test_d4_dispatch
  test_router_bandit
  test_documents_rag
)

pass=0
fail=0
failed_names=()

for t in "${TESTS[@]}"; do
  printf '== %s ==\n' "$t"
  if [ "$QUIET" -eq 1 ]; then
    # Capture output; only print it on failure.
    out="$("$PY" "eval/tests/$t.py" 2>&1)"
    rc=$?
    if [ $rc -eq 0 ]; then
      echo "  ✓ passed"
    else
      echo "$out"
    fi
  else
    "$PY" "eval/tests/$t.py"
    rc=$?
  fi

  if [ $rc -eq 0 ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failed_names+=("$t")
  fi
  echo
done

echo "============================================================"
echo "SUMMARY: $pass passed, $fail failed (of ${#TESTS[@]})"
if [ $fail -gt 0 ]; then
  echo "FAILED: ${failed_names[*]}"
  echo "============================================================"
  exit 1
fi
echo "ALL TESTS PASSED"
echo "============================================================"
exit 0
