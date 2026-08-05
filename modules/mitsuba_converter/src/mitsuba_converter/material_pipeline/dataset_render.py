"""Stage 4 (property maps) — primary-ray property extraction via ray_intersect.

Property maps (depth, geometric/shading normal, roughness, metallic, base color) are
NOT light-transport quantities, so they must not go through the Monte-Carlo path/AOV
integrator — on this build the `aov` integrator injects spp-proportional vertical-stripe
artifacts (a flat plane's depth is clean at spp=1, comb-striped at spp=4096). This module
shoots deterministic primary rays (pixel-centred + a fixed sub-pixel grid for AA, NOT a
stochastic sampler), intersects the geometry, and reads each property directly.

CRITICAL — texture UVs: reading a texture at `si.uv` with hand-rolled numpy sampling is
WRONG, because it ignores the per-texture UV transform / wrap-mode / filter that Mitsuba
applies (symptom: wood texture landing on a glass window). We instead let MITSUBA evaluate
the texture via `si.bsdf().eval_diffuse_reflectance(si)` on purpose-built readout scenes,
so the property maps use the exact same UV pipeline as the RGB render:

    base_color : the scene's own BSDFs (measured→analytic) → eval_diffuse_reflectance
    roughness  : each shape → diffuse{reflectance = the shape's roughness texture NODE
                 (copied with its transform) or the canonical meaningful scalar}
    metallic   : each shape → diffuse{reflectance = canonical metallic scalar
                 (conductor→1, else 0; leaked glTF factor/texture NOT trusted)}

Loaded scenes are cached per-XML so a batch of viewpoints costs one load per readout.
"""
from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[5]

_SCENE_CACHE: dict[str, Any] = {}


def _to_lookat(cam: np.ndarray):
    """origin/target/up from a 4x4 camera-to-world. Matches multimodal's
    camera_to_world_to_lookat: view direction is -Z (camera_to_world_from_lookat stores
    matrix[:,2] = -forward), +Y up."""
    cam = np.asarray(cam, np.float64).reshape(4, 4)
    origin = cam[:3, 3]
    return origin, origin - cam[:3, 2], cam[:3, 1]


def _bsdf_to_material(scene_dir: Path) -> dict[str, str]:
    idx = json.loads((scene_dir / "xml_scene_index.json").read_text())
    pol = json.loads((scene_dir / "render_scene_material_policy.json").read_text())
    sh2mat = {sp["shape_id"]: sp.get("material_id")
              for sp in pol.get("shape_policies", []) if sp.get("shape_id")}
    out: dict[str, str] = {}
    for sh in idx.get("shapes", []):
        ref, mid = sh.get("bsdf_ref"), sh2mat.get(sh.get("shape_id"))
        if ref and mid:
            out.setdefault(ref, mid)
    return out


def _find_texture_node(bsdf: ET.Element, name: str) -> Optional[ET.Element]:
    """Deep-copy the first <texture name="{name}"> node in a bsdf subtree (preserving any
    UV transform / wrap / filter children), or None."""
    for tex in bsdf.iter("texture"):
        if tex.get("name") == name:
            t = copy.deepcopy(tex)
            t.set("name", "reflectance")
            return t
    return None


def _diffuse(shape_bsdf_id: str, reflectance) -> ET.Element:
    b = ET.Element("bsdf", {"type": "diffuse", "id": shape_bsdf_id})
    if isinstance(reflectance, ET.Element):
        b.append(reflectance)
    else:
        b.append(ET.Element("rgb", {"name": "reflectance", "value": reflectance}))
    return b


def _stage_readout_xml(scene_xml: Path, canonical: Mapping[str, Any], channel: str) -> Path:
    """Write a temp scene whose eval_diffuse_reflectance yields `channel` — every material
    becomes a diffuse whose reflectance is the requested property (base color texture for
    'albedo', roughness texture/scalar for 'roughness', metallic scalar for 'metallic'),
    with the scene's own texture nodes (UV transform preserved). All BSDFs become diffuse
    so the scene also loads cleanly in an RGB variant (no measured_polarized wavelength)."""
    scene_dir = scene_xml.parent
    bsdf2mat = _bsdf_to_material(scene_dir)
    mat_by_id = {m["material_id"]: m for m in canonical.get("materials", [])}
    tree = ET.parse(scene_xml)
    root = tree.getroot()

    for b in list(root.findall("bsdf")):
        bid = b.get("id")
        canon = mat_by_id.get(bsdf2mat.get(bid))
        refl: Any = "0 0 0"
        if channel == "albedo":
            # the material's authored base colour = its albedo. For pplastic that is
            # diffuse_reflectance; for a conductor it is specular_reflectance (a ROUGH
            # metal's colour IS its albedo — only a perfect mirror has none). Copy the
            # scene texture node with its UV transform.
            node = (_find_texture_node(b, "diffuse_reflectance")
                    or _find_texture_node(b, "specular_reflectance"))
            if node is not None:
                refl = node
            else:
                bc = (canon or {}).get("parameters", {}).get("base_color", {})
                refl = (" ".join(f"{float(v):.4f}" for v in bc["value"])
                        if bc.get("value") is not None else "0 0 0")
        else:
            param = (canon or {}).get("parameters", {}).get(
                "roughness_perceptual" if channel == "roughness" else "metallic")
            if param and param.get("valid", False):
                if channel == "roughness" and param.get("path"):
                    node = _find_texture_node(b, "alpha")   # scene roughness tex, transform kept
                    refl = node if node is not None else "0.5 0.5 0.5"
                elif param.get("value") is not None:
                    v = float(param["value"])
                    refl = f"{v:.4f} {v:.4f} {v:.4f}"
        for c in list(b):
            b.remove(c)
        b.set("type", "diffuse")
        b.set("id", bid)
        if isinstance(refl, ET.Element):
            b.append(refl)
        else:
            b.append(ET.Element("rgb", {"name": "reflectance", "value": refl}))

    out = scene_xml.parent / f".prop_{channel}.xml"
    tree.write(out, encoding="unicode")
    return out


