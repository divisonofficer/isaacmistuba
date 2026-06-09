"""
USD exporter: authoring_map.json → .usda (Isaac Sim / USD round-trip).

Coordinate convention (same as render_daemon.py):
  USD X = authoring_x
  USD Y = height (up-axis)
  USD Z = authoring_y

Each object that has a source_ref (usd_file#/prim/path) is emitted as a USD
Xform with a Reference to the original prim, so all geometry and materials are
preserved from the source USD.  Room shell objects (no source_ref) are emitted
as UsdGeom.Cube primitives.

Usage:
    from mitsuba_converter.usd_exporter import export_authoring_map_to_usd
    from pathlib import Path

    path = export_authoring_map_to_usd(
        authoring_map,
        output_usda_path=Path("out/exported/kitchen.usda"),
        repo_root=Path("/jarvis/project/robomituba"),
    )
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any


def _safe_prim_name(raw: str) -> str:
    """Convert an arbitrary string to a valid USD prim name."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if name and name[0].isdigit():
        name = "prim_" + name
    return name or "prim"


def _yaw_to_matrix(yaw_deg: float) -> list[float]:
    """Y-axis rotation matrix (row-major 4x4, USD GfMatrix4d convention)."""
    a = math.radians(yaw_deg)
    ca, sa = math.cos(a), math.sin(a)
    return [
        ca,  0.0, sa,  0.0,
        0.0, 1.0, 0.0, 0.0,
        -sa, 0.0, ca,  0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def export_authoring_map_to_usd(
    authoring_map: dict[str, Any],
    output_usda_path: Path,
    repo_root: Path,
    *,
    default_wall_height_m: float | None = None,
    default_floor_y: float = 0.0,
) -> Path:
    """Export an authoring_map to a .usda file readable by Isaac Sim.

    Parameters
    ----------
    authoring_map:
        Parsed authoring_map.json dict.
    output_usda_path:
        Destination path for the .usda file.
    repo_root:
        Absolute path to the robomituba repo root (used to resolve source_ref).
    default_wall_height_m:
        Override wall height; falls back to settings.default_wall_height_m.
    default_floor_y:
        Y coordinate of the ground plane in USD space (default 0.0).

    Returns
    -------
    Path to the written .usda file.
    """
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pxr (OpenUSD) is required for USD export. "
            "Install via: pip install usd-core"
        ) from exc

    output_usda_path = Path(output_usda_path)
    output_usda_path.parent.mkdir(parents=True, exist_ok=True)

    scene_id = authoring_map.get("scene_id") or "exported_scene"
    settings = dict(authoring_map.get("settings") or {})
    wall_height = default_wall_height_m or float(settings.get("default_wall_height_m") or 2.4)
    wall_thickness = float(settings.get("default_wall_thickness_m") or 0.08)
    map_w = float(settings.get("map_w") or 20.0)
    map_h = float(settings.get("map_h") or 20.0)

    stage = Usd.Stage.CreateNew(str(output_usda_path))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    root_path = Sdf.Path(f"/{_safe_prim_name(scene_id)}")
    root_xform = UsdGeom.Xform.Define(stage, root_path)
    stage.SetDefaultPrim(root_xform.GetPrim())

    # ── Room shell ──────────────────────────────────────────────────────────
    _build_room_shell_usd(
        stage, root_path, map_w, map_h, wall_height, wall_thickness, default_floor_y
    )

    # ── Objects ─────────────────────────────────────────────────────────────
    objects_path = root_path.AppendChild("objects")
    UsdGeom.Xform.Define(stage, objects_path)

    used_names: dict[str, int] = {}

    for obj in authoring_map.get("objects") or []:
        obj_id = str(obj.get("id") or "obj")
        source_ref = str(obj.get("source_ref") or "")
        geom = obj.get("geometry") or {}
        center = geom.get("center") or [0.0, 0.0]
        yaw_deg = float(geom.get("yaw_deg") or 0.0)
        base_height = float(geom.get("base_height_m") or default_floor_y)

        prim_name = _safe_prim_name(obj_id)
        # de-duplicate names
        if prim_name in used_names:
            used_names[prim_name] += 1
            prim_name = f"{prim_name}_{used_names[prim_name]}"
        else:
            used_names[prim_name] = 0

        prim_path = objects_path.AppendChild(prim_name)

        tx = float(center[0])
        ty = base_height
        tz = float(center[1])  # authoring_y → USD Z

        if "#" in source_ref:
            _emit_referenced_prim(
                stage, prim_path, source_ref, repo_root,
                tx=tx, ty=ty, tz=tz, yaw_deg=yaw_deg,
                label=str(obj.get("label") or obj_id),
            )
        else:
            # No geometry reference — emit a simple placeholder cube
            _emit_placeholder_cube(
                stage, prim_path, obj,
                tx=tx, ty=ty, tz=tz, yaw_deg=yaw_deg,
                wall_height=wall_height,
            )

    stage.GetRootLayer().Save()
    return output_usda_path


