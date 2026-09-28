"""
Phase 2/3 — seeded-correction transfer experiment (SYNTHETIC siblings only).

Context: the frozen golden set has ZERO valid siblings for the 3 patterns (each is a
singleton; same-pattern Qs either pass unprompted or use a different table). So per
instruction we use ONE clearly-labelled synthetic sibling per pattern, GT computed
live from canonical-style SQL. Results are SUPPLEMENTARY (no golden-sourced transfer
test was possible).

Isolation: production correction_memory holds 186 polluted rows (RateLimitError noise),
so we do NOT touch it. We intercept the three retrieval fns with real embeddings + the
real (1+cos)/2 >= 0.75 threshold against a controlled candidate pool:
  - conversation memory -> [] (constant, neutralized)
  - sql_cache -> None (already bypassed under EVAL_MODE=golden)
  - correction memory -> [] (empty arm) or [seed] (seeded arm)
The seed is stored under the SOURCE question text; retrieval is tested on the SIBLING
(different question) -> this tests TRANSFER, not memorization. Seeds describe the
failure PATTERN, never the corrected SQL for the sibling.
"""
import os, json, warnings
os.environ["EVAL_MODE"] = "golden"
warnings.filterwarnings("ignore")
import re

import graph  # sets up sys.path
from graph import run_agent
from state import create_initial_state
from db.connection import read_sql
import memory.memory_agent as mem_agent
from memory.vector_store_pg import _embed

N = 3  # runs per arm

# ----- scorer (same as eval_memory_ablation) -----
def _nums(t): return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", str(t))]
def _num_in(x, pool):
    tol = max(0.5, abs(x) * 0.01); return any(abs(x - p) <= tol for p in pool)
def _cells(row):
    nums, strs = [], []
    for v in row:
        if isinstance(v, bool): continue
        if isinstance(v, (int, float)): nums.append(float(v))
        elif isinstance(v, str) and re.search(r"[A-Za-z]{3,}", v): strs.append(v.strip().lower())
    return nums, strs
_DENIAL = ["no data","not in","didn't","did not","no record","not present","not available",
           "weren't","were not","wasn't","not found","no results"]
def score_answer(answer, gt):
    if not answer or not answer.strip(): return "refused"
    if not gt or gt.get("row_count", 0) == 0:
        al = answer.lower(); return "correct" if any(p in al for p in _DENIAL) else "wrong"
    rows = gt.get("rows", [])
    if not rows: return "refused"
    al = answer.lower(); a = _nums(answer); cov = 0
    for row in rows:
        nums, strs = _cells(row)
        if (all(_num_in(n, a) for n in nums) if nums else True) and (all(s in al for s in strs) if strs else True):
            cov += 1
    r = cov / len(rows)
    return "correct" if r >= 0.8 else ("partial" if r >= 0.4 else "wrong")

# ----- cosine similarity matching the production formula: sim = (1+cos)/2 -----
import math
def _sim(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a)); nb = math.sqrt(sum(y*y for y in b))
    cos = dot / (na * nb) if na and nb else 0.0
    return (1.0 + cos) / 2.0
CORR_THRESHOLD = 0.75

# ----- the 3 patterns: source question, synthetic sibling, GT SQL, pattern seed -----
PATTERNS = {
  "P_ref": {
    "source": "How many Premier League matches did referee Anthony Taylor officiate in 2023-2024?",
    "sibling": "How many Premier League matches did referee Michael Oliver officiate in 2023-2024?",
    "gt_sql": ("SELECT COUNT(*) AS matches_officiated FROM matches m JOIN seasons s ON s.season_id=m.season_id "
               "JOIN competitions c ON s.competition_id=c.competition_id WHERE c.league_code='ENG-PL' "
               "AND s.season='2023-2024' AND replace(m.referee, chr(160), ' ')='Michael Oliver'"),
    "seed": ("When filtering matches by referee name (matches.referee), exact equality frequently returns 0 "
             "because the stored values contain a non-breaking space (Unicode chr(160)) instead of a normal "
             "space. Normalize before comparing: WHERE replace(referee, chr(160), ' ') = '<name>'."),
  },
  "P_tssf": {
    "source": "Which team received the most yellow cards in 2023-2024?",
    "sibling": "Which team received the most yellow cards in 2024-2025?",
    "gt_sql": ("SELECT t.team_name, sf.tssf_yellow_cards AS yellows FROM team_season_stats_for sf "
               "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
               "JOIN competitions c ON s.competition_id=c.competition_id WHERE c.league_code='ENG-PL' "
               "AND s.season='2024-2025' ORDER BY yellows DESC, t.team_name LIMIT 1"),
    "seed": ("Team-level disciplinary totals (yellow cards, red cards, fouls) must be read from "
             "team_season_stats_for (columns tssf_yellow_cards, tssf_red_cards, ...), NOT summed from the wide "
             "matches table. Summing home_yellow_cards/away_yellow_cards across matches undercounts the true "
             "season total and yields a wrong figure."),
  },
  "P_join": {
    "source": "Which player attempted the most shots (from event data) in 2023-2024?",
    "sibling": "Which player attempted the most shots (from event data) in 2024-2025?",
    "gt_sql": ("SELECT p.player_name, COUNT(*) AS shots FROM match_events e JOIN players p ON p.player_id=e.player_id "
               "WHERE e.season='2024-2025' AND e.league_code='ENG-PL' AND e.is_shot=TRUE "
               "GROUP BY p.player_id, p.player_name ORDER BY shots DESC, p.player_name LIMIT 1"),
    "seed": ("match_events.player_name is frequently NULL. To report a player's name for any event-data "
             "aggregation over match_events, resolve the name by JOINing match_events.player_id to "
             "players.player_id and selecting players.player_name. Do NOT select match_events.player_name."),
  },
}

