#!/usr/bin/env python3
"""Render the Blender 4.2 opaque-Principled RGB/active-NIR dataset.

One persistent Blender/Cycles process is pinned to each GPU.  Workers claim the
next frame after every completion; chunks are neither a scheduling nor storage
unit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import random
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "navigation_dataset", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from navigation_dataset.ir_principled import (  # noqa: E402
    MATERIAL_CONTRACT_SCHEMA, MATERIAL_CONTRACT_VERSION, STAGE2_COMPILER_VERSION, stable_json_digest,
    validate_metallic_contract,
)
from robomituba_bridge.camera_pose import resolve_viewpoint_pose  # noqa: E402
from mitsuba_converter.ir_render_plan import (  # noqa: E402
    CONTENT_PLAN_SCHEMA,
    ILLUMINATION_PLAN_SCHEMA,
    ILLUMINATION_REFERENCE_PLAN_SCHEMA,
    PLAN_SCHEMA,
    stable_digest as render_plan_digest,
)


BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
WORKER_SCRIPT = REPO_ROOT / "tools" / "infinigen" / "blender_render_ir_principled_worker.py"
QUEUE_SCHEMA = "robomituba.ir_principled_rolling_queue.v1"
QUEUE_COMPILER_VERSION = "ir-principled-rolling-render-v14-diffuse-transport-v3"
DATASET_SCHEMA = "robomituba.ir_principled_dataset.v3"
OVERVIEW_SCHEMA = "robomituba.ir_scene_overview.v1"
OVERVIEW_COMPILER_VERSION = "ir-scene-overview-v2"
# One-time compatibility bridge for the binary-AOV/non-finite-pixel repair.  The
# render equations and frame plan did not change, so completed frames from this
# worker remain valid.  No other worker transition is accepted implicitly.
COMPATIBLE_PREVIOUS_WORKER_SHA256 = frozenset({
    "ffc32d5ce1c97a2ef2772ae0f426c64fa6e181db775d0bea2fa066a753c1267e",
    # Worker immediately before the passive-NIR extension.  Keeping this
    # explicit lets legacy queues resume without changing their fingerprint.
    "9a524bb3336dad895abfcfab4398064c9a300a202efad05477eba6d524a8dfc4",
})
REQUIRED_MODALITIES = {
    "rgb", "nir_active", "base_color_rgb", "base_color_nir", "roughness", "metallic", "metallic_family_id",
    "metal_coverage_mask", "exposed_metal_mask",
    "normal_geometry_world", "normal_shading_world", "depth", "range", "object_id", "material_id",
    "gt_defined_mask", "source_valid_mask", "replacement_mask", "fallback_mask", "remediated_pbr_mask",
    "train_pbr_valid_mask", "pbr_provenance_class", "primary_eval_valid_mask",
    "diffuse_transport_rgb", "diffuse_transport_nir",
    "diffuse_component_rgb", "diffuse_component_nir",
    "diffuse_reflectance_rgb", "diffuse_reflectance_nir",
    "diffuse_transport_valid_rgb", "diffuse_transport_valid_nir",
}
PASSIVE_NIR_MODALITIES = {"nir_passive", "nir_active_minus_passive"}
# These fields describe publication/readiness, not the render identity.  They
# are written only after every indexed frame has both passive-NIR sidecars and
# therefore must not change a dataset fingerprint when a queue is resumed.
NIR_PASSIVE_READINESS_KEYS = {
    "nir_passive_enabled",
    "nir_passive_contract",
}
MASK_MODALITIES = {
    "gt_defined_mask", "source_valid_mask", "replacement_mask", "fallback_mask", "remediated_pbr_mask", "train_pbr_valid_mask",
    "metal_coverage_mask", "exposed_metal_mask",
    "primary_eval_valid_mask", "diffuse_transport_valid_rgb", "diffuse_transport_valid_nir",
}
_REQUIRED_EFFECTIVE_INPUTS = frozenset({
    "base_color_rgb", "base_color_nir", "roughness", "metallic",
    "normal_geometry_world", "normal_shading_world",
})


def _validate_prepared_contract(contract: dict) -> None:
    """Reject v1 or incomplete Stage-2 scenes before any GPU worker starts."""
    if (
        contract.get("schema") != MATERIAL_CONTRACT_SCHEMA
        or contract.get("contract_version") != MATERIAL_CONTRACT_VERSION
    ):
        raise RuntimeError("prepared Stage 2 does not implement the required material contract")
    if contract.get("compiler_version") != STAGE2_COMPILER_VERSION:
        raise RuntimeError("prepared Stage 2 was built with an incompatible compiler version")
    records = contract.get("materials")
    if not isinstance(records, list) or not records or not isinstance(contract.get("aov_semantics"), dict):
        raise RuntimeError("prepared Stage 2 lacks the v2 texture-accurate PBR GT audit")
    if any(set((record.get("effective_inputs") or {})) != _REQUIRED_EFFECTIVE_INPUTS for record in records):
        raise RuntimeError("prepared Stage 2 lacks the v2 texture-accurate PBR GT audit")
    invalid = []
    for record in records:
        valid, failures = validate_metallic_contract(record.get("metallic_contract"))
        if not valid:
            invalid.append(f"{record.get('material_id', '?')}:{','.join(failures)}")
    if invalid:
        raise RuntimeError(
            "prepared Stage 2 lacks valid MetallicContractV2 records: " + "; ".join(invalid[:8])
        )
    required_aovs = {
        "metallic", "metallic_family_id", "metal_coverage_mask", "exposed_metal_mask",
    }
    if not required_aovs <= set(contract.get("aov_semantics") or {}):
        raise RuntimeError("prepared Stage 2 lacks the required metallic supervision AOVs")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True, help="OpticalNav scene containing viewpoint_graph.json")
    parser.add_argument("--prepared-scene-dir", type=Path, required=True)
    parser.add_argument("--overview-proxy-dir", type=Path,
                        help="verified pipeline overview proxy; copied into this dataset output")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--viewpoints", help="optional comma-separated node@heading subset")
    parser.add_argument("--frame-plan", type=Path, help="immutable IR camera-pose and lighting plan")
    parser.add_argument("--width", type=int, default=684)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--eye-height", type=float, default=1.2)
    parser.add_argument("--target-height", type=float, default=1.08)
    parser.add_argument("--rgb-spp", type=int, default=2000)
    parser.add_argument("--nir-spp", type=int, default=2000)
    parser.add_argument("--max-bounces", type=int, default=8)
    parser.add_argument("--gpu-indices", default="0,1,2,3")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--gpu-allocation-file", type=Path,
                        help="atomic controller target; workers scale without changing the dataset fingerprint")
    parser.add_argument("--gpu-state-file", type=Path,
                        help="atomic worker lifecycle state consumed by the controller")
    parser.add_argument("--device", choices=("OPTIX", "CUDA"), default="OPTIX")
    parser.add_argument("--shuffle-seed", type=int, default=20260812)
    parser.add_argument("--render-seed", type=int, default=20260812)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--retry-limit", type=int, default=3)
    parser.add_argument("--qc-components", action="store_true")
    nir_group = parser.add_mutually_exclusive_group()
    nir_group.add_argument("--nir-passive", dest="nir_passive", action="store_true",
                           help="render flash-off passive NIR and active-minus-passive sidecar (default for new datasets)")
    nir_group.add_argument("--no-nir-passive", dest="nir_passive", action="store_false",
                           help="keep the legacy active-only observation contract when resuming an old job")
    # ``None`` lets main distinguish a new output root from an existing
    # active-only dataset.  New direct CLI invocations therefore get the same
    # passive-NIR default as Control Center submissions without changing the
    # fingerprint or resume semantics of legacy outputs.
    parser.set_defaults(nir_passive=None)
    parser.add_argument("--nir-formula", choices=("primary", "luminance_matched_v1"), default="primary")
    parser.add_argument("--flash-energy-scale", type=float, default=1.0)
    parser.add_argument("--ambient-fill-energy-scale", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose-blender", action="store_true")
    parser.add_argument("--compatible-worker-resume", action="store_true",
                        help="reuse frames from the explicitly allow-listed pre-contract-fix worker")
    parser.add_argument("--adopt-compatible-plan", type=Path,
                        help="archived legacy frame plan whose exact matching frames may be adopted")
    parser.add_argument("--adopt-compatible-config", type=Path,
                        help="archived legacy dataset config paired with --adopt-compatible-plan")
    parser.add_argument("--adopt-existing-rows", action="store_true",
                        help="re-attest exact existing frame rows using strict row/task checks when a legacy config was lost")
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_dataset_fingerprint(out: Path, config: dict, *, compatible_resume: bool) -> tuple[str, dict]:
    # Passive readiness is a terminal publication bit.  It is intentionally
    # excluded from the render identity so adding the final contract marker
    # cannot invalidate already rendered rows on a later resume.
    candidate = stable_json_digest({
        key: value for key, value in config.items()
        if key not in NIR_PASSIVE_READINESS_KEYS
    })
    config_path = out / "dataset_config.json"
    if not compatible_resume or not config_path.is_file():
        return candidate, config
    try:
        previous = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return candidate, config
    previous_worker = str(previous.get("worker_sha256") or "")
    previous_fingerprint = str(previous.get("dataset_fingerprint") or "")
    ignored = {"worker_sha256", "dataset_fingerprint", "compatible_resume_worker_sha256", *NIR_PASSIVE_READINESS_KEYS}
    semantic_previous = {key: value for key, value in previous.items() if key not in ignored}
    semantic_current = {key: value for key, value in config.items() if key not in ignored}
    if (
        previous_worker not in COMPATIBLE_PREVIOUS_WORKER_SHA256
        or not previous_fingerprint
        or semantic_previous != semantic_current
    ):
        return candidate, config
    stored = dict(config)
    stored["worker_sha256"] = previous_worker
    stored["compatible_resume_worker_sha256"] = config["worker_sha256"]
    print(
        f"[ir-principled-queue] compatible worker resume: preserving fingerprint "
        f"{previous_fingerprint[:16]}", flush=True,
    )
    return previous_fingerprint, stored


def _desired_gpu_indices(path: Path | None, allowed: list[int], fallback: list[int]) -> list[int]:
    """Read a controller allocation without ever escaping the launch allow-list."""
    if path is None:
        return [gpu for gpu in fallback if gpu in allowed]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        desired = sorted({int(value) for value in payload.get("desired_gpu_indices") or []})
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []
    return [gpu for gpu in desired if gpu in allowed]


def _allocation_state(desired: list[int], active: dict[int, Any], pending_count: int) -> str:
    """Small durable state used by the controller to distinguish wait from work."""
    if pending_count <= 0:
        return "complete"
    if active:
        return "running"
    if desired:
        return "starting"
    return "waiting_gpu"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def _origin_offset(scene_dir: Path) -> tuple[float, float, float]:
    path = scene_dir / "authoring_map.json"
    if not path.is_file():
        return (0.0, 0.0, 0.0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = (payload.get("metadata") or {}).get("origin_offset") or (0.0, 0.0, 0.0)
    values = list(values)
    while len(values) < 3:
        values.append(0.0)
    return tuple(float(v) for v in values[:3])


def _frame_specs(graph: dict, subset: str | None, seed: int) -> list[tuple[str, float, dict | None]]:
    nodes = {str(node["node_id"]): node for node in graph["nodes"]}
    if subset:
        result = []
        for spec in subset.split(","):
            node_id, sep, yaw = spec.strip().partition("@")
            if not sep or node_id not in nodes:
                raise ValueError(f"invalid viewpoint specification: {spec!r}")
            result.append((node_id, float(yaw), None))
        return result
    result = [
        (str(node["node_id"]), float(heading["yaw_deg"]), None)
        for node in graph["nodes"] for heading in node.get("headings") or []
    ]
    random.Random(int(seed)).shuffle(result)
    return result


def _plan_specs(graph: dict, plan: dict) -> list[tuple[str, float, dict]]:
    if plan.get("schema") not in {
        PLAN_SCHEMA,
        CONTENT_PLAN_SCHEMA,
        ILLUMINATION_PLAN_SCHEMA,
        ILLUMINATION_REFERENCE_PLAN_SCHEMA,
    }:
        raise ValueError("frame plan schema is not supported")
    nodes = {str(node["node_id"]): node for node in graph.get("nodes") or []}
    result = []
    seen: set[tuple[str, float, str, str]] = set()
    for group in plan.get("groups") or []:
        lighting = dict(group.get("lighting") or {})
        if not lighting.get("id") or not lighting.get("recipe_digest"):
            raise ValueError("frame plan group lacks canonical lighting recipe")
        capture_group_id = str(group.get("capture_group_id") or "")
        if not capture_group_id:
            raise ValueError("frame plan group lacks capture_group_id")
        for pose in group.get("poses") or []:
            node_id, yaw = str(pose.get("viewpoint_id") or ""), float(pose.get("heading_deg", 0.0))
            anchor_id = str(pose.get("anchor_id") or "")
            key = (node_id, yaw, str(lighting.get("id") or ""), anchor_id)
            if node_id not in nodes or key in seen:
                raise ValueError("frame plan has an unknown or duplicate pose")
            seen.add(key)
            result.append((node_id, yaw, {"id": lighting["id"], "recipe": lighting,
                                          "recipe_digest": lighting["recipe_digest"],
                                          "capture_group_id": capture_group_id,
                                          "render_plan_id": plan["render_plan_id"],
                                          "render_plan_digest": plan["render_plan_digest"],
                                          "capture_kind": pose.get("capture_kind", "single"),
                                          "pair_id": pose.get("pair_id"),
                                          "pair_member_index": pose.get("pair_member_index"),
                                          "anchor_id": anchor_id or None,
                                          "camera_set_ids": list(pose.get("camera_set_ids") or []),
                                          "camera_target_height_m": pose.get("target_height_m")}))
    if not result:
        raise ValueError("frame plan contains no poses")
    return result


def _task(node: dict, yaw: float, lighting: dict | None, args: argparse.Namespace, offset, fingerprint: str, pbr_gt_contract_digest: str, external_lighting_available: bool) -> dict:
    target_height = args.target_height
    if lighting and lighting.get("camera_target_height_m") is not None:
        target_height = float(lighting["camera_target_height_m"])
    pose = resolve_viewpoint_pose(
        node["position"], yaw, eye_height_m=args.eye_height,
        target_height_m=target_height, origin_offset=offset,
    )
    frame_id = f"{node['node_id']}__h_{int(round(yaw)) % 360:03d}"
    if lighting and lighting.get("anchor_id"):
        anchor_token = hashlib.sha256(str(lighting["anchor_id"]).encode("utf-8")).hexdigest()[:8]
        frame_id += f"__a_{anchor_token}"
    if lighting:
        frame_id += f"__l_{lighting['id']}"
    task = {
        "frame_id": frame_id, "viewpoint_id": str(node["node_id"]), "heading_deg": float(yaw),
        "camera_to_world_blender": [list(row) for row in pose.camera_to_world_blender],
        "camera": pose.provenance(), "dataset_fingerprint": fingerprint,
        "pbr_gt_contract_digest": pbr_gt_contract_digest,
        "external_lighting_available": bool(external_lighting_available),
        "width": args.width, "height": args.height, "fov_deg": args.fov,
    }
    if lighting:
        task["lighting"] = dict(lighting)
        task["capture_kind"] = str(lighting.get("capture_kind") or "single")
        task["pair_id"] = lighting.get("pair_id")
        task["pair_member_index"] = lighting.get("pair_member_index")
        task["anchor_id"] = lighting.get("anchor_id")
        task["camera_set_ids"] = list(lighting.get("camera_set_ids") or [])
        runtime_recipe = dict(lighting["recipe"])
        center = list(runtime_recipe.get("side_center_xy") or (0.0, 0.0))
        runtime_recipe["side_center_xy"] = [float(center[0]) + float(offset[0]), float(center[1]) + float(offset[1])]
        task["lighting"]["runtime_recipe"] = runtime_recipe
    return task


def _artifact_contract(args: argparse.Namespace, material_contract: dict, fingerprint: str, frame_plan: dict | None,
                       overview: dict | None = None, *, passive_ready: bool = False) -> dict:
    contract = {
        "schema": "robomituba.ir_principled_artifact_contract.v3",
        "dataset_schema": DATASET_SCHEMA,
        "dataset_fingerprint": fingerprint,
        "layout": "modality_first_v1",
        "overview": {"schema": OVERVIEW_SCHEMA, "compiler_version": OVERVIEW_COMPILER_VERSION,
                     "path": "scene_overview.json"},
        "renderer": {"name": "Blender Cycles", "version": "4.2", "device": args.device},
        "exposure_ev": {"rgb": 0.0, "nir_active": 0.0},
        "material_contract": material_contract["contract_version"],
        "render_plan": ({"render_plan_id": frame_plan["render_plan_id"],
                         "render_plan_digest": frame_plan["render_plan_digest"],
                         "lighting_preset_version": frame_plan.get("lighting_preset_version"),
                         "requested_pose_count": frame_plan.get("requested_pose_count"),
                         "actual_pose_count": frame_plan.get("actual_pose_count"),
                         "illumination": frame_plan.get("illumination")} if frame_plan else None),
        "observations": {
            "rgb": {"path": "rgb/{frame_id}.exr", "encoding": "scene_linear_rgb_float32"},
            "nir_active": {
                "path": "nir_active/{frame_id}.exr",
                "encoding": "synthetic_nir_linear_float32_rgb_replicated",
                "formula": args.nir_formula,
            },
        },
        "ground_truth": {
            "base_color_rgb": "linear_unorm16", "base_color_nir": "linear_unorm16",
            "roughness": "perceptual_roughness_unorm16",
            "metallic": "raw_effective_principled_metallic_linear_unorm16",
            "metallic_family_id": "uint8 categorical: 0 dielectric, 1 conductor, 2 coverage_mixed",
            "normal_geometry_world": "xyz_signed_to_unorm16",
            "normal_shading_world": "xyz_signed_to_unorm16",
            "depth": "camera_z_millimeters_u16", "range": "ray_range_millimeters_u16",
            "object_id": "uint16", "material_id": "uint16",
            "diffuse_transport_rgb": "scene_linear_rgb_float32",
            "diffuse_transport_nir": "scene_linear_rgb_float32_replicated",
            "diffuse_component_rgb": "scene_linear_rgb_float32",
            "diffuse_component_nir": "scene_linear_rgb_float32_replicated",
            "diffuse_reflectance_rgb": "linear_unorm16",
            "diffuse_reflectance_nir": "linear_unorm16_replicated",
        },
        "masks": {
            "gt_defined_mask": "binary_u8", "source_valid_mask": "binary_u8",
            "replacement_mask": "binary_u8", "fallback_mask": "binary_u8", "remediated_pbr_mask": "binary_u8",
            "train_pbr_valid_mask": "source_valid OR remediated", "pbr_provenance_class": "uint8",
            "metal_coverage_mask": "binary_u8 conductor-family membership",
            "exposed_metal_mask": "binary_u8 effective exposed conductor coverage",
            "primary_eval_valid_mask": "source_valid AND NOT replacement",
            "diffuse_transport_valid_rgb": "finite surface AND max(diffuse_reflectance_rgb) > 1e-4",
            "diffuse_transport_valid_nir": "finite surface AND max(diffuse_reflectance_nir) > 1e-4",
        },
        "diffuse_decomposition": {
            "contract": "cycles_color_separated_diffuse_transport_v2",
            "transport": "Cycles Diffuse Direct + Diffuse Indirect",
            "reflectance": "Cycles Diffuse Color",
            "component": "diffuse_reflectance * diffuse_transport",
            "reconstruction": "diffuse_reflectance * diffuse_transport ~= diffuse_component",
            "excludes": ["glossy", "transmission", "emission"],
        },
        "nir_transport_provenance": {
            "integration": "cycles_path_traced_all_bounces",
            "nir_material_branch": "pre_integrator",
            "nir_light_conversion": "linear_rec709_luminance_grayscale",
            "spectral_scope": "pseudo_nir_base_color_only",
        },
        "light_calibration": {
            "base_energy_w": material_contract["flash_rig"]["energy_w"],
            "energy_scale": float(args.flash_energy_scale),
            "effective_energy_w": material_contract["flash_rig"]["energy_w"] * float(args.flash_energy_scale),
            "rig": material_contract["flash_rig"],
            "ambient_fill_energy_scale": float(args.ambient_fill_energy_scale),
            "ambient_fill_rig": material_contract.get("ambient_fill_rig"),
        },
    }
    if getattr(args, "nir_passive", False):
        contract["nir_passive"] = {
            "requested": True,
            "ready": bool(passive_ready),
            "contract_version": "nir-passive-v1",
        }
    if getattr(args, "nir_passive", False) and passive_ready:
        contract["exposure_ev"].update({"nir_passive": 0.0, "nir_active_minus_passive": 0.0})
        contract["observations"]["nir_passive"] = {
            "path": "nir_passive/{frame_id}.exr",
            "encoding": "synthetic_nir_linear_float32_rgb_replicated",
            "flash": "disabled",
            "formula": args.nir_formula,
        }
        contract["observations"]["nir_active_minus_passive"] = {
            "path": "nir_active_minus_passive/{frame_id}.exr",
            "encoding": "scene_linear_float32_rgb_difference",
            "definition": "nir_active - nir_passive",
        }
    if overview and (overview.get("traversability") or {}).get("path"):
        contract["overview"]["traversability_path"] = overview["traversability"]["path"]
    if overview and (overview.get("proxy_mesh") or {}).get("path"):
        contract["overview"]["proxy_mesh_path"] = overview["proxy_mesh"]["path"]
        contract["overview"]["proxy_mesh_sha256"] = overview["proxy_mesh"]["sha256"]
    structural = material_contract.get("structural_rematerialization")
    if isinstance(structural, dict):
        selection = structural.get("selection") if isinstance(structural.get("selection"), dict) else {}
        contract["structural_rematerialization"] = {
            "schema": structural.get("schema"), "digest": structural.get("digest"),
            "manifest_sha256": material_contract.get("structural_rematerialization_sha256"),
            "compiler_version": structural.get("compiler_version"),
            "child_scene_id": structural.get("child_scene_id"), "parent_scene_id": structural.get("parent_scene_id"),
            "parent_dataset_fingerprint": structural.get("parent_dataset_fingerprint"),
            "material_variant_id": structural.get("material_variant_id"), "material_seed": structural.get("material_seed"),
            "registry_digest": structural.get("registry_digest"), "binding_count": len(structural.get("bindings") or []),
            "selection": {"policy": selection.get("policy"), "eligible_unit_count": selection.get("eligible_unit_count"),
                          "eligible_slot_count": selection.get("eligible_slot_count"), "excluded_unit_count": selection.get("excluded_unit_count")},
        }
    return contract


def _load_overview_proxy(directory: Path | None) -> dict | None:
    """Verify the immutable pipeline proxy before it influences a dataset fingerprint."""
    if directory is None:
        return None
    glb, manifest_path = directory / "overview_proxy.glb", directory / "overview_proxy_manifest.json"
    if not glb.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("overview proxy directory is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != "robomituba.ir_scene_overview_proxy.v1"
        or manifest.get("coordinate_system") != "mitsuba_y_up"
        or int(manifest.get("triangles") or 0) < 1
        or int(manifest.get("triangles") or 0) > 50_000
        or str(manifest.get("glb_sha256") or "") != _sha256(glb)
    ):
        raise RuntimeError("overview proxy contract is invalid")
    return manifest


def _write_scene_overview(out: Path, graph: dict, tasks: list[dict], args: argparse.Namespace,
                          fingerprint: str, graph_path: Path) -> dict:
    """Write a small portable map: viewer never needs an external scene root."""
    graph_nodes = []
    for node in graph.get("nodes") or []:
        position = list(node.get("position") or [0.0, 0.0, 0.0])
        graph_nodes.append({"viewpoint_id": str(node.get("node_id")),
                            "origin": [float(position[0]), float(args.eye_height), float(position[1])],
                            "clearance_m": float(node.get("clearance_m") or 0.0)})
    poses, lighting_ids = [], set()
    for task in tasks:
        camera = task.get("camera") or {}
        lighting = task.get("lighting") or {}
        lighting_id = str(lighting.get("id") or "legacy")
        lighting_ids.add(lighting_id)
        poses.append({"frame_id": task["frame_id"], "viewpoint_id": task["viewpoint_id"],
                      "heading_deg": float(task["heading_deg"]),
                      "origin": list(camera.get("origin_mitsuba") or [0.0, args.eye_height, 0.0]),
                      "target": list(camera.get("target_mitsuba") or [0.0, args.target_height, 1.0]),
                      "up": list(camera.get("up_mitsuba") or [0.0, 1.0, 0.0]),
                      "fov_deg": float(args.fov), "aspect": float(args.width) / float(args.height),
                      "lighting_id": lighting_id})
    points = np.asarray([node["origin"] for node in graph_nodes] or [[-1.0, 0.0, -1.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    mins, maxs = points.min(axis=0), points.max(axis=0)
    margin = max(0.5, float(np.max(maxs[[0, 2]] - mins[[0, 2]]) * 0.08))
    payload: dict[str, Any] = {
        "schema": OVERVIEW_SCHEMA, "compiler_version": OVERVIEW_COMPILER_VERSION,
        "dataset_fingerprint": fingerprint, "coordinate_system": "mitsuba_y_up",
        "graph_digest": _sha256(graph_path), "graph_available": True,
        "traversability_available": False,
        "bounds": {"min": [float(mins[0] - margin), float(mins[1]), float(mins[2] - margin)],
                   "max": [float(maxs[0] + margin), float(maxs[1]), float(maxs[2] + margin)]},
        "nodes": graph_nodes,
        "edges": [{"source": str(edge.get("source")), "target": str(edge.get("target"))} for edge in (graph.get("edges") or [])],
        "poses": poses, "lighting_ids": sorted(lighting_ids),
    }
    grid_path = graph_path.parent / "traversable_grid.npy"
    grid_meta_path = graph_path.parent / "traversable_grid.npy.json"
    if grid_path.is_file() and grid_meta_path.is_file():
        grid = np.load(grid_path)
        meta = json.loads(grid_meta_path.read_text(encoding="utf-8")).get("grid") or {}
        preview = np.where(grid == 1, 230, np.where(grid == 2, 150, 25)).astype(np.uint8)
        image_path = out / "scene_overview" / "traversability.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(image_path), preview):
            raise RuntimeError("failed to write overview traversability PNG")
        payload["traversability_available"] = True
        payload["traversability"] = {"path": "scene_overview/traversability.png", "origin": meta.get("origin"),
                                      "resolution_m": meta.get("resolution"), "width": int(grid.shape[1]),
                                      "height": int(grid.shape[0]), "shape": [int(grid.shape[0]), int(grid.shape[1])],
                                      "row_axis": "positive_z", "legend": {"0": "obstacle", "1": "traversable", "2": "hazard"}}
    if args.overview_proxy_dir:
        proxy_dir = args.overview_proxy_dir.resolve()
        proxy_path, proxy_manifest_path = proxy_dir / "overview_proxy.glb", proxy_dir / "overview_proxy_manifest.json"
        if not proxy_path.is_file() or not proxy_manifest_path.is_file():
            raise FileNotFoundError("overview proxy directory is incomplete")
        proxy_manifest = json.loads(proxy_manifest_path.read_text(encoding="utf-8"))
        if proxy_manifest.get("schema") != "robomituba.ir_scene_overview_proxy.v1":
            raise RuntimeError("overview proxy schema is unsupported")
        if int(proxy_manifest.get("triangles") or 0) > 50_000 or proxy_manifest.get("coordinate_system") != "mitsuba_y_up":
            raise RuntimeError("overview proxy contract is invalid")
        destination = out / "scene_overview" / "scene_proxy.glb"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proxy_path, destination)
        payload["proxy_mesh"] = {"path": "scene_overview/scene_proxy.glb", "sha256": _sha256(destination),
                                 "triangles": int(proxy_manifest["triangles"]), "byte_count": destination.stat().st_size,
                                 "bounds": proxy_manifest.get("bounds"), "coordinate_system": "mitsuba_y_up",
                                 "compiler_version": proxy_manifest.get("compiler_version"),
                                 "source_geometry_digest": proxy_manifest.get("source_geometry_digest"),
                                 "semantic_groups": proxy_manifest.get("semantic_groups") or ["structural", "large_furniture"]}
        proxy_bounds = proxy_manifest.get("bounds") or {}
        try:
            proxy_low = np.asarray(proxy_bounds["min"], dtype=np.float32)
            proxy_high = np.asarray(proxy_bounds["max"], dtype=np.float32)
            if proxy_low.shape == (3,) and proxy_high.shape == (3,) and np.isfinite(proxy_low).all() and np.isfinite(proxy_high).all():
                bounds = payload["bounds"]
                bounds["min"] = np.minimum(np.asarray(bounds["min"], dtype=np.float32), proxy_low).tolist()
                bounds["max"] = np.maximum(np.asarray(bounds["max"], dtype=np.float32), proxy_high).tolist()
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("overview proxy bounds are invalid")
    _atomic_json(out / "scene_overview.json", payload)
    return payload


def _lighting_group_progress(tasks: list[dict], completed: set[str]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for task in tasks:
        lighting = task.get("lighting") or {}
        ident = str(lighting.get("id") or "legacy")
        group = groups.setdefault(ident, {"total": 0, "completed": 0, "capture_group_id": lighting.get("capture_group_id")})
        group["total"] += 1
        if task["frame_id"] in completed:
            group["completed"] += 1
    for group in groups.values():
        group["percent"] = 100.0 * group["completed"] / max(group["total"], 1)
    return groups


def _row_complete(out: Path, frame_id: str, fingerprint: str, *, require_passive: bool = False) -> bool:
    path = out / "frames" / f"{frame_id}.json"
    if not path.is_file():
        return False
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if row.get("dataset_fingerprint") != fingerprint:
        return False
    paths = row.get("paths") or {}
    required = set(REQUIRED_MODALITIES)
    # A new passive-NIR queue must not adopt an older active-only row as
    # complete.  The row flag is retained for legacy resumes, while the
    # explicit queue requirement covers the transition case before the
    # dataset-level readiness marker is written.
    if require_passive or bool(row.get("nir_passive_enabled")) or bool(row.get("nir_passive_backfill")):
        required |= PASSIVE_NIR_MODALITIES
    if not required <= set(paths):
        return False
    return all((out / paths[name]).is_file() for name in required)


def _derive_nir_difference(out: Path, row: dict) -> dict:
    """Create the exact linear active-minus-passive NIR sidecar.

    Blender writes both captures as scene-linear float EXR. OpenCV preserves
    the float channels; channel order is immaterial because both operands use
    the same RGB->BGR decode path. The result is written atomically and the
    frame manifest is updated only after the file is complete.
    """
    paths = row.get("paths") or {}
    active_rel, passive_rel = paths.get("nir_active"), paths.get("nir_passive")
    if not active_rel or not passive_rel:
        raise RuntimeError("cannot derive active-minus-passive without both NIR captures")
    active = cv2.imread(str(out / active_rel), cv2.IMREAD_UNCHANGED)
    passive = cv2.imread(str(out / passive_rel), cv2.IMREAD_UNCHANGED)
    if active is None or passive is None:
        raise RuntimeError("cannot decode active/passive NIR EXR")
    if active.shape != passive.shape or active.ndim != 3 or active.shape[2] < 3:
        raise RuntimeError(f"active/passive NIR shape mismatch: {active.shape} vs {passive.shape}")
    difference = active[..., :3].astype(np.float32) - passive[..., :3].astype(np.float32)
    target = out / "nir_active_minus_passive" / Path(active_rel).name
    _atomic_image(target, difference)
    row["paths"]["nir_active_minus_passive"] = str(target.relative_to(out))
    scalar = np.mean(difference, axis=2)
    finite = np.isfinite(scalar)
    values = scalar[finite]
    row["nir_difference_qc"] = {
        "mean_signed": float(values.mean()) if values.size else 0.0,
        "mean_abs": float(np.abs(values).mean()) if values.size else 0.0,
        "p95_abs": float(np.percentile(np.abs(values), 95.0)) if values.size else 0.0,
        "positive_pixel_ratio": float((values > 0).mean()) if values.size else 0.0,
        "finite": bool(finite.all()),
    }
    _atomic_json(out / "frames" / f"{row['frame_id']}.json", row)
    return row


def _passive_sidecars_complete(out: Path, frame_ids: set[str], *, fingerprint: str) -> bool:
    """Return true only when every indexed frame has both passive products."""
    for frame_id in frame_ids:
        frame_path = out / "frames" / f"{frame_id}.json"
        try:
            row = json.loads(frame_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if row.get("dataset_fingerprint") != fingerprint:
            return False
        paths = row.get("paths") or {}
        if not all(
            paths.get(name) and (out / str(paths[name])).is_file()
            for name in PASSIVE_NIR_MODALITIES
        ):
            return False
    return True


def _activate_nir_passive_contract(out: Path, *, fingerprint: str, frame_ids: set[str]) -> None:
    """Publish the dataset-level passive contract after an atomic completeness gate.

    Frame sidecars are useful while a queue is still running, but exposing the
    dataset as passive-complete before the last frame exists makes partial
    datasets look trainable.  Readiness is therefore a terminal marker and is
    deliberately excluded from the dataset fingerprint.
    """
    if not _passive_sidecars_complete(out, frame_ids, fingerprint=fingerprint):
        raise RuntimeError("cannot activate passive-NIR contract before every indexed frame has both sidecars")
    config_path = out / "dataset_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if str(config.get("dataset_fingerprint") or fingerprint) != fingerprint:
        raise RuntimeError("passive-NIR contract fingerprint does not match dataset config")
    config["dataset_fingerprint"] = fingerprint
    config["nir_passive_enabled"] = True
    config["nir_passive_contract"] = {
        "version": "nir-passive-v1",
        "active_minus_passive": "linear_exr_subtraction",
        "flash_state": "camera_relative_flash_disabled",
    }
    _atomic_json(config_path, config)
    contract_path = out / "artifact_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["dataset_fingerprint"] = fingerprint
    contract["nir_passive"] = {
        "requested": True,
        "ready": True,
        "contract_version": "nir-passive-v1",
    }
    contract.setdefault("exposure_ev", {}).update({
        "nir_passive": 0.0,
        "nir_active_minus_passive": 0.0,
    })
    observations = contract.setdefault("observations", {})
    observations["nir_passive"] = {
        "path": "nir_passive/{frame_id}.exr",
        "encoding": "synthetic_nir_linear_float32_rgb_replicated",
        "flash": "disabled",
        "formula": config.get("nir_formula", "primary"),
    }
    observations["nir_active_minus_passive"] = {
        "path": "nir_active_minus_passive/{frame_id}.exr",
        "encoding": "scene_linear_float32_rgb_difference",
        "definition": "nir_active - nir_passive",
    }
    _atomic_json(contract_path, contract)


def _atomic_image(path: Path, value: np.ndarray, parameters: list[int] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp{path.suffix}")
    if not cv2.imwrite(str(temp), value, parameters or []):
        raise RuntimeError(f"failed to write image: {temp}")
    os.replace(temp, path)


def _canonicalize_binary_masks(out: Path, row: dict) -> dict[str, int]:
    paths = row.get("paths") or {}
    masks: dict[str, np.ndarray] = {}
    changed: dict[str, int] = {}
    for modality in MASK_MODALITIES:
        relative = paths.get(modality)
        if not relative:
            continue
        path = out / relative
        value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if value is None or value.dtype != np.uint8 or value.ndim != 2:
            raise RuntimeError(f"invalid binary mask artifact: {path}")
        binary = np.where(value >= 128, 255, 0).astype(np.uint8)
        masks[modality] = binary
        difference = int(np.count_nonzero(value != binary))
        if difference:
            _atomic_image(path, binary, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            changed[modality] = difference
    if {"source_valid_mask", "replacement_mask", "primary_eval_valid_mask"} <= set(masks):
        primary = np.where(
            (masks["source_valid_mask"] > 0) & (masks["replacement_mask"] == 0), 255, 0,
        ).astype(np.uint8)
        path = out / paths["primary_eval_valid_mask"]
        difference = int(np.count_nonzero(masks["primary_eval_valid_mask"] != primary))
        if difference:
            _atomic_image(path, primary, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            changed["primary_eval_valid_mask"] = changed.get("primary_eval_valid_mask", 0) + difference
    if {"source_valid_mask", "remediated_pbr_mask", "train_pbr_valid_mask"} <= set(masks):
        train = np.where((masks["source_valid_mask"] > 0) | (masks["remediated_pbr_mask"] > 0), 255, 0).astype(np.uint8)
        path = out / paths["train_pbr_valid_mask"]
        difference = int(np.count_nonzero(masks["train_pbr_valid_mask"] != train))
        if difference:
            _atomic_image(path, train, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            changed["train_pbr_valid_mask"] = changed.get("train_pbr_valid_mask", 0) + difference
    return changed


def _sanitize_diffuse_arrays(
    transport: np.ndarray, component: np.ndarray, reflectance: np.ndarray, pixel_valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    finite_pixel = (
        np.isfinite(transport).all(axis=2)
        & np.isfinite(component).all(axis=2)
        & np.isfinite(reflectance).all(axis=2)
    )
    invalid_count = int(np.count_nonzero(~finite_pixel))
    # Isolated Cycles half-float singularities occur at material/light
    # boundaries.  They are explicitly zeroed and removed from the validity
    # mask.  With the illumination-diversity recipes, HDRI/portal boundaries
    # can produce a slightly larger *localized* cluster (still far below one
    # pixel in a 1e-3 area fraction).  Keep the gate strict enough to reject
    # spatially meaningful corruption, but do not fail an otherwise complete
    # frame for this repairable auxiliary-pass artifact.  At 684x512 this is
    # 176 pixels; the repaired count is retained in diffuse_decomposition_qc.
    nonfinite_limit = max(8, int(math.ceil(component.shape[0] * component.shape[1] * 5e-4)))
    if invalid_count > nonfinite_limit:
        raise RuntimeError(
            f"diffuse decomposition has {invalid_count} non-finite pixels (limit {nonfinite_limit})"
        )
    if invalid_count:
        transport = transport.copy()
        component = component.copy()
        pixel_valid = pixel_valid.copy()
        transport[~finite_pixel] = 0.0
        component[~finite_pixel] = 0.0
        pixel_valid[~finite_pixel] = False
    return transport, component, pixel_valid, invalid_count


def _derive_camera_depth(out: Path, row: dict) -> dict:
    mask_repairs = _canonicalize_binary_masks(out, row)
    range_path = out / row["paths"]["range"]
    ranges_mm = cv2.imread(str(range_path), cv2.IMREAD_UNCHANGED)
    if ranges_mm is None or ranges_mm.dtype != np.uint16:
        raise RuntimeError(f"cannot decode range PNG: {range_path}")
    height, width = ranges_mm.shape[:2]
    tan_x = math.tan(math.radians(float(row["fov_deg"])) * 0.5)
    tan_y = tan_x * height / width
    xs = ((np.arange(width, dtype=np.float32) + 0.5) / width * 2.0 - 1.0) * tan_x
    ys = (1.0 - (np.arange(height, dtype=np.float32) + 0.5) / height * 2.0) * tan_y
    factor = np.sqrt(1.0 + ys[:, None] ** 2 + xs[None, :] ** 2)
    depth_mm = np.where(ranges_mm > 0, np.rint(ranges_mm.astype(np.float32) / factor), 0.0)
    depth_mm = np.clip(depth_mm, 0, 65535).astype(np.uint16)
    depth_path = out / "depth" / f"{row['frame_id']}.png"
    depth_path.parent.mkdir(parents=True, exist_ok=True)
    temp = depth_path.with_name(depth_path.stem + ".tmp.png")
    if not cv2.imwrite(str(temp), depth_mm, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise RuntimeError(f"failed to write camera-Z depth: {temp}")
    os.replace(temp, depth_path)
    row["paths"]["depth"] = str(depth_path.relative_to(out))
    row["intrinsics"] = {
        "fov_axis": "x", "fov_deg": float(row["fov_deg"]),
        "fx": 0.5 * width / tan_x, "fy": 0.5 * width / tan_x,
        "cx": width * 0.5, "cy": height * 0.5,
    }
    nir_path = out / row["paths"]["nir_active"]
    nir = cv2.imread(str(nir_path), cv2.IMREAD_UNCHANGED)
    if nir is None:
        raise RuntimeError(f"cannot decode active-NIR EXR: {nir_path}")
    nir_scalar = nir.astype(np.float32)
    if nir_scalar.ndim == 3:
        nir_scalar = nir_scalar[..., :3].mean(axis=2)
    finite = nir_scalar[np.isfinite(nir_scalar)]
    if not finite.size:
        raise RuntimeError(f"active-NIR EXR has no finite samples: {nir_path}")
    nir_qc = {
        "mean": float(finite.mean()),
        "p95": float(np.percentile(finite, 95.0)),
        "p99": float(np.percentile(finite, 99.0)),
        "saturation_ratio_gt_1": float(np.mean(finite > 1.0)),
    }
    flash_rel = row["paths"].get("qc_nir_flash")
    if flash_rel:
        flash = cv2.imread(str(out / flash_rel), cv2.IMREAD_UNCHANGED)
        if flash is None:
            raise RuntimeError(f"cannot decode flash light-group EXR: {out / flash_rel}")
        flash_scalar = flash.astype(np.float32)
        if flash_scalar.ndim == 3:
            flash_scalar = flash_scalar[..., :3].mean(axis=2)
        denominator = float(np.maximum(nir_scalar, 0.0).sum())
        nir_qc["flash_contribution_ratio"] = (
            float(np.maximum(flash_scalar, 0.0).sum()) / denominator if denominator > 1e-12 else 0.0
        )
        nir_qc["flash_mean"] = float(np.nanmean(flash_scalar))
    row["nir_qc"] = nir_qc
    lighting_qc = {}
    for modality, combined_key, group_key in (
        ("rgb", "rgb", "qc_rgb_ambient_fill"),
        ("nir", "nir_active", "qc_nir_ambient_fill"),
    ):
        group_rel = row["paths"].get(group_key)
        if not group_rel:
            continue
        combined = cv2.imread(str(out / row["paths"][combined_key]), cv2.IMREAD_UNCHANGED)
        group = cv2.imread(str(out / group_rel), cv2.IMREAD_UNCHANGED)
        if combined is None or group is None:
            raise RuntimeError(f"cannot decode {modality} ambient-fill Light Group")
        combined = combined.astype(np.float32)[..., :3]
        group = group.astype(np.float32)[..., :3]
        combined_luminance = combined[..., 0] * 0.0722 + combined[..., 1] * 0.7152 + combined[..., 2] * 0.2126
        group_luminance = group[..., 0] * 0.0722 + group[..., 1] * 0.7152 + group[..., 2] * 0.2126
        denominator = float(np.maximum(combined_luminance, 0.0).sum())
        lighting_qc[modality] = {
            "combined_luminance_mean": float(np.mean(combined_luminance)),
            "combined_luminance_median": float(np.median(combined_luminance)),
            "combined_luminance_p10": float(np.percentile(combined_luminance, 10.0)),
            "combined_luminance_p95": float(np.percentile(combined_luminance, 95.0)),
            "dark_pixel_ratio_lt_0_01": float(np.mean(combined_luminance < 0.01)),
            "ambient_fill_contribution_ratio": (
                float(np.maximum(group_luminance, 0.0).sum()) / denominator if denominator > 1e-12 else 0.0
            ),
        }
    row["lighting_qc"] = lighting_qc
    decomposition_qc = {}
    for modality in ("rgb", "nir"):
        transport_path = out / row["paths"][f"diffuse_transport_{modality}"]
        component_path = out / row["paths"][f"diffuse_component_{modality}"]
        reflectance_path = out / row["paths"][f"diffuse_reflectance_{modality}"]
        valid_path = out / row["paths"][f"diffuse_transport_valid_{modality}"]
        transport = cv2.imread(str(transport_path), cv2.IMREAD_UNCHANGED)
        component = cv2.imread(str(component_path), cv2.IMREAD_UNCHANGED)
        reflectance = cv2.imread(str(reflectance_path), cv2.IMREAD_UNCHANGED)
        valid = cv2.imread(str(valid_path), cv2.IMREAD_UNCHANGED)
        if any(value is None for value in (transport, component, reflectance, valid)):
            raise RuntimeError(f"cannot decode {modality} diffuse decomposition")
        if transport.shape != component.shape or component.shape[:2] != reflectance.shape[:2] or component.shape[:2] != valid.shape[:2]:
            raise RuntimeError(f"{modality} diffuse decomposition dimensions differ")
        transport = transport.astype(np.float32)[..., :3]
        component = component.astype(np.float32)[..., :3]
        reflectance = reflectance.astype(np.float32)[..., :3] / 65535.0
        pixel_valid = valid > 0
        transport, component, pixel_valid, invalid_count = _sanitize_diffuse_arrays(
            transport, component, reflectance, pixel_valid,
        )
        if invalid_count:
            _atomic_image(transport_path, transport)
            _atomic_image(component_path, component)
            _atomic_image(valid_path, np.where(pixel_valid, 255, 0).astype(np.uint8), [cv2.IMWRITE_PNG_COMPRESSION, 3])
        channel_valid = pixel_valid[..., None] & (reflectance > 2.0 / 65535.0)
        reconstructed = transport * reflectance
        absolute_error = np.abs(reconstructed - component)
        finite = np.isfinite(transport) & np.isfinite(component) & np.isfinite(reflectance)
        if not bool(finite.all()):
            raise RuntimeError(f"{modality} diffuse decomposition contains non-finite values after repair")
        errors = absolute_error[channel_valid]
        relative = (absolute_error / np.maximum(np.abs(component), 1e-4))[channel_valid]
        decomposition_qc[modality] = {
            "valid_pixel_ratio": float(pixel_valid.mean()),
            "absolute_error_mean": float(errors.mean()) if errors.size else 0.0,
            "absolute_error_p99": float(np.percentile(errors, 99.0)) if errors.size else 0.0,
            "relative_error_p99": float(np.percentile(relative, 99.0)) if relative.size else 0.0,
            "invalid_nonfinite_pixel_count": invalid_count,
        }
    row["diffuse_decomposition_qc"] = decomposition_qc
    row["mask_canonicalization"] = {
        "threshold": 0.5,
        "repaired_pixel_counts": mask_repairs,
        "primary_eval_valid": "source_valid AND NOT replacement",
        "train_pbr_valid": "source_valid OR remediated_pbr",
    }
    _atomic_json(out / "frames" / f"{row['frame_id']}.json", row)
    return row


class BlenderWorker:
    def __init__(self, gpu: int, args: argparse.Namespace, blend: Path, fingerprint: str):
        self.gpu = int(gpu)
        self.args = args
        self.blend = blend
        self.fingerprint = fingerprint
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> dict:
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)
        command = [
            sys.executable, str(BLENDER_LAUNCHER), "--background", str(self.blend),
            "--python", str(WORKER_SCRIPT), "--",
            "--out", str(self.args.out), "--worker-id", f"gpu_{self.gpu}",
            "--fingerprint", self.fingerprint,
            "--width", str(self.args.width), "--height", str(self.args.height),
            "--fov", str(self.args.fov), "--rgb-spp", str(self.args.rgb_spp),
            "--nir-spp", str(self.args.nir_spp), "--max-bounces", str(self.args.max_bounces),
            "--seed", str(self.args.render_seed), "--device", self.args.device,
            "--nir-formula", self.args.nir_formula,
            "--flash-energy-scale", str(self.args.flash_energy_scale),
            "--ambient-fill-energy-scale", str(self.args.ambient_fill_energy_scale),
        ]
        if self.args.qc_components:
            command.append("--qc-components")
        if getattr(self.args, "nir_passive", False):
            command.append("--nir-passive")
        if getattr(self.args, "allow_legacy_passive_backfill_aovs", False):
            command.append("--allow-legacy-passive-backfill-aovs")
        self.process = subprocess.Popen(
            command, cwd=REPO_ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        return self._read_event("ready", timeout=600.0)

    def _read_event(self, expected: str, timeout: float | None = None) -> dict:
        assert self.process is not None and self.process.stdout is not None
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(f"Blender worker gpu={self.gpu} exited with {self.process.poll()}")
            text = line.rstrip()
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                important = any(token in text.lower() for token in ("error", "warning", "traceback"))
                if text and (self.args.verbose_blender or important):
                    print(f"[blender gpu={self.gpu}] {text}", flush=True)
                continue
            if event.get("type") == expected:
                return event
            if event.get("type") == "failed":
                raise RuntimeError(f"gpu={self.gpu} {event.get('error')}\n{event.get('traceback', '')}")
        raise TimeoutError(f"Blender worker gpu={self.gpu} did not report {expected}")

    def render(self, task: dict) -> dict:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps({"op": "render", "task": task}) + "\n")
        self.process.stdin.flush()
        return self._read_event("complete")

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        # A worker can disappear while its stdout/pipe is still in a kernel
        # wait (for example after an allocation drain or external SIGTERM).
        # Do not let the render parent remain alive indefinitely after all
        # committed frames are complete; shutdown is cleanup, not rendering.
        if process.poll() is not None:
            return
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=8)
            except Exception:
                try:
                    process.terminate()
                except OSError:
                    pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass


def _refresh_index(out: Path, *, fingerprint: str | None = None,
                   frame_ids: set[str] | None = None) -> list[dict]:
    rows = []
    for path in sorted((out / "frames").glob("*.json")) if (out / "frames").is_dir() else []:
        row = json.loads(path.read_text(encoding="utf-8"))
        if fingerprint is not None and row.get("dataset_fingerprint") != fingerprint:
            continue
        if frame_ids is not None and row.get("frame_id") not in frame_ids:
            continue
        rows.append(row)
    _atomic_text(out / "index.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return rows


def _config_adoption_compatible(previous: dict, current: dict) -> bool:
    """Only a frame-set/plan change may reuse pixels from a prior dataset."""
    ignored = {"worker_sha256", "dataset_fingerprint", "compatible_resume_worker_sha256",
               "frame_specs", "render_plan", *NIR_PASSIVE_READINESS_KEYS}
    return ({key: value for key, value in previous.items() if key not in ignored}
            == {key: value for key, value in current.items() if key not in ignored})


def _adopt_compatible_frames(out: Path, *, tasks: list[dict], new_fingerprint: str,
                             previous_config: dict | None, current_config: dict,
                             legacy_plan: Path | None, allow_row_only: bool = False) -> set[str]:
    """Re-attest exact legacy tasks to a corrected plan without touching pixels.

    The manifest is an audit record and makes an interrupted adoption safely
    repeatable: rows already carrying ``new_fingerprint`` simply pass the
    normal completion check on the next queue start.
    """
    if legacy_plan is None or not legacy_plan.is_file():
        return set()
    previous_fingerprint = str((previous_config or {}).get("dataset_fingerprint") or "")
    if previous_config is not None and not _config_adoption_compatible(previous_config, current_config):
        return set()
    try:
        old_plan = json.loads(legacy_plan.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return set()
    old_plan_digest = str(old_plan.get("render_plan_digest") or "")
    if previous_config is None:
        if not allow_row_only or not old_plan_digest:
            return set()
        # A dataset directory may retain rows from older immutable plans.  Only
        # infer the lost config fingerprint from rows belonging to the plan and
        # task set being explicitly adopted; unrelated rows must not make a
        # safe recovery ambiguous.
        task_ids = {str(task["frame_id"]) for task in tasks}
        legacy_fingerprints = set()
        for frame_id in task_ids:
            path = out / "frames" / f"{frame_id}.json"
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            row_plan_digest = str((row.get("lighting") or {}).get("render_plan_digest") or "")
            value = str(row.get("dataset_fingerprint") or "")
            if row_plan_digest == old_plan_digest and value and value != new_fingerprint:
                legacy_fingerprints.add(value)
        if len(legacy_fingerprints) != 1:
            return set()
        previous_fingerprint = next(iter(legacy_fingerprints))
    if not previous_fingerprint:
        return set()
    if previous_config is not None:
        previous_plan = previous_config.get("render_plan") or {}
        if str(previous_plan.get("render_plan_digest") or "") != str(old_plan.get("render_plan_digest") or ""):
            return set()
    required_modalities = set(REQUIRED_MODALITIES)
    if bool(current_config.get("nir_passive_enabled")):
        required_modalities |= PASSIVE_NIR_MODALITIES
    manifest_path = out / "plan_adoption_manifest.json"
    manifest = {
        "schema": "robomituba.ir_principled_plan_adoption.v1",
        "legacy_plan": str(legacy_plan), "legacy_plan_digest": old_plan.get("render_plan_digest"),
        "new_plan_digest": (current_config.get("render_plan") or {}).get("render_plan_digest"),
        "previous_dataset_fingerprint": previous_fingerprint,
        "new_dataset_fingerprint": new_fingerprint, "adopted": [], "rejected": {},
    }
    adopted: set[str] = set()
    for task in tasks:
        frame_id = str(task["frame_id"])
        path = out / "frames" / f"{frame_id}.json"
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            lighting = row.get("lighting") or {}
            target_lighting = task.get("lighting") or {}
            required = row.get("paths") or {}
            valid = (
                row.get("dataset_fingerprint") == previous_fingerprint
                and row.get("viewpoint_id") == task.get("viewpoint_id")
                and float(row.get("heading_deg", -1)) == float(task.get("heading_deg", -2))
                and row.get("camera") == task.get("camera")
                and row.get("pbr_gt_contract_digest") == task.get("pbr_gt_contract_digest")
                and int(row.get("width") or 0) == int(task.get("width") or 0)
                and int(row.get("height") or 0) == int(task.get("height") or 0)
                and float(row.get("fov_deg") or -1) == float(task.get("fov_deg") or -2)
                and lighting.get("recipe_digest") == target_lighting.get("recipe_digest")
                and lighting.get("render_plan_digest") == old_plan.get("render_plan_digest")
                and all(name in required and (out / required[name]).is_file() for name in required_modalities)
            )
            if not valid:
                manifest["rejected"][frame_id] = "task_metadata_or_artifacts_mismatch"
                continue
            before_sha = _sha256(path)
            row["dataset_fingerprint"] = new_fingerprint
            row["capture_kind"] = task.get("capture_kind", "single")
            row["pair_id"] = task.get("pair_id")
            row["pair_member_index"] = task.get("pair_member_index")
            row["lighting"] = {**lighting,
                               "capture_group_id": target_lighting.get("capture_group_id"),
                               "render_plan_id": target_lighting.get("render_plan_id"),
                               "render_plan_digest": target_lighting.get("render_plan_digest"),
                               "capture_kind": task.get("capture_kind", "single"),
                               "pair_id": task.get("pair_id"),
                               "pair_member_index": task.get("pair_member_index")}
            _atomic_json(path, row)
            adopted.add(frame_id)
            manifest["adopted"].append({"frame_id": frame_id, "previous_row_sha256": before_sha})
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            manifest["rejected"][frame_id] = f"read_error:{exc}"
    manifest["adopted_count"] = len(adopted)
    manifest["rejected_count"] = len(manifest["rejected"])
    _atomic_json(manifest_path, manifest)
    return adopted


def _qc_summary(out: Path, rows: list[dict]) -> dict:
    mask_counts = Counter()
    histograms = {name: np.zeros(32, dtype=np.int64) for name in ("roughness_original", "roughness_replacement", "roughness_all", "metallic_original", "metallic_replacement", "metallic_all")}
    for row in rows:
        paths = row.get("paths") or {}
        defined = cv2.imread(str(out / paths["gt_defined_mask"]), cv2.IMREAD_UNCHANGED) > 0
        original = cv2.imread(str(out / paths["primary_eval_valid_mask"]), cv2.IMREAD_UNCHANGED) > 0
        replacement = cv2.imread(str(out / paths["replacement_mask"]), cv2.IMREAD_UNCHANGED) > 0
        fallback = cv2.imread(str(out / paths["fallback_mask"]), cv2.IMREAD_UNCHANGED) > 0
        # Authorized window/mirror surrogates are replacement pixels, not
        # non-semantic missing-material fallbacks.  Keep their coverage in
        # the replacement telemetry, but exclude them from the 5% fallback
        # acceptance gate so a large retained window cannot reject an
        # otherwise valid opaque scene.
        nonsemantic_fallback = fallback & ~replacement
        replacement_fallback = fallback & replacement
        rough = cv2.imread(str(out / paths["roughness"]), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
        metal = cv2.imread(str(out / paths["metallic"]), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
        mask_counts["defined"] += int(defined.sum())
        mask_counts["original"] += int((defined & original).sum())
        mask_counts["replacement"] += int((defined & replacement).sum())
        mask_counts["fallback"] += int((defined & nonsemantic_fallback).sum())
        mask_counts["replacement_fallback"] += int((defined & replacement_fallback).sum())
        for value, prefix in ((rough, "roughness"), (metal, "metallic")):
            for mask, suffix in ((defined & original, "original"), (defined & replacement, "replacement"), (defined, "all")):
                histograms[f"{prefix}_{suffix}"] += np.histogram(value[mask], bins=32, range=(0.0, 1.0))[0]
    fallback_ratio = mask_counts["fallback"] / max(mask_counts["defined"], 1)
    replacement_ratio = mask_counts["replacement"] / max(mask_counts["defined"], 1)
    replacement_fallback_ratio = mask_counts["replacement_fallback"] / max(mask_counts["defined"], 1)
    lighting_groups: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        lighting_id = str((row.get("lighting") or {}).get("id") or "legacy")
        group = lighting_groups.setdefault(lighting_id, {"nir_mean": [], "nir_p95": [], "nir_saturation_ratio": [], "flash_contribution_ratio": []})
        qc = row.get("nir_qc") or {}
        for key, source in (("nir_mean", "mean"), ("nir_p95", "p95"), ("nir_saturation_ratio", "saturation_ratio_gt_1"), ("flash_contribution_ratio", "flash_contribution_ratio")):
            if qc.get(source) is not None:
                group[key].append(float(qc[source]))
    summary = {
        "schema": "robomituba.ir_principled_qc_summary.v1", "generated_at": _utc_now(),
        "frame_count": len(rows), "pixel_counts": dict(mask_counts),
        "replacement_pixel_ratio": replacement_ratio,
        "replacement_fallback_pixel_ratio": replacement_fallback_ratio,
        "fallback_pixel_ratio": fallback_ratio,
        "fallback_threshold": 0.05, "fallback_threshold_passed": fallback_ratio <= 0.05,
        "histograms_32_bins": {key: value.tolist() for key, value in histograms.items()},
        "nir": {
            "mean": [row.get("nir_qc", {}).get("mean") for row in rows],
            "p95": [row.get("nir_qc", {}).get("p95") for row in rows],
            "saturation_ratio_gt_1": [row.get("nir_qc", {}).get("saturation_ratio_gt_1") for row in rows],
            "passive_mean": [row.get("nir_passive_qc", {}).get("mean") for row in rows],
            "passive_p95": [row.get("nir_passive_qc", {}).get("p95") for row in rows],
            "active_minus_passive_mean_abs": [row.get("nir_difference_qc", {}).get("mean_abs") for row in rows],
            "active_minus_passive_p95_abs": [row.get("nir_difference_qc", {}).get("p95_abs") for row in rows],
        },
        "diffuse_decomposition": {
            modality: [row.get("diffuse_decomposition_qc", {}).get(modality) for row in rows]
            for modality in ("rgb", "nir")
        },
        "lighting": {
            modality: [row.get("lighting_qc", {}).get(modality) for row in rows]
            for modality in ("rgb", "nir")
        },
        "lighting_groups": {
            ident: {"frame_count": len(values["nir_mean"]), **{key: (float(np.mean(value)) if value else None) for key, value in values.items()}}
            for ident, values in lighting_groups.items()
        },
    }
    _atomic_json(out / "qc_summary.json", summary)
    return summary


def main() -> int:
    args = _args()
    args.scene_dir = args.scene_dir.resolve()
    args.prepared_scene_dir = args.prepared_scene_dir.resolve()
    args.out = args.out.resolve()
    if args.nir_passive is None:
        args.nir_passive = not (args.out / "dataset_config.json").is_file()
    if args.overview_proxy_dir:
        args.overview_proxy_dir = args.overview_proxy_dir.resolve()
    if args.frame_plan and (args.viewpoints or args.max_frames is not None):
        raise ValueError("--frame-plan cannot be combined with --viewpoints or --max-frames")
    if (
        args.width < 1 or args.height < 1 or args.rgb_spp < 1 or args.nir_spp < 1
        or args.flash_energy_scale <= 0 or args.ambient_fill_energy_scale <= 0
    ):
        raise ValueError("resolution and SPP must be positive")
    # Frame adoption and resume validation may scan thousands of artifacts on
    # network storage before the first Blender worker can be created.  Publish
    # that lifecycle explicitly so the controller does not mistake queue
    # preparation for a failed GPU allocation and rotate through every queued
    # dataset.
    args.out.mkdir(parents=True, exist_ok=True)
    if args.gpu_state_file is not None:
        allowed = [int(value) for value in args.gpu_indices.split(",") if value.strip()]
        desired = _desired_gpu_indices(args.gpu_allocation_file, allowed, allowed)
        _atomic_json(args.gpu_state_file, {
            "schema": "robomituba.ir_gpu_worker_state.v1",
            "updated_at": _utc_now(),
            "queue_pid": os.getpid(),
            "queue_state": "preparing",
            "allowed_gpu_indices": allowed,
            "desired_gpu_indices": desired,
            "workers": {},
        })
    graph_path = args.scene_dir / "viewpoint_graph.json"
    blend = args.prepared_scene_dir / "derived_ir_principled_v1.blend"
    contract_path = args.prepared_scene_dir / "principled_material_contract.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    _validate_prepared_contract(contract)
    overview_proxy = _load_overview_proxy(args.overview_proxy_dir)
    nodes = {str(node["node_id"]): node for node in graph["nodes"]}
    frame_plan = None
    if args.frame_plan:
        frame_plan = json.loads(args.frame_plan.read_text(encoding="utf-8"))
        specs = _plan_specs(graph, frame_plan)
    else:
        specs = _frame_specs(graph, args.viewpoints, args.shuffle_seed)
    if args.max_frames is not None:
        specs = specs[:args.max_frames]
    config = {
        "schema": DATASET_SCHEMA, "queue_compiler_version": QUEUE_COMPILER_VERSION,
        "worker_sha256": _sha256(WORKER_SCRIPT),
        "material_contract_digest": _sha256(contract_path),
        "prepared_blend_sha256": _sha256(blend), "graph_sha256": _sha256(graph_path),
        "width": args.width, "height": args.height, "fov": args.fov,
        "eye_height": args.eye_height, "target_height": args.target_height,
        "rgb_spp": args.rgb_spp, "nir_spp": args.nir_spp, "max_bounces": args.max_bounces,
        "device": args.device, "render_seed": args.render_seed,
        "exposure_ev": {"rgb": 0.0, "nir_active": 0.0},
        "qc_components": bool(args.qc_components),
        "nir_formula": args.nir_formula,
        "flash_energy_scale": args.flash_energy_scale,
        "ambient_fill_energy_scale": args.ambient_fill_energy_scale,
        "overview_compiler_version": OVERVIEW_COMPILER_VERSION,
        "overview_proxy": ({"glb_sha256": overview_proxy["glb_sha256"],
                              "source_geometry_digest": overview_proxy["source_geometry_digest"],
                              "triangle_target": overview_proxy.get("triangle_target"),
                              "triangle_cap": overview_proxy.get("triangle_cap")} if overview_proxy else None),
        "frame_specs": specs,
        "render_plan": ({"render_plan_id": frame_plan["render_plan_id"], "render_plan_digest": frame_plan["render_plan_digest"],
                         "content_digest": render_plan_digest(frame_plan), "illumination": frame_plan.get("illumination")} if frame_plan else None),
    }
    # Keep the legacy config byte/semantic contract untouched unless the new
    # observation pair is explicitly requested. This allows old active-NIR
    # jobs to resume without invalidating their completed RGB/GT frames.  The
    # requested bit is stable render identity; dataset-level ``enabled`` is
    # written only after the final passive sidecar has been verified.
    if args.nir_passive:
        config["nir_passive_requested"] = True
    args.out.mkdir(parents=True, exist_ok=True)
    previous_config = None
    previous_config_path = args.out / "dataset_config.json"
    if previous_config_path.is_file():
        try:
            previous_config = json.loads(previous_config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            previous_config = None
    if args.adopt_compatible_config and args.adopt_compatible_config.is_file():
        try:
            previous_config = json.loads(args.adopt_compatible_config.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            previous_config = None
    elif args.adopt_existing_rows:
        # The current dataset_config may have been atomically rewritten by a
        # cancelled newer queue before any old pixels changed.  Row-only
        # adoption deliberately derives the prior identity from exact frame
        # rows instead of trusting that newer config.
        previous_config = None
    fingerprint, stored_config = _select_dataset_fingerprint(
        args.out, config, compatible_resume=bool(args.compatible_worker_resume),
    )
    offset = _origin_offset(args.scene_dir)
    pbr_gt_contract_digest = stable_json_digest({
        "contract": contract.get("contract_version"),
        "aovs": contract.get("aovs"),
        "aov_semantics": contract.get("aov_semantics"),
        "materials": [
            {
                "id": item.get("material_id"),
                "effective_inputs": item.get("effective_inputs"),
                "metallic_contract": item.get("metallic_contract"),
            }
            for item in contract.get("materials") or []
        ],
    })
    external_lighting_available = bool((contract.get("external_portal_rig") or {}).get("available"))
    tasks = [_task(nodes[node_id], yaw, lighting, args, offset, fingerprint, pbr_gt_contract_digest, external_lighting_available) for node_id, yaw, lighting in specs]
    overview = _write_scene_overview(args.out, graph, tasks, args, fingerprint, graph_path)
    artifact_contract = _artifact_contract(args, contract, fingerprint, frame_plan, overview,
                                           passive_ready=False)
    _atomic_json(args.out / "artifact_contract.json", artifact_contract)
    _atomic_json(args.out / "dataset_config.json", {**stored_config, "dataset_fingerprint": fingerprint})

    adopted = _adopt_compatible_frames(
        args.out, tasks=tasks, new_fingerprint=fingerprint, previous_config=previous_config,
        current_config=config, legacy_plan=args.adopt_compatible_plan,
        allow_row_only=bool(args.adopt_existing_rows),
    )
    completed = {task["frame_id"] for task in tasks if _row_complete(
        args.out, task["frame_id"], fingerprint, require_passive=bool(args.nir_passive),
    )}
    pending = [task for task in tasks if task["frame_id"] not in completed]
    state = {
        "schema": QUEUE_SCHEMA, "dataset_fingerprint": fingerprint,
        "updated_at": _utc_now(), "frame_count": len(tasks),
        "completed": sorted(completed), "pending": [task["frame_id"] for task in pending], "failed": {},
        "lighting_groups": _lighting_group_progress(tasks, completed),
    }
    _atomic_json(args.out / "rolling_queue_state.json", state)
    gpu_indices = [int(value) for value in args.gpu_indices.split(",") if value.strip()]
    worker_count = min(args.workers or len(gpu_indices), len(gpu_indices), max(1, len(pending)))
    fallback_gpus = gpu_indices[:worker_count]
    print(
        f"[ir-principled-queue] frames={len(tasks)} complete={len(completed)} pending={len(pending)} "
        f"workers={worker_count} fingerprint={fingerprint[:16]} adopted={len(adopted)}", flush=True,
    )
    if args.dry_run or not pending:
        rows = _refresh_index(args.out, fingerprint=fingerprint, frame_ids={task["frame_id"] for task in tasks})
        if rows:
            _qc_summary(args.out, rows)
        if args.nir_passive and not args.dry_run and not pending:
            _activate_nir_passive_contract(
                args.out, fingerprint=fingerprint,
                frame_ids={task["frame_id"] for task in tasks},
            )
        return 0

    work: queue.Queue[dict] = queue.Queue()
    for task in pending:
        work.put(task)
    lock = threading.Lock()
    errors: list[str] = []
    attempts = Counter()
    worker_records: dict[str, dict[str, Any]] = {}
    active: dict[int, tuple[threading.Thread, threading.Event]] = {}
    failed_workers: set[int] = set()
    worker_failures = Counter()
    worker_retry_after: dict[int, float] = {}
    # Worker state is UI/lease telemetry, not an artifact checkpoint.  On the
    # network filesystem, writing it once per frame (and again every scheduler
    # tick) can leave otherwise healthy Blender workers in RPC wait.  Keep it
    # responsive while bounding writes to roughly one per second.
    last_worker_state_write = 0.0

    def write_worker_state(desired: list[int], *, force: bool = False) -> None:
        nonlocal last_worker_state_write
        if args.gpu_state_file is None:
            return
        now = time.monotonic()
        if not force and now - last_worker_state_write < 1.0:
            return
        with lock:
            payload = {
                "schema": "robomituba.ir_gpu_worker_state.v1",
                "updated_at": _utc_now(),
                "queue_pid": os.getpid(),
                "queue_state": _allocation_state(desired, active, work.unfinished_tasks),
                "allowed_gpu_indices": list(gpu_indices),
                "desired_gpu_indices": list(desired),
                "workers": {key: dict(value) for key, value in worker_records.items()},
            }
        _atomic_json(args.gpu_state_file, payload)
        last_worker_state_write = now

    def set_worker(gpu: int, status: str, *, frame_id: str | None = None, error: str | None = None) -> None:
        with lock:
            record = worker_records.setdefault(str(gpu), {})
            record.update({"status": status, "current_frame": frame_id, "updated_at": _utc_now()})
            if error is not None:
                record["error"] = error

    def run_worker(gpu: int, drain: threading.Event) -> None:
        worker = BlenderWorker(gpu, args, blend, fingerprint)
        set_worker(gpu, "starting")
        write_worker_state(_desired_gpu_indices(args.gpu_allocation_file, gpu_indices, fallback_gpus))
        try:
            ready = worker.start()
            print(f"[ir-principled-queue] ready gpu={gpu} devices={ready.get('devices')}", flush=True)
            set_worker(gpu, "ready")
            while True:
                if drain.is_set():
                    set_worker(gpu, "draining")
                    return
                try:
                    task = work.get(timeout=0.25)
                except queue.Empty:
                    if work.unfinished_tasks == 0:
                        return
                    continue
                if drain.is_set():
                    work.put(task)
                    work.task_done()
                    set_worker(gpu, "draining")
                    return
                frame_id = task["frame_id"]
                attempts[frame_id] += 1
                set_worker(gpu, "busy", frame_id=frame_id)
                write_worker_state(_desired_gpu_indices(args.gpu_allocation_file, gpu_indices, fallback_gpus))
                worker_failed = False
                try:
                    event = worker.render(task)
                    row = _derive_camera_depth(args.out, event["row"])
                    if args.nir_passive:
                        row = _derive_nir_difference(args.out, row)
                    with lock:
                        completed.add(frame_id)
                        state["completed"] = sorted(completed)
                        state["pending"] = [item["frame_id"] for item in list(work.queue)]
                        state["lighting_groups"] = _lighting_group_progress(tasks, completed)
                        state["updated_at"] = _utc_now()
                        # The image/GT artifacts are committed every frame, but
                        # rewriting a JSON checkpoint on the network filesystem
                        # for every worker completion creates NFS contention at
                        # the tail of a render (workers can remain in rpc_wait
                        # even after the last frame is complete).  Keep UI
                        # progress granular while checkpointing at a bounded
                        # cadence and always persist the terminal state.
                        if len(completed) % 4 == 0 or len(completed) == len(tasks):
                            _atomic_json(args.out / "rolling_queue_state.json", state)
                    print(
                        f"[ir-principled-queue] frame {len(completed)}/{len(tasks)} gpu={gpu} {frame_id} "
                        f"rgb={row['timings_s'].get('rgb', 0.0):.2f}s "
                        f"passive={row['timings_s'].get('nir_passive', 0.0):.2f}s "
                        f"nir={row['timings_s'].get('nir_active', 0.0):.2f}s",
                        flush=True,
                    )
                except Exception as exc:
                    worker_failed = worker.process is None or worker.process.poll() is not None
                    if worker_failed:
                        attempts[frame_id] -= 1
                        work.put(task)
                    elif attempts[frame_id] < args.retry_limit:
                        work.put(task)
                    else:
                        with lock:
                            state["failed"][frame_id] = str(exc)
                            errors.append(f"{frame_id}: {exc}")
                            _atomic_json(args.out / "rolling_queue_state.json", state)
                    print(f"[ir-principled-queue] failed gpu={gpu} {frame_id}: {exc}", flush=True)
                finally:
                    work.task_done()
                    set_worker(gpu, "draining" if drain.is_set() else "ready")
                    write_worker_state(_desired_gpu_indices(args.gpu_allocation_file, gpu_indices, fallback_gpus))
                if worker_failed:
                    raise RuntimeError(f"Blender worker gpu={gpu} exited while rendering {frame_id}")
        except Exception as exc:
            with lock:
                failed_workers.add(gpu)
                worker_failures[gpu] += 1
                worker_retry_after[gpu] = time.monotonic() + 2.0
            set_worker(gpu, "failed", error=str(exc))
            print(f"[ir-principled-queue] worker gpu={gpu} failed: {exc}", flush=True)
        finally:
            worker.stop()
            if gpu not in failed_workers:
                set_worker(gpu, "stopped")
            write_worker_state(_desired_gpu_indices(args.gpu_allocation_file, gpu_indices, fallback_gpus))

    last_desired: list[int] = []
    while work.unfinished_tasks > 0 or active:
        desired = _desired_gpu_indices(args.gpu_allocation_file, gpu_indices, fallback_gpus)
        if desired != last_desired:
            print(f"[ir-principled-queue] allocation desired={desired}", flush=True)
            last_desired = list(desired)
        for gpu, (thread, drain) in list(active.items()):
            if gpu not in desired and not drain.is_set():
                drain.set()
                set_worker(gpu, "draining", frame_id=worker_records.get(str(gpu), {}).get("current_frame"))
        for gpu in desired:
            if gpu in active or work.unfinished_tasks == 0:
                continue
            if gpu in failed_workers:
                if worker_failures[gpu] >= args.retry_limit or time.monotonic() < worker_retry_after[gpu]:
                    continue
                failed_workers.remove(gpu)
            drain = threading.Event()
            thread = threading.Thread(target=run_worker, args=(gpu, drain), name=f"ir-render-gpu-{gpu}", daemon=True)
            active[gpu] = (thread, drain)
            thread.start()
        for gpu, (thread, _drain) in list(active.items()):
            if not thread.is_alive():
                thread.join()
                active.pop(gpu, None)
        write_worker_state(desired)
        if (
            work.unfinished_tasks > 0 and not active and desired
            and all(worker_failures[gpu] >= args.retry_limit for gpu in desired)
        ):
            errors.append("all desired GPU workers failed")
            break
        # A render parent with no lease is intentionally dormant.  Poll the
        # allocation target slowly rather than presenting a hot, busy queue.
        time.sleep(1.0 if work.unfinished_tasks > 0 and not active and not desired else 0.25)

    for thread, drain in active.values():
        drain.set()
        thread.join()
    write_worker_state([], force=True)

    rows = _refresh_index(args.out, fingerprint=fingerprint, frame_ids={task["frame_id"] for task in tasks})
    qc = _qc_summary(args.out, rows) if rows else {}
    if errors or len(completed) != len(tasks):
        print(f"[ir-principled-queue] incomplete completed={len(completed)}/{len(tasks)} errors={len(errors)}", flush=True)
        return 1
    if qc and not qc.get("fallback_threshold_passed", False):
        print("[ir-principled-queue] non-semantic fallback pixel ratio exceeds 5%; blocking full-run acceptance", flush=True)
        return 2
    if args.nir_passive:
        _activate_nir_passive_contract(
            args.out, fingerprint=fingerprint,
            frame_ids={task["frame_id"] for task in tasks},
        )
    print(f"[ir-principled-queue] complete frames={len(rows)} -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
