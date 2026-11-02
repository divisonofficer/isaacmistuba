#!/usr/bin/env python3
"""Build a fixed-pose structural-wall material A/B render set.

The baseline and candidate share the exact same compiled scene, lights and
camera poses.  Only the selected wall's BSDF is replaced in the candidate.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "modules" / "robomituba_bridge" / "src")]
from robomituba_bridge.camera_pose import matrix_to_legacy_flat, resolve_viewpoint_pose  # noqa: E402


def pose(x: float, z: float, yaw_deg: float, height: float) -> list[float]:
    return matrix_to_legacy_flat(resolve_viewpoint_pose((x, z, 0.0), yaw_deg, eye_height_m=height).camera_to_world_mitsuba)


def wall_bsdf(bsdf_id: str, maps: dict[str, str]) -> ET.Element:
    outer = ET.Element("bsdf", {"type": "twosided", "id": bsdf_id})
    normal = ET.SubElement(outer, "bsdf", {"type": "normalmap"})
    normal_tex = ET.SubElement(normal, "texture", {"name": "normalmap", "type": "bitmap"})
    ET.SubElement(normal_tex, "string", {"name": "filename", "value": maps["normal_gl"]})
    ET.SubElement(normal_tex, "boolean", {"name": "raw", "value": "true"})
    plastic = ET.SubElement(normal, "bsdf", {"type": "pplastic"})
    ET.SubElement(plastic, "float", {"name": "int_ior", "value": "1.5000"})
    color = ET.SubElement(plastic, "texture", {"name": "diffuse_reflectance", "type": "bitmap"})
    ET.SubElement(color, "string", {"name": "filename", "value": maps["base_color"]})
    # The exported scene uses pplastic alpha for roughness, so follow that
    # established convention and keep the map in linear space.
    rough = ET.SubElement(plastic, "texture", {"name": "alpha", "type": "bitmap"})
    ET.SubElement(rough, "string", {"name": "filename", "value": maps["roughness"]})
    ET.SubElement(rough, "boolean", {"name": "raw", "value": "true"})
    return outer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--target", default="bedroom_0_0.wall")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    scene_dir, out_dir = args.scene_dir.resolve(), args.out_dir.resolve()
    plan = json.loads(args.plan.read_text())
    maps = plan["target"]["candidate_maps"]
    source_xml = scene_dir / "render_scene.xml"
    candidate_xml = out_dir / "render_scene_texturecan_wall.xml"
    out_dir.mkdir(parents=True, exist_ok=True)

    root = ET.parse(source_xml).getroot()
    bsdf_id = "wall_material_ab_texturecan_concrete_0004"
    root.insert(0, wall_bsdf(bsdf_id, maps))
    target = root.find(f".//shape[@id='{args.target}']")
    if target is None:
        raise SystemExit(f"target shape not found: {args.target}")
    for ref in list(target.findall("ref")):
        target.remove(ref)
    ET.SubElement(target, "ref", {"id": bsdf_id})
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(candidate_xml, encoding="utf-8", xml_declaration=True)

    template = json.loads(args.request.read_text())
    # Five position/heading pairs surround the bedroom and include two grazing
    # angles. The same list is emitted for both variants to keep the A/B fair.
    views = [
        ("south_front", 5.10, 4.25, 0.0),
        ("south_grazing", 3.25, 4.25, 35.0),
        ("west_front", 1.00, 9.06, 90.0),
        ("north_front", 5.10, 13.88, 180.0),
        ("east_grazing", 9.20, 10.80, 225.0),
    ]
    records = []
    for variant, xml in (("baseline", source_xml), ("texturecan", candidate_xml)):
        for ordinal, (view_id, x, z, yaw) in enumerate(views, 1):
            request = copy.deepcopy(template)
            suffix = f"wall-ab-{variant}-{ordinal:02d}-{view_id}"
            frame = f"{scene_dir.name}_{suffix.replace('-', '_')}"
            request["request_id"] = suffix
            request["job_id"] = f"opticalnav-{scene_dir.name}-{suffix}"
            request["frame_id"] = frame
            request["scene_state"]["job_id"] = request["job_id"]
            request["scene_state"]["frame_id"] = frame
            # Daemon payload validation deliberately accepts only repo-relative
            # references; XML itself can retain absolute external asset paths.
            xml_ref = str(xml.relative_to(ROOT))
            request["scene_state"]["scene_snapshot_ref"] = xml_ref
            request["scene_state"]["mitsuba_scene_ref"] = xml_ref
            matrix = pose(x, z, yaw, 1.45)
            request["robot_state"]["base_pose"] = matrix
            request["camera_specs"][0]["camera_to_world"] = matrix
            request["camera_specs"][0]["extras"]["render"].update({"path_spp": 512, "polar_spp": 256})
            request["render_settings"].update({"path_spp": 512, "polar_spp": 256})
            request["extras"].update({"render_mode": "wall_material_ab", "wall_material_ab": {
                "variant": variant, "view_id": view_id, "ordinal": ordinal, "position_xz_m": [x, z],
                "yaw_deg": yaw, "target": args.target, "candidate_material": plan["target"]["candidate_material"],
            }})
            output = out_dir / f"{suffix}.json"
            output.write_text(json.dumps(request, indent=2) + "\n")
            records.append({"variant": variant, "view_id": view_id, "request": str(output), "job_id": request["job_id"]})
    (out_dir / "wall_material_ab_index.json").write_text(json.dumps({"target": args.target, "views": records}, indent=2) + "\n")
    print(json.dumps({"candidate_xml": str(candidate_xml), "requests": len(records), "index": str(out_dir / "wall_material_ab_index.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