# precompute GT + seed embeddings
for pat, d in PATTERNS.items():
    df = read_sql(d["gt_sql"])
    d["gt"] = {"rows": df.values.tolist(), "row_count": len(df), "columns": list(df.columns)}
    d["seed_emb"] = _embed(d["source"])  # seed is stored under the SOURCE question text

# ----- retrieval interception -----
_active_seed = {"pat": None}  # None => empty arm; pat key => seeded arm
_orig_retrieval = mem_agent.memory_retrieval_agent

def patched_retrieval(state):
    if state.get("eval_no_memory") or "user_query" not in state:
        return state
    import uuid
    uq = state["user_query"]
    state["memory_id"] = str(uuid.uuid4())
    state["memory_context"] = []          # neutralized (constant across arms)
    state["cached_sql"] = None            # cache off
    state["sql_cache_hit"] = False
    state["sql_cache_meta"] = None
    warnings_out, fired_sim = [], None
    if _active_seed["pat"]:
        d = PATTERNS[_active_seed["pat"]]
        sim = _sim(_embed(uq), d["seed_emb"])
        fired_sim = sim
        if sim >= CORR_THRESHOLD:
            warnings_out = [{"error_type": "eval_seed", "error_message": d["seed"],
                             "bad_sql": "", "stage": "eval_seed", "similarity": round(sim, 4)}]
    state["memory_warnings"] = warnings_out
    state["_seed_sim"] = fired_sim
    return state

mem_agent.memory_retrieval_agent = patched_retrieval
# graph.py imported the symbol directly; patch there too
graph.memory_retrieval_agent = patched_retrieval

def run_arm(pat, sibling, gt, seeded):
    _active_seed["pat"] = pat if seeded else None
    runs = []
    for i in range(N):
        st = create_initial_state(sibling)
        out = run_agent(sibling, variant="no_control", verbose=False, initial_state=st)
        sql = out.get("sql_query", ""); resp = out.get("final_response", "")
        err = out.get("error"); sim = out.get("_seed_sim")
        verdict = "refused" if err else score_answer(resp, gt)
        runs.append({"verdict": verdict, "sql": " ".join(sql.split()), "resp": resp[:200],
                     "seed_sim": sim, "fired": bool(sim and sim >= CORR_THRESHOLD), "err": err})
    return runs

report = {}
for pat, d in PATTERNS.items():
    print(f"\n{'='*78}\n{pat}  sibling: {d['sibling']}")
    print(f"  GT: {json.dumps(d['gt'], default=str)}")
    empty = run_arm(pat, d["sibling"], d["gt"], seeded=False)
    seeded = run_arm(pat, d["sibling"], d["gt"], seeded=True)
    ev = [r["verdict"] for r in empty]; sv = [r["verdict"] for r in seeded]
    fired = [r["fired"] for r in seeded]; sims = [r["seed_sim"] for r in seeded]
    sql_changed = empty[0]["sql"] != seeded[0]["sql"]
    print(f"  EMPTY  verdicts={ev}")
    print(f"     SQL: {empty[0]['sql'][:280]}")
    print(f"  SEEDED verdicts={sv}  warning_fired={fired}  sims={[round(s,3) if s else None for s in sims]}")
    print(f"     SQL: {seeded[0]['sql'][:280]}")
    print(f"  SQL_CHANGED_arm0={sql_changed}")
    report[pat] = {"sibling": d["sibling"], "gt": d["gt"], "seed": d["seed"],
                   "empty": empty, "seeded": seeded,
                   "empty_verdicts": ev, "seeded_verdicts": sv,
                   "warning_fired": fired, "seed_sims": sims, "sql_changed_arm0": sql_changed}

json.dump(report, open("phase23_results.json", "w"), indent=2, default=str)
print("\n\nWROTE phase23_results.json")
