"""
conditions/single_llm.py — the two single-LLM conditions (no MAS orchestration).

(a) run_single_llm_tools  — single LLM + the SAME tools (run_sql + predict_match_outcome) via native
    function-calling. Identical schema context to every other condition; the only difference from the
    MAS is that there is NO orchestration (one model, one loop).
(b) run_single_llm_rawdata — single LLM + raw data only: schema + an inlined text dump of the core
    tables, NO tools, NO DB, NO web. Answers purely from inlined context.

⚠️ RAW-DATA SCOPE (needs Till's sign-off): the dump inlines the small modelling tables
(team-season standings/home-away/stats, player-season, matches). The huge tables (match_events ~3M
rows, player_match_performance, and by default market_values/transfers/injuries) are NOT inlined —
so event/market/transfer/availability questions are unanswerable in this condition by construction.
This is configurable via RAW_DUMP_TABLES.
"""

from __future__ import annotations

import time

import re

from config import call_llm, set_trace_context, clear_trace_context, get_token_usage, LANGFUSE_ENABLED
from conditions.agent_core import run_tool_agent
from conditions.sql_agent import _PREAMBLE
from tools.run_sql import run_sql
from tools.schema_context import get_schema_context

# ---- (a) single LLM + tools -------------------------------------------------
_TOOLS_SYSTEM = (_PREAMBLE +
                 "\nUse the provided tools to answer: `run_sql` to query the database, and "
                 "`predict_match_outcome` to forecast a fixture's result. Then answer.\n"
                 "Database schema:\n{schema}\n")


def run_single_llm_tools(question: str, model: str, question_id: str = "", repeat: int = 0,
                         experiment: str = "mas_vs_single") -> dict:
    tid = f"{experiment}|single_llm_tools|{model}|{question_id}|r{repeat}"
    set_trace_context(tid, "single_llm_tools", [experiment, "single_llm_tools", str(model)])
    try:
        system = _TOOLS_SYSTEM.format(schema=get_schema_context())
        rec = run_tool_agent(question, model=model, system_prompt=system,
                             tool_names=["run_sql", "predict_match_outcome"],
                             question_id=question_id, condition="single_llm_tools")
        rec["experiment"] = experiment
        rec["langfuse_trace_id"] = tid
        rec["repeat"] = repeat
        rec["token_usage"] = get_token_usage()
        return rec
    finally:
        clear_trace_context()


# ---- (b) single LLM + raw data only ----------------------------------------
# Compact dumps of the core tables (one SELECT each, joined to readable names).
# All dumps are scoped to ENG-PL (seasons.competition_id=1): the DB is multi-league, but this is a
# Premier League system and the golden set is ENG-PL, so the inlined "raw data" is the PL slice.
RAW_DUMP_TABLES: dict[str, str] = {
    "standings": (
        "SELECT s.season, t.team_name, st.tss_rank, st.tss_wins, st.tss_draws, st.tss_losses, "
        "st.tss_goals_for, st.tss_goals_against, st.tss_goal_difference, st.tss_points "
        "FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id "
        "JOIN seasons s ON s.season_id=st.season_id WHERE s.competition_id=1 ORDER BY s.season, st.tss_rank"),
    "home_away": (
        "SELECT s.season, t.team_name, ha.tshas_home_points, ha.tshas_away_points, "
        "ha.tshas_home_wins, ha.tshas_away_wins, ha.tshas_home_goals_for, ha.tshas_away_goals_for "
        "FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id "
        "JOIN seasons s ON s.season_id=ha.season_id WHERE s.competition_id=1 ORDER BY s.season, t.team_name"),
    "team_discipline": (
        "SELECT s.season, t.team_name, sf.tssf_yellow_cards, sf.tssf_red_cards, sf.tssf_goals, "
        "sf.tssf_shots, sf.tssf_possession_percentage FROM team_season_stats_for sf "
        "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
        "WHERE s.competition_id=1 ORDER BY s.season, t.team_name"),
    "player_season": (
        "SELECT s.season, t.team_name, p.player_name, pss.goals_pss, pss.assists_pss, pss.minutes_pss, "
        "pss.xg_pss, pss.yellow_cards_pss, pss.red_cards_pss, pss.shots_pss FROM player_season_stats pss "
        "JOIN players p ON p.player_id=pss.player_id JOIN teams t ON t.team_id=pss.team_id "
        "JOIN seasons s ON s.season_id=pss.season_id WHERE s.competition_id=1 ORDER BY s.season, pss.goals_pss DESC"),
}

_dump_cache: dict | None = None


def _csv(res: dict) -> str:
    head = ",".join(res["columns"])
    body = "\n".join(",".join("" if v is None else str(v) for v in row) for row in res["rows"])
    return head + "\n" + body


def build_raw_dump(tables: list[str] | None = None) -> str:
    global _dump_cache
    keys = tables or list(RAW_DUMP_TABLES)
    cache_key = ",".join(keys)
    if _dump_cache and _dump_cache.get("key") == cache_key:
        return _dump_cache["text"]
    parts = []
    for k in keys:
        res = run_sql(RAW_DUMP_TABLES[k], max_rows=5000)
        parts.append(f"## TABLE {k} ({res['row_count']} rows)\n{_csv(res)}")
    text = "\n\n".join(parts)
    _dump_cache = {"key": cache_key, "text": text}
    return text


