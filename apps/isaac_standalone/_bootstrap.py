from __future__ import annotations

from pathlib import Path
import sys


def bootstrap_repo_paths() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in [
        repo_root,
        repo_root / "modules/robomituba_bridge/src",
        repo_root / "modules/mitsuba_converter/src",
    ]:
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
    return repo_root
