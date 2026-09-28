"""
Phase D dispatch checks (DB, NO LLM) — the team-season multi-task path end-to-end:
  - single-team season_class  -> 1-row forecast with class probabilities
  - league-wide season_class  -> 20 current teams, ranked by relegation probability
  - home/away dependency      -> computed index task

Calls prediction_agent() directly with a pre-set state (skips the manager LLM). Cleans up
the computed_metrics row the single-team path persists.

Run:  cd Ethan/agent_v4 && python eval/tests/test_prediction_dispatch.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# prediction_agent package (pip-installed); add repo-root/prediction_agent as a fallback.
_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_root / "prediction_agent"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

from state import create_initial_state
from agents.prediction_agent import prediction_agent


def _run(query, params):
    st = create_initial_state(query)
    st["intent"] = "prediction_match"
    st["is_premier_league_related"] = True
    st["query_parameters"] = params
    return prediction_agent(st)


def main() -> int:
    # 1. single-team season class
    out = _run("Will Aston Villa finish in the top four next season?",
               {"teams": ["Aston Villa"], "prediction_type": "season_class"})
    assert out.get("error") is None, out.get("error")
    dr = out["data_result"]
    assert len(dr) == 1, dr
    assert any(c.startswith("p_") for c in dr.columns), dr.columns.tolist()
    assert dr.iloc[0]["prediction"] in {"top4", "european", "mid_table", "relegation"}
    print(f"✓ single-team season_class: {dr.iloc[0]['entity']} -> {dr.iloc[0]['prediction']}")

    # 2. league-wide relegation ranking
    out = _run("Who is most likely to be relegated next season?",
               {"prediction_type": "season_class"})
    dr = out["data_result"]
    assert len(dr) == 20, f"expected 20 current teams, got {len(dr)}"
    assert set(dr["from_season"].unique()) == {dr["from_season"].iloc[0]}, "mixed seasons"
    assert (dr["p_relegation"].is_monotonic_decreasing), "not sorted by relegation risk"
    print(f"✓ league-wide season_class: {len(dr)} teams, top risk = {dr.iloc[0]['entity']}")

    # 3. computed index task
    out = _run("How much does Arsenal rely on home form?",
               {"teams": ["Arsenal"], "prediction_type": "home_away_dependency"})
    dr = out["data_result"]
    assert "p_home_reliance_index" in dr.columns, dr.columns.tolist()
    print(f"✓ home_away_dependency: Arsenal index = {dr.iloc[0]['p_home_reliance_index']}")

    # cleanup the persisted single-team forecast (best-effort)
    try:
        import os, psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URI"]); conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM computed_metrics WHERE metric_name='season_class' "
                        "AND (metric_value->>'entity') = 'Aston Villa'")
        conn.close()
    except Exception:
        pass

    print("\n✓ ALL PREDICTION DISPATCH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
