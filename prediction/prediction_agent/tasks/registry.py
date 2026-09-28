"""
Task registry (D0). Each prediction task registers a TaskSpec; the agent's prediction
node and the training CLI both resolve tasks from here, so a new forecasting capability
is added by registering a spec — no graph or agent changes.

A task is either:
  - model-backed  (feature_builder + a trained artefact under artefacts/), or
  - computed      (a deterministic `compute_fn(entity, ...) -> GenericPrediction`),
    used for index-style tasks (e.g. home/away dependency) that need no training.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_ARTEFACTS = Path(__file__).resolve().parent.parent.parent / "artefacts"


@dataclass
class TaskSpec:
    name: str                                   # canonical task id == prediction_type
    description: str
    granularity: str                            # 'team_season' | 'match' | 'player_season' | ...
    target_type: str                            # 'classification' | 'regression' | 'index'
    artefact: Optional[str] = None              # filename under artefacts/ (model-backed)
    aliases: tuple = ()                         # extra prediction_type strings that map here
    intents: tuple = ()                         # example NL phrasings (docs/routing aid)
    compute_fn: Optional[Callable] = None       # for computed/index tasks

    def artefact_path(self) -> Optional[Path]:
        return (_ARTEFACTS / self.artefact) if self.artefact else None


_REGISTRY: dict[str, TaskSpec] = {}


def register(spec: TaskSpec) -> None:
    _REGISTRY[spec.name] = spec
    for a in spec.aliases:
        _REGISTRY[a] = spec


def get(name: str) -> Optional[TaskSpec]:
    return _REGISTRY.get(name)


def all_tasks() -> list[TaskSpec]:
    # de-dupe (aliases point to the same spec object)
    seen, out = set(), []
    for spec in _REGISTRY.values():
        if id(spec) not in seen:
            seen.add(id(spec))
            out.append(spec)
    return out


def task_names() -> list[str]:
    return [s.name for s in all_tasks()]


# Tasks self-register on import of the tasks package (see tasks/__init__.py).
