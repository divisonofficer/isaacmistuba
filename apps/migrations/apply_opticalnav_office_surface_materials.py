#!/usr/bin/env python3
"""Apply CC0 carpet, wall and restroom-tile materials to legacy office render XML.

This is a render-only material migration: authoring geometry, glass, doors and
windows are never changed.  Each affected shape receives its own BSDF so a
room-level carpet choice can vary without leaking into every office floor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO / "out" / "opticalnav"
CARPET_ROOT = Path("/bean/ir_pbr_assets/cc0_office_surfaces_v1")
STRUCTURAL_ROOT = Path("/bean/ir_pbr_assets/cc0_structural_v1")
SCENES = ("infinigen_office_20260822", "infinigen_office_20260823", "infinigen_office_20260824")
SCHEMA = "robomituba.office_surface_materials.v1"

WALLS = ("polyhaven_concrete_wall_001", "polyhaven_concrete_wall_005", "polyhaven_grey_plaster", "polyhaven_plastered_wall")
TILE = "polyhaven_floor_tiles_04"


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _digest(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def _registry(root: Path) -> dict[str, dict[str, Any]]:
    payload = _read(root / "registry.lock.json")
    records = {str(row["id"]): row for row in payload.get("materials") or [] if isinstance(row, dict)}
    for record in records.values():
        for rel in (record.get("maps") or {}).values():
            if not (root / str(rel)).is_file():
                raise FileNotFoundError(root / str(rel))
    return records


def _is_glass(shape_id: str, material_id: str) -> bool:
    text = f"{shape_id} {material_id}".lower()
    return any(token in text for token in ("glass", "window", "mirror", "frame"))


def _choice(shape_id: str, carpets: list[str], structural: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any], Path, str]:
    room = shape_id.rsplit(".", 1)[0]
    if shape_id.endswith(".floor"):
        if room.startswith("restroom"):
            material_id, root, family = TILE, STRUCTURAL_ROOT, "restroom_tile"
        else:
            material_id, root, family = carpets[_digest(room) % len(carpets)], CARPET_ROOT, "office_carpet"
    elif shape_id.endswith(".wall"):
        material_id, root, family = WALLS[_digest(room) % len(WALLS)], STRUCTURAL_ROOT, "concrete_or_plaster_wall"
    else:
        raise ValueError(shape_id)
    return material_id, structural[material_id] if root == STRUCTURAL_ROOT else _registry(root)[material_id], root, family


def _bitmap(name: str, filename: Path, *, raw: bool) -> ET.Element:
    texture = ET.Element("texture", {"name": name, "type": "bitmap"})
    ET.SubElement(texture, "string", {"name": "filename", "value": str(filename)})
    if raw:
        ET.SubElement(texture, "boolean", {"name": "raw", "value": "true"})
    return texture


def _bsdf(bsdf_id: str, record: dict[str, Any], root: Path) -> ET.Element:
    maps = record["maps"]
    outer = ET.Element("bsdf", {"type": "twosided", "id": bsdf_id})
    normal = ET.SubElement(outer, "bsdf", {"type": "normalmap"})
    normal.append(_bitmap("normalmap", root / maps["normal_gl"], raw=True))
    plastic = ET.SubElement(normal, "bsdf", {"type": "pplastic"})
    ET.SubElement(plastic, "float", {"name": "int_ior", "value": "1.5000"})
    plastic.append(_bitmap("diffuse_reflectance", root / maps["base_color"], raw=False))
    plastic.append(_bitmap("alpha", root / maps["roughness"], raw=True))
    return outer


def _replace_shape_bsdf(shape: ET.Element, bsdf_id: str) -> None:
    # Old offline-built XML emits an unnamed direct ``<ref id=.../>`` while
    # newer scenes use ``name=\"bsdf\"``.  A shape has only one direct BSDF
    # reference in either contract; do not touch nested transform refs.
    refs = [node for node in list(shape) if node.tag == "ref" and node.get("name") in {None, "bsdf"}]
    if not refs:
        raise ValueError(f"{shape.get('id')}: no direct bsdf ref")
    for node in refs:
        shape.remove(node)
    shape.insert(0, ET.Element("ref", {"id": bsdf_id}))


def _targets(scene_dir: Path) -> dict[str, str]:
    index = _read(scene_dir / "xml_scene_index.json")
    return {
        str(row.get("shape_id")): str(row.get("material_id") or "")
        for row in index.get("shapes") or []
        if isinstance(row, dict) and str(row.get("shape_id") or "").endswith((".floor", ".wall"))
    }


def _direct_bsdf_type(shape: ET.Element, declared_bsdfs: dict[str, ET.Element]) -> str | None:
    """Resolve the shape's direct material type without touching transforms."""
    direct = next((node for node in list(shape) if node.tag == "bsdf"), None)
    if direct is not None:
        return str(direct.get("type") or "") or None
    ref = next((node for node in list(shape) if node.tag == "ref" and node.get("name") in {None, "bsdf"}), None)
    if ref is None:
        return None
    declared = declared_bsdfs.get(str(ref.get("id") or ""))
    return str(declared.get("type") or "") if declared is not None else None


