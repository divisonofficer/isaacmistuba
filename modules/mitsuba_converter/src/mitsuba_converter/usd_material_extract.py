"""Per-prim UsdShade → simplified material descriptor.

The render daemon historically picked a BSDF strategy from the authoring map's
material category (``wood`` / ``fabric`` / channel-split hpbrdf etc.). USD prims
that carry real ``UsdPreviewSurface`` materials with basecolor / normal /
roughness textures were ignored, so every imported asset rendered with the same
generic grey roughplastic.

``extract_material_for_prim`` reads the bound UsdShade material, follows
``UsdPreviewSurface`` connections, and returns the basecolor RGB / texture path
plus optional roughness / normal map paths. The render daemon uses this to emit
a ``roughplastic`` BSDF backed by ``bitmap`` textures for prims that aren't in
the hpbrdf measured-BSDF category.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


@dataclass
class ExtractedMaterial:
    material_id: str
    usd_path: str | None = None
    surface_shader_id: str | None = None
    base_color_factor: tuple[float, float, float] | None = None
    base_color_asset: str | None = None        # raw USD asset path (with @@ stripped)
    normal_asset: str | None = None
    roughness_asset: str | None = None
    roughness_factor: float | None = None
    metallic_factor: float | None = None
    opacity_factor: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return (
            self.base_color_factor is None
            and self.base_color_asset is None
            and self.normal_asset is None
            and self.roughness_asset is None
            and self.roughness_factor is None
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unwrap(x: Any) -> Any:
    while isinstance(x, (tuple, list)) and len(x) > 0:
        x = x[0]
    return x


def _as_shader(conn: Any) -> Any:
    from pxr import UsdShade  # type: ignore

    conn = _unwrap(conn)
    if conn is None:
        return None
    try:
        return UsdShade.Shader(conn.GetPrim())
    except Exception:
        return None


def _input_value(shader: Any, name: str) -> Any:
    if shader is None:
        return None
    try:
        inp = shader.GetInput(name)
    except Exception:
        return None
    if not inp:
        return None
    try:
        return inp.Get()
    except Exception:
        return None


def _input_connected_shader(shader: Any, name: str) -> Any:
    if shader is None:
        return None
    try:
        inp = shader.GetInput(name)
    except Exception:
        return None
    if not inp:
        return None
    try:
        conn = inp.GetConnectedSource()
    except Exception:
        return None
    if not conn:
        return None
    return _as_shader(conn[0])


def _asset_to_str(asset: Any) -> str | None:
    if asset is None:
        return None
    try:
        s = str(asset)
    except Exception:
        return None
    s = s.strip().strip("@")
    if not s:
        return None
    return s


def _texture_file(shader: Any) -> str | None:
    """If ``shader`` is a UsdUVTexture, return its ``file`` asset path."""
    if shader is None:
        return None
    try:
        sid = shader.GetIdAttr().Get() or ""
    except Exception:
        sid = ""
    if "UVTexture" not in str(sid):
        return None
    try:
        f_in = shader.GetInput("file")
    except Exception:
        return None
    if not f_in:
        return None
    try:
        return _asset_to_str(f_in.Get())
    except Exception:
        return None


def _color_tuple(value: Any) -> tuple[float, float, float] | None:
    if value is None:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except Exception:
        return None


def _scalar(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(value[0])
        except Exception:
            return None


def extract_material_for_prim(
    prim: Any,
    *,
    stage: Any | None = None,
    usd_path: str | Path | None = None,
) -> ExtractedMaterial | None:
    """Return the bound UsdShade material's UsdPreviewSurface descriptor.

    Returns ``None`` when the prim has no bound material; an
    ``ExtractedMaterial`` with empty fields when a material is bound but no
    UsdPreviewSurface inputs are readable.
    """
    if prim is None or not getattr(prim, "IsValid", lambda: False)():
        return None
    try:
        from pxr import UsdShade  # type: ignore
    except Exception:
        return None

    try:
        bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    except Exception:
        return None
    material = _unwrap(bound)
    if not material:
        return None
    try:
        mat_path = str(material.GetPath())
    except Exception:
        mat_path = ""
    if not mat_path:
        return None

    out = ExtractedMaterial(
        material_id=mat_path,
        usd_path=str(usd_path) if usd_path else None,
    )

    try:
        surf_out = material.GetSurfaceOutput()
    except Exception:
        surf_out = None
    surface_shader: Any = None
    if surf_out:
        try:
            src = surf_out.GetConnectedSource()
        except Exception:
            src = None
        if src:
            surface_shader = _as_shader(src[0])

    if surface_shader is None:
        return out

    try:
        sid = surface_shader.GetIdAttr().Get() or ""
    except Exception:
        sid = ""
    out.surface_shader_id = str(sid)

    out.base_color_factor = _color_tuple(_input_value(surface_shader, "diffuseColor")) or _color_tuple(_input_value(surface_shader, "baseColor"))
    out.roughness_factor = _scalar(_input_value(surface_shader, "roughness"))
    out.metallic_factor = _scalar(_input_value(surface_shader, "metallic"))
    out.opacity_factor = _scalar(_input_value(surface_shader, "opacity"))

    diffuse_tex_shader = _input_connected_shader(surface_shader, "diffuseColor") or _input_connected_shader(surface_shader, "baseColor")
    out.base_color_asset = _texture_file(diffuse_tex_shader)

    normal_tex_shader = _input_connected_shader(surface_shader, "normal")
    out.normal_asset = _texture_file(normal_tex_shader)

    rough_tex_shader = _input_connected_shader(surface_shader, "roughness")
    out.roughness_asset = _texture_file(rough_tex_shader)

    return out


def resolve_asset_path(asset_str: str, *, usd_path: str | Path | None) -> Path | None:
    """Resolve a USD asset path (relative or absolute) against the USD file.

    Returns ``None`` when the file cannot be found.
    """
    if not asset_str:
        return None
    p = Path(asset_str)
    if p.is_absolute() and p.exists():
        return p.resolve()
    if usd_path is not None:
        usd_dir = Path(usd_path).parent
        candidate = (usd_dir / asset_str).resolve()
        if candidate.exists():
            return candidate
    if p.exists():
        return p.resolve()
    return None
