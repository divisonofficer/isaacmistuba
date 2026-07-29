#!/usr/bin/env python3
"""Render the fixed spatial-PBR F0-only RGB + polarized close-up A/B experiment."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
for source in ("modules/robomituba_bridge/src", "modules/mitsuba_converter/src"):
    candidate = str(REPO_ROOT / source)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from mitsuba_converter.spatial_pbr import convert_spatial_pbr_textures  # noqa: E402
from mitsuba_converter.spatial_pbr_ab import (  # noqa: E402
    area_light_matrix, assert_scene_pair_invariants, build_scene_xml, load_json,
    load_obj_bounds, lookat_camera, paired_bootstrap, rgb_roi_metrics, roi_metrics,
    screen_space_maps,
    sha256_file,
)

DEFAULT_CONFIG = REPO_ROOT / "configs/experiments/spatial_pbr_ab_2026-07-13.json"
POLAR_MODALITIES = ["polar_rgb_preview", "dop", "aolp", "s1", "s2", "s1_over_s0", "s2_over_s0"]
RGB_MODALITIES = ["rgb"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--assets", nargs="*", default=None, help="object IDs or unambiguous substrings")
    parser.add_argument("--smoke", action="store_true", help="use 256x256/64 spp and fridge+Bed unless --assets is given")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--spp", type=int)
    parser.add_argument("--res", type=int)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_asset_unit(scene: str, object_id: str) -> tuple[Path, dict[str, Any]]:
    manifest = REPO_ROOT / "out/infinigen_imports" / scene / "scene_manifest.json"
    data = load_json(manifest)
    matches = [unit for unit in data.get("units", []) if unit.get("id") == object_id]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {object_id} in {manifest}, got {len(matches)}")
    return manifest, matches[0]


def channel(unit: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    return ((unit.get("pbr") or {}).get("channels") or {}).get(name) or {}


def input_path(scene_dir: Path, unit: Mapping[str, Any], legacy_key: str,
               channel_name: str) -> Path | None:
    value = unit.get(legacy_key)
    if value:
        return (scene_dir / str(value)).resolve()
    descriptor = channel(unit, channel_name)
    if descriptor.get("mode") == "texture" and descriptor.get("ref"):
        return (scene_dir / str(descriptor["ref"])).resolve()
    return None


def constant(unit: Mapping[str, Any], name: str, default: float) -> float:
    descriptor = channel(unit, name)
    value = descriptor.get("value")
    if descriptor.get("mode") == "constant" and isinstance(value, list) and value:
        return float(value[0])
    return float(default)


def prepare_material(asset: Mapping[str, Any], out: Path) -> dict[str, Any]:
    scene = str(asset["scene"]); object_id = str(asset["id"])
    manifest, unit = resolve_asset_unit(scene, object_id)
    scene_dir = manifest.parent
    obj_fallback = (scene_dir / str(unit["mesh_obj"])).resolve()
    glb = (scene_dir / str(unit["mesh_glb"])).resolve() if unit.get("mesh_glb") else None
    obj = obj_fallback
    glb_materialization: dict[str, Any] = {"source": "obj_fallback", "has_uv": False, "has_normal": False}
    if glb is not None and glb.is_file():
        # The manifest OBJ is retained as provenance only: Stage-1 Infinigen
        # OBJ exports can have zero vt/vn, while the sibling GLB is authoritative.
        from mitsuba_converter.glb_texture_adapter import materialize_glb_texture_parts
        materialized = materialize_glb_texture_parts(
            f"out/infinigen_imports/{scene}/meshes/{glb.name}",
            glb_path=glb, repo_root=REPO_ROOT,
            mesh_cache_dir=out / "glb_geometry" / object_id,
            texture_cache_dir=out / "glb_textures" / object_id,
        )
        if materialized.status != "ok" or materialized.combined_obj_path is None:
            raise RuntimeError(f"GLB materialization failed for {object_id}: {materialized.error}")
        obj = Path(materialized.combined_obj_path).resolve()
        glb_materialization = {
            "source": "glb_materialized_obj", "glb": str(glb),
            "cache_obj": str(obj), "has_uv": bool(materialized.has_uv),
            "has_normal": bool(materialized.has_normal),
            "mesh_part_count": int(materialized.mesh_part_count),
            "triangle_count": int(materialized.triangle_count),
        }
        if not materialized.has_uv:
            raise RuntimeError(f"GLB materialization lost UV for {object_id}")
    base = input_path(scene_dir, unit, "baked_albedo", "base_color")
    rough = input_path(scene_dir, unit, "baked_roughness", "roughness")
    metallic = input_path(scene_dir, unit, "baked_metallic", "metallic")
    normal = input_path(scene_dir, unit, "baked_normal", "normal")
    if base is None or not base.is_file() or not obj.is_file():
        raise FileNotFoundError(f"missing OBJ/basecolor for {object_id}: {obj}, {base}")
    maps_dir = out / "asset_maps" / object_id
    ior_dir = REPO_ROOT / "build/mitsuba3-optix7/data/ior"
    record = convert_spatial_pbr_textures(
        object_id=object_id, output_dir=maps_dir, base_color_path=base,
        roughness_path=rough, metallic_path=metallic, normal_path=normal,
        roughness_constant=constant(unit, "roughness", 0.5),
        metallic_constant=constant(unit, "metallic", 0.0),
        ior_dir=ior_dir, write_exr=True,
        provenance={"manifest": str(manifest), "scene_id": scene, "group": asset["group"],
                    "optical_class": unit.get("optical_class")},
    )
    # A requires a raw roughness bitmap even when the source is a scalar constant.
    if rough is None:
        value = int(round(constant(unit, "roughness", 0.5) * 255))
        rough = maps_dir / f"{object_id}_roughness_raw.png"
        Image.new("L", tuple(record["size"]), value).save(rough)
    material = {
        "object_id": object_id, "group": asset["group"], "scene": scene,
        "manifest": manifest, "unit": unit, "obj": obj, "obj_fallback": obj_fallback,
        "glb": glb, "glb_materialization": glb_materialization,
        "obj_parts": [Path(part.obj_path).resolve() for part in getattr(materialized, "mesh_parts", [])]
        if glb is not None and glb_materialization.get("source") == "glb_materialized_obj" else [obj],
        "base_color": Path(record["outputs"]["base_color"]).resolve(),
        "roughness_raw": rough.resolve(), "normal": normal.resolve() if normal else None,
        "alpha": Path(record["outputs"]["alpha"]).resolve(),
        "metallic": Path(record["outputs"]["metallic"]).resolve(),
        "eta": Path(record["outputs"]["eta_exr"]).resolve(),
        "k": Path(record["outputs"]["k_exr"]).resolve(),
        "optical_npz": Path(record["outputs"]["optical_maps_npz"]).resolve(),
        "conductor_index": Path(record["outputs"]["conductor_index"]).resolve(),
        "optical_class": unit.get("optical_class") or "diffuse", "record": record,
    }
    material["input_sha256"] = {
        key: sha256_file(Path(value)) for key, value in {
            "manifest": manifest, "glb": glb, "obj_fallback": obj_fallback,
            "obj": obj, "base_color": base,
            "roughness": rough, "metallic": metallic, "normal": normal,
        }.items() if value is not None and Path(value).is_file()
    }
    return material


def render_uv_aov(scene_xml: Path, camera: np.ndarray, fov: float, res: int,
                  out_dir: Path, variant: str) -> tuple[np.ndarray, np.ndarray]:
    """Render primary-hit UV and depth AOVs once for the shared A/B geometry."""
    import mitsuba as mi
    from mitsuba_converter.multimodal import camera_to_world_to_lookat
    mi.set_variant(variant)
    root = ET.parse(scene_xml).getroot()
    for shape in list(root.findall("./shape")):
        if not shape.attrib.get("id", "").startswith("experiment_object"):
            root.remove(shape)
    obj_shapes = [node for node in root.findall("./shape") if node.attrib.get("id", "").startswith("experiment_object")]
    if not obj_shapes:
        raise RuntimeError(f"experiment object missing in {scene_xml}")
    # UV alignment must be material-independent. Replace the complete A/B BSDF
    # (including normalmap wrappers) with the same neutral diffuse leaf before
    # rendering either AOV scene.
    for obj_shape in obj_shapes:
        for child in list(obj_shape):
            if child.tag in {"bsdf", "ref"}:
                obj_shape.remove(child)
        neutral = ET.SubElement(obj_shape, "bsdf", {"type": "diffuse"})
        ET.SubElement(neutral, "rgb", {"name": "reflectance", "value": "0.5 0.5 0.5"})
    integrator = root.find("./integrator")
    integrator.clear(); integrator.attrib["type"] = "aov"
    ET.SubElement(integrator, "string", {"name": "aovs", "value": "uv:uv,dd:depth"})
    ET.SubElement(integrator, "integrator", {"type": "direct", "name": "img"})
    uv_xml = out_dir / "scene_uv.xml"
    ET.ElementTree(root).write(uv_xml, encoding="utf-8", xml_declaration=True)
    scene = mi.load_file(str(uv_xml))
    origin, target, up = camera_to_world_to_lookat(camera)
    sensor = mi.load_dict({
        "type": "perspective", "fov": float(fov),
        "to_world": mi.ScalarTransform4f.look_at(origin=list(origin), target=list(target), up=list(up)),
        "film": {"type": "hdrfilm", "width": int(res), "height": int(res)},
        "sampler": {"type": "independent", "sample_count": 1},
    })
    image = np.asarray(mi.render(scene, sensor=sensor, spp=1), dtype=np.float32)
    if image.ndim != 3 or image.shape[2] < 6:
        raise RuntimeError(f"unexpected UV AOV shape {image.shape}")
    uv = image[..., -3:-1]
    depth = image[..., -1]
    mask = np.isfinite(depth) & (depth > 0)
    if not np.any(mask):
        raise RuntimeError("empty object mask from UV AOV")
    np.savez_compressed(out_dir / "uv_aov.npz", uv=uv, depth=depth, object_mask=mask)
    return uv, mask


def save_roi_products(out_dir: Path, uv: np.ndarray, mask: np.ndarray,
                      material: Mapping[str, Any]) -> dict[str, np.ndarray]:
    optical = np.load(material["optical_npz"])
    maps = screen_space_maps(uv, mask, {
        "metallic": optical["metallic"], "alpha": optical["alpha"],
        "conductor_index": optical["conductor_index"], "eta": optical["eta"], "k": optical["k"],
    })
    np.savez_compressed(out_dir / "screen_space_maps.npz", uv=uv, **maps)
    for key in ("object_mask", "metal_mask", "dielectric_mask"):
        Image.fromarray(maps[key].astype(np.uint8) * 255, mode="L").save(out_dir / f"{key}.png")
    for key in ("metallic", "alpha"):
        Image.fromarray(np.rint(np.clip(maps[key], 0, 1) * 255).astype(np.uint8), mode="L").save(out_dir / f"{key}.png")
    index = maps["conductor_index"].astype(np.uint8)
    Image.fromarray(np.rint(index * (255 / max(1, int(index.max())))).astype(np.uint8), mode="L").save(out_dir / "conductor_index.png")
    for key in ("eta", "k"):
        value = np.asarray(maps[key], dtype=np.float32)
        scale = max(float(np.quantile(value[mask], 0.99)) if np.any(mask) else 1.0, 1e-6)
        preview = np.rint(np.clip(value / scale, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(preview, mode="RGB").save(out_dir / f"{key}.png")
    return maps


def save_stokes_exrs(render_dir: Path) -> dict[str, np.ndarray]:
    from mitsuba_converter.spatial_pbr import _write_exr
    candidates = list(render_dir.glob("stokes_data.npz")) or list(render_dir.rglob("stokes_data.npz"))
    if not candidates:
        raise FileNotFoundError(f"stokes_data.npz missing under {render_dir}")
    data = np.load(candidates[0])
    result = {key: np.asarray(data[key], dtype=np.float32) for key in data.files}
    for key in ("rgb", "s0", "s1", "s2", "s3"):
        _write_exr(render_dir / f"{key}.exr", result[key])
    preview = list(render_dir.glob("polar_rgb_preview.png")) or list(render_dir.rglob("polar_rgb_preview.png"))
    if preview:
        shutil.copyfile(preview[0], render_dir / "rgb.png")
    result["aolp"] = result.get("aolp", np.mod(0.5 * np.arctan2(result["s2_l"], result["s1_l"]), np.pi))
    return result


def render_branch(xml: Path, camera: np.ndarray, fov: float, res: int, spp: int,
                  out_dir: Path, variant: str) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    from mitsuba_converter.multimodal import RenderConfig, render_modalities
    config = RenderConfig(width=res, height=res, path_spp=spp, polar_spp=spp,
                          aov_spp=1, path_max_depth=8, write_raw_npz=True,
                          use_optix_denoiser=False, use_firefly_clamp=False)
    result = render_modalities(xml, camera, fov, POLAR_MODALITIES, out_dir=out_dir,
                               config=config, variant=variant)
    stokes = save_stokes_exrs(out_dir)
    return stokes, result.to_record()


def render_rgb_branch(xml: Path, camera: np.ndarray, fov: float, res: int, spp: int,
                      out_dir: Path, variant: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Render an independent non-polarized RGB pass for one A/B branch."""
    from mitsuba_converter.multimodal import RenderConfig, render_modalities
    config = RenderConfig(width=res, height=res, path_spp=spp, polar_spp=spp,
                          aov_spp=1, path_max_depth=8, write_raw_npz=True,
                          use_optix_denoiser=False, use_firefly_clamp=False)
    result = render_modalities(xml, camera, fov, RGB_MODALITIES, out_dir=out_dir,
                               config=config, variant=variant)
    if "rgb" not in result.results:
        raise RuntimeError(f"RGB result missing for {xml}")
    return np.asarray(result.results["rgb"].array, dtype=np.float32), result.to_record()


