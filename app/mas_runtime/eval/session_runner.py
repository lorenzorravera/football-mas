"""
Session runner (Phase C, C2) — the multi-step / within-session memory experiment.

This is the experiment that has NOT been run before. It plays ordered conversations
(scripted turns) through four arms and measures within-session carry-over:

  arms:
    mas_memory          MAS with memory ON, hard-scoped to this session (A1 guard).
                        Memory is written BETWEEN turns, so a later turn can retrieve a
                        correction / cached SQL / prior context from an earlier turn.
    mas_no_memory       MAS with memory disabled (eval_no_memory) — ablation control.
    single_llm_stateless   one LLM+SQL-tool call per turn, NO prior-turn context.
    single_llm_history     one LLM+SQL-tool call per turn, FULL prior conversation in-context.

  sub-experiments (the session's `sub_experiment` field):
    correction    headline — turn(s) trigger a failure pattern; a later, semantically
                  similar turn should benefit from the stored correction.
    cache         near-repeat queries within a session (sql_cache reuse).
    conversation  follow-ups that reference earlier turns (context carry).

Per-turn ground truth is derived by executing the turn's `ground_truth_sql` read-only.
Eval rows are written under source='eval_session' and PURGED after each session, so live
memory is never polluted.

Correction sub-experiment — ORACLE-SEEDED failure signal (important, honest caveat):
  The live eval_agent checks only response↔data_result self-consistency and has no runtime
  ground truth, so a wrong-but-self-consistent answer (e.g. 0 corners from an unmatched
  referee name) writes no correction. For sessions carrying a `correction_lesson`, the harness
  supplies the missing signal: when a `trigger` turn is judged WRONG against ground truth, it
  seeds ONE session-scoped correction with that GENERAL lesson (the technique, not the answer).
  This isolates what the experiment measures — does memory TRANSMIT a learned fix to a later
  similar turn — from failure DETECTION (a separate problem). The beneficiary is a different
  referee/season/metric, so it must still write correct SQL: transfer, not recall. Only
  mas_memory has a store to carry it; the other arms don't. See `_seed_correction`.

Usage:
    cd Ethan/agent_v4
    python eval/session_runner.py                 # all sessions, all arms
    python eval/session_runner.py --arms mas_memory,single_llm_stateless
    python eval/session_runner.py --glob 'correction_*.json'

Outputs:
    eval/results/session_runs/<session>__<arm>.json   (per-arm transcript + verdicts)
    eval/results/session_results.csv                  (one row per turn per arm)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

import uuid

from state import create_initial_state
from graph import run_agent
from memory.vector_store_pg import purge_session, store_correction
from eval.single_llm_baseline import run_single_llm, _get_ro_conn
import psycopg2.extras

_HERE = Path(__file__).parent
SESSIONS_DIR = _HERE / "sessions"
RESULTS_DIR = _HERE / "results" / "session_runs"
RESULTS_CSV = _HERE / "results" / "session_results.csv"

ALL_ARMS = ["mas_memory", "mas_no_memory", "single_llm_stateless", "single_llm_history"]


# ---------------------------------------------------------------------------
# Ground truth + scoring
# ---------------------------------------------------------------------------

def _expected_rows(ground_truth_sql: str | None):
    """Execute ground_truth_sql read-only; return list[dict] rows, or None if no GT."""
    if not ground_truth_sql:
        return None
    try:
        conn = _get_ro_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(ground_truth_sql.strip().rstrip(";"))
            return cur.fetchall()
    except Exception:
        return None


def _numbers(text: str) -> set:
    return set(re.findall(r"\d+\.?\d*", str(text)))


def _expected_tokens(rows) -> tuple[set, set]:
    nums, names = set(), set()
    for r in rows:
        for v in r.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                nums.add(str(round(float(v), 2)).rstrip("0").rstrip("."))
            elif isinstance(v, str) and v.strip():
                names.add(v.strip().lower())
    return nums, names


def score(answer: str, rows) -> tuple[str, str]:
    """Return (verdict, reasoning). verdict in correct/partial/wrong/refused/no_gt."""
    if not answer or "error" in answer.lower()[:40]:
        return "refused", "empty or error answer"
    if rows is None:
        return "no_gt", "no ground_truth_sql provided"
    if len(rows) == 0:
        return "no_gt", "ground truth returned no rows"

    exp_nums, exp_names = _expected_tokens(rows)
    a = answer.lower()
    a_nums = _numbers(answer)

    checks, hits = 0, 0
    if exp_nums:
        # normalise expected numbers to the same string form as extracted
        for n in exp_nums:
            checks += 1
            hits += 1 if n in a_nums or n in a else 0
    for nm in list(exp_names)[:8]:
        checks += 1
        hits += 1 if nm in a else 0

    if checks == 0:
        return "no_gt", "no comparable tokens"
    frac = hits / checks
    if frac >= 0.8:
        return "correct", f"{hits}/{checks} key tokens"
    if frac >= 0.4:
        return "partial", f"{hits}/{checks} key tokens"
    return "wrong", f"{hits}/{checks} key tokens"


# ---------------------------------------------------------------------------
# Arm runners
# ---------------------------------------------------------------------------

_FAIL_VERDICTS = {"wrong", "partial", "refused"}


def _seed_correction(sid: str, turn: dict, bad_sql: str, lesson: str) -> bool:
    """Oracle-seed a session-scoped correction after a trigger that ground truth judged WRONG.

    WHY THIS EXISTS: the live eval_agent only checks response↔data_result self-consistency; it
    has no runtime ground truth, so a wrong-but-self-consistent SQL result (e.g. 0 corners from
    an unmatched referee name) scores 1.0 and writes NO correction. The session harness DOES hold
    ground truth, so for the correction sub-experiment it supplies the missing failure signal:
    when a `trigger` turn is judged wrong, it writes one correction carrying the dataset's GENERAL
    `correction_lesson` (the technique, not the answer). This isolates the experiment's actual
    question — does memory *transmit* a learned fix to a later, semantically-similar turn? — from
    the orthogonal problem of detecting the failure. The beneficiary is a DIFFERENT
    referee/season/metric, so it must still write correct SQL: transfer, not recall. Seed is
    session-scoped + source='eval_session', so it's purged with the session and never leaks live.
    """
    try:
        store_correction(
            memory_id=str(uuid.uuid4()),
            user_query=turn["query"],
            error_type="oracle_seed",
            error_message=lesson,
            bad_sql=bad_sql or "",
            stage="oracle_seed",
            session_id=sid,
            source="eval_session",
        )
        return True
    except Exception:
        return False


def _run_mas_arm(session: dict, arm: str, model: str) -> list[dict]:
    """Run an MAS arm (memory on/off) across the session's ordered turns."""
    sid = f"{session['session_id']}:{arm}"
    memory_on = (arm == "mas_memory")
    lesson = session.get("correction_lesson")
    turn_results = []
    try:
        for turn in session["turns"]:
            st = create_initial_state(turn["query"])
            st["session_id"]    = sid if memory_on else None
            st["memory_source"] = "eval_session"
            st["turn_index"]    = turn["turn_index"]
            if not memory_on:
                st["eval_no_memory"] = True

            final = run_agent(
                user_query=turn["query"],
                variant=session.get("variant", "no_control"),
                initial_state=st,
                model=model,
                experiment="session_eval",
                condition=arm,
            )
            answer = final.get("final_response", "") or ""
            data_result = final.get("data_result")
            answer_for_score = answer + (f"\n{data_result}" if data_result is not None else "")
            rows = _expected_rows(turn.get("ground_truth_sql"))
            verdict, reason = score(answer_for_score, rows)
            sql_used = final.get("sql_query") or ""
            turn_results.append({
                "turn_index": turn["turn_index"], "query": turn["query"],
                "role": turn.get("role"), "answer": answer[:500],
                "sql_query": sql_used[:300],
                "error": final.get("error"), "verdict": verdict, "reason": reason,
            })

            # Oracle-seed a correction after a FAILED trigger (mas_memory only), so the
            # later beneficiary turn can retrieve the lesson. See _seed_correction.
            if (memory_on and lesson and turn.get("role") == "trigger"
                    and verdict in _FAIL_VERDICTS):
                seeded = _seed_correction(sid, turn, sql_used, lesson)
                print(f"      ↳ oracle-seeded correction after failed trigger "
                      f"(verdict={verdict}, ok={seeded})")
    finally:
        if memory_on:
            purge_session(sid)  # never persist eval rows to live memory
    return turn_results


