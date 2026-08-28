#!/usr/bin/env python3
"""Create render-only structural-glass wall repairs for imported office scenes.

The migration derives cut OBJ files from every opaque wall owner (room and
corridor) and writes
``geometry_overrides.json``. It never changes an authoring map, source GLB, or
Blend. Use ``--dry-run`` first; ``--apply`` requires the bundled Blender.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENES = ("infinigen_office_20260822", "infinigen_office_20260824")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_dir(project: str, scene_id: str) -> Path:
    return REPO_ROOT / "out" / "opticalnav" / project / "scenes" / scene_id


def _patch_render_xml(scene_dir: Path, repairs: list[dict[str, Any]]) -> None:
    """Point existing shape nodes at the immutable repair meshes immediately.

    A daemon sync will independently derive the same result from
    ``geometry_overrides.json``.  Patching here prevents a queued/stalled sync
    from leaving the old backing wall live in the meantime.
    """
    by_id = {str(item["object_id"]): item for item in repairs}
    for xml_path in (scene_dir / "render_scene.xml", scene_dir / "render_scene_perturbed.xml"):
        if not xml_path.is_file():
            continue
        backup = xml_path.with_name(f"render_only_glass_repair.{xml_path.name}.bak")
        if not backup.exists():
            shutil.copy2(xml_path, backup)
        tree = ET.parse(xml_path)
        for shape in tree.getroot().iter("shape"):
            repair = by_id.get(str(shape.get("id") or ""))
            if not repair:
                continue
            mesh = (REPO_ROOT / str(repair["source_ref"])).resolve()
            cached = scene_dir / "mesh_cache" / "render_only_glass_repair" / mesh.name
            cached.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mesh, cached)
            filename = next((item for item in shape if item.tag == "string" and item.get("name") == "filename"), None)
            if filename is None:
                raise ValueError(f"shape {shape.get('id')} has no OBJ filename")
            filename.set("value", str(cached))
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _patch_xml_preview_index(scene_dir: Path, repairs: list[dict[str, Any]]) -> None:
    """Update just the repaired preview records without rescanning huge meshes."""
    index_path = scene_dir / "xml_scene_index.json"
    if not index_path.is_file():
        return
    index = _read(index_path)
    by_id = {str(item["object_id"]): item for item in repairs}
    for shape in index.get("shapes") or []:
        repair = by_id.get(str(shape.get("shape_id") or shape.get("object_id") or ""))
        if not repair:
            continue
        cache = scene_dir / "mesh_cache" / "render_only_glass_repair" / Path(str(repair["source_ref"])).name
        shape["mesh_path"] = str(cache)
        shape["mesh_ref"] = cache.relative_to(scene_dir / "mesh_cache").as_posix()
        shape["mesh_bytes"] = cache.stat().st_size
        shape["preview_mesh_path"] = str(cache)
        shape["preview_mesh_ref"] = shape["mesh_ref"]
        shape["preview_mesh_bytes"] = shape["mesh_bytes"]
        shape["preview_mesh_status"] = "render_only_glass_repair"
        shape["source_ref"] = str(repair["source_ref"])
    index["xml_mtime_ns"] = (scene_dir / "render_scene.xml").stat().st_mtime_ns
    _write_atomic(index_path, index)


def _repair_plan(scene_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = _read(scene_dir / "office_layout_manifest.json")
    authoring = _read(scene_dir / "authoring_map.json")
    spec = manifest.get("structural_glass") or {}
    segments = spec.get("segments") or []
    objects = {str(item.get("id") or ""): item for item in authoring.get("objects") or [] if isinstance(item, dict)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        room = str(segment.get("room") or "")
        corridor = str(segment.get("corridor") or "")
        owners = segment.get("opaque_wall_owners")
        # v2 manifests omitted this field, but its room/corridor boundary is
        # still authoritative.  Both shells must be cut: repairing only the
        # corridor owner leaves the room-side opaque wall directly behind the
        # dielectric pane, which is exactly the half-glass failure seen in the
        # editor and RGB/polar previews.
        expected_owners = [room, corridor]
        if owners is None:
            owners = expected_owners
        if not isinstance(owners, list) or owners != expected_owners or not room or not corridor:
            raise ValueError(f"invalid opaque_wall_owners in {segment.get('segment_id')}")
        for owner in owners:
            grouped.setdefault(str(owner).replace("/", "_") + ".wall", []).append(segment)
    plan, absent_owner_segments = [], []
    for object_id, cuts in sorted(grouped.items()):
        obj = objects.get(object_id)
        source_ref = str((obj or {}).get("source_ref") or "")
        source = (REPO_ROOT / source_ref).resolve()
        if not obj:
            # Some legacy Infinigen hallway cells emit no standalone wall mesh.
            # There is no opaque backing surface to remove in that case.
            absent_owner_segments.extend({"object_id": object_id, "segment_id": str(cut.get("segment_id"))} for cut in cuts)
            continue
        if not source_ref or not source.is_file() or source.suffix.lower() not in {".glb", ".gltf"}:
            raise FileNotFoundError(f"missing corridor GLB for {object_id}: {source_ref}")
        plan.append({"object_id": object_id, "source_ref": source_ref, "source": source, "segments": cuts})
    if not plan and not absent_owner_segments:
        raise ValueError("no corridor wall repairs found")
    return plan, absent_owner_segments


def repair_scene(project: str, scene_id: str, *, apply: bool, rollback: bool = False) -> dict[str, Any]:
    scene_dir = _scene_dir(project, scene_id)
    if rollback:
        backup = scene_dir / "render_only_glass_repair.backup.json"
        if not backup.is_file():
            return {"scene_id": scene_id, "status": "nothing_to_rollback"}
        previous = _read(backup)
        _write_atomic(scene_dir / "geometry_overrides.json", previous.get("geometry_overrides") or {})
        xml_backup = scene_dir / "render_only_glass_repair.render_scene.xml.bak"
        if xml_backup.is_file():
            shutil.copy2(xml_backup, scene_dir / "render_scene.xml")
        return {"scene_id": scene_id, "status": "rolled_back"}
    plan, absent_owner_segments = _repair_plan(scene_dir)
    existing = _read(scene_dir / "render_only_glass_repair.json") if (scene_dir / "render_only_glass_repair.json").is_file() else None
    source_fingerprint = hashlib.sha256(json.dumps(
        [(item["object_id"], _sha256(item["source"]), [s["segment_id"] for s in item["segments"]]) for item in plan],
        sort_keys=True).encode()).hexdigest()
    if existing and existing.get("source_fingerprint") == source_fingerprint:
        repairs = existing.get("repairs") or []
        if isinstance(repairs, list):
            _patch_render_xml(scene_dir, repairs)
            _patch_xml_preview_index(scene_dir, repairs)
        return {"scene_id": scene_id, "status": "already_applied", "objects": len(plan)}
    result = {"scene_id": scene_id, "status": "planned" if not apply else "repaired", "objects": len(plan),
              "source_fingerprint": source_fingerprint, "repairs": [], "absent_owner_segments": absent_owner_segments}
    if not apply:
        return result
    overrides_path = scene_dir / "geometry_overrides.json"
    previous_overrides = _read(overrides_path) if overrides_path.is_file() else {"overrides": []}
    _write_atomic(scene_dir / "render_only_glass_repair.backup.json", {"geometry_overrides": previous_overrides})
    repair_dir = scene_dir / "render_only_glass_repair"
    overrides = [item for item in previous_overrides.get("overrides") or [] if str(item.get("reason")) != "structural_glass_backing_wall_v1"]
    for item in plan:
        segments_path = repair_dir / f"{item['object_id']}.segments.json"
        output = repair_dir / f"{item['object_id']}.obj"
        _write_atomic(segments_path, {"segments": item["segments"]})
        # The Blender helper accepts a JSON list, not its wrapper object.
        segments_path.write_text(json.dumps(item["segments"]), encoding="utf-8")
        command = [sys.executable, str(REPO_ROOT / "tools/infinigen/run_bundled_blender.py"), "--background",
                   "--python", str(REPO_ROOT / "tools/infinigen/blender_cut_glass_wall_override.py"), "--",
                   "--source", str(item["source"]), "--segments", str(segments_path), "--output", str(output)]
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"Blender did not produce repaired mesh: {output}")
        rel = output.relative_to(REPO_ROOT).as_posix()
        overrides.append({"object_id": item["object_id"], "source_ref": rel,
                          "reason": "structural_glass_backing_wall_v1", "audit_digest": _sha256(output)})
        result["repairs"].append({"object_id": item["object_id"], "segments": [s["segment_id"] for s in item["segments"]],
                                  "source_ref": rel, "sha256": _sha256(output)})
    _write_atomic(overrides_path, {"schema": "robomituba.geometry_overrides.v1", "overrides": overrides})
    _write_atomic(scene_dir / "render_only_glass_repair.json", {"schema": "robomituba.render_only_glass_repair.v1",
        "applied_at": datetime.now(UTC).isoformat(), "source_fingerprint": source_fingerprint,
        "repairs": result["repairs"], "stale_on_source_sync": True})
    _patch_render_xml(scene_dir, result["repairs"])
    _patch_xml_preview_index(scene_dir, result["repairs"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", action="append", default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    scenes = tuple(args.scene) or DEFAULT_SCENES
    results = [repair_scene(args.project, scene, apply=bool(args.apply), rollback=bool(args.rollback)) for scene in scenes]
    print(json.dumps({"mode": "apply" if args.apply else "rollback" if args.rollback else "dry_run", "scenes": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
