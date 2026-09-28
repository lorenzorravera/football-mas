"""
Phase E — Router bandit: a Thompson-Sampling **contextual** bandit over the
`(model, variant)` action space, conditioned on the turn's `intent`.

The `trajectory_log` table (A2 substrate) is the data source: every live turn has
already been recording `arm = model|variant|intent`, `eval_score`, `thumbs`,
`latency_ms`, `token_cost`. This module turns that log into a policy that, given an
intent, proposes which `(model, variant)` arm to run next — and learns online as
rewards arrive.

Design choices (kept deliberately simple + honest, matching the rest of the project):

- **Context = intent**, **action = (model, variant)**. Intent is *not* chooseable — it
  is set by the query — so it is the context, not part of the action. (The
  `trajectory_log.arm` string still encodes the full triple for storage; here we split
  context from action so the policy is a proper contextual bandit.)
- **Beta-Bernoulli Thompson Sampling.** Reward is shaped into [0, 1] (see `shape_reward`);
  each arm keeps a Beta(alpha, beta) posterior updated with `alpha += r`, `beta += 1 - r`.
  To `select`, sample one theta per feasible arm and take the argmax (Thompson). This is
  the textbook conjugate update for a bounded reward and needs no learning rate.
- **Feasible action set depends on intent.** For `conversational` / `prediction_match`
  the data-analyst never runs, so `variant` is irrelevant and collapses to the sentinel
  `"n/a"` (a single arm per model). `gpt4o` is only feasible when `OPENAI_API_KEY` is set
  (it is not, per the handoff), so by default the model dimension has one live value and
  the *variant* dimension is where the bandit actually explores.

**Honest caveat (read this):** as of the last run the live `trajectory_log` is
single-arm (`claude|no_control|data_request`, n=135) — the system has only ever been run
in one configuration, so there is no multi-arm reward signal yet. This module is the
*policy + learning machinery*; `bandit_eval.py` demonstrates convergence/regret on a
seeded reward model grounded in the golden-set numbers, and the live posterior dump shows
what real data exists. Turning the bandit on in `run_agent` (off by default) is what makes
future turns populate the other arms so the posteriors become meaningful.
"""

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# =============================================================================
# Action / context space
# =============================================================================

MODELS = ["claude", "gpt4o"]
VARIANTS = ["full_control", "semi_control", "no_control"]

# Intents for which the data-analyst (and therefore `variant`) is irrelevant.
_NO_VARIANT_INTENTS = {"conversational", "prediction_match"}
_NA_VARIANT = "n/a"

# Reward-shaping weights. Default = pure accuracy (eval_score), so the policy is
# interpretable; cost/latency penalties are opt-in for a "quality per token/ms" objective.
DEFAULT_REWARD_WEIGHTS = {
    "eval": 1.0,     # weight on eval_score (already in [0, 1])
    "thumbs": 0.0,   # weight on user thumbs mapped to {0, 1} (NULL ignored)
    "cost": 0.0,     # penalty weight on normalized token_cost
    "latency": 0.0,  # penalty weight on normalized latency_ms
}

# Normalizers for the optional cost/latency penalties (rough live-scale anchors).
_COST_NORM = 20_000.0     # tokens; a heavy turn
_LATENCY_NORM = 30_000.0  # ms; a slow turn


def feasible_models() -> list[str]:
    """Models the bandit may actually choose given available credentials."""
    models = ["claude"]
    if os.getenv("OPENAI_API_KEY"):
        models.append("gpt4o")
    return models


def feasible_actions(intent: Optional[str]) -> list[tuple[str, str]]:
    """The `(model, variant)` arms that make sense for this intent."""
    variants = [_NA_VARIANT] if intent in _NO_VARIANT_INTENTS else VARIANTS
    return [(m, v) for m in feasible_models() for v in variants]


