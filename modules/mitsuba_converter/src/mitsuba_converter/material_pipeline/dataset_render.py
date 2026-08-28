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

from mitsuba_converter.nir_reflectance import physical_material_for, nir_reflectance
from mitsuba_converter.material_pipeline.spectral_band import _nir_albedo_png
from mitsuba_converter.material_pipeline.ir_effective_scene import uses_specular_semantic_masks

REPO = Path(__file__).resolve().parents[5]

_SCENE_CACHE: dict[str, Any] = {}


def _axial_depth(
    ray_range: np.ndarray,
    ray_direction: np.ndarray,
    camera_forward: np.ndarray,
) -> np.ndarray:
    """Convert camera-centred ray range to optical-axis (Z) depth."""
    directions = np.asarray(ray_direction, np.float64)
    directions /= np.maximum(np.linalg.norm(directions, axis=-1, keepdims=True), 1e-12)
    forward = np.asarray(camera_forward, np.float64)
    forward /= max(float(np.linalg.norm(forward)), 1e-12)
    return np.asarray(ray_range, np.float64) * np.sum(directions * forward, axis=-1)


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


def _opaque_records_by_bsdf(scene_dir: Path) -> dict[str, dict[str, Any]]:
    report_path = scene_dir / "opaque_scene_assembly.json"
    if not report_path.is_file():
        return {}
    report = json.loads(report_path.read_text())
    out: dict[str, dict[str, Any]] = {}
    for row in report.get("replacements") or []:
        record_path = row.get("spatial_record")
        if not row.get("bsdf_id") or not record_path or not Path(record_path).is_file():
            continue
        out[str(row["bsdf_id"])] = json.loads(Path(record_path).read_text())
    return out


def _bitmap_reflectance(path: str, *, raw: bool) -> ET.Element:
    node = ET.Element("texture", {"type": "bitmap", "name": "reflectance"})
    ET.SubElement(node, "string", {"name": "filename", "value": str(Path(path).resolve())})
    if raw:
        ET.SubElement(node, "boolean", {"name": "raw", "value": "true"})
    return node


def _stage_readout_xml(
    scene_xml: Path,
    canonical: Mapping[str, Any],
    channel: str,
    *,
    nir_band: int = 854,
    nir_dir: Optional[Path] = None,
    scratch_dir: Optional[Path] = None,
    metadata_scene: Optional[Path] = None,
) -> Path:
    """Write a temp scene whose eval_diffuse_reflectance yields `channel` — every material
    becomes a diffuse whose reflectance is the requested property (base color texture for
    'albedo', roughness texture/scalar for 'roughness', metallic scalar for 'metallic'),
    with the scene's own texture nodes (UV transform preserved). All BSDFs become diffuse
    so the scene also loads cleanly in an RGB variant (no measured_polarized wavelength)."""
    # Texture-capped render XMLs are written under a run-local directory. The
    # compiled material/index/semantic sidecars remain in the immutable
    # effective scene and must not be looked up beside that transient copy.
    scene_dir = Path(metadata_scene) if metadata_scene is not None else scene_xml.parent
    bsdf2mat = _bsdf_to_material(scene_dir)
    opaque_records = _opaque_records_by_bsdf(scene_dir)
    mat_by_id = {m["material_id"]: m for m in canonical.get("materials", [])}
    tree = ET.parse(scene_xml)
    root = tree.getroot()
    nir_dir = nir_dir or (scene_dir / f"nir_band_{nir_band}")

    for b in list(root.findall("bsdf")):
        bid = b.get("id")
        canon = mat_by_id.get(bsdf2mat.get(bid))
        refl: Any = "0 0 0"
        opaque = opaque_records.get(str(bid))
        if channel == "nir_albedo":
            outputs = dict((opaque or {}).get("outputs") or {})
            mid = bsdf2mat.get(bid)
            optical_class = (canon or {}).get("optical_class")
            pmat, _confidence = physical_material_for(mid, optical_class)
            info = nir_reflectance(pmat, nir_band)
            node = _find_texture_node(b, "diffuse_reflectance")
            if node is None:
                node = _find_texture_node(b, "specular_reflectance")
            source = outputs.get("base_color")
            if source is None and node is not None:
                filename = node.find("string[@name='filename']")
                source = filename.get("value") if filename is not None else None
            if info.get("albedo_channel"):
                nir_png = _nir_albedo_png(source, pmat, nir_band, nir_dir) if source else None
                if nir_png:
                    refl = _bitmap_reflectance(nir_png, raw=True)
                else:
                    value = float(info["mean"])
                    refl = f"{value:.8g} {value:.8g} {value:.8g}"
            elif source:
                # Metals do not have a diffuse NIR channel. Preserve their authored
                # base/specular colour as the single-image target used with metallic=1.
                refl = _bitmap_reflectance(source, raw=False)
            elif node is not None:
                refl = node
            else:
                bc = (canon or {}).get("parameters", {}).get("base_color", {})
                refl = (" ".join(f"{float(v):.4f}" for v in bc["value"])
                        if bc.get("value") is not None else "0 0 0")
        elif opaque is not None:
            outputs = dict(opaque.get("outputs") or {})
            inputs = dict(opaque.get("inputs") or {})
            if channel == "albedo":
                refl = _bitmap_reflectance(outputs["base_color"], raw=False)
            elif channel == "roughness" and inputs.get("roughness"):
                refl = _bitmap_reflectance(inputs["roughness"], raw=True)
            elif channel == "metallic" and outputs.get("metallic"):
                refl = _bitmap_reflectance(outputs["metallic"], raw=True)
            else:
                key = "roughness_constant" if channel == "roughness" else "metallic_constant"
                value = float(inputs.get(key, 0.5 if channel == "roughness" else 0.0))
                refl = f"{value:.8g} {value:.8g} {value:.8g}"
        elif channel == "albedo":
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

    output_dir = Path(scratch_dir) if scratch_dir is not None else scene_xml.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f".prop_{channel}.xml"
    tree.write(out, encoding="unicode")
    return out