def run_single_llm_rawdata(question: str, model: str, question_id: str = "",
                           tables: list[str] | None = None, repeat: int = 0) -> dict:
    t0 = time.time()
    tid = f"mas_vs_single|single_llm_rawdata|{model}|{question_id}|r{repeat}"
    set_trace_context(tid, "single_llm_rawdata", ["mas_vs_single", "single_llm_rawdata", str(model)])
    try:
        dump = build_raw_dump(tables)
        system = (_PREAMBLE + "\nYou have NO tools and NO database access. Answer ONLY from the schema and "
                  "the inlined data below. If the data needed is not present, say so.\n"
                  f"\nSchema:\n{get_schema_context()}\n\n=== INLINED DATA ===\n{dump}\n")
        answer = call_llm([{"role": "system", "content": system}, {"role": "user", "content": question}],
                          model=model)
        return {
            "question_id": question_id, "question": question, "condition": "single_llm_rawdata",
            "model": model, "answer": answer, "tool_sequence": [], "trace": [],
            "langfuse_trace_id": tid, "repeat": repeat,
            "raw_dump_tables": tables or list(RAW_DUMP_TABLES),
            "raw_dump_chars": len(dump), "token_usage": get_token_usage(),
            "latency_s": round(time.time() - t0, 2),
        }
    finally:
        clear_trace_context()


# ---- (c) single LLM + raw data, PREDICTION (Option A: LLM-as-forecaster) -----
def _recent_matches_text(team_name: str, before_date: str, n: int = 10) -> str:
    """Causal: a team's last `n` matches strictly BEFORE `before_date` (results only)."""
    res = run_sql(
        "SELECT m.match_date, ht.team_name AS home, at.team_name AS away, m.home_score, m.away_score "
        "FROM matches m JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id "
        "WHERE (ht.team_name=:t OR at.team_name=:t) AND m.match_date < :d "
        "ORDER BY m.match_date DESC LIMIT :n",
        params={"t": team_name, "d": before_date, "n": n})
    lines = [f"{r[0]}: {r[1]} {r[3]}-{r[4]} {r[2]}" for r in res["rows"]]
    return f"{team_name} — last {len(lines)} matches before {before_date}:\n" + "\n".join(lines)


_PROB_RE = re.compile(r"home\s*=\s*([0-9.]+).*?draw\s*=\s*([0-9.]+).*?away\s*=\s*([0-9.]+)",
                      re.IGNORECASE | re.DOTALL)


def _parse_prob_vector(answer: str) -> dict | None:
    m = _PROB_RE.search(answer or "")
    if not m:
        return None
    h, d, a = (float(m.group(i)) for i in (1, 2, 3))
    s = h + d + a
    if s <= 0:
        return None
    return {"home_win": round(h / s, 3), "draw": round(d / s, 3), "away_win": round(a / s, 3)}


def run_single_llm_rawdata_prediction(question: str, home_team: str, away_team: str, match_date: str,
                                      model: str, question_id: str = "", repeat: int = 0,
                                      experiment: str = "prediction") -> dict:
    """Forecast H/D/A from inlined causal recent-match data only — NO model, NO tools (Option A)."""
    t0 = time.time()
    tid = f"{experiment}|single_llm_rawdata|{model}|{question_id}|r{repeat}"
    set_trace_context(tid, "single_llm_rawdata", [experiment, "single_llm_rawdata", str(model)])
    try:
        dump = (_recent_matches_text(home_team, match_date) + "\n\n"
                + _recent_matches_text(away_team, match_date))
        system = (_PREAMBLE + "\nYou have NO tools and NO prediction model — forecast using ONLY the "
                  "recent results below. Reason about form, then give CALIBRATED probabilities for "
                  f"{home_team} (home) vs {away_team} on {match_date} that sum to 1.0.\n\n"
                  f"=== RECENT RESULTS ===\n{dump}\n\n"
                  "End your answer with EXACTLY this line:\nPROBABILITIES: home=<p>, draw=<p>, away=<p>")
        answer = call_llm([{"role": "system", "content": system}, {"role": "user", "content": question}],
                          model=model)
        return {
            "question_id": question_id, "question": question, "experiment": experiment,
            "condition": "single_llm_rawdata", "model": model, "repeat": repeat,
            "answer": answer, "tool_sequence": [], "trace": [],
            "prediction_vector": _parse_prob_vector(answer),
            "langfuse_trace_id": tid, "langfuse_enabled": LANGFUSE_ENABLED,
            "raw_dump_chars": len(dump), "token_usage": get_token_usage(),
            "latency_s": round(time.time() - t0, 2),
        }
    finally:
        clear_trace_context()


if __name__ == "__main__":
    dump = build_raw_dump()
    print(f"raw dump: {len(dump):,} chars (~{len(dump)//4:,} tokens) over {list(RAW_DUMP_TABLES)}")
