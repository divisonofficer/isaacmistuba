from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mitsuba_converter.opaque_scene import assemble_opaque_scene


def _record(tmp_path: Path, object_id: str) -> dict:
    outputs = {}
    for name, suffix in (
        ("base_color", "base.png"), ("alpha", "alpha.png"),
        ("bsdf_weight", "weight.png"), ("normal", "normal.png"),
        ("eta_exr", "eta.exr"), ("k_exr", "k.exr"),
    ):
        path = tmp_path / suffix
        path.touch()
        outputs[name] = str(path)
    return {"object_id": object_id, "outputs": outputs, "record_path": "record.json"}


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "render_scene.xml"
    source.write_text(
        """<scene version="3.0.0">
  <bsdf type="dielectric" id="old_glass"/>
  <shape type="obj" id="jar"><string name="filename" value="jar.obj"/><ref id="old_glass"/></shape>
  <shape type="obj" id="jar__part_001"><string name="filename" value="jar2.obj"/><ref id="old_glass"/></shape>
  <shape type="obj" id="chair"><string name="filename" value="chair.obj"/><ref id="old_chair"/></shape>
</scene>""",
        encoding="utf-8",
    )
    index = tmp_path / "xml_scene_index.json"
    index.write_text(json.dumps({"shapes": [
        {"shape_id": "jar", "object_id": "unit.jar"},
        {"shape_id": "jar__part_001", "object_id": "unit.jar"},
        {"shape_id": "chair", "object_id": "unit.chair"},
    ]}), encoding="utf-8")
    applied = tmp_path / "applied.json"
    applied.write_text(json.dumps({"substitutions": [
        {"unit_id": "unit.jar", "applied": True},
        {"unit_id": "unit.empty", "applied": False},
    ]}), encoding="utf-8")
    return source, index, applied


def test_assembly_replaces_every_part_but_preserves_other_shapes(tmp_path: Path) -> None:
    source, index, applied = _inputs(tmp_path)
    output = tmp_path / "opaque.xml"
    report = assemble_opaque_scene(
        source_xml=source, xml_scene_index=index, applied_substitutions=applied,
        spatial_records={"unit.jar": _record(tmp_path, "unit.jar")}, output_xml=output,
    )
    root = ET.parse(output).getroot()
    jar_refs = [root.find(f"./shape[@id='{name}']/ref").get("id") for name in ("jar", "jar__part_001")]
    assert jar_refs[0] == jar_refs[1]
    assert jar_refs[0].startswith("opaque_spatial_")
    assert root.find("./shape[@id='chair']/ref").get("id") == "old_chair"
    assert root.find("./bsdf[@id='old_glass']") is None
    generated = root.find(f"./bsdf[@id='{jar_refs[0]}']")
    assert generated is not None and generated.get("type") == "twosided"
    blend = generated.find(".//bsdf[@type='blendbsdf']")
    assert blend is not None
    assert blend.find("./texture[@name='weight']") is not None
    assert blend.find("./bsdf[@type='pplastic']") is not None
    assert blend.find("./bsdf[@type='roughconductor']") is not None
    assert report["assembled_unit_count"] == 1
    assert report["active_substitution_unit_count"] == 1
    assert report["replaced_shape_count"] == 2
    assert report["pruned_superseded_bsdf_count"] == 1


def test_assembly_rejects_missing_active_record(tmp_path: Path) -> None:
    source, index, applied = _inputs(tmp_path)
    with pytest.raises(ValueError, match="missing_records"):
        assemble_opaque_scene(
            source_xml=source, xml_scene_index=index, applied_substitutions=applied,
            spatial_records={}, output_xml=tmp_path / "opaque.xml",
        )
