-- =============================================================================
-- A2 — Trajectory log: per-turn substrate for the router bandit (Phase E) and the
-- Phase-5 preference model. Written from run_agent() AFTER the graph stream
-- completes — NEVER threaded through AgentState (LangGraph DataFrame-serialization
-- constraint). Idempotent; safe to re-run.
-- =============================================================================

CREATE TABLE IF NOT EXISTS trajectory_log (
    query_id             TEXT PRIMARY KEY,      -- = memory_id for the turn
    session_id           TEXT,
    turn_index           INTEGER,
    ts                   TIMESTAMPTZ DEFAULT NOW(),
    experiment           TEXT,                  -- 'live' | 'session_eval' | 'mas_vs_single' | ...
    condition            TEXT,                  -- 'mas' | 'single_llm_tools' | ...
    model                TEXT,
    variant              TEXT,
    intent               TEXT,
    arm                  TEXT,                  -- canonical 'model|variant|intent'
    context_features     JSONB,
    full_trajectory_json JSONB,
    thumbs               INTEGER,               -- +1 / -1 / NULL
    latency_ms           INTEGER,
    token_cost           INTEGER,
    eval_score           REAL
);

CREATE INDEX IF NOT EXISTS trajectory_log_session_idx    ON trajectory_log (session_id);
CREATE INDEX IF NOT EXISTS trajectory_log_arm_idx        ON trajectory_log (arm);
CREATE INDEX IF NOT EXISTS trajectory_log_experiment_idx ON trajectory_log (experiment);
