#!/usr/bin/env python3
"""Create a scene-wide, role-aware structural TextureCan A/B override."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "modules" / "robomituba_bridge" / "src")]
from robomituba_bridge.camera_pose import matrix_to_legacy_flat, resolve_viewpoint_pose  # noqa: E402

PALETTE = {"wall": "texturecan_concrete_0004", "ceiling": "texturecan_concrete_0012", "floor": "texturecan_wood_0037"}
TILE_ROOMS = ("bathroom", "kitchen", "balcony")


def _pose(x: float, z: float, yaw: float) -> list[float]:
    return matrix_to_legacy_flat(resolve_viewpoint_pose((x, z, 0), yaw, eye_height_m=1.45).camera_to_world_mitsuba)


def _bsdf(material_id: str, maps: dict[str, str]) -> ET.Element:
    root = ET.Element("bsdf", {"type": "twosided", "id": f"structural_ab_{material_id}"})
    normal = ET.SubElement(root, "bsdf", {"type": "normalmap"})
    tex = ET.SubElement(normal, "texture", {"name": "normalmap", "type": "bitmap"})
    ET.SubElement(tex, "string", {"name": "filename", "value": maps["normal_gl"]}); ET.SubElement(tex, "boolean", {"name": "raw", "value": "true"})
    plastic = ET.SubElement(normal, "bsdf", {"type": "pplastic"}); ET.SubElement(plastic, "float", {"name": "int_ior", "value": "1.5000"})
    tex = ET.SubElement(plastic, "texture", {"name": "diffuse_reflectance", "type": "bitmap"}); ET.SubElement(tex, "string", {"name": "filename", "value": maps["base_color"]})
    tex = ET.SubElement(plastic, "texture", {"name": "alpha", "type": "bitmap"}); ET.SubElement(tex, "string", {"name": "filename", "value": maps["roughness"]}); ET.SubElement(tex, "boolean", {"name": "raw", "value": "true"})
    return root


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scene-dir", type=Path, required=True); p.add_argument("--source-xml", type=Path)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--registry", type=Path, required=True); p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args(); scene, out = a.scene_dir.resolve(), a.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    registry = {row["id"]: row for row in json.loads(a.registry.read_text())["materials"]}
    bindings = json.loads((scene / "structural_rematerialization.json").read_text())["bindings"]
    selected: dict[str, str] = {}
    for b in bindings:
        role, unit = b["role"], b["unit_id"]
        material = "texturecan_tiles_0042" if role == "floor" and unit.startswith(TILE_ROOMS) else PALETTE[role]
        selected[unit] = material
    source_xml = (a.source_xml or scene / "render_scene.xml").resolve()
    xml_root = ET.parse(source_xml).getroot()
    audit = json.loads((scene / "apartment_quality_ab_manifest.json").read_text())["orphan_audit"]
    remove_ids = {row["object_id"] for row in audit.get("unsupported_before_policy") or []}
    for shape in list(xml_root.findall(".//shape")):
        shape_id = shape.get("id") or ""
        if any(shape_id == object_id or shape_id.startswith(object_id + "__") for object_id in remove_ids):
            xml_root.remove(shape)
    changed = [shape.get("id") for shape in xml_root.findall(".//shape") if shape.get("id") in selected]
    if set(selected) - set(changed): raise SystemExit(f"structural units missing in XML: {sorted(set(selected)-set(changed))}")
    ET.indent(xml_root, space="  ")
    baseline_xml, candidate_xml = out / "render_scene_orphan_clean_baseline.xml", out / "render_scene_structural_texturecan.xml"
    ET.ElementTree(xml_root).write(baseline_xml, encoding="utf-8", xml_declaration=True)
    # Reparse the clean baseline so the candidate differs only in structural BSDF refs.
    xml_root = ET.parse(baseline_xml).getroot()
    for material in sorted(set(selected.values())):
        maps = {key: str((a.registry.parent / value).resolve()) for key, value in registry[material]["maps"].items()}
        xml_root.insert(0, _bsdf(material, maps))
    for shape in xml_root.findall(".//shape"):
        material = selected.get(shape.get("id", ""))
        if material:
            for ref in list(shape.findall("ref")): shape.remove(ref)
            ET.SubElement(shape, "ref", {"id": f"structural_ab_{material}"})
    ET.indent(xml_root, space="  "); ET.ElementTree(xml_root).write(candidate_xml, encoding="utf-8", xml_declaration=True)
    template = json.loads(a.request.read_text())
    views = [("bathroom", 10.35, 2.10, 180), ("bedroom", 5.8, 6.8, 45), ("living", 7.5, 11.2, 225), ("kitchen", 12.5, 8.8, 180), ("upper_room", 13.7, 15.3, 45)]
    records=[]
    for variant, xml in (("baseline", baseline_xml), ("structural_texturecan", candidate_xml)):
      for n,(view,x,z,yaw) in enumerate(views,1):
        req=copy.deepcopy(template); suffix=f"structural-ab-{variant}-{n:02d}-{view}"; frame=f"{scene.name}_{suffix.replace('-', '_')}"; job=f"opticalnav-{scene.name}-{suffix}"
        req.update({"request_id":suffix,"job_id":job,"frame_id":frame}); req["scene_state"].update({"job_id":job,"frame_id":frame,"scene_snapshot_ref":str(xml.relative_to(ROOT)),"mitsuba_scene_ref":str(xml.relative_to(ROOT))})
        m=_pose(x,z,yaw); req["robot_state"]["base_pose"]=m; req["camera_specs"][0]["camera_to_world"]=m; req["camera_specs"][0]["extras"]["render"].update({"path_spp":512,"polar_spp":256}); req["render_settings"].update({"path_spp":512,"polar_spp":256})
        req["extras"]["structural_material_ab"]={"variant":variant,"view_id":view,"position_xz_m":[x,z],"yaw_deg":yaw,"palette":PALETTE,"tile_floor_rooms":TILE_ROOMS}
        path=out/f"{suffix}.json"; path.write_text(json.dumps(req,indent=2)+"\n"); records.append({"variant":variant,"view_id":view,"job_id":job,"request":str(path)})
    (out/"structural_material_ab_index.json").write_text(json.dumps({"selected_material_by_unit":selected,"views":records},indent=2)+"\n")
    print(json.dumps({"xml":str(candidate_xml),"structural_shapes":len(changed),"requests":len(records)},indent=2))

if __name__ == "__main__": main()
