from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mitsuba_converter.glb_texture_adapter import materialize_glb_texture_parts
from mitsuba_converter.render_daemon import _append_bsdf_xml, _select_part_render_material


def _sample_dtc_glb() -> Path:
    path = Path.cwd() / "vendor_datasets" / "dtc_objects" / "Marker_B07Z5P84J2_Peach" / "3d-asset.glb"
    if not path.exists():
        pytest.skip("DTC sample GLB not present")
    return path


def test_dtc_glb_adapter_extracts_pbr_textures(tmp_path: Path) -> None:
    glb = _sample_dtc_glb()
    result = materialize_glb_texture_parts(
        "vendor_datasets/dtc_objects/Marker_B07Z5P84J2_Peach/3d-asset.glb",
        glb_path=glb,
        repo_root=Path.cwd(),
        mesh_cache_dir=tmp_path / "mesh_cache",
        texture_cache_dir=tmp_path / "texture_cache",
    )

    assert result.status == "ok"
    assert result.mesh_parts
    assert result.texture_slots.get("base_color", 0) >= 1
    assert result.texture_slots.get("normal", 0) >= 1
    assert result.texture_slots.get("metallic_roughness", 0) >= 1
    part = result.mesh_parts[0]
    assert part.triangle_count > 0
    assert part.has_uv
    assert part.extracted_material is not None
    em = part.extracted_material
    assert em["source"] == "glb_pbr"
    for key in ("base_color_texture_ref", "normal_texture_ref", "metallic_roughness_texture_ref"):
        value = em.get(key)
        assert value
        assert (Path.cwd() / value).exists() or Path(value).exists()


def test_dtc_glb_extracted_material_reaches_measured_albedo_scale(tmp_path: Path) -> None:
    glb = _sample_dtc_glb()
    result = materialize_glb_texture_parts(
        "vendor_datasets/dtc_objects/Marker_B07Z5P84J2_Peach/3d-asset.glb",
        glb_path=glb,
        repo_root=Path.cwd(),
        mesh_cache_dir=tmp_path / "mesh_cache",
        texture_cache_dir=tmp_path / "texture_cache",
    )
    part = result.mesh_parts[0].to_dict()
    em = part["extracted_material"]
    material_id, material_class = _select_part_render_material(
        None,
        {**part, "object_material": "plastic", "source_ref": "vendor_datasets/dtc_objects/Marker_B07Z5P84J2_Peach/3d-asset.glb"},
        em,
        {},
        repo_root=Path.cwd(),
    )
    assert material_class in {"plastic", "default"}
    assert material_id and (material_id.startswith("hpbrdf_2025:") or material_id.startswith("pbrdf_2020:"))

    shape = ET.Element("shape")
    _append_bsdf_xml(shape, material_id, {}, repo_root=Path.cwd(), extracted_material=em)
    tex = shape.find(".//texture[@name='albedo_scale'][@type='bitmap']")
    assert tex is not None
    filename = tex.find("./string[@name='filename']")
    assert filename is not None
    assert filename.get("value")
