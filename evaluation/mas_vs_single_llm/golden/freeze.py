"""
golden/freeze.py — FREEZE the golden set + ground truth (Phase 2 freeze gate).

Seals the approved candidate into:
  results/golden/golden_set.json     (frozen, self-describing: sha256 + timestamp + git commit)
  results/golden/ground_truth.json   (frozen)
and records the freeze in results/manifest.json.

SAFETY: refuses to overwrite an already-frozen file (constraint: never edit a frozen artifact).
Re-freezing requires deleting the frozen files by hand AND a deliberate --force.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from manifest import record_phase, git_info, now_iso

OUT = Path(__file__).resolve().parent.parent / "results" / "golden"


def sha256_of_items(items: list) -> str:
    """Stable hash over the canonical JSON of the items payload (order-independent keys)."""
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def _seal(artifact: str, items: list, meta: dict) -> tuple[Path, str]:
    h = sha256_of_items(items)
    doc = {
        "frozen": True,
        "phase": "2",
        "artifact": artifact,
        "scope": "ENG-PL, seasons 2020-2021..2024-2025",
        "generated_at": meta["ts"],
        "git_commit": meta["git_commit"],
        "git_dirty": meta["git_dirty"],
        "n_items": len(items),
        "sha256": h,
        "items": items,
    }
    path = OUT / f"{artifact}.json"
    path.write_text(json.dumps(doc, indent=2, default=str))
    return path, h


def freeze(force: bool = False) -> dict:
    targets = [OUT / "golden_set.json", OUT / "ground_truth.json"]
    existing = [p for p in targets if p.exists()]
    if existing and not force:
        raise SystemExit(
            "Refusing to overwrite already-frozen artifact(s): "
            f"{[p.name for p in existing]}. Frozen artifacts must not be edited. "
            "Delete them by hand and pass --force only if you intend to re-freeze.")

    gs = json.loads((OUT / "golden_set.candidate.json").read_text())["items"]
    gt = json.loads((OUT / "ground_truth.candidate.json").read_text())["items"]

    gi = git_info()
    meta = {"ts": now_iso(), **gi}

    gs_path, gs_hash = _seal("golden_set", gs, meta)
    gt_path, gt_hash = _seal("ground_truth", gt, meta)

    entry = {
        "frozen_at": meta["ts"],
        "git_commit": gi["git_commit"],
        "git_dirty": gi["git_dirty"],
        "scope": "ENG-PL, seasons 2020-2021..2024-2025",
        "memory_enabled": False,
        "files": {
            "golden_set.json": {"sha256": gs_hash, "n_items": len(gs)},
            "ground_truth.json": {"sha256": gt_hash, "n_items": len(gt)},
        },
        "note": "canonical_sql drafted by Claude, approved by Till (delegated). "
                "Ground truth = result of running canonical_sql.",
    }
    record_phase("phase2_golden_set", entry)

    print("FROZEN:")
    print(f"  {gs_path.name}  n={len(gs)}  sha256={gs_hash}")
    print(f"  {gt_path.name}  n={len(gt)}  sha256={gt_hash}")
    print(f"  git_commit={gi['git_commit']}  dirty={gi['git_dirty']}")
    print(f"  manifest updated: {OUT.parent/'manifest.json'}")
    if gi.get("git_dirty"):
        print("\n  NOTE: working tree is dirty — the v5 code that generated this is not yet "
              "committed. The SHA256 above is the integrity anchor; commit the code to make "
              "git provenance precise.")
    return entry


if __name__ == "__main__":
    freeze(force="--force" in sys.argv)
