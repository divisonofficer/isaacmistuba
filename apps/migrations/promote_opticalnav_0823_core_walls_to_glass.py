#!/usr/bin/env python3
"""Make 0823's central rooms and two central corridors full glass walls.

This is intentionally narrower than the structural-glass partition repair:
it promotes only the six explicitly central shell objects.  Building-edge
walls, open-office perimeter walls, doors and frames remain unchanged.
"""
from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENE = REPO / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_office_20260823"
TARGETS = {
    "hallway_0_0.wall", "hallway_0_2.wall",
    "meeting-room_0_0.wall", "meeting-room_0_1.wall", "meeting-room_0_2.wall",
    "office_0_0.wall",
}
MANIFEST = SCENE / "core_glass_wall_override.json"


def _write(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _glass_bsdf(root: ET.Element) -> str:
    for shape in root.findall("./shape"):
        if ".glass." not in str(shape.get("id") or ""):
            continue
        ref = next((child for child in list(shape) if child.tag == "ref"), None)
        if ref is not None and ref.get("id"):
            return str(ref.get("id"))
    raise RuntimeError("no existing structural-glass BSDF found")


def _set_ref(shape: ET.Element, bsdf_id: str) -> None:
    refs = [child for child in list(shape) if child.tag == "ref" and child.get("name") in {None, "bsdf"}]
    if not refs:
        raise RuntimeError(f"{shape.get('id')}: missing BSDF reference")
    for ref in refs:
        shape.remove(ref)
    shape.insert(0, ET.Element("ref", {"id": bsdf_id}))


def apply(*, rollback: bool = False) -> dict:
    authoring_path = SCENE / "authoring_map.json"
    if rollback:
        backup = SCENE / "authoring_map.before_core_glass_wall_override.json"
        if not backup.exists():
            return {"status": "nothing_to_rollback"}
        shutil.copy2(backup, authoring_path)
        for xml_name in ("render_scene.xml", "render_scene_perturbed.xml"):
            backup = SCENE / f"{xml_name}.before_core_glass_wall_override"
            if backup.exists():
                shutil.copy2(backup, SCENE / xml_name)
        _write(MANIFEST, {"status": "rolled_back", "targets": sorted(TARGETS)})
        return {"status": "rolled_back", "targets": len(TARGETS)}
    if MANIFEST.exists() and json.loads(MANIFEST.read_text()).get("status") == "applied":
        return {"status": "already_applied", "targets": len(TARGETS)}
    authoring = json.loads(authoring_path.read_text())
    objects = {str(obj.get("id")): obj for obj in authoring.get("objects") or [] if isinstance(obj, dict)}
    missing = sorted(TARGETS - set(objects))
    if missing:
        raise RuntimeError(f"missing authoring walls: {missing}")
    backup = SCENE / "authoring_map.before_core_glass_wall_override.json"
    if not backup.exists():
        shutil.copy2(authoring_path, backup)
    for object_id in TARGETS:
        obj = objects[object_id]
        obj["material"] = "RM_ModernOffice_Glass"
        metadata = dict(obj.get("metadata") or {})
        metadata["core_glass_wall_override"] = {"scope": "0823_central_only", "render_only": False}
        obj["metadata"] = metadata
    _write(authoring_path, authoring)
    patched = []
    for xml_name in ("render_scene.xml", "render_scene_perturbed.xml"):
        xml_path = SCENE / xml_name
        if not xml_path.exists():
            continue
        backup = SCENE / f"{xml_name}.before_core_glass_wall_override"
        if not backup.exists():
            shutil.copy2(xml_path, backup)
        tree = ET.parse(xml_path)
        root = tree.getroot()
        glass_id = _glass_bsdf(root)
        shapes = {str(shape.get("id")): shape for shape in root.findall("./shape")}
        for object_id in TARGETS:
            _set_ref(shapes[object_id], glass_id)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
        patched.append(xml_name)
    _write(MANIFEST, {"schema": "robomituba.core_glass_wall_override.v1", "status": "applied",
                      "applied_at": datetime.now(timezone.utc).isoformat(), "targets": sorted(TARGETS),
                      "xml_files": patched, "excluded": "building-edge and open-office perimeter walls"})
    return {"status": "applied", "targets": len(TARGETS), "xml_files": patched}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply(rollback=args.rollback), ensure_ascii=False, indent=2))
