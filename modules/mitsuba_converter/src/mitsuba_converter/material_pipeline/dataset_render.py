"""Stage 4 (property maps) — primary-ray property extraction via ray_intersect.

Property maps (depth, geometric/shading normal, UV, material-region id, roughness,
metallic, base color) are NOT light-transport quantities, so they must not go through
the Monte-Carlo path/AOV integrator. On this build the `aov` integrator + film
accumulation injects a regular vertical-stripe artifact into every AOV channel that
GROWS with spp (a flat plane's depth develops comb stripes at high spp; clean at spp=1)
— proven on a trivial single-plane scene rendered with raw `mi.render`.

This module bypasses the integrator entirely: it shoots deterministic primary rays
(pixel-centred, with an optional fixed sub-pixel grid for anti-aliasing — NOT a
stochastic sampler), intersects the geometry, and reads each surface property directly:

    camera ray -> scene.ray_intersect() -> SurfaceInteraction
      depth (si.t), geometric normal (si.n), shading normal (si.sh_frame.n),
      uv (si.uv), shape index (-> material_id -> canonical parameter)

Material parameters come from `material_canonical.json`: a texture parameter is sampled
directly at si.uv (bilinear, no BSDF), a scalar is filled, an undefined/invalid one is
left out of the value map and marked in its valid-mask. No lighting, no spp, no BSDF
approximation, no spectral/polarized variant, no AOV backend.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[5]


def _geometry_only_xml(scene_xml: Path) -> Path:
    """Rewrite every top-level <bsdf> to a plain diffuse and drop the integrator/sensor,
    writing a temp scene next to the original. Property extraction needs GEOMETRY ONLY —
    material parameters come from material_canonical.json keyed by shape id, not from the
    loaded BSDFs — so this sidesteps measured_polarized (which won't instantiate in an
    RGB variant without a wavelength) and keeps the load variant-agnostic and cheap."""
    tree = ET.parse(scene_xml)
    root = tree.getroot()
    for b in root.findall("bsdf"):
        bid = b.get("id")
        for child in list(b):
            b.remove(child)
        b.set("type", "diffuse")
        if bid:
            b.set("id", bid)
    # shapes may carry inline bsdfs too
    for shape in root.findall("shape"):
        for b in shape.findall("bsdf"):
            for child in list(b):
                b.remove(child)
            b.set("type", "diffuse")
    out = scene_xml.parent / f".geom_only_{hashlib.md5(str(scene_xml).encode()).hexdigest()[:8]}.xml"
    tree.write(out, encoding="unicode")
    return out


def _to_lookat(cam: np.ndarray):
    """origin/target/up from a 4x4 camera-to-world. Matches multimodal's
    camera_to_world_to_lookat: the view direction is -Z (OpenGL convention, since
    camera_to_world_from_lookat stores matrix[:,2] = -forward), +Y is up."""
    cam = np.asarray(cam, np.float64).reshape(4, 4)
    origin = cam[:3, 3]
    fwd = -cam[:3, 2]
    up = cam[:3, 1]
    return origin, origin + fwd, up


@lru_cache(maxsize=256)
def _load_texture(path: str) -> Optional[np.ndarray]:
    from PIL import Image
    p = Path(path)
    if not p.is_absolute():
        p = REPO / path
    if not p.is_file():
        return None
    return np.asarray(Image.open(p).convert("L" if "roughness" in path or "metallic" in path
                                            else "RGB"), np.float32) / 255.0


def _sample_texture(tex: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Bilinear-sample a texture at per-pixel UV. Mitsuba UV has v=0 at the bottom, so
    the image row is flipped. `uv` is (N,2); returns (N,) or (N,3)."""
    h, w = tex.shape[:2]
    u = np.clip(uv[:, 0], 0.0, 1.0) * (w - 1)
    v = np.clip(1.0 - uv[:, 1], 0.0, 1.0) * (h - 1)
    x0 = np.floor(u).astype(int); y0 = np.floor(v).astype(int)
    x1 = np.minimum(x0 + 1, w - 1); y1 = np.minimum(y0 + 1, h - 1)
    fx = (u - x0)[:, None] if tex.ndim == 3 else (u - x0)
    fy = (v - y0)[:, None] if tex.ndim == 3 else (v - y0)
    a = tex[y0, x0]; b = tex[y0, x1]; c = tex[y1, x0]; d = tex[y1, x1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def render_property_maps(
    scene_xml: str | Path,
    camera_to_world: np.ndarray,
    fov_deg: float,
    canonical: Mapping[str, Any],
    *,
    width: int = 640,
    height: int = 480,
    subpixel: int = 2,
    variant: str = "cuda_ad_rgb",
) -> dict:
    """Extract property maps for one view. Returns a dict of float32 arrays:
    depth(H,W), geo_normal(H,W,3), sh_normal(H,W,3), uv(H,W,2), valid(H,W bool),
    material_region_id(H,W int32), roughness(H,W)+roughness_valid, metallic(H,W)+..,
    base_color(H,W,3)+base_color_valid, plus `region_legend` (id->material_id)."""
    import drjit as dr
    import mitsuba as mi
    mi.set_variant(variant)
    scene = mi.load_file(str(_geometry_only_xml(Path(scene_xml))))
    shapes = scene.shapes()
    shape_ids = [s.id() for s in shapes]

    # shape_id -> material_id, and canonical material lookup
    shape2mat: dict[str, str] = {}
    mat_by_id: dict[str, dict] = {}
    for m in canonical.get("materials", []):
        mat_by_id[m["material_id"]] = m
        for sid in m.get("shape_ids", []):
            shape2mat[sid] = m["material_id"]

    origin, target, up = _to_lookat(camera_to_world)
    sensor = mi.load_dict({
        "type": "perspective", "fov": float(fov_deg),
        "to_world": mi.ScalarTransform4f().look_at(origin=list(origin), target=list(target), up=list(up)),
        "film": {"type": "hdrfilm", "width": width, "height": height, "rfilter": {"type": "box"}},
        "sampler": {"type": "independent", "sample_count": 1},
    })

    n = width * height
    px = (np.arange(width) + 0.0)
    py = (np.arange(height) + 0.0)
    gx, gy = np.meshgrid(px, py)  # (H,W)
    gx = gx.ravel(); gy = gy.ravel()

    def _intersect(ox: float, oy: float):
        pos = mi.Point2f((gx + ox) / width, (gy + oy) / height)
        ray, _ = sensor.sample_ray(0.0, 0.0, pos, mi.Point2f(0.5, 0.5))
        si = scene.ray_intersect(ray)
        valid = np.array(si.is_valid())
        return si, valid

    # --- anti-aliased continuous fields over a fixed KxK sub-pixel grid ---
    S = max(1, int(subpixel))
    depth_sum = np.zeros(n, np.float64); ng_sum = np.zeros((n, 3), np.float64)
    shn_sum = np.zeros((n, 3), np.float64); cnt = np.zeros(n, np.float64)
    for i in range(S):
        for j in range(S):
            si, valid = _intersect((i + 0.5) / S, (j + 0.5) / S)
            t = np.array(si.t); ng = np.array(si.n); shn = np.array(si.sh_frame.n)
            m = valid & np.isfinite(t)
            depth_sum[m] += t[m]; ng_sum[m] += ng[m]; shn_sum[m] += shn[m]; cnt[m] += 1.0

    valid = cnt > 0
    depth = np.where(valid, depth_sum / np.maximum(cnt, 1), 0.0)
    def _norm(v):
        nrm = np.linalg.norm(v, axis=1, keepdims=True)
        return np.where(nrm > 1e-8, v / np.maximum(nrm, 1e-8), 0.0)
    geo_n = _norm(ng_sum); sh_n = _norm(shn_sum)

    # --- categorical fields + material params from the CENTRE sub-pixel (deterministic) ---
    si_c, valid_c = _intersect(0.5, 0.5)
    uv_c = np.array(si_c.uv)
    shape_idx = dr.full(mi.UInt32, len(shapes), n)   # sentinel = out of range
    for i, s in enumerate(shapes):
        shape_idx[dr.eq(si_c.shape, mi.ShapePtr(s))] = i
    shape_idx = np.array(shape_idx)

    # material_region_id: dense integer per distinct material_id actually hit
    region_id = np.full(n, -1, np.int32)
    legend: dict[int, str] = {}
    mat_of_pixel = np.array([""] * n, dtype=object)
    next_id = 0
    mid_to_region: dict[str, int] = {}
    for i in range(len(shapes)):
        px_mask = valid_c & (shape_idx == i)
        if not px_mask.any():
            continue
        mid = shape2mat.get(shape_ids[i])
        if mid is None:
            continue
        if mid not in mid_to_region:
            mid_to_region[mid] = next_id; legend[next_id] = mid; next_id += 1
        region_id[px_mask] = mid_to_region[mid]
        mat_of_pixel[px_mask] = mid

    # --- roughness / metallic / base_color via direct texture-at-UV or scalar ---
    def _param_map(pname: str, channels: int):
        val = np.zeros((n, channels), np.float32) if channels > 1 else np.zeros(n, np.float32)
        pvalid = np.zeros(n, bool)
        for mid, region in mid_to_region.items():
            p = (mat_by_id[mid].get("parameters") or {}).get(pname)
            if p is None or not p.get("valid", False):
                continue
            mask = (region_id == region)
            if not mask.any():
                continue
            if p.get("path"):
                tex = _load_texture(p["path"])
                if tex is None:
                    continue
                if channels == 1 and tex.ndim == 3:
                    tex = tex.mean(-1)
                sampled = _sample_texture(tex, uv_c[mask])
                if channels > 1 and sampled.ndim == 1:
                    sampled = np.repeat(sampled[:, None], channels, 1)
                val[mask] = sampled
            elif p.get("value") is not None:
                val[mask] = np.asarray(p["value"], np.float32)
            else:
                continue
            pvalid[mask] = True
        return val, pvalid

    rough, rough_v = _param_map("roughness_perceptual", 1)
    metal, metal_v = _param_map("metallic", 1)
    basec, basec_v = _param_map("base_color", 3)

    def r(a, *shape):
        return a.reshape(height, width, *shape) if shape else a.reshape(height, width)

    return {
        "depth": r(depth.astype(np.float32)),
        "geo_normal": r(geo_n.astype(np.float32), 3),
        "sh_normal": r(sh_n.astype(np.float32), 3),
        "uv": r(uv_c.astype(np.float32), 2),
        "valid": r(valid),
        "material_region_id": r(region_id),
        "roughness": r(rough), "roughness_valid": r(rough_v),
        "metallic": r(metal), "metallic_valid": r(metal_v),
        "base_color": r(basec, 3), "base_color_valid": r(basec_v),
        "region_legend": legend,
    }