def montage(path: Path, left: Path, right: Path, title: str) -> None:
    a = Image.open(left).convert("RGB"); b = Image.open(right).convert("RGB")
    aa = np.asarray(a, dtype=np.int16); bb = np.asarray(b, dtype=np.int16)
    diff = np.clip(np.abs(aa - bb) * 3, 0, 255).astype(np.uint8)
    pad = 28; canvas = Image.new("RGB", (a.width * 3, a.height + pad), "white")
    canvas.paste(a, (0, pad)); canvas.paste(b, (a.width, pad)); canvas.paste(Image.fromarray(diff), (a.width * 2, pad))
    draw = ImageDraw.Draw(canvas); draw.text((4, 6), f"{title}   A analytic | B spatial F0 | 3x abs diff", fill="black")
    canvas.save(path)


def contact_sheet(path: Path, panels: list[tuple[str, Path]]) -> None:
    existing = [(label, Image.open(image).convert("RGB")) for label, image in panels if image.is_file()]
    if not existing:
        return
    # Report-facing sheets deliberately keep each condition large. The previous
    # 320px two-column sheet made 256px renders occupy a tiny strip with large
    # unused vertical cells when embedded in the HTML report.
    thumb = 640; label_h = 28; cols = min(2, len(existing)); rows = (len(existing) + cols - 1) // cols
    resized: list[tuple[str, Image.Image]] = []
    for label, image in existing:
        fitted = image.copy(); fitted.thumbnail((thumb, thumb))
        resized.append((label, fitted))
    row_heights = [max(resized[i][1].height for i in range(row * cols, min((row + 1) * cols, len(resized)))) + label_h
                   for row in range(rows)]
    canvas = Image.new("RGB", (cols * thumb, sum(row_heights)), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (label, fitted) in enumerate(resized):
        row = index // cols; x = (index % cols) * thumb; y = sum(row_heights[:row])
        canvas.paste(fitted, (x + (thumb - fitted.width) // 2, y + label_h))
        draw.text((x + 4, y + 5), label, fill="black")
    canvas.save(path)


_POLAR_DIAGNOSTIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("DoLP (DoP)", "dop_red_black_colorbar.png"),
    ("AoLP", "aolp_rainbow_colorbar.png"),
    ("S1 raw", "s1_bwr_colorbar.png"),
    ("S2 raw", "s2_bwr_colorbar.png"),
    ("S1/S0", "s1_over_s0_bwr_colorbar.png"),
    ("S2/S0", "s2_over_s0_bwr_colorbar.png"),
)


def polar_diagnostic_sheet(path: Path, pair_dir: Path, title: str) -> None:
    """Compose A/B polarization fields with their native fixed colorbars.

    The renderer already writes each field together with its colorbar.  Keeping
    those panels intact is important: raw S1/S2 use per-frame signed scales,
    while S1/S0 and S2/S0 use the fixed [-1, 1] scale.  This sheet therefore
    places the A and B products side by side instead of re-normalizing them.
    """
    panels: list[tuple[str, Image.Image, Image.Image]] = []
    for label, filename in _POLAR_DIAGNOSTIC_FIELDS:
        a_path = pair_dir / "A" / filename
        b_path = pair_dir / "B" / filename
        if not a_path.is_file() or not b_path.is_file():
            continue
        panels.append((label, Image.open(a_path).convert("RGB"), Image.open(b_path).convert("RGB")))
    if not panels:
        return
    width = max(max(a.width, b.width) for _, a, b in panels)
    label_w = 78
    gap = 10
    header_h = 34
    row_h = max(max(a.height, b.height) for _, a, b in panels) + 8
    canvas = Image.new("RGB", (label_w + width * 2 + gap * 2, header_h + row_h * len(panels)), "#111827")
    draw = ImageDraw.Draw(canvas)
    draw.text((6, 8), title, fill="white")
    draw.text((label_w, 8), "A · analytic", fill="white")
    draw.text((label_w + width + gap, 8), "B · spatial F0", fill="white")
    for index, (label, a, b) in enumerate(panels):
        y = header_h + index * row_h
        draw.text((6, y + 8), label, fill="white")
        canvas.paste(a, (label_w, y))
        canvas.paste(b, (label_w + width + gap, y))
    canvas.save(path)


def polar_diagnostic_contact_sheet(path: Path, panels: list[tuple[str, Path]]) -> None:
    """Tile the four view/light diagnostic sheets without shrinking each field."""
    existing = [(label, Image.open(image).convert("RGB")) for label, image in panels if image.is_file()]
    if not existing:
        return
    cols = min(2, len(existing))
    gap = 18
    cell_w = max(image.width for _, image in existing)
    cell_h = max(image.height for _, image in existing)
    rows = (len(existing) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell_w + (cols - 1) * gap, rows * cell_h + (rows - 1) * gap), "#111827")
    for index, (label, image) in enumerate(existing):
        row, col = divmod(index, cols)
        x = col * (cell_w + gap)
        y = row * (cell_h + gap)
        canvas.paste(image, (x, y))
    canvas.save(path)


def aggregate(rows: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    output: dict[str, Any] = {"pair_count": len(rows), "groups": {}}
    metric_names = ["rgb_relative_mae", "delta_dolp_mean", "delta_dolp_p95",
                    "delta_dolp_gt_005_fraction", "weighted_aolp_distance_rad",
                    "s1_over_s0_mae", "s2_over_s0_mae"]
    for group in ("positive", "negative"):
        group_rows = [r for r in rows if r["group"] == group]
        output["groups"][group] = {}
        for roi in ("object", "metal", "dielectric"):
            output["groups"][group][roi] = {
                metric: paired_bootstrap([r["metrics"][roi].get(metric, np.nan) for r in group_rows], samples=samples)
                for metric in metric_names
            }
    return output


def aggregate_rgb(rows: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    output: dict[str, Any] = {"pair_count": len(rows), "groups": {}}
    metric_names = ["linear_rgb_mae", "linear_rgb_relative_mae", "linear_rgb_p95"]
    for group in ("positive", "negative"):
        group_rows = [r for r in rows if r["group"] == group]
        output["groups"][group] = {}
        for roi in ("object", "metal", "dielectric"):
            output["groups"][group][roi] = {
                metric: paired_bootstrap([r.get("rgb_metrics", {}).get(roi, {}).get(metric, np.nan) for r in group_rows], samples=samples)
                for metric in metric_names
            }
    return output


def main() -> int:
    args = parse_args(); config = load_json(args.config)
    out = (args.out or Path(config["output"])); out = out if out.is_absolute() else REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    profile = config["smoke" if args.smoke else "final"]
    res = int(args.res or profile["resolution"]); spp = int(args.spp or profile["spp"])
    assets = list(config["assets"])
    if args.assets:
        selected = []
        for token in args.assets:
            hits = [asset for asset in assets if token in asset["id"]]
            if len(hits) != 1:
                raise SystemExit(f"--assets token {token!r} matched {len(hits)} assets")
            selected.append(hits[0])
        assets = selected
    elif args.smoke:
        assets = [assets[0], next(asset for asset in assets if asset["id"].startswith("BedFactory"))]
    state_path = out / "resume_manifest.json"
    state = load_json(state_path) if args.resume and state_path.is_file() else {"schema": config["schema"], "pairs": {}}
    build_conf = REPO_ROOT / "build/mitsuba3-optix7/mitsuba.conf"
    experiment = {"config": str(args.config.resolve()), "config_sha256": sha256_file(args.config),
                  "variant": config["variant"], "rgb_variant": config.get("rgb_variant", "cuda_ad_spectral"),
                  "render_modes": ["rgb", "polarized"], "resolution": res, "spp": spp, "seed": config["seed"],
                  "mitsuba_build": {"root": str(REPO_ROOT / "build/mitsuba3-optix7"),
                                    "pythonpath": os.environ.get("PYTHONPATH"),
                                    "mitsuba_conf_sha256": sha256_file(build_conf) if build_conf.is_file() else None},
                  "assets": assets, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    write_json(out / "experiment_manifest.json", experiment)
    rows: list[dict[str, Any]] = []
    for asset in assets:
        material = prepare_material(asset, out)
        bounds_rows = [load_obj_bounds(path) for path in material.get("obj_parts", [material["obj"]])]
        bounds_min = np.min(np.stack([row[0] for row in bounds_rows]), axis=0)
        bounds_max = np.max(np.stack([row[1] for row in bounds_rows]), axis=0)
        center = (bounds_min + bounds_max) * 0.5
        radius = float(np.linalg.norm(bounds_max - bounds_min) * 0.5)
        for view_name, view_angle in config["views"].items():
            camera, origin = lookat_camera(center, radius, azimuth_deg=float(view_angle),
                                           fov_deg=float(config["fov_deg"]), frame_fill=float(config["frame_fill"]))
            for light_name, light_angle in config["lights"].items():
                condition = f"{view_name}__{light_name}"; pair_key = f"{asset['id']}::{condition}"
                pair_dir = out / asset["id"] / condition; pair_dir.mkdir(parents=True, exist_ok=True)
                if args.resume and state["pairs"].get(pair_key, {}).get("status") == "complete" and (pair_dir / "metrics.json").is_file():
                    resumed_row = load_json(pair_dir / "metrics.json")
                    resumed_row.setdefault("polar_diagnostics", str(pair_dir / "polar_diagnostics.png"))
                    write_json(pair_dir / "metrics.json", resumed_row)
                    rows.append(resumed_row); print(f"[resume] {pair_key}"); continue
                state["pairs"][pair_key] = {"status": "running", "updated_at": time.time()}; write_json(state_path, state)
                try:
                    light = area_light_matrix(center, origin, radius, azimuth_deg=float(light_angle),
                                              elevation_deg=float(config["light_elevation_deg"]),
                                              distance_radii=float(config["light_distance_radii"]),
                                              half_size_radii=float(config["light_half_size_radii"]))
                    summaries = {}
                    for branch in ("A", "B"):
                        branch_dir = pair_dir / branch; branch_dir.mkdir(exist_ok=True)
                        summaries[branch] = build_scene_xml(
                            path=branch_dir / "scene.xml", branch=branch, obj_path=material["obj"], material=material,
                            camera_to_world=camera, light_to_world=light, bounds_min=bounds_min, bounds_max=bounds_max,
                            resolution=res, spp=spp, fov_deg=float(config["fov_deg"]),
                            radiance=float(config["light_radiance"]), seed=int(config["seed"]),
                        )
                    invariants = assert_scene_pair_invariants(pair_dir / "A/scene.xml", pair_dir / "B/scene.xml")
                    uv, object_mask = render_uv_aov(pair_dir / "A/scene.xml", camera, float(config["fov_deg"]),
                                                    res, pair_dir, config["variant"])
                    maps = save_roi_products(pair_dir, uv, object_mask, material)
                    rgb_a, rgb_record_a = render_rgb_branch(
                        pair_dir / "A/scene.xml", camera, float(config["fov_deg"]),
                        res, spp, pair_dir / "A/rgb", config.get("rgb_variant", "cuda_ad_spectral"),
                    )
                    rgb_b, rgb_record_b = render_rgb_branch(
                        pair_dir / "B/scene.xml", camera, float(config["fov_deg"]),
                        res, spp, pair_dir / "B/rgb", config.get("rgb_variant", "cuda_ad_spectral"),
                    )
                    stokes_a, record_a = render_branch(pair_dir / "A/scene.xml", camera, float(config["fov_deg"]),
                                                       res, spp, pair_dir / "A", config["variant"])
                    stokes_b, record_b = render_branch(pair_dir / "B/scene.xml", camera, float(config["fov_deg"]),
                                                       res, spp, pair_dir / "B", config["variant"])
                    # The plan calls for one UV AOV render. A/B geometry invariants above make
                    # this AOV common to both branches; material-independent neutral staging
                    # avoids stochastic edge-sample disagreement from two redundant renders.
                    np.savez_compressed(pair_dir / "B/uv_aov.npz", uv=uv, object_mask=object_mask)
                    valid = object_mask
                    metrics = {
                        "object": roi_metrics(stokes_a, stokes_b, valid),
                        "metal": roi_metrics(stokes_a, stokes_b, valid & maps["metal_mask"]),
                        "dielectric": roi_metrics(stokes_a, stokes_b, valid & maps["dielectric_mask"]),
                    }
                    rgb_metrics = {
                        "object": rgb_roi_metrics(rgb_a, rgb_b, valid),
                        "metal": rgb_roi_metrics(rgb_a, rgb_b, valid & maps["metal_mask"]),
                        "dielectric": rgb_roi_metrics(rgb_a, rgb_b, valid & maps["dielectric_mask"]),
                    }
                    row = {"asset": asset["id"], "group": asset["group"], "condition": condition,
                           "metrics": metrics, "rgb_metrics": rgb_metrics,
                           "invariants": invariants, "bsdf": summaries,
                           "map_stats": material["record"]["stats"], "camera_to_world": camera.tolist(),
                           "light_to_world": light.tolist(), "seed": config["seed"], "resolution": res, "spp": spp,
                           "input_sha256": material["input_sha256"],
                           "polar_diagnostics": str(pair_dir / "polar_diagnostics.png"),
                           "render_records": {
                               "polarized": {"A": record_a, "B": record_b},
                               "rgb": {"A": rgb_record_a, "B": rgb_record_b},
                           }}
                    write_json(pair_dir / "metrics.json", row); rows.append(row)
                    montage(pair_dir / "polar_comparison.png", pair_dir / "A/rgb.png", pair_dir / "B/rgb.png", f"{pair_key} polar")
                    montage(pair_dir / "rgb_comparison.png", pair_dir / "A/rgb/rgb.png", pair_dir / "B/rgb/rgb.png", f"{pair_key} RGB")
                    # Keep the historical filename as the polarized comparison.
                    shutil.copyfile(pair_dir / "polar_comparison.png", pair_dir / "comparison.png")
                    state["pairs"][pair_key] = {"status": "complete", "updated_at": time.time(),
                                                "metrics": str(pair_dir / "metrics.json")}
                    print(f"[complete] {pair_key}")
                except Exception as exc:
                    state["pairs"][pair_key] = {"status": "failed", "updated_at": time.time(), "error": repr(exc)}
                    write_json(state_path, state); print(f"[failed] {pair_key}: {exc}", file=sys.stderr)
                    continue
                write_json(state_path, state)
        polar_panels = [(row["condition"], out / row["asset"] / row["condition"] / "polar_comparison.png")
                        for row in rows if row["asset"] == asset["id"]]
        rgb_panels = [(row["condition"], out / row["asset"] / row["condition"] / "rgb_comparison.png")
                      for row in rows if row["asset"] == asset["id"]]
        polar_diagnostic_panels: list[tuple[str, Path]] = []
        for row in rows:
            if row["asset"] != asset["id"]:
                continue
            pair_dir = out / row["asset"] / row["condition"]
            diagnostic_path = pair_dir / "polar_diagnostics.png"
            polar_diagnostic_sheet(diagnostic_path, pair_dir, row["condition"])
            polar_diagnostic_panels.append((row["condition"], diagnostic_path))
        contact_sheet(out / asset["id"] / "polar_contact_sheet.png", polar_panels)
        contact_sheet(out / asset["id"] / "rgb_contact_sheet.png", rgb_panels)
        contact_sheet(out / asset["id"] / "contact_sheet.png", polar_panels)
        polar_diagnostic_contact_sheet(out / asset["id"] / "polar_diagnostics_contact_sheet.png", polar_diagnostic_panels)
    summary = aggregate(rows, int(config.get("bootstrap_samples", 2000)))
    summary["rgb"] = aggregate_rgb(rows, int(config.get("bootstrap_samples", 2000)))
    summary["expected_pairs"] = len(assets) * len(config["views"]) * len(config["lights"])
    summary["expected_renders"] = summary["expected_pairs"] * 4
    summary["expected_render_modes"] = ["rgb_A", "rgb_B", "polarized_A", "polarized_B"]
    summary["complete"] = len(rows) == summary["expected_pairs"]
    write_json(out / "metrics.json", {"summary": summary, "pairs": rows})
    contact_sheet(out / "polar_contact_sheet.png", [
        (asset["id"], out / asset["id"] / "contact_sheet.png") for asset in assets
    ])
    contact_sheet(out / "rgb_contact_sheet.png", [
        (asset["id"], out / asset["id"] / "rgb_contact_sheet.png") for asset in assets
    ])
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle); writer.writerow(["asset", "group", "condition", "roi", "pixels", "rgb_relative_mae", "delta_dolp_mean", "weighted_aolp_distance_rad", "rgb_pass_mae", "rgb_pass_relative_mae"])
        for row in rows:
            for roi, metrics in row["metrics"].items():
                rgb_metrics = row.get("rgb_metrics", {}).get(roi, {})
                writer.writerow([row["asset"], row["group"], row["condition"], roi, metrics.get("pixels", 0),
                                 metrics.get("rgb_relative_mae"), metrics.get("delta_dolp_mean"), metrics.get("weighted_aolp_distance_rad"),
                                 rgb_metrics.get("linear_rgb_mae"), rgb_metrics.get("linear_rgb_relative_mae")])
    print(json.dumps(summary, indent=2)); return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
