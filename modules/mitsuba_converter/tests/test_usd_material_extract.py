"""Smoke test for :mod:`mitsuba_converter.usd_material_extract`.

Constructs a tiny in-memory USD stage with a UsdPreviewSurface bound to a
single mesh, then verifies the extractor recovers basecolor / roughness /
texture-asset paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest


pxr = pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom, UsdShade  # noqa: E402

from mitsuba_converter.usd_material_extract import (  # noqa: E402
    ExtractedMaterial,
    extract_material_for_prim,
    resolve_asset_path,
)


def _build_stage(tmp_path: Path, *, with_texture: Path | None = None) -> Path:
    usd_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    mesh = UsdGeom.Mesh.Define(stage, "/World/Mesh")
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])

    mat = UsdShade.Material.Define(stage, "/World/Looks/Mat")
    shader = UsdShade.Shader.Define(stage, "/World/Looks/Mat/Preview")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set((0.8, 0.2, 0.1))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.4)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)

    if with_texture is not None:
        tex_shader = UsdShade.Shader.Define(stage, "/World/Looks/Mat/Tex")
        tex_shader.CreateIdAttr("UsdUVTexture")
        tex_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(str(with_texture))
        tex_out = tex_shader.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(tex_out)

    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    UsdShade.MaterialBindingAPI(mesh.GetPrim()).Bind(mat)

    stage.GetRootLayer().Save()
    return usd_path


def test_extract_basic_material(tmp_path: Path) -> None:
    usd_path = _build_stage(tmp_path)
    stage = Usd.Stage.Open(str(usd_path))
    prim = stage.GetPrimAtPath("/World/Mesh")
    em = extract_material_for_prim(prim, stage=stage, usd_path=usd_path)
    assert isinstance(em, ExtractedMaterial)
    assert em.material_id.endswith("/World/Looks/Mat")
    assert em.surface_shader_id == "UsdPreviewSurface"
    assert em.base_color_factor == pytest.approx((0.8, 0.2, 0.1))
    assert em.roughness_factor == pytest.approx(0.4)
    assert em.base_color_asset is None  # no texture connection in this fixture
    assert em.normal_asset is None


def test_extract_with_texture(tmp_path: Path) -> None:
    tex_path = tmp_path / "basecolor.png"
    tex_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # not a real PNG, just a sentinel
    usd_path = _build_stage(tmp_path, with_texture=tex_path)
    stage = Usd.Stage.Open(str(usd_path))
    prim = stage.GetPrimAtPath("/World/Mesh")
    em = extract_material_for_prim(prim, stage=stage, usd_path=usd_path)
    assert em is not None
    assert em.base_color_asset is not None
    resolved = resolve_asset_path(em.base_color_asset, usd_path=usd_path)
    assert resolved is not None and resolved.exists()
    assert resolved.name == "basecolor.png"


def test_extract_returns_none_when_unbound(tmp_path: Path) -> None:
    usd_path = tmp_path / "empty.usda"
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.Mesh.Define(stage, "/World/M")
    stage.GetRootLayer().Save()
    stage = Usd.Stage.Open(str(usd_path))
    prim = stage.GetPrimAtPath("/World/M")
    em = extract_material_for_prim(prim, stage=stage, usd_path=usd_path)
    # Unbound prim: bound material is empty → returns None.
    assert em is None or em.is_empty()