def _run_single_llm_arm(session: dict, arm: str, model: str) -> list[dict]:
    mode = "history" if arm == "single_llm_history" else "stateless"
    prior_turns: list[dict] = []
    turn_results = []
    for turn in session["turns"]:
        out = run_single_llm(turn["query"], model=model, mode=mode, prior_turns=prior_turns)
        answer = out["answer"]
        rows = _expected_rows(turn.get("ground_truth_sql"))
        verdict, reason = score(answer, rows)
        prior_turns.append({"query": turn["query"], "answer": answer})
        turn_results.append({
            "turn_index": turn["turn_index"], "query": turn["query"],
            "role": turn.get("role"), "answer": answer[:500],
            "sql_query": " ; ".join(out["sql_calls"])[:300],
            "error": None, "verdict": verdict, "reason": reason,
        })
    return turn_results


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_session(session: dict, arms: list[str], model: str) -> dict:
    print(f"\n=== session {session['session_id']} [{session.get('sub_experiment')}] ===")
    results = {}
    for arm in arms:
        print(f"  arm: {arm}")
        if arm.startswith("mas"):
            results[arm] = _run_mas_arm(session, arm, model)
        else:
            results[arm] = _run_single_llm_arm(session, arm, model)
        verdicts = [t["verdict"] for t in results[arm]]
        print(f"    verdicts: {verdicts}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for arm, turns in results.items():
        out = RESULTS_DIR / f"{session['session_id']}__{arm}.json"
        out.write_text(json.dumps(
            {"session": session["session_id"], "sub_experiment": session.get("sub_experiment"),
             "arm": arm, "turns": turns}, indent=2))
    return results


def _write_csv_from_transcripts() -> int:
    """(Re)build session_results.csv from ALL session_runs/*.json transcripts on disk.

    Sourcing from the saved transcripts (not just this run's in-memory rows) means a
    resumed or partial run — e.g. re-running only `--glob 'correction_*.json'` after the
    cache+conversation families already completed — still yields a COMPLETE CSV, and a
    mid-run crash never loses what already finished.
    """
    rows = []
    for jf in sorted(RESULTS_DIR.glob("*.json")):
        d = json.loads(jf.read_text())
        for t in d.get("turns", []):
            rows.append({
                "session": d["session"],
                "sub_experiment": d.get("sub_experiment"),
                "arm": d["arm"],
                **{k: t.get(k) for k in ("turn_index", "role", "verdict", "reason")},
            })
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(RESULTS_CSV, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default=",".join(ALL_ARMS), help="comma-separated arm list")
    ap.add_argument("--glob", default="*.json", help="session file glob in eval/sessions/")
    ap.add_argument("--model", default="claude")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    files = sorted(SESSIONS_DIR.glob(args.glob))
    if not files:
        print(f"No session files matching {args.glob} in {SESSIONS_DIR}")
        return 1

    failed = None
    try:
        for f in files:
            session = json.loads(f.read_text())
            run_session(session, arms, args.model)
    except Exception as e:
        # Don't lose completed sessions — the per-session transcripts are already on disk;
        # the finally below rebuilds the CSV from them. Surface the cause and exit non-zero.
        failed = e
        print(f"\n✗ run aborted on a session error: {type(e).__name__}: {str(e)[:300]}")
    finally:
        n = _write_csv_from_transcripts()
        print(f"\n✓ rebuilt {RESULTS_CSV} with {n} rows from saved transcripts")

    print("Run eval/session_report.py for per-session deltas + effect sizes.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
