"""
D4 dispatch checks (DB, NO LLM) — the player / transfer / event / computed-team paths and the
model-explanation capability, end-to-end through prediction_agent():

  Q7  player_value           league-wide value ranking
  Q7c player_decline         league-wide decline ranking (sorted by prob) + single player
  Q6  player_team_impact     counterfactual Δ in a team's class probability
  Q12 transfer_fit           player → destination style fit
  Q11 cross_league_translation  player output retention moving leagues
  Q5  squad_availability     league-wide injury-cost ranking
  Q10 stakeholder_value      league-wide strategic-value ranking
  Q9  event_impact           scenario shift vs base rates
  Q14 explanation            attached to a model-backed forecast when asked "why"

Calls prediction_agent() directly with a pre-set state (skips the manager LLM).

Run:  cd Ethan/agent_v4 && python eval/tests/test_d4_dispatch.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
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
    out = prediction_agent(st)
    assert out.get("error") is None, f"{query!r} -> {out.get('error')}"
    return out


def main() -> int:
    # Q7 player_value — league-wide ranking, sorted by value_score.
    out = _run("Which players are the best value for money?",
               {"prediction_type": "player_value"})
    dr = out["data_result"]
    assert {"player_name", "value_score", "label"}.issubset(dr.columns), dr.columns.tolist()
    assert dr["value_score"].is_monotonic_decreasing, "not sorted by value"
    print(f"✓ player_value: top = {dr.iloc[0]['player_name']} ({dr.iloc[0]['label']})")

    # Q7c player_decline — league-wide, sorted by decline probability.
    out = _run("Which players are most likely to decline next season?",
               {"prediction_type": "player_decline"})
    dr = out["data_result"]
    assert "decline_prob" in dr.columns and dr["decline_prob"].is_monotonic_decreasing
    print(f"✓ player_decline (league): top risk = {dr.iloc[0]['player']} "
          f"p={dr.iloc[0]['decline_prob']}")

    # Q6 player_team_impact — counterfactual on season_class.
    out = _run("How much does Mohamed Salah improve Liverpool?",
               {"prediction_type": "player_team_impact", "players": ["Mohamed Salah"]})
    dr = out["data_result"]
    assert any(c.startswith("delta_") for c in dr.columns), dr.columns.tolist()
    print(f"✓ player_team_impact: Δp(top4) = {out['prediction_metadata']['delta_p_top4']}")

    # Q12 transfer_fit — player → destination (player may be from another league).
    out = _run("How would Mbappé fit at Arsenal?",
               {"prediction_type": "transfer_fit", "players": ["Mbappé"], "destination": "Arsenal"})
    dr = out["data_result"]
    assert {"destination_fit", "verdict"}.issubset(dr.columns), dr.columns.tolist()
    print(f"✓ transfer_fit: {dr.iloc[0]['player']} -> Arsenal = {dr.iloc[0]['verdict']}")

    # Q11 cross_league_translation — output retention.
    out = _run("How would Florian Wirtz do in the Premier League?",
               {"prediction_type": "cross_league_translation", "players": ["Florian Wirtz"],
                "destination_league": "ENG-PL"})
    dr = out["data_result"]
    assert {"predicted_retention", "predicted_ga_per90"}.issubset(dr.columns), dr.columns.tolist()
    print(f"✓ cross_league: retention = {dr.iloc[0]['predicted_retention']} "
          f"({dr.iloc[0]['verdict']})")

    # Q5 squad_availability — league-wide, most-injured first (avail_index ascending).
    out = _run("Which team is most hurt by injuries this season?",
               {"prediction_type": "squad_availability"})
    dr = out["data_result"]
    assert "avail_index" in dr.columns and dr["avail_index"].is_monotonic_increasing
    print(f"✓ squad_availability: most hurt = {dr.iloc[0]['team']} "
          f"(~{dr.iloc[0]['est_points_lost']} pts)")

    # Q10 stakeholder_value — league-wide ranking.
    out = _run("Which clubs have the highest strategic value?",
               {"prediction_type": "stakeholder_value"})
    dr = out["data_result"]
    assert ("stakeholder_value_index" in dr.columns
            and dr["stakeholder_value_index"].is_monotonic_decreasing)
    print(f"✓ stakeholder_value: top = {dr.iloc[0]['team']}")

    # Q9 event_impact — scenario shift vs base rate.
    out = _run("How much does an early goal change the result?",
               {"prediction_type": "event_impact"})
    dr = out["data_result"]
    assert {"baseline_pct", "scenario_pct", "shift_pct"}.issubset(dr.columns), dr.columns.tolist()
    hw = dr[dr["result"] == "home_win"].iloc[0]
    assert hw["shift_pct"] > 0, "an early home goal should raise home-win prob"
    print(f"✓ event_impact: home early goal shifts home win by {hw['shift_pct']}%")

    # Q14 explanation — attached to a model-backed forecast when asked "why".
    out = _run("Why will Arsenal finish top four next season? what factors drive it?",
               {"prediction_type": "season_class", "teams": ["Arsenal"]})
    exp = out["prediction_metadata"].get("explanation")
    assert exp and exp.get("top_factors"), f"no explanation attached: {exp}"
    print(f"✓ explanation: method={exp['method']}, "
          f"top={[f['feature'] for f in exp['top_factors'][:3]]}")

    # cleanup the persisted single-team forecast the season_class path writes (best-effort)
    try:
        import os, psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URI"]); conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DELETE FROM computed_metrics WHERE metric_name='season_class' "
                        "AND (metric_value->>'entity') = 'Arsenal'")
        conn.close()
    except Exception:
        pass

    print("\n✓ ALL D4 DISPATCH CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
