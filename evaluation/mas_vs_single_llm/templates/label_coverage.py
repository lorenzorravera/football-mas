"""
templates/label_coverage.py — assign frozen coverage labels (Phase 3).

For every golden question, try every template with best-effort parameter binding and check whether
ANY template's output REPRODUCES the frozen canonical ground truth. The label is decided here, by
template-vs-ground-truth matching — NEVER by what an agent does at runtime.

Reads (read-only) the FROZEN golden_set.json + ground_truth.json. Emits a CANDIDATE
coverage_labels + a coverage matrix for review; freezing is a separate approved step.

Matching = row-containment: a template covers a question if, for some binding, every ground-truth
row's value-set is contained in some template output row (numeric tolerance 2dp). A bare league-wide
aggregate (single numeric cell, no entity in the question) is NOT coverable by these entity/leaderboard
templates and is labelled out_of_coverage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from templates.library import TEMPLATES
from tools.run_sql import run_sql, SqlNotAllowed

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "results" / "golden"
OUT_DIR = Path(__file__).resolve().parent.parent / "results" / "templates"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_N = 50
_TEAM_NAMES: list[str] = []


def _team_names() -> list[str]:
    global _TEAM_NAMES
    if not _TEAM_NAMES:
        _TEAM_NAMES = [r[0] for r in run_sql("SELECT team_name FROM teams ORDER BY length(team_name) DESC")["rows"]]
    return _TEAM_NAMES


def _derive_params(canonical_sql: str) -> dict:
    """Best-effort extraction of season(s) and team(s) from the canonical SQL."""
    seasons = re.findall(r"(\d{4}-\d{4})", canonical_sql or "")
    teams = [name for name in _team_names() if f"'{name}'" in (canonical_sql or "")]
    return {"seasons": list(dict.fromkeys(seasons)), "teams": teams}


def _norm(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v).strip()


def _row_sig(row) -> set:
    return {_norm(v) for v in row if v is not None}


def _is_derived(canonical_sql: str) -> bool:
    """True if the SELECT clause computes a derived value (a-b, 3*w+d, ratios).
    No template reproduces a computed column, so such questions are out-of-coverage by design.
    ('*' is excluded so COUNT(*) is not mistaken for multiplication.)"""
    m = re.search(r"\bselect\b(.*?)\bfrom\b", canonical_sql or "", re.IGNORECASE | re.DOTALL)
    select_clause = m.group(1) if m else (canonical_sql or "")
    return bool(re.search(r"[-+/]", select_clause))


def _is_bare_aggregate(gt: dict, derived: dict) -> bool:
    """Single numeric cell, no team entity in the question → a league-wide aggregate."""
    return (gt["row_count"] == 1 and len(gt["columns"]) == 1
            and isinstance(gt["rows"][0][0], (int, float))
            and not derived["teams"])


def _matches(gt: dict, out: dict, template_name: str, has_team_binding: bool,
             extra_required: set | None = None) -> bool:
    if gt["row_count"] == 0:
        # empty answer: covered only when an entity-specific template returns empty for that entity
        entity_templates = {"team_season_summary", "player_team_leaders",
                            "market_value_team_leaders", "head_to_head"}
        return template_name in entity_templates and has_team_binding and out["row_count"] == 0
    out_sigs = [_row_sig(r) for r in out["rows"]]
    if not out_sigs:
        return False
    extra = extra_required or set()
    for grow in gt["rows"]:
        gsig = _row_sig(grow) | extra   # for single-number answers, also require the entity in-row
        if not any(gsig <= osig for osig in out_sigs):
            return False
    return True


def _combos(tmpl, derived: dict):
    """Yield (params, has_team_binding) bindings to try for this template+question."""
    needs = set(tmpl.entity_params)
    seasons = derived["seasons"] or [None]
    teams = derived["teams"]
    metrics = list(tmpl.metrics) or [None]

    # entity feasibility
    if "season" in needs and not derived["seasons"]:
        return
    if "team" in needs and not teams:
        return
    if {"team_a", "team_b"} <= needs and len(teams) < 2:
        return

    season = seasons[0]
    team_choices = teams if "team" in needs else [None]
    for team in team_choices:
        for metric in metrics:
            p = {"top_n": TOP_N}
            if season is not None:
                p["season"] = season
            elif tmpl.name == "transfer_leaders":
                p["season"] = None
            if team is not None:
                p["team"] = team
            if {"team_a", "team_b"} <= needs:
                p["team_a"], p["team_b"] = teams[0], teams[1]
            if metric is not None:
                p["metric_col"] = tmpl.metrics[metric]
            yield p, (team is not None)


def label() -> dict:
    gs = {it["id"]: it for it in json.loads((GOLDEN_DIR / "golden_set.json").read_text())["items"]}
    gtmap = {it["id"]: it for it in json.loads((GOLDEN_DIR / "ground_truth.json").read_text())["items"]}

    results = []
    for qid, item in gs.items():
        gt = gtmap[qid].get("ground_truth")
        sql_text = item.get("canonical_sql")
        derived = _derive_params(sql_text)
        matched: list[str] = []
        eligible = (gt is not None
                    and not _is_derived(sql_text)        # computed-column answers: no template reproduces them
                    and not _is_bare_aggregate(gt, derived))  # league-wide aggregate, no entity
        if eligible:
            # For a single-number answer tied to an entity, require the value AND the entity in one row.
            single_numeric = (gt["row_count"] == 1 and len(gt["columns"]) == 1
                              and isinstance(gt["rows"][0][0], (int, float)))
            extra_required = set(derived["teams"]) if single_numeric and derived["teams"] else set()
            for tname, tmpl in TEMPLATES.items():
                hit = False
                for p, has_team in _combos(tmpl, derived):
                    try:
                        sql, bound = tmpl.build(p)
                        out = run_sql(sql, params=bound, max_rows=200)
                    except (SqlNotAllowed, Exception):  # noqa: BLE001
                        continue
                    if _matches(gt, out, tname, has_team, extra_required):
                        hit = True
                        break
                if hit:
                    matched.append(tname)
        results.append({
            "id": qid, "category": item["category"], "difficulty": item["difficulty"],
            "answer_type": item["answer_type"],
            "coverage_label": "in_coverage" if matched else "out_of_coverage",
            "matched_templates": matched,
        })

    in_n = sum(r["coverage_label"] == "in_coverage" for r in results)
    out_n = len(results) - in_n

    (OUT_DIR / "coverage_labels.candidate.json").write_text(
        json.dumps({"frozen": False, "in_coverage": in_n, "out_of_coverage": out_n,
                    "items": results}, indent=2))

    # matrix
    L = ["# Coverage matrix (CANDIDATE — generated before any DoF runs)", "",
         f"In-coverage: **{in_n}** · Out-of-coverage: **{out_n}** · Total: {len(results)}", "",
         "Coverage decided by template-vs-ground-truth matching (NOT agent runtime). "
         "A question is in-coverage iff some template's output reproduces the frozen ground truth. "
         "Computed-column answers (e.g. home−away gap, goals−xG) and league-wide aggregates with no "
         "entity are out-of-coverage by design (no template reproduces them).", "",
         "## Template library (intent — these are realistic, not strawmen)", "",
         "| template | intent |", "|---|---|"]
    for name, tmpl in TEMPLATES.items():
        L.append(f"| `{name}` | {tmpl.intent} |")
    L += ["", "## Per-question labels", "",
          "_Note: 'matched templates' is the value-containment superset; for some questions a "
          "template appears incidentally because the answer string/number occurs in its output. "
          "The in/out label is the frozen artifact._", "",
          "| id | category | diff | answer | label | matched templates |",
          "|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['id']} | {r['category']} | {r['difficulty']} | {r['answer_type']} | "
                 f"{'✅ in' if r['coverage_label']=='in_coverage' else '— out'} | "
                 f"{', '.join(r['matched_templates']) or '—'} |")
    (OUT_DIR / "coverage_matrix.md").write_text("\n".join(L))

    print(f"in_coverage={in_n}  out_of_coverage={out_n}  total={len(results)}")
    print(f"{'id':5} {'label':16} matched")
    for r in results:
        print(f"{r['id']:5} {r['coverage_label']:16} {', '.join(r['matched_templates']) or '—'}")
    print(f"\nWrote:\n  {OUT_DIR/'coverage_labels.candidate.json'}\n  {OUT_DIR/'coverage_matrix.md'}")
    return {"in": in_n, "out": out_n, "results": results}


if __name__ == "__main__":
    label()