def canonical_variant(intent: Optional[str], variant: Optional[str]) -> str:
    """Collapse `variant` to the sentinel when it cannot have influenced the turn."""
    if intent in _NO_VARIANT_INTENTS:
        return _NA_VARIANT
    return variant or "no_control"


# =============================================================================
# Reward shaping
# =============================================================================

def shape_reward(
    eval_score: Optional[float],
    thumbs: Optional[int] = None,
    token_cost: Optional[int] = None,
    latency_ms: Optional[int] = None,
    weights: Optional[dict] = None,
) -> Optional[float]:
    """
    Map a logged turn's signals to a single reward in [0, 1] for the Beta update.

    Returns None when there is no usable signal at all (so the caller can skip the row),
    otherwise a clipped weighted blend. With the default weights this is just
    `eval_score`. Weights are renormalized over the *present* signals so a missing
    component (e.g. no thumbs) doesn't silently shrink the reward.
    """
    w = {**DEFAULT_REWARD_WEIGHTS, **(weights or {})}

    terms: list[tuple[float, float]] = []  # (weight, value) for positive-direction signals
    if eval_score is not None and w["eval"]:
        terms.append((w["eval"], float(np.clip(eval_score, 0.0, 1.0))))
    if thumbs is not None and w["thumbs"]:
        terms.append((w["thumbs"], 1.0 if thumbs > 0 else 0.0))

    if not terms:
        # No positive-direction signal — penalties alone can't define a reward.
        return None

    pos_weight = sum(wt for wt, _ in terms)
    reward = sum(wt * val for wt, val in terms) / pos_weight

    # Optional penalties (subtractive, normalized) for a cost/latency-aware objective.
    if token_cost is not None and w["cost"]:
        reward -= w["cost"] * min(token_cost / _COST_NORM, 1.0)
    if latency_ms is not None and w["latency"]:
        reward -= w["latency"] * min(latency_ms / _LATENCY_NORM, 1.0)

    return float(np.clip(reward, 0.0, 1.0))


# =============================================================================
# Beta-Bernoulli Thompson-Sampling contextual bandit
# =============================================================================

@dataclass
class _Posterior:
    """Beta(alpha, beta) for one (intent, model, variant) arm."""
    alpha: float = 1.0  # prior successes (uniform Beta(1,1))
    beta: float = 1.0   # prior failures
    n: int = 0          # observed pulls (for reporting; priors excluded)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


