"""
GoldenItem — data model for one golden-set question (spec Phase 1 / Phase 2).

A GoldenItem is authored in Phase 2 (NL question by AI draft, canonical_sql hand-authored/
approved by Till). ground_truth is the RESULT of running canonical_sql (Phase 2) — never an AI
prose answer. coverage_label is frozen in Phase 3 by template-vs-ground-truth matching.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

GtType = Literal["deterministic_sql", "multi_step", "prediction"]
AnswerType = Literal["scalar", "ranking", "table", "probability_vector"]
CoverageLabel = Literal["in_coverage", "out_of_coverage"]
Difficulty = Literal["simple", "medium", "hard", "edge_case"]


@dataclass
class GoldenItem:
    id: str
    question: str
    category: str
    difficulty: Difficulty
    gt_type: GtType
    answer_type: AnswerType
    canonical_sql: Optional[str] = None          # hand-authored/approved by Till (None for prediction)
    ground_truth: Optional[Any] = None           # structured result of canonical_sql (filled Phase 2)
    coverage_label: Optional[CoverageLabel] = None   # frozen in Phase 3
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.gt_type in ("deterministic_sql", "multi_step") and self.canonical_sql is None:
            # allowed during drafting, but flag intent: SQL-answerable items need canonical_sql by Phase 2 freeze
            pass
        if self.gt_type == "prediction" and self.answer_type != "probability_vector":
            raise ValueError(f"{self.id}: prediction items must have answer_type='probability_vector'")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GoldenItem":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


if __name__ == "__main__":
    item = GoldenItem(
        id="G001",
        question="How many points did Arsenal finish with in 2023-2024?",
        category="team_league_outcomes",
        difficulty="simple",
        gt_type="deterministic_sql",
        answer_type="scalar",
        canonical_sql="SELECT tss_points FROM team_season_standings "
                      "WHERE tss_team='Arsenal' AND tss_season='2023-2024'",
    )
    print(item.to_dict())
    print("round-trip ok:", GoldenItem.from_dict(item.to_dict()) == item)
