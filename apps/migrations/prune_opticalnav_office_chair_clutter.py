#!/usr/bin/env python3
"""Remove excess generic Infinigen office chairs from selected OpticalNav scenes.

``OfficeChairFactory`` is unconstrained decorative population in the affected
legacy office imports.  The quota chairs created by the office repair pass use
``ChairFactory_910...`` and are deliberately preserved.
"""
from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SCENES = ("infinigen_office_20260822", "infinigen_office_20260824")


def _read(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(path)
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _is_excess_chair(obj: dict[str, Any]) -> bool:
    metadata = obj.get("metadata") or {}
    return str(metadata.get("factory") or "") == "OfficeChairFactory"


def _prune_render_sidecars(scene: Path, removed: set[str]) -> None:
    xml_path = scene / "render_scene.xml"
    if xml_path.is_file():
        backup = scene / "render_scene.before_office_chair_prune.xml"
        if not backup.exists():
            shutil.copy2(xml_path, backup)
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for shape in list(root.findall("shape")):
            if str(shape.get("id") or "") in removed:
                root.remove(shape)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    index_path = scene / "xml_scene_index.json"
    if index_path.is_file():
        index = _read(index_path)
        index["shapes"] = [shape for shape in index.get("shapes") or []
                           if str(shape.get("shape_id") or shape.get("object_id") or "") not in removed]
        _write(index_path, index)


def prune(project: str, scene_id: str, *, apply: bool) -> dict[str, Any]:
    scene = REPO / "out" / "opticalnav" / project / "scenes" / scene_id
    authoring_path = scene / "authoring_map.json"
    authoring = _read(authoring_path)
    removed = [str(item.get("id")) for item in authoring.get("objects") or [] if isinstance(item, dict) and _is_excess_chair(item)]
    prior_report = scene / "office_chair_prune.json"
    previously_removed = []
    if prior_report.is_file():
        previously_removed = [str(item) for item in (_read(prior_report).get("removed_object_ids") or [])]
    report = {"schema": "robomituba.office_chair_prune.v1", "scene_id": scene_id, "removed_object_ids": removed or previously_removed,
              "preserved_policy": "ChairFactory quota chairs retained; OfficeChairFactory decorative blockers removed"}
    if not apply:
        return {"scene_id": scene_id, "status": "planned", "removed": len(removed), "previously_removed": len(previously_removed)}
    backup = scene / "authoring_map.before_office_chair_prune.json"
    if not backup.exists():
        shutil.copy2(authoring_path, backup)
    authoring["objects"] = [item for item in authoring.get("objects") or [] if not (isinstance(item, dict) and _is_excess_chair(item))]
    authoring.setdefault("metadata", {})["office_chair_prune"] = report
    _write(authoring_path, authoring)
    _prune_render_sidecars(scene, set(removed or previously_removed))
    _write(scene / "office_chair_prune.json", report)
    return {"scene_id": scene_id, "status": "applied", "removed": len(removed)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    scenes = tuple(args.scene) or DEFAULT_SCENES
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "scenes": [prune(args.project, s, apply=args.apply) for s in scenes]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
