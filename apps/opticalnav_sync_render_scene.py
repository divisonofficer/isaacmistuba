#!/usr/bin/env python3
"""Stage an OpticalNav scene's render XML/mesh cache without a running daemon.

The render-scene sync used to be reachable only through the daemon's HTTP
route, so re-staging a scene locally required a daemon that was up, reachable
and running the code you just changed.  This runs the same sync in-process.

Examples:
    python apps/opticalnav_sync_render_scene.py --scene infinigen_office_20260823
    python apps/opticalnav_sync_render_scene.py --scene my_scene --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _module_path in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
):
    if str(_module_path) not in sys.path:
        sys.path.insert(0, str(_module_path))

from mitsuba_converter.render_scene_sync import (  # noqa: E402
    RenderSceneSyncBusy,
    daemon_is_reachable,
    sync_render_scene,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", required=True, help="Scene id under <project>/scenes/.")
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--daemon-url", default="http://127.0.0.1:8765")
    parser.add_argument(
        "--allow-running-daemon",
        action="store_true",
        help=(
            "Sync even though a daemon is reachable. The daemon serialises syncs with a "
            "process-local lock, so a UI 'Sync' on this scene would race us."
        ),
    )
    parser.add_argument("--camera-rig", default=None, help="Camera rig id to stage with.")
    parser.add_argument("--environment", default=None, help="Environment/lighting preset id.")
    parser.add_argument("--scene-variant-id", default=None)
    parser.add_argument("--quiet", action="store_true", help="Suppress per-stage progress lines.")
    parser.add_argument("--json", action="store_true", help="Print the full result body as JSON.")
    return parser.parse_args()


def main() -> int:
    args = _args()
    payload = {
        key: value
        for key, value in (
            ("camera_rig", args.camera_rig),
            ("environment", args.environment),
            ("scene_variant_id", args.scene_variant_id),
        )
        if value is not None
    }

    if not args.allow_running_daemon and daemon_is_reachable(args.daemon_url):
        print(
            f"[error] a render daemon is answering at {args.daemon_url}.\n"
            "        Its sync lock is process-local, so staging this scene here would race\n"
            "        anything it syncs (including a 'Sync' click in webui). Either let the\n"
            "        daemon do it:\n"
            f"          curl -X POST -d '{{}}' -H 'Content-Type: application/json' \\\n"
            f"            {args.daemon_url}/api/opticalnav/projects/{args.project}/scenes/{args.scene}/sync/render-scene\n"
            "        or stop the daemon, or pass --allow-running-daemon if you know it is\n"
            "        not touching this scene.",
            file=sys.stderr,
        )
        return 3

    def progress(done: int, total: int, stage: str, message: str) -> None:
        if not args.quiet:
            print(f"[{stage}] {done}/{total} {message}".rstrip(), flush=True)

    try:
        result = sync_render_scene(
            args.repo_root, args.project, args.scene, payload, progress_cb=progress,
        )
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    except RenderSceneSyncBusy as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 4

    if args.json:
        print(json.dumps(result.body, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        stats = result.mesh_stats
        # These three explain the common failure at a glance: how much geometry
        # was staged, how much fell back to a cube, and how much the scene-local
        # cache rescued after an import directory went missing.
        interesting = ("glb_mesh_parts", "glb_missing", "glb_missing_recovered_from_cache")
        summary = "  ".join(f"{key}={stats[key]}" for key in interesting if key in stats)
        print(f"[sync] {args.scene}: HTTP {result.status_code}" + (f"  {summary}" if summary else ""))

    if not result.ok:
        print(f"[error] {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
