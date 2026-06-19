"""
Phase 1: Restore editor mesh display for authoring_map objects.

Every object with a source_ref of the form  usd_file#/prim/path  should have
  metadata.asset_source_path = "/prim/path"
  metadata.usd_ref           = "assets/moorelane/..."

Without these fields MapEditor3D.svelte never calls the /prim-mesh endpoint and
falls back to hardcoded chair/table/plant/box proxy shapes.

Usage:
  # single scene
  python apps/fix_authoring_map_metadata.py --project opticalnav-v0.2 --scene office_lobby_001

  # all scenes in a project
  python apps/fix_authoring_map_metadata.py --project opticalnav-v0.2

  # dry-run (show counts without writing)
  python apps/fix_authoring_map_metadata.py --project opticalnav-v0.2 --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPTICALNAV_ROOT = REPO_ROOT / "out" / "opticalnav"


def fix_scene(authoring_map_path: Path, *, dry_run: bool = False) -> dict:
    raw = json.loads(authoring_map_path.read_text(encoding="utf-8"))
    objects = raw.get("objects") or []

    patched = 0
    skipped_no_ref = 0
    already_ok = 0

    for obj in objects:
        source_ref = obj.get("source_ref") or ""
        if "#" not in source_ref:
            skipped_no_ref += 1
            continue

        usd_ref, prim_path = source_ref.split("#", 1)
        meta = obj.setdefault("metadata", {})

        # Only write if missing; don't overwrite explicitly set values.
        changed = False
        if not meta.get("asset_source_path"):
            meta["asset_source_path"] = prim_path
            changed = True
        if not meta.get("usd_ref"):
            meta["usd_ref"] = usd_ref
            changed = True

        if changed:
            patched += 1
        else:
            already_ok += 1

    stats = {
        "total": len(objects),
        "patched": patched,
        "already_ok": already_ok,
        "skipped_no_ref": skipped_no_ref,
    }

    if not dry_run and patched > 0:
        authoring_map_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate metadata.asset_source_path from source_ref")
    parser.add_argument("--project", required=True, help="Project ID (e.g. opticalnav-v0.2)")
    parser.add_argument("--scene", default=None, help="Scene ID (omit for all scenes)")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing")
    args = parser.parse_args()

    project_dir = OPTICALNAV_ROOT / args.project
    if not project_dir.exists():
        print(f"[ERROR] Project not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    scenes_dir = project_dir / "scenes"
    if args.scene:
        scene_dirs = [scenes_dir / args.scene]
    else:
        scene_dirs = sorted(p for p in scenes_dir.iterdir() if p.is_dir())

    any_patched = False
    for scene_dir in scene_dirs:
        am_path = scene_dir / "authoring_map.json"
        if not am_path.exists():
            print(f"  [{scene_dir.name}] no authoring_map.json — skip")
            continue

        stats = fix_scene(am_path, dry_run=args.dry_run)
        tag = "[DRY-RUN] " if args.dry_run else ""
        print(
            f"  {tag}[{scene_dir.name}] total={stats['total']}  "
            f"patched={stats['patched']}  already_ok={stats['already_ok']}  "
            f"skipped_no_ref={stats['skipped_no_ref']}"
        )
        if stats["patched"] > 0:
            any_patched = True

    if any_patched and not args.dry_run:
        print("\nDone. Restart the daemon or call PUT /authoring-map to regenerate render_scene.xml.")
    elif not any_patched:
        print("\nNothing to patch — all objects already have asset_source_path set.")


if __name__ == "__main__":
    main()