def _scene(xml_path: Path):
    import mitsuba as mi
    key = str(xml_path)
    if key not in _SCENE_CACHE:
        _SCENE_CACHE[key] = mi.load_file(key)
    return _SCENE_CACHE[key]


def render_property_maps(
    scene_xml: str | Path,
    camera_to_world: np.ndarray,
    fov_deg: float,
    canonical: Mapping[str, Any],
    *,
    width: int = 640,
    height: int = 480,
    subpixel: int = 3,
    variant: str = "cuda_ad_rgb",
) -> dict:
    """Extract property maps for one view via Mitsuba texture eval (correct UVs)."""
    import drjit as dr
    import mitsuba as mi
    mi.set_variant(variant)
    scene_xml = Path(scene_xml)

    scenes = {ch: _scene(_stage_readout_xml(scene_xml, canonical, ch))
              for ch in ("albedo", "roughness", "metallic")}
    alb_scene = scenes["albedo"]
    shapes = alb_scene.shapes()
    shape_ids = [s.id() for s in shapes]
    shape2mat: dict[str, str] = {}
    for m in canonical.get("materials", []):
        for sid in m.get("shape_ids", []):
            shape2mat[sid] = m["material_id"]

    o, t, u = _to_lookat(camera_to_world)
    sensor = mi.load_dict({
        "type": "perspective", "fov": float(fov_deg),
        "to_world": mi.ScalarTransform4f().look_at(origin=list(o), target=list(t), up=list(u)),
        "film": {"type": "hdrfilm", "width": width, "height": height, "rfilter": {"type": "box"}},
        "sampler": {"type": "independent", "sample_count": 1},
    })
    n = width * height
    gx, gy = np.meshgrid(np.arange(width) + 0.0, np.arange(height) + 0.0)
    gx = gx.ravel(); gy = gy.ravel()

    def rays(ox, oy):
        pos = mi.Point2f((gx + ox) / width, (gy + oy) / height)
        ray, _ = sensor.sample_ray(0.0, 0.0, pos, mi.Point2f(0.5, 0.5))
        return ray

    S = max(1, int(subpixel))
    depth_sum = np.zeros(n); ng_sum = np.zeros((n, 3)); shn_sum = np.zeros((n, 3)); cnt = np.zeros(n)
    acc = {ch: np.zeros((n, 3)) for ch in scenes}
    acc_cnt = np.zeros(n)
    for i in range(S):
        for j in range(S):
            ray = rays((i + 0.5) / S, (j + 0.5) / S)
            si = alb_scene.ray_intersect(ray)
            valid = np.array(si.is_valid())
            tt = np.array(si.t); m = valid & np.isfinite(tt)
            depth_sum[m] += tt[m]
            ng_sum[m] += np.array(si.n)[m]; shn_sum[m] += np.array(si.sh_frame.n)[m]; cnt[m] += 1
            # eval each readout scene at the SAME rays (geometry identical across readouts)
            for ch, sc in scenes.items():
                sic = sc.ray_intersect(ray)
                val = np.array(sic.bsdf().eval_diffuse_reflectance(sic))
                acc[ch][valid] += val[valid]
            acc_cnt[valid] += 1

    valid = cnt > 0
    depth = np.where(valid, depth_sum / np.maximum(cnt, 1), 0.0)
    def _norm(v):
        nn = np.linalg.norm(v, axis=1, keepdims=True)
        return np.where(nn > 1e-8, v / np.maximum(nn, 1e-8), 0.0)
    c = np.maximum(acc_cnt, 1)[:, None]
    basec = acc["albedo"] / c
    rough = (acc["roughness"] / c).mean(1)
    metal = (acc["metallic"] / c).mean(1)

    # material_region_id from centre sub-pixel
    si_c = alb_scene.ray_intersect(rays(0.5, 0.5)); valid_c = np.array(si_c.is_valid())
    shape_idx = dr.full(mi.UInt32, len(shapes), n)
    for k, s in enumerate(shapes):
        shape_idx[dr.eq(si_c.shape, mi.ShapePtr(s))] = k
    shape_idx = np.array(shape_idx)
    region_id = np.full(n, -1, np.int32); legend: dict[int, str] = {}
    mid_to_region: dict[str, int] = {}; nxt = 0
    for k in range(len(shapes)):
        pm = valid_c & (shape_idx == k)
        if not pm.any():
            continue
        mid = shape2mat.get(shape_ids[k])
        if mid is None:
            continue
        if mid not in mid_to_region:
            mid_to_region[mid] = nxt; legend[nxt] = mid; nxt += 1
        region_id[pm] = mid_to_region[mid]

    def r(a, *sh):
        return a.reshape(height, width, *sh) if sh else a.reshape(height, width)
    return {
        "depth": r(depth.astype(np.float32)),
        "geo_normal": r(_norm(ng_sum).astype(np.float32), 3),
        "sh_normal": r(_norm(shn_sum).astype(np.float32), 3),
        "valid": r(valid),
        "material_region_id": r(region_id),
        "base_color": r(basec.astype(np.float32), 3), "base_color_valid": r(valid),
        "roughness": r(rough.astype(np.float32)), "roughness_valid": r(valid),
        "metallic": r(metal.astype(np.float32)), "metallic_valid": r(valid),
        "region_legend": legend,
    }
