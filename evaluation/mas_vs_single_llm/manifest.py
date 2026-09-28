"""
manifest.py — writes/updates results/manifest.json.

Records per-phase provenance: git commit + dirty flag, timestamp, frozen-artifact SHA256s,
and (for scored phases) model versions / temperature / repeat count / memory_enabled.
The SHA256 of a frozen artifact is the real tamper-evidence anchor (git commit is context).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "results" / "manifest.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_info() -> dict:
    """Current HEAD commit + whether the working tree is dirty (uncommitted changes)."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().strip())
        return {"git_commit": commit, "git_dirty": dirty}
    except Exception as e:  # noqa: BLE001
        return {"git_commit": None, "git_dirty": None, "git_error": str(e)}


def load() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {
        "project": "agent_v5",
        "memory_enabled_for_scored_runs": False,   # constraint 10 — global default
        "phases": {},
    }


def record_phase(phase_key: str, data: dict) -> dict:
    """Merge a phase record into manifest.json and persist."""
    m = load()
    m.setdefault("phases", {})[phase_key] = data
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(m, indent=2, default=str))
    return m


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
    print("git:", git_info())
