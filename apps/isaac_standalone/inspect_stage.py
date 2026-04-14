from __future__ import annotations

import argparse
import json

from apps.isaac_standalone._bootstrap import bootstrap_repo_paths

bootstrap_repo_paths()

from apps.isaac_standalone._stage_bridge import inspect_stage_summary, load_stage


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the current Isaac Sim stage or a USD file.")
    parser.add_argument("--usd", default=None, help="Optional USD file to inspect instead of the current Isaac stage.")
    args = parser.parse_args()

    stage, source_usd_path = load_stage(usd_path=args.usd)
    print(json.dumps(inspect_stage_summary(stage, source_usd_path=source_usd_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
