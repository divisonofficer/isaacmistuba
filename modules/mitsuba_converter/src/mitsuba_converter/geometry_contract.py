"""Geometry/UV integrity checks for materialized OpticalNav scene assets."""
from __future__ import annotations

import json
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


def _glb_primitives(path: Path) -> list[int]:
    """Return GLB primitive material indices without loading binary geometry."""
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"glTF":
            raise ValueError("not a GLB file")
        chunk_len, chunk_type = struct.unpack("<II", handle.read(8))
        if chunk_type != 0x4E4F534A:
            raise ValueError("GLB has no JSON chunk")
        payload = json.loads(handle.read(chunk_len).decode("utf-8"))
    return [int(primitive.get("material", -1)) for mesh in payload.get("meshes", []) for primitive in mesh.get("primitives", [])]


def _obj_uv_contract(path: Path) -> dict[str, Any]:
    vertices = texcoords = faces = faces_without_uv = invalid_uv = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("v "):
                vertices += 1
            elif line.startswith("vt "):
                texcoords += 1
                try:
                    u, v = (float(x) for x in line.split()[1:3])
                    invalid_uv += int(not (math.isfinite(u) and math.isfinite(v)))
                except (TypeError, ValueError):
                    invalid_uv += 1
            elif line.startswith("f "):
                faces += 1
                tokens = line.split()[1:]
                if not tokens or any("/" not in token or not token.split("/")[1] for token in tokens):
                    faces_without_uv += 1
    return {
        "path": str(path), "vertices": vertices, "texcoords": texcoords,
        "faces": faces, "faces_without_uv": faces_without_uv, "invalid_uv": invalid_uv,
        "ok": bool(faces == 0 or (texcoords > 0 and faces_without_uv == 0 and invalid_uv == 0)),
    }


def audit_scene_geometry_contract(scene_dir: Path, authoring_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Audit GLB material-slot parity and final OBJ UV availability per object."""
    objects = {str(item.get("id") or ""): item for item in (authoring_payload.get("objects") or []) if isinstance(item, Mapping)}
    repo_root = scene_dir.parents[4]
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.parse(scene_dir / "render_scene.xml", parser=parser).getroot()
    current_object: str | None = None
    obj_files: dict[str, list[Path]] = {}
    for child in list(root):
        if child.tag is ET.Comment and (child.text or "").startswith("opticalnav-obj:"):
            try:
                current_object = str(json.loads((child.text or "")[len("opticalnav-obj:"):]).get("id") or "")
            except ValueError:
                current_object = None
        elif child.tag == "shape" and current_object:
            filename = child.find("./string[@name='filename']")
            if filename is not None and filename.get("value"):
                obj_files.setdefault(current_object, []).append(Path(str(filename.get("value"))))
    records: list[dict[str, Any]] = []
    for object_id, obj in sorted(objects.items()):
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), Mapping) else {}
        full_ref = str(metadata.get("source_ref_full") or obj.get("source_ref") or "")
        selected_ref = str(obj.get("source_ref") or "")
        record: dict[str, Any] = {"object_id": object_id, "source_ref": selected_ref, "source_ref_full": full_ref}
        full_path = Path(full_ref)
        selected_path = Path(selected_ref)
        if not full_path.is_absolute():
            full_path = repo_root / full_path
        if not selected_path.is_absolute():
            selected_path = repo_root / selected_path
        if full_path.suffix.lower() == ".glb" and selected_path.suffix.lower() == ".glb" and full_path.is_file() and selected_path.is_file():
            try:
                record["glb_material_slots"] = {"full": _glb_primitives(full_path), "selected": _glb_primitives(selected_path)}
                record["material_slot_parity"] = sorted(record["glb_material_slots"]["full"]) == sorted(record["glb_material_slots"]["selected"])
            except Exception as exc:  # audit must report malformed assets, not abort sync
                record["glb_error"] = str(exc)
                record["material_slot_parity"] = False
        parts = [_obj_uv_contract(path) for path in obj_files.get(object_id, []) if path.is_file()]
        if parts:
            record["obj_parts"] = parts
            record["uv_ok"] = all(bool(part["ok"]) for part in parts)
        texture_refs = []
        for channel in (metadata.get("pbr", {}).get("channels", {}) if isinstance(metadata.get("pbr"), Mapping) else {}).values():
            if isinstance(channel, Mapping) and channel.get("ref"):
                texture_refs.append(str(channel["ref"]))
        record["texture_refs"] = texture_refs
        record["status"] = "ok" if record.get("uv_ok", True) and record.get("material_slot_parity", True) else "needs_override"
        records.append(record)
    return {"schema": "robomituba.geometry-contract.v1", "scene_dir": str(scene_dir), "objects": records}
