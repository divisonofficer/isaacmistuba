from __future__ import annotations

import importlib.util
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from mitsuba_converter.glb_texture_adapter import _save_metallic_roughness_channels
from mitsuba_converter.render_daemon import (
    _append_extracted_bsdf_xml,
    _dedupe_shape_bsdfs_to_shared,
    _select_part_render_material,
    _write_normalized_obj_for_scene_cache,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_importer():
    path = REPO_ROOT / "apps" / "import_infinigen_scene.py"
    spec = importlib.util.spec_from_file_location("import_infinigen_scene_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _minimal_uv_glb_bytes(*, degenerate_uv: bool = False) -> bytes:
    positions = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    uv = (0.0, 0.0, 0.5, 0.0, 1.0, 0.0) if degenerate_uv else (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    binary = struct.pack("<9f", *positions) + struct.pack("<6f", *uv)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 24},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}}]}],
    }
    chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    chunk += b" " * ((-len(chunk)) % 4)
    total = 12 + 8 + len(chunk) + 8 + len(binary)
    return (
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<II", len(chunk), 0x4E4F534A)
        + chunk
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_packed_mr_channels_are_materialized(tmp_path: Path) -> None:
    packed = Image.new("RGB", (2, 1))
    packed.putdata([(255, 32, 224), (255, 160, 16)])
    rough, metallic = _save_metallic_roughness_channels(
        packed,
        glb_path=tmp_path / "asset.glb",
        mtime_ns=1,
        material_key="mat",
        texture_cache_dir=tmp_path,
        repo_root=None,
    )
    assert rough and metallic
    assert list(Image.open(rough).convert("RGB").getdata()) == [(32, 32, 32), (160, 160, 160)]
    assert list(Image.open(metallic).convert("RGB").getdata()) == [(224, 224, 224), (16, 16, 16)]


def test_spatial_pbr_emits_polarized_blend(tmp_path: Path) -> None:
    paths = {}
    for name, value in (("base", 128), ("rough", 64), ("metal", 192), ("normal", 127)):
        path = tmp_path / f"{name}.png"
        Image.new("RGB", (2, 2), (value, value, value)).save(path)
        paths[name] = str(path)
    shape = ET.Element("shape")
    ok = _append_extracted_bsdf_xml(
        shape,
        {
            "base_color_texture_ref": paths["base"],
            "roughness_texture_ref": paths["rough"],
            "metallic_texture_ref": paths["metal"],
            "normal_texture_ref": paths["normal"],
        },
        strategy="pplastic",
        inject={"ior": 1.5, "conductor_material": "Al", "is_metal": False},
    )
    assert ok
    assert shape.find(".//bsdf[@type='roughplastic']") is None
    blend = shape.find(".//bsdf[@type='blendbsdf']")
    assert blend is not None
    assert blend.find("./texture[@name='weight']") is not None
    assert blend.find("./bsdf[@type='pplastic']") is not None
    assert blend.find("./bsdf[@type='roughconductor']") is not None
    assert shape.find(".//texture[@name='normalmap']") is not None
    assert len(shape.findall(".//texture[@name='alpha']")) == 2


def test_glass_strategy_cannot_be_overridden_by_source_albedo(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    rough = tmp_path / "rough.png"
    Image.new("RGB", (1, 1), "white").save(base)
    Image.new("RGB", (1, 1), (64, 64, 64)).save(rough)
    shape = ET.Element("shape")
    assert _append_extracted_bsdf_xml(
        shape,
        {"base_color_texture_ref": str(base), "roughness_texture_ref": str(rough)},
        strategy="dielectric",
        inject={"ior": 1.52, "is_metal": False},
    )
    # Smooth dielectric, never roughdielectric: the polarized build returns
    # DoLP=0 for roughdielectric (dev_report 2026-07-06 §2.1), so glass must
    # keep the smooth Fresnel path to retain any polarization signal at all.
    assert shape.find(".//bsdf[@type='dielectric']") is not None
    assert shape.find(".//bsdf[@type='roughdielectric']") is None
    assert shape.find(".//bsdf[@type='pplastic']") is None
    assert shape.find(".//bsdf[@type='roughplastic']") is None


def test_manifest_v2_is_strict_and_allows_explicit_legacy_fallback(tmp_path: Path) -> None:
    importer = _load_importer()
    legacy = {"units": [{"id": "u", "mesh_obj": "meshes/u.obj"}]}
    issues = importer.validate_infinigen_manifest(
        legacy, tmp_path, allow_obj_fallback=True,
    )
    assert issues
    try:
        importer.validate_infinigen_manifest(legacy, tmp_path)
    except ValueError as exc:
        assert "strict Infinigen GLB/PBR" in str(exc)
    else:
        raise AssertionError("legacy manifest unexpectedly passed strict validation")


def test_manifest_v2_accepts_resolved_glb(tmp_path: Path) -> None:
    importer = _load_importer()
    glb = tmp_path / "meshes" / "u.glb"
    glb.parent.mkdir()
    glb.write_bytes(_minimal_uv_glb_bytes())
    base = tmp_path / "textures" / "base.png"
    base.parent.mkdir()
    Image.new("RGB", (2, 2), "white").save(base)
    channels = {
        "base_color": {
            "mode": "texture", "ref": "textures/base.png", "source": "linked",
            "colorspace": "srgb", "resolution": [2, 2],
            "bake_validation": {"attempted": True, "result": "spatial"},
        },
        "roughness": {"mode": "constant", "value": [0.4], "colorspace": "raw"},
        "metallic": {"mode": "constant", "value": [0.0], "colorspace": "raw"},
        "normal": {"mode": "not_applicable"},
    }
    manifest = {
        "export_contract_version": 2,
        "units": [{
            "id": "u", "mesh_glb": "meshes/u.glb",
            "glb_sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
            "uv": {"valid": True, "layer": "UVMap"},
            "pbr": {"status": "ok", "self_contained_glb": True, "channels": channels},
        }],
    }
    assert importer.validate_infinigen_manifest(manifest, tmp_path) == []


def test_manifest_v2_rejects_empty_glb_container(tmp_path: Path) -> None:
    importer = _load_importer()
    glb = tmp_path / "meshes" / "u.glb"
    glb.parent.mkdir()
    document = json.dumps({"asset": {"version": "2.0"}, "scenes": [{"nodes": []}]}).encode()
    document += b" " * ((-len(document)) % 4)
    glb.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 20 + len(document))
        + struct.pack("<II", len(document), 0x4E4F534A)
        + document
    )
    channels = {
        "base_color": {"mode": "constant", "value": [0.5, 0.5, 0.5], "colorspace": "srgb"},
        "roughness": {"mode": "constant", "value": [0.4], "colorspace": "raw"},
        "metallic": {"mode": "constant", "value": [0.0], "colorspace": "raw"},
        "normal": {"mode": "not_applicable"},
    }
    manifest = {
        "export_contract_version": 2,
        "units": [{
            "id": "u", "mesh_glb": "meshes/u.glb",
            "glb_sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
            "uv": {"valid": True, "layer": "UVMap"},
            "pbr": {"status": "ok", "self_contained_glb": True, "channels": channels},
        }],
    }
    try:
        importer.validate_infinigen_manifest(manifest, tmp_path)
    except ValueError as exc:
        assert "no mesh primitives" in str(exc)
    else:
        raise AssertionError("empty GLB unexpectedly passed strict validation")