def _update_polar_material_policy(
    scene: Path,
    plan: list[dict[str, Any]],
    *,
    carpets: list[str],
    structural: dict[str, dict[str, Any]],
) -> bool:
    """Keep the analytic/Stokes policy aligned with this render-only migration.

    Polar staging intentionally rewrites source materials according to this
    policy.  Without this companion update, a PBR-assigned floor was rendered
    as the pre-migration ``RM_ModernOffice_Floor`` solid colour.  The policy
    must also retain the render-only central glass overrides as dielectric.
    """
    policy_path = scene / "render_scene_material_policy.json"
    xml_path = scene / "render_scene.xml"
    if not policy_path.is_file() or not xml_path.is_file():
        return False
    policy = _read(policy_path)
    policy_rows = {
        str(row.get("shape_id") or ""): row
        for row in policy.get("shape_policies") or []
        if isinstance(row, dict)
    }
    root = ET.parse(xml_path).getroot()
    shapes = {str(node.get("id") or ""): node for node in root.findall("./shape")}
    declared = {str(node.get("id") or ""): node for node in root.findall("./bsdf") if node.get("id")}
    changed = False
    # Apply assigned PBR surfaces first.  A later source sync can restore a
    # shared material ref in XML, so this must be derived from the durable
    # assignment manifest rather than from the current XML material id.
    for item in plan:
        shape_id = str(item["shape_id"])
        row = policy_rows.get(shape_id)
        shape = shapes.get(shape_id)
        if row is None or shape is None:
            continue
        # Core corridor/room partitions are deliberately glass in the source
        # XML.  Preserve that semantic in the Stokes policy instead of
        # reintroducing the former opaque wall through the analytic fallback.
        if _direct_bsdf_type(shape, declared) == "dielectric":
            fallback = dict(row.get("analytic_fallback") or {})
            if fallback.get("bsdf_strategy") != "dielectric":
                fallback.update({
                    "kind": "render_only_glass_override",
                    "bsdf_strategy": "dielectric",
                    "material_id": "RM_ModernOffice_Glass",
                    "optical_class": "dielectric",
                    "capabilities": {"rgb": True, "polarization": True},
                })
                for key in ("base_color_texture_ref", "normal_texture_ref", "roughness_texture_ref"):
                    fallback.pop(key, None)
                row["analytic_fallback"] = fallback
                row["analytic_strategy"] = "dielectric"
                row["analytic_capabilities"] = {"rgb": True, "polarization": True}
                row["analytic_polar_rgb"] = True
                row["material_id"] = "RM_ModernOffice_Glass"
                changed = True
            continue
        material_id, record, library_root, _family = _choice(shape_id, carpets, structural)
        maps = dict(record["maps"])
        fallback = dict(row.get("analytic_fallback") or {})
        extracted = dict(row.get("extracted_material") or {})
        updates = {
            "kind": "cc0_office_surface_pbr",
            "bsdf_strategy": "pplastic",
            "material_id": material_id,
            "base_color_texture_ref": str(library_root / maps["base_color"]),
            "normal_texture_ref": str(library_root / maps["normal_gl"]),
            "roughness_texture_ref": str(library_root / maps["roughness"]),
            "roughness": max(0.2, min(1.0, 0.55 + float(item["roughness_offset"]))),
            "capabilities": {"rgb": True, "polarization": True},
        }
        if any(fallback.get(key) != value for key, value in updates.items()):
            fallback.update(updates)
            row["analytic_fallback"] = fallback
            row["analytic_strategy"] = "pplastic"
            row["analytic_capabilities"] = {"rgb": True, "polarization": True}
            row["analytic_polar_rgb"] = True
            row["material_id"] = material_id
            extracted.update({
                "source": "cc0_office_surface_pbr",
                "material_id": material_id,
                "base_color_texture_ref": updates["base_color_texture_ref"],
                "normal_texture_ref": updates["normal_texture_ref"],
                "roughness_texture_ref": updates["roughness_texture_ref"],
            })
            row["extracted_material"] = extracted
            changed = True
    # Glass overrides are deliberately absent from ``plan`` (they are not PBR
    # surface assignments), but a sync rebuild may also recreate their policy
    # row from the original opaque wall material.  Reconcile every currently
    # direct dielectric shape so polar staging can never resurrect an opaque
    # backing wall merely because the assignment manifest excludes glass.
    for shape_id, shape in shapes.items():
        if _direct_bsdf_type(shape, declared) != "dielectric":
            continue
        row = policy_rows.get(shape_id)
        if row is None:
            continue
        fallback = dict(row.get("analytic_fallback") or {})
        if fallback.get("bsdf_strategy") == "dielectric":
            continue
        fallback.update({
            "kind": "render_only_glass_override",
            "bsdf_strategy": "dielectric",
            "material_id": "RM_ModernOffice_Glass",
            "optical_class": "dielectric",
            "capabilities": {"rgb": True, "polarization": True},
        })
        for key in ("base_color_texture_ref", "normal_texture_ref", "roughness_texture_ref"):
            fallback.pop(key, None)
        row["analytic_fallback"] = fallback
        row["analytic_strategy"] = "dielectric"
        row["analytic_capabilities"] = {"rgb": True, "polarization": True}
        row["analytic_polar_rgb"] = True
        row["material_id"] = "RM_ModernOffice_Glass"
        changed = True
    if not changed:
        return False
    backup = scene / "render_scene_material_policy.before_office_surface_materials.json"
    if not backup.exists():
        shutil.copy2(policy_path, backup)
    policy["office_surface_materials_policy_revision"] = "pbr-plus-glass-v2"
    policy["office_surface_materials_policy_updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(policy_path, policy)
    return True


def apply(project: str, scene_id: str, *, mode: str) -> dict[str, Any]:
    scene = PROJECT_ROOT / project / "scenes" / scene_id
    structural = _registry(STRUCTURAL_ROOT)
    carpets = sorted(_registry(CARPET_ROOT))
    targets = _targets(scene)
    selected = {sid: material for sid, material in targets.items() if not _is_glass(sid, material)}
    plan = []
    for shape_id in sorted(selected):
        material_id, record, root, family = _choice(shape_id, carpets, structural)
        plan.append({"shape_id": shape_id, "material_id": material_id, "family": family,
                     "rotation_deg": (0, 90, 180, 270)[_digest(shape_id) % 4],
                     "roughness_offset": ((-3, -1, 1, 3)[_digest("rough" + shape_id) % 4]) / 100})
    report = {"schema": SCHEMA, "scene_id": scene_id, "applied_at": datetime.now(timezone.utc).isoformat(),
              "registry_refs": {"carpet": str(CARPET_ROOT / "registry.lock.json"), "structural": str(STRUCTURAL_ROOT / "registry.lock.json")},
              "assignments": plan, "excluded_glass_or_frame_shape_count": len(targets) - len(selected)}
    if mode == "dry-run":
        return {"scene_id": scene_id, "status": "planned", "assignments": len(plan), "excluded": report["excluded_glass_or_frame_shape_count"]}
    manifest_path = scene / "office_surface_materials.json"
    if mode == "rollback":
        backup = scene / "render_scene.before_office_surface_materials.xml"
        if not backup.is_file():
            raise FileNotFoundError(backup)
        shutil.copy2(backup, scene / "render_scene.xml")
        _write(manifest_path, {**report, "status": "rolled_back"})
        return {"scene_id": scene_id, "status": "rolled_back"}
    if manifest_path.is_file():
        previous = _read(manifest_path)
        if previous.get("schema") == SCHEMA and previous.get("status") == "applied":
            if previous.get("assignments") == plan:
                changed = _update_polar_material_policy(scene, plan, carpets=carpets, structural=structural)
                return {
                    "scene_id": scene_id,
                    "status": "policy_updated" if changed else "already_applied",
                    "assignments": len(plan),
                }
            # A glass repair legitimately removes former wall assignments from
            # the target list.  Permit that narrow reconciliation only when
            # every surviving assignment is byte-for-byte unchanged; additions
            # or altered material choices still require an explicit rollback.
            previous_by_shape = {
                str(item.get("shape_id")): item
                for item in previous.get("assignments") or [] if isinstance(item, dict)
            }
            if any(previous_by_shape.get(str(item["shape_id"])) != item for item in plan):
                raise RuntimeError(f"{scene_id}: existing material migration differs; rollback before changing rules")
    for xml_path in [scene / "render_scene.xml", scene / "render_scene_perturbed.xml"]:
        if not xml_path.is_file():
            continue
        if xml_path.name == "render_scene.xml":
            backup = scene / "render_scene.before_office_surface_materials.xml"
            if not backup.exists():
                shutil.copy2(xml_path, backup)
        root = ET.parse(xml_path).getroot()
        shape_by_id = {str(node.get("id")): node for node in root.findall("./shape")}
        for item in plan:
            shape = shape_by_id.get(item["shape_id"])
            if shape is None:
                continue
            material_id, record, library_root, _family = _choice(item["shape_id"], carpets, structural)
            bsdf_id = "office_surface_" + hashlib.sha256(f"{item['shape_id']}:{material_id}".encode()).hexdigest()[:16]
            # Reconciliation may run after sync recreated the scene.  Avoid
            # duplicate declarations with the same ID when reapplying it.
            for node in list(root.findall("./bsdf")):
                if node.get("id") == bsdf_id:
                    root.remove(node)
            root.insert(0, _bsdf(bsdf_id, record, library_root))
            _replace_shape_bsdf(shape, bsdf_id)
        ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
    _write(manifest_path, {**report, "status": "applied"})
    changed = _update_polar_material_policy(scene, plan, carpets=carpets, structural=structural)
    return {"scene_id": scene_id, "status": "applied", "assignments": len(plan), "policy_updated": changed}


def verify(project: str, scene_id: str) -> dict[str, Any]:
    scene = PROJECT_ROOT / project / "scenes" / scene_id
    manifest = _read(scene / "office_surface_materials.json")
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "applied":
        raise ValueError(f"{scene_id}: material migration is not applied")
    assignments = manifest.get("assignments") or []
    xml_paths = [scene / "render_scene.xml", scene / "render_scene_perturbed.xml"]
    verified_xml = 0
    for xml_path in xml_paths:
        if not xml_path.is_file():
            continue
        root = ET.parse(xml_path).getroot()
        bsdfs = {str(node.get("id")): node for node in root.findall("./bsdf") if node.get("id")}
        shapes = {str(node.get("id")): node for node in root.findall("./shape")}
        for item in assignments:
            shape = shapes.get(str(item["shape_id"]))
            if shape is None:
                continue
            ref = next((node for node in list(shape) if node.tag == "ref"), None)
            # A later render-only glass repair intentionally replaces selected
            # central wall PBR refs with the shared dielectric BSDF.  That is
            # compatible with this migration and is verified by the matching
            # Stokes material policy rather than treated as a failed PBR write.
            if _direct_bsdf_type(shape, bsdfs) == "dielectric":
                continue
            if ref is None or not str(ref.get("id") or "").startswith("office_surface_"):
                raise ValueError(f"{xml_path}: {item['shape_id']} does not reference an office surface BSDF")
            bsdf = bsdfs.get(str(ref.get("id")))
            if bsdf is None:
                raise ValueError(f"{xml_path}: missing {ref.get('id')}")
            for node in bsdf.findall(".//string[@name='filename']"):
                if not Path(str(node.get("value"))).is_file():
                    raise FileNotFoundError(node.get("value"))
        verified_xml += 1
    return {"scene_id": scene_id, "status": "verified", "assignments": len(assignments), "xml_files": verified_xml}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if sum((args.apply, args.rollback, args.verify)) > 1:
        parser.error("choose only one of --apply, --rollback or --verify")
    mode = "verify" if args.verify else "rollback" if args.rollback else "apply" if args.apply else "dry-run"
    scenes = tuple(args.scene) or SCENES
    operation = verify if mode == "verify" else lambda project, scene: apply(project, scene, mode=mode)
    print(json.dumps({"mode": mode, "scenes": [operation(args.project, scene) for scene in scenes]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
