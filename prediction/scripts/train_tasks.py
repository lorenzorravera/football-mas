"""
Train registered model-backed prediction tasks (D0/D1/D4).

Trains every model-backed task and writes artefacts under artefacts/:
  team-season  (Q1–Q3): season_class, position_movement, turnaround
  player       (Q7c):    player_decline
  transfer     (Q11):    cross_league_translation
  in-game      (Q9):     event_impact (an empirical lookup table, not a fitted model)
Computed tasks (Q4 home/away, Q5 squad availability, Q6 player impact, Q7a/b value, Q10
stakeholder value, Q12 transfer fit) need no training. Reports a holdout metric per task.

Usage:
    cd prediction_agent
    python scripts/train_tasks.py                 # train everything
    python scripts/train_tasks.py --task season_class
    python scripts/train_tasks.py --group player  # team_season | player | transfer | event
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# .env with DATABASE_URI lives in the agent folder; override the stale shell placeholder.
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "Ethan" / "agent_v4" / ".env", override=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # prediction_agent/

from prediction_agent.models.team_season import train_team_season_task, TASKS as TS_TASKS
from prediction_agent.models.player_season import train_player_task, TASKS as PL_TASKS
from prediction_agent.models import cross_league as xleague
from prediction_agent.models import event_impact as eimpact

# task key -> (group, trainer callable)
_TRAINERS = {
    **{k: ("team_season", lambda k=k: train_team_season_task(k, save=True)) for k in TS_TASKS},
    **{k: ("player", lambda k=k: train_player_task(k, save=True)) for k in PL_TASKS},
    "cross_league_translation": ("transfer", lambda: xleague.train(save=True)),
    "event_impact": ("event", lambda: eimpact.train(save=True)),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="all", help="task key or 'all'")
    ap.add_argument("--group", default=None,
                    help="train a group: team_season | player | transfer | event")
    args = ap.parse_args()

    if args.task != "all":
        keys = [args.task]
    elif args.group:
        keys = [k for k, (g, _) in _TRAINERS.items() if g == args.group]
    else:
        keys = list(_TRAINERS)

    print(f"Training: {keys}\n")
    for k in keys:
        if k not in _TRAINERS:
            print(f"  ! unknown task {k!r}; have {list(_TRAINERS)}")
            continue
        m = _TRAINERS[k][1]()
        print(f"✓ {k}")
        for kk, vv in m.items():
            print(f"    {kk}: {vv}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
