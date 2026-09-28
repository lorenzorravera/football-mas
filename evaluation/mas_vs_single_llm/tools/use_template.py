"""
tools/use_template.py — the `use_template` tool + function-calling tool specs.

`use_template(template_name, params)` runs one of the frozen Phase-3 templates and returns its
rows. This is the ONLY data tool the CONTROLLED agent may call; SEMI gets this + run_sql; AUTONOMOUS
gets run_sql only. The agents differ ONLY in which of these tool specs are registered.
"""

from __future__ import annotations

from templates.library import TEMPLATES
from tools.run_sql import run_sql, SqlNotAllowed
from tools.predict_match_outcome import TOOL_SCHEMA as _PREDICT_SCHEMA, predict_match_outcome


def use_template(template_name: str, params: dict | None = None) -> dict:
    """Run a named template. Returns {columns, rows, row_count, template} or {error}."""
    tmpl = TEMPLATES.get(template_name)
    if tmpl is None:
        return {"error": f"unknown template '{template_name}'", "available": list(TEMPLATES)}
    p = dict(params or {})
    p.setdefault("top_n", 50)
    if tmpl.metrics:
        metric = p.get("metric")
        if metric not in tmpl.metrics:
            return {"error": f"template '{template_name}' requires 'metric' in {list(tmpl.metrics)}"}
        p["metric_col"] = tmpl.metrics[metric]
    for ep in tmpl.entity_params:
        if not p.get(ep):
            return {"error": f"missing required param '{ep}' for template '{template_name}'"}
    try:
        sql, bound = tmpl.build(p)
        res = run_sql(sql, params=bound, max_rows=int(p.get("top_n") or 50))
        return {"template": template_name, "columns": res["columns"],
                "rows": res["rows"], "row_count": res["row_count"]}
    except (SqlNotAllowed, Exception) as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


def _template_catalogue() -> str:
    lines = []
    for name, t in TEMPLATES.items():
        parts = [f"params: {t.entity_params or 'none'}"]
        if t.metrics:
            parts.append(f"metric in {list(t.metrics)}")
        lines.append(f"- {name}: {t.intent} ({'; '.join(parts)})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Function-calling tool specs (OpenAI-style; LiteLLM maps to each provider)
# --------------------------------------------------------------------------- #
USE_TEMPLATE_TOOL = {
    "type": "function",
    "function": {
        "name": "use_template",
        "description": (
            "Run a pre-built parameterized SQL template and get its rows. Available templates:\n"
            + _template_catalogue()
            + "\nSeasons are 'YYYY-YYYY' (e.g. '2023-2024'). Pass team/player names as canonical strings."),
        "parameters": {
            "type": "object",
            "properties": {
                "template_name": {"type": "string", "enum": list(TEMPLATES)},
                "params": {
                    "type": "object",
                    "description": "Entity params (season, team, team_a, team_b), optional 'metric' label, optional 'top_n'.",
                    "properties": {
                        "season": {"type": "string"},
                        "team": {"type": "string"},
                        "team_a": {"type": "string"},
                        "team_b": {"type": "string"},
                        "metric": {"type": "string"},
                        "top_n": {"type": "integer"},
                    },
                },
            },
            "required": ["template_name", "params"],
        },
    },
}

RUN_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": ("Run a single read-only SELECT/WITH query against the Premier League database "
                        "and get the rows. Only SELECT/WITH is allowed."),
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT/WITH statement."}},
            "required": ["sql"],
        },
    },
}

PREDICT_TOOL = {"type": "function", "function": _PREDICT_SCHEMA}


def run_sql_tool(sql: str) -> dict:
    """Tool wrapper around run_sql that returns errors as data (never raises to the agent loop)."""
    try:
        res = run_sql(sql, max_rows=200)
        return {"columns": res["columns"], "rows": res["rows"],
                "row_count": res["row_count"], "truncated": res["truncated"]}
    except SqlNotAllowed as e:
        return {"error": f"rejected: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}


# name -> (callable, schema). Conditions pick a subset of these to register.
TOOL_REGISTRY = {
    "use_template": (lambda **kw: use_template(kw.get("template_name"), kw.get("params")), USE_TEMPLATE_TOOL),
    "run_sql": (lambda **kw: run_sql_tool(kw.get("sql", "")), RUN_SQL_TOOL),
    "predict_match_outcome": (lambda **kw: predict_match_outcome(
        kw.get("home_team"), kw.get("away_team"),
        match_date=kw.get("match_date"), season=kw.get("season")), PREDICT_TOOL),
}


if __name__ == "__main__":
    print("use_template smoke tests:")
    print(" controlled-style league_table:",
          use_template("league_table", {"season": "2024-2025"})["row_count"], "rows")
    print(" player_season_leaders(goals):",
          use_template("player_season_leaders", {"season": "2023-2024", "metric": "goals", "top_n": 3})["rows"])
    print(" missing metric:", use_template("player_season_leaders", {"season": "2023-2024"}))
    print(" unknown template:", use_template("nope", {})["error"])
