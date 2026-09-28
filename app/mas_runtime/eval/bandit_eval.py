"""
Phase E — Router-bandit offline evaluation.

Two things, both runnable with no LLM cost:

1. **Seeded regret simulation** (`simulate`) — the *mechanism* demonstration. The live
   `trajectory_log` is single-arm (see the handoff), so we cannot do honest off-policy
   evaluation from it yet. Instead we ground a synthetic reward model in the project's own
   **golden-set per-variant accuracies** (full_control 0.35 / semi_control 0.50 /
   no_control 0.65 — `eval_runner.py` v2 baselines) and show that Thompson Sampling
   converges to the best variant, beating random and the worst fixed arm and approaching
   the oracle (always-best). Reports cumulative regret + final arm-selection mix.

2. **Live posterior dump** (`live_report`) — reads whatever real rows exist in
   `trajectory_log`, warm-starts a `RouterBandit`, and prints the per-intent posterior
   table. This is what a reviewer should look at to see how much multi-arm evidence has
   actually accrued (currently: one arm).

Run:
    python eval/bandit_eval.py            # simulation + live dump
    python eval/bandit_eval.py --sim      # simulation only (no DB)
    python eval/bandit_eval.py --live     # live posterior dump only
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.router_bandit import RouterBandit, VARIANTS, feasible_actions  # noqa: E402

# Per-variant "true" reward for the simulation, anchored to the golden-set v2 baselines
# (data_request intent, claude). These are the project's real measured accuracies.
GOLDEN_SET_ACCURACY = {
    "full_control": 0.35,
    "semi_control": 0.50,
    "no_control": 0.65,
}
SIM_INTENT = "data_request"
SIM_MODEL = "claude"


# =============================================================================
# Policies under test (all over the same feasible action set)
# =============================================================================

def _thompson(bandit, intent):
    return bandit.select(intent, explore=True)


def _epsilon_greedy(bandit, intent, rng, eps=0.1):
    if rng.random() < eps:
        actions = feasible_actions(intent)
        return actions[rng.integers(len(actions))]
    return bandit.select(intent, explore=False)


# =============================================================================
# Simulation
# =============================================================================

def simulate(n_turns: int = 600, seed: int = 0) -> dict:
    """
    Pull arms for `n_turns` under several policies against the golden-set reward model;
    return per-policy cumulative reward, regret vs the oracle, and selection mix.
    """
    best_p = max(GOLDEN_SET_ACCURACY.values())          # oracle per-turn reward
    worst_p = min(GOLDEN_SET_ACCURACY.values())

    def true_p(variant):
        return GOLDEN_SET_ACCURACY[variant]

    results = {}

    # --- Thompson Sampling -------------------------------------------------
    rng = np.random.default_rng(seed)
    ts = RouterBandit(seed=seed)
    ts_reward, ts_regret, ts_counts = 0.0, 0.0, {v: 0 for v in VARIANTS}
    for _ in range(n_turns):
        m, v = _thompson(ts, SIM_INTENT)
        r = float(rng.random() < true_p(v))
        ts.update(SIM_INTENT, m, v, r)
        ts_reward += r
        ts_regret += best_p - true_p(v)
        ts_counts[v] += 1
    results["thompson"] = dict(reward=ts_reward, regret=ts_regret, counts=ts_counts)

    # --- epsilon-greedy ----------------------------------------------------
    rng = np.random.default_rng(seed + 1)
    eg = RouterBandit(seed=seed + 1)
    eg_reward, eg_regret, eg_counts = 0.0, 0.0, {v: 0 for v in VARIANTS}
    for _ in range(n_turns):
        m, v = _epsilon_greedy(eg, SIM_INTENT, rng)
        r = float(rng.random() < true_p(v))
        eg.update(SIM_INTENT, m, v, r)
        eg_reward += r
        eg_regret += best_p - true_p(v)
        eg_counts[v] += 1
    results["epsilon_greedy"] = dict(reward=eg_reward, regret=eg_regret, counts=eg_counts)

    # --- random ------------------------------------------------------------
    rng = np.random.default_rng(seed + 2)
    actions = feasible_actions(SIM_INTENT)
    rnd_reward, rnd_regret, rnd_counts = 0.0, 0.0, {v: 0 for v in VARIANTS}
    for _ in range(n_turns):
        _, v = actions[rng.integers(len(actions))]
        r = float(rng.random() < true_p(v))
        rnd_reward += r
        rnd_regret += best_p - true_p(v)
        rnd_counts[v] += 1
    results["random"] = dict(reward=rnd_reward, regret=rnd_regret, counts=rnd_counts)

    # --- fixed baselines (no learning) -------------------------------------
    results["fixed_best"] = dict(reward=best_p * n_turns, regret=0.0,
                                 counts={"no_control": n_turns})
    results["fixed_worst"] = dict(reward=worst_p * n_turns,
                                  regret=(best_p - worst_p) * n_turns,
                                  counts={"full_control": n_turns})
    results["_meta"] = dict(n_turns=n_turns, best_p=best_p, worst_p=worst_p,
                            accuracy=GOLDEN_SET_ACCURACY)
    return results


def print_simulation(results: dict) -> None:
    meta = results["_meta"]
    n = meta["n_turns"]
    print("=" * 68)
    print(f"ROUTER-BANDIT SIMULATION  (n={n} turns, intent={SIM_INTENT})")
    print(f"Reward model = golden-set v2 accuracy: {meta['accuracy']}")
    print(f"Oracle/turn={meta['best_p']:.2f}  worst/turn={meta['worst_p']:.2f}")
    print("=" * 68)
    order = ["fixed_best", "thompson", "epsilon_greedy", "random", "fixed_worst"]
    print(f"{'policy':16} {'avg_reward':>11} {'regret':>9}  arm-mix")
    print("-" * 68)
    for name in order:
        r = results[name]
        mix = "  ".join(f"{k}={v}" for k, v in r["counts"].items() if v)
        print(f"{name:16} {r['reward'] / n:>11.3f} {r['regret']:>9.1f}  {mix}")
    print("-" * 68)
    ts, rnd = results["thompson"], results["random"]
    print(f"Thompson beats random by {(ts['reward'] - rnd['reward']) / n:+.3f} avg reward "
          f"and cuts regret {rnd['regret']:.0f} -> {ts['regret']:.0f} "
          f"({100 * (1 - ts['regret'] / rnd['regret']):.0f}% lower).")
    print("Interpretation: TS learns the best variant online and converges toward the")
    print("oracle without being told which arm is best — the policy the trajectory_log was")
    print("built to feed. (Reward model is illustrative; swap in live multi-arm data when")
    print("the bandit has been exploring in production.)")


# =============================================================================
# Live posterior dump
# =============================================================================

def live_report(experiment: str = None) -> None:
    print("\n" + "=" * 68)
    print("LIVE trajectory_log POSTERIORS" + (f"  (experiment={experiment})" if experiment else ""))
    print("=" * 68)
    bandit = RouterBandit.from_trajectory_log(experiment=experiment)
    rows = bandit.posterior_table()
    if not rows:
        print("No trajectory_log rows reached (DB unavailable or empty).")
        return
    print(f"{'intent':16} {'model':7} {'variant':13} {'n':>5} {'mean':>7}")
    print("-" * 68)
    for r in rows:
        print(f"{r['intent']:16} {r['model']:7} {r['variant']:13} "
              f"{r['n']:>5} {r['mean']:>7.3f}")
    n_arms = len({(r["intent"], r["model"], r["variant"]) for r in rows if r["n"] > 0})
    print("-" * 68)
    print(f"{n_arms} arm(s) with observed pulls. The bandit needs >1 arm per intent to")
    print("discriminate; enable it in run_agent (bandit=...) so future turns explore.")


# =============================================================================
# CLI
# =============================================================================

def main():
    ap = argparse.ArgumentParser(description="Router-bandit offline evaluation")
    ap.add_argument("--sim", action="store_true", help="simulation only")
    ap.add_argument("--live", action="store_true", help="live posterior dump only")
    ap.add_argument("--turns", type=int, default=600)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--experiment", default=None, help="filter live rows by experiment")
    args = ap.parse_args()

    do_sim = args.sim or not args.live
    do_live = args.live or not args.sim

    if do_sim:
        print_simulation(simulate(n_turns=args.turns, seed=args.seed))
    if do_live:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
        except Exception:
            pass
        live_report(experiment=args.experiment)


if __name__ == "__main__":
    main()
