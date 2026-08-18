"""Blender-side consumer for ``robomituba.ir_scene_domain.v1``.

The effective Mitsuba scene records which Blender object/material faces were
removed.  This adapter applies exactly those removals to temporary mesh copies
inside a headless Blender process; the source ``.blend`` is never saved or
modified on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
from pathlib import Path
from typing import Any, Iterable

import bmesh  # type: ignore
import bpy  # type: ignore


_SCHEMA = "robomituba.ir_scene_domain.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_domain(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != _SCHEMA:
        raise ValueError(f"unsupported IR scene-domain contract: {path}")
    if not payload.get("effective_scene_digest"):
        raise ValueError(f"IR scene-domain contract has no effective_scene_digest: {path}")
    return payload


def apply_face_exclusion(domain: dict[str, Any] | None) -> tuple[list[tuple[object, object]], dict[str, Any]]:
    """Return restore handles after deleting selected material faces from mesh copies."""
    if domain is None:
        return [], {
            "requested_selector_count": 0, "resolved_selector_count": 0,
            "unresolved_selector_count": 0, "applied_selector_count": 0,
            "removed_face_count": 0, "removed_triangle_count": 0, "selectors": [],
        }
    selectors = domain.get("exclusion", {}).get("blender_face_selectors") or []
    by_object: dict[str, set[str]] = {}
    for selector in selectors:
        if not isinstance(selector, dict):
            raise ValueError("invalid Blender face selector in IR scene-domain contract")
        obj = str(selector.get("blender_object") or "")
        material = str(selector.get("blender_material") or "")
        if not obj or not material:
            raise ValueError(f"invalid Blender face selector: {selector!r}")
        by_object.setdefault(obj, set()).add(material)

    restore: list[tuple[object, object]] = []
    applied: list[dict[str, Any]] = []
    removed_faces = 0
    removed_triangles = 0
    requested_selector_count = sum(len(materials) for materials in by_object.values())
    resolved_selector_count = 0
    for object_name, materials in sorted(by_object.items()):
        obj = bpy.data.objects.get(object_name)
        if obj is None or obj.type != "MESH":
            raise ValueError(f"IR Blender selector object is missing or not a mesh: {object_name}")
        slot_indices = {
            index for index, slot in enumerate(obj.material_slots)
            if slot.material is not None and slot.material.name in materials
        }
        matched_materials = {
            slot.material.name for index, slot in enumerate(obj.material_slots)
            if index in slot_indices and slot.material is not None
        }
        missing = sorted(materials - matched_materials)
        whole_object = False
        if missing:
            if not obj.material_slots:
                whole_object = True
            else:
                raise ValueError(
                    f"IR Blender selector material is absent from {object_name}: {', '.join(missing)}"
                )
        copied_mesh = obj.data.copy()
        bm = bmesh.new()
        try:
            bm.from_mesh(copied_mesh)
            doomed = list(bm.faces) if whole_object else [face for face in bm.faces if face.material_index in slot_indices]
            if not doomed:
                raise ValueError(
                    f"IR Blender selector has no faces on {object_name} for {sorted(materials)}"
                )
            doomed_triangles = sum(max(0, len(face.verts) - 2) for face in doomed)
            bmesh.ops.delete(bm, geom=doomed, context="FACES")
            bm.to_mesh(copied_mesh)
            copied_mesh.update()
        finally:
            bm.free()
        original_mesh = obj.data
        obj.data = copied_mesh
        restore.append((obj, original_mesh))
        removed_faces += len(doomed)
        removed_triangles += doomed_triangles
        resolved_selector_count += len(materials)
        applied.append({
            "blender_object": object_name,
            "blender_materials": sorted(materials),
            "mode": "whole_object_no_material_slots" if whole_object else "material_faces",
            "removed_face_count": len(doomed),
            "removed_triangle_count": doomed_triangles,
        })
    return restore, {
        # selector count and object count differ when an object has several
        # dielectric material slots; publish both so audit never mistakes a
        # grouped material-face deletion for an unresolved selector.
        "requested_selector_count": requested_selector_count,
        "resolved_selector_count": resolved_selector_count,
        "unresolved_selector_count": requested_selector_count - resolved_selector_count,
        "applied_selector_count": len(applied),
        "removed_face_count": removed_faces,
        "removed_triangle_count": removed_triangles,
        "selectors": applied,
    }


def restore_face_exclusion(handles: Iterable[tuple[object, object]]) -> None:
    for obj, original_mesh in reversed(list(handles)):
        copied = obj.data
        obj.data = original_mesh
        try:
            bpy.data.meshes.remove(copied)
        except Exception:
            pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def fingerprint(
    *, graph_path: Path, source_blend: Path, args: Any, domain: dict[str, Any] | None,
    frame_ids: Iterable[str],
) -> dict[str, Any]:
    pose_manifest = getattr(args, "pose_manifest", None)
    return {
        "schema": "robomituba.blender_gt_run.v2",
        "source_blend": str(source_blend.resolve()),
        "source_blend_sha256": _sha256(source_blend),
        "scene_graph": str(graph_path.resolve()),
        "scene_graph_sha256": _sha256(graph_path),
        "effective_scene_digest": (domain or {}).get("effective_scene_digest"),
        "surface_domain": (domain or {}).get("surface_domain", "all"),
        "width": int(args.width),
        "height": int(args.height),
        "fov": float(args.fov),
        "eye_height": float(args.eye_height),
        "target_height": None if args.target_height is None else float(args.target_height),
        "samples": int(args.samples),
        "engine": str(args.engine),
        "pose_contract": "observation_camera_to_world_v1",
        "pose_manifest": str(pose_manifest.resolve()) if pose_manifest is not None else None,
        "pose_manifest_sha256": _sha256(pose_manifest) if pose_manifest is not None else None,
        "require_pose_manifest": bool(getattr(args, "require_pose_manifest", False)),
        "frame_ids": list(frame_ids),
    }


def _png_header_matches(path: Path, width: int, height: int) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(29)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return False
        actual_width, actual_height = struct.unpack(">II", header[16:24])
        return actual_width == int(width) and actual_height == int(height)
    except OSError:
        return False


def complete_frame(out: Path, frame_id: str, stems: Iterable[str], *, width: int, height: int) -> bool:
    return all(
        _png_header_matches(out / stem / f"{frame_id}.png", width, height)
        for stem in stems
    )


def prepare_resume(
    *, out: Path, fingerprint_value: dict[str, Any], stems: Iterable[str], resume: bool, adopt_existing: bool,
) -> set[str]:
    path = out / "gt_progress.json"
    stems = list(stems)
    existing_files = any((out / stem).is_dir() and any((out / stem).glob("*.png")) for stem in stems)
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        old = dict(state.get("fingerprint") or {})
        if old != fingerprint_value:
            raise ValueError("GT resume state does not match source blend/graph/camera/domain fingerprint")
        if not resume:
            raise ValueError("GT output already has progress state; pass --resume or choose a new output directory")
    elif existing_files and not adopt_existing:
        raise ValueError("GT output has artifacts without progress state; pass --adopt-existing to scan them")
    elif existing_files and not resume:
        raise ValueError("--adopt-existing also requires --resume")
    completed = {
        frame_id for frame_id in fingerprint_value["frame_ids"]
        if resume and complete_frame(
            out, frame_id, stems, width=fingerprint_value["width"], height=fingerprint_value["height"],
        )
    }
    _atomic_json(path, {
        "schema": "robomituba.blender_gt_progress.v1",
        "fingerprint": fingerprint_value,
        "completed_frame_ids": sorted(completed),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return completed


def record_progress(out: Path, fingerprint_value: dict[str, Any], completed: Iterable[str]) -> None:
    _atomic_json(out / "gt_progress.json", {
        "schema": "robomituba.blender_gt_progress.v1",
        "fingerprint": fingerprint_value,
        "completed_frame_ids": sorted(set(completed)),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