# ── Private helpers ──────────────────────────────────────────────────────────


def _set_xform_translate_rotate(
    prim: Any, tx: float, ty: float, tz: float, yaw_deg: float
) -> None:
    from pxr import Gf, UsdGeom  # type: ignore

    xformable = UsdGeom.Xformable(prim)
    xformable.ClearXformOpOrder()
    t_op = xformable.AddTranslateOp()
    t_op.Set(Gf.Vec3d(tx, ty, tz))
    if abs(yaw_deg) > 1e-4:
        r_op = xformable.AddRotateYOp()
        r_op.Set(yaw_deg)


def _emit_referenced_prim(
    stage: Any,
    prim_path: Any,
    source_ref: str,
    repo_root: Path,
    *,
    tx: float,
    ty: float,
    tz: float,
    yaw_deg: float,
    label: str,
) -> None:
    from pxr import Gf, Sdf, UsdGeom  # type: ignore

    usd_file, prim_path_str = source_ref.split("#", 1)
    abs_usd = str((repo_root / usd_file).resolve())

    prim = stage.DefinePrim(prim_path, "Xform")
    prim.GetReferences().AddReference(
        assetPath=abs_usd,
        primPath=Sdf.Path(prim_path_str),
    )
    prim.SetCustomDataByKey("sourceRef", source_ref)
    prim.SetCustomDataByKey("label", label)

    _set_xform_translate_rotate(prim, tx, ty, tz, yaw_deg)


def _emit_placeholder_cube(
    stage: Any,
    prim_path: Any,
    obj: dict[str, Any],
    *,
    tx: float,
    ty: float,
    tz: float,
    yaw_deg: float,
    wall_height: float,
) -> None:
    from pxr import Gf, UsdGeom  # type: ignore

    obj_type = str(obj.get("type") or "landmark")
    geom = obj.get("geometry") or {}
    size_m = geom.get("size_m") or [0.5, wall_height, 0.5]
    if isinstance(size_m, list) and len(size_m) >= 3:
        sx, sy, sz = float(size_m[0]), float(size_m[1]), float(size_m[2])
    else:
        sx = sy = sz = 0.5

    cube = UsdGeom.Cube.Define(stage, prim_path)
    cube.GetSizeAttr().Set(1.0)
    cube.GetPrim().SetCustomDataByKey("type", obj_type)
    cube.GetPrim().SetCustomDataByKey("label", str(obj.get("label") or ""))

    from pxr import UsdGeom as _ug
    xformable = _ug.Xformable(cube.GetPrim())
    xformable.ClearXformOpOrder()
    t_op = xformable.AddTranslateOp()
    t_op.Set((__import__("pxr").Gf.Vec3d(tx, ty + sy / 2.0, tz)))
    s_op = xformable.AddScaleOp()
    s_op.Set(__import__("pxr").Gf.Vec3f(sx, sy, sz))
    if abs(yaw_deg) > 1e-4:
        r_op = xformable.AddRotateYOp()
        r_op.Set(yaw_deg)


def _build_room_shell_usd(
    stage: Any,
    root_path: Any,
    map_w: float,
    map_h: float,
    wall_height: float,
    wall_thickness: float,
    floor_y: float,
) -> None:
    from pxr import Gf, UsdGeom  # type: ignore

    shell_path = root_path.AppendChild("room_shell")
    UsdGeom.Xform.Define(stage, shell_path)

    half_w = map_w / 2.0
    half_h = map_h / 2.0
    half_wt = wall_thickness / 2.0
    half_wall_y = wall_height / 2.0

    def _cube(name: str, translate: tuple, scale: tuple) -> None:
        path = shell_path.AppendChild(name)
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(1.0)
        xf = UsdGeom.Xformable(cube.GetPrim())
        xf.ClearXformOpOrder()
        t = xf.AddTranslateOp()
        t.Set(Gf.Vec3d(*translate))
        s = xf.AddScaleOp()
        s.Set(Gf.Vec3f(*scale))

    # Floor
    _cube("floor", (half_w, floor_y - 0.025, half_h), (map_w, 0.05, map_h))
    # Ceiling
    _cube("ceiling", (half_w, floor_y + wall_height + 0.025, half_h), (map_w, 0.05, map_h))
    # Walls (south/north/west/east)
    _cube("wall_south", (half_w, floor_y + half_wall_y, -half_wt), (map_w, wall_height, wall_thickness))
    _cube("wall_north", (half_w, floor_y + half_wall_y, map_h + half_wt), (map_w, wall_height, wall_thickness))
    _cube("wall_west", (-half_wt, floor_y + half_wall_y, half_h), (wall_thickness, wall_height, map_h))
    _cube("wall_east", (map_w + half_wt, floor_y + half_wall_y, half_h), (wall_thickness, wall_height, map_h))
