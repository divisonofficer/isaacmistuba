from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_project_sys_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for rel in (
        "modules/navigation_dataset/src",
        "modules/robomituba_bridge/src",
        "modules/mitsuba_converter/src",
    ):
        path = str(repo_root / rel)
        if path not in sys.path:
            sys.path.insert(0, path)


_bootstrap_project_sys_path()

from navigation_dataset.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
