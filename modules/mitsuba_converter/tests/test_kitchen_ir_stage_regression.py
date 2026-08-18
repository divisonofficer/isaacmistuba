from __future__ import annotations

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from mitsuba_converter.render_daemon import _stage_xml_obj_filenames_to_scene_mesh_cache


REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE = REPO_ROOT / "out/ir_dataset/kitchen_structural_specular_lod/ir_geometry"
DERIVED = REPO_ROOT / "out/opticalnav/opticalnav-v0.2/scenes/infinigen_single_room_kitchen_20260730__ir_semantic_lod_v1"
KITCHEN_ID = "KitchenSpaceFactory_6391524_.spawn_asset_3450668"


def _obj_bounds(paths: list[Path]) -> tuple[list[float], list[float]]:
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("v "):
                continue
            value = [float(item) for item in line.split()[1:4]]
            lo = [min(lo[i], value[i]) for i in range(3)]
            hi = [max(hi[i], value[i]) for i in range(3)]
    return lo, hi


@pytest.mark.skipif(
    os.environ.get("ROBOMITUBA_RUN_KITCHEN_IR_REGRESSION") != "1",
    reason="set ROBOMITUBA_RUN_KITCHEN_IR_REGRESSION=1 for the installed kitchen Stage-1/2 smoke",
)
def test_installed_kitchen_stage1_parts_restage_without_collapsing(tmp_path: Path) -> None:
    manifest_path = PROFILE / "stage1/scene_manifest.json"
    audit_path = DERIVED / "render_scene_materialization.json"
    if not manifest_path.is_file() or not audit_path.is_file():
        pytest.skip("installed kitchen IR Stage-1/2 is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unit = next(row for row in manifest["units"] if row["id"] == KITCHEN_ID)
    assert unit["glb_validation"]["primitive_count"] == 27

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    records = [
        row for row in audit["objects"]
        if row.get("object_id") == KITCHEN_ID and row.get("source_type") == "glb_part"
    ]
    assert len(records) == 27
    # The old Stage-2 audit retains the adapter output in cache_obj.  Those
    # files are the correct assembly-local Stage-1 GLB parts, before the buggy
    # second, per-part recentering pass.
    scene_dir = tmp_path / "kitchen_regression"
    scene_dir.mkdir()
    root = ET.Element("scene", {"version": "3.0.0"})
    for row in records:
        shape = ET.SubElement(root, "shape", {"type": "obj", "id": str(row["shape_id"])})
        source = REPO_ROOT / str(row["cache_obj"])
        assert source.is_file()
        ET.SubElement(shape, "string", {"name": "filename", "value": str(source)})
    xml = scene_dir / "render_scene.xml"
    ET.ElementTree(root).write(xml, encoding="utf-8", xml_declaration=True)
    stats = _stage_xml_obj_filenames_to_scene_mesh_cache(
        xml, scene_mesh_cache_dir=scene_dir / "mesh_cache", repo_root=REPO_ROOT,
        materialization_records=records,
    )
    filenames = {
        shape.get("id"): Path(shape.find("./string[@name='filename']").get("value"))
        for shape in ET.parse(xml).findall(".//shape[@type='obj']")
        if shape.find("./string[@name='filename']") is not None
    }
    lo, hi = _obj_bounds([filenames[str(row["shape_id"])] for row in records])
    spans = [hi[i] - lo[i] for i in range(3)]
    expected = list(unit["place_size_m"])
    assert spans[0] == pytest.approx(expected[0], abs=1e-5)
    assert spans[1] == pytest.approx(expected[1], abs=1e-5)
    assert spans[2] == pytest.approx(expected[2], abs=1e-5)
    assert stats["preserved_positions"] == 27
    assert stats["offset_nonzero"] == 0
