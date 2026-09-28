"""
golden/extended.py — the EXTENDED golden set (60 items = 30 DA + 30 prediction).

Why this exists (see results/extended_eval_report.md §"DB drift"):
  The live Aiven DB was repopulated from ENG-PL-only to FIVE leagues (+ international tables)
  AFTER the original 46-item golden set was frozen. Re-running the original canonical SQL now
  returns cross-league–contaminated results (30/46 differ from the frozen ground truth), because
  those queries filtered on `season='YYYY-YYYY'` only — every league has a row for that season label.

  Fix (Till-approved: "re-scope to ENG-PL on current DB"): every canonical_sql here is EXPLICITLY
  scoped to competition ENG-PL (seasons.competition_id = 1, i.e. league_code 'ENG-PL'), and the
  ground truth is the RESULT of executing that re-scoped SQL against the CURRENT DB. For the
  questions whose underlying data did not otherwise change, the re-scoped result reproduces the
  original PL-only frozen ground truth exactly (verified in build_extended() → validation report).

Curation:
  * 30 DA questions selected from the original 46, preserving the in-/out-of-coverage split
    (18 in_coverage / 12 out_of_coverage — the original was 28/18 ≈ 61% in; 18/30 = 60% in).
  * coverage_label carried over verbatim from the frozen results/templates/coverage_labels.json.
  * 30 prediction questions: real ENG-PL 2024-2025 fixtures (the 4 originals + 26 new), spread
    across the whole season, outcome-balanced (10 H / 9 D / 11 A), 20 distinct teams.

Ground truth is NEVER an AI prose answer:
  * DA        → the structured result of the re-scoped canonical_sql.
  * prediction→ (a) model_gt: the trained model's probability vector (predict_match_outcome), for
                    tool-use fidelity; (b) actual_onehot: the realised H/D/A, for Brier accuracy.

FREEZE writes results/golden/{golden_set,ground_truth,prediction_golden}_v2.json with the SAME
sha256+timestamp+git_commit sealing mechanism as golden/freeze.py, and refuses to overwrite an
already-frozen v2 artifact (never edit a frozen artifact). The original v1 frozen files are left
untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from golden.generate import DRAFT_ITEMS
from manifest import record_phase, git_info, now_iso

OUT = Path(__file__).resolve().parent.parent / "results" / "golden"

# ENG-PL scope fragments (competition_id 1 == league_code 'ENG-PL').
ENGPL = "AND s.competition_id = 1"
# Canonical set of ENG-PL club names (for text-keyed tables: transfers, injuries).
PL_TEAM_NAMES = ("(SELECT DISTINCT t.team_name FROM teams t "
                 "JOIN team_season_standings st2 ON st2.team_id = t.team_id "
                 "JOIN seasons s2 ON s2.season_id = st2.season_id WHERE s2.competition_id = 1)")

# 30 selected question ids and their ENG-PL-scoped canonical SQL. Every SQL is a single read-only
# SELECT/WITH executed via tools.run_sql. Re-scoping = adding the competition filter (and, for the
# text-keyed transfer/injury tables, restricting to ENG-PL club names).
RESCOPED_SQL: dict[str, str] = {
    # ── team / league outcomes ─────────────────────────────────────────────
    "Q01": ("SELECT t.team_name FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} AND st.tss_rank=1"),
    "Q02": ("SELECT st.tss_points FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} AND t.team_name='Arsenal'"),
    "Q03": ("SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2022-2023' {ENGPL} ORDER BY st.tss_rank"),
    "Q05": ("SELECT t.team_name FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} ORDER BY st.tss_goal_difference DESC, t.team_name LIMIT 1"),
    "Q06": ("SELECT st.tss_points AS actual_points, (3*st.tss_wins + st.tss_draws) AS points_without_deduction "
            "FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id "
            "JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} AND t.team_name='Everton'"),
    "Q07": ("SELECT t.team_name, s.season, st.tss_points FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE 1=1 {ENGPL} ORDER BY st.tss_points DESC, t.team_name LIMIT 1"),

    # ── player season aggregates ───────────────────────────────────────────
    "Q09": ("SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} GROUP BY p.player_id, p.player_name "
            "ORDER BY goals DESC, p.player_name LIMIT 1"),
    "Q10": ("SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} GROUP BY p.player_id, p.player_name "
            "ORDER BY goals DESC, p.player_name LIMIT 5"),
    "Q11": ("SELECT p.player_name, SUM(pss.assists_pss) AS assists FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} GROUP BY p.player_id, p.player_name "
            "ORDER BY assists DESC, p.player_name LIMIT 1"),
    "Q12": ("SELECT p.player_name, SUM(pss.goals_pss) AS total_goals FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} AND p.player_name='Cole Palmer' "
            "GROUP BY p.player_id, p.player_name"),

    # ── home / away splits ─────────────────────────────────────────────────
    "Q16": ("SELECT t.team_name, ha.tshas_home_points AS home_points FROM team_season_home_away_standings ha "
            "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} ORDER BY home_points DESC, t.team_name LIMIT 1"),
    "Q18": ("SELECT t.team_name, (ha.tshas_home_points - ha.tshas_away_points) AS home_away_gap "
            "FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id "
            f"JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2023-2024' {ENGPL} "
            "ORDER BY home_away_gap DESC, t.team_name LIMIT 1"),
    "Q19": ("SELECT ha.tshas_home_points FROM team_season_home_away_standings ha "
            "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} AND t.team_name='Arsenal'"),
    "Q20": ("SELECT t.team_name, ha.tshas_home_goals_for AS home_goals FROM team_season_home_away_standings ha "
            "JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} ORDER BY home_goals DESC, t.team_name LIMIT 1"),

    # ── disciplinary ───────────────────────────────────────────────────────
    "Q21": ("SELECT t.team_name, sf.tssf_yellow_cards AS yellows FROM team_season_stats_for sf "
            "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} ORDER BY yellows DESC, t.team_name LIMIT 1"),
    "Q23": ("SELECT t.team_name, sf.tssf_red_cards AS reds FROM team_season_stats_for sf "
            "JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} ORDER BY reds DESC, t.team_name LIMIT 1"),
    "Q24": ("SELECT SUM(sf.tssf_red_cards) AS total_red_cards FROM team_season_stats_for sf "
            f"JOIN seasons s ON s.season_id=sf.season_id WHERE s.season='2023-2024' {ENGPL}"),
    "Q25": ("SELECT COUNT(*) AS matches_officiated FROM matches m JOIN seasons s ON s.season_id=m.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} AND replace(m.referee, chr(160), ' ') = 'Anthony Taylor'"),

    # ── xG over/under-performance ──────────────────────────────────────────
    "Q26": ("SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
            "ROUND(SUM(pss.goals_pss) - SUM(pss.xg_pss),2) AS overperformance FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} GROUP BY p.player_id, p.player_name "
            "HAVING SUM(pss.goals_pss) >= 10 ORDER BY overperformance DESC, p.player_name LIMIT 1"),
    "Q27": ("SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
            "ROUND(SUM(pss.xg_pss) - SUM(pss.goals_pss),2) AS underperformance FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2023-2024' {ENGPL} GROUP BY p.player_id, p.player_name "
            "HAVING SUM(pss.goals_pss) >= 10 ORDER BY underperformance DESC, p.player_name LIMIT 1"),
    "Q29": ("SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, "
            "ROUND(SUM(pss.goals_pss)/NULLIF(SUM(pss.xg_pss),0),3) AS goals_per_xg FROM player_season_stats pss "
            "JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} GROUP BY p.player_id, p.player_name "
            "HAVING SUM(pss.xg_pss) >= 15 ORDER BY goals_per_xg DESC, p.player_name LIMIT 1"),

    # ── market / transfers (text-keyed to_team → restrict to PL club names) ─
    "Q32": ("SELECT p.player_name, MAX(tr.to_team) AS to_team, tr.season, tr.transfer_fee "
            "FROM player_transfers tr JOIN players p ON p.player_id=tr.player_id "
            f"WHERE tr.to_team IN {PL_TEAM_NAMES} AND tr.transfer_fee IS NOT NULL "
            "GROUP BY p.player_id, p.player_name, tr.season, tr.transfer_fee "
            "ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 5"),
    "Q33": ("SELECT p.player_name, tr.to_team, tr.transfer_fee FROM player_transfers tr "
            "JOIN players p ON p.player_id=tr.player_id "
            f"WHERE tr.season='2023-2024' AND tr.to_team IN {PL_TEAM_NAMES} AND tr.transfer_fee IS NOT NULL "
            "ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 1"),

    # ── availability / injuries (text-keyed team → restrict to PL club names)
    "Q37": ("SELECT p.player_name, SUM(pis.days_missed) AS total_days_missed FROM player_injury_spells pis "
            "JOIN players p ON p.player_id=pis.player_id "
            f"WHERE pis.season='2023-2024' AND pis.team IN {PL_TEAM_NAMES} "
            "GROUP BY p.player_id, p.player_name ORDER BY total_days_missed DESC NULLS LAST, p.player_name LIMIT 1"),
    "Q39": ("SELECT COUNT(*) AS spells FROM player_injury_spells pis "
            "WHERE pis.season='2023-2024' AND pis.team='Brentford'"),

    # ── event-level / player-match (already league-scoped via league_code) ──
    "Q41": ("SELECT p.player_name, pmp.game_id, pmp.match_goals FROM player_match_performance pmp "
            "JOIN players p ON p.player_id=pmp.player_id "
            "WHERE pmp.season='2024-2025' AND pmp.league_code='ENG-PL' "
            "ORDER BY pmp.match_goals DESC, p.player_name LIMIT 5"),
    "Q42": ("SELECT p.player_name, SUM(pmp.fouls) AS fouls FROM player_match_performance pmp "
            "JOIN players p ON p.player_id=pmp.player_id "
            "WHERE pmp.season='2023-2024' AND pmp.league_code='ENG-PL' "
            "GROUP BY p.player_id, p.player_name HAVING SUM(pmp.fouls) IS NOT NULL "
            "ORDER BY fouls DESC, p.player_name LIMIT 1"),
    "Q44": ("SELECT ht.team_name AS home_team, at.team_name AS away_team, m.home_score, m.away_score "
            "FROM matches m JOIN seasons s ON s.season_id=m.season_id "
            "JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id "
            f"WHERE s.season='2024-2025' {ENGPL} ORDER BY (m.home_score - m.away_score) DESC, m.home_score DESC LIMIT 1"),

    # ── edge cases ─────────────────────────────────────────────────────────
    "Q45": ("SELECT st.tss_points FROM team_season_standings st "
            "JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id "
            f"WHERE s.season='2024-2025' {ENGPL} AND t.team_name='Norwich City'"),
    "Q46": ("SELECT COUNT(*) AS matches_with_attendance FROM matches m JOIN seasons s ON s.season_id=m.season_id "
            f"WHERE s.season='2020-2021' {ENGPL} AND m.attendance_m IS NOT NULL"),
}

SELECTED_IDS = list(RESCOPED_SQL)   # 30, insertion order above
EXPECT_EMPTY = {"Q45"}              # Norwich City not in the PL in 2024-2025 (empty is correct)

# 30 ENG-PL 2024-2025 fixtures for the prediction slice: (home, away, date, actual H/D/A).
# The first four are the original P01–P04 fixtures (preserved); the rest are new, spread across the
# whole season and outcome-balanced.
PREDICTION_FIXTURES = [
    ("Manchester United", "Fulham", "2024-08-16", "H"),
    ("Arsenal", "Wolves", "2024-08-17", "H"),
    ("Everton", "Brighton", "2024-08-17", "A"),
    ("Nottingham Forest", "Bournemouth", "2024-08-17", "D"),
    ("Chelsea", "Crystal Palace", "2024-09-01", "D"),
    ("Southampton", "Manchester United", "2024-09-14", "A"),
    ("Brentford", "West Ham United", "2024-09-28", "D"),
    ("Leicester City", "Bournemouth", "2024-10-05", "H"),
    ("Fulham", "Aston Villa", "2024-10-19", "A"),
    ("Wolves", "Manchester City", "2024-10-20", "A"),
    ("Ipswich Town", "Leicester City", "2024-11-02", "D"),
    ("Arsenal", "Nottingham Forest", "2024-11-23", "H"),
    ("Newcastle United", "West Ham United", "2024-11-25", "A"),
    ("Newcastle United", "Liverpool", "2024-12-04", "D"),
    ("Aston Villa", "Manchester City", "2024-12-21", "H"),
    ("Tottenham Hotspur", "Liverpool", "2024-12-22", "A"),
    ("Brighton", "Brentford", "2024-12-27", "D"),
    ("West Ham United", "Fulham", "2025-01-14", "H"),
    ("Ipswich Town", "Brighton", "2025-01-16", "A"),
    ("Manchester City", "Chelsea", "2025-01-25", "H"),
    ("Crystal Palace", "Everton", "2025-02-15", "A"),
    ("Everton", "Manchester United", "2025-02-22", "D"),
    ("Nottingham Forest", "Arsenal", "2025-02-26", "D"),
    ("Fulham", "Tottenham Hotspur", "2025-03-16", "H"),
    ("Southampton", "Crystal Palace", "2025-04-02", "D"),
    ("Southampton", "Aston Villa", "2025-04-12", "A"),
    ("Tottenham Hotspur", "Nottingham Forest", "2025-04-21", "A"),
    ("Wolves", "Leicester City", "2025-04-26", "H"),
    ("Newcastle United", "Chelsea", "2025-05-11", "H"),
    ("Ipswich Town", "West Ham United", "2025-05-25", "A"),
]

_ONEHOT = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}   # order: home, draw, away


def _sha256(items: list) -> str:
    """Same stable hash as golden/freeze.py: canonical JSON, sorted keys."""
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _draft_by_id() -> dict:
    return {it["id"]: it for it in DRAFT_ITEMS}


def build_extended_da() -> tuple[list, list, dict]:
    """Execute every re-scoped canonical SQL and validate against the original v1 frozen GT.

    Returns (golden_items, ground_truth_items, validation). golden_items carry question metadata +
    re-scoped canonical_sql + coverage_label; ground_truth_items carry the executed structured result.
    """
    from tools.run_sql import run_sql

    draft = _draft_by_id()
    cov = {it["id"]: it["coverage_label"]
           for it in json.loads((OUT.parent / "templates" / "coverage_labels.json").read_text())["items"]}
    v1_gt = {it["id"]: (it.get("ground_truth") or {})
             for it in json.loads((OUT / "ground_truth.json").read_text())["items"]}

    def _norm(rows):
        return sorted([tuple(str(v) for v in r) for r in (rows or [])])

    golden, gtruth, validation = [], [], {"reproduced_v1": [], "changed_vs_v1": [], "errors": []}
    for qid in SELECTED_IDS:
        meta = draft[qid]
        sql = RESCOPED_SQL[qid]
        item = {k: meta[k] for k in ("id", "question", "category", "difficulty", "gt_type", "answer_type")}
        item["canonical_sql"] = sql
        item["coverage_label"] = cov[qid]
        item["notes"] = "ENG-PL re-scoped (competition_id=1) on the multi-league DB."
        item["tags"] = ["extended_v2"]
        golden.append(item)

        try:
            res = run_sql(sql, max_rows=100)
            gt = {"columns": res["columns"], "rows": res["rows"],
                  "row_count": res["row_count"], "truncated": res["truncated"]}
            status = ("empty_expected" if (res["row_count"] == 0 and qid in EXPECT_EMPTY)
                      else "EMPTY" if res["row_count"] == 0 else "ok")
            # validation vs the original PL-only frozen ground truth
            if _norm(res["rows"]) == _norm(v1_gt.get(qid, {}).get("rows")):
                validation["reproduced_v1"].append(qid)
            else:
                validation["changed_vs_v1"].append(
                    {"id": qid, "v1_rows": v1_gt.get(qid, {}).get("row_count"),
                     "v2_rows": res["row_count"]})
        except Exception as e:  # noqa: BLE001
            gt = None
            status = "ERROR"
            validation["errors"].append({"id": qid, "error": str(e)[:200]})
        gtruth.append({**item, "ground_truth": gt, "status": status})
    return golden, gtruth, validation


def build_extended_predictions() -> list:
    """For each fixture: model_gt (predict_match_outcome vector) + actual_onehot."""
    from tools.predict_match_outcome import predict_match_outcome

    items = []
    for i, (home, away, date, actual) in enumerate(PREDICTION_FIXTURES, 1):
        model_gt = predict_match_outcome(home, away, match_date=date)
        items.append({
            "id": f"P{i:02d}", "category": "prediction", "difficulty": "medium",
            "gt_type": "prediction", "answer_type": "probability_vector",
            "question": (f"Predict the outcome of {home} vs {away} on {date} — give the home win, "
                         "draw and away win probabilities."),
            "home_team": home, "away_team": away, "match_date": date, "actual": actual,
            "model_gt": model_gt, "actual_onehot": _ONEHOT[actual], "tags": ["extended_v2"],
        })
    return items


def build_candidates() -> dict:
    """Write the (unfrozen) candidate files + a human-readable appendix. No hashing yet."""
    OUT.mkdir(parents=True, exist_ok=True)
    golden, gtruth, validation = build_extended_da()
    preds = build_extended_predictions()

    (OUT / "golden_set_v2.candidate.json").write_text(
        json.dumps({"frozen": False, "items": golden}, indent=2, default=str))
    (OUT / "ground_truth_v2.candidate.json").write_text(
        json.dumps({"frozen": False, "items": gtruth, "validation": validation}, indent=2, default=str))
    (OUT / "prediction_golden_v2.candidate.json").write_text(
        json.dumps({"frozen": False, "items": preds}, indent=2, default=str))

    from collections import Counter
    cov_counts = Counter(it["coverage_label"] for it in golden)
    print(f"DA: {len(golden)} items  coverage={dict(cov_counts)}")
    print(f"  reproduced v1 GT exactly: {len(validation['reproduced_v1'])}/{len(golden)}  "
          f"-> {validation['reproduced_v1']}")
    print(f"  changed vs v1 (data grew / re-scoped diff): {validation['changed_vs_v1']}")
    print(f"  errors: {validation['errors']}")
    print(f"Prediction: {len(preds)} items  outcomes={dict(Counter(p['actual'] for p in preds))}")
    pred_err = [p['id'] for p in preds if (p['model_gt'] or {}).get('error')]
    print(f"  prediction model errors: {pred_err or 'none'}")
    return {"golden": golden, "ground_truth": gtruth, "predictions": preds, "validation": validation}


def _seal(artifact: str, items: list, meta: dict, phase: str, extra: dict | None = None) -> tuple[Path, str]:
    h = _sha256(items)
    doc = {"frozen": True, "phase": phase, "artifact": artifact,
           "scope": "ENG-PL (competition_id=1), seasons 2020-2021..2024-2025",
           "basis": "extended v2 — 30 DA (re-scoped) + 30 prediction; multi-league DB",
           "generated_at": meta["ts"], "git_commit": meta["git_commit"], "git_dirty": meta["git_dirty"],
           "n_items": len(items), "sha256": h, **(extra or {}), "items": items}
    path = OUT / f"{artifact}.json"
    path.write_text(json.dumps(doc, indent=2, default=str))
    return path, h


def freeze(force: bool = False) -> dict:
    targets = [OUT / f"{a}.json" for a in ("golden_set_v2", "ground_truth_v2", "prediction_golden_v2")]
    existing = [p for p in targets if p.exists()]
    if existing and not force:
        raise SystemExit(
            f"Refusing to overwrite already-frozen v2 artifact(s): {[p.name for p in existing]}. "
            "Frozen artifacts must not be edited. Delete by hand and pass --force to re-freeze.")

    gs = json.loads((OUT / "golden_set_v2.candidate.json").read_text())["items"]
    gtc = json.loads((OUT / "ground_truth_v2.candidate.json").read_text())
    gt, validation = gtc["items"], gtc.get("validation", {})
    pr = json.loads((OUT / "prediction_golden_v2.candidate.json").read_text())["items"]

    gi = git_info()
    meta = {"ts": now_iso(), **gi}
    gs_path, gs_h = _seal("golden_set_v2", gs, meta, "2b")
    gt_path, gt_h = _seal("ground_truth_v2", gt, meta, "2b", {"validation": validation})
    pr_path, pr_h = _seal("prediction_golden_v2", pr, meta, "7b")

    entry = {
        "frozen_at": meta["ts"], "git_commit": gi["git_commit"], "git_dirty": gi["git_dirty"],
        "scope": "ENG-PL (competition_id=1), seasons 2020-2021..2024-2025",
        "memory_enabled": False,
        "files": {
            "golden_set_v2.json": {"sha256": gs_h, "n_items": len(gs)},
            "ground_truth_v2.json": {"sha256": gt_h, "n_items": len(gt)},
            "prediction_golden_v2.json": {"sha256": pr_h, "n_items": len(pr)},
        },
        "note": "Extended set. DA canonical_sql re-scoped to ENG-PL on the multi-league DB; ground "
                "truth = result of executing it. Prediction model_gt = predict_match_outcome vector.",
    }
    record_phase("phase2b_extended_golden_set", entry)
    print("FROZEN (extended v2):")
    for name, h, n in [("golden_set_v2", gs_h, len(gs)), ("ground_truth_v2", gt_h, len(gt)),
                       ("prediction_golden_v2", pr_h, len(pr))]:
        print(f"  {name}.json  n={n}  sha256={h}")
    print(f"  git_commit={gi['git_commit']}  dirty={gi['git_dirty']}")
    return entry


if __name__ == "__main__":
    import sys
    if "freeze" in sys.argv:
        freeze(force="--force" in sys.argv)
    else:
        build_candidates()