def _scene(xml_path: Path):
    import mitsuba as mi
    key = str(xml_path)
    if key not in _SCENE_CACHE:
        _SCENE_CACHE[key] = mi.load_file(key)
    return _SCENE_CACHE[key]


def _first_hit_specular_masks(
    scene_xml: Path,
    shape_ids: Sequence[str],
    shape_idx: np.ndarray,
    valid: np.ndarray,
    *,
    metadata_scene: Optional[Path] = None,
) -> dict[str, np.ndarray]:
    """Return deterministic first-geometric-hit semantic masks for an IR scene."""
    names = ("window_glass", "object_glass", "glass", "mirror")
    empty = {name: np.zeros(valid.shape, dtype=bool) for name in names}
    scene_dir = Path(metadata_scene) if metadata_scene is not None else scene_xml.parent
    contract_path = scene_dir / "ir_scene_domain.json"
    if not contract_path.is_file():
        return empty
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not uses_specular_semantic_masks(str(contract.get("surface_domain") or "")):
        return empty
    semantic_contract = contract.get("specular_semantics") or {}
    reference = semantic_contract.get("ref")
    if reference != "specular_semantic_regions.json":
        raise ValueError("specular-masked property extraction has no semantic-region sidecar")
    payload = json.loads((scene_dir / str(reference)).read_text(encoding="utf-8"))
    if payload.get("mask_semantics") != "primary_ray_first_geometric_hit_v1":
        raise ValueError("unsupported specular semantic-mask policy")
    class_map = payload.get("shape_classes") or {}
    if not isinstance(class_map, Mapping):
        raise ValueError("invalid specular semantic shape-class map")
    shape_lookup = {shape_id: index for index, shape_id in enumerate(shape_ids)}

    def mask_for(shape_set: Sequence[object]) -> np.ndarray:
        indices = [shape_lookup[str(shape_id)] for shape_id in shape_set if str(shape_id) in shape_lookup]
        return valid & np.isin(shape_idx, np.asarray(indices, np.int64)) if indices else np.zeros(valid.shape, dtype=bool)

    window = mask_for(class_map.get("window_glass") or [])
    object_glass = mask_for(class_map.get("object_glass") or [])
    mirror = mask_for(class_map.get("mirror") or [])
    return {
        "window_glass": window,
        "object_glass": object_glass,
        "glass": window | object_glass,
        "mirror": mirror,
    }


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
    nir_band: int = 854,
    nir_dir: Optional[Path] = None,
    scratch_dir: Optional[Path] = None,
    metadata_scene: Optional[str | Path] = None,
) -> dict:
    """Extract property maps for one view via Mitsuba texture eval (correct UVs)."""
    import drjit as dr
    import mitsuba as mi
    mi.set_variant(variant)
    scene_xml = Path(scene_xml)
    metadata_dir = Path(metadata_scene).resolve() if metadata_scene is not None else scene_xml.parent

    scenes = {
        ch: _scene(_stage_readout_xml(
            scene_xml, canonical, ch, nir_band=nir_band, nir_dir=nir_dir, scratch_dir=scratch_dir,
            metadata_scene=metadata_dir,
        ))
        for ch in ("albedo", "nir_albedo", "roughness", "metallic")
    }
    alb_scene = scenes["albedo"]
    shapes = alb_scene.shapes()
    shape_ids = [s.id() for s in shapes]
    shape_bsdf_ids = [s.bsdf().id() if s.bsdf() is not None else "" for s in shapes]
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

    def vec3(values):
        array = np.asarray(values)
        if array.ndim == 2 and array.shape == (3, n):
            array = array.T
        return array.reshape(n, 3)

    def rays(ox, oy):
        pos = mi.Point2f((gx + ox) / width, (gy + oy) / height)
        ray, _ = sensor.sample_ray(0.0, 0.0, pos, mi.Point2f(0.5, 0.5))
        return ray

    S = max(1, int(subpixel))
    depth_sum = np.zeros(n); range_sum = np.zeros(n)
    ng_sum = np.zeros((n, 3)); shn_sum = np.zeros((n, 3))
    tangent_sum = np.zeros((n, 3)); cnt = np.zeros(n)
    acc = {ch: np.zeros((n, 3)) for ch in scenes}
    acc_cnt = np.zeros(n)
    for i in range(S):
        for j in range(S):
            ray = rays((i + 0.5) / S, (j + 0.5) / S)
            si = alb_scene.ray_intersect(ray)
            valid = np.array(si.is_valid())
            tt = np.array(si.t); m = valid & np.isfinite(tt)
            ray_directions = vec3(ray.d)
            axial = _axial_depth(tt, ray_directions, np.asarray(t) - np.asarray(o))
            gn = vec3(si.n); sn = vec3(si.sh_frame.n)
            depth_sum[m] += axial[m]; range_sum[m] += tt[m]
            ng_sum[m] += gn[m]; shn_sum[m] += sn[m]; cnt[m] += 1
            du = vec3(si.dp_du); dv = vec3(si.dp_dv)
            def unit(values):
                length = np.linalg.norm(values, axis=1, keepdims=True)
                return np.where(length > 1e-8, values / np.maximum(length, 1e-8), 0.0)
            nn = unit(gn)
            tangent = unit(du - (du * nn).sum(1, keepdims=True) * nn)
            bitangent = unit(dv - (dv * nn).sum(1, keepdims=True) * nn
                             - (dv * tangent).sum(1, keepdims=True) * tangent)
            fallback = unit(np.cross(nn, tangent))
            bad_b = np.linalg.norm(bitangent, axis=1) <= 1e-8
            bitangent[bad_b] = fallback[bad_b]
            shading = unit(sn)
            tangent_normal = np.stack([
                (shading * tangent).sum(1),
                (shading * bitangent).sum(1),
                (shading * nn).sum(1),
            ], axis=1)
            tangent_sum[m] += tangent_normal[m]
            # eval each readout scene at the SAME rays (geometry identical across readouts)
            for ch, sc in scenes.items():
                sic = sc.ray_intersect(ray)
                val = vec3(sic.bsdf().eval_diffuse_reflectance(sic))
                acc[ch][valid] += val[valid]
            acc_cnt[valid] += 1

    valid = cnt > 0
    depth = np.where(valid, depth_sum / np.maximum(cnt, 1), 0.0)
    ray_range = np.where(valid, range_sum / np.maximum(cnt, 1), 0.0)
    def _norm(v):
        nn = np.linalg.norm(v, axis=1, keepdims=True)
        return np.where(nn > 1e-8, v / np.maximum(nn, 1e-8), 0.0)
    c = np.maximum(acc_cnt, 1)[:, None]
    basec = acc["albedo"] / c
    rough = (acc["roughness"] / c).mean(1)
    metal = (acc["metallic"] / c).mean(1)

    # Stable dataset-wide material/object ids from the compiled XML index.
    si_c = alb_scene.ray_intersect(rays(0.5, 0.5)); valid_c = np.array(si_c.is_valid())
    # On CUDA variants ``SurfaceInteraction3f.shape`` carries a Dr.Jit
    # ShapePtr handle.  Comparing it against Python ``Mesh`` wrappers (or
    # against an element of ``scene.shapes_dr()``) is not a reliable vector
    # pointer comparison: it left every ray at the sentinel value and turned
    # the object/material maps into zero images.  Reinterpret the opaque
    # handle to its stable UInt32 code instead, and map that code back to the
    # XML/top-level shape ordinal on the host.  This also avoids compiling an
    # O(number_of_shapes) select chain for every primary-ray batch.
    pointer_to_shape: dict[int, int] = {}
    for k, shape in enumerate(shapes):
        code_values = np.asarray(
            dr.reinterpret_array_v(mi.UInt32, mi.ShapePtr(shape)), dtype=np.uint32,
        ).reshape(-1)
        if code_values.size != 1:
            raise RuntimeError(f"unexpected ShapePtr code width for {shape.id()!r}: {code_values.size}")
        code = int(code_values[0])
        previous = pointer_to_shape.setdefault(code, k)
        if previous != k:
            raise RuntimeError(
                f"duplicate Mitsuba ShapePtr code {code} for {shapes[previous].id()!r} and {shape.id()!r}"
            )
    hit_codes = np.asarray(
        dr.reinterpret_array_v(mi.UInt32, si_c.shape), dtype=np.uint32,
    ).reshape(-1)
    if hit_codes.size != n:
        raise RuntimeError(f"primary-ray ShapePtr count mismatch: expected {n}, got {hit_codes.size}")
    shape_idx = np.full(n, len(shapes), dtype=np.int32)
    for code, k in pointer_to_shape.items():
        shape_idx[hit_codes == code] = k
    specular_masks = _first_hit_specular_masks(
        scene_xml, shape_ids, shape_idx, valid_c, metadata_scene=metadata_dir,
    )
    index_path = metadata_dir / "xml_scene_index.json"
    index_rows = json.loads(index_path.read_text()).get("shapes", []) if index_path.is_file() else []
    shape_meta = {str(row.get("shape_id")): row for row in index_rows if row.get("shape_id")}
    assembly_path = metadata_dir / "opaque_scene_assembly.json"
    opaque_object_by_bsdf: dict[str, str] = {}
    if assembly_path.is_file():
        assembly = json.loads(assembly_path.read_text())
        opaque_object_by_bsdf = {
            str(row["bsdf_id"]): str(row["object_id"])
            for row in assembly.get("replacements") or []
            if row.get("bsdf_id") and row.get("object_id")
        }
    material_names = sorted(
        {str(row.get("material_id")) for row in index_rows if row.get("material_id")}
        | {f"opaque_unit::{object_id}" for object_id in opaque_object_by_bsdf.values()}
    )
    object_names = sorted(
        {str(row.get("object_id")) for row in index_rows if row.get("object_id")}
        | set(opaque_object_by_bsdf.values())
    )
    material_lookup = {name: idx for idx, name in enumerate(material_names)}
    object_lookup = {name: idx for idx, name in enumerate(object_names)}
    region_id = np.full(n, -1, np.int32)
    object_id = np.full(n, -1, np.int32)
    substitution_path = metadata_dir / "opaque_substitutions_applied.json"
    replacement_units = set()
    if substitution_path.is_file():
        replacement_units = {
            str(row["unit_id"])
            for row in json.loads(substitution_path.read_text()).get("substitutions", [])
            if row.get("applied")
        }
    replacement = np.zeros(n, dtype=bool)
    for k in range(len(shapes)):
        pm = valid_c & (shape_idx == k)
        if not pm.any():
            continue
        meta = shape_meta.get(shape_ids[k], {})
        opaque_oid = opaque_object_by_bsdf.get(shape_bsdf_ids[k])
        oid = str(opaque_oid or meta.get("object_id") or "")
        mid = (
            f"opaque_unit::{opaque_oid}" if opaque_oid
            else str(meta.get("material_id") or shape2mat.get(shape_ids[k]) or "")
        )
        if mid in material_lookup:
            region_id[pm] = material_lookup[mid]
        if oid in object_lookup:
            object_id[pm] = object_lookup[oid]
            replacement[pm] = oid in replacement_units

    def r(a, *sh):
        return a.reshape(height, width, *sh) if sh else a.reshape(height, width)
    return {
        "depth": r(depth.astype(np.float32)),
        "range": r(ray_range.astype(np.float32)),
        "geo_normal": r(_norm(ng_sum).astype(np.float32), 3),
        "sh_normal": r(_norm(shn_sum).astype(np.float32), 3),
        "tangent_normal": r(_norm(tangent_sum).astype(np.float32), 3),
        "valid": r(valid),
        "material_region_id": r(region_id),
        "object_id": r(object_id),
        "replacement_mask": r(replacement),
        "window_glass_mask": r(specular_masks["window_glass"]),
        "object_glass_mask": r(specular_masks["object_glass"]),
        "glass_mask": r(specular_masks["glass"]),
        "mirror_mask": r(specular_masks["mirror"]),
        "base_color": r(basec.astype(np.float32), 3), "base_color_valid": r(valid),
        "nir_albedo": r((acc["nir_albedo"] / c).mean(1).astype(np.float32)),
        "nir_albedo_valid": r(valid),
        "roughness": r(rough.astype(np.float32)), "roughness_valid": r(valid),
        "metallic": r(metal.astype(np.float32)), "metallic_valid": r(valid),
        "region_legend": {idx: name for name, idx in material_lookup.items()},
        "object_legend": {idx: name for name, idx in object_lookup.items()},
    }
