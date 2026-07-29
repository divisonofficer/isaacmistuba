#!/usr/bin/env python3
"""Combine original .blend graph audit with GLB UV coverage and baked PNGs."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

import cv2
import numpy as np
import trimesh
from PIL import Image


CHANNELS = ("albedo", "roughness", "metallic", "normal")
VARYING_STATES = {
    "IMAGE_TEXTURE", "PROCEDURAL_2D", "PROCEDURAL_3D", "VERTEX_ATTRIBUTE",
    "GEOMETRY_DERIVED",
}


def _args():
    p = argparse.ArgumentParser()
    p.add_argument("--audit", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--import-root", required=True)
    p.add_argument("--out", required=True)
    return p.parse_args()


def _source_channel(materials, channel):
    if all(m.get("closure") == "MISSING_MATERIAL" for m in materials):
        return {"state": "ABSENT", "varying": False, "unresolved": False, "states": ["ABSENT"]}
    states, member_states, member_features, constant_values = [], [], [], []
    for material in materials:
        rec = (material.get("channels") or {}).get(channel) or {"state": "UNRESOLVED"}
        states.append(rec["state"])
        for member in rec.get("members", []):
            member_states.append(member.get("state"))
            member_features.extend(member.get("features") or [])
            if "CONSTANT" in (member.get("state") or ""):
                constant_values.append(json.dumps(member.get("value"), sort_keys=True))
    all_states = [x for x in states + member_states if x]
    # Different constants on material slots/closure branches vary spatially at object level.
    varying = (
        any(x in VARYING_STATES for x in all_states)
        or any(x in VARYING_STATES for x in member_features)
        or len(set(constant_values)) > 1
    )
    # MIXED can also mean unresolved closure routing; keep that uncertainty separate.
    unresolved = any(x == "UNRESOLVED" for x in all_states)
    state = states[0] if len(set(states)) == 1 else "MIXED"
    return {"state": state, "varying": varying, "unresolved": unresolved, "states": sorted(set(all_states))}


def _uv_mask(glb_path, width, height):
    mask = np.zeros((height, width), np.uint8)
    scene = trimesh.load(glb_path, force="scene", process=False)
    geometry_triangle_count = sum(len(mesh.faces) for mesh in scene.geometry.values())
    triangle_count = 0
    uv_part_count = 0
    valid_uv_part_count = 0
    for mesh in scene.geometry.values():
        uv = getattr(mesh.visual, "uv", None)
        if uv is None or not len(mesh.faces):
            continue
        uv_part_count += 1
        triangles = np.asarray(uv, dtype=np.float64)[np.asarray(mesh.faces, dtype=np.int64)]
        finite = np.isfinite(triangles).all(axis=(1, 2))
        triangles = triangles[finite]
        triangle_count += len(triangles)
        if not len(triangles):
            continue
        area2 = np.abs(
            (triangles[:, 1, 0] - triangles[:, 0, 0]) * (triangles[:, 2, 1] - triangles[:, 0, 1])
            - (triangles[:, 1, 1] - triangles[:, 0, 1]) * (triangles[:, 2, 0] - triangles[:, 0, 0])
        )
        nondegenerate = area2 > 1e-10
        if np.any(nondegenerate):
            valid_uv_part_count += 1
        triangles = triangles[nondegenerate]
        if not len(triangles):
            continue
        points = np.empty_like(triangles, dtype=np.int32)
        points[:, :, 0] = np.rint(np.clip(triangles[:, :, 0], 0, 1) * (width - 1)).astype(np.int32)
        points[:, :, 1] = np.rint((1 - np.clip(triangles[:, :, 1], 0, 1)) * (height - 1)).astype(np.int32)
        for start in range(0, len(points), 50000):
            cv2.fillPoly(mask, list(points[start:start + 50000]), 255)
    return mask.astype(bool), geometry_triangle_count, triangle_count, uv_part_count, valid_uv_part_count


def _texture_metrics(path, coverage):
    image = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
    if coverage.shape != image.shape[:2]:
        coverage = cv2.resize(coverage.astype(np.uint8), (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    values = image[coverage]
    if not len(values):
        return {"result": "empty_coverage", "covered_pixels": 0}
    p01 = np.percentile(values, 1, axis=0)
    p99 = np.percentile(values, 99, axis=0)
    robust_range = p99 - p01
    if float(np.max(p99)) <= 1.0 / 255.0:
        result = "black"
    elif float(np.max(robust_range)) <= 2.0 / 255.0:
        result = "constant"
    else:
        result = "spatial"
    return {
        "result": result,
        "covered_pixels": int(len(values)),
        "coverage_fraction": float(coverage.mean()),
        "mean": values.mean(axis=0).tolist(),
        "std": values.std(axis=0).tolist(),
        "percentile_01": p01.tolist(),
        "percentile_99": p99.tolist(),
        "robust_range": robust_range.tolist(),
    }


def _manifest_channel(unit, channel):
    key = "base_color" if channel == "albedo" else channel
    return (((unit.get("pbr") or {}).get("channels") or {}).get(key) or {})


def _channel_verdict(source, manifest_rec, metrics):
    mode = manifest_rec.get("mode")
    if source["varying"]:
        if mode != "texture":
            return "varying_source_without_texture"
        if not metrics or metrics.get("result") == "empty_coverage":
            return "unverifiable_missing_glb_uv_coverage"
        if metrics.get("result") in {"black", "constant"}:
            return "linked_bake_collapse"
        return "spatial_bake_candidate"
    if source["unresolved"]:
        return "unresolved_source"
    if mode == "texture":
        if metrics and metrics.get("result") == "spatial":
            return "spatial_texture_without_traced_principled_variation"
        return "unnecessary_flat_texture"
    if mode in {"constant", "not_applicable"}:
        return "valid_constant_or_absent"
    return "missing_resolution"


def _provenance(channel, source, manifest_rec, metrics, exportability_group):
    mode = manifest_rec.get("mode")
    pixel_result = (metrics or {}).get("result")
    if pixel_result == "empty_coverage":
        return "UNVERIFIABLE_EMPTY_GLB"
    if channel == "normal":
        if source["varying"]:
            return "SOURCE_PROJECTED" if pixel_result == "spatial" else "BAKE_COLLAPSE"
        if mode == "texture" and pixel_result == "spatial":
            return "BAKE_DERIVED_GEOMETRY_NORMAL"
        if mode == "texture":
            return "FLAT_OR_ARTIFACT_NORMAL"
        return "SOURCE_ABSENT"
    if source["varying"]:
        if mode != "texture" or pixel_result != "spatial":
            return "BAKE_COLLAPSE"
        if exportability_group in {
            "G3_DISPLACEMENT_DEPENDENT", "G4_TRANSMISSION_GLASS", "G5_NONSTANDARD_OR_LAYERED",
        }:
            return "BAKE_APPROXIMATION"
        return "SOURCE_PROJECTED"
    if source["unresolved"]:
        return "BAKE_APPROXIMATION" if mode == "texture" and pixel_result == "spatial" else "UNRESOLVED"
    if mode == "texture":
        return "CONSTANT_RASTERIZED" if pixel_result in {"black", "constant"} else "BAKE_APPROXIMATION"
    if mode == "constant":
        return "SOURCE_CONSTANT_FACTOR"
    return "SOURCE_ABSENT"


def _assess(obj, has_collapse, glb_geometry_valid, glb_uv_area_valid):
    group = obj["exportability_group"]
    if not glb_geometry_valid:
        raster = four = realtime = "unsupported_empty_glb"
    elif not glb_uv_area_valid:
        raster = four = realtime = "unsupported_degenerate_glb_uv"
    elif has_collapse:
        raster = four = realtime = "unsupported_current_export"
    elif group == "G7_BAKE_FAILURE_OR_INVALID":
        raster = four = realtime = "unsupported"
    elif group == "G4_TRANSMISSION_GLASS":
        raster, four, realtime = "bake_equivalent_for_opaque_terms_only", "severely_lossy", "severely_lossy"
    elif group == "G5_NONSTANDARD_OR_LAYERED":
        raster, four, realtime = "bake_equivalent_candidate", "severely_lossy", "acceptable_approximation_candidate"
    elif group == "G3_DISPLACEMENT_DEPENDENT":
        raster, four, realtime = "bake_equivalent_for_surface_color_only", "severely_lossy", "severely_lossy_without_height_geometry"
    elif group == "G2_BAKEABLE_PROCEDURAL_PBR":
        raster, four, realtime = "bake_equivalent_candidate", "bake_equivalent_candidate", "acceptable_approximation_candidate"
    else:
        raster = four = realtime = "exact_candidate"
    return {
        "raster_bake_feasibility": raster,
        "four_map_fidelity": four,
        "realtime_metallic_roughness": realtime,
        "final_gate": "requires_multiview_render_comparison",
    }


def main():
    args = _args()
    with open(args.audit, encoding="utf-8") as f:
        audit = json.load(f)
    with open(args.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    units = {u["blender_name"]: u for u in manifest["units"]}
    rows = []
    for index, obj in enumerate(x for x in audit["objects"] if x["exporter_renderable"]):
        unit = units[obj["name"]]
        sources = {ch: _source_channel(obj["materials"], ch) for ch in CHANNELS}
        texture_records = {ch: _manifest_channel(unit, ch) for ch in CHANNELS}
        refs = [r.get("ref") for r in texture_records.values() if r.get("mode") == "texture" and r.get("ref")]
        if refs:
            first = np.asarray(Image.open(os.path.join(args.import_root, refs[0])))
            mask_width, mask_height = first.shape[1], first.shape[0]
        else:
            mask_width = mask_height = 512
        coverage, geometry_triangle_count, triangle_count, uv_part_count, valid_uv_part_count = _uv_mask(
            os.path.join(args.import_root, unit["mesh_glb"]), mask_width, mask_height
        )
        channel_results = {}
        for channel in CHANNELS:
            rec = texture_records[channel]
            metrics = None
            if rec.get("mode") == "texture" and rec.get("ref"):
                metrics = _texture_metrics(os.path.join(args.import_root, rec["ref"]), coverage)
            channel_results[channel] = {
                "source": sources[channel], "manifest": rec, "covered_uv_metrics": metrics,
                "verdict": _channel_verdict(sources[channel], rec, metrics),
                "provenance": _provenance(
                    channel, sources[channel], rec, metrics, obj["exportability_group"]
                ),
            }
        collapses = [ch for ch, r in channel_results.items() if r["verdict"] in {
            "linked_bake_collapse", "varying_source_without_texture",
        }]
        bitmask = "".join(ch[0].upper() if sources[ch]["varying"] else "-" for ch in CHANNELS)
        row = {
            "name": obj["name"], "unit_id": unit["id"], "optical_class": unit.get("optical_class"),
            "materials": [m.get("name") for m in obj["materials"]],
            "source_uv_valid": obj["uv"]["valid"], "export_uv_valid": unit["uv"]["valid"],
            "uv_remediation": (
                "smart_uv_generated" if not obj["uv"]["valid"] and geometry_triangle_count > 0
                and (uv_part_count == 0 or valid_uv_part_count == uv_part_count)
                else "attempted_but_invalid" if not obj["uv"]["valid"]
                else "preserved"
            ),
            "glb_uv_triangle_count": triangle_count,
            "glb_geometry_triangle_count": geometry_triangle_count,
            "glb_geometry_valid": geometry_triangle_count > 0,
            "glb_uv_part_count": uv_part_count,
            "glb_valid_uv_part_count": valid_uv_part_count,
            "glb_uv_area_valid": geometry_triangle_count > 0 and (
                uv_part_count == 0 or valid_uv_part_count == uv_part_count
            ),
            "exportability_group": obj["exportability_group"],
            "source_variation_bitmask": bitmask,
            "channels": channel_results,
            "collapse_channels": collapses,
        }
        row["assessment"] = _assess(
            obj, bool(collapses), geometry_triangle_count > 0,
            geometry_triangle_count > 0 and (uv_part_count == 0 or valid_uv_part_count == uv_part_count),
        )
        rows.append(row)
        if (index + 1) % 20 == 0:
            print(f"[covered-uv-audit] {index + 1}/{len(units)}", flush=True)
    source_combos = Counter(r["source_variation_bitmask"] for r in rows)
    verdicts = {ch: Counter(r["channels"][ch]["verdict"] for r in rows) for ch in CHANNELS}
    provenance = {ch: Counter(r["channels"][ch]["provenance"] for r in rows) for ch in CHANNELS}
    assessments = {
        key: Counter(r["assessment"][key] for r in rows)
        for key in ("raster_bake_feasibility", "four_map_fidelity", "realtime_metallic_roughness")
    }
    shader_normal = sum(r["channels"]["normal"]["source"]["varying"] for r in rows)
    baked_normal = sum(r["channels"]["normal"]["manifest"].get("mode") == "texture" for r in rows)
    summary = {
        "unit_count": len(rows),
        "source_uv_invalid_but_export_fixed": sum(
            not r["source_uv_valid"] and r["glb_uv_area_valid"] for r in rows
        ),
        "source_uv_invalid_and_export_still_invalid": sum(
            not r["source_uv_valid"] and not r["glb_uv_area_valid"] for r in rows
        ),
        "empty_glb_units": sum(not r["glb_geometry_valid"] for r in rows),
        "degenerate_glb_uv_units": sum(
            r["glb_geometry_valid"] and not r["glb_uv_area_valid"] for r in rows
        ),
        "source_variation_combinations": dict(sorted(source_combos.items())),
        "channel_verdicts": {k: dict(sorted(v.items())) for k, v in verdicts.items()},
        "channel_provenance": {k: dict(sorted(v.items())) for k, v in provenance.items()},
        "assessment_counts": {k: dict(sorted(v.items())) for k, v in assessments.items()},
        "units_with_linked_bake_collapse": sum(bool(r["collapse_channels"]) for r in rows),
        "shader_normal_varying_units": shader_normal,
        "baked_normal_texture_units": baked_normal,
        "baked_normal_without_shader_channel": sum(
            r["channels"]["normal"]["verdict"] == "spatial_texture_without_traced_principled_variation" for r in rows
        ),
        "acceptance": "BLOCK_STAGE_2_PENDING_FIX_AND_MULTIVIEW_RENDER_COMPARISON",
    }
    result = {"schema": "robomituba.infinigen.covered_uv_pbr_audit.v1", "summary": summary, "objects": rows}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
