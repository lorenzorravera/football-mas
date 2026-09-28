"""
In-game event-impact table (D4, Q9) — empirical P(result | event scenario).

How much does an early goal / half-time lead / red card change the final result? The honest,
interpretable answer is the EMPIRICAL conditional distribution P(result | scenario) versus the
unconditional base rate — not a parametric model, which (because the event flags are strongly
correlated) produces out-of-distribution artefacts when a single flag is toggled in isolation
(e.g. "a red card in a match where nobody has scored" reads as a 0-0 draw).

So this builds a lookup table from the ~1900 ENG-PL matches: for each named scenario, the result
distribution among matches satisfying it, the sample size, and the shift vs base rates. The
compute_fn (tasks/computed.event_impact_scenario) reads this table.

Artefact: artefacts/event_impact_v1.pkl  — a plain bundle:
  {task_name, version, target_type='lookup', base_rates, scenarios: {name: {dist, n, desc}}}
"""

from __future__ import annotations

import joblib
from pathlib import Path

from prediction_agent.features.event_features import build_event_frame

VERSION = "v1"
TASK = "event_impact"

# name -> (mask builder over the event frame, human description)
SCENARIOS = {
    "home_scores_first":        (lambda d: d.fg_home == 1, "home team scores first"),
    "home_scores_first_early":  (lambda d: (d.fg_home == 1) & (d.fg_early == 1),
                                 "home team scores first within 15 min"),
    "away_scores_first":        (lambda d: d.fg_away == 1, "away team scores first"),
    "away_scores_first_early":  (lambda d: (d.fg_away == 1) & (d.fg_early == 1),
                                 "away team scores first within 15 min"),
    "home_leads_ht":            (lambda d: d.ht_lead_home == 1, "home team leads at half-time"),
    "away_leads_ht":            (lambda d: d.ht_lead_away == 1, "away team leads at half-time"),
    "home_red_card":            (lambda d: d.red_home == 1, "home team receives a red card"),
    "away_red_card":            (lambda d: d.red_away == 1, "away team receives a red card"),
    "home_leads_ht_away_red":   (lambda d: (d.ht_lead_home == 1) & (d.red_away == 1),
                                 "home leads at half-time and the away team is reduced to ten"),
}


def _dist(sub) -> dict:
    return {r: round(float((sub["ft_result"] == r).mean()), 4) for r in ("H", "D", "A")}


def train(save: bool = True) -> dict:
    df = build_event_frame()
    base_rates = _dist(df)
    scenarios = {}
    for name, (mask_fn, desc) in SCENARIOS.items():
        sub = df[mask_fn(df)]
        if len(sub) == 0:
            continue
        scenarios[name] = {"dist": _dist(sub), "n": int(len(sub)), "desc": desc}

    bundle = {"task_name": TASK, "version": VERSION, "target_type": "lookup",
              "base_rates": base_rates, "scenarios": scenarios}
    metrics = {"task": TASK, "target_type": "lookup", "n_matches": int(len(df)),
               "base_rates": base_rates, "n_scenarios": len(scenarios)}
    if save:
        path = Path(__file__).resolve().parents[2] / "artefacts" / f"{TASK}_{VERSION}.pkl"
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, path)
        metrics["artefact"] = str(path.name)
    return metrics


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / "Ethan" / "agent_v4" / ".env", override=True)
    m = train()
    print(m)
    b = joblib.load(Path(__file__).resolve().parents[2] / "artefacts" / "event_impact_v1.pkl")
    for k, v in b["scenarios"].items():
        print(f"  {k:26s} n={v['n']:4d}  {v['dist']}  ({v['desc']})")
