"""
templates/freeze_coverage.py — FREEZE the coverage labels (Phase 3 freeze gate).

Seals results/templates/coverage_labels.candidate.json into a frozen, self-describing
coverage_labels.json (sha256 + timestamp + git commit) and records it in manifest.json.
Header states it was generated BEFORE any DoF runs.

SAFETY: refuses to overwrite an already-frozen coverage_labels.json (never edit a frozen artifact).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from manifest import record_phase, git_info, now_iso

OUT = Path(__file__).resolve().parent.parent / "results" / "templates"


def sha256_of_items(items: list) -> str:
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def freeze(force: bool = False) -> dict:
    target = OUT / "coverage_labels.json"
    if target.exists() and not force:
        raise SystemExit(
            f"Refusing to overwrite already-frozen {target.name}. "
            "Delete it by hand and pass --force only if you intend to re-freeze.")

    cand = json.loads((OUT / "coverage_labels.candidate.json").read_text())
    items = cand["items"]
    gi = git_info()
    ts = now_iso()
    h = sha256_of_items(items)

    doc = {
        "frozen": True,
        "phase": "3",
        "artifact": "coverage_labels",
        "generated_before_dof_runs": True,
        "generated_at": ts,
        "git_commit": gi["git_commit"],
        "git_dirty": gi["git_dirty"],
        "in_coverage": cand["in_coverage"],
        "out_of_coverage": cand["out_of_coverage"],
        "n_items": len(items),
        "sha256": h,
        "items": items,
    }
    target.write_text(json.dumps(doc, indent=2, default=str))

    record_phase("phase3_coverage_labels", {
        "frozen_at": ts, "git_commit": gi["git_commit"], "git_dirty": gi["git_dirty"],
        "in_coverage": cand["in_coverage"], "out_of_coverage": cand["out_of_coverage"],
        "files": {"coverage_labels.json": {"sha256": h, "n_items": len(items)}},
        "note": "Coverage decided by template-vs-ground-truth matching, generated before any DoF runs. "
                "12 templates in templates/library.py.",
    })

    print(f"FROZEN: coverage_labels.json  in={cand['in_coverage']} out={cand['out_of_coverage']} "
          f"n={len(items)}  sha256={h}")
    print(f"  git_commit={gi['git_commit']}  dirty={gi['git_dirty']}")
    if gi.get("git_dirty"):
        print("  NOTE: working tree dirty — commit the v5 code to make git provenance precise.")
    return doc


if __name__ == "__main__":
    freeze(force="--force" in sys.argv)