@dataclass
class RouterBandit:
    """
    Contextual Thompson-Sampling router.

    Usage:
        b = RouterBandit.from_trajectory_log()      # warm-start from live data
        model, variant = b.select("data_request")   # propose an arm
        ... run the turn ...
        b.update("data_request", model, variant, reward=0.5)

    `seed` makes `select` reproducible (tests + deterministic eval). Reward shaping is
    controlled by `weights` (see `shape_reward`).
    """
    weights: dict = field(default_factory=lambda: dict(DEFAULT_REWARD_WEIGHTS))
    seed: Optional[int] = None
    _post: dict = field(default_factory=lambda: defaultdict(_Posterior))
    _rng: np.random.Generator = field(default=None)

    def __post_init__(self):
        self._rng = np.random.default_rng(self.seed)

    # ---- core API --------------------------------------------------------

    def _key(self, intent, model, variant):
        return (intent or "unknown", model, canonical_variant(intent, variant))

    def update(self, intent, model, variant, reward: float) -> None:
        """Apply one Beta-Bernoulli update with a reward in [0, 1]."""
        r = float(np.clip(reward, 0.0, 1.0))
        p = self._post[self._key(intent, model, variant)]
        p.alpha += r
        p.beta += 1.0 - r
        p.n += 1

    def observe(self, intent, model, variant, **signals) -> bool:
        """Shape raw logged signals into a reward and update. Returns False if skipped."""
        r = shape_reward(weights=self.weights, **signals)
        if r is None:
            return False
        self.update(intent, model, variant, r)
        return True

    def select(self, intent: Optional[str], explore: bool = True) -> tuple[str, str]:
        """
        Propose an arm for this intent.

        explore=True  -> Thompson sampling (one Beta draw per feasible arm, argmax).
        explore=False -> greedy exploitation (posterior-mean argmax) for reporting/serving.
        """
        actions = feasible_actions(intent)
        if explore:
            scores = [self._rng.beta(p.alpha, p.beta)
                      for p in (self._post[self._key(intent, m, v)] for m, v in actions)]
        else:
            scores = [self._post[self._key(intent, m, v)].mean for m, v in actions]
        return actions[int(np.argmax(scores))]

    # ---- reporting -------------------------------------------------------

    def posterior_table(self, intent: Optional[str] = None) -> list[dict]:
        """Flat rows of every arm's posterior (optionally filtered to one intent)."""
        rows = []
        for (i, m, v), p in sorted(self._post.items()):
            if intent is not None and i != intent:
                continue
            rows.append({
                "intent": i, "model": m, "variant": v,
                "n": p.n, "alpha": round(p.alpha, 3), "beta": round(p.beta, 3),
                "mean": round(p.mean, 4),
            })
        return rows

    # ---- warm start ------------------------------------------------------

    @classmethod
    def from_rows(cls, rows, weights=None, seed=None) -> "RouterBandit":
        """
        Build a bandit from an iterable of dict rows. Each row needs `intent`, `model`,
        `variant` and at least one of `eval_score` / `thumbs` (cost/latency optional).
        """
        b = cls(weights={**DEFAULT_REWARD_WEIGHTS, **(weights or {})}, seed=seed)
        for r in rows:
            b.observe(
                r.get("intent"), r.get("model"), r.get("variant"),
                eval_score=r.get("eval_score"),
                thumbs=r.get("thumbs"),
                token_cost=r.get("token_cost"),
                latency_ms=r.get("latency_ms"),
            )
        return b

    @classmethod
    def from_trajectory_log(cls, experiment=None, weights=None, seed=None,
                            limit: Optional[int] = None) -> "RouterBandit":
        """
        Warm-start from the live `trajectory_log` table. Best-effort: on any DB error
        returns an uninitialized bandit (uniform priors) rather than raising — selection
        still works, it just has no evidence yet.
        """
        rows = []
        try:
            # Local import so the module is usable without DB deps (e.g. pure-sim tests).
            from memory.vector_store_pg import _get_conn
            where = "WHERE experiment = %s" if experiment else ""
            params = [experiment] if experiment else []
            sql = (
                "SELECT intent, model, variant, eval_score, thumbs, token_cost, latency_ms "
                f"FROM trajectory_log {where} ORDER BY ts"
            )
            if limit:
                sql += " LIMIT %s"
                params.append(limit)
            conn = _get_conn()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, vals)) for vals in cur.fetchall()]
        except Exception as exc:  # best-effort warm start
            import logging
            logging.getLogger(__name__).warning(
                "RouterBandit.from_trajectory_log: %s (starting from priors)", exc)
        return cls.from_rows(rows, weights=weights, seed=seed)


if __name__ == "__main__":
    # Tiny smoke test: synthetic two-arm contextual problem, no DB needed.
    b = RouterBandit(seed=0)
    truth = {("data_request", "claude", "no_control"): 0.8,
             ("data_request", "claude", "semi_control"): 0.5,
             ("data_request", "claude", "full_control"): 0.3}
    rng = np.random.default_rng(0)
    for _ in range(400):
        m, v = b.select("data_request")
        r = float(rng.random() < truth[("data_request", m, v)])
        b.update("data_request", m, v, r)
    print("Posterior table (data_request):")
    for row in b.posterior_table("data_request"):
        print(" ", row)
    print("Greedy pick:", b.select("data_request", explore=False), "(truth-best: no_control)")
