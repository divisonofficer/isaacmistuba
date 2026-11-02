#!/usr/bin/env python3
"""Add back rooms the Infinigen import dropped, without re-importing the scene.

Stage 2 keeps a room only when at least one furniture unit sits inside its
floor footprint (``_select_rooms``), so an unfurnished balcony, bedroom or
garage is discarded together with its floor, walls and ceiling.  The navigation
surface is built from the traversable grid, not from that decision, so paths
still run through the discarded room -- through open space where a wall should
be.

Re-running the whole import would fix the geometry and rebuild
``authoring_map.json`` from scratch, which renumbers nothing but does replace
the file every downstream artifact was derived from: place/support graphs and
the episode set built on them.  This instead converts the scene a second time
into a throwaway scene id *with* ``--keep-empty-rooms``, and copies only the
objects that appear solely in that run into the real map.  Existing objects are
never rewritten, so their ids -- and everything keyed on them -- survive.

After a restore the scene's traversable grid and graphs should be rebuilt: the
new walls change what is reachable.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _room_key(blender_name: str | None) -> str | None:
    """Mirror of ``import_infinigen_scene._room_key``: ``x_0/0.wall`` -> ``x_0/0``."""
    import re

    match = re.match(r"^(.+?)\.(wall|floor|ceiling|exterior)$", str(blender_name or ""))
    return match.group(1) if match else None


def _rebase_object(obj: dict[str, Any], delta: list[float]) -> dict[str, Any]:
    """Move one object from the probe's origin frame into the scene's.

    Both runs normalise raw Infinigen world coordinates by subtracting an
    ``origin_offset`` derived from the kept rooms' bounding box.  Restoring a
    room enlarges that box, so the probe picks a different offset and every
    coordinate it emits is shifted by the difference.  Merging without this
    correction puts the recovered walls metres away from the room they bound.
    """
    if not any(delta):
        return obj
    moved = json.loads(json.dumps(obj))
    geometry = moved.get("geometry")
    if isinstance(geometry, dict):
        for key in ("center", "start", "end"):
            point = geometry.get(key)
            if isinstance(point, list):
                geometry[key] = [
                    value + delta[index] if index < len(delta) and isinstance(value, (int, float)) else value
                    for index, value in enumerate(point)
                ]
        base = geometry.get("base_height_m")
        if isinstance(base, (int, float)) and len(delta) > 2:
            geometry["base_height_m"] = base + delta[2]
    metadata = moved.get("metadata")
    if isinstance(metadata, dict):
        for key in ("world_bbox_min", "world_bbox_max"):
            box = metadata.get(key)
            if isinstance(box, list):
                metadata[key] = [
                    value + delta[index] if index < len(delta) and isinstance(value, (int, float)) else value
                    for index, value in enumerate(box)
                ]
    return moved


def _object_rooms(obj: dict[str, Any]) -> set[str]:
    extras = obj.get("extras") or {}
    keys = set()
    for candidate in (extras.get("blender_name"), obj.get("id"), obj.get("label")):
        key = _room_key(candidate)
        if key:
            keys.add(key)
    return keys


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--rooms",
        default=None,
        help="Comma-separated room keys to restore (default: the scene's recorded dropped_rooms).",
    )
    parser.add_argument("--stage1-profile", default="strict-pbr-v1")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be added and stop.")
    parser.add_argument("--keep-probe", action="store_true", help="Do not delete the throwaway probe scene.")
    return parser.parse_args()


def main() -> int:
    args = _args()
    root = Path(args.repo_root).resolve()
    project_dir = root / "out" / "opticalnav" / args.project
    scene_dir = project_dir / "scenes" / args.scene
    map_path = scene_dir / "authoring_map.json"
    if not map_path.is_file():
        print(f"[error] authoring map not found: {map_path}", file=sys.stderr)
        return 2

    current = _read_json(map_path)
    metadata = current.get("metadata") or {}
    recorded = [str(r) for r in (metadata.get("dropped_rooms") or [])]
    rooms = [r.strip() for r in args.rooms.split(",") if r.strip()] if args.rooms else recorded
    if not rooms:
        print(f"[ok] {args.scene}: no dropped rooms recorded; nothing to restore.")
        return 0

    import_root = str(metadata.get("import_root") or "")
    manifest = root / import_root / "scene_manifest.json" if import_root else None
    if manifest is None or not manifest.is_file():
        print(
            f"[error] stage-1 manifest missing: {manifest}\n"
            "        The room geometry only exists in the import directory. Re-run\n"
            "        apps/run_infinigen_import.sh ... --bake-only to rebuild it first.",
            file=sys.stderr,
        )
        return 2

    print(f"[restore] {args.scene}: rooms={rooms}")
    print(f"[restore] stage-1 manifest: {manifest}")

    # The probe id has to be unique per run.  It names both the throwaway scene
    # and the fixture the importer writes under out/infinigen_imports/, so two
    # restores of one scene (a second operator, a retry) would overwrite each
    # other's fixture mid-read and fail with "Expecting value: line 1 column 1".
    probe_id = f"{args.scene}__restore_probe_{os.getpid()}_{int(time.time())}"
    probe_dir = project_dir / "scenes" / probe_id
    if probe_dir.exists():
        shutil.rmtree(probe_dir)
    command = [
        sys.executable, str(root / "apps" / "import_infinigen_scene.py"),
        "--manifest", str(manifest),
        "--scene-id", probe_id,
        "--project-id", args.project,
        "--stage1-profile", args.stage1_profile,
        "--keep-empty-rooms", "--force",
    ]
    print("[restore] " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=root, text=True)
    if result.returncode:
        print(f"[error] probe conversion failed ({result.returncode})", file=sys.stderr)
        return 1

    probe_map = probe_dir / "authoring_map.json"
    if not probe_map.is_file():
        print(f"[error] probe produced no authoring map: {probe_map}", file=sys.stderr)
        return 1
    probe = _read_json(probe_map)

    # Restoring rooms grows the scene's bounding box, so the probe normalises
    # coordinates against a different origin. Everything it emits has to be
    # moved back into the frame the existing objects (and every graph built on
    # them) already use.
    # Verified against this scene: an authoring coordinate is the raw Infinigen
    # one PLUS origin_offset (a wall at raw x=13.594 lands at 15.987 under
    # offset 2.3926).  So undo the probe's offset and apply the scene's:
    #   scene = probe - probe_origin + scene_origin
    scene_origin = [float(v) for v in (metadata.get("origin_offset") or [0.0, 0.0, 0.0])]
    probe_origin = [float(v) for v in ((probe.get("metadata") or {}).get("origin_offset") or scene_origin)]
    delta = [s - p for s, p in zip(scene_origin, probe_origin)]
    if any(abs(d) > 1e-9 for d in delta):
        print(f"[restore] origin_offset scene={scene_origin} probe={probe_origin}")
        print(f"[restore] rebasing restored objects by {delta}")
    else:
        print(f"[restore] origin_offset matches ({scene_origin}); no rebase needed")

    have = {str(obj.get("id")) for obj in current.get("objects") or []}
    wanted = set(rooms)
    additions = [
        _rebase_object(obj, delta) for obj in probe.get("objects") or []
        if str(obj.get("id")) not in have and (_object_rooms(obj) & wanted)
    ]
    # Objects the probe places inside a restored room carry no room-named mesh
    # (furniture, windows). Admit them only when they are new *and* the probe
    # gained them because of these rooms, i.e. every other new object is left
    # alone rather than silently pulled in.
    other_new = [
        obj for obj in probe.get("objects") or []
        if str(obj.get("id")) not in have and not (_object_rooms(obj) & wanted)
    ]

    print(f"[restore] probe objects={len(probe.get('objects') or [])} · current={len(have)}")
    print(f"[restore] restoring {len(additions)} object(s) for {rooms}")
    if other_new:
        print(f"[restore] {len(other_new)} other new object(s) NOT added (not room-keyed): "
              f"{[str(o.get('id'))[:40] for o in other_new[:5]]}")
    for obj in additions[:10]:
        print(f"    + {obj.get('type'):<12} {str(obj.get('id'))[:60]}")
    if len(additions) > 10:
        print(f"    ... and {len(additions) - 10} more")

    if args.dry_run:
        print("[dry-run] no files written.")
        if not args.keep_probe:
            shutil.rmtree(probe_dir, ignore_errors=True)
        return 0
    if not additions:
        print("[restore] nothing to add.")
        if not args.keep_probe:
            shutil.rmtree(probe_dir, ignore_errors=True)
        return 0

    # An object names its material by id; the scene rejects the whole authoring
    # map with "Unknown material preset" if that id is not in its own materials
    # list.  The restored rooms use presets no kept room referenced, so their
    # material entries have to come across with them.
    have_materials = {str(m.get("material_id")) for m in current.get("materials") or []}
    needed = {str(obj.get("material")) for obj in additions if obj.get("material")}
    probe_materials = {str(m.get("material_id")): m for m in probe.get("materials") or []}
    new_materials = [probe_materials[name] for name in sorted(needed - have_materials) if name in probe_materials]
    unresolved = sorted(needed - have_materials - set(probe_materials))
    if new_materials:
        print(f"[restore] adding {len(new_materials)} material(s): "
              f"{[str(m.get('material_id'))[:44] for m in new_materials]}")
    if unresolved:
        print(f"[error] {len(unresolved)} material(s) referenced by the restored rooms are in "
              f"neither map: {unresolved}", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = map_path.with_suffix(f".json.{stamp}.pre_room_restore.bak")
    shutil.copy2(map_path, backup)
    print(f"[restore] backup: {backup}")

    current.setdefault("objects", []).extend(additions)
    if new_materials:
        current.setdefault("materials", []).extend(new_materials)
    metadata["kept_rooms"] = sorted(set(metadata.get("kept_rooms") or []) | wanted)
    metadata["dropped_rooms"] = sorted(set(recorded) - wanted)
    metadata.setdefault("room_restores", []).append({
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "rooms": sorted(wanted),
        "objects_added": len(additions),
        "materials_added": [str(m.get("material_id")) for m in new_materials],
        "probe_scene_id": probe_id,
        "source_manifest": str(manifest.relative_to(root)),
    })
    current["metadata"] = metadata
    _write_json_atomic(map_path, current)
    print(f"[restore] authoring_map objects {len(have)} -> {len(current['objects'])}")

    if not args.keep_probe:
        shutil.rmtree(probe_dir, ignore_errors=True)
        print(f"[restore] probe scene removed: {probe_id}")

    print(
        "\n[next] the new walls change what is reachable. Rebuild the scene's\n"
        "       traversable grid / graphs, then re-stage:\n"
        f"         python apps/opticalnav_sync_render_scene.py --scene {args.scene}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