def test_manifest_v2_rejects_collapsed_linked_texture(tmp_path: Path) -> None:
    importer = _load_importer()
    glb = tmp_path / "meshes" / "u.glb"
    glb.parent.mkdir()
    glb.write_bytes(_minimal_uv_glb_bytes())
    base = tmp_path / "textures" / "base.png"
    base.parent.mkdir()
    Image.new("RGB", (2, 2), "black").save(base)
    channels = {
        "base_color": {
            "mode": "texture", "ref": "textures/base.png", "source": "linked",
            "colorspace": "srgb", "resolution": [2, 2],
            "bake_validation": {"attempted": True, "result": "black"},
        },
        "roughness": {"mode": "constant", "value": [0.4], "colorspace": "raw"},
        "metallic": {"mode": "constant", "value": [0.0], "colorspace": "raw"},
        "normal": {"mode": "not_applicable"},
    }
    manifest = {
        "export_contract_version": 2,
        "units": [{
            "id": "u", "mesh_glb": "meshes/u.glb",
            "glb_sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
            "uv": {"valid": True, "layer": "UVMap"},
            "pbr": {"status": "ok", "self_contained_glb": True, "channels": channels},
        }],
    }
    try:
        importer.validate_infinigen_manifest(manifest, tmp_path)
    except ValueError as exc:
        assert "linked base_color bake validation is black" in str(exc)
    else:
        raise AssertionError("collapsed linked texture unexpectedly passed strict validation")


def test_glb_contract_rejects_collinear_uv_triangles(tmp_path: Path) -> None:
    importer = _load_importer()
    glb = tmp_path / "line_uv.glb"
    glb.write_bytes(_minimal_uv_glb_bytes(degenerate_uv=True))
    assert any(
        "degenerate TEXCOORD_0 triangle area" in issue
        for issue in importer._validate_glb_mesh_contract(glb)
    )


def test_glb_part_material_name_precedes_class_heuristics() -> None:
    selected, material_class = _select_part_render_material(
        "default_infinigen",
        {"material_name": "GlassPanel"},
        {"material_id": "GlassPanel", "base_color_factor": [0.2, 0.3, 0.4, 1.0]},
        {"GlassPanel": {"material_id": "GlassPanel", "render_binding": {"bsdf_strategy": "dielectric"}}},
    )
    assert selected == "GlassPanel"
    assert material_class == "glass"


def test_blend_children_do_not_reuse_global_bsdf_ids(tmp_path: Path) -> None:
    base = tmp_path / "base.png"
    metallic = tmp_path / "metallic.png"
    Image.new("RGB", (1, 1), "white").save(base)
    Image.new("RGB", (1, 1), (128, 128, 128)).save(metallic)
    root = ET.Element("scene")
    for index in range(2):
        shape = ET.SubElement(root, "shape", {"type": "obj", "id": f"shape_{index}"})
        assert _append_extracted_bsdf_xml(
            shape,
            {
                "base_color_texture_ref": str(base),
                "metallic_texture_ref": str(metallic),
            },
            strategy="pplastic",
        )
    _dedupe_shape_bsdfs_to_shared(root)
    declarations = [
        node.get("id")
        for node in root.iter("bsdf")
        if node.get("id")
    ]
    assert len(declarations) == len(set(declarations))
    assert "a_plastic" not in declarations
    assert "b_metal" not in declarations


def test_obj_normalizer_strips_invalid_normal_references(tmp_path: Path) -> None:
    source = tmp_path / "invalid.obj"
    source.write_text(
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "vt 0 0\n"
        "vt 1 0\n"
        "vt 0 1\n"
        "vn 0 0 1\n"
        "f 1/1/1 2/2/4 3/3/1\n",
        encoding="utf-8",
    )
    target = tmp_path / "normalized.obj"
    info = _write_normalized_obj_for_scene_cache(source, target)
    assert info["normal_invalid_references"] is True
    assert info["normal_mode"] == "recomputed"
    output = target.read_text(encoding="utf-8")
    assert "\nvn " not in output
    assert "f 1/1 2/2 3/3" in output
