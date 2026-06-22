from __future__ import annotations

import base64
from collections import deque
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import platform
from pathlib import Path
import math
import shutil
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.error
import urllib.request
import zipfile

import subprocess

import numpy as np

from robomituba_bridge import (
    AssistLightSpec,
    BsdfOverride,
    CameraSpec,
    IsaacCaptureRequest,
    IsaacMaterialPatch,
    IsaacObjectState,
    IsaacSensorSpec,
    IsaacSessionOpen,
    IsaacStatePatch,
    ObservationBundleManifest,
    RenderArtifactManifest,
    RenderJobAccepted,
    RenderJobStatus,
    RenderRequest,
    RobotState,
    SceneOverrideSpec,
    SceneState,
    SceneSnapshot,
    isaac_state_snapshot_from_payload,
    isaac_capture_request_from_payload,
    isaac_material_patch_from_payload,
    isaac_sensor_spec_from_payload,
    isaac_session_open_from_payload,
    isaac_state_patch_from_payload,
    bsdf_override_to_payload,
    read_shape_mapping,
    make_job_id,
    observation_bundle_manifest_to_payload,
    read_observation_bundle_manifest,
    read_render_job_status,
    render_job_accepted_to_payload,
    render_job_status_to_payload,
    render_request_from_payload,
    render_request_to_payload,
    resolve_repo_path,
    to_repo_relative_posix,
    write_render_job_status,
)
from robomituba_bridge.io import scene_snapshot_from_payload

from .local_snapshot import enumerate_xml_targets, prepare_basic_scene_from_disk
from .material_overrides_store import (
    StoredOverride,
    load_overrides as _load_material_overrides,
    merge_overrides as _merge_material_overrides,
    overrides_path_for_scene as _overrides_path_for_scene,
    overrides_ref_for_scene as _overrides_ref_for_scene,
    save_overrides as _save_material_overrides,
)
from .multimodal import SUPPORTED_MODALITIES, camera_to_world_to_lookat, normalize_mat4_storage
from .observation_bridge import render_timestep_bundle_split_lighting
from .scene_floorplan import CameraOverlay, LightOverlay, render_scene_floorplan
from .glb_texture_adapter import extract_glb_mesh_for_editor as extract_glb_mesh_for_editor_preview
from .usd_editor_geometry import build_usd_editor_geometry, extract_prim_mesh_for_editor
from .worker_manager import WorkerManager


RenderFn = Callable[..., ObservationBundleManifest]
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# Phase R: subprocess-based render worker isolation. The daemon defaults to
# rendering in a worker subprocess because Dr.Jit/Mitsuba can abort the process
# on unrecoverable CUDA failures (for example OOM during texture allocation).
# ``ROBOMITUBA_RENDER_INPROCESS=1`` remains as the legacy rollback switch.
_RENDER_INPROCESS_DEFAULT = "0"
_RENDER_INPROCESS = (
    os.environ.get("ROBOMITUBA_RENDER_INPROCESS", _RENDER_INPROCESS_DEFAULT).strip().lower()
    in ("1", "true", "yes", "on")
)


def _backend_only_mode() -> bool:
    return os.environ.get("ROBOMITUBA_BACKEND_ONLY", "0").strip().lower() in ("1", "true", "yes", "on")


def _render_queue_url() -> str:
    return os.environ.get("ROBOMITUBA_RENDER_QUEUE_URL", "http://127.0.0.1:8766").strip().rstrip("/")


def _is_render_queue_proxy_path(method: str, path: str) -> bool:
    method = method.upper()
    if path == "/render" or path.startswith("/jobs/"):
        return True
    if path == "/isaac/render" or path == "/isaac/render/submit":
        return True
    if path == "/api/render-jobs" or path.startswith("/api/render-jobs/"):
        return True
    if path == "/api/material-jobs" or path.startswith("/api/material-jobs/"):
        return True
    if path.startswith("/api/material-preview/") or path == "/api/material-previews/batch-invalidate":
        return True
    if not path.startswith("/api/opticalnav/projects/"):
        return False
    parts = [part for part in path[len("/api/opticalnav/projects/"):].strip("/").split("/") if part]
    if len(parts) >= 4 and parts[1] == "scenes" and parts[3:] == ["graph", "sweep"]:
        return method == "POST"
    if len(parts) >= 2 and parts[1] in {"graph-render-batches", "render-batches"}:
        return method in {"GET", "POST"}
    if len(parts) >= 2 and parts[1:] == ["episodes", "render"]:
        return method == "POST"
    return False


def _isaac_snapshot_to_scene_override(snapshot: Any) -> SceneOverrideSpec | None:
    """Convert IsaacStateSnapshot objects list to a SceneOverrideSpec for XML patching."""
    bsdf_overrides: dict[str, Any] = {}
    transform_overrides: dict[str, Any] = {}
    for obj in snapshot.objects:
        if obj.bsdf_override is not None:
            bsdf_overrides[obj.prim_path] = obj.bsdf_override
        if obj.transform is not None:
            transform_overrides[obj.prim_path] = obj.transform
    if not bsdf_overrides and not transform_overrides:
        return None
    return SceneOverrideSpec(
        prim_to_shape_ids=dict(snapshot.extras.get("prim_to_shape_ids", {})),
        bsdf_overrides=bsdf_overrides,
        transform_overrides=transform_overrides,
    )


def _artifact_paths_from_bundle(bundle: ObservationBundleManifest) -> dict[str, dict[str, str]]:
    artifacts: dict[str, dict[str, str]] = {}
    for artifact in bundle.artifacts:
        key = artifact.modality
        artifacts[key] = {
            name: value
            for name, value in artifact.artifact_paths.items()
            if isinstance(value, str)
        }
    return artifacts


class _ClientDisconnectedError(RuntimeError):
    """Raised when the HTTP client disconnects before the response is fully written."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat(timespec="seconds")


def _log_graph_edit(handler: Any, project_dir: "Path", scene_id: str, event: dict[str, Any]) -> None:
    """Best-effort: append one human graph-edit event to the scene's history jsonl.

    Records the manual viewpoint-graph (path) edit as training/analysis data for
    improving auto path generation. Never raises — logging must not break the edit.
    Common context (project/scene/source/session/client) is added here; callers pass
    the operation-specific delta + algorithm-view fields.
    """
    try:
        from navigation_dataset.graph_edit_log import append_graph_edit
        scene_dir = Path(project_dir) / "scenes" / str(scene_id)
        session_id = None
        client_ip = None
        try:
            session_id = handler.headers.get("X-Edit-Session") if getattr(handler, "headers", None) else None
            client_ip = handler.client_address[0] if getattr(handler, "client_address", None) else None
        except Exception:  # noqa: BLE001
            pass
        enriched = {
            "project_id": Path(project_dir).name,
            "scene_id": str(scene_id),
            "source": "manual_editor",
            "session_id": session_id,
            "client_ip": client_ip,
            **event,
        }
        append_graph_edit(scene_dir, enriched, ts=_utc_now_iso())
    except Exception:  # noqa: BLE001 — logging is strictly best-effort
        pass


def _event_ts_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _render_progress_persist_interval_s() -> float:
    raw = os.environ.get("ROBOMITUBA_RENDER_PROGRESS_PERSIST_INTERVAL_S", "30")
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return 30.0


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _render_gpu_indices_from_env() -> list[int]:
    raw = str(os.environ.get("ROBOMITUBA_RENDER_GPU_INDICES") or "0").strip()
    indices: list[int] = []
    for part in raw.replace(",", " ").split():
        try:
            indices.append(int(part))
        except ValueError:
            continue
    return indices or [0]


def _static_gpu_shards_enabled() -> bool:
    return str(os.environ.get("ROBOMITUBA_RENDER_STATIC_GPU_SHARDS") or "0").strip().lower() in {"1", "true", "yes", "on"}


def _dynamic_gpu_scheduling_policy() -> str:
    raw = str(os.environ.get("ROBOMITUBA_RENDER_WORKER_BACKLOG_PER_GPU") or "2").strip()
    try:
        backlog = max(1, int(raw))
    except (TypeError, ValueError):
        backlog = 2
    return f"dynamic_worker_pull_prefetch_{backlog}"


def _interleaved_gpu_shard_assignments(item_count: int, gpu_indices: list[int]) -> list[dict[str, int]]:
    """Assign consecutive render jobs across GPUs in round-robin order.

    The old contiguous layout produced all GPU0 jobs first, then GPU1, etc.
    Because the daemon pending queue is FIFO, large OpticalNav sweeps then ran
    as a single-GPU workload for hundreds of frames before the next GPU saw
    work. Interleaving keeps each worker fed from the start while preserving
    per-GPU shard metadata for UI/debugging.
    """
    if item_count <= 0:
        return []
    active_gpus = list(gpu_indices or [0])[:item_count]
    shard_count = max(1, len(active_gpus))
    base = item_count // shard_count
    remainder = item_count % shard_count
    shard_sizes = [
        base + (1 if shard_index < remainder else 0)
        for shard_index in range(shard_count)
    ]
    shard_item_indices = [0 for _ in range(shard_count)]
    assignments: list[dict[str, int]] = []
    for item_index in range(item_count):
        shard_index = item_index % shard_count
        shard_item_index = shard_item_indices[shard_index]
        shard_item_indices[shard_index] += 1
        assignments.append({
            "target_gpu_index": int(active_gpus[shard_index]),
            "shard_index": int(shard_index),
            "shard_count": int(shard_count),
            "shard_item_index": int(shard_item_index),
            "shard_size": int(shard_sizes[shard_index]),
        })
    return assignments


def _safe_sort_ts(value: str | None) -> tuple[int, str]:
    return (1 if value else 0, value or "")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_scene_overlay_objects(scene_dir: Path) -> "list[dict[str, Any]] | None":
    """Load full-geometry objects from ``render_scene_overlays.json`` for footprint
    masking. Returns None when the overlay is missing so callers fall back to the
    lossy annotation masking."""
    overlay_path = scene_dir / "render_scene_overlays.json"
    if not overlay_path.exists():
        return None
    try:
        return _read_json(overlay_path).get("objects") or None
    except Exception:
        return None


def _maybe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _generate_minimal_opticalnav_scene_xml(authoring_map_payload: dict[str, Any], out_path: "Path") -> None:
    """Generate a minimal Mitsuba scene XML from an authoring map.

    Creates a simple room (floor, ceiling, perimeter walls, ambient lighting)
    whose coordinate system matches the authoring map (meters, XZ plane for floor).
    Used when no registered Mitsuba scene exists for an opticalnav scene.
    """
    import xml.etree.ElementTree as ET

    regions = authoring_map_payload.get("regions") or []
    settings = authoring_map_payload.get("settings") or {}
    wall_h = float(settings.get("default_wall_height_m") or 2.4)
    wall_t = float(settings.get("default_wall_thickness_m") or 0.08)

    # Determine floor bounds from traversable region
    traversable = next((r for r in regions if r.get("type") == "traversable"), None)
    if traversable:
        bounds = (traversable.get("geometry") or {}).get("bounds")
        if isinstance(bounds, list) and len(bounds) == 4:
            min_x, min_z, max_x, max_z = [float(b) for b in bounds]
        else:
            min_x, min_z, max_x, max_z = 0.0, 0.0, 10.0, 10.0
    else:
        min_x, min_z, max_x, max_z = 0.0, 0.0, 10.0, 10.0

    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0
    dx = max_x - min_x
    dz = max_z - min_z

    root = ET.Element("scene", version="3.0.0")

    def _cube_shape(parent: "ET.Element", cx: float, cy: float, cz: float,
                    sx: float, sy: float, sz: float, angle_y: float = 0.0,
                    color: str = "0.75 0.75 0.75") -> None:
        shape = ET.SubElement(parent, "shape", type="cube")
        xf = ET.SubElement(shape, "transform", attrib={"name": "to_world"})
        ET.SubElement(xf, "scale", x=f"{sx:.6f}", y=f"{sy:.6f}", z=f"{sz:.6f}")
        if abs(angle_y) > 1e-4:
            ET.SubElement(xf, "rotate", y="1", angle=f"{angle_y:.4f}")
        ET.SubElement(xf, "translate", x=f"{cx:.6f}", y=f"{cy:.6f}", z=f"{cz:.6f}")
        bsdf = ET.SubElement(shape, "bsdf", type="diffuse")
        ET.SubElement(bsdf, "rgb", attrib={"name": "reflectance", "value": color})

    # Floor slab (thin cube at Y=0)
    _cube_shape(root, cx, -0.025, cz, dx / 2, 0.025, dz / 2, color="0.55 0.50 0.45")
    # Ceiling slab
    _cube_shape(root, cx, wall_h + 0.025, cz, dx / 2, 0.025, dz / 2, color="0.85 0.85 0.85")
    # North perimeter wall (along X at max_z)
    _cube_shape(root, cx, wall_h / 2, max_z, dx / 2, wall_h / 2, wall_t / 2, color="0.80 0.78 0.75")
    # South perimeter wall
    _cube_shape(root, cx, wall_h / 2, min_z, dx / 2, wall_h / 2, wall_t / 2, color="0.80 0.78 0.75")
    # East perimeter wall (along Z at max_x)
    _cube_shape(root, max_x, wall_h / 2, cz, wall_t / 2, wall_h / 2, dz / 2, color="0.80 0.78 0.75")
    # West perimeter wall
    _cube_shape(root, min_x, wall_h / 2, cz, wall_t / 2, wall_h / 2, dz / 2, color="0.80 0.78 0.75")

    # Path integrator (required by multimodal renderer)
    integrator = ET.SubElement(root, "integrator", type="path")
    ET.SubElement(integrator, "integer", attrib={"name": "max_depth", "value": "6"})

    # Ambient + directional lighting
    emitter = ET.SubElement(root, "emitter", type="constant")
    ET.SubElement(emitter, "rgb", attrib={"name": "radiance", "value": "0.8 0.8 0.85"})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass
    ET.ElementTree(root).write(str(out_path), encoding="unicode", xml_declaration=False)



def _material_index(authoring_map_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in authoring_map_payload.get("materials") or []:
        mid = str(item.get("material_id") or "").strip()
        if not mid:
            continue
        material = dict(item)
        index[mid] = material
        # Historical maps mix dataset/material and dataset:material forms.
        # Treat them as aliases so render readiness and BSDF generation do not
        # block when the object id and material table id use different separators.
        if "/" in mid:
            index.setdefault(mid.replace("/", ":", 1), material)
        if ":" in mid:
            index.setdefault(mid.replace(":", "/", 1), material)
    return index


def _coerce_float_list(value: Any, default: list[float], *, length: int) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) >= length:
        try:
            return [float(value[i]) for i in range(length)]
        except Exception:
            pass
    return list(default)


def _rgb_value(value: Any, *, intensity: float = 1.0, default: str = "0.8 0.8 0.85") -> str:
    rgb = _coerce_float_list(value, [float(v) for v in default.split()], length=3)
    return " ".join(f"{max(0.0, c * intensity):.6g}" for c in rgb)


_MEASURED_KINDS = {"measured", "hpbrdf", "pbrdf", "hpbrdf_2025", "pbrdf_2020"}


def _binding_is_measured(binding: dict[str, Any]) -> bool:
    """True when ``binding`` resolves to a measured/hpbrdf channel-split BSDF.

    Used to decide whether USD UsdShade material should be allowed to override
    the BSDF: hpbrdf prims keep their measured BSDF, others can use USD.
    """
    strategy = str(binding.get("bsdf_strategy") or "").lower()
    if strategy in {"measured", "measured_polarized"}:
        return True
    kind = str(binding.get("kind") or "").lower()
    if kind in _MEASURED_KINDS:
        return True
    return False


def _absolutize_texture_path(value: str | None, repo_root: "Path | None") -> str | None:
    """Convert a repo-relative texture path to an absolute filesystem path.

    Mitsuba's bitmap loader resolves relative paths against the *XML file's*
    directory, but our XML is staged to ``.staged_mitsuba/base/*.xml`` while
    textures live under the repo root, so we always emit absolute paths.
    """
    if not value:
        return None
    p = Path(value)
    if p.is_absolute():
        return str(p)
    if repo_root is not None:
        return str((repo_root / p).resolve())
    return str(p.resolve())


def _resolve_hpbrdf_channels_dir(binding: dict[str, Any], repo_root: "Path | None") -> str | None:
    """Return the channel-split HPBRDF directory for a measured binding, if available."""
    channels_dir = _maybe_str(binding.get("channels_dir"))
    src_mid = _maybe_str(binding.get("material_id"))
    if not channels_dir and repo_root is not None and src_mid:
        try:
            from .material_library import hpbrdf_channels_dir as _ch_dir

            ch = _ch_dir(repo_root, src_mid)
            if ch is not None:
                channels_dir = ch.relative_to(repo_root).as_posix()
        except Exception:
            channels_dir = None
    return channels_dir


def _append_measured_albedo_scale_xml(
    bsdf: "ET.Element",
    extracted_material: dict[str, Any] | None,
    *,
    repo_root: "Path | None" = None,
) -> bool:
    """Attach source albedo as a measured-pBRDF multiplier for HPBRDF RGB MVP.

    This intentionally carries only base color texture/factor. Roughness, metallic
    and normal maps remain part of the analytic material path for v1.
    """
    if not extracted_material:
        return False

    import xml.etree.ElementTree as ET

    base_tex = _absolutize_texture_path(extracted_material.get("base_color_texture_ref"), repo_root)
    base_factor = extracted_material.get("base_color_factor")

    if base_tex and Path(base_tex).exists():
        tex = ET.SubElement(bsdf, "texture", attrib={"name": "albedo_scale", "type": "bitmap"})
        ET.SubElement(tex, "string", attrib={"name": "filename", "value": str(base_tex)})
        return True

    if isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3:
        try:
            rgb = " ".join(f"{max(0.0, min(1.0, float(c))):.6g}" for c in base_factor[:3])
        except Exception:
            return False
        ET.SubElement(bsdf, "rgb", attrib={"name": "albedo_scale", "value": rgb})
        return True

    return False


_PART_CLASS_TOKEN_MAP = {
    "glass": ("glass", "glazing", "window", "pane"),
    "metal": ("metal", "steel", "aluminum", "aluminium", "chrome", "brass", "iron", "suj2"),
    "wood": ("wood", "oak", "walnut", "timber", "veneer"),
    "leather": ("leather", "seat", "chair_leather"),
    "fabric": ("fabric", "cloth", "stitch", "seam", "blanket", "textile"),
    "ceramic": ("ceramic", "porcelain", "alumina", "zro"),
    "plastic": ("plastic", "poly", "peek", "pom", "rubber", "silicone"),
}

_CLASS_HPBRDF_FALLBACKS = {
    "wood": "hpbrdf_2025:yellow_rough_plastic",
    "leather": "hpbrdf_2025:black_rough_plastic",
    "fabric": "hpbrdf_2025:black_rough_plastic",
    "ceramic": "hpbrdf_2025:white_smooth_plastic",
    "plastic": "hpbrdf_2025:white_smooth_plastic",
    "default": "hpbrdf_2025:white_smooth_plastic",
}

_USD_PRIM_MATERIAL_META_VERSION = 2  # v2: per-mesh extracted material + render material hints

_CLASS_PBRDF_FALLBACKS = {
    "wood": "pbrdf_2020:peek",
    "leather": "pbrdf_2020:black_billiard",
    "fabric": "pbrdf_2020:black_billiard",
    "ceramic": "pbrdf_2020:ceramic_alumina",
    "plastic": "pbrdf_2020:white_billiard",
    "default": "pbrdf_2020:white_billiard",
}


def _texture_or_material_tokens(part: dict[str, Any], extracted_material: dict[str, Any] | None) -> str:
    fields: list[str] = [
        str(part.get("mesh_name") or ""),
        str(part.get("mesh_prim_path") or ""),
        str(part.get("part_id") or ""),
        str(part.get("asset_category") or ""),
        str(part.get("object_type") or ""),
        str(part.get("object_material") or ""),
        str(part.get("source_ref") or ""),
    ]
    if extracted_material:
        fields.extend(str(extracted_material.get(key) or "") for key in (
            "material_id", "surface_shader_id", "base_color_asset", "base_color_texture_ref",
            "normal_asset", "normal_texture_ref", "roughness_asset", "roughness_texture_ref",
        ))
    return " ".join(fields).lower()


def _infer_material_class(part: dict[str, Any], extracted_material: dict[str, Any] | None) -> str:
    tokens = _texture_or_material_tokens(part, extracted_material)
    for cls, needles in _PART_CLASS_TOKEN_MAP.items():
        if any(tok in tokens for tok in needles):
            return cls
    try:
        if extracted_material and float(extracted_material.get("metallic_factor") or 0.0) >= 0.75:
            return "metal"
    except Exception:
        pass
    return "default"


def _catalog_material_available(material_id: str, material_idx: dict[str, dict[str, Any]], repo_root: "Path | None") -> bool:
    if material_id in material_idx:
        return True
    if not material_id or ":" not in material_id:
        return False
    dataset_id, source_mid = material_id.split(":", 1)
    if dataset_id == "hpbrdf_2025":
        if repo_root is None:
            return False
        try:
            from .material_library import hpbrdf_channels_dir
            return hpbrdf_channels_dir(repo_root, source_mid) is not None
        except Exception:
            return False
    if dataset_id == "pbrdf_2020":
        try:
            from .material_library import MATERIAL_CATALOG
            return any(mid == source_mid for mid, _label, native in MATERIAL_CATALOG.get("pbrdf_2020", []) if native)
        except Exception:
            return False
    return False


def _catalog_pbrdf_native_file(material_id: str) -> str | None:
    if not material_id.startswith("pbrdf_2020:"):
        return None
    source_mid = material_id.split(":", 1)[1]
    try:
        from .material_library import MATERIAL_CATALOG
        for mid, _label, native in MATERIAL_CATALOG.get("pbrdf_2020", []):
            if mid == source_mid:
                return native
    except Exception:
        return None
    return None


def _select_part_render_material(
    parent_material_id: str | None,
    part: dict[str, Any],
    extracted_material: dict[str, Any] | None,
    material_idx: dict[str, dict[str, Any]],
    *,
    repo_root: "Path | None" = None,
) -> tuple[str | None, str]:
    material_class = _infer_material_class(part, extracted_material)
    if material_class == "glass":
        return "clear_glass", material_class
    if material_class == "metal":
        return "mirror", material_class

    parent_binding = _resolve_material_binding(parent_material_id, material_idx)
    if _resolve_hpbrdf_channels_dir(parent_binding, repo_root):
        return parent_material_id, material_class

    hpbrdf_id = _CLASS_HPBRDF_FALLBACKS.get(material_class) or _CLASS_HPBRDF_FALLBACKS["default"]
    if _catalog_material_available(hpbrdf_id, material_idx, repo_root):
        return hpbrdf_id, material_class

    pbrdf_id = _CLASS_PBRDF_FALLBACKS.get(material_class) or _CLASS_PBRDF_FALLBACKS["default"]
    if _catalog_material_available(pbrdf_id, material_idx, repo_root):
        return pbrdf_id, material_class

    if extracted_material and (extracted_material.get("base_color_texture_ref") or extracted_material.get("base_color_factor")):
        return "wood" if material_class == "wood" else "fabric" if material_class in {"leather", "fabric"} else "plastic", material_class
    return parent_material_id, material_class


def _should_emit_asset_mesh_part(obj: dict[str, Any], part: dict[str, Any]) -> bool:
    """Return False for child meshes that belong to a bundled asset but not this object.

    Curated USD assets sometimes group several semantic objects under one prim
    (for example MooreLane DiningRoom/Table contains both the table and dining
    chairs). When that prim is attached to an authoring object of type ``table``,
    emitting every child mesh produces black chair silhouettes around the table.
    Keep the default permissive, but filter obvious bundled-chair children for
    table-only objects. Authors can opt out via metadata.keep_all_asset_parts.
    """
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    if bool(meta.get("keep_all_asset_parts")):
        return True
    obj_type = str(obj.get("type") or "").lower()
    if obj_type != "table":
        return True
    tokens = _texture_or_material_tokens(part, part.get("extracted_material") if isinstance(part.get("extracted_material"), dict) else None)
    if "chair" in tokens or "chairs" in tokens or "armchair" in tokens:
        return False
    return True


def _resolve_material_asset_path(raw: str | None, *, base_dir: "Path", repo_root: "Path | None") -> "Path | None":
    """Resolve an OBJ/MTL sidecar asset path without assuming repo-relative input."""
    value = (raw or "").strip()
    if not value:
        return None
    path = Path(value)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(base_dir / path)
        if repo_root is not None:
            candidates.append(repo_root / path)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved.exists():
            return resolved
    return None


def _mtl_texture_value(raw: str) -> str:
    """Return the filename-like part of a Wavefront MTL texture statement."""
    value = raw.strip()
    if not value:
        return ""
    # Most exported MooreLane MTLs are plain `map_Kd /abs/path.png`. Keep that
    # path intact. For option-heavy MTLs, fall back to the trailing filename.
    if not value.startswith("-"):
        return value
    parts = value.split()
    return parts[-1] if parts else ""


def _extract_obj_mtl_material(obj_path: "Path", *, repo_root: "Path | None" = None) -> dict[str, Any] | None:
    """Extract a simple diffuse texture material from an OBJ's first MTL sidecar.

    Direct MooreLane OBJ exports carry useful `map_Kd` texture references in
    their `.mtl` files. If we attach a scene-level measured BSDF to the OBJ
    shape, Mitsuba ignores those sidecar materials and the object can render as
    an almost black silhouette. This helper converts the sidecar into the same
    compact material descriptor used by USD material extraction.
    """
    try:
        obj_text = obj_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    mtl_refs: list[str] = []
    for line in obj_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("mtllib "):
            ref = stripped.split(None, 1)[1].strip()
            if ref:
                mtl_refs.append(ref)
    if not mtl_refs:
        return None

    for mtl_ref in mtl_refs:
        mtl_path = _resolve_material_asset_path(mtl_ref, base_dir=obj_path.parent, repo_root=repo_root)
        if mtl_path is None:
            continue
        try:
            mtl_text = mtl_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        kd: list[float] | None = None
        map_kd: Path | None = None
        for line in mtl_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, _, raw_value = stripped.partition(" ")
            key_l = key.lower()
            if key_l == "kd":
                parts = raw_value.split()
                if len(parts) >= 3:
                    try:
                        kd = [float(parts[0]), float(parts[1]), float(parts[2])]
                    except (TypeError, ValueError):
                        kd = None
            elif key_l == "map_kd":
                tex_value = _mtl_texture_value(raw_value)
                map_kd = _resolve_material_asset_path(tex_value, base_dir=mtl_path.parent, repo_root=repo_root)
        if map_kd is not None:
            return {
                "source": "obj_mtl",
                "base_color_texture_ref": str(map_kd),
                "base_color_factor": kd or [0.78, 0.78, 0.78],
                "roughness_factor": 0.35,
                "metallic_factor": 0.0,
                "mtl_ref": str(mtl_path),
            }
        if kd is not None:
            return {
                "source": "obj_mtl",
                "base_color_factor": kd,
                "roughness_factor": 0.35,
                "metallic_factor": 0.0,
                "mtl_ref": str(mtl_path),
            }
    return None


def _append_extracted_bsdf_xml(
    shape: "ET.Element",
    extracted_material: dict[str, Any],
    *,
    fallback_color: str = "0.65 0.62 0.58",
    repo_root: "Path | None" = None,
) -> bool:
    """Emit a roughplastic BSDF from a USD ``UsdPreviewSurface`` descriptor.

    Returns ``True`` when the BSDF was attached, ``False`` when the descriptor
    has nothing usable so the caller can fall back.
    """
    import xml.etree.ElementTree as ET

    base_tex = _absolutize_texture_path(extracted_material.get("base_color_texture_ref"), repo_root)
    normal_tex = _absolutize_texture_path(extracted_material.get("normal_texture_ref"), repo_root)
    base_factor = extracted_material.get("base_color_factor")
    roughness = extracted_material.get("roughness_factor")
    metallic = extracted_material.get("metallic_factor")

    # If the texture file no longer exists on disk, drop it (else mitsuba aborts the whole scene load).
    if base_tex and not Path(base_tex).exists():
        base_tex = None
    if normal_tex and not Path(normal_tex).exists():
        normal_tex = None

    has_basecolor = bool(base_tex) or (isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3)
    if not has_basecolor and not normal_tex:
        return False

    # Wrap in a two-sided BSDF so surfaces whose geometric normals face away from
    # the camera (common in imported/Blender meshes — interior walls, floors, and
    # meshes with inconsistent winding) still shade instead of rendering black.
    # Mirrors the existing twosided handling for conductor/measured BSDFs.
    twosided = ET.SubElement(shape, "bsdf", type="twosided")
    inner_bsdf_parent: "ET.Element"
    if normal_tex:
        # Mitsuba 3 normalmap BSDF wraps an inner BSDF; provide the normal as a bitmap.
        outer = ET.SubElement(twosided, "bsdf", type="normalmap")
        nm_tex = ET.SubElement(outer, "texture", attrib={"name": "normalmap", "type": "bitmap"})
        ET.SubElement(nm_tex, "string", attrib={"name": "filename", "value": str(normal_tex)})
        # ``raw`` must be a <boolean>; <string> is rejected by Mitsuba's properties parser.
        ET.SubElement(nm_tex, "boolean", attrib={"name": "raw", "value": "true"})
        inner_bsdf_parent = outer
    else:
        inner_bsdf_parent = twosided

    # Treat fully metallic materials as roughconductor; otherwise roughplastic.
    use_conductor = False
    try:
        if metallic is not None and float(metallic) > 0.5:
            use_conductor = True
    except Exception:
        pass

    if use_conductor:
        bsdf = ET.SubElement(inner_bsdf_parent, "bsdf", type="roughconductor")
        ET.SubElement(bsdf, "string", attrib={"name": "material", "value": "Al"})
        try:
            alpha = max(0.01, min(0.9, float(roughness) if roughness is not None else 0.2))
        except Exception:
            alpha = 0.2
        ET.SubElement(bsdf, "float", attrib={"name": "alpha", "value": f"{alpha:.4f}"})
    else:
        bsdf = ET.SubElement(inner_bsdf_parent, "bsdf", type="roughplastic")
        if base_tex:
            tex = ET.SubElement(bsdf, "texture", attrib={"name": "diffuse_reflectance", "type": "bitmap"})
            ET.SubElement(tex, "string", attrib={"name": "filename", "value": str(base_tex)})
        elif isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3:
            try:
                rgb = " ".join(f"{max(0.0, min(1.0, float(c))):.6g}" for c in base_factor[:3])
            except Exception:
                rgb = fallback_color
            ET.SubElement(bsdf, "rgb", attrib={"name": "diffuse_reflectance", "value": rgb})
        else:
            ET.SubElement(bsdf, "rgb", attrib={"name": "diffuse_reflectance", "value": fallback_color})
        try:
            alpha = max(0.01, min(0.9, float(roughness) if roughness is not None else 0.2))
        except Exception:
            alpha = 0.2
        ET.SubElement(bsdf, "float", attrib={"name": "alpha", "value": f"{alpha:.4f}"})
    return True


def _resolve_material_binding(material_id: str | None, material_idx: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mid = str(material_id or "").strip()
    preset_strategy = {
        "painted_wall": "roughplastic",
        "clear_glass": "dielectric",
        "frosted_glass": "roughdielectric",
        "mirror": "conductor",
        "wood": "roughplastic",
        "fabric": "roughplastic",
        "tile": "roughplastic",
        "default_floor": "roughplastic",
        "default_ceiling": "diffuse",
        "default_wall": "roughplastic",
    }
    if mid in material_idx:
        material = material_idx[mid]
        params = dict(material.get("params") or {})
        binding = dict(material.get("render_binding") or {})
        if not binding:
            # `hpbrdf_2025/...` style entries use `native_file_path`,
            # `hpbrdf_2025:...` colon-form uses `native_file`. Accept both.
            source_mid = params.get("source_material_id")
            if not source_mid and "/" in mid:
                source_mid = mid.split("/", 1)[1]
            elif not source_mid and ":" in mid:
                source_mid = mid.split(":", 1)[1]
            binding = {
                "kind": params.get("kind") or material.get("category") or "preset",
                "dataset_id": params.get("dataset_id"),
                "material_id": source_mid or mid,
                "native_file": params.get("native_file") or params.get("native_file_path"),
                "channels_dir": params.get("channels_dir"),
                "bsdf_strategy": params.get("mitsuba_strategy"),
                "capabilities": params.get("capabilities") or {},
            }
        binding.setdefault("material_id", mid)
        binding.setdefault("kind", "preset" if mid in preset_strategy else "curated")
        if not binding.get("bsdf_strategy"):
            kind = str(binding.get("kind") or "")
            binding["bsdf_strategy"] = "measured_polarized" if kind in _MEASURED_KINDS else preset_strategy.get(mid, "roughplastic")
        return binding
    if mid in preset_strategy or not mid:
        return {"kind": "preset", "material_id": mid or "default", "bsdf_strategy": preset_strategy.get(mid, "roughplastic"), "capabilities": {"rgb": True}}
    if ":" in mid or "/" in mid:
        sep = ":" if ":" in mid else "/"
        dataset_id, source_mid = mid.split(sep, 1)
        return {
            "kind": "measured",
            "dataset_id": dataset_id,
            "material_id": source_mid,
            "bsdf_strategy": "measured_polarized",
            "capabilities": {"rgb": True, "polarization": True},
            "unresolved": True,
        }
    return {"kind": "preset", "material_id": mid, "bsdf_strategy": "roughplastic", "unresolved": True, "capabilities": {"rgb": True}}


_BSDF_CHANNEL_PLACEHOLDER_NM = 542  # green, used when scene XML is generated outside per-modality dispatch

_BSDF_METAL_TOKENS = ("gold", "silver", "copper", "aluminum", "aluminium", "chrome", "steel", "brass", "platinum", "metal")
_BSDF_CERAMIC_TOKENS = ("ceramic", "alumina", "zro", "zirconia", "porcelain")
_BSDF_SOFT_TOKENS = ("silicone", "rubber", "wax", "skin", "cloth", "fabric", "velvet")


def _measured_alpha_sample_for_material(material_id: str | None) -> float:
    mid = str(material_id or "").lower()
    if "fake" in mid and "gold" in mid:
        return 0.03
    if any(tok in mid for tok in _BSDF_METAL_TOKENS):
        return 0.02
    if any(tok in mid for tok in _BSDF_CERAMIC_TOKENS):
        return 0.08
    if "billiard" in mid:
        return 0.04
    if any(tok in mid for tok in _BSDF_SOFT_TOKENS):
        return 0.12
    return 0.08


def _append_twosided_child_bsdf(shape: "ET.Element", bsdf_type: str) -> "ET.Element":
    import xml.etree.ElementTree as ET

    twosided = ET.SubElement(shape, "bsdf", type="twosided")
    return ET.SubElement(twosided, "bsdf", type=bsdf_type)

# Warm-white incandescent-ish radiance baseline (Mitsuba absolute units).
# Picked so a single small bulb noticeably lights an interior room while staying
# below film clipping at common spp/exposure. Authoring `emitter_intensity` scales this.
_DEFAULT_EMITTER_RADIANCE = (15.0, 14.0, 12.0)


def _append_area_emitter_xml(shape: "ET.Element", obj: dict[str, Any]) -> None:
    """Wrap ``shape`` with an area emitter using the object's authored radiance."""
    import xml.etree.ElementTree as ET

    radiance_raw = obj.get("emitter_radiance")
    if isinstance(radiance_raw, (list, tuple)) and len(radiance_raw) >= 3:
        try:
            base = (float(radiance_raw[0]), float(radiance_raw[1]), float(radiance_raw[2]))
        except (TypeError, ValueError):
            base = _DEFAULT_EMITTER_RADIANCE
    else:
        base = _DEFAULT_EMITTER_RADIANCE
    try:
        intensity = float(obj.get("emitter_intensity") or 1.0)
    except (TypeError, ValueError):
        intensity = 1.0
    intensity = max(0.0, intensity)
    rgb = " ".join(f"{max(0.0, c * intensity):.6g}" for c in base)
    emitter = ET.SubElement(shape, "emitter", type="area")
    ET.SubElement(emitter, "rgb", attrib={"name": "radiance", "value": rgb})


def _append_bsdf_xml(
    shape: "ET.Element",
    material_id: str | None,
    material_idx: dict[str, dict[str, Any]],
    *,
    fallback_color: str = "0.65 0.62 0.58",
    repo_root: "Path | None" = None,
    extracted_material: dict[str, Any] | None = None,
) -> None:
    import xml.etree.ElementTree as ET

    binding = _resolve_material_binding(material_id, material_idx)
    strategy = str(binding.get("bsdf_strategy") or "roughplastic")

    measured_binding = _binding_is_measured(binding)
    measured_channels_dir = _resolve_hpbrdf_channels_dir(binding, repo_root) if measured_binding else None

    # Per-material branch: HPBRDF channel-split bindings keep the measured BSDF
    # and carry source albedo as ``albedo_scale``. Non-measured materials, and
    # non-channel measured hints from OBJ sidecars, can still use the analytic
    # extracted UsdPreviewSurface/MTL material.
    prefer_source_texture = bool(
        extracted_material
        and extracted_material.get("source") == "obj_mtl"
        and extracted_material.get("base_color_texture_ref")
    )
    if extracted_material and ((prefer_source_texture and not measured_channels_dir) or not measured_binding):
        if _append_extracted_bsdf_xml(shape, extracted_material, fallback_color=fallback_color, repo_root=repo_root):
            return
    if strategy == "dielectric":
        bsdf = ET.SubElement(shape, "bsdf", type="dielectric")
        ET.SubElement(bsdf, "float", attrib={"name": "int_ior", "value": "1.5"})
        return
    if strategy == "roughdielectric":
        bsdf = ET.SubElement(shape, "bsdf", type="roughdielectric")
        ET.SubElement(bsdf, "float", attrib={"name": "alpha", "value": "0.08"})
        ET.SubElement(bsdf, "float", attrib={"name": "int_ior", "value": "1.5"})
        return
    if strategy == "conductor":
        bsdf = _append_twosided_child_bsdf(shape, "conductor")
        ET.SubElement(bsdf, "string", attrib={"name": "material", "value": "Al"})
        return
    if strategy in {"measured", "measured_polarized"}:
        # Prefer channel-split single-wavelength .pbrdf (~180 MB) over the
        # monolithic raw .hpbrdf (13 GB). At per-shape staging time we don't
        # know the render modality yet, so use a representative visible
        # wavelength placeholder; Stage 2 swaps this filename per-modality.
        chosen = None
        channels_dir = measured_channels_dir
        src_mid = _maybe_str(binding.get("material_id"))
        if channels_dir:
            chosen = f"{channels_dir.rstrip('/')}/{_BSDF_CHANNEL_PLACEHOLDER_NM}.pbrdf"
        else:
            chosen = _maybe_str(binding.get("native_file")) or _catalog_pbrdf_native_file(str(material_id or ""))
        if chosen:
            bsdf_type = "measured_polarized" if strategy == "measured_polarized" else "measured"
            bsdf = _append_twosided_child_bsdf(shape, bsdf_type)
            ET.SubElement(bsdf, "string", attrib={"name": "filename", "value": chosen})
            if bsdf_type == "measured_polarized":
                ET.SubElement(
                    bsdf,
                    "float",
                    attrib={"name": "alpha_sample", "value": f"{_measured_alpha_sample_for_material(src_mid):.4f}"},
                )
            if _binding_is_measured(binding):
                _append_measured_albedo_scale_xml(bsdf, extracted_material, repo_root=repo_root)
            return
        # No measured data available — fall through to roughplastic fallback.
    if strategy == "diffuse":
        bsdf = _append_twosided_child_bsdf(shape, "diffuse")
        ET.SubElement(bsdf, "rgb", attrib={"name": "reflectance", "value": fallback_color})
        return
    bsdf = _append_twosided_child_bsdf(shape, "roughplastic")
    ET.SubElement(bsdf, "rgb", attrib={"name": "diffuse_reflectance", "value": fallback_color})
    ET.SubElement(bsdf, "float", attrib={"name": "alpha", "value": "0.2"})


def _opticalnav_obj_comment_data(obj: dict[str, Any]) -> str:
    """Serialize an authoring object's metadata as a compact JSON string for XML comment embedding.

    Format: ``opticalnav-obj:{...json...}``  — Mitsuba ignores XML comments entirely.
    The editor parses these comments to reconstruct the authoring model from the XML.
    """
    geom = obj.get("geometry") or {}
    nav = obj.get("navigation") or {}
    data: dict[str, Any] = {
        "id": obj.get("id"),
        "type": obj.get("type"),
        "label": obj.get("label"),
        "placement": obj.get("placement") or geom.get("type"),
        "material": obj.get("material"),
        "source_ref": obj.get("source_ref"),
        "is_emitter": bool(obj.get("is_emitter")),
        "emitter_radiance": obj.get("emitter_radiance"),
        "emitter_intensity": obj.get("emitter_intensity"),
        "geometry": {
            "type": geom.get("type"),
            "center": geom.get("center"),
            "start": geom.get("start"),
            "end": geom.get("end"),
            "height_m": geom.get("height_m"),
            "thickness_m": geom.get("thickness_m"),
            "size_m": geom.get("size_m"),
            "base_height_m": geom.get("base_height_m"),
            "yaw_deg": geom.get("yaw_deg"),
            "pitch_deg": geom.get("pitch_deg"),
            "roll_deg": geom.get("roll_deg"),
            "scale": geom.get("scale"),
        },
        "nav": {
            "blocks": bool(nav.get("blocks_navigation")),
            "hazard_type": nav.get("hazard_type"),
            "include_hazard_mask": bool(nav.get("include_in_hazard_mask")),
            "goal_candidate": bool(nav.get("goal_candidate")),
            "instruction_candidate": bool(nav.get("instruction_candidate")),
        },
    }
    return "opticalnav-obj:" + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _extract_opticalnav_objects_from_xml(xml_path: "Path") -> list[dict[str, Any]]:
    """Parse opticalnav-obj JSON comments from render_scene.xml → authoring object dicts.

    Room-shell shapes (type '__room_shell__') are filtered out.
    Returns an empty list if the file does not exist or has no embedded metadata.
    """
    import xml.etree.ElementTree as ET
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        tree = ET.parse(str(xml_path), parser=parser)
    except Exception:
        return []
    objects: list[dict[str, Any]] = []
    for child in tree.getroot():
        if not callable(child.tag):
            continue
        text = (child.text or "").strip()
        if not text.startswith("opticalnav-obj:"):
            continue
        try:
            data = json.loads(text[len("opticalnav-obj:"):])
        except Exception:
            continue
        if isinstance(data, dict) and data.get("type") != "__room_shell__":
            objects.append(data)
    return objects


def _extract_opticalnav_scene_meta_from_xml(xml_path: "Path") -> "dict[str, Any] | None":
    """Parse the opticalnav-scene JSON comment from render_scene.xml.

    Returns None if the file does not exist or has no scene metadata comment.
    """
    import xml.etree.ElementTree as ET
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        tree = ET.parse(str(xml_path), parser=parser)
    except Exception:
        return None
    for child in tree.getroot():
        if not callable(child.tag):
            continue
        text = (child.text or "").strip()
        if not text.startswith("opticalnav-scene:"):
            continue
        try:
            return json.loads(text[len("opticalnav-scene:"):])
        except Exception:
            return None
    return None


_MATERIALIZATION_STATUS_LABELS = {
    "obj": "OBJ mesh",
    "fallback_cube": "Cube fallback",
    "emitter_cube": "Emitter cube (intentional)",
    "cube": "Cube (wall/line)",
    "dropped": "Dropped",
}


def _classify_extracted_material(em: dict[str, Any] | None) -> str:
    """PR2.5b: bucket the result of UsdShade extraction so the UI / next-round fix
    can target the dominant failure mode.

    Returns one of:
      ``"missing"``                       — no extraction record at all.
      ``"black_basecolor_suspected"``     — base_color_factor sums to ~0 or RGB
                                             all under 0.05 (visually black).
      ``"opacity_below_1"``               — opacity_factor < 1 → glass/dielectric
                                             candidate that's currently rendered
                                             as opaque roughplastic.
      ``"texture_connection_unresolved"`` — extraction kept a texture asset path
                                             but the daemon couldn't resolve /
                                             copy it (asset string remains but
                                             the ``_ref`` field is null).
      ``"ok"``                            — anything else with a non-trivial
                                             base color or texture.
    """
    if not em:
        return "missing"
    try:
        opacity = em.get("opacity_factor")
        if opacity is not None and float(opacity) < 0.99:
            return "opacity_below_1"
    except (TypeError, ValueError):
        pass
    base_factor = em.get("base_color_factor")
    has_base_tex = bool(em.get("base_color_texture_ref"))
    if isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3:
        try:
            rgb = [float(c) for c in base_factor[:3]]
        except (TypeError, ValueError):
            rgb = None
        if rgb is not None and not has_base_tex:
            if sum(rgb) < 0.05 or all(c < 0.05 for c in rgb):
                return "black_basecolor_suspected"
    # An asset path was extracted but the daemon couldn't resolve it (PR1's
    # ``_opticalnav_cache_texture`` returns None and leaves the ``_ref`` null).
    has_base_asset = bool(em.get("base_color_asset"))
    if has_base_asset and not has_base_tex:
        return "texture_connection_unresolved"
    return "ok"


def _build_materialization_audit(
    *,
    scene_id: str,
    overlay_objects: list[dict[str, Any]],
    materialization_records: list[dict[str, Any]],
    mesh_stats: dict[str, int] | None,
) -> dict[str, Any]:
    """Aggregate per-object materialization records into PR1's audit sidecar."""
    summary = {
        "total": len(materialization_records),
        "obj_shapes": sum(1 for r in materialization_records if r.get("status") == "obj"),
        "fallback_cubes": sum(1 for r in materialization_records if r.get("status") == "fallback_cube"),
        "emitter_cubes": sum(1 for r in materialization_records if r.get("status") == "emitter_cube"),
        "wall_cubes": sum(1 for r in materialization_records if r.get("status") == "cube"),
        "dropped": sum(1 for r in materialization_records if r.get("status") == "dropped"),
    }
    by_reason: dict[str, int] = {}
    for r in materialization_records:
        reason = r.get("reason")
        if reason:
            by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
    # PR2.5b: aggregate the per-object extracted_material_status into a breakdown
    # so the UI can show "81 ok · 13 missing · 6 black_basecolor_suspected" without
    # walking the full per-object list. Only USD-prim records carry a status.
    material_breakdown: dict[str, int] = {}
    for r in materialization_records:
        ex = r.get("extras") or {}
        if not isinstance(ex, dict):
            continue
        status = ex.get("extracted_material_status")
        if status and status != "n/a":
            material_breakdown[str(status)] = material_breakdown.get(str(status), 0) + 1
    return {
        "version": "opticalnav-materialization-v1",
        "scene_id": scene_id,
        "generated_at": _utc_now_iso(),
        "summary": summary,
        "fallback_breakdown": by_reason,
        "material_extraction_breakdown": material_breakdown,
        "mesh_stats": dict(mesh_stats or {}),
        "objects": materialization_records,
    }


def _build_xml_scene_index(
    xml_path: Path,
    *,
    scene_id: str,
    materialization_records: list[dict[str, Any]] | None = None,
    preview_mesh_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Walk render_scene.xml and emit a per-shape index for the editor / patch API.

    Reuses :func:`_extract_opticalnav_scene_meta_from_xml` for the head comment and
    :func:`_extract_opticalnav_objects_from_xml` for the per-shape comment fields,
    then walks the actual ``<shape>``/``<emitter>``/``<sensor>`` elements to pick
    up XML-side data (shape_type, mesh filename, bsdf_ref, transform). Floor and
    room-shell shapes are tagged via their ``__room_shell__`` / ``opticalnav-floor``
    comment markers.
    """
    if not xml_path.exists():
        return None
    import xml.etree.ElementTree as ET
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        tree = ET.parse(str(xml_path), parser=parser)
    except Exception:
        return None
    root = tree.getroot()
    try:
        mtime_ns = int(xml_path.stat().st_mtime_ns)
    except OSError:
        mtime_ns = 0

    # Map shape_id → object record (from PR1's materialization_records) for cross-ref.
    mat_by_shape: dict[str, dict[str, Any]] = {}
    for rec in materialization_records or []:
        sid = str(rec.get("shape_id") or rec.get("object_id") or "")
        if sid:
            mat_by_shape[sid] = rec

    # Helper: read a <transform name="to_world"> into a flat dict.
    def _read_transform(elem: "ET.Element") -> dict[str, Any] | None:
        xf = elem.find("./transform[@name='to_world']")
        if xf is None:
            return None
        out: dict[str, Any] = {}
        for child in xf:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "translate":
                out["translate"] = [float(child.attrib.get("x", 0)), float(child.attrib.get("y", 0)), float(child.attrib.get("z", 0))]
            elif child.tag == "scale":
                out["scale"] = [float(child.attrib.get("x", 1)), float(child.attrib.get("y", 1)), float(child.attrib.get("z", 1))]
            elif child.tag == "rotate":
                axis = "y" if "y" in child.attrib else ("x" if "x" in child.attrib else ("z" if "z" in child.attrib else "y"))
                key = f"rotate_{axis}_deg"
                try:
                    out[key] = float(child.attrib.get("angle", 0))
                except (TypeError, ValueError):
                    out[key] = 0.0
        return out

    # Walk children. Comments alternate with shapes — we use a pending marker.
    shapes: list[dict[str, Any]] = []
    emitters: list[dict[str, Any]] = []
    sensors: list[dict[str, Any]] = []
    pending_marker: dict[str, Any] | None = None

    for child in root:
        if not isinstance(child.tag, str):
            # Comment node — peek for floor/room-shell markers.
            text = (child.text or "").strip()
            if text.startswith("opticalnav-floor:"):
                try:
                    pending_marker = json.loads(text[len("opticalnav-floor:"):])
                    pending_marker["_marker_type"] = "floor"
                except Exception:
                    pending_marker = None
            elif text.startswith("opticalnav-obj:"):
                try:
                    data = json.loads(text[len("opticalnav-obj:"):])
                    if isinstance(data, dict):
                        data["_marker_type"] = "object"
                        pending_marker = data
                except Exception:
                    pending_marker = None
            else:
                # Other comments (room-shell, scene head, dedupe noise) — leave pending alone.
                if text.startswith("{"):
                    try:
                        meta = json.loads(text)
                        if isinstance(meta, dict) and meta.get("type") == "__room_shell__":
                            pending_marker = {"_marker_type": "room_shell", "role": meta.get("role")}
                    except Exception:
                        pass
            continue

        if child.tag == "shape":
            shape_type = child.attrib.get("type") or "unknown"
            shape_id = child.attrib.get("id") or ""
            mesh_path: str | None = None
            fn = child.find("./string[@name='filename']")
            if fn is not None:
                mesh_path = fn.attrib.get("value")
            bsdf_ref: str | None = None
            ref = child.find("./ref")
            if ref is not None:
                bsdf_ref = ref.attrib.get("id")
            rec: dict[str, Any] = {
                "shape_id": shape_id,
                "shape_type": shape_type,
                "mesh_path": mesh_path,
                "bsdf_ref": bsdf_ref,
                "transform": _read_transform(child),
            }
            preview_rec = None
            if preview_mesh_manifest and shape_id:
                candidate = preview_mesh_manifest.get(shape_id)
                if isinstance(candidate, Mapping):
                    preview_rec = dict(candidate)
            if preview_rec:
                rec.update(preview_rec)

            mat_rec = mat_by_shape.get(shape_id) if shape_id else None
            if mat_rec:
                rec["fallback"] = mat_rec.get("status") == "fallback_cube"
                rec["fallback_reason"] = mat_rec.get("reason") if rec["fallback"] else None
                rec["source_ref"] = mat_rec.get("source_ref")
                rec["material_id"] = mat_rec.get("material_id")
                rec["object_id"] = mat_rec.get("object_id")
            elif pending_marker and pending_marker.get("_marker_type") == "floor":
                rec["xml_role"] = "floor"
                rec["material_id"] = pending_marker.get("material_id")
                rec["extras"] = {"region_id": pending_marker.get("region_id"), "shape_id_marker": pending_marker.get("shape_id")}
                rec["fallback"] = False
                rec.setdefault("editor_layer", "floor")
                rec.setdefault("editor_pickable", False)
                if rec.get("transform"):
                    rec.setdefault("editor_proxy", {"kind": "floor", "material_hint": rec.get("material_id")})
            elif pending_marker and pending_marker.get("_marker_type") == "room_shell":
                rec["xml_role"] = f"shell_{pending_marker.get('role') or 'unknown'}"
                rec["fallback"] = False
                rec.setdefault("editor_layer", "shell")
                rec.setdefault("editor_pickable", False)
                rec.setdefault("editor_proxy", {"kind": pending_marker.get("role") or "shell", "material_hint": rec.get("material_id")})
            pending_marker = None
            shapes.append(rec)
        elif child.tag == "emitter":
            emit_type = child.attrib.get("type") or "unknown"
            emit_rec: dict[str, Any] = {"emitter_id": child.attrib.get("id") or f"emitter_{emit_type}", "type": emit_type}
            fn = child.find("./string[@name='filename']")
            if fn is not None:
                emit_rec["filename"] = fn.attrib.get("value")
            scale = child.find("./float[@name='scale']")
            if scale is not None:
                try:
                    emit_rec["intensity"] = float(scale.attrib.get("value", 1.0))
                except (TypeError, ValueError):
                    pass
            emitters.append(emit_rec)
            pending_marker = None
        elif child.tag == "sensor":
            sensor_rec: dict[str, Any] = {
                "sensor_id": child.attrib.get("id") or "sensor_default",
                "type": child.attrib.get("type") or "unknown",
            }
            fov = child.find("./float[@name='fov']")
            if fov is not None:
                try:
                    sensor_rec["fov_deg"] = float(fov.attrib.get("value", 0))
                except (TypeError, ValueError):
                    pass
            film = child.find("./film")
            if film is not None:
                w = film.find("./integer[@name='width']")
                h = film.find("./integer[@name='height']")
                try:
                    sensor_rec["resolution"] = [int(w.attrib.get("value", 0)) if w is not None else 0,
                                                int(h.attrib.get("value", 0)) if h is not None else 0]
                except (TypeError, ValueError):
                    pass
            sensors.append(sensor_rec)
            pending_marker = None

    return {
        "version": "opticalnav-xml-index-v1",
        "scene_id": scene_id,
        "xml_path": str(xml_path),
        "xml_mtime_ns": mtime_ns,
        "shapes": shapes,
        "emitters": emitters,
        "sensors": sensors,
        "scene_meta": _extract_opticalnav_scene_meta_from_xml(xml_path),
    }


_PREVIEW_MESH_CACHE_VERSION = 1
_DEFAULT_PREVIEW_TARGET_FACES = 5000


def _preview_mesh_target_faces() -> int:
    raw = os.environ.get("ROBOMITUBA_PREVIEW_MESH_TARGET_FACES")
    if raw:
        try:
            return max(256, min(50000, int(raw)))
        except (TypeError, ValueError):
            pass
    return _DEFAULT_PREVIEW_TARGET_FACES


def _scan_obj_bounds_and_faces(path: Path) -> dict[str, Any]:
    vertices: list[tuple[float, float, float]] = []
    face_count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.lstrip()
                if stripped.startswith("v "):
                    parts = stripped.split()
                    if len(parts) >= 4:
                        try:
                            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                        except (TypeError, ValueError):
                            continue
                elif stripped.startswith("f "):
                    # OBJ polygons may be n-gons; count the triangulated face budget.
                    n = max(0, len(stripped.split()) - 1)
                    face_count += max(1, n - 2) if n >= 3 else 0
    except OSError as exc:
        return {"error": str(exc), "vertex_count": 0, "face_count": 0}
    if not vertices:
        return {"vertex_count": 0, "face_count": face_count}
    arr = np.asarray(vertices, dtype=np.float64)
    mn = arr.min(axis=0)
    mx = arr.max(axis=0)
    size = np.maximum(mx - mn, 1e-6)
    center = (mn + mx) * 0.5
    return {
        "vertex_count": int(len(vertices)),
        "face_count": int(face_count),
        "bounds": {
            "min": mn.astype(float).tolist(),
            "max": mx.astype(float).tolist(),
            "size": size.astype(float).tolist(),
            "center": center.astype(float).tolist(),
        },
    }


def _preview_architecture_kind(shape_id: str, rec: Mapping[str, Any] | None, mesh_info: Mapping[str, Any]) -> str | None:
    extras = rec.get("extras") if isinstance(rec, Mapping) and isinstance(rec.get("extras"), Mapping) else {}

    def _basename(value: Any) -> str:
        text = str(value or "")
        if "#" in text:
            text = text.rsplit("#", 1)[-1]
        return Path(text).name

    name_tokens = " ".join(
        str(v or "")
        for v in (
            shape_id,
            rec.get("object_id") if isinstance(rec, Mapping) else None,
            rec.get("label") if isinstance(rec, Mapping) else None,
            rec.get("type") if isinstance(rec, Mapping) else None,
            _basename(rec.get("source_ref") if isinstance(rec, Mapping) else None),
            extras.get("mesh_name") if isinstance(extras, Mapping) else None,
            _basename(extras.get("mesh_prim_path") if isinstance(extras, Mapping) else None),
        )
    ).lower()
    material_id = str(rec.get("material_id") or "").lower() if isinstance(rec, Mapping) else ""

    # Guard common movable/prop factories before architecture checks. Infinigen
    # imports often use type=landmark and paths like indoor_seed2; substring tests
    # on the whole path previously matched "door" inside "indoor" and classified
    # nearly everything as architecture.
    non_arch_tokens = (
        "chair", "table", "desk", "shelf", "cabinet", "sofa", "couch", "bed",
        "comforter", "pillow", "book", "bottle", "bowl", "cup", "plate", "fork",
        "spoon", "chopstick", "plant", "vase", "lamp", "light", "monitor",
        "keyboard", "mouse", "printer", "toilet", "sink", "stove", "fridge",
        "door",
    )
    if any(tok in name_tokens for tok in non_arch_tokens):
        return None

    arch_text = name_tokens
    if material_id in {"default_floor", "default_wall", "default_ceiling"}:
        arch_text += f" {material_id}"

    if any(tok in arch_text for tok in ("ceiling", "roof")):
        return "ceiling"
    if any(tok in arch_text for tok in ("floor", "ground", "slab", "tile")):
        return "floor"
    if any(tok in arch_text for tok in ("wall", "shell", "partition")):
        return "wall"
    if any(tok in arch_text for tok in ("glass", "window", "pane")):
        return "glass"

    bounds = mesh_info.get("bounds") if isinstance(mesh_info, Mapping) else None
    size = bounds.get("size") if isinstance(bounds, Mapping) else None
    if isinstance(size, list) and len(size) >= 3:
        sx, sy, sz = [float(v or 0.0) for v in size[:3]]
        max_xz = max(sx, sz, 1e-6)
        min_xz = max(min(sx, sz), 1e-6)
        # Geometry fallback only catches very large room-scale surfaces. Do not
        # infer architecture from polygon count alone; furniture can be very dense.
        if max_xz >= 8.0 and sy <= max_xz * 0.06:
            return "floor"
        if sy >= 1.5 and max_xz >= 5.0 and min_xz <= max_xz * 0.08:
            return "wall"
    return None


def _preview_mesh_ref_for_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _write_decimated_preview_obj(src: Path, dst: Path, target_faces: int) -> tuple[int, str | None]:
    try:
        import trimesh
    except Exception as exc:
        return 0, f"trimesh_unavailable: {exc}"
    try:
        mesh = trimesh.load(src, force="mesh", process=False)
        if mesh is None or getattr(mesh, "faces", None) is None or len(mesh.faces) == 0:
            return 0, "mesh_empty"
        simplified = mesh.simplify_quadric_decimation(face_count=int(target_faces))
        if simplified is None or getattr(simplified, "faces", None) is None or len(simplified.faces) == 0:
            return 0, "simplified_mesh_empty"
        tmp = dst.with_name(f"{dst.stem}.tmp.{os.getpid()}.{threading.get_ident()}{dst.suffix}")
        simplified.export(tmp)
        tmp.replace(dst)
        return int(len(simplified.faces)), None
    except Exception as exc:
        return 0, str(exc)


def _build_editor_preview_mesh_manifest(
    xml_path: Path,
    *,
    scene_mesh_cache_dir: Path,
    repo_root: Path,
    materialization_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create editor-only preview metadata for OBJ shapes in a synced scene.

    Full OBJ paths in render_scene.xml remain authoritative for Mitsuba. This pass
    only adds lightweight editor hints: decimated preview OBJs for ordinary assets,
    or non-pickable architecture proxy metadata for room-scale shells.
    """
    import xml.etree.ElementTree as ET

    target_faces = _preview_mesh_target_faces()
    by_shape: dict[str, dict[str, Any]] = {}
    stats: dict[str, Any] = {
        "target_faces": target_faces,
        "ready": 0,
        "skipped_small": 0,
        "skipped_full_mesh": 0,
        "architecture_proxy": 0,
        "failed": 0,
        "unavailable": 0,
    }
    if not xml_path.exists():
        stats["error"] = "xml_missing"
        return {"version": _PREVIEW_MESH_CACHE_VERSION, "stats": stats, "shapes": by_shape}
    try:
        tree = ET.parse(str(xml_path))
    except Exception as exc:
        stats["error"] = str(exc)
        return {"version": _PREVIEW_MESH_CACHE_VERSION, "stats": stats, "shapes": by_shape}

    mat_by_shape: dict[str, dict[str, Any]] = {}
    for rec in materialization_records or []:
        sid = str(rec.get("shape_id") or rec.get("object_id") or "")
        if sid:
            mat_by_shape[sid] = rec

    scene_mesh_cache_dir.mkdir(parents=True, exist_ok=True)
    for shape in tree.getroot().findall(".//shape"):
        if shape.attrib.get("type") != "obj":
            continue
        shape_id = shape.attrib.get("id") or ""
        if not shape_id:
            continue
        fn = shape.find("./string[@name='filename']")
        raw = fn.attrib.get("value") if fn is not None else ""
        if not raw:
            continue
        try:
            src = resolve_repo_path(repo_root, raw)
        except Exception:
            src = Path(raw)
        if not src.is_file():
            by_shape[shape_id] = {
                "preview_mesh_status": "unavailable",
                "preview_mesh_reason": "source_obj_missing",
                "editor_layer": "object",
                "editor_pickable": True,
            }
            stats["unavailable"] += 1
            continue
        mesh_info = _scan_obj_bounds_and_faces(src)
        face_count = int(mesh_info.get("face_count") or 0)
        rec = mat_by_shape.get(shape_id)
        arch_kind = _preview_architecture_kind(shape_id, rec, mesh_info)
        is_architecture = bool(arch_kind)
        editor_layer = "architecture" if is_architecture else "object"
        editor_pickable = not is_architecture
        editor_proxy = {
            "kind": arch_kind,
            "bounds": mesh_info.get("bounds"),
            "material_hint": rec.get("material_id") if isinstance(rec, Mapping) else None,
        } if is_architecture else None
        if face_count <= 0:
            if is_architecture:
                by_shape[shape_id] = {
                    "preview_mesh_status": "architecture_proxy",
                    "preview_mesh_reason": mesh_info.get("error") or f"classified_{arch_kind}_face_count_unavailable",
                    "source_mesh_faces": face_count,
                    "editor_layer": editor_layer,
                    "editor_pickable": editor_pickable,
                    "editor_proxy": editor_proxy,
                }
                stats["architecture_proxy"] += 1
            else:
                by_shape[shape_id] = {
                    "preview_mesh_status": "failed",
                    "preview_mesh_reason": mesh_info.get("error") or "face_count_unavailable",
                    "source_mesh_faces": face_count,
                    "editor_layer": editor_layer,
                    "editor_pickable": editor_pickable,
                }
                stats["failed"] += 1
            continue
        if face_count <= target_faces:
            ref = _preview_mesh_ref_for_path(src, repo_root)
            by_shape[shape_id] = {
                "preview_mesh_path": ref,
                "preview_mesh_faces": face_count,
                "source_mesh_faces": face_count,
                "preview_mesh_status": "skipped_small",
                "editor_layer": editor_layer,
                "editor_pickable": editor_pickable,
                **({"editor_proxy": editor_proxy} if editor_proxy else {}),
            }
            stats["skipped_small"] += 1
            continue
        try:
            stat = src.stat()
            digest = hashlib.sha1(
                f"{src.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|faces{target_faces}|preview_obj_v{_PREVIEW_MESH_CACHE_VERSION}".encode("utf-8")
            ).hexdigest()[:16]
        except OSError:
            digest = hashlib.sha1(f"{src}|faces{target_faces}|preview_obj_v{_PREVIEW_MESH_CACHE_VERSION}".encode("utf-8")).hexdigest()[:16]
        dst = scene_mesh_cache_dir / f"preview_{digest}_f{target_faces}.obj"
        preview_faces = 0
        reason = None
        if dst.exists():
            cached_info = _scan_obj_bounds_and_faces(dst)
            preview_faces = int(cached_info.get("face_count") or 0)
            if preview_faces <= 0:
                reason = "cached_preview_invalid"
        if not dst.exists() or reason:
            try:
                dst.unlink(missing_ok=True)
            except OSError:
                pass
            preview_faces, reason = _write_decimated_preview_obj(src, dst, target_faces)
        if preview_faces > 0 and dst.exists():
            by_shape[shape_id] = {
                "preview_mesh_path": _preview_mesh_ref_for_path(dst, repo_root),
                "preview_mesh_faces": preview_faces,
                "source_mesh_faces": face_count,
                "preview_mesh_status": "ready",
                "editor_layer": editor_layer,
                "editor_pickable": editor_pickable,
                **({"editor_proxy": editor_proxy} if editor_proxy else {}),
            }
            stats["ready"] += 1
        else:
            if is_architecture:
                try:
                    src_size = src.stat().st_size
                except OSError:
                    src_size = 0
                if src_size and src_size <= 16 * 1024 * 1024:
                    by_shape[shape_id] = {
                        "preview_mesh_path": _preview_mesh_ref_for_path(src, repo_root),
                        "preview_mesh_faces": face_count,
                        "source_mesh_faces": face_count,
                        "preview_mesh_status": "skipped_full_mesh",
                        "preview_mesh_reason": reason or f"classified_{arch_kind}_decimation_failed_using_full_mesh",
                        "editor_layer": editor_layer,
                        "editor_pickable": editor_pickable,
                        "editor_proxy": editor_proxy,
                    }
                    stats["skipped_full_mesh"] += 1
                else:
                    by_shape[shape_id] = {
                        "preview_mesh_status": "architecture_proxy",
                        "preview_mesh_reason": reason or f"classified_{arch_kind}_decimation_failed",
                        "source_mesh_faces": face_count,
                        "editor_layer": editor_layer,
                        "editor_pickable": editor_pickable,
                        "editor_proxy": editor_proxy,
                    }
                    stats["architecture_proxy"] += 1
            else:
                by_shape[shape_id] = {
                    "preview_mesh_status": "failed",
                    "preview_mesh_reason": reason or "decimation_failed",
                    "source_mesh_faces": face_count,
                    "editor_layer": editor_layer,
                    "editor_pickable": editor_pickable,
                }
                stats["failed"] += 1
    return {"version": _PREVIEW_MESH_CACHE_VERSION, "stats": stats, "shapes": by_shape}


_SCENE_MESH_CACHE_OBJ_VERSION = 2


def _write_normalized_obj_for_scene_cache(src: Path, dst: Path) -> dict[str, Any]:
    """Write OBJ with vertices centered in X/Z and bottom-aligned to Y=0."""
    text = src.read_text(encoding="utf-8", errors="replace")
    rows = text.splitlines(keepends=True)
    vertices: list[tuple[float, float, float]] = []
    for line in rows:
        stripped = line.lstrip()
        if not stripped.startswith("v "):
            continue
        prefix_len = len(line) - len(stripped)
        parts = stripped.split()
        if len(parts) < 4:
            continue
        try:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        except (TypeError, ValueError):
            continue
    if not vertices:
        shutil.copy2(src, dst)
        return {"normalized": False, "vertex_count": 0}

    min_x = min(v[0] for v in vertices)
    max_x = max(v[0] for v in vertices)
    min_y = min(v[1] for v in vertices)
    min_z = min(v[2] for v in vertices)
    max_z = max(v[2] for v in vertices)
    off_x = (min_x + max_x) / 2.0
    off_y = min_y
    off_z = (min_z + max_z) / 2.0

    out: list[str] = []
    for line in rows:
        stripped = line.lstrip()
        if not stripped.startswith("v "):
            out.append(line)
            continue
        leading = line[:len(line) - len(stripped)]
        newline = "\n" if line.endswith("\n") else ""
        parts = stripped.split()
        if len(parts) < 4:
            out.append(line)
            continue
        try:
            x = float(parts[1]) - off_x
            y = float(parts[2]) - off_y
            z = float(parts[3]) - off_z
        except (TypeError, ValueError):
            out.append(line)
            continue
        suffix = ""
        if len(parts) > 4:
            suffix = " " + " ".join(parts[4:])
        out.append(f"{leading}v {x:.8g} {y:.8g} {z:.8g}{suffix}{newline}")
    dst.write_text("".join(out), encoding="utf-8")
    return {
        "normalized": True,
        "vertex_count": len(vertices),
        "source_bounds": {
            "min": [min_x, min_y, min_z],
            "max": [max_x, max(v[1] for v in vertices), max_z],
            "center_xz": [off_x, off_z],
        },
        "offset_applied": [off_x, off_y, off_z],
    }


def _stage_xml_obj_filenames_to_scene_mesh_cache(
    xml_path: Path,
    *,
    scene_mesh_cache_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    """Copy OBJ files referenced by render_scene.xml into scene-local mesh_cache.

    The browser editor fetches OBJ preview geometry only through
    ``/scenes/<scene_id>/mesh-cache/<filename>``. Mitsuba can load absolute or
    repo-relative OBJ paths, but the editor cannot serve those directly. This
    pass stages every OBJ filename from the XML into the scene's ``mesh_cache``
    and rewrites the XML filename to the staged repo-relative path.
    """
    if not xml_path.exists():
        return {"staged": 0, "missing": 0, "rewritten": 0}
    import xml.etree.ElementTree as ET

    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        tree = ET.parse(str(xml_path), parser=parser)
    except Exception as exc:
        return {"staged": 0, "missing": 0, "rewritten": 0, "error": str(exc)}

    scene_mesh_cache_dir.mkdir(parents=True, exist_ok=True)
    staged = 0
    missing = 0
    rewritten = 0
    root = tree.getroot()
    for shape in root.findall(".//shape"):
        if shape.attrib.get("type") != "obj":
            continue
        fn = shape.find("./string[@name='filename']")
        if fn is None:
            continue
        raw = fn.attrib.get("value") or ""
        if not raw.lower().endswith(".obj"):
            continue
        try:
            src = resolve_repo_path(repo_root, raw)
        except Exception:
            src = Path(raw)
        if not src.exists() or not src.is_file():
            missing += 1
            continue
        try:
            stat = src.stat()
        except OSError:
            missing += 1
            continue
        digest = hashlib.sha1(
            f"{src.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|stage_obj_v{_SCENE_MESH_CACHE_OBJ_VERSION}".encode("utf-8")
        ).hexdigest()[:16]
        dst = scene_mesh_cache_dir / f"{digest}.obj"
        if src.resolve() != dst.resolve() and not dst.exists():
            tmp = scene_mesh_cache_dir / f"{digest}.tmp.{os.getpid()}.{threading.get_ident()}.obj"
            try:
                _write_normalized_obj_for_scene_cache(src, tmp)
                try:
                    tmp.replace(dst)
                except FileNotFoundError:
                    pass
                staged += 1
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                missing += 1
                continue
        # Write the staged path as absolute. Mitsuba loads the XML from
        # `.staged_mitsuba/base/<hash>.xml` and resolves relative paths against
        # *that* directory — a repo-relative `out/opticalnav/.../<digest>.obj`
        # silently fails to load. The editor reads mesh paths from
        # xml_scene_index.json (where mesh_path is recorded separately as a
        # repo-relative path for the /mesh-cache/<filename> endpoint), so the
        # XML filename does not need to be repo-relative.
        staged_ref = str(dst.resolve())
        if raw != staged_ref:
            fn.set("value", staged_ref)
            rewritten += 1

    if rewritten:
        try:
            ET.indent(tree, space="  ")
        except Exception:
            pass
        tree.write(str(xml_path), encoding="utf-8", xml_declaration=True)
    return {"staged": staged, "missing": missing, "rewritten": rewritten}


def _glb_cache_write_meta(cache_dir: Path, payload: dict[str, Any]) -> None:
    """Drop a small ``meta.json`` next to the cached OBJ so PR1 / debug UIs can read it."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        meta_path = cache_dir / "meta.json"
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _mirror_glb_obj_to_scene_mesh_cache(
    obj_path: Path, digest: str, scene_mesh_cache_dir: "Path | None"
) -> Path:
    """Mirror a global glb_obj_cache OBJ into the scene's mesh_cache so the
    frontend's basename-based ``/mesh-cache/<filename>`` endpoint can serve it
    alongside USD-prim OBJs. Returns the scene-local path when mirroring works,
    otherwise the original global path."""
    if scene_mesh_cache_dir is None:
        return obj_path
    try:
        scene_mesh_cache_dir.mkdir(parents=True, exist_ok=True)
        local = scene_mesh_cache_dir / f"glb_{digest}.obj"
        if not local.exists() or local.stat().st_size != obj_path.stat().st_size:
            try:
                if local.exists():
                    local.unlink()
                os.link(obj_path, local)
            except (OSError, AttributeError):
                import shutil
                shutil.copyfile(obj_path, local)
        return local
    except OSError:
        return obj_path


def _materialize_glb_obj_for_overlay(
    source_ref: str,
    *,
    repo_root: "Path | None",
    mesh_stats: "dict[str, int] | None" = None,
    detail_out: "dict[str, Any] | None" = None,
    scene_mesh_cache_dir: "Path | None" = None,
    scene_texture_cache_dir: "Path | None" = None,
) -> "Path | None":
    """Convert a repo-local GLB source into cached OBJ part meshes for Mitsuba.

    DTC GLBs carry embedded PBR textures. The adapter exports OBJ geometry into
    the scene mesh cache and extracts embedded PBR textures into the scene
    texture cache, returning metadata in the same shape as USD ``mesh_parts``.
    """
    if repo_root is None:
        if detail_out is not None:
            detail_out.update({"stage": "skipped", "error": "repo_root not set"})
        return None
    lower = source_ref.lower()
    if not (lower.endswith(".glb") or lower.endswith(".gltf")):
        if detail_out is not None:
            detail_out.update({"stage": "skipped", "error": "not a GLB/GLTF source"})
        return None
    try:
        glb_path = resolve_repo_path(repo_root, source_ref)
    except Exception:
        glb_path = Path(source_ref)
    if not glb_path.exists():
        if mesh_stats is not None:
            mesh_stats["glb_missing"] = mesh_stats.get("glb_missing", 0) + 1
        if detail_out is not None:
            detail_out.update({"stage": "load", "error": "glb file not found", "source_path": str(glb_path)})
        return None
    if scene_mesh_cache_dir is None:
        try:
            stat = glb_path.stat()
            digest = hashlib.sha1(
                f"{glb_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|legacy_glb_adapter".encode("utf-8")
            ).hexdigest()[:16]
        except OSError:
            digest = hashlib.sha1(str(glb_path).encode("utf-8")).hexdigest()[:16]
        scene_mesh_cache_dir = repo_root / "out" / "control_plane_cache" / "glb_obj_cache" / digest
    try:
        from .glb_texture_adapter import materialize_glb_texture_parts

        result = materialize_glb_texture_parts(
            source_ref,
            glb_path=glb_path,
            repo_root=repo_root,
            mesh_cache_dir=scene_mesh_cache_dir,
            texture_cache_dir=scene_texture_cache_dir,
        )
        if result.status != "ok":
            if mesh_stats is not None:
                mesh_stats["glb_materialize_error"] = mesh_stats.get("glb_materialize_error", 0) + 1
            if detail_out is not None:
                detail_out.update({"stage": "export", "error": result.error or "glb materialization failed"})
            return None
        meta = result.to_meta()
        if detail_out is not None:
            detail_out.update({"stage": "ok", "cache_obj": result.combined_obj_ref, "digest": result.digest, **meta})
        if mesh_stats is not None:
            mesh_stats["glb_obj_materialized"] = mesh_stats.get("glb_obj_materialized", 0) + 1
            mesh_stats["glb_mesh_parts"] = mesh_stats.get("glb_mesh_parts", 0) + int(result.mesh_part_count)
            if result.texture_slots.get("base_color"):
                mesh_stats["glb_base_textures"] = mesh_stats.get("glb_base_textures", 0) + int(result.texture_slots.get("base_color") or 0)
        return result.combined_obj_path
    except Exception as exc:
        if mesh_stats is not None:
            mesh_stats["glb_materialize_error"] = mesh_stats.get("glb_materialize_error", 0) + 1
        if detail_out is not None:
            detail_out.update({"stage": "export", "error": str(exc)})
        return None

def _wall_shape_xml_element(obj: dict[str, Any], material_idx: dict[str, dict[str, Any]], *, repo_root: "Path | None" = None) -> "ET.Element | None":
    """Return a Mitsuba cube <shape> element for a wall/glass overlay object, or None."""
    import math
    import xml.etree.ElementTree as ET

    geom = obj.get("geometry") or {}
    if geom.get("type") != "line":
        return None
    start = geom.get("start")
    end = geom.get("end")
    if not start or not end or len(start) < 2 or len(end) < 2:
        return None
    x1, z1 = float(start[0]), float(start[1])
    x2, z2 = float(end[0]), float(end[1])
    length = math.hypot(x2 - x1, z2 - z1)
    if length < 1e-4:
        return None
    height_m = float(geom.get("height_m") or 2.4)
    thickness_m = float(geom.get("thickness_m") or 0.08)
    cx, cz, cy = (x1 + x2) / 2, (z1 + z2) / 2, height_m / 2
    angle_deg = math.degrees(math.atan2(z2 - z1, x2 - x1))
    shape = ET.Element("shape", type="cube", id=str(obj.get("id") or obj.get("label") or "wall"))
    xf = ET.SubElement(shape, "transform", attrib={"name": "to_world"})
    ET.SubElement(xf, "scale", x=f"{length / 2:.6f}", y=f"{height_m / 2:.6f}", z=f"{thickness_m / 2:.6f}")
    ET.SubElement(xf, "rotate", y="1", angle=f"{angle_deg:.4f}")
    ET.SubElement(xf, "translate", x=f"{cx:.6f}", y=f"{cy:.6f}", z=f"{cz:.6f}")
    if bool(obj.get("is_emitter")):
        _append_area_emitter_xml(shape, obj)
        return shape
    obj_type = str(obj.get("type") or "wall")
    material = str(obj.get("material") or "")
    fallback = "0.8 0.8 0.8"
    if "glass" in obj_type or "glass" in material:
        material = material or "clear_glass"
    elif obj_type == "mirror_wall" or "mirror" in material:
        material = material or "mirror"
    _append_bsdf_xml(shape, material or "default_wall", material_idx, fallback_color=fallback, repo_root=repo_root)
    return shape


def _proxy_box_xml_element(
    obj: dict[str, Any],
    eg_by_label: "dict[str, Any]",
    material_idx: dict[str, dict[str, Any]],
    *,
    repo_root: "Path | None" = None,
    mesh_resolver: "Callable[[str, str], tuple[Path, dict] | None] | None" = None,
    mesh_stats: "dict[str, int] | None" = None,
    materialization_records: "list[dict[str, Any]] | None" = None,
    scene_mesh_cache_dir: "Path | None" = None,
    scene_texture_cache_dir: "Path | None" = None,
) -> "ET.Element | None":
    """Return a Mitsuba shape (OBJ when USD mesh is available, cube otherwise).

    The element is placed at the authoring center using yaw/pitch/roll + translate.
    Cubes are scaled by their bounds; OBJ meshes are placed in prim-local meters
    (bottom-at-y=0) so ``base_height_m`` becomes the floor-anchored placement Y.

    Counts (when ``mesh_stats`` provided): ``mesh_attached`` / ``cube_fallback``
    / ``mesh_resolver_error``.

    When ``materialization_records`` is provided, one record per emitted shape is
    appended. PR1 (render_scene_materialization.json) consumes this directly.
    """
    import xml.etree.ElementTree as ET

    geom = obj.get("geometry") or {}
    geom_type = geom.get("type")

    def _record(status: str, source_type: str, *, reason: str | None = None,
                cache_obj: str | None = None, shape_id: str | None = None,
                extras: dict[str, Any] | None = None) -> None:
        if materialization_records is None:
            return
        rec: dict[str, Any] = {
            "object_id": str(obj.get("id") or obj.get("label") or "object"),
            "label": _maybe_str(obj.get("label")),
            "type": _maybe_str(obj.get("type")),
            "source_ref": _maybe_str(obj.get("source_ref")),
            "shape_id": shape_id or str(obj.get("id") or obj.get("label") or "object"),
            "status": status,
            "source_type": source_type,
            "reason": reason,
            "cache_obj": cache_obj,
            "material_id": _maybe_str(obj.get("material")),
            "is_emitter": bool(obj.get("is_emitter")),
        }
        if extras:
            rec["extras"] = extras
        materialization_records.append(rec)

    if geom_type == "line":
        elem = _wall_shape_xml_element(obj, material_idx, repo_root=repo_root)
        if elem is not None:
            _record("cube", "wall_line", reason=None, shape_id=elem.get("id"))
        else:
            _record("dropped", "wall_line", reason="line_geometry_degenerate")
        return elem

    center = geom.get("center")
    if not center or len(center) < 2:
        _record("dropped", "primitive", reason="geometry_missing_center")
        return None
    cx, cz = float(center[0]), float(center[1])

    size_m = geom.get("size_m")
    if isinstance(size_m, (list, tuple)) and len(size_m) >= 3:
        sx, sy, sz = max(0.01, float(size_m[0])), max(0.01, float(size_m[1])), max(0.01, float(size_m[2]))
    else:
        eg_obj = eg_by_label.get(str(obj.get("label", "")))
        if eg_obj and eg_obj.get("bounds", {}).get("size"):
            s = eg_obj["bounds"]["size"]
            sx, sy, sz = float(s[0]), float(s[1]), float(s[2])
        else:
            sx, sy, sz = 0.5, 1.2, 0.5
    user_scale_xyz = (1.0, 1.0, 1.0)
    scale = geom.get("scale")
    if isinstance(scale, (list, tuple)) and len(scale) >= 3:
        user_scale_xyz = (float(scale[0]), float(scale[1]), float(scale[2]))
        sx *= user_scale_xyz[0]; sy *= user_scale_xyz[1]; sz *= user_scale_xyz[2]
    elif scale is not None:
        try:
            f = float(scale)
            user_scale_xyz = (f, f, f)
            sx *= f; sy *= f; sz *= f
        except Exception:
            pass

    if sx > 80.0 or sz > 80.0:
        _record("dropped", "primitive", reason="geometry_too_large")
        return None

    base_height = float(geom.get("base_height_m") or 0.0)
    cy_cube = base_height + sy / 2.0
    # If this object came from a USD scene (editor_geometry has real world bounds),
    # prefer the actual USD bounds center Y when the user hasn't overridden
    # base_height. Otherwise wall-mounted lamps and ceiling lights collapse to
    # the floor and can't illuminate downward.
    if base_height == 0.0:
        eg_obj_h = eg_by_label.get(str(obj.get("label", "")))
        eg_center = (eg_obj_h or {}).get("bounds", {}).get("center")
        if isinstance(eg_center, list) and len(eg_center) >= 3:
            try:
                eg_y = float(eg_center[1])
                if 0.05 <= eg_y <= 8.0:
                    cy_cube = eg_y
            except (TypeError, ValueError):
                pass
    yaw_deg = float(geom.get("yaw_deg") or 0.0)
    pitch_deg = float(geom.get("pitch_deg") or 0.0)
    roll_deg = float(geom.get("roll_deg") or 0.0)

    obj_id = str(obj.get("id") or obj.get("label") or "object")
    is_emitter = bool(obj.get("is_emitter"))

    # OBJ path: when the object has a USD source_ref and the resolver produces
    # a cached .obj, or when a local GLB source can be materialized to OBJ.
    # Emitters keep cube + area emitter so radiance x area stays predictable.
    obj_mesh_filename: str | None = None
    obj_extracted_material: dict[str, Any] | None = None
    usd_mesh_parts: list[dict[str, Any]] = []
    materialize_reason: str | None = None
    materialize_source_type: str = "primitive"
    materialize_cache_obj: str | None = None
    source_ref = _maybe_str(obj.get("source_ref"))
    if source_ref and not is_emitter:
        source_ref_l = source_ref.lower()
        if source_ref_l.endswith(".obj"):
            materialize_source_type = "obj_file"
            if repo_root is not None:
                try:
                    obj_path = resolve_repo_path(repo_root, source_ref)
                except Exception:
                    obj_path = Path(source_ref)
                if obj_path.exists():
                    try:
                        obj_mesh_filename = obj_path.relative_to(repo_root).as_posix()
                    except ValueError:
                        obj_mesh_filename = str(obj_path)
                    materialize_cache_obj = obj_mesh_filename
                    obj_extracted_material = _extract_obj_mtl_material(obj_path, repo_root=repo_root)
                else:
                    materialize_reason = "obj_source_missing"
            else:
                materialize_reason = "obj_source_requires_repo_root"
        glb_detail: dict[str, Any] = {}
        if obj_mesh_filename is None and not source_ref_l.endswith(".obj"):
            glb_obj_path = _materialize_glb_obj_for_overlay(
                source_ref, repo_root=repo_root, mesh_stats=mesh_stats, detail_out=glb_detail,
                scene_mesh_cache_dir=scene_mesh_cache_dir, scene_texture_cache_dir=scene_texture_cache_dir,
            )
            if glb_obj_path is not None and repo_root is not None:
                try:
                    obj_mesh_filename = glb_obj_path.relative_to(repo_root).as_posix()
                except ValueError:
                    obj_mesh_filename = str(glb_obj_path)
                materialize_source_type = "glb"
                materialize_cache_obj = obj_mesh_filename
                raw_parts = glb_detail.get("mesh_parts") if isinstance(glb_detail, dict) else None
                if isinstance(raw_parts, list):
                    usd_mesh_parts = [dict(part) for part in raw_parts if isinstance(part, dict)]
                for part in usd_mesh_parts:
                    em = part.get("extracted_material") if isinstance(part.get("extracted_material"), dict) else None
                    if obj_extracted_material is None and em and not em.get("error"):
                        obj_extracted_material = em
        if obj_mesh_filename is None and source_ref_l.endswith((".glb", ".gltf")):
            materialize_source_type = "glb"
            materialize_reason = glb_detail.get("error") or "glb_to_obj_failed"
        elif obj_mesh_filename is None and mesh_resolver is not None and "#" in source_ref:
            try:
                usd_ref, prim_path = source_ref.split("#", 1)
                resolved = mesh_resolver(usd_ref, prim_path)
                if resolved is not None and repo_root is not None:
                    cached_path, _meta = resolved
                    try:
                        obj_mesh_filename = cached_path.relative_to(repo_root).as_posix()
                    except ValueError:
                        obj_mesh_filename = str(cached_path)
                    materialize_source_type = "usd_prim"
                    materialize_cache_obj = obj_mesh_filename
                    if isinstance(_meta, dict):
                        raw_parts = _meta.get("mesh_parts")
                        if isinstance(raw_parts, list):
                            usd_mesh_parts = [dict(part) for part in raw_parts if isinstance(part, dict)]
                    em = _meta.get("extracted_material") if isinstance(_meta, dict) else None
                    if isinstance(em, dict) and not em.get("error"):
                        obj_extracted_material = em
                else:
                    materialize_source_type = "usd_prim"
                    materialize_reason = "usd_prim_extraction_returned_none"
            except Exception as exc:
                if mesh_stats is not None:
                    mesh_stats["resolver_error"] = mesh_stats.get("resolver_error", 0) + 1
                materialize_source_type = "usd_prim"
                materialize_reason = f"usd_prim_resolver_error: {exc}"
        elif obj_mesh_filename is None and materialize_reason is None:
            materialize_reason = "invalid_source_ref"
    elif source_ref and is_emitter:
        # Emitters are intentionally cubes (so radiance × area stays predictable).
        materialize_reason = "is_emitter"
    elif not source_ref and not is_emitter:
        materialize_reason = "no_source_ref"

    if obj_mesh_filename:
        obj_type = str(obj.get("type", ""))
        material = str(obj.get("material") or "")
        fallback = "0.55 0.45 0.35"
        if "plant" in obj_type:
            fallback = "0.3 0.55 0.25"
        elif "table" in obj_type or "desk" in obj_type:
            fallback = "0.7 0.6 0.4"
        elif "chair" in obj_type:
            fallback = "0.5 0.5 0.6"

        def _obj_shape(filename: str, shape_id: str) -> "ET.Element":
            shape = ET.Element("shape", type="obj", id=shape_id)
            ET.SubElement(shape, "string", attrib={"name": "filename", "value": filename})
            xf = ET.SubElement(shape, "transform", attrib={"name": "to_world"})
            if user_scale_xyz != (1.0, 1.0, 1.0):
                ET.SubElement(xf, "scale", x=f"{user_scale_xyz[0]:.6f}", y=f"{user_scale_xyz[1]:.6f}", z=f"{user_scale_xyz[2]:.6f}")
            if abs(roll_deg) > 1e-5:
                ET.SubElement(xf, "rotate", x="1", angle=f"{roll_deg:.4f}")
            if abs(pitch_deg) > 1e-5:
                ET.SubElement(xf, "rotate", z="1", angle=f"{pitch_deg:.4f}")
            if abs(yaw_deg) > 1e-5:
                ET.SubElement(xf, "rotate", y="1", angle=f"{yaw_deg:.4f}")
            ET.SubElement(xf, "translate", x=f"{cx:.6f}", y=f"{base_height:.6f}", z=f"{cz:.6f}")
            return shape

        obj_meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        for part in usd_mesh_parts:
            part.setdefault("asset_category", obj_meta.get("asset_category"))
            part.setdefault("object_type", obj.get("type"))
            part.setdefault("object_material", obj.get("material"))
            part.setdefault("source_ref", source_ref)
        usable_parts = [
            part for part in usd_mesh_parts
            if (
                part.get("obj_ref")
                and int(part.get("triangle_count") or 0) > 0
                and _should_emit_asset_mesh_part(obj, part)
            )
        ] if materialize_source_type in {"usd_prim", "glb"} else []
        if usable_parts:
            main_index = max(range(len(usable_parts)), key=lambda i: int(usable_parts[i].get("triangle_count") or 0))
            shapes: list[ET.Element] = []
            for part_index, part in enumerate(usable_parts):
                part_id = str(part.get("part_id") or f"part_{part_index:03d}")
                shape_id = obj_id if part_index == main_index else f"{obj_id}__{part_id}"
                em = part.get("extracted_material") if isinstance(part.get("extracted_material"), dict) else None
                selected_material, material_class = _select_part_render_material(
                    material, part, em, material_idx, repo_root=repo_root,
                )
                part["render_material_id"] = selected_material
                part["material_class"] = material_class
                shape = _obj_shape(str(part.get("obj_ref")), shape_id)
                _append_bsdf_xml(
                    shape, selected_material or material, material_idx,
                    fallback_color=fallback, repo_root=repo_root, extracted_material=em,
                )
                shapes.append(shape)
                if mesh_stats is not None:
                    mesh_stats["mesh_attached"] = mesh_stats.get("mesh_attached", 0) + 1
                    if em:
                        mesh_stats["usd_material_attached"] = mesh_stats.get("usd_material_attached", 0) + 1
                material_status = _classify_extracted_material(em) if em else "n/a"
                _record(
                    "obj", "glb_part" if materialize_source_type == "glb" else "usd_prim_part",
                    shape_id=shape_id, cache_obj=str(part.get("obj_ref")),
                    extras={
                        "parent_shape_id": obj_id,
                        "part_id": part_id,
                        "mesh_prim_path": part.get("mesh_prim_path"),
                        "mesh_name": part.get("mesh_name"),
                        "triangle_count": part.get("triangle_count"),
                        "material_class": material_class,
                        "render_material_id": selected_material,
                        "asset_id": (obj_meta.get("asset_id") if isinstance(obj_meta, dict) else None),
                        "render_readiness": (obj_meta.get("render_readiness") if isinstance(obj_meta, dict) else None),
                        "readiness_reason": (obj_meta.get("readiness_reason") if isinstance(obj_meta, dict) else None),
                        "albedo_scale_candidate": bool(em and (em.get("base_color_texture_ref") or em.get("base_color_factor")) and selected_material and (str(selected_material).startswith("hpbrdf_2025:") or str(selected_material).startswith("pbrdf_2020:"))),
                        "has_base_texture": bool(em and em.get("base_color_texture_ref")),
                        "has_normal_texture": bool(em and em.get("normal_texture_ref")),
                        "has_metallic_roughness_texture": bool(em and em.get("metallic_roughness_texture_ref")),
                        "usd_material_attached": bool(em),
                        "source_material_attached": bool(em),
                        "source_material_type": em.get("source") if em else None,
                        "extracted_material_status": material_status,
                        "extracted_material_summary": (
                            {
                                "base_color_factor": em.get("base_color_factor") if em else None,
                                "opacity_factor": em.get("opacity_factor") if em else None,
                                "has_base_texture": bool(em.get("base_color_texture_ref")) if em else False,
                                "has_base_asset": bool(em.get("base_color_asset")) if em else False,
                                "has_normal_texture": bool(em.get("normal_texture_ref")) if em else False,
                                "has_metallic_roughness_texture": bool(em.get("metallic_roughness_texture_ref")) if em else False,
                                "mtl_ref": em.get("mtl_ref") if em else None,
                            } if em else None
                        ),
                    },
                )
            return shapes if len(shapes) > 1 else shapes[0]

        shape = _obj_shape(obj_mesh_filename, obj_id)
        _append_bsdf_xml(
            shape, material, material_idx,
            fallback_color=fallback, repo_root=repo_root,
            extracted_material=obj_extracted_material,
        )
        if mesh_stats is not None:
            mesh_stats["mesh_attached"] = mesh_stats.get("mesh_attached", 0) + 1
            if obj_extracted_material:
                mesh_stats["usd_material_attached"] = mesh_stats.get("usd_material_attached", 0) + 1
        material_status = _classify_extracted_material(obj_extracted_material) if obj_extracted_material else "n/a"
        _record(
            "obj", materialize_source_type,
            shape_id=obj_id, cache_obj=materialize_cache_obj,
            extras={
                "asset_id": (obj_meta.get("asset_id") if isinstance(obj_meta, dict) else None),
                "render_readiness": (obj_meta.get("render_readiness") if isinstance(obj_meta, dict) else None),
                "readiness_reason": (obj_meta.get("readiness_reason") if isinstance(obj_meta, dict) else None),
                "albedo_scale_candidate": bool(obj_extracted_material and (obj_extracted_material.get("base_color_texture_ref") or obj_extracted_material.get("base_color_factor"))),
                "has_base_texture": bool(obj_extracted_material and obj_extracted_material.get("base_color_texture_ref")),
                "has_normal_texture": bool(obj_extracted_material and obj_extracted_material.get("normal_texture_ref")),
                "has_metallic_roughness_texture": bool(obj_extracted_material and obj_extracted_material.get("metallic_roughness_texture_ref")),
                "usd_material_attached": bool(obj_extracted_material),
                "source_material_attached": bool(obj_extracted_material),
                "source_material_type": obj_extracted_material.get("source") if obj_extracted_material else None,
                "extracted_material_status": material_status,
                "extracted_material_summary": (
                    {
                        "base_color_factor": obj_extracted_material.get("base_color_factor") if obj_extracted_material else None,
                        "opacity_factor": obj_extracted_material.get("opacity_factor") if obj_extracted_material else None,
                        "has_base_texture": bool(obj_extracted_material.get("base_color_texture_ref")) if obj_extracted_material else False,
                        "has_base_asset": bool(obj_extracted_material.get("base_color_asset")) if obj_extracted_material else False,
                        "mtl_ref": obj_extracted_material.get("mtl_ref") if obj_extracted_material else None,
                    } if obj_extracted_material else None
                ),
            },
        )
        return shape

    # Cube fallback (or emitter, which always uses a cube).
    shape = ET.Element("shape", type="cube", id=obj_id)
    xf = ET.SubElement(shape, "transform", attrib={"name": "to_world"})
    ET.SubElement(xf, "scale", x=f"{sx/2:.6f}", y=f"{sy/2:.6f}", z=f"{sz/2:.6f}")
    if abs(roll_deg) > 1e-5:
        ET.SubElement(xf, "rotate", x="1", angle=f"{roll_deg:.4f}")
    if abs(pitch_deg) > 1e-5:
        ET.SubElement(xf, "rotate", z="1", angle=f"{pitch_deg:.4f}")
    if abs(yaw_deg) > 1e-5:
        ET.SubElement(xf, "rotate", y="1", angle=f"{yaw_deg:.4f}")
    ET.SubElement(xf, "translate", x=f"{cx:.6f}", y=f"{cy_cube:.6f}", z=f"{cz:.6f}")

    if is_emitter:
        _append_area_emitter_xml(shape, obj)
        if mesh_stats is not None:
            mesh_stats["emitter_cube"] = mesh_stats.get("emitter_cube", 0) + 1
        _record("emitter_cube", "primitive", shape_id=obj_id, reason="is_emitter")
        return shape
    obj_type = str(obj.get("type", ""))
    material = str(obj.get("material") or "")
    fallback = "0.55 0.45 0.35"
    if "plant" in obj_type:
        fallback = "0.3 0.55 0.25"
    elif "table" in obj_type or "desk" in obj_type:
        fallback = "0.7 0.6 0.4"
    elif "chair" in obj_type:
        fallback = "0.5 0.5 0.6"
    _append_bsdf_xml(shape, material, material_idx, fallback_color=fallback, repo_root=repo_root)
    if mesh_stats is not None:
        mesh_stats["cube_fallback"] = mesh_stats.get("cube_fallback", 0) + 1
    _record(
        "fallback_cube", materialize_source_type,
        shape_id=obj_id,
        reason=materialize_reason or ("no_source_ref" if not source_ref else "unknown_fallback"),
    )
    return shape


def _append_environment_xml(root: "ET.Element", authoring_map_payload: dict[str, Any]) -> None:
    import xml.etree.ElementTree as ET

    environment = dict(authoring_map_payload.get("environment") or {})
    mode = str(environment.get("mode") or "constant")
    intensity = float(environment.get("intensity") or 1.0)
    if mode == "envmap" and environment.get("envmap_ref"):
        emitter = ET.SubElement(root, "emitter", type="envmap")
        ET.SubElement(emitter, "string", attrib={"name": "filename", "value": str(environment.get("envmap_ref"))})
        ET.SubElement(emitter, "float", attrib={"name": "scale", "value": f"{intensity:.6g}"})
        rotation = float(environment.get("rotation_deg") or 0.0)
        if abs(rotation) > 1e-5:
            xf = ET.SubElement(emitter, "transform", attrib={"name": "to_world"})
            ET.SubElement(xf, "rotate", y="1", angle=f"{rotation:.4f}")
        return
    emitter = ET.SubElement(root, "emitter", type="constant")
    ET.SubElement(emitter, "rgb", attrib={"name": "radiance", "value": _rgb_value(environment.get("radiance"), intensity=intensity)})


def _ceiling_skylight_radiance(authoring_map_payload: dict[str, Any]) -> str | None:
    """Radiance string for a luminous ceiling, or ``None`` to keep it opaque.

    A sealed room (walls + ceiling) blocks the ``constant`` environment emitter,
    so the interior is lit only by small authored fixtures → dark, slow-converging
    and noisy even at high spp. When the environment is a constant ambient we turn
    the ceiling slab into a large downward area emitter carrying that ambient into
    the room. A big area light is cheap to importance-sample, so this brightens the
    scene and cuts noise at the SAME spp — no render-time cost, unlike raising
    spp/max_depth.

    Controls (under ``environment``):
      * ``ceiling_skylight``  — bool, default True. Set False to keep the opaque ceiling.
      * ``ceiling_fill_gain`` — float, default 1.0. Multiplies the ambient radiance.
    Only active for ``mode == "constant"`` (envmap rooms should drop the shell instead).
    """
    environment = dict(authoring_map_payload.get("environment") or {})
    mode = str(environment.get("mode") or "constant")
    if mode != "constant" or not bool(environment.get("ceiling_skylight", True)):
        return None
    intensity = float(environment.get("intensity") or 1.0)
    gain = float(environment.get("ceiling_fill_gain", 1.0) or 1.0)
    return _rgb_value(environment.get("radiance"), intensity=intensity * gain)


_ROOM_SHELL_WALL_THICKNESS_M = 0.08  # full thickness; renderer's old code passed wt=0.04 as a half-extent → 0.08m


def _room_shell_enabled(authoring_map_payload: dict[str, Any]) -> bool:
    """Walls + ceiling on/off. Phase 1: no longer controls the floor.

    Defaults to True for backward compatibility. Set ``settings.room_shell_enabled = false``
    to drop the synthetic walls + ceiling so an envmap can illuminate / be visible through
    the bounds. The floor stays independently — see :func:`_auto_floor_enabled`.
    """
    settings = authoring_map_payload.get("settings") or {}
    val = settings.get("room_shell_enabled")
    if val is None:
        return True
    return bool(val)


def _auto_floor_enabled(authoring_map_payload: dict[str, Any]) -> bool:
    """Auto floor slab(s) on/off. Independent of walls/ceiling.

    Defaults to True so existing scenes still get a base floor. Set
    ``settings.auto_floor_enabled = false`` for a fully open scene (e.g. naked envmap).
    """
    settings = authoring_map_payload.get("settings") or {}
    val = settings.get("auto_floor_enabled")
    if val is None:
        return True
    return bool(val)


def _auto_ceiling_enabled(authoring_map_payload: dict[str, Any]) -> bool:
    """Ceiling slab on/off, independent of the perimeter walls.

    Lets an authored scene keep an opaque ceiling (enclosure + lighting bounce)
    while dropping the synthetic perimeter walls so glass walls / windows reveal
    the environment outside. When ``settings.auto_ceiling_enabled`` is unset we
    fall back to ``room_shell_enabled`` (the legacy coupled behaviour) so existing
    scenes — including envmap rooms that disabled the shell — are unchanged.
    """
    settings = authoring_map_payload.get("settings") or {}
    val = settings.get("auto_ceiling_enabled")
    if val is None:
        return _room_shell_enabled(authoring_map_payload)
    return bool(val)


def _default_floor_material_id(authoring_map_payload: dict[str, Any]) -> str:
    """Per-region fallback when a traversable region has no ``floor_material_id``."""
    settings = authoring_map_payload.get("settings") or {}
    val = settings.get("default_floor_material_id")
    return str(val) if val else "default_floor"


def _compute_floor_slabs(authoring_map_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-traversable-region floor slabs with material assignment.

    - Each traversable region's ``geometry.bounds`` rectangle → one cube slab,
      bottom at y=-slab_h, top at y=0. Shape id = ``floor_{region_id}``.
    - region.floor_material_id is preferred; missing → settings default.
    - No traversable region: fall back to a single union-bounds slab using the
      default material (matches historical behaviour).
    - ``auto_floor_enabled == False`` → empty list (caller must skip the emit loop).
    """
    if not _auto_floor_enabled(authoring_map_payload):
        return []
    default_mid = _default_floor_material_id(authoring_map_payload)
    slab_h = 0.05  # full thickness; top sits at y=0
    cy = -slab_h / 2.0

    regions = authoring_map_payload.get("regions") or []
    traversable_regions: list[dict[str, Any]] = []
    union: list[float] | None = None  # [min_x, min_z, max_x, max_z]
    for r in regions:
        if not isinstance(r, Mapping) or r.get("type") != "traversable":
            continue
        bounds = ((r.get("geometry") or {}).get("bounds")) if isinstance(r.get("geometry"), Mapping) else None
        if not (isinstance(bounds, list) and len(bounds) == 4):
            continue
        try:
            mn_x, mn_z, mx_x, mx_z = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
        except (TypeError, ValueError):
            continue
        if not (mx_x > mn_x and mx_z > mn_z):
            continue
        traversable_regions.append({
            "region_id": str(r.get("id") or ""),
            "bounds": (mn_x, mn_z, mx_x, mx_z),
            "material_id": _maybe_str(r.get("floor_material_id")) or default_mid,
        })
        if union is None:
            union = [mn_x, mn_z, mx_x, mx_z]
        else:
            union[0] = min(union[0], mn_x); union[1] = min(union[1], mn_z)
            union[2] = max(union[2], mx_x); union[3] = max(union[3], mx_z)

    slabs: list[dict[str, Any]] = []
    if traversable_regions:
        for t in traversable_regions:
            mn_x, mn_z, mx_x, mx_z = t["bounds"]
            cx = (mn_x + mx_x) / 2.0
            cz = (mn_z + mx_z) / 2.0
            sx = mx_x - mn_x
            sz = mx_z - mn_z
            rid = t["region_id"] or "anonymous"
            slabs.append({
                "role": "floor",
                "id": f"floor_{rid}",
                "region_id": rid,
                "center": [cx, cy, cz],
                "size": [sx, slab_h, sz],
                "material_id": t["material_id"],
            })
        return slabs

    # Fallback: no traversable regions → single union slab.
    # Prefer the editor's authoring map_w/map_h when set; otherwise the union of
    # placed objects; otherwise a 20×20 default. Hardcoded 20×20 was producing
    # floors that extended far past the user-configured editor extent.
    settings_for_floor = authoring_map_payload.get("settings") or {}
    map_w_setting = settings_for_floor.get("map_w")
    map_h_setting = settings_for_floor.get("map_h")
    try:
        map_w_val = float(map_w_setting) if map_w_setting is not None else None
        map_h_val = float(map_h_setting) if map_h_setting is not None else None
    except (TypeError, ValueError):
        map_w_val = map_h_val = None
    if union is not None:
        mn_x, mn_z, mx_x, mx_z = union[0], union[1], union[2], union[3]
    elif map_w_val and map_h_val and map_w_val > 0 and map_h_val > 0:
        mn_x, mn_z, mx_x, mx_z = 0.0, 0.0, map_w_val, map_h_val
    else:
        mn_x, mn_z, mx_x, mx_z = 0.0, 0.0, 20.0, 20.0
    cx = (mn_x + mx_x) / 2.0
    cz = (mn_z + mx_z) / 2.0
    slabs.append({
        "role": "floor",
        "id": "floor_default",
        "region_id": None,
        "center": [cx, cy, cz],
        "size": [mx_x - mn_x, slab_h, mx_z - mn_z],
        "material_id": default_mid,
    })
    return slabs


def _compute_room_shell_geometry(authoring_map_payload: dict[str, Any]) -> dict[str, Any]:
    """Compute the 6 auto-room-shape geometry (floor/ceiling slab + 4 perimeter walls).

    Single source of truth shared by the Mitsuba XML emitter and the editor 3D
    overlay. ``center`` is the world-space midpoint of each shape; ``size`` is
    the full extent on each axis (NOT half-extent).

    The returned dict carries ``enabled`` so the editor can default its own viewer
    overlay toggle to match the authoring intent. Shapes are always computed even
    when disabled — the editor still needs them to draw a translucent preview.
    """
    regions = authoring_map_payload.get("regions") or []
    settings = authoring_map_payload.get("settings") or {}
    wall_h = float(settings.get("default_wall_height_m") or 2.4)
    wt = float(settings.get("default_wall_thickness_m") or _ROOM_SHELL_WALL_THICKNESS_M)

    traversable = next((r for r in regions if r.get("type") == "traversable"), None)
    bounds_raw = ((traversable or {}).get("geometry") or {}).get("bounds")
    if isinstance(bounds_raw, list) and len(bounds_raw) == 4:
        min_x, min_z, max_x, max_z = (float(b) for b in bounds_raw)
    else:
        min_x, min_z, max_x, max_z = 0.0, 0.0, 20.0, 20.0

    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0
    dx = max_x - min_x
    dz = max_z - min_z
    slab_h = 0.05  # full thickness of the floor/ceiling slab

    shapes = [
        {"role": "floor",   "center": [cx, -slab_h / 2,        cz],   "size": [dx, slab_h, dz]},
        {"role": "ceiling", "center": [cx, wall_h + slab_h / 2, cz],  "size": [dx, slab_h, dz]},
        {"role": "wall_n",  "center": [cx, wall_h / 2,         max_z], "size": [dx, wall_h, wt]},
        {"role": "wall_s",  "center": [cx, wall_h / 2,         min_z], "size": [dx, wall_h, wt]},
        {"role": "wall_e",  "center": [max_x, wall_h / 2,      cz],   "size": [wt, wall_h, dz]},
        {"role": "wall_w",  "center": [min_x, wall_h / 2,      cz],   "size": [wt, wall_h, dz]},
    ]
    return {
        "wall_height_m": wall_h,
        "wall_thickness_m": wt,
        "bounds": [min_x, min_z, max_x, max_z],
        "center_xz": [cx, cz],
        "extent_xz": [dx, dz],
        # ``shapes`` keeps the legacy floor entry so older clients still see something to
        # draw, but Phase 1 sources the actual rendered floors from ``floor_slabs``.
        "shapes": shapes,
        "floor_slabs": _compute_floor_slabs(authoring_map_payload),
        "auto_floor_enabled": _auto_floor_enabled(authoring_map_payload),
        "default_floor_material_id": _default_floor_material_id(authoring_map_payload),
        # ``enabled`` kept for backward compat = perimeter walls flag. Ceiling is now
        # independently gated via ``ceiling_enabled`` (falls back to walls when unset).
        "enabled": _room_shell_enabled(authoring_map_payload),
        "walls_enabled": _room_shell_enabled(authoring_map_payload),
        "ceiling_enabled": _auto_ceiling_enabled(authoring_map_payload),
    }


def _generate_opticalnav_render_scene_xml(
    authoring_map_payload: "dict[str, Any]",
    overlay: "dict[str, Any]",
    out_path: "Path",
    *,
    editor_geometry: "dict[str, Any] | None" = None,
    repo_root: "Path | None" = None,
    mesh_resolver: "Callable[[str, str], tuple[Path, dict] | None] | None" = None,
    mesh_stats: "dict[str, int] | None" = None,
    materialization_records: "list[dict[str, Any]] | None" = None,
) -> int:
    """Generate a full Mitsuba render scene from authoring_map in authoring coordinates.

    Coordinate system: X=authoring_x, Y=up, Z=authoring_y (matches sensor_sweep camera gen).
    Returns number of proxy shapes added.
    """
    import xml.etree.ElementTree as ET

    material_idx = _material_index(authoring_map_payload)
    eg_by_label: dict[str, Any] = {}
    if editor_geometry:
        for eg_obj in editor_geometry.get("objects") or []:
            label = str(eg_obj.get("label") or "")
            if label:
                eg_by_label[label] = eg_obj

    shell = _compute_room_shell_geometry(authoring_map_payload)
    wall_h = float(shell["wall_height_m"])
    wt = float(shell["wall_thickness_m"])
    min_x, min_z, max_x, max_z = shell["bounds"]
    cx, cz = float(shell["center_xz"][0]), float(shell["center_xz"][1])
    dx, dz = float(shell["extent_xz"][0]), float(shell["extent_xz"][1])

    root = ET.Element("scene", version="3.0.0")
    # Embed scene-level authoring metadata as the first XML comment child.
    # Mitsuba ignores comments; the editor reads this to reconstruct non-object state.
    _scene_meta = {
        "version": "opticalnav-scene-v0.1",
        "scene_id": str(authoring_map_payload.get("scene_id") or ""),
        "settings": dict(authoring_map_payload.get("settings") or {}),
        "camera_rig": authoring_map_payload.get("camera_rig"),
        "environment": authoring_map_payload.get("environment"),
        "materials": authoring_map_payload.get("materials"),
    }
    root.append(ET.Comment("opticalnav-scene:" + json.dumps(_scene_meta, ensure_ascii=False, separators=(",", ":"))))
    integrator = ET.SubElement(root, "integrator", type="path")
    ET.SubElement(integrator, "integer", attrib={"name": "max_depth", "value": "6"})

    # Placeholder sensor. Runtime sensor replacement is used by scene reuse, but a
    # sensor keeps legacy _update_sensor() paths functional.
    sensor = ET.SubElement(root, "sensor", type="perspective")
    ET.SubElement(sensor, "float", attrib={"name": "fov", "value": "60.0"})
    sxf = ET.SubElement(sensor, "transform", attrib={"name": "to_world"})
    ET.SubElement(sxf, "lookat", attrib={"origin": f"{cx} 1.0 {cz}", "target": f"{cx} 1.0 {cz + 1.0}", "up": "0 1 0"})
    sampler = ET.SubElement(sensor, "sampler", type="independent")
    ET.SubElement(sampler, "integer", attrib={"name": "sample_count", "value": "64"})
    film = ET.SubElement(sensor, "film", type="hdrfilm")
    ET.SubElement(film, "integer", attrib={"name": "width", "value": "640"})
    ET.SubElement(film, "integer", attrib={"name": "height", "value": "480"})

    _append_environment_xml(root, authoring_map_payload)

    def _cube(parent: "ET.Element", ex: float, ey: float, ez: float,
              sx: float, sy: float, sz: float, material_id: str, color: str = "0.75 0.75 0.75",
              shape_id: str | None = None, emitter_radiance: str | None = None) -> None:
        attrib = {"type": "cube"}
        if shape_id:
            attrib["id"] = shape_id
        s = ET.SubElement(parent, "shape", attrib=attrib)
        xf = ET.SubElement(s, "transform", attrib={"name": "to_world"})
        ET.SubElement(xf, "scale", x=f"{sx:.6f}", y=f"{sy:.6f}", z=f"{sz:.6f}")
        ET.SubElement(xf, "translate", x=f"{ex:.6f}", y=f"{ey:.6f}", z=f"{ez:.6f}")
        _append_bsdf_xml(s, material_id, material_idx, fallback_color=color, repo_root=repo_root)
        if emitter_radiance:
            em = ET.SubElement(s, "emitter", type="area")
            ET.SubElement(em, "rgb", attrib={"name": "radiance", "value": emitter_radiance})

    # Phase 1: floor is its own layer with per-region materials and stable shape ids.
    # Gated by ``settings.auto_floor_enabled`` independently of walls/ceiling.
    _FLOOR_FALLBACK_COLOR = "0.55 0.50 0.45"
    if shell.get("auto_floor_enabled", True):
        for slab in (shell.get("floor_slabs") or []):
            ex, ey, ez = slab["center"]
            ssx, ssy, ssz = slab["size"]
            material_id = str(slab.get("material_id") or "default_floor")
            shape_id = str(slab.get("id") or f"floor_{slab.get('region_id') or 'auto'}")
            root.append(ET.Comment("opticalnav-floor:" + json.dumps(
                {"shape_id": shape_id, "region_id": slab.get("region_id"), "material_id": material_id},
                ensure_ascii=False, separators=(",", ":"))))
            _cube(root, ex, ey, ez, ssx / 2.0, ssy / 2.0, ssz / 2.0,
                  material_id, color=_FLOOR_FALLBACK_COLOR, shape_id=shape_id)
    else:
        root.append(ET.Comment("opticalnav-floor:" + json.dumps(
            {"shape_id": None, "region_id": None, "material_id": None, "disabled": True},
            ensure_ascii=False, separators=(",", ":"))))

    # Walls + ceiling. Phase 1 dropped floor from this loop — floor is emitted above.
    _ROOM_COLORS = {
        "ceiling": ("default_ceiling", "0.85 0.85 0.85"),
        "wall_n": ("default_wall", "0.78 0.76 0.73"),
        "wall_s": ("default_wall", "0.78 0.76 0.73"),
        "wall_e": ("default_wall", "0.78 0.76 0.73"),
        "wall_w": ("default_wall", "0.78 0.76 0.73"),
    }
    ceiling_fill = _ceiling_skylight_radiance(authoring_map_payload)
    walls_enabled = bool(shell.get("walls_enabled", shell.get("enabled", True)))
    ceiling_enabled = bool(shell.get("ceiling_enabled", shell.get("enabled", True)))
    if walls_enabled or ceiling_enabled:
        for sh in shell["shapes"]:
            role = sh.get("role")
            if role == "floor":
                # Phase 1: floor is no longer part of the room shell. It's emitted from
                # ``floor_slabs`` above so the user can disable walls/ceiling without
                # losing the ground.
                continue
            # Ceiling and perimeter walls are now independently gated so an authored
            # scene can keep the ceiling while exposing glass walls to the environment.
            if role == "ceiling" and not ceiling_enabled:
                continue
            if role != "ceiling" and not walls_enabled:
                continue
            ex, ey, ez = sh["center"]
            wsx, wsy, wsz = sh["size"]
            mat, color = _ROOM_COLORS.get(sh["role"], ("default_wall", "0.78 0.76 0.73"))
            # Sealed-room interiors are lit only by small fixtures and converge slowly;
            # make the ceiling a large luminous panel that carries the constant ambient
            # into the room (brightens + denoises at the same spp). See
            # _ceiling_skylight_radiance().
            is_ceiling = sh.get("role") == "ceiling"
            emit = ceiling_fill if is_ceiling else None
            shell_meta = {"type": "__room_shell__", "role": sh["role"]}
            if emit:
                shell_meta["emissive"] = True
            root.append(ET.Comment(json.dumps(shell_meta, ensure_ascii=False, separators=(",", ":"))))
            _cube(root, ex, ey, ez, wsx / 2.0, wsy / 2.0, wsz / 2.0, mat, color, emitter_radiance=emit)
    else:
        root.append(ET.Comment(json.dumps({"type": "__room_shell__", "role": "disabled"},
                                          ensure_ascii=False, separators=(",", ":"))))

    added = 0
    # Mirror GLB-materialized OBJs into the scene's mesh_cache so the frontend's
    # basename-based `/mesh-cache/<filename>` endpoint can find them (they live
    # in a global glb_obj_cache/<digest>/mesh.obj by default — 18 GLB objects
    # in one scene all share the basename "mesh.obj" and 404 in the editor).
    scene_mesh_cache_dir = out_path.parent / "mesh_cache"
    scene_texture_cache_dir = out_path.parent / "texture_cache"
    for obj in overlay.get("objects") or []:
        elem = _proxy_box_xml_element(
            obj, eg_by_label, material_idx,
            repo_root=repo_root,
            mesh_resolver=mesh_resolver,
            mesh_stats=mesh_stats,
            materialization_records=materialization_records,
            scene_mesh_cache_dir=scene_mesh_cache_dir,
            scene_texture_cache_dir=scene_texture_cache_dir,
        )
        if elem is not None:
            root.append(ET.Comment(_opticalnav_obj_comment_data(obj)))
            elems = elem if isinstance(elem, list) else [elem]
            for child_elem in elems:
                root.append(child_elem)
                added += 1

    _dedupe_shape_bsdfs_to_shared(root)
    if repo_root is not None:
        _absolutize_filename_refs(root, repo_root=repo_root, mesh_stats=mesh_stats)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass
    ET.ElementTree(root).write(str(out_path), encoding="unicode", xml_declaration=False)
    return added


def _absolutize_filename_refs(root: "ET.Element", *, repo_root: "Path", mesh_stats: "dict[str, int] | None" = None) -> None:
    """Convert every relative ``<string name="filename">`` in the scene XML to absolute.

    Mitsuba's xml loader resolves a relative filename against the XML file's
    parent directory. Our render_scene.xml gets staged into
    ``.staged_mitsuba/base/<hash>.xml`` before load, so repo-relative paths
    (``assets/...``, ``data/...``, ``out/...``) silently break. Walking the
    final tree here means every shape OBJ, texture bitmap, envmap, and measured
    BSDF data file lands as an absolute path no matter who emitted it.

    Missing files are *not* rewritten and a count is recorded in ``mesh_stats``
    so the readiness summary can surface them.
    """
    rewritten = 0
    missing = 0
    for node in root.iter("string"):
        if node.attrib.get("name") != "filename":
            continue
        value = node.attrib.get("value")
        if not value:
            continue
        p = Path(value)
        if p.is_absolute():
            if not p.exists() and mesh_stats is not None:
                missing += 1
            continue
        absolute = (repo_root / p).resolve()
        node.attrib["value"] = str(absolute)
        rewritten += 1
        if not absolute.exists() and mesh_stats is not None:
            missing += 1
    if mesh_stats is not None:
        if rewritten:
            mesh_stats["filename_paths_absolutized"] = mesh_stats.get("filename_paths_absolutized", 0) + rewritten
        if missing:
            mesh_stats["filename_paths_missing"] = mesh_stats.get("filename_paths_missing", 0) + missing


def _dedupe_shape_bsdfs_to_shared(root: "ET.Element") -> None:
    """Hoist inline <bsdf> children of <shape> into top-level shared <bsdf id=...> blocks.

    Each shape's inline BSDF is replaced with <ref id="..."/>. Identical BSDFs (by
    canonical serialized form) collapse to a single shared instance, which cuts
    OptiX shader compile time dramatically when many shapes share materials.
    """
    import hashlib
    import xml.etree.ElementTree as ET

    def _strip(elem: "ET.Element") -> "ET.Element":
        for child in elem.iter():
            if child.tail:
                child.tail = None
            if child.text and not child.text.strip():
                child.text = None
        return elem

    def _canonical(elem: "ET.Element") -> str:
        return ET.tostring(_strip(elem), encoding="unicode")

    seen: dict[str, str] = {}  # canonical text → shared id
    shared_blocks: list[ET.Element] = []

    for shape in list(root.findall("./shape")):
        bsdf = shape.find("./bsdf")
        if bsdf is None:
            continue
        # Skip if the shape already references a shared BSDF.
        if bsdf.get("type") is None and bsdf.tag == "ref":
            continue
        key = _canonical(bsdf)
        shared_id = seen.get(key)
        if shared_id is None:
            shared_id = f"shared_bsdf_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
            seen[key] = shared_id
            hoisted = ET.fromstring(ET.tostring(bsdf))
            hoisted.set("id", shared_id)
            shared_blocks.append(hoisted)
        shape.remove(bsdf)
        ref = ET.SubElement(shape, "ref", attrib={"id": shared_id})

    # Insert shared blocks at top of scene (after integrator/sensor/environment, before shapes).
    insert_idx = 0
    for i, child in enumerate(list(root)):
        if child.tag == "shape":
            insert_idx = i
            break
        insert_idx = i + 1
    for block in reversed(shared_blocks):
        root.insert(insert_idx, block)


def _build_opticalnav_render_readiness(
    authoring_map_payload: dict[str, Any],
    *,
    repo_root: Path,
    render_scene_path: Path,
    render_scene_ref: str | None,
    overlay_shape_count: int,
    generation_error: str | None = None,
    materialization_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def add_check(key: str, ok: bool, label: str, *, level: str = "error", message: str | None = None) -> None:
        checks.append({"key": key, "ok": ok, "label": label, "level": level, "message": message})
        if ok:
            return
        item = {"key": key, "label": label, "message": message or label}
        (warnings if level == "warning" else errors).append(item)

    env = dict(authoring_map_payload.get("environment") or {})
    env_mode = str(env.get("mode") or "constant")
    if env_mode == "envmap":
        env_ref = _maybe_str(env.get("envmap_ref"))
        env_ok = bool(env_ref)
        if env_ref:
            try:
                env_ok = resolve_repo_path(repo_root, env_ref).exists()
            except Exception:
                env_ok = Path(env_ref).exists()
        add_check("environment", env_ok, "Environment valid", message="Envmap path is missing or unresolved.")
    else:
        add_check("environment", True, "Environment valid")

    # Phase 1: floor and walls/ceiling are independent toggles. Warn when both are
    # off under constant lighting — the scene will render almost empty/flat.
    shell_on = _room_shell_enabled(authoring_map_payload)
    floor_on = _auto_floor_enabled(authoring_map_payload)
    if not shell_on and not floor_on and env_mode == "constant":
        add_check(
            "empty_enclosure_constant", False,
            "No floor or enclosure",
            level="warning",
            message="Floor and walls/ceiling are both disabled under constant lighting; the scene may look empty or flat. Switch to envmap or re-enable at least one layer.",
        )
    elif not shell_on and env_mode == "constant":
        add_check(
            "room_shell_lighting", False,
            "Walls & ceiling off — envmap recommended",
            level="warning",
            message="Walls/ceiling are disabled but environment mode is 'constant'. Switch to envmap for non-flat lighting.",
        )
    else:
        add_check("room_shell_lighting", True, "Enclosure / lighting consistent", level="info")

    # Floor material sanity: every traversable region with a non-default floor_material_id
    # should resolve in the catalog. Missing entries fall back to default_floor (not blocking)
    # so we surface as warnings instead of errors.
    material_idx_for_floor = _material_index(authoring_map_payload)
    default_floor_mid = _default_floor_material_id(authoring_map_payload)
    for region in authoring_map_payload.get("regions") or []:
        if not isinstance(region, Mapping) or region.get("type") != "traversable":
            continue
        floor_mid = _maybe_str(region.get("floor_material_id"))
        if not floor_mid or floor_mid == default_floor_mid:
            continue
        binding = _resolve_material_binding(floor_mid, material_idx_for_floor)
        if binding.get("unresolved"):
            warnings.append({
                "key": f"floor_material_unknown.{region.get('id')}",
                "label": "Floor material unknown",
                "message": f"Region '{region.get('id')}' floor_material_id '{floor_mid}' is not in the catalog; falling back to default_floor.",
            })

    rig = dict(authoring_map_payload.get("camera_rig") or {})
    sensors = [dict(item) for item in rig.get("sensors") or [] if isinstance(item, Mapping)]
    # Fall back to camera_rigs directory if authoring_map has no inline sensors.
    # The camera_rigs directory uses a different schema (sensor_type/intrinsics/modalities),
    # so convert each entry to the authoring_map sensor shape for uniform checks below.
    if not sensors:
        rig_id = str(rig.get("rig_id") or "ranger_mini_default")
        _camera_rigs_dir = repo_root / "out" / "control_plane_cache" / "camera_rigs"
        for _candidate in (rig_id, "ranger_mini_default"):
            _rig_path = _camera_rigs_dir / f"{_candidate}.json"
            if _rig_path.exists():
                try:
                    _rig_data = _read_json(_rig_path)
                    for _s in _rig_data.get("sensors") or []:
                        if not isinstance(_s, Mapping) or not _s.get("enabled", True):
                            continue
                        _intr = dict(_s.get("intrinsics") or {})
                        _modalities = [str(m) for m in (_s.get("modalities") or [])]
                        _modality = "rgb" if "rgb" in _modalities else (_modalities[0] if _modalities else str(_s.get("sensor_type") or "rgb"))
                        sensors.append({
                            "sensor_id": str(_s.get("sensor_id") or "sensor"),
                            "modality": _modality,
                            "fov_deg": float(_intr.get("fov_h_deg") or _intr.get("fov_v_deg") or 70.0),
                            "resolution": list(_intr.get("resolution") or [640, 480]),
                        })
                    if sensors:
                        break
                except Exception:
                    pass
    add_check("camera_rig", bool(sensors), "Camera rig valid", message="Add at least one robot-relative camera sensor.")
    add_check("rgb_camera", any(str(sensor.get("modality") or "").lower() == "rgb" for sensor in sensors), "At least one RGB camera", message="Camera rig must include an RGB sensor.")
    for sensor in sensors:
        sid = str(sensor.get("sensor_id") or "sensor")
        res = sensor.get("resolution") or []
        fov = float(sensor.get("fov_deg") or 0.0)
        ok = isinstance(res, list) and len(res) >= 2 and int(res[0]) > 0 and int(res[1]) > 0 and fov > 0
        add_check(f"camera.{sid}", ok, f"Camera {sid} intrinsics", message="FOV and resolution must be positive.")

    add_check("xml_generated", bool(render_scene_ref) and render_scene_path.exists() and not generation_error, "XML generated", message=generation_error or "render_scene.xml is missing.")
    add_check("geometry_materialized", overlay_shape_count > 0, "All object geometry materialized", level="warning", message="No editor overlay objects were materialized; only room primitives will render.")

    material_idx = _material_index(authoring_map_payload)
    material_errors = 0
    proxy_warnings = 0
    asset_errors = 0
    for obj in authoring_map_payload.get("objects") or []:
        if not isinstance(obj, Mapping):
            continue
        oid = str(obj.get("id") or obj.get("label") or "object")
        source_ref = _maybe_str(obj.get("source_ref"))
        if source_ref:
            # ``usda#/prim/path`` style source_refs end on the prim path, not the file
            # extension; strip any ``#fragment`` so the extension test sees the actual
            # asset filename (otherwise USD-prim objects get miscounted as proxies).
            ref_for_check = source_ref.split("#", 1)[0]
            looks_like_file = any(ref_for_check.lower().endswith(ext) for ext in (".obj", ".ply", ".usd", ".usda", ".usdc", ".glb", ".gltf"))
            if looks_like_file:
                try:
                    exists = resolve_repo_path(repo_root, ref_for_check).exists()
                except Exception:
                    exists = Path(ref_for_check).exists()
                if not exists:
                    asset_errors += 1
                    errors.append({"key": f"asset.{oid}", "label": "Asset path missing", "message": f"Asset source_ref does not exist: {source_ref}"})
            else:
                proxy_warnings += 1
        else:
            proxy_warnings += 1
        mat_id = _maybe_str(obj.get("material"))
        if mat_id:
            binding = _resolve_material_binding(mat_id, material_idx)
            if binding.get("unresolved"):
                # Unresolved binding → render falls back to default diffuse. Warning only.
                proxy_warnings += 1
                warnings.append({"key": f"material.{oid}", "label": "Material fallback", "message": f"No render binding for {mat_id!r} — default diffuse used."})
            if str(binding.get("bsdf_strategy") or "") in {"measured", "measured_polarized"}:
                native = _maybe_str(binding.get("native_file"))
                channels_dir = _maybe_str(binding.get("channels_dir"))
                channel_paths: list[Path] = []
                if channels_dir:
                    ch_root = Path(channels_dir)
                    if not ch_root.is_absolute():
                        ch_root = repo_root / ch_root
                    channel_paths = [ch_root / f"{w}.pbrdf" for w in (446, 542, 614, 854)]
                if channels_dir and all(path.exists() for path in channel_paths):
                    continue
                if channels_dir and channel_paths:
                    material_errors += 1
                    missing_channels = ", ".join(str(path) for path in channel_paths if not path.exists())
                    errors.append({"key": f"material_source.{oid}", "label": "Measured BSDF source missing", "message": f"Measured material channel files are missing for {mat_id}: {missing_channels}"})
                elif not native:
                    material_errors += 1
                    errors.append({"key": f"material_source.{oid}", "label": "Measured BSDF source missing", "message": f"Measured material {mat_id} has no native_file."})
                elif not (Path(native).exists() or (repo_root / native).exists()):
                    material_errors += 1
                    errors.append({"key": f"material_source.{oid}", "label": "Measured BSDF source missing", "message": f"Measured material source does not exist: {native}"})
    checks.append({"key": "assets_exist", "ok": asset_errors == 0, "label": "All assets exist", "level": "error", "message": None if asset_errors == 0 else f"{asset_errors} asset refs are missing."})
    checks.append({"key": "material_bindings", "ok": material_errors == 0, "label": "Measured material sources present", "level": "error", "message": None if material_errors == 0 else f"{material_errors} measured material source(s) missing."})
    # Prefer PR1's per-object audit when available — it's the only signal that knows
    # which objects ACTUALLY ended up as fallback cubes after sync. The static guess
    # above can't tell a successful USD-prim materialization apart from a never-tried
    # source_ref, so when the audit is present we replace the proxy count and surface
    # a per-reason breakdown.
    if materialization_records:
        fallback_records = [r for r in materialization_records if r.get("status") == "fallback_cube"]
        if fallback_records:
            by_reason: dict[str, int] = {}
            for r in fallback_records:
                reason = str(r.get("reason") or "unknown")
                by_reason[reason] = by_reason.get(reason, 0) + 1
            top_reasons = ", ".join(f"{k}: {v}" for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1])[:3])
            warnings.append({
                "key": "proxy_primitive",
                "label": "Proxy primitive used",
                "message": f"{len(fallback_records)} objects rendered as proxy primitives ({top_reasons}).",
            })
    elif proxy_warnings:
        warnings.append({"key": "proxy_primitive", "label": "Proxy primitive used", "message": f"{proxy_warnings} objects have no materialized asset mesh and will render as proxy primitives."})

    texture_profile = os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION") or "1024"
    checks.append({"key": "texture_profile", "ok": True, "label": "Texture profile active", "level": "info", "message": f"max{texture_profile}"})
    checks.append({"key": "catalog_fallback", "ok": True, "label": "No catalog fallback", "level": "error", "message": "editor_generated_xml"})
    ok = not errors
    return {
        "ok": ok,
        "status": "ready" if ok else "blocked",
        "render_sync_mode": "editor_generated_xml",
        "xml_path": render_scene_ref,
        "texture_profile": int(texture_profile) if str(texture_profile).isdigit() else texture_profile,
        "environment": env,
        "camera_rig_id": rig.get("rig_id"),
        "sensor_count": len(sensors),
        "overlay_shape_count": overlay_shape_count,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }

def _bake_overlay_into_mitsuba_xml(base_xml_path: Path, overlay: dict[str, Any], out_path: Path) -> bool:
    """Parse base_xml_path, inject wall/glass shapes from overlay, write to out_path.

    out_path MUST be in the same directory as base_xml_path so that relative
    <string name="filename" .../> paths inside the XML remain valid.
    Returns True if at least one shape was added.
    """
    import xml.etree.ElementTree as ET

    if not base_xml_path.exists():
        return False
    # Guard: writing to a different directory breaks relative mesh paths.
    if out_path.parent.resolve() != base_xml_path.parent.resolve():
        raise ValueError(
            f"overlay XML must be written next to base XML "
            f"(base dir: {base_xml_path.parent}, out dir: {out_path.parent})"
        )
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(str(base_xml_path), parser=parser)
    root = tree.getroot()
    added = 0
    for obj in overlay.get("objects") or []:
        elem = _wall_shape_xml_element(obj)
        if elem is not None:
            root.append(elem)
            added += 1
    if added == 0:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass  # Python < 3.9 has no ET.indent
    tree.write(str(out_path), encoding="unicode", xml_declaration=False)
    return True


def _extract_render_settings_variant(render_request: RenderRequest) -> tuple[RenderRequest, str | None]:
    render_settings = dict(render_request.render_settings or {})
    variant = _maybe_str(render_settings.pop("variant", None))
    if variant is None:
        return render_request, None
    request_payload = render_request_to_payload(render_request)
    request_payload["render_settings"] = render_settings
    return render_request_from_payload(request_payload), variant


@dataclass
class _QueuedJob:
    render_request: RenderRequest
    status: RenderJobStatus
    request_payload: dict[str, Any]
    variant: str
    runtime_overrides: dict[str, Any]
    lazy_persist: bool = False  # skip disk writes at enqueue; persist just before worker dispatch
    last_progress_persist_s: float = 0.0


@dataclass
class _IsaacActiveSession:
    scene_id: str
    mitsuba_scene_ref: str
    shape_map_ref: str
    scene_snapshot_ref: str | None
    prim_to_shape_ids: dict[str, list[str]]
    objects: dict[str, IsaacObjectState]
    material_overrides: dict[str, BsdfOverride]
    sensors: dict[str, IsaacSensorSpec]
    selected_prim_paths: list[str]
    opened_at: str
    updated_at: str
    session_revision: int = 1
    state_revision: int = 0
    material_revision: int = 0
    sensor_revision: int = 0
    state_dirty: bool = True
    material_dirty: bool = False


def _object_transform_translation(transform: list[float] | None) -> list[float] | None:
    if not isinstance(transform, list) or len(transform) != 16:
        return None
    try:
        matrix = normalize_mat4_storage(transform)
    except Exception:
        return None
    return [float(matrix[0, 3]), float(matrix[1, 3]), float(matrix[2, 3])]


MATERIAL_PRESETS: list[dict[str, Any]] = [
    {
        "bsdf_type": "none",
        "category": "special",
        "title_en": "No Override",
        "title_kr": "오버라이드 없음",
        "description_en": "Keep the material that already comes from the scene.",
        "description_kr": "scene에 이미 들어 있는 재질을 그대로 사용합니다.",
        "swatch": "preset-none",
    },
    {
        "bsdf_type": "diffuse",
        "category": "paint",
        "title_en": "Diffuse",
        "title_kr": "디퓨즈",
        "description_en": "Soft matte surface with broad, even shading.",
        "description_kr": "부드러운 무광 표면입니다.",
        "swatch": "preset-diffuse",
    },
    {
        "bsdf_type": "roughplastic",
        "category": "plastic",
        "title_en": "Rough Plastic",
        "title_kr": "거친 플라스틱",
        "description_en": "Plastic body with a gentle glossy lobe.",
        "description_kr": "약한 glossy가 있는 플라스틱 느낌입니다.",
        "swatch": "preset-roughplastic",
    },
    {
        "bsdf_type": "pplastic",
        "category": "plastic",
        "title_en": "Polar Plastic",
        "title_kr": "편광 플라스틱",
        "description_en": "Polarization-aware plastic preset.",
        "description_kr": "편광 특성을 함께 보는 플라스틱 preset입니다.",
        "swatch": "preset-pplastic",
    },
    {
        "bsdf_type": "conductor",
        "category": "metal",
        "title_en": "Conductor",
        "title_kr": "금속",
        "description_en": "Clean metallic reflection with strong highlights.",
        "description_kr": "강한 하이라이트가 있는 금속 표면입니다.",
        "swatch": "preset-conductor",
    },
    {
        "bsdf_type": "roughconductor",
        "category": "metal",
        "title_en": "Rough Conductor",
        "title_kr": "거친 금속",
        "description_en": "Metal with wider, softer reflections.",
        "description_kr": "반사가 조금 더 넓고 부드러운 금속입니다.",
        "swatch": "preset-roughconductor",
    },
    {
        "bsdf_type": "dielectric",
        "category": "glass",
        "title_en": "Dielectric",
        "title_kr": "유전체",
        "description_en": "Glass-like transmissive material.",
        "description_kr": "유리 같은 투명 재질입니다.",
        "swatch": "preset-dielectric",
    },
    {
        "bsdf_type": "principled",
        "category": "paint",
        "title_en": "Principled",
        "title_kr": "프린시플드",
        "description_en": "General-purpose surface for quick look-dev.",
        "description_kr": "범용 look-dev용 preset입니다.",
        "swatch": "preset-principled",
    },
    {
        "bsdf_type": "glossy_black_lacquer",
        "category": "paint",
        "title_en": "Glossy Black Lacquer",
        "title_kr": "검정 래커",
        "description_en": "Dark glossy finish for painted pieces.",
        "description_kr": "도장된 부품에 어울리는 짙은 glossy finish입니다.",
        "swatch": "preset-glossy-black",
    },
    {
        "bsdf_type": "mirror_black_enamel",
        "category": "special",
        "title_en": "Mirror Black Enamel",
        "title_kr": "미러 블랙 에나멜",
        "description_en": "Highly reflective dark enamel look.",
        "description_kr": "매우 반사적인 짙은 에나멜 느낌입니다.",
        "swatch": "preset-mirror-black",
    },
]


@dataclass
class _IsaacRemoteCommand:
    command_id: str
    command_type: str
    scene_id: str | None
    payload: dict[str, Any]
    status: str
    created_at: str
    dispatched_at: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None
    progress_stage: str | None = None
    progress_message: str | None = None
    progress_origin: str | None = None
    progress_counts: dict[str, int] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(eq=False)
class _SceneTelemetrySubscriber:
    scene_id: str | None
    handler: BaseHTTPRequestHandler
    lock: threading.Lock

    def matches(self, scene_id: str | None) -> bool:
        return self.scene_id is None or self.scene_id == scene_id

    def send_json(self, payload: Mapping[str, Any]) -> None:
        data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        with self.lock:
            daemon = getattr(self.handler, "daemon", None)
            if daemon is None:
                raise RuntimeError("scene telemetry handler is missing daemon")
            daemon._write_ws_frame(self.handler, data)


@dataclass(eq=False)
class _JobStatusSubscriber:
    handler: BaseHTTPRequestHandler
    lock: threading.Lock

    def send_json(self, payload: Mapping[str, Any]) -> None:
        data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        with self.lock:
            daemon = getattr(self.handler, "daemon", None)
            if daemon is None:
                raise RuntimeError("job-status handler is missing daemon")
            daemon._write_ws_frame(self.handler, data)


@dataclass(eq=False)
class _GraphBuildSubscriber:
    handler: BaseHTTPRequestHandler
    lock: threading.Lock

    def send_json(self, payload: Mapping[str, Any]) -> None:
        data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        with self.lock:
            daemon = getattr(self.handler, "daemon", None)
            if daemon is None:
                raise RuntimeError("graph-build handler is missing daemon")
            daemon._write_ws_frame(self.handler, data)


_download_jobs: dict[str, dict[str, Any]] = {}
_download_jobs_lock = threading.Lock()


def _parse_hf_dataset_url(url: str) -> tuple[str, str]:
    """Parse hf-dataset://<owner>/<repo>/<path/inside/repo> into (repo_id, filename)."""
    rest = url[len("hf-dataset://"):]
    parts = rest.split("/", 2)
    if len(parts) < 3:
        raise ValueError(f"invalid hf-dataset URL: {url}")
    owner, repo, filename = parts[0], parts[1], parts[2]
    return f"{owner}/{repo}", filename


def _human_bytes(n: int | float) -> str:
    """Pretty-print a byte count. 13_000_000_000 -> '12.1 GB'."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _hf_file_size(repo_id: str, filename: str) -> int:
    """Look up the size of a single file in a HF dataset repo, in bytes.

    Returns 0 if the metadata is unavailable. Used to seed the progress
    total before download starts (Xet downloads don't drive tqdm reliably).
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return 0
    try:
        info_list = HfApi().get_paths_info(
            repo_id=repo_id, paths=[filename], repo_type="dataset"
        )
    except Exception:
        return 0
    if not info_list:
        return 0
    info = info_list[0]
    # Regular file (post-2024 schema)
    size = getattr(info, "size", 0) or 0
    if size:
        return int(size)
    # LFS-pointed file (Xet falls under LFS for size info)
    lfs = getattr(info, "lfs", None)
    if lfs is not None:
        return int(getattr(lfs, "size", 0) or 0)
    return 0


def _download_hf_dataset_file(
    repo_id: str,
    filename: str,
    dest: Path,
    progress_cb: "Callable[[int, int], None] | None" = None,
) -> None:
    """Stream a single file from a HF dataset repo into ``dest``.

    We bypass ``hf_hub_download`` because HF's Xet backend writes to a
    chunk-addressed CAS cache (``~/.cache/huggingface/xet/``) and only
    assembles the final file at the very end — meaning ``dest`` stays at 0
    bytes throughout the download and there's no way to surface progress.
    Streaming via the public ``resolve`` URL also skips the (mostly opaque)
    Xet cache, downloading directly to a ``.part`` next to ``dest`` so we
    can poll its size for accurate per-chunk progress and resume via HTTP
    Range on retry.
    """
    import requests
    from urllib.parse import quote

    base = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{quote(filename)}"

    # Resolve total size via HF API (for the progress total) — falls back to
    # Content-Length from a HEAD if API metadata is missing.
    total_bytes = _hf_file_size(repo_id, filename)
    if total_bytes <= 0:
        try:
            head = requests.head(base, allow_redirects=True, timeout=30)
            total_bytes = int(head.headers.get("Content-Length") or 0)
        except Exception:
            total_bytes = 0

    part = dest.with_suffix(dest.suffix + ".part")
    resume_pos = part.stat().st_size if part.exists() else 0
    if total_bytes and resume_pos >= total_bytes:
        # Already fully downloaded but never renamed; finalize and exit.
        part.replace(dest)
        if progress_cb:
            try:
                progress_cb(total_bytes, total_bytes)
            except Exception:
                pass
        return

    headers = {}
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"

    if progress_cb:
        try:
            progress_cb(resume_pos, total_bytes)
        except Exception:
            pass

    chunk_size = 1024 * 1024  # 1 MB
    last_emit = 0.0
    downloaded = resume_pos

    with requests.get(base, headers=headers, stream=True, timeout=(30, 300), allow_redirects=True) as r:
        if resume_pos > 0 and r.status_code == 200:
            # Server ignored Range — restart from scratch.
            downloaded = 0
            mode = "wb"
        else:
            r.raise_for_status()
            mode = "ab" if resume_pos > 0 else "wb"
        with part.open(mode) as fh:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    now = time.time()
                    # Throttle UI updates to ~5/sec to avoid lock spam.
                    if now - last_emit >= 0.2:
                        last_emit = now
                        try:
                            progress_cb(downloaded, total_bytes or downloaded)
                        except Exception:
                            pass

    # Atomic rename to final destination.
    part.replace(dest)
    if progress_cb:
        try:
            final_size = dest.stat().st_size
            progress_cb(final_size, total_bytes or final_size)
        except Exception:
            pass


# In-flight sphere-preview renders. The HTTP handler kicks the actual
# Mitsuba render off into a background daemon thread so the request thread
# returns 202 Accepted right away — otherwise a single slow render (~5–15s
# for spp=128 on the scalar variant) blocks every other request behind the
# Python GIL, which is what made /health time out at 8s while a preview was
# rendering. The set lets duplicate requests for the same key short-circuit
# instead of starting a duplicate render.
_preview_inflight: set[str] = set()
_preview_inflight_lock = threading.Lock()


# Server-side job registry for the materials page bottom panel. Lives in
# process memory only — survives browser refreshes (which previously wiped
# the log) but not daemon restarts. Capped at MAX_MATERIAL_JOBS so memory
# doesn't grow without bound. Each entry mirrors the frontend `MaterialJob`
# shape so the page can render it directly.
_material_jobs: list[dict[str, Any]] = []
_material_jobs_lock = threading.Lock()
_material_jobs_seq = 0
MAX_MATERIAL_JOBS = 200


def _create_material_job(key: str, title: str, subtitle: str, action: str) -> dict[str, Any]:
    """Append a new running-state job to the registry and return it."""
    global _material_jobs_seq
    with _material_jobs_lock:
        _material_jobs_seq += 1
        job: dict[str, Any] = {
            "id": _material_jobs_seq,
            "key": key,
            "title": title,
            "subtitle": subtitle,
            "action": action,
            "status": "running",
            "stage": "queued",
            "stage_message": "큐 대기 중",
            # Sub-render progress: current chunk index out of progress_total.
            # progress_total=0 means "no progress info" (e.g. for jobs that
            # don't render in chunks like measured renders going through
            # get_measured_preview).
            "progress": 0,
            "progress_total": 0,
            "started_at": time.time(),
            "stage_updated_at": time.time(),
            "finished_at": None,
            "error": None,
        }
        _material_jobs.insert(0, job)
        if len(_material_jobs) > MAX_MATERIAL_JOBS:
            del _material_jobs[MAX_MATERIAL_JOBS:]
        return dict(job)


def _update_material_job_stage(job_id: int, stage: str, message: str) -> None:
    """Update the live stage of a running job — e.g. 'rendering' / 'saving'."""
    with _material_jobs_lock:
        for j in _material_jobs:
            if j["id"] == job_id:
                j["stage"] = stage
                j["stage_message"] = message
                j["stage_updated_at"] = time.time()
                return


def _update_material_job_progress(job_id: int, current: int, total: int) -> None:
    """Update the live sub-step progress of a running job. Used by chunked
    Mitsuba renders to show n/N + percentage in the bottom panel."""
    with _material_jobs_lock:
        for j in _material_jobs:
            if j["id"] == job_id:
                j["progress"] = int(current)
                j["progress_total"] = int(total)
                j["stage_updated_at"] = time.time()
                return


def _set_material_job_bytes(
    job_id: int,
    done: int,
    total: int,
    speed_bps: float | None = None,
) -> None:
    """Attach byte-level progress (and optional moving-avg speed) to a job."""
    with _material_jobs_lock:
        for j in _material_jobs:
            if j["id"] == job_id:
                j["current_done_bytes"] = int(done)
                j["current_total_bytes"] = int(total)
                if speed_bps is not None:
                    j["current_speed_bps"] = float(speed_bps)
                j["stage_updated_at"] = time.time()
                return


def _finish_material_job(job_id: int, status: str, error: str | None = None) -> None:
    """Mark `job_id` as success or failed. Logs to stderr so the operator
    can verify BG-thread completion in the daemon log even when the
    frontend isn't actively polling."""
    info: dict[str, Any] | None = None
    with _material_jobs_lock:
        for j in _material_jobs:
            if j["id"] == job_id:
                j["status"] = status
                j["finished_at"] = time.time()
                j["stage"] = "done" if status == "success" else "failed"
                j["stage_message"] = "완료" if status == "success" else (error or "실패")
                j["stage_updated_at"] = time.time()
                if error is not None:
                    j["error"] = error
                info = {"key": j["key"], "elapsed": j["finished_at"] - j["started_at"]}
                break
    if info is not None:
        suffix = f" — {error}" if error else ""
        print(
            f"[daemon] material-job #{job_id} {info['key']} -> {status}"
            f" ({info['elapsed']:.1f}s){suffix}",
            file=sys.stderr,
            flush=True,
        )


def _list_material_jobs() -> list[dict[str, Any]]:
    with _material_jobs_lock:
        return [dict(j) for j in _material_jobs]


def _clear_finished_material_jobs() -> int:
    with _material_jobs_lock:
        before = len(_material_jobs)
        _material_jobs[:] = [j for j in _material_jobs if j["status"] == "running"]
        return before - len(_material_jobs)


def _claim_preview_inflight(key: str) -> bool:
    """Reserve `key` if no render for it is in progress; return True if claimed."""
    with _preview_inflight_lock:
        if key in _preview_inflight:
            return False
        _preview_inflight.add(key)
        return True


def _release_preview_inflight(key: str) -> None:
    with _preview_inflight_lock:
        _preview_inflight.discard(key)


# Single-worker queue for preview renders.
#
# Why a queue (and not a fresh thread per call): historically each
# `_spawn_preview_render` call started its own thread and relied on
# `_mitsuba_render_lock` to serialize the actual `mi.render()`. That kept
# the GPU usage technically serial, BUT all the Python `threading.Thread`
# objects + their per-thread Mitsuba scene/Dr.Jit state stayed alive
# concurrently. With ~12 hpBRDF threads queued behind one another, the
# GPU residue from each loaded measured_polarized BSDF accumulated
# (Dr.Jit's allocator doesn't release CUDA memory eagerly across thread
# boundaries) and the next render OOMed.
#
# Single worker means one Python frame, one Mitsuba scene, one BSDF in
# GPU memory at a time — and the scene + scene_dict refs go out of scope
# fully between iterations so `_release_gpu_pool()` actually reclaims.
import queue as _queue
import gc as _gc

_preview_render_queue: "_queue.Queue[tuple[str, Any, float]]" = _queue.Queue()
_preview_worker_thread: threading.Thread | None = None
_preview_worker_start_lock = threading.Lock()


def _preview_worker_loop() -> None:
    while True:
        key, render_fn, enqueued_at = _preview_render_queue.get()
        wait_s = time.perf_counter() - enqueued_at
        depth_after = _preview_render_queue.qsize()
        print(
            f"[daemon] preview_queue: start key={key} waited={wait_s:.2f}s queue_depth_after={depth_after}",
            file=sys.stderr, flush=True,
        )
        t_start = time.perf_counter()
        outcome = "ok"
        try:
            render_fn()
        except Exception as exc:
            outcome = "failed"
            print(
                f"[daemon] preview render failed ({key}): {exc}",
                file=sys.stderr, flush=True,
            )
        finally:
            _release_preview_inflight(key)
            elapsed = time.perf_counter() - t_start
            print(
                f"[daemon] preview_queue: done key={key} outcome={outcome} elapsed={elapsed:.2f}s "
                f"total_wait_plus_run={wait_s + elapsed:.2f}s",
                file=sys.stderr, flush=True,
            )
            # Force a GC pass between renders so the previous scene's
            # Python refs go away and `_release_gpu_pool()` (called
            # inside the render itself) actually frees CUDA memory
            # before we start the next one.
            _gc.collect()


def _ensure_preview_worker() -> None:
    """Lazily start the single preview worker thread on first enqueue."""
    global _preview_worker_thread
    with _preview_worker_start_lock:
        if _preview_worker_thread is None or not _preview_worker_thread.is_alive():
            _preview_worker_thread = threading.Thread(
                target=_preview_worker_loop,
                daemon=True,
                name="preview-worker",
            )
            _preview_worker_thread.start()


def _spawn_preview_render(key: str, render_fn: Any) -> None:
    """Enqueue `render_fn()` onto the SINGLE preview worker thread.

    Name kept for backward compat with all the existing call sites — the
    semantics are now "queue for serial execution" rather than "fork a
    new thread immediately". Inflight tracking still runs: callers
    `_claim_preview_inflight(key)` BEFORE calling this; the worker
    releases inflight in its finally clause.

    Emits a ``preview_queue: enqueue`` line so operators can see the
    queue depth at admission time — `[http] ... 202 -` alone hides
    whether the daemon is keeping up.
    """
    _ensure_preview_worker()
    enqueued_at = time.perf_counter()
    depth_before = _preview_render_queue.qsize()
    _preview_render_queue.put((key, render_fn, enqueued_at))
    print(
        f"[daemon] preview_queue: enqueue key={key} queue_depth_before={depth_before}",
        file=sys.stderr, flush=True,
    )


# ── Phase R: subprocess-mode preview render dispatch ────────────────────

# Maps worker_job_id (string sent across JSONL) → daemon-side metadata so
# the listener can update _material_jobs / _preview_inflight without
# leaking those internals through the JSONL protocol.
_render_worker_job_meta: dict[str, dict[str, Any]] = {}
_render_worker_job_meta_lock = threading.Lock()


def _register_render_worker_job(
    worker_job_id: str,
    *,
    material_job_id: int,
    inflight_key: str,
) -> None:
    with _render_worker_job_meta_lock:
        _render_worker_job_meta[worker_job_id] = {
            "material_job_id": int(material_job_id),
            "inflight_key": str(inflight_key),
        }


def _peek_render_worker_job_meta(worker_job_id: str) -> dict[str, Any] | None:
    with _render_worker_job_meta_lock:
        meta = _render_worker_job_meta.get(worker_job_id)
        return dict(meta) if meta else None


def _pop_render_worker_job_meta(worker_job_id: str) -> dict[str, Any] | None:
    with _render_worker_job_meta_lock:
        return _render_worker_job_meta.pop(worker_job_id, None)


# Translate the worker's failure ``reason`` codes into the user-facing
# Korean messages that the existing UI was displaying. Keeps the move to
# subprocess invisible to the bottom-panel reader.
_PHASE_R_REASON_MESSAGES: dict[str, str] = {
    "plugin_unavailable": (
        "GPU(CUDA) 변종이 빌드되지 않았거나, 이 재질이 패치된 "
        "Mitsuba 빌드를 요구합니다 (hpBRDF 등)"
    ),
    "mitsuba_unavailable": "Mitsuba 임포트 실패",
    "load_error": "파일 파싱 실패 (포맷 불일치)",
    "optix_unavailable": (
        "OptiX 초기화 실패 — 호스트 NVIDIA 드라이버가 OptiX 8 요구사항(R535+)보다 낮습니다. "
        "ROBOMITUBA_DISABLE_CUDA=1 로 CPU variant를 사용하세요."
    ),
    "gpu_oom": (
        "GPU/host-pinned 메모리 부족 — hpBRDF는 파일당 13 GB라 "
        "다른 큰 작업 종료 후 재시도하세요"
    ),
    "not_downloaded": "원본 파일 없음 — 먼저 다운로드 필요",
    "placeholder": "원본 파일 없음 — placeholder 사용",
    "missing_path": "측정 BSDF 파일 경로가 비어있습니다",
    "unknown_material": "큐레이션 머터리얼 ID 를 찾지 못했습니다",
    "unknown_kind": "워커가 인식하지 못한 작업 종류입니다",
    "bad_request": "워커로 보낸 요청이 형식에 맞지 않습니다",
    "exception": "워커에서 처리되지 않은 예외 — daemon 로그 확인 필요",
    "worker_exited": "렌더 워커 프로세스가 비정상 종료됨 — 자동 재시작됨",
    "worker_restarting": "워커 재기동 중이라 이 작업은 실행되지 못함 — 명시적 재시도 필요",
    "worker_pipe_broken": "워커 stdin 파이프가 닫힘 — 매니저가 재시작 중",
    "heartbeat_timeout": "워커 heartbeat timeout — 자동 재시작됨",
    "job_cancelled": "작업이 취소되었습니다",
    "manager_degraded": "워커 매니저가 degraded 상태 — daemon 재시작 필요",
    "no_worker": "사용 가능한 렌더 워커 없음",
}

_RETRYABLE_RENDER_FAILURE_REASONS = {
    "worker_exited",
    "worker_restarting",
    "worker_pipe_broken",
    "heartbeat_timeout",
    "no_worker",
}


def _spawn_preview_render_subprocess(
    daemon: "RenderDaemon",
    key: str,
    payload: dict[str, Any],
    *,
    material_job_id: int,
) -> None:
    """Submit a render job to the WorkerManager subprocess.

    Mirrors :func:`_spawn_preview_render` semantics (enqueue line + serial
    in-order delivery to a single worker) but routes via the JSON-RPC
    subprocess instead of the in-process closure thread. ``payload`` must
    be a JSON-serializable dict matching ``preview_worker._dispatch``'s
    request envelope. The caller is responsible for having claimed
    ``_preview_inflight`` and created the material_job; this function
    only registers the worker→daemon lookup metadata and enqueues.
    """
    worker_job_id = f"matjob-{material_job_id}"
    payload = dict(payload)
    payload["job_id"] = worker_job_id
    _register_render_worker_job(
        worker_job_id, material_job_id=material_job_id, inflight_key=key,
    )
    mgr = daemon._ensure_render_worker_manager()
    mgr.submit(payload)
    print(
        f"[daemon] preview_queue: enqueue (subprocess) key={key} "
        f"worker_job_id={worker_job_id} kind={payload.get('kind')}",
        file=sys.stderr, flush=True,
    )


class RenderDaemon:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        host: str = "127.0.0.1",
        port: int = 8765,
        variant: str = "auto",
        render_fn: RenderFn | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.host = host
        self.port = int(port)
        self.variant = variant
        self.render_fn = render_fn or render_timestep_bundle_split_lighting

        self._condition = threading.Condition()
        self._pending: deque[str] = deque()
        self._jobs: dict[str, _QueuedJob] = {}
        self._scene_cache_stats: dict[str, dict[str, Any]] = {}
        self._path_size_cache: dict[str, dict[str, Any]] = {}
        self._telemetry_cache: dict[str, Any] = {"path": None, "mtime_ns": None, "rows": []}
        # TTL caches for expensive glob+deserialize operations in request handlers
        self._job_status_cache: list[Any] | None = None
        self._job_status_cache_ts: float = 0.0
        self._bundle_manifest_cache: list[Any] | None = None
        self._bundle_manifest_cache_ts: float = 0.0
        # Per-path (mtime, parsed) index so the bridge_jobs scans don't
        # re-deserialize unchanged (terminal) jobs every refresh — the full
        # re-read dominated startup/request latency on the CIFS mount with
        # thousands of accumulated jobs. TTLs are env-tunable for slow mounts.
        self._job_status_index: dict[str, tuple[float, Any]] = {}
        self._bundle_manifest_index: dict[str, tuple[float, Any]] = {}

        def _env_float(name: str, default: float) -> float:
            try:
                return max(0.0, float(os.environ.get(name, "").strip() or default))
            except (TypeError, ValueError):
                return default

        self._job_status_ttl_s: float = _env_float("ROBOMITUBA_JOB_SCAN_TTL_S", 5.0)
        self._bundle_manifest_ttl_s: float = _env_float("ROBOMITUBA_BUNDLE_SCAN_TTL_S", 5.0)
        self._session_inventory_cache: list[Any] | None = None
        self._session_inventory_cache_ts: float = 0.0
        self._geometry_bounds_cache: dict[str, dict[str, Any] | None] = {}
        self._isaac_session: _IsaacActiveSession | None = None
        self._isaac_commands_pending: deque[str] = deque()
        self._isaac_commands: dict[str, _IsaacRemoteCommand] = {}
        self._debug_events: deque[dict[str, Any]] = deque(maxlen=50)
        self._debug_event_counter: int = 0
        self._scene_telemetry_subscribers: set[_SceneTelemetrySubscriber] = set()
        self._scene_telemetry_lock = threading.Lock()
        self._last_scene_telemetry_signature: tuple[Any, ...] | None = None
        self._shutdown = False
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None

        # USD stage cache: repo-relative usd_ref → opened Usd.Stage (or None on failure)
        self._usd_stage_cache: dict[str, Any] = {}
        self._usd_stage_lock = threading.Lock()
        # mesh_cache index: keyed by (scene_cache_dir_str) → dict[(usd_ref, prim_path) → (obj_path, meta)]
        self._mesh_cache_index: dict[str, dict[tuple[str, str], tuple[Path, dict[str, Any]]]] = {}
        self._mesh_cache_index_lock = threading.Lock()
        # Thumbnail background generation: asset_id → threading.Event (set when done)
        self._thumb_gen_pending: set[str] = set()
        self._thumb_gen_lock = threading.Lock()

        # Phase R: render subprocess manager. Lazily spawned on first
        # subprocess-mode render submission so that an INPROCESS=1
        # rollout never pays the worker startup cost.
        self._render_worker_manager: WorkerManager | None = None
        self._render_worker_manager_lock = threading.Lock()

        self._graph_build_progress: dict[str, dict[str, Any]] = {}
        self._graph_build_lock = threading.Lock()
        self._graph_edit_locks: dict[tuple[str, str], threading.RLock] = {}
        self._graph_edit_locks_lock = threading.Lock()

        self._job_status_subscribers: set[_JobStatusSubscriber] = set()
        self._job_status_sub_lock = threading.Lock()

        self._graph_build_subscribers: dict[str, set[_GraphBuildSubscriber]] = {}
        self._graph_build_sub_lock = threading.Lock()

        # OpticalNav sync (render-scene) async jobs.
        # Keyed by sync_job_id → latest progress payload. The final completion
        # payload (status='done'|'error', result=...) stays in the dict so a
        # late-connecting WS subscriber can still pick it up.
        self._opticalnav_sync_progress: dict[str, dict[str, Any]] = {}
        self._opticalnav_sync_lock = threading.Lock()
        self._opticalnav_sync_subscribers: dict[str, set[_GraphBuildSubscriber]] = {}
        self._opticalnav_sync_sub_lock = threading.Lock()

        # Scene-bundle export jobs — per-job status dict + WS subscribers.
        # The worker thread updates `_export_jobs[job_id]` and broadcasts each
        # change to any `_export_job_subscribers[job_id]` over the matching WS
        # connection. status.json is persisted to disk for polling fallback.
        self._export_jobs: dict[str, dict[str, Any]] = {}
        self._export_jobs_lock = threading.Lock()
        self._export_job_subscribers: dict[str, set[_GraphBuildSubscriber]] = {}
        self._export_job_sub_lock = threading.Lock()

        asset_root = Path(__file__).resolve().parent
        self._static_dir = asset_root / "static"
        self._spa_dir = asset_root / "static" / "app"

    def _opticalnav_graph_edit_lock(self, project_dir: Path, scene_id: str) -> threading.RLock:
        key = (str(Path(project_dir).resolve()), str(scene_id))
        with self._graph_edit_locks_lock:
            lock = self._graph_edit_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._graph_edit_locks[key] = lock
            return lock

    @staticmethod
    def _bump_viewpoint_graph_revision(graph: Any, client_op_ids: Sequence[str] = ()) -> tuple[int, int]:
        meta = dict(getattr(graph, "metadata", None) or {})
        try:
            before = int(meta.get("revision", 0) or 0)
        except (TypeError, ValueError):
            before = 0
        after = before + 1
        meta["revision"] = after
        if client_op_ids:
            existing = [str(item) for item in (meta.get("applied_client_op_ids") or []) if item]
            seen = set(existing)
            for op_id in client_op_ids:
                if op_id and op_id not in seen:
                    existing.append(op_id)
                    seen.add(op_id)
            meta["applied_client_op_ids"] = existing[-500:]
        graph.metadata = meta
        return before, after

    def _apply_opticalnav_graph_edits(
        self,
        handler: BaseHTTPRequestHandler,
        project_dir: Path,
        scene_id: str,
        payload: Mapping[str, Any],
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        from navigation_dataset.graph_edit_log import edge_record as _erec, graph_size as _gsz, node_record as _nrec
        from navigation_dataset.viewpoint_graph import (
            append_edge,
            find_edge_by_endpoints,
            read_viewpoint_graph,
            remove_edge,
            write_viewpoint_graph,
        )

        scene_dir = project_dir / "scenes" / scene_id
        graph_path = scene_dir / "viewpoint_graph.json"
        if not graph_path.exists():
            return HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"}
        raw_ops = payload.get("ops")
        if not isinstance(raw_ops, list) or not raw_ops:
            return HTTPStatus.BAD_REQUEST, {"error": "graph edits require a non-empty ops list"}
        client_batch_id = _maybe_str(payload.get("client_batch_id"))

        with self._opticalnav_graph_edit_lock(project_dir, scene_id):
            graph = read_viewpoint_graph(graph_path)
            meta = dict(getattr(graph, "metadata", None) or {})
            try:
                revision_before = int(meta.get("revision", 0) or 0)
            except (TypeError, ValueError):
                revision_before = 0
            applied_ids = [str(item) for item in (meta.get("applied_client_op_ids") or []) if item]
            applied_set = set(applied_ids)
            new_applied_ids: list[str] = []
            results: list[dict[str, Any]] = []
            log_events: list[dict[str, Any]] = []
            changed = False

            for raw in raw_ops:
                if not isinstance(raw, Mapping):
                    results.append({"ok": False, "error": "op must be an object"})
                    continue
                op_type = str(raw.get("type") or "")
                client_op_id = _maybe_str(raw.get("client_op_id"))
                if client_op_id and client_op_id in applied_set:
                    results.append({"client_op_id": client_op_id, "ok": True, "duplicate_client_op": True})
                    continue

                if op_type == "add_edge":
                    source = str(raw.get("source") or "")
                    target = str(raw.get("target") or "")
                    if not source or not target or source == target:
                        results.append({"client_op_id": client_op_id, "ok": False, "type": op_type, "error": "source/target node ids required and must differ"})
                        continue
                    before = _gsz(graph)
                    existing = find_edge_by_endpoints(graph, source, target)
                    try:
                        distance_m = float(raw["distance_m"]) if raw.get("distance_m") is not None else None
                        weight = float(raw["weight"]) if raw.get("weight") is not None else None
                    except (TypeError, ValueError):
                        results.append({"client_op_id": client_op_id, "ok": False, "type": op_type, "source": source, "target": target, "error": "distance_m/weight must be numeric"})
                        continue
                    edge = append_edge(graph, source, target, distance_m=distance_m, weight=weight)
                    if edge is None:
                        results.append({"client_op_id": client_op_id, "ok": False, "type": op_type, "source": source, "target": target, "error": "Could not append edge (unknown source/target?)"})
                        continue
                    is_new = existing is None
                    changed = changed or is_new
                    if client_op_id:
                        new_applied_ids.append(client_op_id)
                        applied_set.add(client_op_id)
                    results.append({
                        "client_op_id": client_op_id,
                        "ok": True,
                        "type": op_type,
                        "edge_id": edge.edge_id,
                        "source": edge.source,
                        "target": edge.target,
                        "distance_m": edge.distance_m,
                        "duplicate_edge": not is_new,
                    })
                    log_events.append({
                        "operation": "add_edge",
                        "graph_id": getattr(graph, "graph_id", None),
                        "client_batch_id": client_batch_id,
                        "client_op_id": client_op_id,
                        "revision_before": revision_before,
                        "before": before,
                        "after": _gsz(graph),
                        "params": {"source": source, "target": target, "distance_m": raw.get("distance_m"), "weight": raw.get("weight")},
                        "added_edge": {
                            "id": edge.edge_id,
                            "source": edge.source,
                            "target": edge.target,
                            "source_pos": (_nrec(graph, edge.source) or {}).get("position"),
                            "target_pos": (_nrec(graph, edge.target) or {}).get("position"),
                            "distance_m": edge.distance_m,
                            "duplicate_edge": not is_new,
                        },
                    })
                    continue

                if op_type == "delete_edge":
                    edge_id = str(raw.get("edge_id") or "")
                    if not edge_id:
                        results.append({"client_op_id": client_op_id, "ok": False, "type": op_type, "error": "edge_id required"})
                        continue
                    before = _gsz(graph)
                    rec = _erec(graph, edge_id)
                    ok = remove_edge(graph, edge_id)
                    if not ok:
                        results.append({"client_op_id": client_op_id, "ok": False, "type": op_type, "edge_id": edge_id, "error": f"edge_id not found: {edge_id}"})
                        continue
                    changed = True
                    if client_op_id:
                        new_applied_ids.append(client_op_id)
                        applied_set.add(client_op_id)
                    results.append({"client_op_id": client_op_id, "ok": True, "type": op_type, "edge_id": edge_id, "deleted": True})
                    log_events.append({
                        "operation": "delete_edge",
                        "graph_id": getattr(graph, "graph_id", None),
                        "client_batch_id": client_batch_id,
                        "client_op_id": client_op_id,
                        "revision_before": revision_before,
                        "before": before,
                        "after": _gsz(graph),
                        "params": {"edge_id": edge_id},
                        "deleted_edges": [rec] if rec else [],
                    })
                    continue

                results.append({"client_op_id": client_op_id, "ok": False, "type": op_type or None, "error": f"unsupported op type: {op_type or 'missing'}"})

            if changed or new_applied_ids:
                _rev_before, revision_after = self._bump_viewpoint_graph_revision(graph, new_applied_ids)
                write_viewpoint_graph(graph_path, graph)
            else:
                revision_after = revision_before

            for event in log_events:
                event["revision_after"] = revision_after
                _log_graph_edit(handler, project_dir, scene_id, event)

            return HTTPStatus.OK, {
                "ok": True,
                "graph_id": getattr(graph, "graph_id", None),
                "revision": revision_after,
                "node_count": len(getattr(graph, "nodes", []) or []),
                "edge_count": len(getattr(graph, "edges", []) or []),
                "results": results,
            }

    # ── Phase R: render worker subprocess wiring ────────────────────────

    def _ensure_render_worker_manager(self) -> WorkerManager:
        """Lazily start the render worker subprocess manager + listener."""
        if _backend_only_mode():
            raise RuntimeError("render_queue_disabled: this process was launched with ROBOMITUBA_BACKEND_ONLY=1")
        with self._render_worker_manager_lock:
            if self._render_worker_manager is not None:
                return self._render_worker_manager
            worker_count = max(1, int(os.environ.get("ROBOMITUBA_RENDER_WORKER_COUNT", "1") or "1"))
            mgr = WorkerManager(repo_root=self.repo_root, worker_count=worker_count)
            mgr.add_listener(self._on_render_worker_event)
            mgr.start()
            self._render_worker_manager = mgr
            return mgr

    def _on_render_worker_event(self, event: dict[str, Any]) -> None:
        """Translate worker JSONL events back into daemon-side state mutations.

        Looks up daemon-side metadata (material job id + inflight key) by
        the worker's job_id via :func:`_peek_render_worker_job_meta`, so
        the protocol can stay opaque about daemon internals.
        """
        kind = str(event.get("type") or "")
        if kind in ("heartbeat", "ready", "log"):
            return
        worker_job_id = str(event.get("job_id") or "")
        if not worker_job_id:
            return
        meta = _peek_render_worker_job_meta(worker_job_id)
        if meta is None:
            # No preview meta → this is a render_job (Phase R-4) whose
            # daemon-side state lives in ``self._jobs`` keyed by the
            # same string job_id, or a stale event after restart.
            with self._condition:
                render_job = self._jobs.get(worker_job_id)
            if render_job is not None:
                self._handle_render_job_event(worker_job_id, kind, event)
                return
            if kind == "failed":
                print(
                    f"[daemon] render_worker: unmapped failed event "
                    f"job_id={worker_job_id!r} reason={event.get('reason')!r}",
                    file=sys.stderr, flush=True,
                )
            return
        material_job_id = int(meta["material_job_id"])
        inflight_key = str(meta["inflight_key"])

        if kind == "started":
            _update_material_job_stage(
                material_job_id, "rendering",
                "워커에서 렌더 시작",
            )
        elif kind == "progress":
            stage = str(event.get("stage") or "rendering")
            message = event.get("message")
            if isinstance(message, str) and message:
                _update_material_job_stage(material_job_id, stage, message)
            current = event.get("current")
            total = event.get("total")
            if isinstance(current, int) and isinstance(total, int) and total > 0:
                _update_material_job_progress(material_job_id, current, total)
        elif kind == "completed":
            _update_material_job_stage(material_job_id, "saved", "PNG 저장 완료")
            _finish_material_job(material_job_id, "success")
            _release_preview_inflight(inflight_key)
            _pop_render_worker_job_meta(worker_job_id)
        elif kind == "failed":
            reason = str(event.get("reason") or "unknown")
            message_raw = event.get("message")
            if isinstance(message_raw, str) and message_raw:
                message = message_raw
            else:
                message = _PHASE_R_REASON_MESSAGES.get(reason, f"render unavailable: {reason}")
            _finish_material_job(material_job_id, "failed", message)
            _release_preview_inflight(inflight_key)
            _pop_render_worker_job_meta(worker_job_id)

    def _handle_render_job_event(self, job_id: str, kind: str, event: dict[str, Any]) -> None:
        """Map worker events back onto a Phase R-4 render_job in ``self._jobs``.

        ``started`` is a no-op (the dispatcher thread already marked the
        job ``running`` when it popped from ``_pending``). The terminal
        events drive ``_mark_succeeded`` / ``_mark_failed`` which finalise
        on-disk status, telemetry and the log.
        """
        if kind == "started":
            # Dispatcher already set status=running; store the actual worker
            # handoff timestamp so UI duration excludes per-worker queue wait.
            worker_started_at = _event_ts_iso(event.get("ts")) or _utc_now_iso()
            with self._condition:
                job = self._jobs.get(job_id)
                if job is not None and job.status.status != "cancelled":
                    job.status.worker_started_at = worker_started_at
                    job.status.extras["worker_started_at"] = worker_started_at
                    actual_gpu = event.get("gpu_index")
                    if actual_gpu is not None:
                        try:
                            job.status.extras["actual_gpu_index"] = int(actual_gpu)
                        except (TypeError, ValueError):
                            job.status.extras["actual_gpu_index"] = actual_gpu
            if job is not None:
                self._persist_status_unlocked(job)
                self._append_job_log_line(
                    job, event_type="running", stage="worker_started",
                    message="worker subprocess accepted job",
                    event_ts=event.get("ts"),
                )
            return
        if kind == "progress":
            stage = str(event.get("stage") or "rendering")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else None
            self._update_progress(job_id, stage, payload, event_ts=event.get("ts"))
            return
        if kind == "routing_fallback":
            with self._condition:
                job = self._jobs.get(job_id)
                if job is None or job.status.status == "cancelled":
                    return
                job.status.extras["routing_fallback_reason"] = str(event.get("reason") or "unknown")
                if event.get("target_gpu_index") is not None:
                    job.status.extras["routing_fallback_target_gpu_index"] = event.get("target_gpu_index")
                if event.get("routed_gpu_index") is not None:
                    job.status.extras["routed_gpu_index"] = event.get("routed_gpu_index")
            message = str(event.get("message") or "worker routing fallback")
            self._append_job_log_line(job, event_type="routing", stage="routing_fallback", message=message)
            self._persist_status_unlocked(job)
            return
        if kind == "completed":
            manifest_path = event.get("manifest_path")
            if not manifest_path:
                # Worker emitted out_path style — synthesise the manifest path.
                out_path = event.get("out_path") or ""
                manifest_path = f"{out_path}/manifest.json" if out_path else ""
            if not manifest_path:
                self._mark_failed(job_id, "worker_completed_without_manifest", event_ts=event.get("ts"))
                return
            self._mark_succeeded(job_id, manifest_path=str(manifest_path), event_ts=event.get("ts"))
            return
        if kind == "failed":
            reason = str(event.get("reason") or "unknown")
            with self._condition:
                current = self._jobs.get(job_id)
                if current is None or current.status.status == "cancelled":
                    return
            message_raw = event.get("message")
            if isinstance(message_raw, str) and message_raw:
                message = f"{reason}: {message_raw}"
            else:
                fallback = _PHASE_R_REASON_MESSAGES.get(reason, "render unavailable")
                message = f"{reason}: {fallback}"
            if self._retry_render_job(job_id, reason=reason, message=message):
                return
            with self._condition:
                failed_job = self._jobs.get(job_id)
            if failed_job is not None and self._is_gpu_scene_prepare_failure(failed_job):
                texture_profile = self._job_texture_profile(failed_job)
                if texture_profile and texture_profile <= 1024:
                    message = f"gpu_scene_load_failed texture_profile={texture_profile}: {message}"
            self._mark_failed(job_id, message)
            return

    def _isaac_scene_catalog_path(self) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "isaac_scene_catalog.json"

    def _isaac_command_telemetry_path(self) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "isaac_command_telemetry.jsonl"

    def _render_options_path(self, scene_id: str) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "scene_render_options" / f"{scene_id}.json"

    def _camera_rigs_dir(self) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "camera_rigs"

    def _camera_rig_path(self, rig_id: str) -> Path:
        safe_id = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(rig_id or "").strip())
        if not safe_id:
            raise ValueError("rig_id is required.")
        return self._camera_rigs_dir() / f"{safe_id}.json"

    def _default_camera_rig(self, rig_id: str = "ranger_mini_default") -> dict[str, Any]:
        now = _utc_now_iso()
        base_intrinsics = {
            "resolution": [640, 360],
            "fov_h_deg": 75.0,
            "fov_v_deg": 60.0,
            "focal_length_px": 410.0,
            "clip_near_m": 0.10,
            "clip_far_m": 30.0,
        }
        base_render = {
            "path_spp": 4096,
            "aov_spp": 16,
            "polar_spp": 256,
            "samples_per_pass": None,
        }
        return {
            "rig_id": rig_id,
            "label": "Ranger Mini default optical rig",
            "robot_model": "ranger_mini_v3",
            "base_frame": "base_link",
            "updated_at": now,
            "sensors": [
                {
                    "sensor_id": "opticalnav_front_cam",
                    "sensor_type": "rgb_camera",
                    "modalities": ["rgb"],
                    "enabled": True,
                    "mount": {"parent_frame": "base_link", "xyz_m": [0.0, 0.40, 0.80], "rpy_deg": [0.0, 0.0, 0.0]},
                    "intrinsics": dict(base_intrinsics),
                    "render": dict(base_render),
                },
                {
                    "sensor_id": "opticalnav_left_nir",
                    "sensor_type": "nir_camera",
                    "modalities": ["nir_intensity"],
                    "enabled": True,
                    "mount": {"parent_frame": "base_link", "xyz_m": [-0.30, 0.35, 0.72], "rpy_deg": [0.0, 0.0, 90.0]},
                    "intrinsics": dict(base_intrinsics),
                    "render": dict(base_render),
                    "nir": {"wavelength_min_nm": 830.0, "wavelength_max_nm": 870.0, "active_emitter_radiance": 40.0},
                },
                {
                    "sensor_id": "opticalnav_right_polar",
                    "sensor_type": "polar_camera",
                    "modalities": ["polar_rgb_preview", "dop", "aolp", "s1", "s2"],
                    "enabled": True,
                    "mount": {"parent_frame": "base_link", "xyz_m": [0.30, 0.35, 0.72], "rpy_deg": [0.0, 0.0, -90.0]},
                    "intrinsics": dict(base_intrinsics),
                    "render": dict(base_render),
                    "polarization": {"polarizer_angle_deg": 0.0},
                },
                {
                    "sensor_id": "opticalnav_rear_cam",
                    "sensor_type": "rgb_camera",
                    "modalities": ["rgb"],
                    "enabled": True,
                    "mount": {"parent_frame": "base_link", "xyz_m": [0.0, -0.35, 0.82], "rpy_deg": [0.0, 0.0, 180.0]},
                    "intrinsics": dict(base_intrinsics),
                    "render": dict(base_render),
                },
            ],
        }

    def _as_finite_float(self, value: Any, *, name: str) -> float:
        try:
            number = float(value)
        except Exception as exc:
            raise ValueError(f"{name} must be numeric.") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite.")
        return number

    def _as_positive_int(self, value: Any, *, name: str) -> int:
        try:
            number = int(value)
        except Exception as exc:
            raise ValueError(f"{name} must be an integer.") from exc
        if number <= 0:
            raise ValueError(f"{name} must be positive.")
        return number

    def _as_float_vec(self, value: Any, *, name: str, length: int) -> list[float]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != length:
            raise ValueError(f"{name} must be a {length}-element array.")
        return [self._as_finite_float(item, name=f"{name}[{idx}]") for idx, item in enumerate(value)]

    def _normalize_camera_rig_render_settings(self, value: Any, *, sensor_id: str, sensor_type: str) -> dict[str, Any]:
        raw = value if isinstance(value, Mapping) else {}
        defaults = {
            "path_spp": 1 if sensor_type == "lidar_3d" else 4096,
            "aov_spp": 1 if sensor_type == "lidar_3d" else 16,
            "polar_spp": 1 if sensor_type == "lidar_3d" else 256,
            "samples_per_pass": None,
        }
        samples_per_pass = raw.get("samples_per_pass", defaults["samples_per_pass"])
        return {
            "path_spp": self._as_positive_int(raw.get("path_spp", defaults["path_spp"]), name=f"{sensor_id}.render.path_spp"),
            "aov_spp": self._as_positive_int(raw.get("aov_spp", defaults["aov_spp"]), name=f"{sensor_id}.render.aov_spp"),
            "polar_spp": self._as_positive_int(raw.get("polar_spp", defaults["polar_spp"]), name=f"{sensor_id}.render.polar_spp"),
            "samples_per_pass": None if samples_per_pass in (None, "") else self._as_positive_int(samples_per_pass, name=f"{sensor_id}.render.samples_per_pass"),
        }

    def _normalize_camera_rig(self, payload: Mapping[str, Any], *, rig_id: str | None = None) -> dict[str, Any]:
        allowed_types = {"rgb_camera", "nir_camera", "polar_camera", "lidar_3d"}
        default_modalities = {
            "rgb_camera": ["rgb"],
            "nir_camera": ["nir_intensity"],
            "polar_camera": ["polar_rgb_preview", "dop", "aolp", "s1", "s2"],
            "lidar_3d": ["lidar_point_cloud"],
        }
        normalized_rig_id = str(rig_id or payload.get("rig_id") or "").strip()
        if not normalized_rig_id:
            raise ValueError("rig_id is required.")
        sensors_raw = payload.get("sensors")
        if not isinstance(sensors_raw, Sequence) or isinstance(sensors_raw, (str, bytes)):
            raise ValueError("sensors must be an array.")
        seen: set[str] = set()
        sensors: list[dict[str, Any]] = []
        for idx, raw in enumerate(sensors_raw):
            if not isinstance(raw, Mapping):
                raise ValueError(f"sensors[{idx}] must be an object.")
            sensor_id = str(raw.get("sensor_id") or "").strip()
            if not sensor_id:
                raise ValueError(f"sensors[{idx}].sensor_id is required.")
            if sensor_id in seen:
                raise ValueError(f"duplicate sensor_id: {sensor_id}")
            seen.add(sensor_id)
            sensor_type = str(raw.get("sensor_type") or "").strip()
            if sensor_type not in allowed_types:
                raise ValueError(f"{sensor_id}: sensor_type must be one of {sorted(allowed_types)}.")
            modalities_raw = raw.get("modalities") or default_modalities[sensor_type]
            if not isinstance(modalities_raw, Sequence) or isinstance(modalities_raw, (str, bytes)):
                raise ValueError(f"{sensor_id}: modalities must be an array.")
            modalities = [str(item) for item in modalities_raw if str(item).strip()]
            mount_raw = raw.get("mount") if isinstance(raw.get("mount"), Mapping) else {}
            intr_raw = raw.get("intrinsics") if isinstance(raw.get("intrinsics"), Mapping) else {}
            resolution_raw = intr_raw.get("resolution", [640, 360])
            if not isinstance(resolution_raw, Sequence) or isinstance(resolution_raw, (str, bytes)) or len(resolution_raw) != 2:
                raise ValueError(f"{sensor_id}: intrinsics.resolution must be [width, height].")
            resolution = [int(resolution_raw[0]), int(resolution_raw[1])]
            if resolution[0] <= 0 or resolution[1] <= 0:
                raise ValueError(f"{sensor_id}: resolution values must be positive.")
            near = self._as_finite_float(intr_raw.get("clip_near_m", 0.10), name=f"{sensor_id}.clip_near_m")
            far = self._as_finite_float(intr_raw.get("clip_far_m", 30.0), name=f"{sensor_id}.clip_far_m")
            if near <= 0 or far <= near:
                raise ValueError(f"{sensor_id}: clipping planes must satisfy 0 < near < far.")
            intrinsics = {
                "resolution": resolution,
                "fov_h_deg": self._as_finite_float(intr_raw.get("fov_h_deg", 75.0), name=f"{sensor_id}.fov_h_deg"),
                "fov_v_deg": self._as_finite_float(intr_raw.get("fov_v_deg", 60.0), name=f"{sensor_id}.fov_v_deg"),
                "focal_length_px": self._as_finite_float(intr_raw.get("focal_length_px", 410.0), name=f"{sensor_id}.focal_length_px"),
                "clip_near_m": near,
                "clip_far_m": far,
            }
            if intrinsics["fov_h_deg"] <= 0 or intrinsics["fov_v_deg"] <= 0:
                raise ValueError(f"{sensor_id}: FOV values must be positive.")
            sensor: dict[str, Any] = {
                "sensor_id": sensor_id,
                "sensor_type": sensor_type,
                "modalities": modalities,
                "enabled": bool(raw.get("enabled", True)),
                "mount": {
                    "parent_frame": str(mount_raw.get("parent_frame") or payload.get("base_frame") or "base_link"),
                    "xyz_m": self._as_float_vec(mount_raw.get("xyz_m", [0.0, 0.0, 0.0]), name=f"{sensor_id}.mount.xyz_m", length=3),
                    "rpy_deg": self._as_float_vec(mount_raw.get("rpy_deg", [0.0, 0.0, 0.0]), name=f"{sensor_id}.mount.rpy_deg", length=3),
                },
                "intrinsics": intrinsics,
                "render": self._normalize_camera_rig_render_settings(raw.get("render"), sensor_id=sensor_id, sensor_type=sensor_type),
            }
            if sensor_type == "nir_camera":
                nir_raw = raw.get("nir") if isinstance(raw.get("nir"), Mapping) else {}
                sensor["nir"] = {
                    "wavelength_min_nm": self._as_finite_float(nir_raw.get("wavelength_min_nm", 830.0), name=f"{sensor_id}.nir.wavelength_min_nm"),
                    "wavelength_max_nm": self._as_finite_float(nir_raw.get("wavelength_max_nm", 870.0), name=f"{sensor_id}.nir.wavelength_max_nm"),
                    "active_emitter_radiance": self._as_finite_float(nir_raw.get("active_emitter_radiance", 40.0), name=f"{sensor_id}.nir.active_emitter_radiance"),
                }
            if sensor_type == "polar_camera":
                pol_raw = raw.get("polarization") if isinstance(raw.get("polarization"), Mapping) else {}
                sensor["polarization"] = {
                    "polarizer_angle_deg": self._as_finite_float(pol_raw.get("polarizer_angle_deg", 0.0), name=f"{sensor_id}.polarizer_angle_deg"),
                }
            if sensor_type == "lidar_3d":
                lidar_raw = raw.get("lidar") if isinstance(raw.get("lidar"), Mapping) else {}
                sensor["lidar"] = {
                    "horizontal_samples": int(lidar_raw.get("horizontal_samples", 1024)),
                    "vertical_channels": int(lidar_raw.get("vertical_channels", 32)),
                    "horizontal_fov_deg": self._as_finite_float(lidar_raw.get("horizontal_fov_deg", 360.0), name=f"{sensor_id}.lidar.horizontal_fov_deg"),
                    "vertical_fov_min_deg": self._as_finite_float(lidar_raw.get("vertical_fov_min_deg", -25.0), name=f"{sensor_id}.lidar.vertical_fov_min_deg"),
                    "vertical_fov_max_deg": self._as_finite_float(lidar_raw.get("vertical_fov_max_deg", 15.0), name=f"{sensor_id}.lidar.vertical_fov_max_deg"),
                    "min_range_m": self._as_finite_float(lidar_raw.get("min_range_m", 0.2), name=f"{sensor_id}.lidar.min_range_m"),
                    "max_range_m": self._as_finite_float(lidar_raw.get("max_range_m", 80.0), name=f"{sensor_id}.lidar.max_range_m"),
                    "wavelength_nm": self._as_finite_float(lidar_raw.get("wavelength_nm", 905.0), name=f"{sensor_id}.lidar.wavelength_nm"),
                }
            sensors.append(sensor)
        return {
            "rig_id": normalized_rig_id,
            "label": str(payload.get("label") or normalized_rig_id),
            "robot_model": "ranger_mini_v3",
            "base_frame": str(payload.get("base_frame") or "base_link"),
            "updated_at": _utc_now_iso(),
            "sensors": sensors,
        }

    def _load_camera_rig(self, rig_id: str) -> dict[str, Any]:
        path = self._camera_rig_path(rig_id)
        if path.exists():
            return self._normalize_camera_rig(json.loads(path.read_text(encoding="utf-8")), rig_id=rig_id)
        if rig_id in {"ranger_mini_default", "default"}:
            return self._default_camera_rig("ranger_mini_default")
        raise KeyError(rig_id)

    def _save_camera_rig(self, rig_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        rig = self._normalize_camera_rig(payload, rig_id=rig_id)
        path = self._camera_rig_path(rig["rig_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rig, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return rig

    def _list_camera_rigs(self) -> dict[str, Any]:
        rigs: list[dict[str, Any]] = []
        default = self._load_camera_rig("ranger_mini_default")
        rigs.append({
            "rig_id": default["rig_id"],
            "label": default.get("label", default["rig_id"]),
            "robot_model": default.get("robot_model", "ranger_mini_v3"),
            "sensor_count": len(default.get("sensors") or []),
            "updated_at": default.get("updated_at"),
            "is_default": True,
        })
        root = self._camera_rigs_dir()
        if root.exists():
            for path in sorted(root.glob("*.json")):
                rig_id = path.stem
                if rig_id == "ranger_mini_default":
                    continue
                try:
                    rig = self._load_camera_rig(rig_id)
                except Exception:
                    continue
                rigs.append({
                    "rig_id": rig["rig_id"],
                    "label": rig.get("label", rig["rig_id"]),
                    "robot_model": rig.get("robot_model", "ranger_mini_v3"),
                    "sensor_count": len(rig.get("sensors") or []),
                    "updated_at": rig.get("updated_at"),
                    "is_default": False,
                })
        return {"default_rig_id": "ranger_mini_default", "rigs": rigs}

    def _bounds_for_flat_vertices(self, vertices: Sequence[float]) -> dict[str, Any]:
        pts = np.asarray(vertices, dtype=np.float32).reshape(-1, 3)
        mn = pts.min(axis=0)
        mx = pts.max(axis=0)
        return {
            "min": mn.astype(float).tolist(),
            "max": mx.astype(float).tolist(),
            "size": (mx - mn).astype(float).tolist(),
            "center": ((mn + mx) * 0.5).astype(float).tolist(),
        }

    def _camera_rig_proxy_mesh(self) -> dict[str, Any]:
        vertices: list[float] = []
        indices: list[int] = []

        def add_box(cx: float, cy: float, cz: float, sx: float, sy: float, sz: float) -> None:
            base = len(vertices) // 3
            x0, x1 = cx - sx / 2, cx + sx / 2
            y0, y1 = cy - sy / 2, cy + sy / 2
            z0, z1 = cz - sz / 2, cz + sz / 2
            vertices.extend([
                x0, y0, z0, x1, y0, z0, x1, y1, z0, x0, y1, z0,
                x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y1, z1,
            ])
            indices.extend([
                base + 0, base + 1, base + 2, base + 0, base + 2, base + 3,
                base + 4, base + 6, base + 5, base + 4, base + 7, base + 6,
                base + 0, base + 4, base + 5, base + 0, base + 5, base + 1,
                base + 1, base + 5, base + 6, base + 1, base + 6, base + 2,
                base + 2, base + 6, base + 7, base + 2, base + 7, base + 3,
                base + 3, base + 7, base + 4, base + 3, base + 4, base + 0,
            ])

        add_box(0.0, 0.0, 0.28, 0.62, 0.86, 0.20)
        add_box(0.0, 0.10, 0.48, 0.44, 0.42, 0.16)
        add_box(0.0, 0.00, 0.70, 0.14, 0.14, 0.42)
        for x in (-0.36, 0.36):
            for y in (-0.30, 0.30):
                add_box(x, y, 0.18, 0.12, 0.20, 0.26)
        return {
            "robot_model": "ranger_mini_v3",
            "source": "fallback_proxy",
            "status": "fallback_proxy",
            "vertices": vertices,
            "indices": indices,
            "bounds": self._bounds_for_flat_vertices(vertices),
        }

    def _ranger_mini_mesh_for_camera_rig(self) -> dict[str, Any]:
        usd_ref = "assets/robots/ranger_mini_v3/ranger_mini_v3.usda"
        usd_path = self.repo_root / usd_ref
        if usd_path.exists():
            try:
                mesh = extract_prim_mesh_for_editor(
                    usd_path,
                    "/RangerMini",
                    max_triangles=12000,
                    max_mesh_prims=160,
                )
                if mesh and mesh.get("vertices") and mesh.get("indices"):
                    vertices = list(mesh["vertices"])
                    return {
                        "robot_model": "ranger_mini_v3",
                        "source": usd_ref,
                        "status": "ready",
                        "vertices": vertices,
                        "indices": list(mesh["indices"]),
                        "bounds": self._bounds_for_flat_vertices(vertices),
                        "center_offset": mesh.get("center_offset"),
                        "vertex_count": mesh.get("vertex_count"),
                        "triangle_count": mesh.get("triangle_count"),
                    }
            except Exception as exc:
                proxy = self._camera_rig_proxy_mesh()
                proxy["error"] = str(exc)
                return proxy
        return self._camera_rig_proxy_mesh()

    def _push_debug_event(self, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Append a real-time debug event visible in the daemon UI toast feed."""
        with self._condition:
            self._debug_event_counter += 1
            self._debug_events.append({
                "id": self._debug_event_counter,
                "kind": kind,
                "message": message,
                "data": data or {},
                "ts": _utc_now_iso(),
            })
            self._condition.notify_all()

    def _load_scene_render_options(self, scene_id: str | None) -> dict[str, Any]:
        if not scene_id:
            return {"modalities": ["rgb", "depth"], "spp": 64, "width": 1280, "height": 720, "upscale": "none"}
        path = self._render_options_path(scene_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"modalities": ["rgb", "depth"], "spp": 64, "width": 1280, "height": 720, "upscale": "none"}

    def _parse_iso_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).astimezone(timezone.utc)
        except Exception:
            return None

    def _seconds_between(self, start: str | None, end: str | None) -> float | None:
        start_dt = self._parse_iso_timestamp(start)
        end_dt = self._parse_iso_timestamp(end)
        if start_dt is None or end_dt is None:
            return None
        return max(0.0, (end_dt - start_dt).total_seconds())

    def _percentile(self, values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(float(value) for value in values)
        index = max(0, min(len(ordered) - 1, int(math.ceil(percentile * len(ordered))) - 1))
        return ordered[index]

    def _classify_windows_path_mode(self, raw_path: str | None) -> str:
        path_str = str(raw_path or "").strip()
        if not path_str:
            return "unknown"
        if path_str.startswith("\\\\"):
            return "unc"
        if len(path_str) > 1 and path_str[1] == ":":
            normalized = path_str.replace("\\", "/").lower()
            if "/workspace/jinnyeong/project/robomituba/" in normalized:
                return "mapped_drive"
            return "local_mirror"
        return "unknown"

    def _classify_error_kind(self, message: str | None, *, windows_path_mode: str = "unknown") -> str:
        raw = str(message or "").lower()
        if not raw:
            return "unknown"
        if "shape_map" in raw:
            return "shape_map_missing"
        if "session/open" in raw or "session open" in raw:
            return "session_open_failed"
        if "usd" in raw and "open" in raw:
            return "usd_open_failed"
        if windows_path_mode == "unc" and any(token in raw for token in ("texture", "stream", "dome", "hdri")):
            return "unc_texture_risk"
        return "unknown"

    def _scene_telemetry_context(self, scene_id: str | None) -> dict[str, Any]:
        if not scene_id:
            return {
                "scene_id": None,
                "usd_stage_path": None,
                "stage_path_local": None,
                "windows_path_mode": "unknown",
                "render_ready": None,
                "shape_map_exists": None,
                "size_tier": None,
                "asset_file_count": None,
                "texture_cache_status": None,
                "texture_cache_root": None,
                "texture_cache_hit": None,
            }
        catalog = {item["scene_id"]: item for item in self._isaac_scene_catalog_records()}
        scene = catalog.get(scene_id) or {}
        usd_stage_path = _maybe_str(scene.get("usd_stage_path"))
        return {
            "scene_id": scene_id,
            "usd_stage_path": usd_stage_path,
            "stage_path_local": _maybe_str(scene.get("stage_path_local")),
            "windows_path_mode": self._classify_windows_path_mode(usd_stage_path),
            "render_ready": scene.get("render_ready"),
            "shape_map_exists": scene.get("shape_map_exists"),
            "size_tier": scene.get("size_tier"),
            "asset_file_count": scene.get("asset_file_count"),
            "texture_cache_status": scene.get("texture_cache_status"),
            "texture_cache_root": scene.get("texture_cache_root"),
            "texture_cache_hit": scene.get("texture_cache_hit"),
        }

    def _append_telemetry_row(self, row: Mapping[str, Any]) -> None:
        path = self._isaac_command_telemetry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        self._telemetry_cache["mtime_ns"] = None

    def _record_isaac_command_telemetry(self, command: _IsaacRemoteCommand, *, event_type: str) -> None:
        scene_ctx = self._scene_telemetry_context(command.scene_id)
        timestamp = command.updated_at or command.completed_at or command.dispatched_at or command.created_at or _utc_now_iso()
        terminal_ts = command.completed_at if command.status in {"succeeded", "failed"} else None
        elapsed_s = self._seconds_between(command.created_at, terminal_ts or timestamp)
        progress_message = command.error or command.progress_message
        row = {
            "kind": "isaac_command",
            "event_type": event_type,
            "timestamp": timestamp,
            "command_id": command.command_id,
            "scene_id": command.scene_id,
            "command_type": command.command_type,
            "status": command.status,
            "progress_stage": command.progress_stage,
            "progress_message": progress_message,
            "progress_origin": command.progress_origin,
            "progress_counts": dict(command.progress_counts or {}),
            "elapsed_s": elapsed_s,
            "windows_path_mode": scene_ctx["windows_path_mode"],
            "usd_stage_path": scene_ctx["usd_stage_path"],
            "stage_path_local": scene_ctx["stage_path_local"],
            "render_ready": scene_ctx["render_ready"],
            "shape_map_exists": scene_ctx["shape_map_exists"],
            "size_tier": scene_ctx["size_tier"],
            "asset_file_count": scene_ctx["asset_file_count"],
            "texture_cache_status": scene_ctx["texture_cache_status"],
            "texture_cache_root": scene_ctx["texture_cache_root"],
            "texture_cache_hit": scene_ctx["texture_cache_hit"],
            "error_kind": self._classify_error_kind(progress_message, windows_path_mode=scene_ctx["windows_path_mode"]) if command.status == "failed" else None,
        }
        self._append_telemetry_row(row)

    def _record_render_job_telemetry(self, job: _QueuedJob, *, event_type: str) -> None:
        # Keep render telemetry lightweight. Calling _scene_telemetry_context() here
        # walks the scene/catalog/bundle cache, and complete/progress events arrive
        # on the worker stdout reader thread. A heavy scan there delays all worker
        # terminal events and makes fast renders look like multi-minute jobs.
        scene_ctx = {
            "windows_path_mode": "unknown",
            "usd_stage_path": None,
            "stage_path_local": None,
            "render_ready": None,
            "shape_map_exists": None,
            "size_tier": None,
            "asset_file_count": None,
        }
        run_started_at = job.status.worker_started_at or job.status.started_at
        timestamp = job.status.finished_at or run_started_at or job.status.submitted_at or _utc_now_iso()
        timing_summary = job.status.extras.get("render_timing_summary") if isinstance(job.status.extras.get("render_timing_summary"), Mapping) else {}
        row = {
            "kind": "render_job",
            "event_type": event_type,
            "timestamp": timestamp,
            "job_id": job.render_request.job_id,
            "frame_id": job.render_request.frame_id,
            "scene_id": job.render_request.scene_state.scene_id,
            "command_type": "render_job",
            "status": job.status.status,
            "progress_stage": job.status.progress_stage,
            "progress_message": job.status.error or job.status.progress_stage,
            "progress_origin": "daemon_render",
            "progress_counts": dict(job.status.extras.get("progress_context", {}) or {}) if isinstance(job.status.extras.get("progress_context"), Mapping) else {},
            "elapsed_s": self._seconds_between(run_started_at or job.status.submitted_at, timestamp),
            "sync_mode": str(job.status.extras.get("sync_mode") or "unknown"),
            "sync_policy": str(job.status.extras.get("sync_policy") or "default"),
            "windows_path_mode": scene_ctx["windows_path_mode"],
            "usd_stage_path": scene_ctx["usd_stage_path"],
            "stage_path_local": scene_ctx["stage_path_local"],
            "render_ready": scene_ctx["render_ready"],
            "shape_map_exists": scene_ctx["shape_map_exists"],
            "size_tier": scene_ctx["size_tier"],
            "asset_file_count": scene_ctx["asset_file_count"],
            "render_pass_count": timing_summary.get("pass_count"),
            "render_scene_cache_hits": timing_summary.get("scene_cache_hits"),
            "render_scene_cache_misses": timing_summary.get("scene_cache_misses"),
            "render_scene_cache_hit_ratio": timing_summary.get("scene_cache_hit_ratio"),
            "render_load_scene_total_s": timing_summary.get("load_scene_total_s"),
            "render_total_s": timing_summary.get("total_s"),
            "error_kind": self._classify_error_kind(job.status.error, windows_path_mode=scene_ctx["windows_path_mode"]) if job.status.status == "failed" else None,
        }
        self._append_telemetry_row(row)

    def _load_telemetry_rows(self, *, limit: int = 500) -> list[dict[str, Any]]:
        path = self._isaac_command_telemetry_path()
        if not path.exists():
            return []
        try:
            stat = path.stat()
        except OSError:
            return []
        cache_path = self._telemetry_cache.get("path")
        cache_mtime = self._telemetry_cache.get("mtime_ns")
        if cache_path == str(path) and cache_mtime == stat.st_mtime_ns:
            rows = self._telemetry_cache.get("rows", [])
            return rows[-limit:] if limit else list(rows)
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        except OSError:
            return []
        self._telemetry_cache = {"path": str(path), "mtime_ns": stat.st_mtime_ns, "rows": rows}
        return rows[-limit:] if limit else rows

    def _telemetry_recent_rows(self, *, limit: int = 25) -> list[dict[str, Any]]:
        rows = self._load_telemetry_rows(limit=max(limit * 4, 100))
        rows.sort(key=lambda item: _safe_sort_ts(_maybe_str(item.get("timestamp"))), reverse=True)
        return rows[:limit]

    def _telemetry_recent_rows_for_command(self, command_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._load_telemetry_rows(limit=2000)
            if row.get("kind") == "isaac_command" and str(row.get("command_id") or "") == command_id
        ]
        rows.sort(key=lambda item: _safe_sort_ts(_maybe_str(item.get("timestamp"))), reverse=True)
        return rows[:limit]

    def _telemetry_stats(self, *, limit: int = 1000) -> dict[str, Any]:
        rows = [row for row in self._load_telemetry_rows(limit=limit) if row.get("kind") == "isaac_command"]
        by_command: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            command_id = _maybe_str(row.get("command_id"))
            if not command_id:
                continue
            by_command.setdefault(command_id, []).append(row)

        stage_buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
        error_counts: dict[str, int] = {}
        path_mode_counts: dict[str, int] = {}

        for command_rows in by_command.values():
            command_rows.sort(key=lambda item: _safe_sort_ts(_maybe_str(item.get("timestamp"))))
            terminal = command_rows[-1]
            terminal_status = _maybe_str(terminal.get("status")) or "running"
            scene_id = _maybe_str(terminal.get("scene_id")) or "scene"
            command_type = _maybe_str(terminal.get("command_type")) or "command"
            path_mode = _maybe_str(terminal.get("windows_path_mode")) or "unknown"
            path_mode_counts[path_mode] = path_mode_counts.get(path_mode, 0) + 1
            error_kind = _maybe_str(terminal.get("error_kind"))
            if error_kind:
                error_counts[error_kind] = error_counts.get(error_kind, 0) + 1
            if terminal_status not in {"succeeded", "failed"}:
                continue

            segment_stage = _maybe_str(command_rows[0].get("progress_stage")) or _maybe_str(command_rows[0].get("status")) or "running"
            segment_start = _maybe_str(command_rows[0].get("timestamp"))
            segment_end = segment_start
            for row in command_rows[1:]:
                row_stage = _maybe_str(row.get("progress_stage")) or _maybe_str(row.get("status")) or "running"
                row_ts = _maybe_str(row.get("timestamp"))
                if row_stage != segment_stage:
                    duration = self._seconds_between(segment_start, row_ts)
                    bucket = stage_buckets.setdefault((scene_id, command_type, segment_stage), {"durations": [], "success_count": 0, "failure_count": 0, "last_seen_at": None})
                    if duration is not None:
                        bucket["durations"].append(duration)
                    if terminal_status == "succeeded":
                        bucket["success_count"] += 1
                    else:
                        bucket["failure_count"] += 1
                    bucket["last_seen_at"] = max(bucket.get("last_seen_at") or "", row_ts or "")
                    segment_stage = row_stage
                    segment_start = row_ts
                segment_end = row_ts

            duration = self._seconds_between(segment_start, segment_end)
            bucket = stage_buckets.setdefault((scene_id, command_type, segment_stage), {"durations": [], "success_count": 0, "failure_count": 0, "last_seen_at": None})
            if duration is not None:
                bucket["durations"].append(duration)
            if terminal_status == "succeeded":
                bucket["success_count"] += 1
            else:
                bucket["failure_count"] += 1
            bucket["last_seen_at"] = max(bucket.get("last_seen_at") or "", segment_end or "")

        stage_stats: list[dict[str, Any]] = []
        for (scene_id, command_type, progress_stage), bucket in stage_buckets.items():
            durations = [float(value) for value in bucket["durations"] if value is not None]
            stage_stats.append(
                {
                    "scene_id": scene_id,
                    "command_type": command_type,
                    "progress_stage": progress_stage,
                    "count": len(durations),
                    "success_count": int(bucket["success_count"]),
                    "failure_count": int(bucket["failure_count"]),
                    "median_duration_s": round(self._percentile(durations, 0.5) or 0.0, 2) if durations else None,
                    "p90_duration_s": round(self._percentile(durations, 0.9) or 0.0, 2) if durations else None,
                    "last_seen_at": bucket["last_seen_at"],
                }
            )
        stage_stats.sort(key=lambda item: (item["scene_id"], item["command_type"], item["progress_stage"]))
        error_summary = [{"error_kind": key, "count": value} for key, value in sorted(error_counts.items(), key=lambda item: (-item[1], item[0]))]
        path_mode_summary = [{"windows_path_mode": key, "count": value} for key, value in sorted(path_mode_counts.items(), key=lambda item: (-item[1], item[0]))]
        return {
            "stage_stats": stage_stats,
            "error_summary": error_summary,
            "path_mode_summary": path_mode_summary,
        }

    def _telemetry_baseline_for_command(self, command: _IsaacRemoteCommand) -> dict[str, Any] | None:
        scene_id = command.scene_id or "scene"
        progress_stage = command.progress_stage or command.status or "running"
        for item in self._telemetry_stats(limit=1200)["stage_stats"]:
            if item["scene_id"] == scene_id and item["command_type"] == command.command_type and item["progress_stage"] == progress_stage:
                return {
                    "median_duration_s": item["median_duration_s"],
                    "p90_duration_s": item["p90_duration_s"],
                    "sample_count": item["count"],
                }
        return None

    def _expected_next_stage_for_command(self, command: _IsaacRemoteCommand) -> dict[str, str] | None:
        stage = command.progress_stage or command.status or ""
        command_stages: dict[str, list[tuple[str, dict[str, str]]]] = {
            "load_scene": [
                ("picked_up", {"en": "Resolve scene path", "kr": "장면 경로 해석"}),
                ("resolving_scene", {"en": "Open stage", "kr": "stage 열기"}),
                ("opening_stage", {"en": "Load assets", "kr": "에셋 로딩"}),
                ("assets_loading", {"en": "Prepare streaming", "kr": "streaming 준비"}),
                ("assets_loaded", {"en": "Prepare Hydra", "kr": "Hydra 준비"}),
                ("streaming_scene", {"en": "Scene ready", "kr": "scene 준비 완료"}),
            ],
            "connect_session": [
                ("picked_up", {"en": "Collect scene refs", "kr": "scene ref 수집"}),
                ("collecting_scene_refs", {"en": "Open daemon session", "kr": "daemon session 열기"}),
                ("opening_session", {"en": "Session ready", "kr": "세션 준비 완료"}),
            ],
            "sync_session": [
                ("picked_up", {"en": "Capture stage state", "kr": "stage 상태 수집"}),
                ("capturing_stage_state", {"en": "Serialize patch", "kr": "patch 직렬화"}),
                ("serializing_patch", {"en": "Upload patch", "kr": "patch 업로드"}),
                ("uploading_patch", {"en": "Sync complete", "kr": "동기화 완료"}),
            ],
            "render_current_view": [
                ("picked_up", {"en": "Ensure active session", "kr": "active session 확인"}),
                ("ensuring_session", {"en": "Capture viewport", "kr": "뷰포트 수집"}),
                ("capturing_view", {"en": "Submit capture request", "kr": "capture 요청 제출"}),
                ("sending_capture_request", {"en": "Ambient branch", "kr": "ambient 렌더 시작"}),
                ("ambient", {"en": "Stage scene XML", "kr": "씬 XML 준비"}),
                ("staging_scene", {"en": "Load scene to GPU", "kr": "GPU 메모리 로딩"}),
                ("loading_scene", {"en": "Ray tracing", "kr": "경로 추적 중"}),
                ("rendering", {"en": "Save EXR outputs", "kr": "EXR 출력 저장"}),
                ("saving_output", {"en": "Active / polar branch", "kr": "active/polar branch"}),
                ("active", {"en": "Polar branch", "kr": "polar branch"}),
                ("polar", {"en": "Write manifest", "kr": "manifest 기록"}),
                ("writing_manifest", {"en": "Render complete", "kr": "렌더 완료"}),
            ],
            "render_sensor": [
                ("picked_up", {"en": "Ensure active session", "kr": "active session 확인"}),
                ("ensuring_session", {"en": "Resolve sensor", "kr": "센서 확인"}),
                ("resolving_sensor", {"en": "Submit capture request", "kr": "capture 요청 제출"}),
                ("sending_capture_request", {"en": "Ambient branch", "kr": "ambient 렌더 시작"}),
                ("ambient", {"en": "Stage scene XML", "kr": "씬 XML 준비"}),
                ("staging_scene", {"en": "Load scene to GPU", "kr": "GPU 메모리 로딩"}),
                ("loading_scene", {"en": "Ray tracing", "kr": "경로 추적 중"}),
                ("rendering", {"en": "Save EXR outputs", "kr": "EXR 출력 저장"}),
                ("saving_output", {"en": "Active / polar branch", "kr": "active/polar branch"}),
                ("active", {"en": "Polar branch", "kr": "polar branch"}),
                ("polar", {"en": "Write manifest", "kr": "manifest 기록"}),
                ("writing_manifest", {"en": "Render complete", "kr": "렌더 완료"}),
            ],
        }
        stages = command_stages.get(command.command_type)
        if not stages:
            return None
        for index, (stage_name, _label) in enumerate(stages):
            if stage_name == stage and index + 1 < len(stages):
                return stages[index + 1][1]
        return None

    def _current_stage_elapsed_for_command(self, command: _IsaacRemoteCommand) -> float | None:
        current_stage = command.progress_stage or command.status or ""
        if not current_stage:
            return None
        rows = self._telemetry_recent_rows_for_command(command.command_id, limit=40)
        if not rows:
            return self._seconds_between(command.created_at, command.updated_at or _utc_now_iso())
        rows_chrono = list(reversed(rows))
        stage_start_ts = command.created_at
        for row in rows_chrono:
            row_stage = _maybe_str(row.get("progress_stage")) or _maybe_str(row.get("status")) or ""
            row_ts = _maybe_str(row.get("timestamp"))
            if row_stage == current_stage and row_ts:
                stage_start_ts = row_ts
                break
        return self._seconds_between(stage_start_ts, command.updated_at or _utc_now_iso())

    def _progress_details_for_command(self, command: _IsaacRemoteCommand) -> dict[str, Any] | None:
        recent_rows = self._telemetry_recent_rows_for_command(command.command_id, limit=8)
        if not recent_rows:
            return None
        baseline = self._telemetry_baseline_for_command(command)
        current_stage_elapsed_s = self._current_stage_elapsed_for_command(command)
        relative_speed = None
        if baseline and current_stage_elapsed_s is not None:
            median_s = baseline.get("median_duration_s")
            p90_s = baseline.get("p90_duration_s")
            if isinstance(p90_s, (int, float)) and p90_s > 0 and current_stage_elapsed_s > p90_s:
                relative_speed = "slower_than_p90"
            elif isinstance(median_s, (int, float)) and median_s > 0 and current_stage_elapsed_s > (median_s * 2.0):
                relative_speed = "slower_than_median"
            else:
                relative_speed = "within_range"
        recent_events = []
        for row in recent_rows:
            recent_events.append(
                {
                    "timestamp": row.get("timestamp"),
                    "event_type": row.get("event_type"),
                    "progress_stage": row.get("progress_stage") or row.get("status"),
                    "progress_message": row.get("progress_message"),
                    "progress_origin": row.get("progress_origin"),
                }
            )
        return {
            "current_stage_elapsed_s": round(current_stage_elapsed_s, 2) if current_stage_elapsed_s is not None else None,
            "expected_next_stage": self._expected_next_stage_for_command(command),
            "relative_speed": relative_speed,
            "recent_events": recent_events,
        }

    def _telemetry_hint_for_command(self, command: _IsaacRemoteCommand) -> dict[str, str] | None:
        baseline = self._telemetry_baseline_for_command(command)
        scene_ctx = self._scene_telemetry_context(command.scene_id)
        elapsed_s = self._seconds_between(command.created_at, command.updated_at or _utc_now_iso()) or 0.0
        windows_path_mode = scene_ctx["windows_path_mode"]
        hint_en = ""
        hint_kr = ""
        if baseline and baseline.get("sample_count"):
            median_s = baseline.get("median_duration_s")
            p90_s = baseline.get("p90_duration_s")
            sample_count = baseline.get("sample_count")
            if median_s is not None:
                hint_en = f"Recent median for this stage: {median_s:.0f}s"
                hint_kr = f"최근 동일 stage 중앙값: {median_s:.0f}초"
            if p90_s is not None and p90_s > 0:
                range_en = f"Usually finishes within ~{p90_s:.0f}s (p90, {sample_count} samples)."
                range_kr = f"최근 {sample_count}회 기준 보통 ~{p90_s:.0f}초 안에 끝났습니다."
                hint_en = f"{hint_en} · {range_en}" if hint_en else range_en
                hint_kr = f"{hint_kr} · {range_kr}" if hint_kr else range_kr
            if median_s and elapsed_s > max(median_s * 2.0, baseline.get("p90_duration_s") or 0.0):
                slow_en = "This run is taking longer than the recent baseline."
                slow_kr = "이번 실행은 최근 기준보다 오래 걸리고 있습니다."
                hint_en = f"{hint_en} · {slow_en}" if hint_en else slow_en
                hint_kr = f"{hint_kr} · {slow_kr}" if hint_kr else slow_kr
        if windows_path_mode == "unc" and (command.command_type == "load_scene" or (command.progress_stage or "") in {"opening_stage", "streaming_scene", "assets_loading"}):
            unc_en = "UNC network path detected; texture streaming may be slow. Mapped drive or local mirror is recommended."
            unc_kr = "UNC 네트워크 경로가 감지되었습니다. 텍스처 streaming이 느릴 수 있어 mapped drive나 local mirror를 권장합니다."
            hint_en = f"{hint_en} · {unc_en}" if hint_en else unc_en
            hint_kr = f"{hint_kr} · {unc_kr}" if hint_kr else unc_kr
        if not hint_en and scene_ctx.get("size_tier") in {"heavy", "huge"}:
            size_en = f"{scene_ctx.get('size_tier', 'heavy').title()} scene with {scene_ctx.get('asset_file_count') or 0} asset files; cold loads may take a while."
            size_kr = f"{scene_ctx.get('asset_file_count') or 0}개 에셋 파일이 있는 {scene_ctx.get('size_tier') or 'heavy'} 장면으로, 처음 로딩이 오래 걸릴 수 있습니다."
            hint_en = size_en
            hint_kr = size_kr
        if not hint_en:
            return None
        return {"en": hint_en, "kr": hint_kr}

    def _next_isaac_command_id(self) -> str:
        return f"isaac-cmd-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"

    def _queue_isaac_command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        command_type = _maybe_str(payload.get("command_type"))
        if not command_type:
            raise ValueError("command_type is required.")
        scene_id = _maybe_str(payload.get("scene_id"))
        command_payload = dict(payload.get("payload") or {})
        # Inject saved render options into render commands when not explicitly set
        if command_type in {"render_current_view", "render_sensor"} and "modalities" not in command_payload:
            saved = self._load_scene_render_options(scene_id)
            command_payload["modalities"] = saved.get("modalities", ["rgb", "depth"])
            if "spp" not in command_payload:
                command_payload["spp"] = saved.get("spp", 64)
            # 해상도 및 업스케일 주입
            rs = command_payload.setdefault("render_settings", {})
            if "width" not in rs:
                rs["width"] = saved.get("width", 1280)
            if "height" not in rs:
                rs["height"] = saved.get("height", 720)
            if "upscale" not in rs:
                rs["upscale"] = saved.get("upscale", "none")
        if command_type == "render_sensor" and not command_payload.get("sensor_id"):
            raise ValueError("render_sensor command requires payload.sensor_id.")
        command_id = self._next_isaac_command_id()
        command = _IsaacRemoteCommand(
            command_id=command_id,
            command_type=command_type,
            scene_id=scene_id,
            payload=command_payload,
            status="queued",
            created_at=_utc_now_iso(),
            updated_at=_utc_now_iso(),
        )
        with self._condition:
            self._isaac_commands[command_id] = command
            self._isaac_commands_pending.append(command_id)
            self._condition.notify_all()
        self._record_isaac_command_telemetry(command, event_type="queued")
        return self._isaac_command_payload(command)

    def _start_isaac_command(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        command_type = _maybe_str(payload.get("command_type"))
        if not command_type:
            raise ValueError("command_type is required.")
        scene_id = _maybe_str(payload.get("scene_id"))
        command_payload = dict(payload.get("payload") or {})
        now = _utc_now_iso()
        command = _IsaacRemoteCommand(
            command_id=self._next_isaac_command_id(),
            command_type=command_type,
            scene_id=scene_id,
            payload=command_payload,
            status="running",
            created_at=now,
            dispatched_at=now,
            updated_at=now,
        )
        with self._condition:
            self._isaac_commands[command.command_id] = command
            self._condition.notify_all()
        self._record_isaac_command_telemetry(command, event_type="running")
        return self._isaac_command_payload(command)

    def _isaac_command_payload(self, command: _IsaacRemoteCommand) -> dict[str, Any]:
        payload = {
            "command_id": command.command_id,
            "command_type": command.command_type,
            "scene_id": command.scene_id,
            "payload": command.payload,
            "status": command.status,
            "created_at": command.created_at,
            "dispatched_at": command.dispatched_at,
            "completed_at": command.completed_at,
            "updated_at": command.updated_at,
            "progress_stage": command.progress_stage,
            "progress_message": command.progress_message,
            "progress_origin": command.progress_origin,
            "progress_counts": dict(command.progress_counts or {}),
            "result": command.result,
            "error": command.error,
        }
        baseline = self._telemetry_baseline_for_command(command)
        hint = self._telemetry_hint_for_command(command) if command.status in {"queued", "dispatched", "running"} else None
        if baseline is not None:
            payload["telemetry_baseline"] = baseline
        if hint is not None:
            payload["telemetry_hint"] = hint
        progress_details = self._progress_details_for_command(command)
        if progress_details is not None:
            payload["progress_details"] = progress_details
        return payload

    def _list_isaac_commands(self, *, limit: int = 20) -> list[dict[str, Any]]:
        commands = list(self._isaac_commands.values())
        commands.sort(key=lambda item: _safe_sort_ts(item.created_at), reverse=False)
        commands.reverse()
        return [self._isaac_command_payload(item) for item in commands[:limit]]

    def _recent_isaac_render_commands(self, *, limit: int = 20) -> list[dict[str, Any]]:
        render_command_types = {"render_current_view", "render_sensor"}
        commands = [
            command
            for command in self._list_isaac_commands(limit=max(limit * 4, 20))
            if str(command.get("command_type") or "") in render_command_types
        ]
        return commands[:limit]

    def _next_isaac_command(self) -> dict[str, Any] | None:
        with self._condition:
            while self._isaac_commands_pending:
                command_id = self._isaac_commands_pending.popleft()
                command = self._isaac_commands.get(command_id)
                if command is None or command.status != "queued":
                    continue
                command.status = "dispatched"
                command.dispatched_at = _utc_now_iso()
                command.updated_at = command.dispatched_at
                self._record_isaac_command_telemetry(command, event_type="dispatched")
                return self._isaac_command_payload(command)
        return None

    def _update_isaac_command_progress(self, command_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._condition:
            command = self._isaac_commands.get(command_id)
            if command is None:
                raise KeyError(command_id)
            status = _maybe_str(payload.get("status")) or command.status
            if status not in {"queued", "dispatched", "running", "succeeded", "failed"}:
                raise ValueError("status must be one of 'queued', 'dispatched', 'running', 'succeeded', or 'failed'.")
            command.status = status
            command.progress_stage = _maybe_str(payload.get("progress_stage")) or command.progress_stage
            progress_message = _maybe_str(payload.get("progress_message")) or command.progress_message
            if status == "failed":
                progress_message = self._normalize_command_error(progress_message, scene_id=command.scene_id)
            command.progress_message = progress_message
            command.progress_origin = _maybe_str(payload.get("progress_origin")) or command.progress_origin
            progress_counts = payload.get("progress_counts")
            if isinstance(progress_counts, Mapping):
                loaded = progress_counts.get("loaded")
                total = progress_counts.get("total")
                normalized: dict[str, int] = {}
                if isinstance(loaded, (int, float)):
                    normalized["loaded"] = int(loaded)
                if isinstance(total, (int, float)):
                    normalized["total"] = int(total)
                command.progress_counts = normalized or None
            command.updated_at = _utc_now_iso()
            if status in {"succeeded", "failed"} and command.completed_at is None:
                command.completed_at = command.updated_at
            self._condition.notify_all()
            self._record_isaac_command_telemetry(command, event_type="progress")
            return self._isaac_command_payload(command)

    def _complete_isaac_command(self, command_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._condition:
            command = self._isaac_commands.get(command_id)
            if command is None:
                raise KeyError(command_id)
            status = _maybe_str(payload.get("status")) or "succeeded"
            if status not in {"succeeded", "failed"}:
                raise ValueError("status must be either 'succeeded' or 'failed'.")
            command.status = status
            command.completed_at = _utc_now_iso()
            command.updated_at = command.completed_at
            if status == "succeeded":
                command.progress_stage = command.progress_stage or "ready"
                command.progress_message = command.progress_message or "Completed"
            else:
                command.progress_stage = "failed"
            command.progress_message = self._normalize_command_error(
                _maybe_str(payload.get("error")) or command.progress_message or "Failed",
                scene_id=command.scene_id,
            )
            result = payload.get("result")
            command.result = dict(result) if isinstance(result, Mapping) else None
            command.error = self._normalize_command_error(_maybe_str(payload.get("error")), scene_id=command.scene_id)
            if status == "succeeded" and command.command_type == "sync_opticalnav_stage":
                self._mark_opticalnav_isaac_stage_synced(command)
            self._record_isaac_command_telemetry(command, event_type="complete")
            return self._isaac_command_payload(command)

    def _mark_opticalnav_isaac_stage_synced(self, command: _IsaacRemoteCommand) -> None:
        command_payload = dict(command.payload or {})
        project_id = _maybe_str(command_payload.get("project_id"))
        scene_id = _maybe_str(command_payload.get("scene_id")) or command.scene_id
        if not project_id or not scene_id:
            return
        try:
            from navigation_dataset.scene_annotations import read_scene_annotation, write_scene_annotation

            project_dir = self._opticalnav_project_dir(project_id)
            annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
            annotation = read_scene_annotation(annotation_path)
            sync = dict(annotation.metadata.get("sync", {}))
            sync.update({
                "isaac_stage": "synced",
                "isaac_stage_synced_at": _utc_now_iso(),
                "isaac_stage_command_id": command.command_id,
                "message": "Dataset, render-scene overlay, and Isaac stage are synced.",
            })
            if isinstance(command.result, Mapping):
                sync["isaac_stage_result"] = dict(command.result)
            annotation.metadata = {**dict(annotation.metadata or {}), "sync": sync}
            write_scene_annotation(annotation_path, annotation)
        except Exception:
            return

    def _load_registered_isaac_scenes(self) -> dict[str, dict[str, Any]]:
        path = self._isaac_scene_catalog_path()
        if not path.exists():
            return {}
        try:
            payload = _read_json(path)
        except Exception:
            return {}
        scenes = payload.get("scenes", {})
        if not isinstance(scenes, Mapping):
            return {}
        return {
            str(scene_id): dict(scene_payload)
            for scene_id, scene_payload in scenes.items()
            if isinstance(scene_payload, Mapping)
        }

    def _write_registered_isaac_scenes(self, scenes: Mapping[str, Any]) -> Path:
        path = self._isaac_scene_catalog_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _utc_now_iso(),
            "scenes": scenes,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _cancel_stale_jobs_at_startup(self) -> None:
        """Mark any running/queued jobs from the previous session as failed.

        When the daemon restarts, in-flight jobs have no live workers — they
        will never complete on their own.  Rewriting their status to 'failed'
        prevents the UI from showing them as perpetually running/pending.

        Skippable via ``ROBOMITUBA_SKIP_STALE_JOB_SCAN=1`` — on a slow network
        mount with thousands of jobs this glob delays the daemon's listen.
        """
        if os.environ.get("ROBOMITUBA_SKIP_STALE_JOB_SCAN", "").strip().lower() in ("1", "true", "yes", "on"):
            print("[daemon] Skipping startup stale-job scan (ROBOMITUBA_SKIP_STALE_JOB_SCAN).", flush=True)
            return
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            return
        stale_statuses = ("running", "queued", "pending")
        count = 0
        for status_path in root.glob("*/job_status.json"):
            try:
                status = read_render_job_status(status_path)
            except Exception:
                continue
            if status.status not in stale_statuses:
                continue
            status.status = "failed"
            status.progress_stage = "failed"
            status.error = (status.error or "") + " [abandoned: daemon restarted]"
            try:
                write_render_job_status(status_path, status)
                count += 1
            except Exception:
                pass
        if count:
            print(f"[daemon] Marked {count} stale job(s) as failed on startup.", flush=True)
        self._invalidate_job_status_cache()

    def start(self) -> None:
        if self._server is not None:
            return

        self._cancel_stale_jobs_at_startup()

        controller = self

        class Handler(BaseHTTPRequestHandler):
            daemon = controller

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                if os.environ.get("ROBOMITUBA_DAEMON_DEBUG_LOG") not in {"1", "true", "yes", "on"}:
                    return
                message = format % args
                print(f"[http] {self.address_string()} {message}", file=sys.stderr, flush=True)

            def _log_exception(self, method: str) -> None:
                print(f"[daemon] unhandled {method} {self.path}", file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)

            def do_GET(self) -> None:  # noqa: N802
                try:
                    parsed = urlparse(self.path)
                    if (
                        parsed.path == "/isaac/session/camera_ws"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_camera_websocket(self)
                        return
                    if (
                        parsed.path == "/api/ws/current-scene"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_scene_telemetry_websocket(self, parsed)
                        return
                    if (
                        parsed.path == "/api/ws/job-status"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_job_status_websocket(self)
                        return
                    if (
                        parsed.path == "/api/ws/graph-build-progress"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_graph_build_progress_websocket(self, parsed)
                        return
                    if (
                        parsed.path == "/api/ws/opticalnav-sync-progress"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_opticalnav_sync_progress_websocket(self, parsed)
                        return
                    if (
                        parsed.path == "/api/ws/opticalnav-export"
                        and self.headers.get("Upgrade", "").lower() == "websocket"
                    ):
                        self.daemon._handle_export_job_websocket(self, parsed)
                        return
                    self.daemon._handle_get(self)
                except Exception:
                    self._log_exception("GET")
                    raise

            def do_HEAD(self) -> None:  # noqa: N802
                try:
                    self.daemon._handle_head(self)
                except Exception:
                    self._log_exception("HEAD")
                    raise

            def do_POST(self) -> None:  # noqa: N802
                try:
                    self.daemon._handle_post(self)
                except Exception:
                    self._log_exception("POST")
                    raise

            def do_PUT(self) -> None:  # noqa: N802
                try:
                    self.daemon._handle_put(self)
                except Exception:
                    self._log_exception("PUT")
                    raise

            def do_DELETE(self) -> None:  # noqa: N802
                try:
                    self.daemon._handle_delete(self)
                except Exception:
                    self._log_exception("DELETE")
                    raise

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])

        self._worker_thread = threading.Thread(target=self._worker_loop, name="robomituba-render-worker", daemon=True)
        self._worker_thread.start()

        self._server_thread = threading.Thread(target=self._server.serve_forever, name="robomituba-render-daemon", daemon=True)
        self._server_thread.start()

    def shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify_all()

        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
            self._worker_thread = None

        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)
            self._server_thread = None

    def wait_forever(self) -> None:
        if self._server_thread is None:
            raise RuntimeError("RenderDaemon.start() must be called before wait_forever().")
        self._server_thread.join()

    def _handle_camera_websocket(self, handler: BaseHTTPRequestHandler) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()

        while not self._shutdown:
            frame = self._read_ws_frame(handler)
            if frame is None:
                break
            opcode, payload = frame
            if opcode == 0x8:
                break
            if opcode == 0x9:
                self._write_ws_frame(handler, payload, opcode=0xA)
                continue
            if opcode != 0x1:
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
                if isinstance(message, Mapping):
                    self._register_isaac_sensors(dict(message))
            except RuntimeError:
                # Camera telemetry is best-effort. If the Isaac session is not
                # active yet, drop the frame instead of creating HTTP 409 noise.
                continue
            except Exception as exc:
                self._push_debug_event("error", f"camera websocket payload ignored: {exc}")

    def _handle_scene_telemetry_websocket(self, handler: BaseHTTPRequestHandler, parsed: Any) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()

        query = parse_qs(parsed.query or "")
        requested_scene_id = _maybe_str((query.get("scene_id") or [None])[0])
        subscriber = _SceneTelemetrySubscriber(
            scene_id=requested_scene_id,
            handler=handler,
            lock=threading.Lock(),
        )
        with self._scene_telemetry_lock:
            self._scene_telemetry_subscribers.add(subscriber)
        try:
            payload = self._scene_telemetry_payload(scene_id=requested_scene_id)
            if payload is not None:
                subscriber.send_json(payload)
            while not self._shutdown:
                frame = self._read_ws_frame(handler)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write_ws_frame(handler, payload, opcode=0xA)
        finally:
            with self._scene_telemetry_lock:
                self._scene_telemetry_subscribers.discard(subscriber)

    def _patch_opticalnav_annotation_sync(self, project_dir: Path, scene_id: str, patch: Mapping[str, Any]) -> bool:
        annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
        if not annotation_path.exists():
            return False
        try:
            raw = json.loads(annotation_path.read_text(encoding="utf-8"))
            sync = dict(raw.get("metadata", {}).get("sync", {}))
            sync.update(dict(patch))
            raw.setdefault("metadata", {})["sync"] = sync
            annotation_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def _run_render_scene_sync_inner(
        self,
        project_dir: Path,
        scene_id: str,
        payload: Mapping[str, Any],
        *,
        sync_job_id: str | None,
        progress_cb: "Callable[[int, int, str, str], None] | None",
    ) -> "tuple[int, dict[str, Any]]":
        """Render-scene sync body. Returns (status_code, response_body) without sending."""
        from navigation_dataset.authoring_map import (
            authoring_map_to_payload as _am_to_payload,
            load_authoring_map,
            save_authoring_map,
        )
        from navigation_dataset.scene_annotations import SceneAnnotation, read_scene_annotation, write_scene_annotation
        from navigation_dataset.scene_sync import write_render_scene_sync

        scene_dir = project_dir / "scenes" / scene_id
        map_path = scene_dir / "authoring_map.json"
        annotation_path = scene_dir / "scene_annotation.json"
        envmap_invalidated: dict[str, Any] | None = None
        # Phase 3 readiness split: render sync used to require a fully compiled
        # scene_annotation.json (which itself required a traversable region) before
        # producing render_scene.xml. That coupled Dataset readiness with Render
        # readiness — a user with no traversable region drawn yet couldn't even
        # render their scene. We now read the annotation when present, and fall
        # back to a minimal one (scene_id only) so XML emit always succeeds.
        # Dataset compile remains as a separate workflow.
        annotation_missing = False
        # Wipe the .staged_mitsuba/ cache up-front: any in-flight render job that
        # already resolved a staged_xml path under the previous render_scene.xml
        # would otherwise keep loading stale envmap / texture refs.
        staged_cleared = self._opticalnav_clear_staged_scene_cache(scene_dir)
        try:
            authoring_map = load_authoring_map(map_path)
            envmap_invalidated = self._opticalnav_invalidate_missing_envmap(
                authoring_map, map_path, scene_dir,
            )
            try:
                annotation = read_scene_annotation(annotation_path)
            except (FileNotFoundError, ValueError, OSError):
                annotation_missing = True
                # Minimal annotation: render only needs scene_id and the
                # coordinate_system default. Hazard / goal / traversable lists
                # stay empty; dataset workflows still flag this separately.
                annotation = SceneAnnotation(scene_id=scene_id)
            result = write_render_scene_sync(
                scene_dir, authoring_map, annotation,
                project_dir=project_dir,
                scene_variant_id=_maybe_str(payload.get("scene_variant_id")),
            )
        except Exception as exc:
            return int(HTTPStatus.BAD_REQUEST), {"error": str(exc)}

        authoring_payload = _am_to_payload(authoring_map)
        render_scene_path = scene_dir / "render_scene.xml"
        render_readiness_path = scene_dir / "render_readiness.json"
        render_scene_ref: str | None = None
        overlay_shape_count = 0
        generation_error: str | None = None
        mesh_extraction_stats: dict[str, int] = {}

        # Total estimate: count overlay objects with USD-backed source_ref.
        total_estimate = 0
        for obj in (result.overlay or {}).get("objects") or []:
            src = obj.get("source_ref") if isinstance(obj, Mapping) else None
            if isinstance(src, str) and "#" in src:
                total_estimate += 1
        if progress_cb is not None:
            progress_cb(0, total_estimate, "preparing", "scene_sync")

        try:
            eg_path = scene_dir / "editor_geometry.json"
            eg_data = _read_json(eg_path) if eg_path.exists() else None
            _shared_stage_cache: dict[str, Any] = {}
            _processed = {"n": 0}

            def _resolve_prim_obj(usd_ref: str, prim_path: str):
                res = self._ensure_prim_obj_cached(
                    project_dir, scene_id, usd_ref, prim_path,
                    stage_cache=_shared_stage_cache,
                )
                _processed["n"] += 1
                if progress_cb is not None and (_processed["n"] % 4 == 0 or _processed["n"] == total_estimate):
                    progress_cb(_processed["n"], max(total_estimate, _processed["n"]), prim_path.rsplit("/", 1)[-1], "mesh_extract")
                return res

            t_mesh_start = time.perf_counter()
            materialization_records: list[dict[str, Any]] = []
            overlay_shape_count = _generate_opticalnav_render_scene_xml(
                authoring_payload,
                result.overlay,
                render_scene_path,
                editor_geometry=eg_data,
                repo_root=self.repo_root,
                mesh_resolver=_resolve_prim_obj,
                mesh_stats=mesh_extraction_stats,
                materialization_records=materialization_records,
            )
            mesh_extraction_stats["extraction_time_ms"] = int((time.perf_counter() - t_mesh_start) * 1000)
            render_scene_ref = render_scene_path.relative_to(self.repo_root).as_posix()
            scene_mesh_cache_dir = self._opticalnav_mesh_cache_dir(project_dir, scene_id)
            mesh_extraction_stats["scene_mesh_cache"] = _stage_xml_obj_filenames_to_scene_mesh_cache(
                render_scene_path,
                scene_mesh_cache_dir=scene_mesh_cache_dir,
                repo_root=self.repo_root,
            )
            preview_mesh_manifest = _build_editor_preview_mesh_manifest(
                render_scene_path,
                scene_mesh_cache_dir=scene_mesh_cache_dir,
                repo_root=self.repo_root,
                materialization_records=materialization_records,
            )
            mesh_extraction_stats["editor_preview_mesh_cache"] = preview_mesh_manifest.get("stats", {})
            try:
                (scene_dir / "editor_preview_mesh_manifest.json").write_text(
                    json.dumps(preview_mesh_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            except Exception as exc:
                mesh_extraction_stats["editor_preview_mesh_manifest_error"] = str(exc)

            # PR1: per-object materialization audit + XML scene index sidecars.
            # Both consume the records collected during XML emit and the freshly written
            # render_scene.xml, so they sit at the tail of the generation block.
            try:
                audit_payload = _build_materialization_audit(
                    scene_id=scene_id,
                    overlay_objects=list(result.overlay.get("objects") or []),
                    materialization_records=materialization_records,
                    mesh_stats=mesh_extraction_stats,
                )
                (scene_dir / "render_scene_materialization.json").write_text(
                    json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            except Exception as exc:
                mesh_extraction_stats["materialization_audit_error"] = str(exc)
            try:
                xml_index = _build_xml_scene_index(
                    render_scene_path,
                    scene_id=scene_id,
                    materialization_records=materialization_records,
                    preview_mesh_manifest=preview_mesh_manifest.get("shapes", {}),
                )
                if xml_index is not None:
                    (scene_dir / "xml_scene_index.json").write_text(
                        json.dumps(xml_index, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
            except Exception as exc:
                mesh_extraction_stats["xml_scene_index_error"] = str(exc)
        except Exception as exc:
            generation_error = str(exc)

        if progress_cb is not None:
            progress_cb(total_estimate, total_estimate, "finalizing", "readiness")

        readiness = _build_opticalnav_render_readiness(
            authoring_payload,
            repo_root=self.repo_root,
            render_scene_path=render_scene_path,
            render_scene_ref=render_scene_ref,
            overlay_shape_count=overlay_shape_count,
            generation_error=generation_error,
            materialization_records=materialization_records,
        )
        render_readiness_path.write_text(json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8")
        readiness_ref = render_readiness_path.relative_to(project_dir).as_posix()

        sv_path = scene_dir / "scene_variant.json"
        sv = _read_json(sv_path)
        sv["render_sync_mode"] = "editor_generated_xml"
        sv["base_scene_xml_ref"] = None
        sv["overlay_scene_xml_ref"] = render_scene_ref
        sv["render_readiness_ref"] = readiness_ref
        sv["environment_profile"] = authoring_payload.get("environment") or {}
        sv["camera_rig_id"] = (authoring_payload.get("camera_rig") or {}).get("rig_id")
        sv["camera_rig"] = authoring_payload.get("camera_rig") or {}
        sv["texture_profile"] = readiness.get("texture_profile")
        sv_path.write_text(json.dumps(sv, ensure_ascii=False, indent=2), encoding="utf-8")

        # Patch metadata.sync directly in raw JSON to avoid full annotation validation
        # (which requires goal_regions/traversable_regions and would fail on uncommitted scenes).
        try:
            _raw = json.loads(annotation_path.read_text(encoding="utf-8"))
        except Exception:
            _raw = {"scene_id": scene_id}
        sync_payload = {
            **dict(_raw.get("metadata", {}).get("sync", {})),
            **result.sync,
            "render_scene": "synced" if readiness.get("ok") else "blocked",
            "render_scene_mode": "editor_generated_xml",
            "scene_variant_ref": result.scene_variant_ref,
            "render_scene_overlay_ref": result.overlay_ref,
            "render_scene_xml_ref": render_scene_ref,
            "render_readiness_ref": readiness_ref,
            "render_readiness_status": readiness.get("status"),
        }
        _raw.setdefault("metadata", {})["sync"] = sync_payload
        annotation_path.write_text(json.dumps(_raw, ensure_ascii=False, indent=2), encoding="utf-8")
        body = {
            "ok": bool(readiness.get("ok")),
            "stage": "sync_render_scene",
            "status": "done" if readiness.get("ok") else "blocked",
            "message": (
                f"Render-scene XML generated ({overlay_shape_count} proxy shapes)."
                if readiness.get("ok") else
                "Render-scene XML generated but render readiness is blocked."
            ),
            "scene_id": scene_id,
            "scene_variant_ref": result.scene_variant_ref,
            "render_scene_overlay_ref": result.overlay_ref,
            "render_scene_xml_ref": render_scene_ref,
            "render_readiness_ref": readiness_ref,
            "sync": sync_payload,
            "scene_variant": sv,
            "overlay": result.overlay,
            "render_readiness": readiness,
            "mesh_extraction_stats": mesh_extraction_stats,
            "room_shell": _compute_room_shell_geometry(authoring_payload),
            "project": self._opticalnav_project_summary(project_dir),
            "sync_job_id": sync_job_id,
            "envmap_invalidated": envmap_invalidated,
            "staged_cleared": staged_cleared,
            "annotation_missing": annotation_missing,
        }
        return int(HTTPStatus.OK), body

    def _publish_opticalnav_sync_progress(self, sync_job_id: str, payload: dict[str, Any]) -> None:
        """Record latest progress and broadcast to any WebSocket subscribers."""
        with self._opticalnav_sync_lock:
            self._opticalnav_sync_progress[sync_job_id] = dict(payload)
        with self._opticalnav_sync_sub_lock:
            subs = list(self._opticalnav_sync_subscribers.get(sync_job_id, ()))
        for s in subs:
            try:
                s.send_json(payload)
            except Exception:
                pass

    def _handle_opticalnav_sync_progress_websocket(self, handler: BaseHTTPRequestHandler, parsed: Any) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()

        query = parse_qs(parsed.query or "")
        sync_job_id = _maybe_str((query.get("sync_job_id") or [None])[0]) or ""
        subscriber = _GraphBuildSubscriber(handler=handler, lock=threading.Lock())
        with self._opticalnav_sync_sub_lock:
            bucket = self._opticalnav_sync_subscribers.setdefault(sync_job_id, set())
            bucket.add(subscriber)
        try:
            with self._opticalnav_sync_lock:
                state = self._opticalnav_sync_progress.get(sync_job_id)
            try:
                subscriber.send_json(state if state is not None else {"status": "idle", "processed": 0, "total": 0})
            except Exception:
                pass
            while not self._shutdown:
                frame = self._read_ws_frame(handler)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write_ws_frame(handler, payload, opcode=0xA)
        finally:
            with self._opticalnav_sync_sub_lock:
                bucket = self._opticalnav_sync_subscribers.get(sync_job_id, set())
                bucket.discard(subscriber)

    def _handle_graph_build_progress_websocket(self, handler: BaseHTTPRequestHandler, parsed: Any) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()

        query = parse_qs(parsed.query or "")
        project_id = _maybe_str((query.get("project_id") or [None])[0]) or ""
        scene_id = _maybe_str((query.get("scene_id") or [None])[0]) or ""
        project_dir = self.repo_root / "out" / "opticalnav" / project_id
        progress_key = f"{project_dir}/{scene_id}"

        subscriber = _GraphBuildSubscriber(handler=handler, lock=threading.Lock())
        with self._graph_build_sub_lock:
            if progress_key not in self._graph_build_subscribers:
                self._graph_build_subscribers[progress_key] = set()
            self._graph_build_subscribers[progress_key].add(subscriber)
        try:
            # Send current state on connect
            with self._graph_build_lock:
                state = self._graph_build_progress.get(progress_key)
            try:
                subscriber.send_json(state if state is not None else {"status": "idle", "progress": 0.0, "stage": ""})
            except Exception:
                pass
            while not self._shutdown:
                frame = self._read_ws_frame(handler)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write_ws_frame(handler, payload, opcode=0xA)
        finally:
            with self._graph_build_sub_lock:
                bucket = self._graph_build_subscribers.get(progress_key, set())
                bucket.discard(subscriber)

    # ── Scene-bundle export jobs ─────────────────────────────────────────

    _EXPORT_STAGE_LABELS = {
        "scope": "Export 범위 확인",
        "validate": "데이터셋 검사",
        "select_episodes": "내보낼 episode 선택",
        "build_manifest": "index/split 작성",
        "generate_thumbnails": "에피소드 썸네일 생성",
        "collect_files": "파일 수집",
        "zip_files": "파일 압축",
        "finalize": "다운로드 준비",
    }

    def _export_status_path(self, project_dir: Path, job_id: str) -> Path:
        return project_dir / "exports" / job_id / "export_status.json"

    def _publish_export_progress(self, job_id: str, project_dir: Path, **updates: Any) -> None:
        """Apply updates to the in-memory job state, write status.json atomically,
        and broadcast to any WS subscribers."""
        with self._export_jobs_lock:
            state = dict(self._export_jobs.get(job_id) or {})
            state.update({k: v for k, v in updates.items() if v is not None or k in ("error", "summary", "current_file")})
            state["job_id"] = job_id
            state["updated_at"] = _utc_now_iso()
            if "stage" in updates and updates["stage"]:
                state["stage_label"] = self._EXPORT_STAGE_LABELS.get(updates["stage"], updates["stage"])
            self._export_jobs[job_id] = state
            snapshot = dict(state)
        # Atomic write to disk (tmp + rename) so polling readers never see a
        # half-written JSON.
        try:
            status_path = self._export_status_path(project_dir, job_id)
            status_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = status_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(status_path)
        except OSError:
            pass
        with self._export_job_sub_lock:
            subs = list(self._export_job_subscribers.get(job_id, ()))
        for s in subs:
            try:
                s.send_json(snapshot)
            except Exception:
                pass

    def _export_cancel_requested(self, job_id: str) -> bool:
        with self._export_jobs_lock:
            return bool((self._export_jobs.get(job_id) or {}).get("cancel_requested"))

    def _run_export_job(
        self,
        job_id: str,
        project_id: str,
        project_dir: Path,
        scene_id: str,
        only_completed: bool,
        episode_ids: list[str] | None,
        include_episode_thumbnails: bool,
        panorama_observations: bool = True,
        png_only: bool = False,
        include_birdseye: bool = True,
        include_polarization_raw: bool = True,
    ) -> None:
        """Background worker — runs the 7-/8-stage scene bundle export.

        Stages, in order: scope → validate → select_episodes → build_manifest
        → [generate_thumbnails] → collect_files → zip_files → finalize.
        Each stage publishes progress so the WS / polling consumers can render
        a meaningful progress card; cancel is checked at every file boundary.
        """
        import shutil
        from navigation_dataset.episode_schema import read_episode
        from navigation_dataset.exporters.custom_json import (
            build_dataset_index,
            find_episode_files,
            is_episode_complete,
            iter_export_files,
            write_dataset_index_from,
            write_split_files_from,
        )
        from navigation_dataset.validation import validate_dataset

        exports_root = project_dir / "exports" / job_id
        staging = exports_root / "staging"
        ts = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        zip_path = exports_root / f"{scene_id}_{ts}.zip"

        def publish(**kwargs: Any) -> None:
            self._publish_export_progress(job_id, project_dir, **kwargs)

        class Cancelled(Exception):
            pass

        def check_cancel() -> None:
            if self._export_cancel_requested(job_id):
                raise Cancelled()

        try:
            publish(
                status="running",
                stage="scope",
                message=f"scene={scene_id}, only_completed={only_completed}",
                current=0,
                total=0,
                bytes_current=0,
                bytes_total=0,
            )
            check_cancel()

            publish(stage="validate", message="checking dataset")
            report = validate_dataset(project_dir, scene_ids=[scene_id])
            if not report.ok:
                publish(status="failed", error="validation failed", summary={"errors": report.errors})
                return
            check_cancel()

            # ── select_episodes ────────────────────────────────────────────
            all_paths = find_episode_files(project_dir)
            scene_paths = [
                p for p in all_paths
                if read_episode(p).scene_id == scene_id
            ]
            allow_ep = set(episode_ids) if episode_ids else None
            publish(stage="select_episodes", current=0, total=len(scene_paths), message="filtering")
            kept_paths: list[Path] = []
            kept_episodes = []
            for i, path in enumerate(scene_paths):
                check_cancel()
                try:
                    ep = read_episode(path)
                except Exception:
                    continue
                ok = True
                if allow_ep is not None and ep.episode_id not in allow_ep:
                    ok = False
                if ok and only_completed and not is_episode_complete(ep, project_dir):
                    ok = False
                if ok:
                    kept_paths.append(path)
                    kept_episodes.append(ep)
                publish(
                    stage="select_episodes",
                    current=i + 1,
                    total=len(scene_paths),
                    message=ep.episode_id,
                )
            episodes_kept = len(kept_paths)
            episodes_skipped = len(scene_paths) - episodes_kept

            # ── build_manifest ─────────────────────────────────────────────
            publish(stage="build_manifest", message="writing dataset.json + splits/*.json", current=0, total=0)
            staging.mkdir(parents=True, exist_ok=True)
            index_payload = build_dataset_index(
                project_dir,
                scene_ids=[scene_id],
                only_completed=only_completed,
                episode_ids=episode_ids,
            )
            write_dataset_index_from(index_payload, staging)
            write_split_files_from(index_payload, staging)
            check_cancel()

            # ── generate_thumbnails (opt-in) ───────────────────────────────
            if include_episode_thumbnails and kept_episodes:
                publish(stage="generate_thumbnails", current=0, total=len(kept_episodes), message="building L|F|R triplets")
                try:
                    from PIL import Image as _PILImage, ImageDraw as _PILDraw
                except Exception:
                    _PILImage = None
                    _PILDraw = None

                def _heading_to_yaw(h_id: str) -> int | None:
                    try:
                        return int(str(h_id).replace("h_", "").lstrip("0") or "0")
                    except ValueError:
                        return None

                def _nearest_heading(target_yaw: int, available: list[str]) -> str | None:
                    if not available:
                        return None
                    best = None
                    best_d = 360
                    for hid in available:
                        y = _heading_to_yaw(hid)
                        if y is None:
                            continue
                        d = abs((target_yaw - y + 540) % 360 - 180)
                        if d < best_d:
                            best_d = d
                            best = hid
                    return best

                for ep_idx, ep in enumerate(kept_episodes):
                    check_cancel()
                    if not ep.path_nodes or not ep.path_headings:
                        continue
                    pairs = list(zip(ep.path_nodes, ep.path_headings))
                    pad = max(len(str(max(len(pairs) - 1, 0))), 2)
                    thumb_dir = staging / "thumbnails" / ep.episode_id
                    thumb_dir.mkdir(parents=True, exist_ok=True)
                    vp_obs_root = project_dir / "scenes" / scene_id / "observations"
                    triplets: list[tuple[int, str, str, Path]] = []  # (step, vp, fwd_h, dst)
                    # Five panels per step. Render convention: yaw=0 looks
                    # +y_graph (N) and +yaw rotates CCW from above (N→W→S→E),
                    # so the agent's LEFT corresponds to forward +90° and the
                    # agent's RIGHT to forward -90°. Display order on the strip
                    # is LL · L · F · R · RR (reading left-to-right matches
                    # the agent panning their head left → right).
                    panel_offsets = [(60, "LL"), (30, "L"), (0, "F"), (-30, "R"), (-60, "RR")]
                    # Build a node_id → (x, y) map from viewpoint_graph.json so
                    # we can recompute forward yaw from positions and ignore
                    # episode.path_headings (which were saved with the old,
                    # 90°-off `_edge_heading` formula).
                    try:
                        import math as _math
                        from navigation_dataset.viewpoint_graph import read_viewpoint_graph as _read_vg
                        _vg = _read_vg(project_dir / "scenes" / scene_id / "viewpoint_graph.json")
                        _pos_by_id = {n.node_id: (float(n.position[0]), float(n.position[1])) for n in _vg.nodes}
                    except Exception:
                        _pos_by_id = {}

                    def _forward_yaw_from_positions(step_i: int) -> float | None:
                        nodes_p = ep.path_nodes
                        if step_i + 1 < len(nodes_p):
                            a, b = nodes_p[step_i], nodes_p[step_i + 1]
                        elif step_i > 0:
                            a, b = nodes_p[step_i - 1], nodes_p[step_i]
                        else:
                            return None
                        if a not in _pos_by_id or b not in _pos_by_id:
                            return None
                        ax, ay = _pos_by_id[a]
                        bx, by = _pos_by_id[b]
                        dx, dy = bx - ax, by - ay
                        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                            return None
                        return (_math.degrees(_math.atan2(-dx, dy)) + 360.0) % 360.0

                    for step_idx, (vp, h_fwd_saved) in enumerate(pairs):
                        # Prefer position-derived yaw; fall back to the saved
                        # path_heading when graph nodes aren't reachable.
                        fwd_yaw_pos = _forward_yaw_from_positions(step_idx)
                        if fwd_yaw_pos is not None:
                            fwd_yaw = int(round(fwd_yaw_pos))
                        else:
                            fwd_yaw = _heading_to_yaw(h_fwd_saved)
                        vp_dir = vp_obs_root / str(vp)
                        if fwd_yaw is None or not vp_dir.is_dir():
                            continue
                        available = sorted(d.name for d in vp_dir.iterdir() if d.is_dir())
                        # Snap forward to the nearest rendered heading at this vp.
                        h_fwd = _nearest_heading(int(fwd_yaw), available) or h_fwd_saved
                        panels: list[tuple[str, Path | None, str]] = []
                        for off, tag in panel_offsets:
                            hid = h_fwd if off == 0 else _nearest_heading((fwd_yaw + off) % 360, available)
                            rgb_path = (vp_dir / str(hid) / "rgb.png") if hid else None
                            panels.append((tag, rgb_path if rgb_path and rgb_path.is_file() else None, hid or "?"))
                        dst = thumb_dir / f"step_{str(step_idx).zfill(pad)}_yaw{str(fwd_yaw).zfill(3)}deg_{vp}.png"
                        if _PILImage is None or not any(p[1] is not None for p in panels):
                            if h_fwd in available:
                                src = vp_dir / h_fwd / "rgb.png"
                                if src.is_file():
                                    shutil.copy2(src, dst)
                                    triplets.append((step_idx, vp, h_fwd, dst))
                            continue
                        try:
                            sample = next(_PILImage.open(p[1]).convert("RGB") for p in panels if p[1])
                            sw, sh = sample.size
                            scale = 240 / max(sw, sh)
                            tw, th = max(1, int(sw * scale)), max(1, int(sh * scale))
                            bar_h = 22
                            gap = 4
                            sheet_w = tw * len(panels) + gap * (len(panels) - 1)
                            sheet_h = th + bar_h
                            sheet = _PILImage.new("RGB", (sheet_w, sheet_h), (15, 23, 42))
                            draw = _PILDraw.Draw(sheet) if _PILDraw is not None else None
                            x = 0
                            for tag, p, hid in panels:
                                if p is not None:
                                    im = _PILImage.open(p).convert("RGB").resize((tw, th), _PILImage.LANCZOS)
                                    sheet.paste(im, (x, 0))
                                if draw is not None:
                                    yaw_lbl = (str(_heading_to_yaw(hid) or 0).zfill(3) + "°") if hid else "—"
                                    draw.text((x + 4, th + 4), f"{tag} {yaw_lbl}", fill=(219, 234, 254))
                                x += tw + gap
                            if draw is not None:
                                draw.text((4, 4), f"#{step_idx}", fill=(253, 224, 71))
                            sheet.save(dst, optimize=True)
                            triplets.append((step_idx, vp, h_fwd, dst))
                        except Exception:
                            pass
                    # Goal preview — 4-direction (N/E/S/W) panorama at the goal
                    # node so the "go to goal X" instruction is grounded in
                    # actual imagery. Falls back to whatever headings exist.
                    if _PILImage is not None and ep.path_nodes:
                        goal_node = ep.goal_node or ep.path_nodes[-1]
                        goal_dir = vp_obs_root / str(goal_node)
                        if goal_dir.is_dir():
                            try:
                                goal_available = sorted(d.name for d in goal_dir.iterdir() if d.is_dir())
                                cardinal_yaws = [0, 90, 180, 270]
                                tiles_g = []
                                sw_g = sh_g = None
                                for yaw in cardinal_yaws:
                                    hid = _nearest_heading(yaw, goal_available)
                                    rgb_p = (goal_dir / str(hid) / "rgb.png") if hid else None
                                    if rgb_p and rgb_p.is_file():
                                        im = _PILImage.open(rgb_p).convert("RGB")
                                        if sw_g is None:
                                            sw_g, sh_g = im.size
                                            scale = 320 / max(sw_g, sh_g)
                                            tw_g, th_g = max(1, int(sw_g * scale)), max(1, int(sh_g * scale))
                                        im = im.resize((tw_g, th_g), _PILImage.LANCZOS)
                                        tile = _PILImage.new("RGB", (tw_g, th_g + 22), (15, 23, 42))
                                        tile.paste(im, (0, 0))
                                        if _PILDraw is not None:
                                            dg = _PILDraw.Draw(tile)
                                            dg.text((4, th_g + 4), f"yaw {str(yaw).zfill(3)}°", fill=(219, 234, 254))
                                        tiles_g.append(tile)
                                if tiles_g:
                                    gap = 4
                                    instr = (ep.natural_language_instruction or "").strip()
                                    head_h = 28 + (16 if instr else 0)
                                    sheet_w = sum(t.width for t in tiles_g) + gap * (len(tiles_g) - 1)
                                    sheet_h = max(t.height for t in tiles_g) + head_h
                                    sheet = _PILImage.new("RGB", (sheet_w, sheet_h), (15, 23, 42))
                                    if _PILDraw is not None:
                                        dh = _PILDraw.Draw(sheet)
                                        label = f"GOAL: {goal_node}"
                                        if ep.goal_region:
                                            label += f"  ({ep.goal_region})"
                                        dh.text((6, 6), label, fill=(252, 211, 77))
                                        if instr:
                                            # Truncate if longer than panel width.
                                            max_chars = max(20, sheet_w // 7)
                                            line = instr if len(instr) <= max_chars else instr[:max_chars - 1] + "…"
                                            dh.text((6, 24), f"“{line}”", fill=(219, 234, 254))
                                    x = 0
                                    for t in tiles_g:
                                        sheet.paste(t, (x, head_h))
                                        x += t.width + gap
                                    sheet.save(thumb_dir / "_goal_view.png", optimize=True)
                            except Exception:
                                pass
                    # Goal context txt — durable structured info for anyone
                    # programmatically reading the bundle. Captures the goal
                    # node, region, pose, and the instruction text in one
                    # spot per episode (the natural-language string alone can
                    # be ambiguous, e.g., "Go to couch" with multiple couches
                    # in the scene; the node id + pose + region resolve it).
                    try:
                        goal_node_id = ep.goal_node or (ep.path_nodes[-1] if ep.path_nodes else "")
                        goal_info = {
                            "episode_id": ep.episode_id,
                            "scene_id": ep.scene_id,
                            "instruction": ep.natural_language_instruction,
                            "goal_node": goal_node_id,
                            "goal_region": ep.goal_region,
                            "goal_pose": ep.goal_pose,
                            "start_node": ep.start_node,
                            "start_pose": ep.start_pose,
                            "path_node_count": len(ep.path_nodes),
                            "scenario": (ep.metadata or {}).get("scenario"),
                            "graph_distance_m": (ep.metadata or {}).get("graph_distance_m"),
                        }
                        (thumb_dir / "_goal_info.json").write_text(
                            json.dumps(goal_info, ensure_ascii=False, indent=2), encoding="utf-8",
                        )
                    except Exception:
                        pass
                    # Optional path strip — one wide PNG concatenating every
                    # step's triplet vertically (each row = one step), plus a
                    # caption band carrying the natural-language instruction so
                    # the user can see GT + the goal description in one place.
                    if _PILImage is not None and triplets:
                        try:
                            row_imgs = [_PILImage.open(p).convert("RGB") for _, _, _, p in triplets]
                            if row_imgs:
                                instruction = (ep.natural_language_instruction or "").strip()
                                head_h = 0
                                wrapped_lines: list[str] = []
                                if instruction and _PILDraw is not None:
                                    # Word-wrap to fit panel width.
                                    panel_w = max(im.width for im in row_imgs)
                                    avg_chr = 7
                                    chars_per_line = max(20, panel_w // avg_chr)
                                    words = instruction.split()
                                    line = ""
                                    for w in words:
                                        if len(line) + len(w) + 1 > chars_per_line:
                                            wrapped_lines.append(line)
                                            line = w
                                        else:
                                            line = (line + " " + w).strip()
                                    if line:
                                        wrapped_lines.append(line)
                                    head_h = 18 + 14 * len(wrapped_lines)
                                rw = max(im.width for im in row_imgs)
                                rh = head_h + sum(im.height for im in row_imgs) + 2 * (len(row_imgs) - 1)
                                strip = _PILImage.new("RGB", (rw, rh), (15, 23, 42))
                                if head_h and _PILDraw is not None:
                                    dh2 = _PILDraw.Draw(strip)
                                    dh2.text((6, 4), "INSTRUCTION:", fill=(252, 211, 77))
                                    for i, ln in enumerate(wrapped_lines):
                                        dh2.text((6, 18 + 14 * i), ln, fill=(219, 234, 254))
                                y = head_h
                                for im in row_imgs:
                                    strip.paste(im, (0, y))
                                    y += im.height + 2
                                strip.save(thumb_dir / "_path_strip.png", optimize=True)
                        except Exception:
                            pass
                    publish(
                        stage="generate_thumbnails",
                        current=ep_idx + 1,
                        total=len(kept_episodes),
                        message=ep.episode_id,
                    )

            # ── collect_files ──────────────────────────────────────────────
            publish(stage="collect_files", message="resolving bundle contents", current=0, total=0)
            files = list(iter_export_files(
                project_dir, index_payload, kept_episodes,
                panorama_observations=panorama_observations,
                include_exr=not png_only,
                include_polarization_raw=include_polarization_raw,
            ))
            bytes_total = sum(src.stat().st_size for src, _ in files)
            publish(
                stage="collect_files",
                current=0,
                total=len(files),
                bytes_total=bytes_total,
                message=f"{len(files)} files queued",
            )
            # Persist file manifest for audit.
            try:
                manifest_payload = {
                    "scene_id": scene_id,
                    "file_count": len(files),
                    "bytes_total": bytes_total,
                    "files": [{"src": str(src), "dst": dst, "bytes": src.stat().st_size} for src, dst in files],
                }
                (exports_root / "export_file_manifest.json").write_text(
                    json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            except OSError:
                pass
            # Copy into staging with throttled publishes (~200ms).
            last_pub = 0.0
            bytes_current = 0
            for i, (src, dst_rel) in enumerate(files):
                check_cancel()
                dst = staging / dst_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                    bytes_current += src.stat().st_size
                except OSError:
                    pass
                now = time.monotonic()
                if now - last_pub > 0.2 or i + 1 == len(files):
                    publish(
                        stage="collect_files",
                        current=i + 1,
                        total=len(files),
                        bytes_current=bytes_current,
                        bytes_total=bytes_total,
                        current_file=dst_rel,
                    )
                    last_pub = now

            # ── bird's-eye summary ─────────────────────────────────────────
            # Top-down PNG of the grid + viewpoint graph + episode paths.
            if include_birdseye:
                try:
                    from navigation_dataset.birdseye import render_birdseye
                    _scene_dir = project_dir / "scenes" / scene_id
                    _grid_npy = _scene_dir / "traversable_grid.npy"
                    _grid_meta = _scene_dir / "traversable_grid.npy.json"
                    _vg = _scene_dir / "viewpoint_graph.json"
                    if _grid_npy.exists() and _vg.exists():
                        grid_spec = (_read_json(_grid_meta).get("grid") if _grid_meta.exists() else {}) or {}
                        ep_dicts = []
                        for _ep in kept_episodes:
                            ep_path = project_dir / "episodes" / _ep.split / f"{_ep.episode_id}.json"
                            if ep_path.is_file():
                                ep_dicts.append(_read_json(ep_path))
                        out_png = staging / "scenes" / scene_id / f"{scene_id}__birdseye.png"
                        render_birdseye(_grid_npy, grid_spec, _read_json(_vg), ep_dicts, out_png, scale=4)
                except Exception:
                    pass  # best-effort summary; never fail the export over it

            # ── zip_files ──────────────────────────────────────────────────
            staging_files = sorted(p for p in staging.rglob("*") if p.is_file())
            zip_bytes_total = sum(p.stat().st_size for p in staging_files)
            publish(
                stage="zip_files",
                current=0,
                total=len(staging_files),
                bytes_current=0,
                bytes_total=zip_bytes_total,
                message=f"compressing {len(staging_files)} files",
            )
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            zip_bytes_current = 0
            last_pub = 0.0
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for i, p in enumerate(staging_files):
                    check_cancel()
                    arcname = p.relative_to(staging).as_posix()
                    zf.write(p, arcname)
                    zip_bytes_current += p.stat().st_size
                    now = time.monotonic()
                    if now - last_pub > 0.2 or i + 1 == len(staging_files):
                        publish(
                            stage="zip_files",
                            current=i + 1,
                            total=len(staging_files),
                            bytes_current=zip_bytes_current,
                            bytes_total=zip_bytes_total,
                            current_file=p.name,
                        )
                        last_pub = now

            # ── finalize ──────────────────────────────────────────────────
            publish(stage="finalize", message="writing report")
            zip_size = zip_path.stat().st_size if zip_path.exists() else 0
            zip_ref = zip_path.relative_to(self.repo_root).as_posix()
            duration = time.monotonic() - 0  # filled by caller
            report_payload = {
                "job_id": job_id,
                "project_id": project_id,
                "scene_id": scene_id,
                "only_completed": only_completed,
                "include_episode_thumbnails": include_episode_thumbnails,
                "episodes_total_in_scope": len(scene_paths),
                "episodes_exported": episodes_kept,
                "episodes_skipped": episodes_skipped,
                "files_packaged": len(staging_files),
                "zip_size_bytes": zip_size,
                "zip_ref": zip_ref,
                "download_url": f"/artifacts?path={quote(zip_ref)}",
                "generated_at": _utc_now_iso(),
            }
            try:
                (exports_root / "export_report.json").write_text(
                    json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8",
                )
            except OSError:
                pass
            publish(
                status="succeeded",
                stage="finalize",
                message="export complete",
                summary=report_payload,
                current=len(staging_files),
                total=len(staging_files),
                bytes_current=zip_bytes_current,
                bytes_total=zip_bytes_total,
            )
            # Cleanup staging (optional — keep for now so user can inspect on error).
            try:
                shutil.rmtree(staging, ignore_errors=True)
            except OSError:
                pass
        except Cancelled:
            publish(status="cancelled", message="export cancelled")
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            publish(status="failed", error=f"{type(exc).__name__}: {exc}")

    def _handle_export_job_websocket(self, handler: BaseHTTPRequestHandler, parsed: Any) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()
        query = parse_qs(parsed.query or "")
        job_id = _maybe_str((query.get("job_id") or [None])[0]) or ""
        subscriber = _GraphBuildSubscriber(handler=handler, lock=threading.Lock())
        with self._export_job_sub_lock:
            bucket = self._export_job_subscribers.setdefault(job_id, set())
            bucket.add(subscriber)
        try:
            with self._export_jobs_lock:
                state = self._export_jobs.get(job_id)
            try:
                subscriber.send_json(state if state is not None else {"job_id": job_id, "status": "unknown"})
            except Exception:
                pass
            while not self._shutdown:
                frame = self._read_ws_frame(handler)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write_ws_frame(handler, payload, opcode=0xA)
        finally:
            with self._export_job_sub_lock:
                bucket = self._export_job_subscribers.get(job_id, set())
                bucket.discard(subscriber)

    def _handle_job_status_websocket(self, handler: BaseHTTPRequestHandler) -> None:
        key = handler.headers.get("Sec-WebSocket-Key", "").strip()
        if not key:
            handler.send_error(HTTPStatus.BAD_REQUEST, "Missing Sec-WebSocket-Key")
            return
        accept = base64.b64encode(hashlib.sha1(f"{key}{_WS_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()

        subscriber = _JobStatusSubscriber(handler=handler, lock=threading.Lock())
        with self._job_status_sub_lock:
            self._job_status_subscribers.add(subscriber)
        try:
            # Send current state immediately on connect
            try:
                subscriber.send_json(self._job_status_ws_payload())
            except Exception:
                pass
            while not self._shutdown:
                frame = self._read_ws_frame(handler)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._write_ws_frame(handler, payload, opcode=0xA)
        finally:
            with self._job_status_sub_lock:
                self._job_status_subscribers.discard(subscriber)

    def _read_ws_frame(self, handler: BaseHTTPRequestHandler) -> tuple[int, bytes] | None:
        header = handler.rfile.read(2)
        if len(header) < 2:
            return None
        first, second = header[0], header[1]
        opcode = first & 0x0F
        masked = (second & 0x80) != 0
        length = second & 0x7F
        if length == 126:
            raw = handler.rfile.read(2)
            if len(raw) < 2:
                return None
            length = int.from_bytes(raw, "big")
        elif length == 127:
            raw = handler.rfile.read(8)
            if len(raw) < 8:
                return None
            length = int.from_bytes(raw, "big")
        if length > 1_000_000:
            return None
        mask = handler.rfile.read(4) if masked else b""
        if masked and len(mask) < 4:
            return None
        payload = handler.rfile.read(length)
        if len(payload) < length:
            return None
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return opcode, payload

    def _write_ws_frame(self, handler: BaseHTTPRequestHandler, payload: bytes, *, opcode: int = 0x1) -> None:
        length = len(payload)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.extend([126, *length.to_bytes(2, "big")])
        else:
            header.extend([127, *length.to_bytes(8, "big")])
        handler.wfile.write(bytes(header) + payload)
        handler.wfile.flush()

    def _scene_telemetry_signature(self, payload: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
        if not isinstance(payload, Mapping):
            return None
        active_camera = payload.get("active_viewport_camera")
        if not isinstance(active_camera, Mapping):
            return (
                str(payload.get("scene_id") or ""),
                None,
            )
        return (
            str(payload.get("scene_id") or ""),
            str(active_camera.get("sensor_id") or ""),
            round(float(active_camera.get("fov_deg") or 0.0), 3),
            tuple(round(float(value), 4) for value in list(active_camera.get("origin") or [])),
            tuple(round(float(value), 4) for value in list(active_camera.get("target") or [])),
        )

    def _scene_telemetry_payload(self, *, scene_id: str | None = None) -> dict[str, Any] | None:
        session = self._isaac_session
        if session is None:
            return None
        if scene_id is not None and session.scene_id != scene_id:
            return None
        return {
            "scene_id": session.scene_id,
            "updated_at": session.updated_at,
            "sensor_revision": int(session.sensor_revision),
            "active_viewport_camera": self._active_viewport_camera_payload(session),
        }

    def _broadcast_scene_telemetry(self, *, force: bool = False) -> None:
        payload = self._scene_telemetry_payload()
        signature = self._scene_telemetry_signature(payload)
        if not force and signature == self._last_scene_telemetry_signature:
            return
        self._last_scene_telemetry_signature = signature
        if payload is None:
            return
        stale: list[_SceneTelemetrySubscriber] = []
        with self._scene_telemetry_lock:
            subscribers = list(self._scene_telemetry_subscribers)
        for subscriber in subscribers:
            if not subscriber.matches(str(payload.get("scene_id") or "")):
                continue
            try:
                subscriber.send_json(payload)
            except Exception:
                stale.append(subscriber)
        if stale:
            with self._scene_telemetry_lock:
                for subscriber in stale:
                    self._scene_telemetry_subscribers.discard(subscriber)

    def submit_payload(self, payload: Mapping[str, Any]) -> RenderJobAccepted:
        request_payload = dict(payload)
        runtime_overrides = request_payload.pop("runtime_overrides", None)
        variant = request_payload.pop("variant", None)
        nested_request = request_payload.pop("render_request", None)
        if request_payload:
            if nested_request is not None:
                raise ValueError("Unexpected keys alongside render_request envelope.")
            nested_request = payload
            runtime_overrides = None
            variant = None

        if nested_request is None or not isinstance(nested_request, Mapping):
            raise ValueError("POST /render expects a RenderRequest payload or {'render_request': ...}.")
        if runtime_overrides is None:
            runtime_overrides = {}
        if not isinstance(runtime_overrides, Mapping):
            raise ValueError("runtime_overrides must be an object when provided.")

        render_request = render_request_from_payload(dict(nested_request))
        if runtime_overrides:
            request_dict = render_request_to_payload(render_request)
            render_request = render_request_from_payload(_deep_merge(request_dict, dict(runtime_overrides)))
        return self.submit(render_request, variant=str(variant) if variant is not None else None, runtime_overrides=dict(runtime_overrides))

    def submit(
        self,
        render_request: RenderRequest,
        *,
        variant: str | None = None,
        runtime_overrides: Mapping[str, Any] | None = None,
        lazy_persist: bool = False,
    ) -> RenderJobAccepted:
        if _backend_only_mode():
            raise RuntimeError("render_queue_disabled: start scripts/run_render_queue_optix7.sh for GPU render jobs")
        render_request, render_settings_variant = _extract_render_settings_variant(render_request)
        chosen_variant = str(variant or render_settings_variant or self.variant)
        runtime_override_payload = dict(runtime_overrides or {})
        request_payload = render_request_to_payload(render_request)
        scene_cache_key = self._scene_cache_key(render_request, chosen_variant)

        with self._condition:
            if render_request.job_id in self._jobs:
                existing = self._jobs[render_request.job_id]
                if existing.status.status in ("queued", "running"):
                    # Idempotent re-submit: job is already in flight — return existing info.
                    return RenderJobAccepted(
                        job_id=existing.render_request.job_id,
                        frame_id=existing.render_request.frame_id,
                        status=existing.status.status,
                        submitted_at=existing.status.submitted_at,
                        status_url=f"{self.base_url}/jobs/{existing.render_request.job_id}",
                        manifest_url=f"{self.base_url}/jobs/{existing.render_request.job_id}/manifest",
                        queue_position=0,
                        extras={"request_id": existing.render_request.request_id, "variant": existing.variant, "idempotent": True},
                    )
                raise ValueError(f"Duplicate job_id already queued or rendered: {render_request.job_id}")

            submitted_at = _utc_now_iso()
            cache_stats = self._scene_cache_stats.setdefault(scene_cache_key, {"submissions": 0, "runs": 0})
            cache_stats["submissions"] += 1
            cache_stats["last_submitted_at"] = submitted_at

            status_extras: dict[str, Any] = {
                "request_id": render_request.request_id,
                "variant": chosen_variant,
                "scene_cache_key": scene_cache_key,
                "scene_cache_submissions": int(cache_stats["submissions"]),
                "sync_mode": str(render_request.extras.get("sync_mode") or "unknown"),
                "sync_policy": str(render_request.extras.get("sync_policy") or "default"),
            }
            worker_gpu_index = runtime_override_payload.get("worker_gpu_index")
            if worker_gpu_index is not None:
                try:
                    status_extras["target_gpu_index"] = int(worker_gpu_index)
                except (TypeError, ValueError):
                    status_extras["target_gpu_index"] = str(worker_gpu_index)
            for key in ("shard_index", "shard_count", "shard_item_index", "shard_size"):
                if key in runtime_override_payload:
                    try:
                        status_extras[key] = int(runtime_override_payload[key])
                    except (TypeError, ValueError):
                        status_extras[key] = runtime_override_payload[key]

            status = RenderJobStatus(
                job_id=render_request.job_id,
                frame_id=render_request.frame_id,
                status="queued",
                submitted_at=submitted_at,
                progress_stage="queued",
                extras=status_extras,
            )
            job = _QueuedJob(
                render_request=render_request,
                status=status,
                request_payload=request_payload,
                variant=chosen_variant,
                runtime_overrides=runtime_override_payload,
                lazy_persist=lazy_persist,
            )
            self._jobs[render_request.job_id] = job
            self._enqueue_pending_unlocked(render_request.job_id, job)
            queue_position = len(self._pending)
            self._condition.notify_all()

        if not lazy_persist:
            # Disk I/O outside the lock — each job writes to its own unique path so
            # concurrent submit() calls from different HTTP handler threads don't interfere.
            self._persist_request_unlocked(job)
            self._persist_status_unlocked(job)
            self._record_render_job_telemetry(job, event_type="queued")

        return RenderJobAccepted(
            job_id=render_request.job_id,
            frame_id=render_request.frame_id,
            status="queued",
            submitted_at=submitted_at,
            status_url=f"{self.base_url}/jobs/{render_request.job_id}",
            manifest_url=f"{self.base_url}/jobs/{render_request.job_id}/manifest",
            queue_position=queue_position,
            extras={
                "request_id": render_request.request_id,
                "variant": chosen_variant,
            },
        )

    def get_status(self, job_id: str) -> RenderJobStatus:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return RenderJobStatus(**render_job_status_to_payload(job.status))

    def get_manifest(self, job_id: str) -> ObservationBundleManifest:
        status = self.get_status(job_id)
        if status.manifest_path is None:
            raise RuntimeError(f"Manifest is not available yet for job {job_id}.")
        manifest_path = resolve_repo_path(self.repo_root, status.manifest_path)
        if not manifest_path.exists():
            raise RuntimeError(f"Manifest path does not exist yet: {status.manifest_path}")
        return read_observation_bundle_manifest(manifest_path)

    def cancel(self, job_id: str) -> RenderJobStatus:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status.status == "queued":
                try:
                    self._pending.remove(job_id)
                except ValueError:
                    pass
                job.status.status = "cancelled"
                job.status.finished_at = _utc_now_iso()
                job.status.progress_stage = "cancelled"
                job.status.extras["cancelled_before_start"] = True
                self._persist_status_unlocked(job)
                self._record_render_job_telemetry(job, event_type="cancelled")
                self._append_job_log_line(job, event_type="cancelled", stage="cancelled", message="Job cancelled before start")
                self._condition.notify_all()
                return RenderJobStatus(**render_job_status_to_payload(job.status))
            if job.status.status == "running":
                job.status.status = "cancelled"
                job.status.finished_at = _utc_now_iso()
                job.status.progress_stage = "cancelled"
                job.status.extras["cancelled_while_running"] = True
                job.status.error = None
                manager = self._render_worker_manager
                if manager is not None:
                    job.status.extras["worker_cancel_requested"] = bool(manager.cancel(job_id))
                self._persist_status_unlocked(job)
                self._record_render_job_telemetry(job, event_type="cancelled")
                self._append_job_log_line(job, event_type="cancelled", stage="cancelled", message="Job cancelled")
                self._condition.notify_all()
                return RenderJobStatus(**render_job_status_to_payload(job.status))
            return RenderJobStatus(**render_job_status_to_payload(job.status))

    def delete_job(self, job_id: str, *, force: bool = False) -> None:
        """Remove a finished/cancelled/failed job record and its log file.

        Queued/running jobs are refused unless `force=True`, which lets callers
        purge orphaned stale entries (e.g. records left behind when a daemon
        exited mid-render). Deletes in-memory status, the status JSON, and the
        log file. No-ops for unknown ids so repeated UI dismissals are idempotent.
        """
        job_id = (job_id or "").strip()
        if not job_id:
            raise ValueError("Missing job_id")
        with self._condition:
            job = self._jobs.get(job_id)
            if job is not None:
                state = job.status.status
                if state in ("queued", "running") and not force:
                    raise RuntimeError(f"Cannot delete a {state} job; cancel it first.")
                self._jobs.pop(job_id, None)
            try:
                self._pending.remove(job_id)
            except ValueError:
                pass
            try:
                self._status_path(job_id).unlink(missing_ok=True)
            except Exception:
                pass
            try:
                self._job_log_path(job_id).unlink(missing_ok=True)
            except Exception:
                pass
            self._invalidate_job_status_cache()

    def _opticalnav_root(self) -> Path:
        root = self.repo_root / "out" / "opticalnav"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _safe_opticalnav_project_id(self, value: str) -> str:
        safe = []
        previous_dash = False
        for char in (value or "").strip().lower():
            if char.isalnum() or char in {"_", "."}:
                safe.append(char)
                previous_dash = False
            elif not previous_dash:
                safe.append("-")
                previous_dash = True
        project_id = "".join(safe).strip("-.") or f"project-{_utc_now().strftime('%Y%m%d%H%M%S')}"
        return project_id[:80]

    def _opticalnav_project_dir(self, project_id: str) -> Path:
        root = self._opticalnav_root().resolve()
        project = (root / unquote(project_id)).resolve()
        if project != root and root in project.parents:
            return project
        raise ValueError(f"Invalid OpticalNav project_id: {project_id!r}")

    def _opticalnav_episode_files(self, project_dir: Path, *, split: str | None = None) -> list[Path]:
        if split:
            return sorted((project_dir / "episodes" / split).glob("*.json"))
        return sorted((project_dir / "episodes").glob("*/*.json"))

    def _opticalnav_find_episode(self, project_dir: Path, episode_id: str) -> Path:
        for path in self._opticalnav_episode_files(project_dir):
            if path.stem == episode_id:
                return path
        raise KeyError(episode_id)

    def _opticalnav_create_layout(self, project_dir: Path) -> None:
        for rel in (
            "scenes",
            "episodes/train",
            "episodes/val_seen",
            "episodes/val_unseen",
            "episodes/test",
            "observations",
            "viewpoint_observations",
            "splits",
            "evaluation",
            "docs",
            "render_batches",
            "graph_render_batches",
        ):
            (project_dir / rel).mkdir(parents=True, exist_ok=True)
        readme = project_dir / "README.md"
        if not readme.exists():
            readme.write_text(
                "# OpticalNav-v0.2\n\n"
                "Targeted synthetic fine-tuning dataset for glass, mirror, "
                "transparent partition, and reflective navigation hazards.\n\n"
                "OpticalNav builds a sensor-rich viewpoint graph from Isaac-Mitsuba scene variants, "
                "caches multi-modal observations at each graph node, and generates navigation episodes "
                "by querying shortest paths over this graph.\n",
                encoding="utf-8",
            )
        dataset_card = project_dir / "dataset_card.md"
        if not dataset_card.exists():
            dataset_card.write_text(
                "# Dataset Card\n\n"
                "This package is not a full VLN benchmark. It is a targeted "
                "synthetic fine-tuning dataset generator output.\n\n"
                "`active_nir_intensity` is an NIR-like proxy, not a calibrated physical NIR camera model.\n",
                encoding="utf-8",
            )
        docs = {
            "action_interface.md": "Actions: move_forward, turn_left, turn_right, stop.\n",
            "coordinate_system.md": "Poses use [x, y, yaw] in the annotation/map coordinate system.\n",
            "modality_definitions.md": (
                "Public v0.2 modalities: rgb, depth, active_nir_intensity, hazard_mask.\n"
                "active_nir_intensity is an NIR-like proxy, not calibrated physical NIR.\n"
            ),
            "graph_action_interface.md": "Graph actions: move_to_neighbor, turn_left_30, turn_right_30, stop.\n",
            "known_limitations.md": (
                "v0.2 excludes full physics rollout, real robot execution, VLN-CE/LeRobot native export, "
                "semantic/instance segmentation, LiDAR-like point clouds, hyperspectral cubes, and training code.\n"
            ),
        }
        for name, text in docs.items():
            path = project_dir / "docs" / name
            if not path.exists():
                path.write_text(text, encoding="utf-8")

    def _opticalnav_project_summary(self, project_dir: Path) -> dict[str, Any]:
        from navigation_dataset.validation import validate_dataset

        dataset_path = project_dir / "dataset.json"
        dataset = _read_json(dataset_path) if dataset_path.exists() else {}
        scenes = []
        for scene_dir in sorted((project_dir / "scenes").glob("*")):
            if not scene_dir.is_dir():
                continue
            annotation_path = scene_dir / "scene_annotation.json"
            authoring_map_path = scene_dir / "authoring_map.json"
            traversable_grid_path = scene_dir / "traversable_grid.npy"
            nav_graph_path = scene_dir / "nav_graph.json"
            annotation_ok = False
            annotation_error = None
            sync_status: dict[str, Any] = {
                "dataset": "missing",
                "render_scene": "missing",
                "isaac_stage": "missing",
                "annotation_stale": False,
                "traversable_map_stale": False,
                "viewpoint_graph_stale": False,
            }
            if annotation_path.exists():
                try:
                    from navigation_dataset.scene_annotations import read_scene_annotation

                    annotation = read_scene_annotation(annotation_path)
                    annotation_ok = True
                    sync_status.update(dict(annotation.metadata.get("sync", {})))
                except Exception as exc:
                    annotation_error = str(exc)
                    # Fallback: read sync metadata directly from raw JSON even if validation fails
                    # (scenes before compilation may lack goal_regions/traversable_regions).
                    try:
                        _raw_ann = json.loads(annotation_path.read_text(encoding="utf-8"))
                        sync_status.update(dict(_raw_ann.get("metadata", {}).get("sync", {})))
                    except Exception:
                        pass
            if authoring_map_path.exists() and annotation_path.exists():
                sync_status["annotation_stale"] = authoring_map_path.stat().st_mtime > annotation_path.stat().st_mtime
            if annotation_path.exists() and traversable_grid_path.exists():
                sync_status["traversable_map_stale"] = annotation_path.stat().st_mtime > traversable_grid_path.stat().st_mtime
            graph_path = scene_dir / "viewpoint_graph.json"
            graph_summary = None
            if graph_path.exists():
                try:
                    from navigation_dataset.viewpoint_graph import read_viewpoint_graph

                    graph = read_viewpoint_graph(graph_path)
                    graph_summary = {
                        "graph_id": graph.graph_id,
                        "node_count": len(graph.nodes),
                        "edge_count": len(graph.edges),
                        "heading_count": graph.node_heading_count,
                        "hazard_edge_count": sum(1 for edge in graph.edges if edge.hazard_crossing),
                    }
                except Exception as exc:
                    graph_summary = {"error": str(exc)}
            if traversable_grid_path.exists() and graph_path.exists():
                sync_status["viewpoint_graph_stale"] = traversable_grid_path.stat().st_mtime > graph_path.stat().st_mtime
            usd_ref = self._opticalnav_scene_usd_ref(project_dir, scene_dir.name)
            usd_exists = False
            usd_error = None
            if usd_ref:
                try:
                    usd_exists = resolve_repo_path(self.repo_root, usd_ref).exists()
                    if not usd_exists:
                        usd_error = f"USD ref does not exist: {usd_ref}"
                except Exception as exc:
                    usd_error = str(exc)
            readiness_path = scene_dir / "render_readiness.json"
            readiness_summary = None
            if readiness_path.exists():
                try:
                    readiness_payload = _read_json(readiness_path)
                    readiness_summary = {
                        "ok": bool(readiness_payload.get("ok")),
                        "status": readiness_payload.get("status"),
                        "texture_profile": readiness_payload.get("texture_profile"),
                        "error_count": len(readiness_payload.get("errors") or []),
                        "warning_count": len(readiness_payload.get("warnings") or []),
                    }
                except Exception as exc:
                    readiness_summary = {"ok": False, "status": "unreadable", "error": str(exc)}
            scenes.append({
                "scene_id": scene_dir.name,
                "usd_ref": usd_ref,
                "usd_exists": usd_exists,
                "usd_error": usd_error,
                "annotation_ref": annotation_path.relative_to(project_dir).as_posix() if annotation_path.exists() else None,
                "authoring_map_ref": authoring_map_path.relative_to(project_dir).as_posix() if authoring_map_path.exists() else None,
                "authoring_map_exists": authoring_map_path.exists(),
                "editor_geometry_ref": (scene_dir / "editor_geometry.json").relative_to(project_dir).as_posix() if (scene_dir / "editor_geometry.json").exists() else None,
                "editor_geometry_exists": (scene_dir / "editor_geometry.json").exists(),
                "scene_variant_ref": (scene_dir / "scene_variant.json").relative_to(project_dir).as_posix() if (scene_dir / "scene_variant.json").exists() else None,
                "render_scene_overlay_ref": (scene_dir / "render_scene_overlays.json").relative_to(project_dir).as_posix() if (scene_dir / "render_scene_overlays.json").exists() else None,
                "render_scene_xml_ref": (scene_dir / "render_scene.xml").relative_to(project_dir).as_posix() if (scene_dir / "render_scene.xml").exists() else None,
                "render_readiness_ref": readiness_path.relative_to(project_dir).as_posix() if readiness_path.exists() else None,
                "render_readiness": readiness_summary,
                "annotation_ok": annotation_ok,
                "annotation_error": annotation_error,
                "sync_status": sync_status,
                "map_exists": traversable_grid_path.exists(),
                "nav_graph_exists": nav_graph_path.exists(),
                "viewpoint_graph_exists": graph_path.exists(),
                "viewpoint_graph": graph_summary,
            })
        split_counts: dict[str, int] = {}
        for split_dir in sorted((project_dir / "episodes").glob("*")):
            if split_dir.is_dir():
                split_counts[split_dir.name] = len(list(split_dir.glob("*.json")))
        report = validate_dataset(project_dir, require_observations=False).to_payload()
        return {
            "project_id": project_dir.name,
            "root": project_dir.relative_to(self.repo_root).as_posix(),
            "dataset": dataset,
            "scenes": scenes,
            "split_counts": split_counts,
            "episode_count": sum(split_counts.values()),
            "validation": report,
        }

    def _opticalnav_starter_annotation(self, scene_id: str, usd_ref: str | None) -> dict[str, Any]:
        return {
            "scene_id": scene_id,
            "usd_ref": usd_ref,
            "coordinate_system": "xy_yaw",
            "objects": [
                {
                    "object_id": "glass_surface_01",
                    "category": "transparent_surface",
                    "hazard_type": "glass_door",
                    "geometry": {"type": "box", "bounds": [0.9, -0.15, 1.1, 0.15]},
                    "mask_export": True,
                },
                {
                    "object_id": "chair_01",
                    "category": "landmark",
                    "geometry": {"type": "circle", "center": [2.0, 0.0], "radius": 0.2},
                    "mask_export": False,
                },
            ],
            "transparent_surfaces": ["glass_surface_01"],
            "reflective_hazards": [],
            "hazard_regions": [
                {
                    "region_id": "hazard_glass_surface_01",
                    "hazard_type": "transparent_surface",
                    "geometry": {"type": "box", "bounds": [0.85, -0.25, 1.15, 0.25]},
                    "object_refs": ["glass_surface_01"],
                    "collision_risk": True,
                }
            ],
            "goal_regions": [
                {
                    "region_id": "goal_near_chair",
                    "center": [2.0, 0.0, 0.0],
                    "radius": 0.35,
                    "label": "chair",
                    "landmark_refs": ["chair_01"],
                }
            ],
            "landmarks": [
                {
                    "landmark_id": "chair_01",
                    "label": "chair",
                    "center": [2.0, 0.0, 0.0],
                    "object_ref": "chair_01",
                    "goal_candidate": True,
                }
            ],
            "traversable_regions": [
                {
                    "region_id": "corridor_floor",
                    "geometry": {"type": "box", "bounds": [-0.5, -0.8, 2.6, 0.8]},
                    "traversable": True,
                }
            ],
            "metadata": {"starter": True},
            "schema_version": "0.1",
        }

    def _opticalnav_scene_usd_ref(self, project_dir: Path, scene_id: str) -> str | None:
        scene_dir = project_dir / "scenes" / scene_id
        annotation_path = scene_dir / "scene_annotation.json"
        if annotation_path.exists():
            try:
                annotation = _read_json(annotation_path)
                usd_ref = _maybe_str(annotation.get("usd_ref"))
                if usd_ref:
                    return usd_ref
            except Exception:
                pass
        dataset_path = project_dir / "dataset.json"
        if dataset_path.exists():
            try:
                dataset = _read_json(dataset_path)
                for scene in dataset.get("scenes", []) or []:
                    if isinstance(scene, Mapping) and scene.get("scene_id") == scene_id:
                        usd_ref = _maybe_str(scene.get("usd_ref"))
                        if usd_ref:
                            return usd_ref
            except Exception:
                pass
        return None

    def _opticalnav_usd_extractor_status(self) -> dict[str, Any]:
        try:
            from pxr import Usd  # type: ignore

            return {
                "runtime": "daemon_python",
                "python_executable": sys.executable,
                "python_version": platform.python_version(),
                "pxr_available": True,
                "usd_version": ".".join(str(part) for part in Usd.GetVersion()),
            }
        except Exception as exc:
            return {
                "runtime": "daemon_python",
                "python_executable": sys.executable,
                "python_version": platform.python_version(),
                "pxr_available": False,
                "reason": str(exc),
                "recommended_fix": "Use Isaac-side extraction or install usd-core into this daemon Python runtime.",
            }

    def _opticalnav_usd_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        roots = [self.repo_root / "assets" / "moorelane", self.repo_root / "scenes" / "moorelane"]
        seen: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted([*root.rglob("*.usd"), *root.rglob("*.usda")]):
                try:
                    rel = path.relative_to(self.repo_root).as_posix()
                except ValueError:
                    continue
                if rel in seen:
                    continue
                seen.add(rel)
                label = path.stem.replace("_", " ")
                candidates.append({
                    "usd_ref": rel,
                    "label": label,
                    "source": "moorelane",
                    "size_bytes": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                })
        return candidates

    def _opticalnav_dtc_object_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        roots = [
            self.repo_root / "vendor_datasets" / "dtc_objects",
            self.repo_root / "vendor_datasets" / "digital_twin_catalog",
            self.repo_root / "vendor_datasets" / "DigitalTwinCatalog",
            self.repo_root / "assets" / "dtc_objects",
        ]
        seen: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("3d-asset.glb")):
                try:
                    rel = path.relative_to(self.repo_root).as_posix()
                except ValueError:
                    continue
                if rel in seen:
                    continue
                seen.add(rel)
                metadata_path = path.parent / "metadata.json"
                metadata = _read_json(metadata_path) if metadata_path.exists() else {}
                label = self._dtc_metadata_label(metadata, path.parent.name)
                candidates.append({
                    "usd_ref": rel,
                    "source_ref": rel,
                    "label": label,
                    "source": "digital_twin_catalog",
                    "source_type": "dtc_glb_object",
                    "metadata_ref": metadata_path.relative_to(self.repo_root).as_posix() if metadata_path.exists() else None,
                    "license_ref": self._dtc_license_ref(path.parent),
                    "size_bytes": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                })
        return candidates

    def _opticalnav_asset_library_dir(self) -> Path:
        path = self._opticalnav_root() / "asset_library"
        (path / "catalogs").mkdir(parents=True, exist_ok=True)
        return path

    def _asset_source_hash(self, usd_ref: str) -> str:
        return hashlib.sha1(usd_ref.encode("utf-8")).hexdigest()[:16]

    def _opticalnav_curated_asset_manifests(self) -> list[dict[str, Any]]:
        root = self.repo_root / "assets" / "opticalnav_curated"
        manifests: list[dict[str, Any]] = []
        if not root.exists():
            return manifests
        for path in sorted(root.glob("*.json")):
            try:
                payload = _read_json(path)
            except Exception:
                continue
            source_usd = _maybe_str(payload.get("source_usd"))
            if not source_usd:
                continue
            manifests.append({**payload, "_manifest_ref": path.relative_to(self.repo_root).as_posix()})
        return manifests

    def _opticalnav_curated_manifest_for_source(self, usd_ref: str) -> dict[str, Any] | None:
        for manifest in self._opticalnav_curated_asset_manifests():
            if str(manifest.get("source_usd") or "") == usd_ref:
                return manifest
        return None

    # ─── Asset thumbnail ──────────────────────────────────────────────────────

    _THUMB_COLORS: dict[str, tuple[int, int, int]] = {
        "glass":     (103, 232, 249),
        "mirror":    (100, 116, 139),
        "furniture": (154, 90,  36),
        "shell":     ( 80,  80,  80),
        "floor":     (134, 239, 172),
        "plant":     ( 22, 101,  52),
        "electronics": (100, 116, 139),
        "goal":      ( 96, 165, 250),
        "start":     (129, 140, 248),
        "hazard":    (251, 146,  60),
        "forbidden": (239,  68,  68),
        "object":    (148, 163, 184),
    }
    _ASSET_THUMBNAIL_VERSION = "mesh_thumb_v4"

    def _get_cached_usd_stage(self, usd_ref: str) -> Any | None:
        """Return a cached opened USD stage, opening it lazily.

        Thread-safe: only ONE thread opens each USD file; others wait on a
        threading.Event until it's ready, preventing duplicate Stage.Open calls
        for the same large binary USD (e.g. 856 MB moorelane).
        """
        # Fast-path: already cached (stage or None for failed open)
        with self._usd_stage_lock:
            entry = self._usd_stage_cache.get(usd_ref, _MISSING := object())
            if entry is not _MISSING:
                if isinstance(entry, threading.Event):
                    event: threading.Event = entry
                else:
                    return entry  # None or real stage
            else:
                # We are the loading thread — store an Event as sentinel
                event = threading.Event()
                self._usd_stage_cache[usd_ref] = event

        if isinstance(entry, threading.Event):
            # Another thread is loading — wait (up to 120 s for large USD files)
            event.wait(timeout=120.0)
            with self._usd_stage_lock:
                result = self._usd_stage_cache.get(usd_ref)
            return result if not isinstance(result, threading.Event) else None

        # This thread opens the stage
        try:
            from pxr import Usd  # type: ignore
            usd_path = resolve_repo_path(self.repo_root, usd_ref)
            stage = Usd.Stage.Open(str(usd_path)) if usd_path.exists() else None
        except Exception:
            stage = None
        with self._usd_stage_lock:
            self._usd_stage_cache[usd_ref] = stage
        event.set()  # wake up all waiting threads
        return stage

    def _render_mesh_to_png(self, vertices_flat: list, indices_flat: list, color: tuple, size: int = 84) -> bytes | None:
        """Software-rasterize a mesh (isometric view, Lambertian shading) to PNG bytes."""
        try:
            import math
            import io
            from PIL import Image, ImageDraw  # type: ignore
            import numpy as np

            verts = np.array(vertices_flat, dtype=np.float32).reshape(-1, 3)
            tris  = np.array(indices_flat,  dtype=np.int32 ).reshape(-1, 3)
            if len(verts) == 0 or len(tris) == 0:
                return None

            # Normalise to [-0.5, 0.5]
            mn, mx = verts.min(axis=0), verts.max(axis=0)
            sc = max((mx - mn).max(), 1e-6)
            verts = (verts - (mn + mx) * 0.5) / sc

            # Isometric rotation: tilt down 28°, then rotate 40° around Y
            ax, ay = math.radians(28), math.radians(40)
            Rx = np.array([[1,0,0],[0,math.cos(ax),-math.sin(ax)],[0,math.sin(ax),math.cos(ax)]])
            Ry = np.array([[math.cos(ay),0,math.sin(ay)],[0,1,0],[-math.sin(ay),0,math.cos(ay)]])
            rot = verts @ (Rx @ Ry).T

            pad = size * 0.10
            inner = size - 2 * pad
            x2d = (rot[:, 0] + 0.5) * inner + pad
            y2d = (-rot[:, 1] + 0.5) * inner + pad
            z2d = rot[:, 2]

            # Face normals
            v0, v1, v2 = rot[tris[:,0]], rot[tris[:,1]], rot[tris[:,2]]
            nrm = np.cross(v1 - v0, v2 - v0)
            nlen = np.linalg.norm(nrm, axis=1, keepdims=True)
            valid = nlen.squeeze() > 1e-10
            nrm[valid] /= nlen[valid]

            light = np.array([-0.4, 0.7, 0.6])
            light /= np.linalg.norm(light)
            diffuse = np.clip(nrm @ light, 0, 1)
            depth = (z2d[tris[:,0]] + z2d[tris[:,1]] + z2d[tris[:,2]]) / 3.0
            order = np.argsort(depth)  # back-to-front

            img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            r0, g0, b0 = color

            for idx in order:
                if not valid[idx]:
                    continue
                lf = 0.35 + 0.65 * float(diffuse[idx])
                rc, gc, bc = int(min(255, r0*lf)), int(min(255, g0*lf)), int(min(255, b0*lf))
                i0, i1, i2 = int(tris[idx,0]), int(tris[idx,1]), int(tris[idx,2])
                pts = [(float(x2d[i0]), float(y2d[i0])),
                       (float(x2d[i1]), float(y2d[i1])),
                       (float(x2d[i2]), float(y2d[i2]))]
                draw.polygon(pts, fill=(rc, gc, bc, 235))

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            return None

    @staticmethod
    def _looks_like_glb_ref(value: Any) -> bool:
        return str(value or "").lower().split("?", 1)[0].endswith((".glb", ".gltf"))

    def _glb_ref_from_asset(self, asset: Mapping[str, Any]) -> str:
        for key in ("glb_ref", "source_ref", "usd_ref"):
            value = str(asset.get(key) or "")
            if self._looks_like_glb_ref(value):
                return value
        return ""

    def _extract_glb_mesh_preview(self, source_ref: str, *, max_triangles: int = 3500) -> dict[str, Any] | None:
        if not self._looks_like_glb_ref(source_ref):
            return None
        try:
            glb_path = resolve_repo_path(self.repo_root, source_ref)
            if not glb_path.exists():
                return None
            result = extract_glb_mesh_for_editor_preview(glb_path, max_triangles=max_triangles)
            if result is None:
                return None
            stat = glb_path.stat()
            mesh_key = {
                "version": "prim_mesh_glb_v1",
                "source_ref": source_ref,
                "source_mtime_ns": stat.st_mtime_ns,
                "source_size": stat.st_size,
                "max_triangles": int(max_triangles),
            }
            return {**result, "source_ref": source_ref, "cache_key": mesh_key}
        except Exception:
            return None

    def _generate_asset_mesh_thumbnail_png(self, asset: Mapping[str, Any], size: int = 84, *, stage: Any = None) -> bytes | None:
        category = str(asset.get("category") or "object")
        color = self._THUMB_COLORS.get(category, (148, 163, 184))
        glb_ref = self._glb_ref_from_asset(asset)
        if glb_ref:
            mesh = self._extract_glb_mesh_preview(glb_ref, max_triangles=3500)
            if mesh and mesh.get("vertices") and mesh.get("indices"):
                return self._render_mesh_to_png(mesh["vertices"], mesh["indices"], color, size)
            return None

        usd_ref = str(asset.get("usd_ref") or "")
        source_path = str(asset.get("source_path") or "")
        if not usd_ref or not source_path:
            return None
        try:
            usd_path = resolve_repo_path(self.repo_root, usd_ref)
            if not usd_path.exists():
                return None
            cached_stage = stage if stage is not None else self._get_cached_usd_stage(usd_ref)
            mesh = extract_prim_mesh_for_editor(
                usd_path,
                source_path,
                max_triangles=3500,
                max_mesh_prims=96,
                stage=cached_stage,
            )
            if mesh and mesh.get("vertices") and mesh.get("indices"):
                return self._render_mesh_to_png(mesh["vertices"], mesh["indices"], color, size)
        except Exception:
            return None
        return None

    def _generate_asset_thumbnail_png(self, asset: Mapping[str, Any], size: int = 84, *, stage: Any = None, skip_usd: bool = False) -> bytes:
        """Generate PNG thumbnail: actual mesh render if USD available, otherwise fallback shape.

        Pass ``skip_usd=True`` to skip USD loading and return the PIL color-rectangle immediately.
        Pass a pre-opened ``stage`` to avoid re-opening large USD files on every call.
        """
        category = str(asset.get("category") or "object")
        color    = self._THUMB_COLORS.get(category, (148, 163, 184))

        if not skip_usd:
            mesh_png = self._generate_asset_mesh_thumbnail_png(asset, size, stage=stage)
            if mesh_png is not None:
                return mesh_png

        # Fallback: plain PIL
        try:
            import io
            from PIL import Image, ImageDraw  # type: ignore
            light = tuple(min(255, c + 40) for c in color)
            dark  = tuple(max(0,   c - 50) for c in color)
            img   = Image.new("RGBA", (size, size), (26, 26, 30, 255))
            draw  = ImageDraw.Draw(img)
            pad   = int(size * 0.15)
            draw.rectangle([pad, pad, size - pad, size - pad], fill=(*color, 210))
            draw.rectangle([pad+1, pad+1, size-pad-1, size-pad-1], outline=(*light, 100), width=1)
            label = str(asset.get("label") or category).rsplit("/", 1)[-1][:8]
            try:
                from PIL import ImageFont  # type: ignore
                font = ImageFont.load_default(size=max(8, size // 9))
                bbox = draw.textbbox((0, 0), label, font=font)
                tx = max(1, (size - (bbox[2] - bbox[0])) // 2)
                ty = size - (bbox[3] - bbox[1]) - 3
                draw.text((tx, ty), label, fill=(220, 220, 220, 220), font=font)
            except Exception:
                pass
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except ImportError:
            return self._generate_asset_thumbnail_fallback(asset, size)

    def _generate_asset_thumbnail_fallback(self, asset: Mapping[str, Any], size: int = 84) -> bytes:
        """Minimal PNG (1x1 colored pixel) when PIL is unavailable."""
        import struct, zlib
        category = str(asset.get("category") or "object")
        r, g, b = self._THUMB_COLORS.get(category, (148, 163, 184))

        def png_chunk(tag: bytes, data: bytes) -> bytes:
            c = zlib.crc32(tag + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", c)

        header = b"\x89PNG\r\n\x1a\n"
        ihdr   = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw    = zlib.compress(bytes([0, r, g, b]))
        idat   = png_chunk(b"IDAT", raw)
        iend   = png_chunk(b"IEND", b"")
        return header + ihdr + idat + iend

    def _opticalnav_asset_thumbnail(self, project_dir: Path, asset_id: str) -> tuple[bytes, str, bool] | None:
        """Return (png_bytes, etag) for the given asset_id, generating and caching if needed.

        Returns a fallback color-rectangle immediately on first request and spawns a background
        thread to render the real mesh thumbnail (cached on disk for subsequent requests).
        """
        thumbs_dir = project_dir / "thumbnails"
        cache_path = thumbs_dir / f"{asset_id}.png"
        meta_path = thumbs_dir / f"{asset_id}.json"

        asset = next((a for a in self._opticalnav_all_asset_library_assets() if a.get("asset_id") == asset_id), None)
        if asset is None:
            return None
        thumb_key = {
            "version": self._ASSET_THUMBNAIL_VERSION,
            "asset_id": asset_id,
            "source_ref": str(asset.get("source_ref") or ""),
            "bounds": asset.get("bounds"),
        }
        etag = hashlib.sha1(json.dumps(thumb_key, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

        # Fast path: cache hit
        if cache_path.exists() and meta_path.exists():
            try:
                meta = _read_json(meta_path)
                if meta.get("thumb_key") == thumb_key and meta.get("render_mode") == "mesh":
                    return cache_path.read_bytes(), etag, True
            except Exception:
                pass

        # GLB thumbnails are cheap enough to build synchronously and should not
        # flash as indistinguishable label boxes in the place catalog. USD assets
        # keep the background path because opening large stages can be expensive.
        if self._glb_ref_from_asset(asset):
            png = self._generate_asset_mesh_thumbnail_png(asset)
            if png is not None:
                try:
                    thumbs_dir.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(png)
                    meta_path.write_text(
                        json.dumps({"thumb_key": thumb_key, "etag": etag, "render_mode": "mesh"}, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                return png, etag, True

        # Not cached yet — return PIL color-rectangle immediately, schedule real render in background
        fallback_png = self._generate_asset_thumbnail_png(asset, skip_usd=True)

        with self._thumb_gen_lock:
            already_pending = asset_id in self._thumb_gen_pending
            if not already_pending:
                self._thumb_gen_pending.add(asset_id)

        if not already_pending:
            def _bg_generate(asset=asset, thumb_key=thumb_key, etag=etag,
                             cache_path=cache_path, meta_path=meta_path, asset_id=asset_id):
                try:
                    usd_ref = str(asset.get("usd_ref") or "")
                    cached_stage = self._get_cached_usd_stage(usd_ref) if usd_ref else None
                    thumbs_dir.mkdir(parents=True, exist_ok=True)
                    png = self._generate_asset_mesh_thumbnail_png(asset, stage=cached_stage)
                    if png is not None:
                        cache_path.write_bytes(png)
                        meta_path.write_text(
                            json.dumps(
                                {"thumb_key": thumb_key, "etag": etag, "render_mode": "mesh"},
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                except Exception:
                    pass
                finally:
                    with self._thumb_gen_lock:
                        self._thumb_gen_pending.discard(asset_id)

            t = threading.Thread(target=_bg_generate, daemon=True)
            t.start()

        return fallback_png, etag, False

    def _asset_id(self, usd_ref: str, source_path: str) -> str:
        digest = hashlib.sha1(f"{usd_ref}#{source_path}".encode("utf-8")).hexdigest()[:12]
        return f"usd_asset_{digest}"

    def _asset_placement_for(self, category: str, label: str, source_path: str) -> str:
        key = f"{category} {label} {source_path}".lower()
        if category in {"shell", "glass", "mirror"} or any(token in key for token in ("wall", "door", "partition", "window")):
            return "line_candidate"
        return "point"

    def _asset_tags_for(self, category: str, label: str, source_path: str) -> list[str]:
        key = f"{category} {label} {source_path}".lower()
        tags = [category] if category else []
        for token in ("chair", "table", "plant", "sofa", "desk", "cabinet", "shelf", "door", "window", "glass", "mirror", "wall", "keyboard", "mouse", "monitor", "printer", "copier", "fire", "lamp", "light"):
            if token in key and token not in tags:
                tags.append(token)
        return tags

    def _asset_default_material_hint(self, category: str) -> str:
        if category == "glass":
            return "curated:glass_clear"
        if category == "mirror":
            return "mirror"
        if category == "floor":
            return "pbrdf_2020:ceramic_alumina"
        if category == "electronics":
            return "pbrdf_2020:black_billiard"
        if category == "lighting":
            return "pbrdf_2020:brass"
        if category == "safety":
            return "pbrdf_2020:red_billiard"
        if category in {"furniture", "plant"}:
            return "pbrdf_2020:peek"
        return "pbrdf_2020:white_billiard"

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "y", "on", "active", "selected", "enable", "enabled"}:
                return True
            if normalized in {"0", "false", "f", "no", "n", "off", "inactive", "unselected", "disable", "disabled", "deactivate", "deactivated"}:
                return False
        return default

    def _asset_is_selected(self, asset: Mapping[str, Any]) -> bool:
        return self._coerce_bool(asset.get("selected"), False)

    _ASSET_READINESS_USABLE = {"texture_ready", "analytic_ok"}

    def _asset_readiness_path(self) -> Path:
        return self._opticalnav_asset_library_dir() / "asset_readiness.json"

    def _load_asset_readiness_index(self) -> dict[str, dict[str, Any]]:
        path = self._asset_readiness_path()
        if not path.exists():
            return {}
        try:
            payload = _read_json(path)
        except Exception:
            return {}
        records: dict[str, dict[str, Any]] = {}
        for raw in payload.get("assets", []) or []:
            if not isinstance(raw, Mapping):
                continue
            rec = dict(raw)
            asset_id = _maybe_str(rec.get("asset_id"))
            source_ref = _maybe_str(rec.get("source_ref"))
            if asset_id:
                records[f"asset:{asset_id}"] = rec
            if source_ref:
                records[f"source:{source_ref}"] = rec
        return records

    def _asset_readiness_record(self, asset: Mapping[str, Any], readiness_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        index = readiness_index if readiness_index is not None else self._load_asset_readiness_index()
        asset_id = _maybe_str(asset.get("asset_id"))
        source_ref = _maybe_str(asset.get("source_ref"))
        rec = (index.get(f"asset:{asset_id}") if asset_id else None) or (index.get(f"source:{source_ref}") if source_ref else None)
        if rec:
            status = str(rec.get("render_readiness") or rec.get("status") or "unknown")
            usable = status in self._ASSET_READINESS_USABLE and self._coerce_bool(rec.get("usable_by_agent"), True)
            return {**rec, "render_readiness": status, "usable_by_agent": usable}
        return {
            "asset_id": asset_id,
            "source_ref": source_ref,
            "render_readiness": "unknown",
            "usable_by_agent": False,
            "reason": "asset_readiness_not_audited",
        }

    def _asset_is_usable_for_render(self, asset: Mapping[str, Any], readiness_index: dict[str, dict[str, Any]] | None = None) -> bool:
        return bool(self._asset_readiness_record(asset, readiness_index).get("usable_by_agent"))

    def _asset_agent_guidance(self, readiness: Mapping[str, Any]) -> str:
        status = str(readiness.get("render_readiness") or "unknown")
        if status == "texture_ready":
            return "Preferred: mesh is verified and base texture reaches measured pBRDF albedo_scale."
        if status == "analytic_ok":
            return "Allowed: analytic glass/metal material is the intended render strategy."
        if status == "partial":
            return "Do not use for scene generation by default: mesh exists but bitmap texture modulation is incomplete."
        if status == "blocked":
            return "Do not use: mesh/materialization failed or source is missing."
        return "Do not use by default: render readiness has not been audited."

    def _asset_payload_with_readiness(self, asset: Mapping[str, Any], readiness_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        readiness = self._asset_readiness_record(asset, readiness_index)
        return {
            **dict(asset),
            "render_readiness": readiness.get("render_readiness"),
            "readiness_reason": readiness.get("reason"),
            "usable_by_agent": bool(readiness.get("usable_by_agent")),
            "readiness": readiness,
        }

    def _find_asset_for_agent_request(self, req: Mapping[str, Any]) -> dict[str, Any] | None:
        asset_id = _maybe_str(req.get("asset_id"))
        source_ref = _maybe_str(req.get("source_ref") or req.get("asset_source_ref"))
        if not asset_id and not source_ref:
            return None
        readiness_index = self._load_asset_readiness_index()
        for asset in self._opticalnav_all_asset_library_assets():
            if asset_id and str(asset.get("asset_id") or "") != asset_id:
                continue
            if source_ref and str(asset.get("source_ref") or "") != source_ref:
                continue
            enriched = self._asset_payload_with_readiness(asset, readiness_index)
            if not self._asset_is_selected(enriched):
                raise ValueError(f"Asset {asset_id or source_ref} is not active in the Asset Library.")
            if not enriched.get("usable_by_agent"):
                raise ValueError(
                    f"Asset {asset_id or source_ref} is not usable for agent scene generation "
                    f"({enriched.get('render_readiness')}: {enriched.get('readiness_reason')})."
                )
            return enriched
        raise ValueError(f"Unknown asset for agent object request: {asset_id or source_ref}")

    def _read_asset_selection_store(self) -> dict[str, Any]:
        path = self._opticalnav_asset_library_dir() / "selected_assets.json"
        if not path.exists():
            return {"assets": {}}
        try:
            payload = _read_json(path)
            if isinstance(payload.get("assets"), Mapping):
                return {"assets": dict(payload["assets"])}
        except Exception:
            pass
        return {"assets": {}}

    def _write_asset_selection_store(self, payload: Mapping[str, Any]) -> Path:
        path = self._opticalnav_asset_library_dir() / "selected_assets.json"
        path.write_text(json.dumps({"assets": dict(payload.get("assets", {}))}, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _asset_catalog_path(self, usd_ref: str) -> Path:
        return self._opticalnav_asset_library_dir() / "catalogs" / f"{self._asset_source_hash(usd_ref)}.json"

    _USD_ASSET_CATALOG_VERSION = "usd_assembly_assets_v3"
    _CURATED_ASSET_CATALOG_VERSION = "curated_usd_assets_v1"
    _DTC_ASSET_CATALOG_VERSION = "dtc_glb_asset_v2"

    def _asset_source_status(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        usd_ref = str(candidate.get("usd_ref") or "")
        source_hash = self._asset_source_hash(usd_ref)
        catalog_path = self._asset_catalog_path(usd_ref)
        status = "not_imported"
        asset_count = 0
        catalog_ref = None
        stale = False
        if catalog_path.exists():
            try:
                catalog = _read_json(catalog_path)
                asset_count = len(catalog.get("assets", []) or [])
                expected_version = (
                    self._DTC_ASSET_CATALOG_VERSION
                    if str(candidate.get("source_type") or "") == "dtc_glb_object"
                    else self._CURATED_ASSET_CATALOG_VERSION
                    if candidate.get("curated_manifest_ref")
                    else self._USD_ASSET_CATALOG_VERSION
                )
                stale = (
                    catalog.get("catalog_version") != expected_version
                    or int(catalog.get("source_mtime_ns", -1)) != int(candidate.get("mtime_ns", -2))
                    or int(catalog.get("source_size", -1)) != int(candidate.get("size_bytes", -2))
                )
                status = "stale" if stale else "imported"
                catalog_ref = catalog_path.relative_to(self.repo_root).as_posix()
            except Exception:
                status = "failed"
        return {
            **dict(candidate),
            "source_hash": source_hash,
            "import_status": status,
            "stale": stale,
            "asset_count": asset_count,
            "catalog_ref": catalog_ref,
        }

    def _opticalnav_asset_sources(self) -> list[dict[str, Any]]:
        curated_by_source = {
            str(manifest.get("source_usd") or ""): manifest
            for manifest in self._opticalnav_curated_asset_manifests()
        }
        sources = [
            self._asset_source_status({
                **candidate,
                "source_type": "curated_usd_scene" if candidate.get("usd_ref") in curated_by_source else candidate.get("source_type"),
                "curated_manifest_ref": curated_by_source.get(str(candidate.get("usd_ref") or ""), {}).get("_manifest_ref"),
                "curated_asset_count": len(curated_by_source.get(str(candidate.get("usd_ref") or ""), {}).get("assets", []) or []),
            })
            for candidate in [*self._opticalnav_usd_candidates(), *self._opticalnav_dtc_object_candidates()]
        ]
        return sorted(
            sources,
            key=lambda item: (
                0 if item.get("source_type") == "dtc_glb_object" else 1,
                0 if item.get("import_status") in {"imported", "stale"} else 1,
                str(item.get("label") or item.get("usd_ref") or ""),
            ),
        )

    def _dtc_license_ref(self, object_dir: Path) -> str | None:
        for name in ("CC_BY-SA.txt", "LICENSE", "license.txt", "License.txt"):
            path = object_dir / name
            if path.exists():
                try:
                    return path.relative_to(self.repo_root).as_posix()
                except ValueError:
                    return None
        return None

    def _metadata_value(self, metadata: Any, keys: set[str]) -> Any:
        if isinstance(metadata, Mapping):
            for key, value in metadata.items():
                if str(key).lower() in keys:
                    return value
            for value in metadata.values():
                found = self._metadata_value(value, keys)
                if found is not None:
                    return found
        elif isinstance(metadata, list):
            for value in metadata:
                found = self._metadata_value(value, keys)
                if found is not None:
                    return found
        return None

    def _dtc_metadata_label(self, metadata: Mapping[str, Any], fallback: str) -> str:
        value = self._metadata_value(metadata, {"name", "object_name", "instance_name", "label", "title"})
        if value:
            return str(value)
        return fallback.replace("_", " ").replace("-", " ").strip() or "DTC object"

    def _dtc_metadata_category(self, metadata: Mapping[str, Any], label: str) -> str:
        value = self._metadata_value(metadata, {"category", "class", "object_class", "semantic_category", "super_category"})
        if value:
            return str(value).lower().replace(" ", "_")
        key = label.lower()
        for category, tokens in {
            "furniture": ("chair", "table", "desk", "sofa", "stool", "cabinet", "shelf"),
            "electronics": ("camera", "phone", "laptop", "keyboard", "remote", "mouse", "monitor", "screen", "computer", "speaker", "calculator"),
            "safety": ("fire", "extinguisher", "alarm"),
            "lighting": ("lamp", "light", "fixture", "chandelier", "led"),
            "kitchenware": ("cup", "bowl", "plate", "mug", "pan", "pot", "bottle"),
            "plant": ("plant", "vase"),
            "object": (),
        }.items():
            if any(token in key for token in tokens):
                return category
        return "object"

    def _dtc_metadata_material(self, metadata: Mapping[str, Any]) -> str | None:
        value = self._metadata_value(metadata, {"material", "materials", "material_hint", "composition"})
        if isinstance(value, list):
            return ", ".join(str(item) for item in value[:4])
        if value:
            return str(value)
        return None

    def _dtc_metadata_dimensions(self, metadata: Mapping[str, Any]) -> list[float] | None:
        value = self._metadata_value(metadata, {"dimensions_m", "dimensions", "size_m", "size", "bbox_size", "bounding_box_size"})
        if isinstance(value, Mapping):
            raw = [value.get(key) for key in ("x", "y", "z")]
            if any(item is None for item in raw):
                raw = [value.get(key) for key in ("width", "height", "depth")]
            value = raw
        if isinstance(value, list) and len(value) >= 3:
            try:
                dims = [abs(float(value[0])), abs(float(value[1])), abs(float(value[2]))]
                if all(dim > 0 for dim in dims):
                    return [round(dim, 4) for dim in dims]
            except Exception:
                return None
        return None

    def _dtc_metadata_description(self, metadata: Mapping[str, Any], label: str, category: str, material: str | None, dims: list[float] | None) -> str:
        value = self._metadata_value(metadata, {"description", "caption", "summary"})
        if value:
            return str(value)
        dim_text = f"{dims[0]:.2f}m x {dims[1]:.2f}m x {dims[2]:.2f}m" if dims else "unknown size"
        material_text = material or "metadata material unknown"
        return (
            f"{label} is a Digital Twin Catalog scanned GLB object for OpticalNav placement. "
            f"It is categorized as {category}, uses {material_text}, and has approximate bounds {dim_text}. "
            "Use it as a high-quality rendering asset; the original GLB is referenced read-only."
        )

    def _opticalnav_import_dtc_glb_source(self, source_ref: str, *, force: bool = False) -> dict[str, Any]:
        glb_path = resolve_repo_path(self.repo_root, source_ref)
        if not glb_path.exists():
            return {
                "status": "unavailable",
                "reason": f"DTC GLB ref does not exist: {source_ref}",
                "usd_ref": source_ref,
                "source_hash": self._asset_source_hash(source_ref),
                "assets": [],
            }
        metadata_path = glb_path.parent / "metadata.json"
        metadata = _read_json(metadata_path) if metadata_path.exists() else {}
        stat = glb_path.stat()
        catalog_path = self._asset_catalog_path(source_ref)
        source_hash = self._asset_source_hash(source_ref)
        if catalog_path.exists() and not force:
            cached = _read_json(catalog_path)
            if (
                cached.get("catalog_version") == self._DTC_ASSET_CATALOG_VERSION
                and int(cached.get("source_mtime_ns", -1)) == stat.st_mtime_ns
                and int(cached.get("source_size", -1)) == stat.st_size
            ):
                cached["cached"] = True
                return cached

        label = self._dtc_metadata_label(metadata, glb_path.parent.name)
        category = self._dtc_metadata_category(metadata, label)
        material = self._dtc_metadata_material(metadata)
        dims = self._dtc_metadata_dimensions(metadata) or [0.5, 0.5, 0.5]
        bounds = {
            "min": [round(-dims[0] / 2, 4), 0.0, round(-dims[2] / 2, 4)],
            "max": [round(dims[0] / 2, 4), round(dims[1], 4), round(dims[2] / 2, 4)],
            "size": dims,
        }
        asset_id = f"dtc_asset_{self._asset_source_hash(source_ref)[:12]}"
        tags = sorted(set(["dtc", "glb", category, *self._asset_tags_for(category, label, source_ref)]))
        asset = {
            "asset_id": asset_id,
            "usd_ref": source_ref,
            "glb_ref": source_ref,
            "source_format": "glb",
            "source_dataset": "DigitalTwinCatalog",
            "source_type": "dtc_glb_object",
            "source_path": f"/DigitalTwinCatalog/{glb_path.parent.name}",
            "source_ref": source_ref,
            "metadata_ref": metadata_path.relative_to(self.repo_root).as_posix() if metadata_path.exists() else None,
            "license_ref": self._dtc_license_ref(glb_path.parent),
            "label": label,
            "category": category,
            "material_hint": material,
            "bounds": bounds,
            "proxy": {"type": "glb", "glb_ref": source_ref, "fallback": "box"},
            "placement": "point",
            "tags": tags,
            "selected": True,
            "description": self._dtc_metadata_description(metadata, label, category, material, dims),
        }
        selections = self._read_asset_selection_store().get("assets", {})
        asset = self._merge_asset_selection(asset, selections)
        payload = {
            "status": "ready",
            "usd_ref": source_ref,
            "source_ref": source_ref,
            "source_type": "dtc_glb_object",
            "source_hash": source_hash,
            "catalog_version": self._DTC_ASSET_CATALOG_VERSION,
            "source_mtime_ns": stat.st_mtime_ns,
            "source_size": stat.st_size,
            "extractor": {"runtime": "daemon_python", "format": "glb_pbr_adapter", "metadata_available": metadata_path.exists()},
            "bounds": bounds,
            "asset_count": 1,
            "assets": [asset],
            "cached": False,
        }
        catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _asset_payload_from_proxy(self, usd_ref: str, proxy: Mapping[str, Any]) -> dict[str, Any]:
        source_path = str(proxy.get("source_path") or proxy.get("id") or "")
        label = str(proxy.get("label") or source_path.rsplit("/", 1)[-1] or proxy.get("id") or "USD asset")
        category = str(proxy.get("category") or "object")
        return {
            "asset_id": self._asset_id(usd_ref, source_path),
            "usd_ref": usd_ref,
            "source_path": source_path,
            "source_ref": f"{usd_ref}#{source_path}",
            "label": label,
            "category": category,
            "material_hint": proxy.get("material_hint"),
            "bounds": proxy.get("bounds"),
            "proxy": proxy.get("proxy") or {"type": "box"},
            "placement": self._asset_placement_for(category, label, source_path),
            "tags": self._asset_tags_for(category, label, source_path),
            "selected": False,
        }

    def _asset_payload_from_curated(self, usd_ref: str, item: Mapping[str, Any], manifest_ref: str | None) -> dict[str, Any]:
        source_path = str(item.get("source_path") or "")
        label = str(item.get("label") or source_path.rsplit("/", 1)[-1] or item.get("asset_id") or "Curated asset")
        category = str(item.get("category") or "object")
        asset_id = str(item.get("asset_id") or self._asset_id(usd_ref, source_path))
        bounds = item.get("bounds") if isinstance(item.get("bounds"), Mapping) else {"size": [0.5, 0.5, 0.5]}
        if isinstance(bounds, Mapping) and "size" in bounds and "min" not in bounds and "max" not in bounds:
            try:
                sx, sy, sz = [float(v) for v in list(bounds.get("size") or [])[:3]]
                bounds = {
                    **dict(bounds),
                    "min": [round(-sx / 2, 4), 0.0, round(-sz / 2, 4)],
                    "max": [round(sx / 2, 4), round(sy, 4), round(sz / 2, 4)],
                    "center": [0.0, round(sy / 2, 4), 0.0],
                }
            except Exception:
                bounds = dict(bounds)
        return {
            "asset_id": asset_id,
            "usd_ref": usd_ref,
            "source_path": source_path,
            "source_ref": f"{usd_ref}#{source_path}",
            "source_type": "curated_usd_asset",
            "source_dataset": "MooreLane",
            "curated_manifest_ref": manifest_ref,
            "label": label,
            "category": category,
            "material_hint": item.get("material_hint") or self._asset_default_material_hint(category),
            "bounds": bounds,
            "proxy": {"type": "usd_prim", "curated": True},
            "placement": str(item.get("placement") or self._asset_placement_for(category, label, source_path)),
            "tags": [str(tag) for tag in item.get("tags", []) or self._asset_tags_for(category, label, source_path)],
            "selected": self._coerce_bool(item.get("selected", item.get("use", True)), True),
            "description": item.get("description"),
        }

    def _merge_asset_selection(self, asset: Mapping[str, Any], selections: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(asset)
        override = selections.get(str(asset.get("asset_id"))) if isinstance(selections, Mapping) else None
        if isinstance(override, Mapping):
            for key in ("label", "category", "placement", "tags", "description", "activation_reason"):
                if key in override:
                    merged[key] = override[key]
            if "selected" in override:
                merged["selected"] = self._coerce_bool(override["selected"], False)
        return merged

    def _opticalnav_import_asset_library_source(self, usd_ref: str, *, force: bool = False) -> dict[str, Any]:
        usd_path = resolve_repo_path(self.repo_root, usd_ref)
        if not usd_path.exists():
            return {
                "status": "unavailable",
                "reason": f"USD ref does not exist: {usd_ref}",
                "usd_ref": usd_ref,
                "source_hash": self._asset_source_hash(usd_ref),
                "assets": [],
            }
        stat = usd_path.stat()
        catalog_path = self._asset_catalog_path(usd_ref)
        source_hash = self._asset_source_hash(usd_ref)
        curated_manifest = self._opticalnav_curated_manifest_for_source(usd_ref)
        catalog_version = self._CURATED_ASSET_CATALOG_VERSION if curated_manifest else self._USD_ASSET_CATALOG_VERSION
        if catalog_path.exists() and not force:
            cached = _read_json(catalog_path)
            if (
                cached.get("catalog_version") == catalog_version
                and int(cached.get("source_mtime_ns", -1)) == stat.st_mtime_ns
                and int(cached.get("source_size", -1)) == stat.st_size
            ):
                cached["cached"] = True
                return cached
        geometry: dict[str, Any] = {}
        if curated_manifest:
            manifest_ref = _maybe_str(curated_manifest.get("_manifest_ref"))
            assets = [
                self._asset_payload_from_curated(usd_ref, item, manifest_ref)
                for item in curated_manifest.get("assets", []) or []
                if isinstance(item, Mapping) and item.get("source_path")
            ]
            geometry = {
                "extractor": {
                    "runtime": "curated_manifest",
                    "manifest_ref": manifest_ref,
                    "manifest_version": curated_manifest.get("manifest_version"),
                    "rejected_patterns": curated_manifest.get("rejected_patterns", []),
                },
                "bounds": None,
            }
        else:
            geometry = build_usd_editor_geometry(usd_path, scene_id=source_hash, repo_root=self.repo_root, usd_ref=usd_ref)
            assets = [self._asset_payload_from_proxy(usd_ref, item) for item in geometry.get("objects", []) or []]
        selections = self._read_asset_selection_store().get("assets", {})
        assets = [self._merge_asset_selection(asset, selections) for asset in assets]
        payload = {
            "status": "ready",
            "usd_ref": usd_ref,
            "source_hash": source_hash,
            "source_type": "curated_usd_scene" if curated_manifest else "usd_scene",
            "catalog_version": catalog_version,
            "source_mtime_ns": stat.st_mtime_ns,
            "source_size": stat.st_size,
            "extractor": geometry.get("extractor") or self._opticalnav_usd_extractor_status(),
            "bounds": geometry.get("bounds"),
            "asset_count": len(assets),
            "assets": assets,
            "curated": bool(curated_manifest),
            "cached": False,
        }
        catalog_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def _ensure_dtc_asset_catalogs(self) -> None:
        for candidate in self._opticalnav_dtc_object_candidates():
            source_ref = _maybe_str(candidate.get("source_ref") or candidate.get("usd_ref"))
            if not source_ref:
                continue
            try:
                status = self._asset_source_status(candidate)
                if status.get("import_status") in {"not_imported", "stale", "failed"}:
                    self._opticalnav_import_dtc_glb_source(source_ref, force=bool(status.get("stale")))
            except Exception:
                continue

    def _opticalnav_all_asset_library_assets(self) -> list[dict[str, Any]]:
        self._ensure_dtc_asset_catalogs()
        selections = self._read_asset_selection_store().get("assets", {})
        assets: list[dict[str, Any]] = []
        for path in sorted((self._opticalnav_asset_library_dir() / "catalogs").glob("*.json")):
            try:
                catalog = _read_json(path)
            except Exception:
                continue
            for asset in catalog.get("assets", []) or []:
                if isinstance(asset, Mapping):
                    assets.append(self._merge_asset_selection(asset, selections))
        return assets

    def _opticalnav_update_asset_library_asset(self, asset_id: str, update: Mapping[str, Any]) -> dict[str, Any] | None:
        current = next((asset for asset in self._opticalnav_all_asset_library_assets() if asset.get("asset_id") == asset_id), None)
        if current is None:
            return None
        store = self._read_asset_selection_store()
        assets = dict(store.get("assets", {}))
        merged = dict(assets.get(asset_id, {}))
        for key in ("label", "category", "placement", "tags"):
            if key in update:
                merged[key] = update[key]
        if "selected" in update:
            merged["selected"] = self._coerce_bool(update["selected"], False)
        if "active" in update:
            merged["selected"] = self._coerce_bool(update["active"], False)
        for key in ("description", "activation_reason"):
            if key in update:
                merged[key] = update[key]
        assets[asset_id] = merged
        self._write_asset_selection_store({"assets": assets})
        return self._merge_asset_selection(current, assets)

    def _asset_dimensions_m(self, asset: Mapping[str, Any]) -> list[float] | None:
        bounds = asset.get("bounds")
        if not isinstance(bounds, Mapping):
            return None
        size = bounds.get("size")
        if not isinstance(size, list) or len(size) < 3:
            return None
        try:
            return [round(float(size[0]), 4), round(float(size[1]), 4), round(float(size[2]), 4)]
        except Exception:
            return None

    def _asset_natural_description(self, asset: Mapping[str, Any]) -> str:
        if asset.get("description"):
            return str(asset["description"])
        title = str(asset.get("label") or "USD asset")
        category = str(asset.get("category") or "object")
        material = str(asset.get("material_hint") or "unknown material")
        placement = str(asset.get("placement") or "point")
        tags = [str(tag) for tag in asset.get("tags", []) or []]
        dims = self._asset_dimensions_m(asset)
        dim_text = f"{dims[0]:.2f}m x {dims[1]:.2f}m x {dims[2]:.2f}m" if dims else "unknown size"
        source_path = str(asset.get("source_path") or "")
        name_hint = " ".join(source_path.replace("_", " ").replace("/", " ").split())
        return (
            f"{title} is a USD-derived {category} asset for OpticalNav map placement. "
            f"It uses material hint '{material}', has approximate bounds {dim_text}, "
            f"and is intended for {placement} placement. "
            f"Recognition hints: {', '.join(tags) if tags else name_hint or 'none'}."
        )

    def _agent_asset_payload(self, asset: Mapping[str, Any], readiness_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        dims = self._asset_dimensions_m(asset)
        active = self._asset_is_selected(asset)
        enriched = self._asset_payload_with_readiness(asset, readiness_index)
        readiness = enriched.get("readiness") if isinstance(enriched.get("readiness"), Mapping) else {}
        guidance = self._asset_agent_guidance(readiness)
        return {
            "asset_id": asset.get("asset_id"),
            "title": asset.get("label"),
            "description": self._asset_natural_description(asset),
            "category": asset.get("category"),
            "material": asset.get("material_hint"),
            "dimensions_m": dims,
            "placement": asset.get("placement"),
            "active": active,
            "selected": active,
            "tags": asset.get("tags", []),
            "source_ref": asset.get("source_ref"),
            "usd_ref": asset.get("usd_ref"),
            "source_path": asset.get("source_path"),
            "source_type": asset.get("source_type"),
            "source_dataset": asset.get("source_dataset"),
            "source_format": asset.get("source_format"),
            "bounds": asset.get("bounds"),
            "activation_reason": asset.get("activation_reason"),
            "render_readiness": enriched.get("render_readiness"),
            "readiness_reason": enriched.get("readiness_reason"),
            "usable_by_agent": bool(enriched.get("usable_by_agent")),
            "agent_guidance": guidance,
            "readiness": readiness,
            "llm_hints": {
                "recognition_text": " ".join([
                    str(asset.get("label") or ""),
                    str(asset.get("category") or ""),
                    str(asset.get("material_hint") or ""),
                    str(asset.get("source_path") or "").replace("/", " "),
                    " ".join(str(tag) for tag in asset.get("tags", []) or []),
                    str(enriched.get("render_readiness") or ""),
                ]).strip(),
                "map_editor_effect": "If active and usable_by_agent is true, this asset appears in /datasets Place Catalog and can be placed into authoring_map.json as source_ref + transform.",
                "asset_selection_rule": "Use only texture_ready or analytic_ok assets for scene generation. Do not use primitive proxies unless explicitly debugging.",
            },
        }

    def _asset_library_ui_payload(self, asset: Mapping[str, Any], readiness_index: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        enriched = self._asset_payload_with_readiness(asset, readiness_index)
        return {
            **enriched,
            "description": self._asset_natural_description(asset),
            "dimensions_m": self._asset_dimensions_m(asset),
            "agent_guidance": self._asset_agent_guidance(enriched.get("readiness") or {}),
        }

    def _filter_agent_assets(self, query: Mapping[str, list[str]]) -> list[dict[str, Any]]:
        assets = self._opticalnav_all_asset_library_assets()
        q = _maybe_str((query.get("q") or [None])[0])
        category = _maybe_str((query.get("category") or [None])[0])
        active_raw = _maybe_str((query.get("active") or query.get("selected") or [None])[0])
        include_unready = self._coerce_bool((query.get("include_unready") or [None])[0], False)
        readiness_index = self._load_asset_readiness_index()
        payloads = [self._agent_asset_payload(asset, readiness_index) for asset in assets]
        if not include_unready:
            payloads = [asset for asset in payloads if bool(asset.get("usable_by_agent"))]
        if q:
            needle = q.lower()
            payloads = [asset for asset in payloads if needle in asset["llm_hints"]["recognition_text"].lower()]
        if category and category != "all":
            payloads = [asset for asset in payloads if str(asset.get("category") or "") == category]
        if active_raw is not None:
            want_active = self._coerce_bool(active_raw, False)
            payloads = [asset for asset in payloads if self._coerce_bool(asset.get("active"), False) == want_active]
        return payloads

    def _opticalnav_apply_agent_asset_activation(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        decisions: list[dict[str, Any]] = []
        for asset_id in payload.get("activate", []) or []:
            decisions.append({"asset_id": str(asset_id), "active": True})
        for asset_id in payload.get("deactivate", []) or []:
            decisions.append({"asset_id": str(asset_id), "active": False})
        for item in payload.get("decisions", []) or []:
            if isinstance(item, Mapping):
                decisions.append(dict(item))
        if self._coerce_bool(payload.get("replace"), False):
            activate_ids = {
                str(item.get("asset_id"))
                for item in decisions
                if self._coerce_bool(item.get("active", item.get("selected")), False)
            }
            for asset in self._opticalnav_all_asset_library_assets():
                asset_id = str(asset.get("asset_id"))
                if asset_id and asset_id not in activate_ids:
                    decisions.append({"asset_id": asset_id, "active": False})
        updated = []
        missing = []
        for item in decisions:
            asset_id = str(item.get("asset_id") or "")
            if not asset_id:
                continue
            active = self._coerce_bool(item.get("active", item.get("selected")), False)
            update = {"selected": active}
            if item.get("reason"):
                update["activation_reason"] = str(item["reason"])
            result = self._opticalnav_update_asset_library_asset(asset_id, update)
            if result is None:
                missing.append(asset_id)
            else:
                updated.append(self._agent_asset_payload(result))
        return {
            "ok": not missing,
            "updated": updated,
            "missing_asset_ids": missing,
            "active_count": sum(1 for asset in self._opticalnav_all_asset_library_assets() if self._asset_is_selected(asset)),
        }

    def _opticalnav_set_scene_usd_ref(self, project_dir: Path, scene_id: str, usd_ref: str | None) -> dict[str, Any]:
        from navigation_dataset.episode_schema import read_project, write_project

        scene_dir = project_dir / "scenes" / scene_id
        if not scene_dir.exists():
            raise KeyError(scene_id)
        if usd_ref:
            resolve_repo_path(self.repo_root, usd_ref)

        annotation_path = scene_dir / "scene_annotation.json"
        if annotation_path.exists():
            annotation = _read_json(annotation_path)
        else:
            annotation = self._opticalnav_starter_annotation(scene_id, usd_ref)
        annotation["usd_ref"] = usd_ref
        annotation_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")

        dataset_path = project_dir / "dataset.json"
        if dataset_path.exists():
            project = read_project(dataset_path)
            scenes: list[Any] = []
            updated = False
            for item in project.scenes:
                if isinstance(item, Mapping) and item.get("scene_id") == scene_id:
                    scenes.append({
                        **dict(item),
                        "scene_id": scene_id,
                        "usd_ref": usd_ref,
                        "annotation_ref": f"scenes/{scene_id}/scene_annotation.json",
                    })
                    updated = True
                elif item == scene_id:
                    scenes.append({"scene_id": scene_id, "usd_ref": usd_ref, "annotation_ref": f"scenes/{scene_id}/scene_annotation.json"})
                    updated = True
                else:
                    scenes.append(item)
            if not updated:
                scenes.append({"scene_id": scene_id, "usd_ref": usd_ref, "annotation_ref": f"scenes/{scene_id}/scene_annotation.json"})
            project.scenes = scenes
            write_project(dataset_path, project)

        cache_path = scene_dir / "editor_geometry.json"
        if cache_path.exists():
            cache_path.unlink()
        return {"scene_id": scene_id, "usd_ref": usd_ref, "annotation": _read_json(annotation_path)}

    def _opticalnav_unavailable_editor_geometry(self, scene_id: str, reason: str, *, usd_ref: str | None = None) -> dict[str, Any]:
        return {
            "scene_id": scene_id,
            "status": "unavailable",
            "reason": reason,
            "usd_ref": usd_ref,
            "extractor": self._opticalnav_usd_extractor_status(),
            "coordinate_system": "world_xz_authoring",
            "bounds": {"min": [0.0, 0.0, 0.0], "max": [6.0, 0.1, 4.0], "size": [6.0, 0.1, 4.0], "center": [3.0, 0.05, 2.0]},
            "objects": [],
            "floor_planes": [
                {
                    "id": "floor_fallback",
                    "bounds": {"min": [0.0, 0.0, 0.0], "max": [6.0, 0.05, 4.0], "size": [6.0, 0.05, 4.0], "center": [3.0, 0.025, 2.0]},
                }
            ],
        }

    def _opticalnav_editor_geometry(self, project_dir: Path, scene_id: str, *, force_refresh: bool = False) -> dict[str, Any]:
        scene_dir = project_dir / "scenes" / scene_id
        if not scene_dir.exists():
            raise KeyError(scene_id)
        usd_ref = self._opticalnav_scene_usd_ref(project_dir, scene_id)
        if not usd_ref:
            return self._opticalnav_unavailable_editor_geometry(scene_id, "usd_ref missing for scene.", usd_ref=None)
        try:
            usd_path = resolve_repo_path(self.repo_root, usd_ref)
        except Exception as exc:
            return self._opticalnav_unavailable_editor_geometry(scene_id, f"USD ref could not be resolved: {exc}", usd_ref=usd_ref)
        if not usd_path.exists():
            return self._opticalnav_unavailable_editor_geometry(scene_id, f"USD ref does not exist: {usd_ref}", usd_ref=usd_ref)

        stat = usd_path.stat()
        cache_key = {
            "editor_geometry_version": "usd_bbox_assembly_proxy_v3",
            "usd_ref": usd_ref,
            "usd_mtime_ns": stat.st_mtime_ns,
            "usd_size": stat.st_size,
        }
        cache_path = scene_dir / "editor_geometry.json"
        cached_payload = None
        if cache_path.exists() and not force_refresh:
            try:
                cached = _read_json(cache_path)
                cached_payload = cached
                if cached.get("cache_key") == cache_key:
                    cached["cached"] = True
                    cached["extractor"] = cached.get("extractor") or self._opticalnav_usd_extractor_status()
                    return cached
            except Exception:
                pass
        try:
            payload = build_usd_editor_geometry(usd_path, scene_id=scene_id, repo_root=self.repo_root, usd_ref=usd_ref)
            payload["cache_key"] = cache_key
            payload["cached"] = False
            payload["extractor"] = self._opticalnav_usd_extractor_status()
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload
        except Exception as exc:
            if isinstance(cached_payload, dict):
                cached_payload["cached"] = True
                cached_payload["cache_stale"] = True
                cached_payload["status"] = cached_payload.get("status") or "ready"
                cached_payload["warning"] = f"Using stale cached USD proxy geometry because extraction failed: {exc}"
                cached_payload["extractor"] = cached_payload.get("extractor") or self._opticalnav_usd_extractor_status()
                return cached_payload
            return self._opticalnav_unavailable_editor_geometry(scene_id, f"USD geometry unavailable: {exc}", usd_ref=usd_ref)

    def _opticalnav_episode_summary(self, project_dir: Path, episode_path: Path) -> dict[str, Any]:
        from navigation_dataset.episode_schema import read_episode
        from navigation_dataset.exporters.custom_json import is_episode_complete

        episode = read_episode(episode_path)
        # Disk-based check — episode.timesteps[i].observation_bundle_ref is
        # populated at episode-creation time only, so the previous heuristic
        # marked everything as "planned" once the user rendered via the daemon
        # batch path (which doesn't back-write to episode JSON).
        complete = is_episode_complete(episode, project_dir)
        # Per-step rendered count from the consolidated observations dir so the
        # UI can show partial-progress hints alongside the boolean flag.
        rendered_steps = 0
        if episode.path_nodes and episode.path_headings and len(episode.path_nodes) == len(episode.path_headings):
            obs_root = project_dir / "scenes" / str(episode.scene_id) / "observations"
            for node_id, heading_id in zip(episode.path_nodes, episode.path_headings):
                if (obs_root / str(node_id) / str(heading_id)).is_dir():
                    rendered_steps += 1
        return {
            "episode_id": episode.episode_id,
            "scene_id": episode.scene_id,
            "split": episode.split,
            "navigation_mode": episode.navigation_mode,
            "status": "rendered" if complete else "planned",
            "timestep_count": len(episode.timesteps),
            "path_node_count": len(episode.path_nodes),
            "rendered_step_count": rendered_steps,
            "hazard_collision": any(step.hazard_collision for step in episode.timesteps),
            "observation_complete": complete,
            "path": episode_path.relative_to(project_dir).as_posix(),
        }

    def _strict_catalog_match(self, project_dir: Path, scene_id: str) -> "dict[str, Any] | None":
        annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
        if not annotation_path.exists():
            return None
        usd_ref = _maybe_str(_read_json(annotation_path).get("usd_ref"))
        # Fallback: editor_geometry.json carries the USD path when scene_annotation.usd_ref is unset
        # (scenes imported from Isaac USD via the editor geometry pipeline).
        if not usd_ref:
            eg_path = project_dir / "scenes" / scene_id / "editor_geometry.json"
            if eg_path.exists():
                try:
                    usd_ref = _maybe_str(_read_json(eg_path).get("usd_ref"))
                except Exception:
                    pass
        if not usd_ref:
            return None
        catalog_path = self.repo_root / "out" / "control_plane_cache" / "isaac_scene_catalog.json"
        if not catalog_path.exists():
            return None
        for entry in _read_json(catalog_path).get("scenes", {}).values():
            stage_path = str(entry.get("usd_stage_path") or "").replace("\\", "/").lower()
            if any(seg.lower() in stage_path for seg in usd_ref.replace("\\", "/").split("/") if len(seg) > 8):
                return dict(entry)
        return None

    def _opticalnav_derive_render_config(self, project_dir: Path, scene_id: str) -> dict[str, Any]:
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.5, 0.0, 1.0]
        camera_spec = {
            "camera_id": "opticalnav_front_cam",
            "name": "OpticalNav Front Camera",
            "camera_to_world": identity,
            "fov_deg": 60.0,
            "resolution": [640, 480],
            "sensor_modality": "multimodal",
            "sensor_sync_group": "default",
            "extras": {},
        }

        def _make_scene_state(xml_ref: str, source: str) -> dict[str, Any]:
            return {
                "ok": True,
                "scene_id": scene_id,
                "source": source,
                "scene_state": {
                    "job_id": f"opticalnav-{scene_id}-template",
                    "scene_id": scene_id,
                    "frame_id": f"{scene_id}_frame_template",
                    "timestamp": _utc_now_iso(),
                    "scene_snapshot_ref": xml_ref,
                    "mitsuba_scene_ref": xml_ref,
                    "extras": {},
                },
                "camera_spec": camera_spec,
            }

        scene_dir = project_dir / "scenes" / scene_id
        authoring_map_path = scene_dir / "authoring_map.json"
        if authoring_map_path.exists():
            try:
                am = _read_json(authoring_map_path)
                rig = dict(am.get("camera_rig") or {})
                rgb_sensor = next((dict(sensor) for sensor in rig.get("sensors") or [] if str(sensor.get("modality") or "").lower() == "rgb"), None)
                # Fall back to camera_rigs directory if authoring_map has no inline RGB sensor.
                if rgb_sensor is None:
                    rig_id = str(rig.get("rig_id") or "ranger_mini_default")
                    _camera_rigs_dir = self.repo_root / "out" / "control_plane_cache" / "camera_rigs"
                    for _candidate in (rig_id, "ranger_mini_default"):
                        _rig_path = _camera_rigs_dir / f"{_candidate}.json"
                        if _rig_path.exists():
                            try:
                                _rig_data = _read_json(_rig_path)
                                _raw = next((s for s in _rig_data.get("sensors") or [] if isinstance(s, Mapping) and s.get("sensor_type") == "rgb_camera" and s.get("enabled", True)), None)
                                if _raw:
                                    _intr = dict(_raw.get("intrinsics") or {})
                                    rgb_sensor = {
                                        "sensor_id": str(_raw.get("sensor_id") or "opticalnav_front_cam"),
                                        "label": str(_raw.get("label") or _raw.get("sensor_id") or "Camera"),
                                        "modality": "rgb",
                                        "fov_deg": float(_intr.get("fov_h_deg") or 70.0),
                                        "resolution": list(_intr.get("resolution") or [640, 480]),
                                        "mount": _raw.get("mount") or {},
                                        "sensor_sync_group": "default",
                                    }
                                    rig["rig_id"] = _rig_data.get("rig_id") or _candidate
                                    break
                            except Exception:
                                pass
                        if rgb_sensor:
                            break
                if rgb_sensor:
                    camera_spec["camera_id"] = str(rgb_sensor.get("sensor_id") or camera_spec["camera_id"])
                    camera_spec["name"] = str(rgb_sensor.get("label") or camera_spec["name"])
                    camera_spec["fov_deg"] = float(rgb_sensor.get("fov_deg") or camera_spec["fov_deg"])
                    if isinstance(rgb_sensor.get("resolution"), list) and len(rgb_sensor["resolution"]) >= 2:
                        camera_spec["resolution"] = [int(rgb_sensor["resolution"][0]), int(rgb_sensor["resolution"][1])]
                    camera_spec["sensor_sync_group"] = str(rgb_sensor.get("sensor_sync_group") or "default")
                    camera_spec["extras"] = {
                        **dict(camera_spec.get("extras") or {}),
                        "robot_mount": rgb_sensor.get("mount") or {},
                        "camera_rig_id": rig.get("rig_id"),
                        "calibration_ref": rgb_sensor.get("calibration_ref"),
                    }
            except Exception:
                pass

        # Priority 1: render_config.json (explicitly saved by user)
        saved_rc = scene_dir / "render_config.json"
        if saved_rc.exists():
            return {**_read_json(saved_rc), "source": "saved"}

        # Priority 2: editor-generated scene_variant.json refs. This is the default
        # UI render path and must win over MooreLane/catalog preview fallback.
        sv_path = scene_dir / "scene_variant.json"
        if sv_path.exists():
            sv = _read_json(sv_path)
            if str(sv.get("render_sync_mode") or "") == "editor_generated_xml":
                ref = _maybe_str(sv.get("overlay_scene_xml_ref"))
                if ref and resolve_repo_path(self.repo_root, ref).exists():
                    state = _make_scene_state(ref, "editor_generated_xml")
                    state["scene_variant"] = sv
                    return state

        # Priority 3: Isaac catalog strict match. This is now legacy/debug fallback;
        # graph sweep itself refuses catalog fallback unless a generated XML exists.
        catalog_entry = self._strict_catalog_match(project_dir, scene_id)
        if catalog_entry is not None:
            mitsuba_scene_ref = _maybe_str(catalog_entry.get("mitsuba_scene_ref"))
            scene_snapshot_ref = _maybe_str(catalog_entry.get("scene_snapshot_ref"))
            if not mitsuba_scene_ref:
                return {"ok": False, "error": "Catalog entry has no mitsuba_scene_ref.", "scene_id": scene_id}
            return {
                "ok": True,
                "scene_id": scene_id,
                "source": "catalog_preview",
                "catalog_scene_id": str(catalog_entry.get("scene_id") or ""),
                "scene_state": {
                    "job_id": f"opticalnav-{scene_id}-template",
                    "scene_id": str(catalog_entry.get("scene_id") or scene_id),
                    "frame_id": f"{scene_id}_frame_template",
                    "timestamp": _utc_now_iso(),
                    "scene_snapshot_ref": scene_snapshot_ref or mitsuba_scene_ref,
                    "mitsuba_scene_ref": mitsuba_scene_ref,
                    "scene_version": _maybe_str(catalog_entry.get("scene_version")),
                    "illumination_setup": _maybe_str(catalog_entry.get("illumination_setup")),
                    "extras": {},
                },
                "camera_spec": camera_spec,
            }

        # Priority 4: legacy scene_variant refs (older non-catalog scenes only).
        sv_path = scene_dir / "scene_variant.json"
        if sv_path.exists():
            sv = _read_json(sv_path)
            for key in ("overlay_scene_xml_ref", "base_scene_xml_ref"):
                ref = _maybe_str(sv.get(key))
                if ref and resolve_repo_path(self.repo_root, ref).exists():
                    return _make_scene_state(ref, "scene_variant")

        # Priority 5: hand-crafted base_scene.xml (non-catalog scenes like cornell_box)
        candidate = scene_dir / "base_scene.xml"
        if candidate.exists():
            try:
                xml_ref = candidate.relative_to(self.repo_root).as_posix()
            except ValueError:
                xml_ref = str(candidate)
            return _make_scene_state(xml_ref, "hand_crafted")

        return {"ok": False, "error": "No scene XML found. Run Sync Render Scene.", "scene_id": scene_id}

    def _opticalnav_render_precondition_payload(
        self,
        project_dir: Path,
        scene_ids: list[str],
        payload: Mapping[str, Any],
        *,
        mode: str,
    ) -> dict[str, Any] | None:
        if bool(payload.get("allow_unsynced_render_scene", False)):
            return None
        missing: list[dict[str, Any]] = []
        for scene_id in sorted(set(scene_ids)):
            annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
            if not annotation_path.exists():
                missing.append({
                    "key": f"{scene_id}.scene_annotation",
                    "label": f"{scene_id} annotation",
                    "reason": "scene_annotation.json is missing.",
                    "action": "compile_authoring_map",
                })
                continue
            sync: dict[str, Any] = {}
            try:
                from navigation_dataset.scene_annotations import read_scene_annotation

                annotation = read_scene_annotation(annotation_path)
                sync = dict(annotation.metadata.get("sync", {}))
            except Exception:
                # Validation may fail for uncommitted scenes (missing goal_regions etc.).
                # Fall back to raw JSON to still read the sync metadata we wrote.
                try:
                    _raw_ann = json.loads(annotation_path.read_text(encoding="utf-8"))
                    sync = dict(_raw_ann.get("metadata", {}).get("sync", {}))
                except Exception as exc2:
                    missing.append({
                        "key": f"{scene_id}.scene_annotation",
                        "label": f"{scene_id} annotation",
                        "reason": f"Scene annotation cannot be read: {exc2}",
                        "action": "fix_scene_annotation",
                    })
                    continue
            if sync and sync.get("render_scene") != "synced":
                missing.append({
                    "key": f"{scene_id}.render_scene",
                    "label": f"{scene_id} render scene",
                    "reason": "Edited navigation overlays are not synced into render-scene artifacts.",
                    "action": "sync_render_scene",
                })
            if sync.get("render_scene") == "synced":
                # scene_variant_ref / render_scene_overlay_ref / render_readiness_ref are project-relative
                # (written by write_render_scene_sync against project_dir).
                # render_scene_xml_ref is repo-relative (written by sync handler against repo_root).
                _project_relative_keys = {"scene_variant_ref", "render_scene_overlay_ref", "render_readiness_ref"}
                for key in ("scene_variant_ref", "render_scene_overlay_ref", "render_scene_xml_ref", "render_readiness_ref"):
                    ref = sync.get(key)
                    ref_path = None
                    if ref:
                        ref_path = (project_dir / str(ref)) if key in _project_relative_keys else resolve_repo_path(self.repo_root, str(ref))
                    if not ref or not ref_path or not ref_path.exists():
                        missing.append({
                            "key": f"{scene_id}.{key}",
                            "label": key,
                            "reason": f"Synced render-scene artifact is missing: {ref or key}",
                            "action": "sync_render_scene",
                        })
                readiness_ref = sync.get("render_readiness_ref")
                if readiness_ref:
                    try:
                        readiness = _read_json(project_dir / str(readiness_ref))
                        if not readiness.get("ok"):
                            missing.append({
                                "key": f"{scene_id}.render_readiness",
                                "label": "Render readiness",
                                "reason": "; ".join(str(item.get("message") or item.get("label")) for item in readiness.get("errors", [])[:3]) or "Render readiness is blocked.",
                                "action": "sync_render_scene",
                            })
                    except Exception as exc:
                        missing.append({
                            "key": f"{scene_id}.render_readiness",
                            "label": "Render readiness",
                            "reason": f"Render readiness cannot be read: {exc}",
                            "action": "sync_render_scene",
                        })
            elif sync.get("render_scene") == "blocked":
                missing.append({
                    "key": f"{scene_id}.render_readiness",
                    "label": "Render readiness",
                    "reason": "Render-scene sync is blocked by readiness errors.",
                    "action": "sync_render_scene",
                })
        # scene_state and camera_spec are only required for non-graph_sweep modes.
        # For graph_sweep: scene_state is always rebuilt from scene_variant.json in the handler,
        # and camera_spec is derived from the camera_rig in authoring_map automatically.
        if mode != "graph_sweep":
            if not isinstance(payload.get("scene_state"), Mapping):
                missing.append({
                    "key": "scene_state",
                    "label": "Isaac scene state",
                    "reason": "No scene_state payload was provided for rendering.",
                    "action": "configure_sensor_sweep",
                })
            if not isinstance(payload.get("camera_spec"), Mapping):
                missing.append({
                    "key": "camera_spec",
                    "label": "Camera specification",
                    "reason": "No camera_spec payload was provided for rendering.",
                    "action": "configure_sensor_sweep",
                })
        if not missing:
            return None
        return {
            "ok": False,
            "stage": "render_preconditions",
            "status": "blocked",
            "mode": mode,
            "message": "Rendering is not ready.",
            "missing": missing,
            "next_action": {
                "id": missing[0]["action"],
                "label": (
                    "Sync Render Scene" if missing[0]["action"] == "sync_render_scene"
                    else "Compile Authoring Map" if missing[0]["action"] == "compile_authoring_map"
                    else "Configure Sensor Sweep"
                ),
            },
        }

    _OPTICALNAV_OBS_PNG_FILENAMES = {
        "rgb": "rgb.png",
        "depth": "depth.png",
        "albedo": "albedo.png",
        "active_nir_intensity": "active_nir_intensity.png",
        "hazard_mask": "hazard_mask.png",
        "polar_rgb_preview": "polar_rgb_preview.png",
        "dop": "dop_red_black_colorbar.png",
        "aolp": "aolp_rainbow_colorbar.png",
        "s1": "s1_bwr_colorbar.png",
        "s2": "s2_bwr_colorbar.png",
        "s1_over_s0": "s1_over_s0_bwr_colorbar.png",
        "s2_over_s0": "s2_over_s0_bwr_colorbar.png",
    }

    def _opticalnav_scan_observations(self, project_dir: Path, scene_id: str) -> dict[str, Any]:
        """Scan the consolidated observations dir for a scene, returning per-vp heading status."""
        obs_root = project_dir / "scenes" / scene_id / "observations"
        viewpoints: dict[str, Any] = {}
        if not obs_root.exists():
            return {"scene_id": scene_id, "viewpoints": viewpoints}
        for vp_dir in sorted(obs_root.iterdir()):
            if not vp_dir.is_dir():
                continue
            vp_id = vp_dir.name
            for h_dir in sorted(vp_dir.iterdir()):
                if not h_dir.is_dir():
                    continue
                heading_id = h_dir.name
                has_rgb = (h_dir / "rgb.png").exists()
                has_depth = (h_dir / "depth.png").exists()
                has_albedo = (h_dir / "albedo.png").exists()
                has_active_nir = (h_dir / "active_nir_intensity.png").exists()
                has_hazard = (h_dir / "hazard_mask.png").exists()
                has_polar_rgb = (h_dir / "polar_rgb_preview.png").exists()
                if vp_id not in viewpoints:
                    viewpoints[vp_id] = {"headings": {}, "total": 0, "completed": 0}
                sensors: dict[str, Any] = {}
                sensors_dir = h_dir / "sensors"
                if sensors_dir.exists():
                    for sensor_dir in sorted(sensors_dir.iterdir()):
                        if not sensor_dir.is_dir():
                            continue
                        sensor_status = {
                            f"has_{modality}": (sensor_dir / filename).exists()
                            for modality, filename in self._OPTICALNAV_OBS_PNG_FILENAMES.items()
                        }
                        if any(sensor_status.values()):
                            sensors[sensor_dir.name] = sensor_status
                completed = has_rgb or has_depth or any(
                    bool(sensor_status.get("has_rgb") or sensor_status.get("has_depth"))
                    for sensor_status in sensors.values()
                )
                viewpoints[vp_id]["headings"][heading_id] = {
                    "job_id": None,
                    "status": "succeeded" if completed else "unknown",
                    "has_rgb": has_rgb,
                    "has_depth": has_depth,
                    "has_albedo": has_albedo,
                    "has_active_nir_intensity": has_active_nir,
                    "has_hazard_mask": has_hazard,
                    "has_polar_rgb_preview": has_polar_rgb,
                    "sensors": sensors,
                }
                viewpoints[vp_id]["total"] += 1
                if completed:
                    viewpoints[vp_id]["completed"] += 1
        return {"scene_id": scene_id, "viewpoints": viewpoints}

    def _opticalnav_clear_staged_scene_cache(self, scene_dir: Path) -> dict[str, Any]:
        """Remove cached ``.staged_mitsuba/`` XMLs and texture-audit sidecars.

        Sync regenerates ``render_scene.xml``. The Mitsuba staging cache keys on
        the source XML's path + mtime + size, so a fresh mtime usually triggers
        a new staged file. But render jobs that resolved the staged path under
        the *previous* render_scene.xml keep loading that path even after the
        new XML lands — so we explicitly wipe the directory at sync start.
        """
        staged_dir = scene_dir / ".staged_mitsuba"
        if not staged_dir.exists():
            return {"removed_files": 0}
        removed = 0
        errors: list[str] = []
        for entry in staged_dir.rglob("*"):
            if entry.is_file():
                try:
                    entry.unlink()
                    removed += 1
                except OSError as exc:
                    errors.append(f"{entry.name}: {exc}")
        info: dict[str, Any] = {"removed_files": removed}
        if errors:
            info["errors"] = errors[:8]
        return info

    def _opticalnav_invalidate_missing_envmap(
        self,
        authoring_map: Any,
        map_path: Path,
        scene_dir: Path,
    ) -> dict[str, Any] | None:
        """Drop the authoring envmap when the referenced file is gone.

        Mitsuba's xml loader aborts the whole scene load on an unreadable
        envmap filename. When the user uploads an envmap, deletes it from disk,
        then re-syncs, we'd otherwise build a render_scene.xml that fails at
        load time. Downgrade the environment to ``constant`` and persist it.

        Returns a dict summarizing what was cleared (for the sync response),
        or ``None`` when no change was needed.
        """
        env = getattr(authoring_map, "environment", None)
        if env is None:
            return None
        ref = getattr(env, "envmap_ref", None)
        mode = str(getattr(env, "mode", "") or "").lower()
        # Case A: mode says envmap but ref is null/empty → downgrade mode.
        if mode == "envmap" and not ref:
            env.mode = "constant"
            try:
                from navigation_dataset.authoring_map import save_authoring_map  # local import
                save_authoring_map(map_path, authoring_map)
            except Exception as exc:
                return {"envmap_ref": None, "cleared": False, "save_error": str(exc)}
            return {"envmap_ref": None, "cleared": True, "downgraded_to": "constant", "reason": "envmap_mode_without_ref"}
        if not ref:
            return None
        # Case B: ref present — check whether the file resolves.
        candidates: list[Path] = []
        try:
            candidates.append(resolve_repo_path(self.repo_root, ref))
        except Exception:
            pass
        candidates.append(scene_dir / ref)
        candidates.append(Path(ref))
        if any(p.exists() for p in candidates if p):
            return None
        # Missing on disk → clear and downgrade.
        original_ref = ref
        env.envmap_ref = None
        if mode == "envmap":
            env.mode = "constant"
        try:
            save_authoring_map_path = map_path
            from navigation_dataset.authoring_map import save_authoring_map  # local import
            save_authoring_map(save_authoring_map_path, authoring_map)
        except Exception as exc:
            return {
                "envmap_ref": original_ref,
                "cleared": False,
                "save_error": str(exc),
            }
        return {
            "envmap_ref": original_ref,
            "cleared": True,
            "downgraded_to": getattr(env, "mode", "constant"),
        }

    def _opticalnav_mesh_cache_dir(self, project_dir: Path, scene_id: str) -> Path:
        return project_dir / "scenes" / scene_id / "mesh_cache"

    def _opticalnav_texture_cache_dir(self, project_dir: Path, scene_id: str) -> Path:
        return project_dir / "scenes" / scene_id / "texture_cache"

    def _opticalnav_cache_texture(
        self,
        project_dir: Path,
        scene_id: str,
        asset_str: str | None,
        *,
        usd_path: Path,
    ) -> str | None:
        """Resolve a USD texture asset and copy it into ``texture_cache/`` when external.

        Returns a repo-relative POSIX path suitable for Mitsuba ``<string filename>`` or
        ``None`` when the asset cannot be resolved.
        """
        if not asset_str:
            return None
        from .usd_material_extract import resolve_asset_path

        resolved = resolve_asset_path(asset_str, usd_path=usd_path)
        if resolved is None:
            return None
        # If already inside the repo, point to it directly.
        try:
            rel = resolved.relative_to(self.repo_root)
            return rel.as_posix()
        except ValueError:
            pass
        # External path → copy into texture_cache/ keyed by (path + mtime).
        try:
            mtime_ns = resolved.stat().st_mtime_ns
        except OSError:
            return None
        digest = hashlib.sha1(f"{resolved}|{mtime_ns}".encode("utf-8")).hexdigest()[:16]
        ext = resolved.suffix.lower() or ".bin"
        cache_dir = self._opticalnav_texture_cache_dir(project_dir, scene_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        dst = cache_dir / f"{digest}{ext}"
        if not dst.exists():
            tmp = cache_dir / f"{digest}.tmp.{os.getpid()}.{threading.get_ident()}{ext}"
            try:
                shutil.copy2(resolved, tmp)
                try:
                    tmp.replace(dst)
                except FileNotFoundError:
                    pass  # another worker won the race
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                return None
        try:
            return dst.relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(dst)

    def _make_mesh_resolver(self, project_dir: Path, scene_id: str) -> "Callable[[str, str], tuple[Path, dict] | None]":
        """Return a mesh_resolver closure for use in _generate_opticalnav_render_scene_xml."""
        def _resolve(usd_ref: str, prim_path: str) -> "tuple[Path, dict] | None":
            return self._ensure_prim_obj_cached(project_dir, scene_id, usd_ref, prim_path)
        return _resolve

    def _ensure_prim_obj_cached(
        self,
        project_dir: Path,
        scene_id: str,
        usd_ref: str,
        prim_path: str,
        *,
        stage_cache: "dict[str, Any] | None" = None,
    ) -> "tuple[Path, dict[str, Any]] | None":
        """Resolve a per-prim OBJ (+ extracted UsdShade material) from the on-disk cache.

        ``stage_cache`` lets callers share an opened ``pxr.Usd.Stage`` across many
        prims in the same USD file (one Stage open per file per sync).
        """
        from .usd_prim_obj import OBJ_WRITER_VERSION  # local import keeps pxr optional

        if not usd_ref or not prim_path:
            return None
        try:
            usd_abs = resolve_repo_path(self.repo_root, usd_ref)
        except Exception:
            return None
        if not usd_abs.exists():
            return None
        try:
            mtime_ns = usd_abs.stat().st_mtime_ns
        except OSError:
            return None
        digest = hashlib.sha1(
            f"{usd_ref}|{prim_path}|{mtime_ns}|v{OBJ_WRITER_VERSION}|matv{_USD_PRIM_MATERIAL_META_VERSION}".encode("utf-8")
        ).hexdigest()[:16]
        cache_dir = self._opticalnav_mesh_cache_dir(project_dir, scene_id)
        obj_path = cache_dir / f"{digest}.obj"
        meta_path = cache_dir / f"{digest}.meta.json"
        if obj_path.exists() and meta_path.exists():
            try:
                meta = _read_json(meta_path)
                if int(meta.get("writer_version") or 0) >= OBJ_WRITER_VERSION:
                    return obj_path, meta
            except Exception:
                pass  # corrupt sidecar — rebuild

        from .usd_prim_obj import extract_prim_mesh_to_obj
        from .usd_material_extract import extract_material_for_prim

        stage = None
        if stage_cache is not None:
            stage = stage_cache.get(str(usd_abs))
            if stage is None:
                try:
                    from pxr import Usd  # type: ignore
                    stage = Usd.Stage.Open(str(usd_abs))
                except Exception:
                    stage = None
                stage_cache[str(usd_abs)] = stage
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            stats = extract_prim_mesh_to_obj(usd_abs, prim_path, obj_path, stage=stage)
        except Exception:
            return None
        if stats is None:
            return None

        extracted_material: dict[str, Any] | None = None
        stats_payload = stats.to_dict()
        try:
            if stage is None:
                from pxr import Usd  # type: ignore
                tmp_stage = Usd.Stage.Open(str(usd_abs))
            else:
                tmp_stage = stage

            def _material_dict_for_prim_path(path_value: str) -> dict[str, Any] | None:
                if tmp_stage is None or not path_value:
                    return None
                target = tmp_stage.GetPrimAtPath(path_value)
                em = extract_material_for_prim(target, stage=tmp_stage, usd_path=usd_abs)
                if em is None:
                    return None
                em_dict = em.to_dict()
                em_dict["source"] = "usd_prim"
                em_dict["base_color_texture_ref"] = self._opticalnav_cache_texture(
                    project_dir, scene_id, em.base_color_asset, usd_path=usd_abs,
                )
                em_dict["normal_texture_ref"] = self._opticalnav_cache_texture(
                    project_dir, scene_id, em.normal_asset, usd_path=usd_abs,
                )
                em_dict["roughness_texture_ref"] = self._opticalnav_cache_texture(
                    project_dir, scene_id, em.roughness_asset, usd_path=usd_abs,
                )
                return em_dict

            if tmp_stage is not None:
                parts = []
                for raw_part in stats_payload.get("mesh_parts") or []:
                    part = dict(raw_part)
                    obj_raw = part.get("obj_path")
                    if obj_raw:
                        try:
                            part["obj_ref"] = Path(str(obj_raw)).resolve().relative_to(self.repo_root).as_posix()
                        except Exception:
                            part["obj_ref"] = str(obj_raw)
                    em_dict = _material_dict_for_prim_path(str(part.get("mesh_prim_path") or ""))
                    part["extracted_material"] = em_dict
                    part["material_class"] = _infer_material_class(part, em_dict)
                    parts.append(part)
                    if extracted_material is None and em_dict is not None:
                        extracted_material = em_dict
                stats_payload["mesh_parts"] = parts

                if extracted_material is None:
                    # Fallback for single-mesh prims or legacy no-part writers.
                    prim = tmp_stage.GetPrimAtPath(prim_path)
                    target_prim = prim
                    try:
                        from pxr import UsdGeom  # type: ignore
                        if prim and prim.IsValid() and not prim.IsA(UsdGeom.Mesh):
                            from pxr import Usd  # type: ignore
                            for child in Usd.PrimRange(prim):
                                if child.IsA(UsdGeom.Mesh):
                                    target_prim = child
                                    break
                    except Exception:
                        pass
                    try:
                        extracted_material = _material_dict_for_prim_path(str(target_prim.GetPath()))
                    except Exception:
                        extracted_material = None
        except Exception as exc:
            extracted_material = {"error": str(exc)}

        meta = {
            **stats_payload,
            "usd_ref": usd_ref,
            "prim_path": prim_path,
            "usd_mtime_ns": int(mtime_ns),
            "material_meta_version": _USD_PRIM_MATERIAL_META_VERSION,
            "generated_at": _utc_now_iso(),
            "extracted_material": extracted_material,
        }
        try:
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        return obj_path, meta

    def _opticalnav_render_scene_stats(self, project_dir: Path, scene_id: str) -> dict[str, Any]:
        """Quick counts from render_scene.xml so the Sync Inspector can diff against the editor state."""
        xml_path = project_dir / "scenes" / scene_id / "render_scene.xml"
        if not xml_path.exists():
            return {"exists": False, "scene_id": scene_id}
        try:
            stat = xml_path.stat()
            text = xml_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"exists": True, "scene_id": scene_id, "error": str(exc)}
        return {
            "exists": True,
            "scene_id": scene_id,
            "path": xml_path.relative_to(self.repo_root).as_posix(),
            "size_bytes": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "shape_count": text.count("<shape "),
            "obj_shape_count": text.count('<shape type="obj"'),
            "cube_shape_count": text.count('<shape type="cube"'),
            "area_emitter_count": text.count('type="area"'),
            "envmap_count": text.count('<emitter type="envmap"'),
            "constant_emitter_count": text.count('<emitter type="constant"'),
            "shared_bsdf_count": text.count("<bsdf type=") - text.count("shape><bsdf"),
            "measured_polarized_count": text.count('<bsdf type="measured_polarized"'),
            "channel_split_refs": text.count("data/hpbrdf_2025/channels/"),
            "raw_hpbrdf_refs": text.count(".hpbrdf\""),
        }

    def _opticalnav_observation_modality_png(
        self,
        project_dir: Path,
        scene_id: str,
        vp_id: str,
        heading_id: str,
        modality: str,
        *,
        sensor_id: str | None = None,
    ) -> bytes | None:
        filename = self._OPTICALNAV_OBS_PNG_FILENAMES.get(modality)
        if not filename:
            return None
        heading_dir = project_dir / "scenes" / scene_id / "observations" / vp_id / heading_id
        if sensor_id:
            path = heading_dir / "sensors" / sensor_id / filename
            if path.exists():
                return path.read_bytes()
            return None
        path = heading_dir / filename
        if path.exists():
            return path.read_bytes()
        return None

    def _opticalnav_observation_rgb_png(self, project_dir: Path, scene_id: str, vp_id: str, heading_id: str) -> bytes | None:
        """Return the rgb.png bytes for a completed observation from the consolidated dir."""
        path = project_dir / "scenes" / scene_id / "observations" / vp_id / heading_id / "rgb.png"
        if path.exists():
            return path.read_bytes()
        return None

    def _opticalnav_render_batch_payload(self, project_dir: Path, batch_id: str) -> dict[str, Any]:
        batch_path = project_dir / "render_batches" / f"{batch_id}.json"
        if not batch_path.exists():
            raise KeyError(batch_id)
        batch = _read_json(batch_path)
        jobs = []
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0}
        for item in batch.get("jobs", []):
            job_id = str(item.get("job_id") or "")
            try:
                status = render_job_status_to_payload(self.get_status(job_id))
            except Exception:
                status = {"job_id": job_id, "status": "unknown"}
            state = str(status.get("status") or "unknown")
            counts[state] = counts.get(state, 0) + 1
            jobs.append({**item, "status": status})
        total = max(1, len(jobs))
        return {
            **batch,
            "jobs": jobs,
            "counts": counts,
            "progress": {
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
                "total": len(jobs),
                "fraction": (counts.get("completed", 0) + counts.get("failed", 0)) / total,
            },
        }

    def _opticalnav_graph_batch_payload(self, project_dir: Path, batch_id: str) -> dict[str, Any]:
        batch_path = project_dir / "graph_render_batches" / f"{batch_id}.json"
        if not batch_path.exists():
            raise KeyError(batch_id)
        batch = _read_json(batch_path)
        jobs = []
        counts = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0}
        for item in batch.get("jobs", []):
            job_id = str(item.get("job_id") or "")
            try:
                status = render_job_status_to_payload(self.get_status(job_id))
            except Exception:
                status = {"job_id": job_id, "status": "unknown"}
            state = str(status.get("status") or "unknown")
            counts[state] = counts.get(state, 0) + 1
            jobs.append({**item, "status": status})
        total = max(1, len(jobs))
        return {
            **batch,
            "jobs": jobs,
            "counts": counts,
            "progress": {
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
                "total": len(jobs),
                "fraction": (counts.get("completed", 0) + counts.get("failed", 0)) / total,
            },
        }

    # --- OpticalNav Agent API helpers ---

    @staticmethod
    def _geom_summary(geom: Any) -> str:
        if geom.type == "line" and geom.start and geom.end:
            s, e = geom.start, geom.end
            return f"line([{round(s[0],2)},{round(s[1],2)}]→[{round(e[0],2)},{round(e[1],2)}])"
        if geom.type == "rectangle" and isinstance(geom.bounds, list) and len(geom.bounds) == 4:
            b = [round(v, 2) for v in geom.bounds]
            return f"rect([{b[0]},{b[1]}]→[{b[2]},{b[3]}])"
        if geom.type == "point" and geom.center:
            return f"point({round(geom.center[0],2)},{round(geom.center[1],2)})"
        return geom.type

    @staticmethod
    def _parse_agent_geometry(obj_req: dict, placement: str) -> Any:
        from navigation_dataset.authoring_map import AuthoringGeometry
        if placement == "line":
            return AuthoringGeometry(type="line", start=[float(v) for v in obj_req["start"]], end=[float(v) for v in obj_req["end"]])
        if placement == "point":
            return AuthoringGeometry(type="point", center=[float(v) for v in obj_req["position"]])
        if placement == "rectangle":
            mn, mx = obj_req["min"], obj_req["max"]
            return AuthoringGeometry(type="rectangle", bounds=[float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1])])
        raise ValueError(f"Unknown placement: {placement!r}. Use 'line', 'point', or 'rectangle'.")

    @staticmethod
    def _auto_object_id(obj_type: str, existing_ids: set) -> str:
        i = 1
        while True:
            candidate = f"{obj_type}_{i:03d}"
            if candidate not in existing_ids:
                return candidate
            i += 1

    def _build_agent_object(self, req: dict, existing_ids: set) -> Any:
        from navigation_dataset.authoring_map import AuthoringNavigationFlags, AuthoringObject
        _defaults: dict[str, dict] = {
            "glass_wall":            {"blocks_navigation": True,  "hazard_type": "transparent_obstacle", "include_in_hazard_mask": True},
            "mirror_wall":           {"blocks_navigation": True,  "hazard_type": "reflective_obstacle",  "include_in_hazard_mask": True},
            "transparent_partition": {"blocks_navigation": True,  "hazard_type": "transparent_obstacle", "include_in_hazard_mask": True},
            "glass_door":            {"blocks_navigation": False, "hazard_type": "transparent_obstacle", "include_in_hazard_mask": True},
            "wall":                  {"blocks_navigation": True},
            "chair":                 {"blocks_navigation": True},
            "table":                 {"blocks_navigation": True},
            "plant":                 {"blocks_navigation": True},
            "shelf":                 {"blocks_navigation": True},
            "landmark":              {"instruction_candidate": True},
        }
        obj_type = str(req.get("type") or "")
        placement = str(req.get("placement") or "")
        asset = self._find_asset_for_agent_request(req)
        proxy_allowed = self._coerce_bool(req.get("allow_proxy"), False)
        asset_required = obj_type not in {"wall", "glass_wall", "mirror_wall", "transparent_partition", "glass_door"}
        if asset_required and asset is None and not proxy_allowed:
            raise ValueError("Agent object placement requires an active usable asset_id/source_ref. Use allow_proxy=true only for debug proxies.")
        label = str(req.get("label") or (asset.get("label") if asset else None) or obj_type)
        obj_id = str(req["id"]) if req.get("id") else self._auto_object_id(obj_type, existing_ids)
        geometry = self._parse_agent_geometry(req, placement)
        d = _defaults.get(obj_type, {})
        nav = AuthoringNavigationFlags(
            blocks_navigation=bool(d.get("blocks_navigation", False)),
            hazard_type=str(d["hazard_type"]) if d.get("hazard_type") else None,
            include_in_hazard_mask=bool(d.get("include_in_hazard_mask", False)),
            instruction_candidate=bool(d.get("instruction_candidate", False)),
        )
        metadata = dict(req.get("metadata") or {})
        source_ref = _maybe_str(req.get("source_ref") or req.get("asset_source_ref"))
        material = str(req["material"]) if req.get("material") else None
        if asset is not None:
            source_ref = _maybe_str(asset.get("source_ref")) or source_ref
            material = material or _maybe_str(asset.get("material_hint") or asset.get("material"))
            metadata.update({
                "asset_id": asset.get("asset_id"),
                "asset_category": asset.get("category"),
                "asset_source_ref": source_ref,
                "asset_source_path": source_ref if self._looks_like_glb_ref(source_ref) else asset.get("source_path"),
                "asset_source_format": asset.get("source_format") or ("glb" if str(source_ref or "").lower().endswith((".glb", ".gltf")) else "usd_prim"),
                "asset_source_dataset": asset.get("source_dataset"),
                "render_readiness": asset.get("render_readiness"),
                "readiness_reason": asset.get("readiness_reason"),
            })
            bounds = asset.get("bounds") if isinstance(asset.get("bounds"), Mapping) else {}
            size = bounds.get("size") if isinstance(bounds, Mapping) else None
            if isinstance(size, list) and len(size) >= 3:
                metadata.setdefault("proxy_size", size[:3])
            mn = bounds.get("min") if isinstance(bounds, Mapping) else None
            if isinstance(mn, list) and len(mn) >= 2:
                metadata.setdefault("normalized_y_min", mn[1])
        return AuthoringObject(
            id=obj_id, type=obj_type, label=label, placement=placement, geometry=geometry,
            material=material, navigation=nav, source_ref=source_ref, metadata=metadata,
        )

    def _build_agent_region(self, req: dict, existing_ids: set) -> Any:
        from navigation_dataset.authoring_map import AuthoringNavigationFlags, AuthoringRegion
        _defaults: dict[str, dict] = {
            "goal":        {"goal_candidate": True},
            "hazard":      {"hazard_type": "transparent_obstacle", "include_in_hazard_mask": True},
            "obstacle":    {"blocks_navigation": True},
        }
        region_type = str(req.get("type") or "")
        placement = str(req.get("placement") or "")
        label = str(req.get("label") or region_type)
        obj_id = str(req["id"]) if req.get("id") else self._auto_object_id(region_type, existing_ids)
        geometry = self._parse_agent_geometry(req, placement)
        d = _defaults.get(region_type, {})
        nav = AuthoringNavigationFlags(
            blocks_navigation=bool(d.get("blocks_navigation", False)),
            hazard_type=str(d["hazard_type"]) if d.get("hazard_type") else None,
            include_in_hazard_mask=bool(d.get("include_in_hazard_mask", False)),
            goal_candidate=bool(d.get("goal_candidate", False)),
        )
        return AuthoringRegion(id=obj_id, type=region_type, label=label, placement=placement, geometry=geometry, navigation=nav)

    def _handle_opticalnav_get(self, handler: BaseHTTPRequestHandler, path: str, query: Mapping[str, list[str]]) -> bool:
        if path == "/api/opticalnav/projects":
            projects = []
            for dataset_path in sorted(self._opticalnav_root().glob("*/dataset.json")):
                projects.append(self._opticalnav_project_summary(dataset_path.parent))
            self._send_json(handler, HTTPStatus.OK, {"projects": projects})
            return True
        if path == "/api/opticalnav/usd-candidates":
            self._send_json(handler, HTTPStatus.OK, {"candidates": self._opticalnav_usd_candidates()})
            return True
        if path == "/api/opticalnav/asset-library/sources":
            self._send_json(handler, HTTPStatus.OK, {"sources": self._opticalnav_asset_sources()})
            return True
        if path == "/api/opticalnav/asset-library/assets":
            assets = self._opticalnav_all_asset_library_assets()
            q = _maybe_str((query.get("q") or [None])[0])
            category = _maybe_str((query.get("category") or [None])[0])
            selected_raw = _maybe_str((query.get("selected") or [None])[0])
            source_ref = _maybe_str((query.get("source_ref") or query.get("usd_ref") or [None])[0])
            source_type = _maybe_str((query.get("source_type") or [None])[0])
            if q:
                needle = q.lower()
                assets = [
                    asset for asset in assets
                    if needle in " ".join([
                        str(asset.get("label") or ""),
                        str(asset.get("source_path") or ""),
                        str(asset.get("category") or ""),
                        " ".join(str(tag) for tag in asset.get("tags", []) or []),
                    ]).lower()
                ]
            if category and category != "all":
                assets = [asset for asset in assets if str(asset.get("category") or "") == category]
            if source_ref:
                assets = [asset for asset in assets if str(asset.get("usd_ref") or asset.get("source_ref") or "") == source_ref]
            if source_type and source_type != "all":
                assets = [asset for asset in assets if str(asset.get("source_dataset") or asset.get("source_type") or "").lower() == source_type.lower()]
            if selected_raw is not None:
                want_selected = self._coerce_bool(selected_raw, False)
                assets = [asset for asset in assets if self._asset_is_selected(asset) == want_selected]
            readiness_index = self._load_asset_readiness_index()
            self._send_json(handler, HTTPStatus.OK, {"assets": [self._asset_library_ui_payload(asset, readiness_index) for asset in assets], "count": len(assets)})
            return True
        if path == "/api/opticalnav/agent/assets":
            assets = self._filter_agent_assets(query)
            self._send_json(handler, HTTPStatus.OK, {
                "assets": assets,
                "count": len(assets),
                "active_count": sum(1 for asset in assets if self._coerce_bool(asset.get("active"), False)),
                "contract": {
                    "activate": "POST /api/opticalnav/agent/assets/activation with activate/deactivate arrays or decisions[].",
                    "effect": "Only active assets with render_readiness texture_ready or analytic_ok appear in the OpticalNav Place Catalog by default.",
                    "readiness_rule": "Scene generation agents must use usable_by_agent=true assets; include_unready=1 is debug-only.",
                },
            })
            return True
        if path == "/api/opticalnav/agent/materials":
            from mitsuba_converter.material_library import MATERIAL_CATALOG, hpbrdf_channels_dir
            from navigation_dataset.authoring_map import MATERIAL_PRESETS
            _preset_categories = {
                "clear_glass": "glass", "frosted_glass": "glass",
                "mirror": "metal", "painted_wall": "wall",
                "wood": "furniture", "fabric": "furniture", "tile": "floor",
            }
            presets = [{"id": mid, "label": mid.replace("_", " ").title(), "category": _preset_categories.get(mid, "other")} for mid in sorted(MATERIAL_PRESETS)]
            hpbrdf = [{"id": mid, "label": label, "dataset": "hpbrdf_2025", "local_available": hpbrdf_channels_dir(self.repo_root, mid) is not None} for mid, label, _ in MATERIAL_CATALOG.get("hpbrdf_2025", [])]
            pbrdf = [{"id": mid, "label": label, "dataset": "pbrdf_2020"} for mid, label, _ in MATERIAL_CATALOG.get("pbrdf_2020", [])]
            self._send_json(handler, HTTPStatus.OK, {"presets": presets, "hpbrdf": hpbrdf, "pbrdf": pbrdf})
            return True
        if not path.startswith("/api/opticalnav/projects/"):
            return False
        rest = path[len("/api/opticalnav/projects/"):].strip("/")
        parts = [unquote(part) for part in rest.split("/") if part]
        if not parts:
            return False
        try:
            project_dir = self._opticalnav_project_dir(parts[0])
        except ValueError as exc:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if not project_dir.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav project_id: {parts[0]}"})
            return True
        if len(parts) == 1:
            self._send_json(handler, HTTPStatus.OK, self._opticalnav_project_summary(project_dir))
            return True
        if len(parts) == 2 and parts[1] == "map-assets":
            readiness_index = self._load_asset_readiness_index()
            assets = [
                asset for asset in self._opticalnav_all_asset_library_assets()
                if self._asset_is_selected(asset) and self._asset_is_usable_for_render(asset, readiness_index)
            ]
            self._send_json(handler, HTTPStatus.OK, {
                "project_id": parts[0],
                "assets": [self._asset_library_ui_payload(asset, readiness_index) for asset in assets],
                "count": len(assets),
                "readiness_filter": {"allowed": sorted(self._ASSET_READINESS_USABLE), "sidecar": self._asset_readiness_path().relative_to(self.repo_root).as_posix()},
            })
            return True
        if len(parts) == 4 and parts[1] == "map-assets" and parts[3] == "thumbnail":
            asset_id = parts[2]
            result = self._opticalnav_asset_thumbnail(project_dir, asset_id)
            if result is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown asset: {asset_id}"})
                return True
            png_bytes, etag, final_thumbnail = result
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "image/png")
            handler.send_header("Content-Length", str(len(png_bytes)))
            if final_thumbnail:
                handler.send_header("Cache-Control", "public, max-age=86400")
            else:
                handler.send_header("Cache-Control", "no-store, max-age=0")
                handler.send_header("X-Robomituba-Thumbnail-State", "rendering")
            handler.send_header("ETag", f'"{etag}"')
            handler.end_headers()
            handler.wfile.write(png_bytes)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "annotation":
            annotation_path = project_dir / "scenes" / parts[2] / "scene_annotation.json"
            if not annotation_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "scene_annotation.json not found"})
                return True
            self._send_json(handler, HTTPStatus.OK, _read_json(annotation_path))
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "authoring-map":
            from navigation_dataset.authoring_map import authoring_map_to_payload, load_authoring_map, starter_authoring_map

            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            xml_path = scene_dir / "render_scene.xml"
            try:
                map_exists = map_path.exists()
                if map_path.exists():
                    payload = authoring_map_to_payload(load_authoring_map(map_path))
                else:
                    payload = authoring_map_to_payload(starter_authoring_map(scene_id, f"/api/scenes/{quote(scene_id, safe='')}/floorplan"))
                # authoring_map.json is the editor's canonical state. Older
                # builds embedded opticalnav-obj comments in render_scene.xml
                # and this endpoint used those comments as a migration source.
                # Keeping XML authoritative after the map exists is unsafe:
                # Save Map can persist a transform to authoring_map.json while
                # a stale render_scene.xml still contains the previous transform,
                # causing a hard reload to "undo" saved edits.
                map_has_objects = bool(payload.get("objects"))
                if xml_path.exists():
                    xml_objects = _extract_opticalnav_objects_from_xml(xml_path) if (not map_exists or not map_has_objects) else []
                    if xml_objects and (not map_exists or not map_has_objects):
                        payload = dict(payload)
                        # Migration fallback only: rebuild authoring objects
                        # from XML metadata when no canonical map objects exist.
                        payload["objects"] = xml_objects
                    xml_scene_meta = _extract_opticalnav_scene_meta_from_xml(xml_path)
                    if xml_scene_meta and (not map_exists):
                        # Migration fallback for pre-authoring_map scenes.
                        if xml_scene_meta.get("environment") and not payload.get("environment"):
                            payload = dict(payload)
                            payload["environment"] = xml_scene_meta["environment"]
                        if xml_scene_meta.get("camera_rig") and not payload.get("camera_rig"):
                            payload = dict(payload)
                            payload["camera_rig"] = xml_scene_meta["camera_rig"]
                        if xml_scene_meta.get("materials") and not payload.get("materials"):
                            payload = dict(payload)
                            payload["materials"] = xml_scene_meta["materials"]
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, payload)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "prim-mesh":
            scene_id = parts[2]
            source_path_raw = _maybe_str((query.get("source_path") or [None])[0])
            source_ref_raw = _maybe_str((query.get("source_ref") or [None])[0])
            usd_ref_override = _maybe_str((query.get("usd_ref") or [None])[0])
            if not source_path_raw and not source_ref_raw:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "source_path or source_ref query param required"})
                return True
            try:
                glb_ref = source_ref_raw or ""
                if not glb_ref and self._looks_like_glb_ref(source_path_raw):
                    glb_ref = str(source_path_raw)
                if not glb_ref and self._looks_like_glb_ref(usd_ref_override):
                    glb_ref = str(usd_ref_override)
                if glb_ref:
                    glb_path = resolve_repo_path(self.repo_root, glb_ref)
                    if not glb_path.exists():
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"GLB file not found: {glb_ref}"})
                        return True
                    stat = glb_path.stat()
                    mesh_key = {
                        "version": "prim_mesh_glb_v1",
                        "source_ref": glb_ref,
                        "source_mtime_ns": stat.st_mtime_ns,
                        "source_size": stat.st_size,
                        "max_triangles": 3500,
                    }
                    etag = hashlib.sha1(json.dumps(mesh_key, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                    if handler.headers.get("If-None-Match", "").strip().strip('"') == etag:
                        handler.send_response(HTTPStatus.NOT_MODIFIED)
                        handler.send_header("Cache-Control", "public, max-age=604800")
                        handler.send_header("ETag", f'"{etag}"')
                        handler.end_headers()
                        return True
                    result = self._extract_glb_mesh_preview(glb_ref, max_triangles=3500)
                    if result is None:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"GLB has no mesh geometry: {glb_ref}"})
                        return True
                    result = {**result, "cache_key": mesh_key}
                    self._send_json(
                        handler,
                        HTTPStatus.OK,
                        result,
                        extra_headers={
                            "Cache-Control": "public, max-age=604800",
                            "ETag": f'"{etag}"',
                        },
                    )
                    return True

                usd_ref = usd_ref_override or self._opticalnav_scene_usd_ref(project_dir, scene_id)
                if not usd_ref:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "No USD reference for scene"})
                    return True
                usd_path = resolve_repo_path(self.repo_root, usd_ref)
                if not usd_path.exists():
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"USD file not found: {usd_ref}"})
                    return True
                stat = usd_path.stat()
                mesh_key = {
                    "version": "prim_mesh_v1",
                    "usd_ref": usd_ref,
                    "source_path": source_path_raw,
                    "source_mtime_ns": stat.st_mtime_ns,
                    "source_size": stat.st_size,
                }
                etag = hashlib.sha1(json.dumps(mesh_key, sort_keys=True).encode("utf-8")).hexdigest()[:16]
                if handler.headers.get("If-None-Match", "").strip().strip('"') == etag:
                    handler.send_response(HTTPStatus.NOT_MODIFIED)
                    handler.send_header("Cache-Control", "public, max-age=604800")
                    handler.send_header("ETag", f'"{etag}"')
                    handler.end_headers()
                    return True
                cached_stage = self._get_cached_usd_stage(usd_ref)
                result = extract_prim_mesh_for_editor(usd_path, str(source_path_raw), stage=cached_stage)
                if result is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Prim has no mesh geometry: {source_path_raw}"})
                    return True
                result = {**result, "cache_key": mesh_key}
                self._send_json(
                    handler,
                    HTTPStatus.OK,
                    result,
                    extra_headers={
                        "Cache-Control": "public, max-age=604800",
                        "ETag": f'"{etag}"',
                    },
                )
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "editor-geometry":
            scene_id = parts[2]
            try:
                refresh_raw = _maybe_str((query.get("refresh") or [None])[0])
                payload = self._opticalnav_editor_geometry(project_dir, scene_id, force_refresh=refresh_raw in {"1", "true", "yes"})
            except KeyError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            self._send_json(handler, HTTPStatus.OK, payload)
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "build-progress":
            progress_key = f"{project_dir}/{parts[2]}"
            with self._graph_build_lock:
                state = self._graph_build_progress.get(progress_key)
            if state is None:
                self._send_json(handler, HTTPStatus.OK, {"status": "idle", "progress": 0.0, "stage": ""})
            else:
                self._send_json(handler, HTTPStatus.OK, state)
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "overlapping-nodes":
            # Auto-detect grid vertices that landed on top of objects, so the
            # editor can pre-select them for manual review + removal.
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, find_object_overlapping_nodes
            scene_dir = project_dir / "scenes" / parts[2]
            graph_path = scene_dir / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            try:
                margin_m = float((query.get("margin_m") or ["0"])[0])
            except (TypeError, ValueError):
                margin_m = 0.0
            try:
                robot_height_m = float((query.get("robot_height_m") or ["1.2"])[0])
            except (TypeError, ValueError):
                robot_height_m = 1.2
            include_walls = _maybe_str((query.get("include_walls") or [None])[0]) in {"1", "true", "yes"}
            overlay_path = scene_dir / "render_scene_overlays.json"
            try:
                graph = read_viewpoint_graph(graph_path)
                objects = (_read_json(overlay_path).get("objects") if overlay_path.exists() else []) or []
                node_ids = find_object_overlapping_nodes(
                    graph, objects, margin_m=margin_m, include_walls=include_walls, robot_height_m=robot_height_m,
                )
                self._send_json(handler, HTTPStatus.OK, {
                    "node_ids": node_ids,
                    "count": len(node_ids),
                    "margin_m": margin_m,
                    "include_walls": include_walls,
                    "robot_height_m": robot_height_m,
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "graph":
            graph_path = project_dir / "scenes" / parts[2] / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            payload = _read_json(graph_path)
            try:
                from navigation_dataset.viewpoint_graph import compute_connected_components, read_viewpoint_graph
                graph = read_viewpoint_graph(graph_path)
                cc = compute_connected_components(graph)
                payload["components"] = cc["node_to_component"]
                payload["component_summary"] = [
                    {"index": c["index"], "size": c["size"]} for c in cc["components"]
                ]
            except Exception:
                pass
            self._send_json(handler, HTTPStatus.OK, payload)
            return True
        if len(parts) == 2 and parts[1] == "episodes":
            split = _maybe_str((query.get("split") or [None])[0])
            episodes = [self._opticalnav_episode_summary(project_dir, item) for item in self._opticalnav_episode_files(project_dir, split=split)]
            self._send_json(handler, HTTPStatus.OK, {"episodes": episodes})
            return True
        if len(parts) == 3 and parts[1] == "episodes":
            try:
                episode_path = self._opticalnav_find_episode(project_dir, parts[2])
            except KeyError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown episode_id: {parts[2]}"})
                return True
            self._send_json(handler, HTTPStatus.OK, _read_json(episode_path))
            return True
        if len(parts) == 3 and parts[1] == "render-batches":
            try:
                self._send_json(handler, HTTPStatus.OK, self._opticalnav_render_batch_payload(project_dir, parts[2]))
            except KeyError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown batch_id: {parts[2]}"})
            return True
        if len(parts) == 3 and parts[1] == "export-jobs":
            job_id = parts[2]
            with self._export_jobs_lock:
                state = self._export_jobs.get(job_id)
            if state is None:
                # Cold fallback: read status.json from disk (e.g., after daemon
                # restart or for a finished job that's no longer in memory).
                status_path = self._export_status_path(project_dir, job_id)
                if status_path.exists():
                    try:
                        state = _read_json(status_path)
                    except Exception:
                        state = None
            if state is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown export job: {job_id}"})
                return True
            self._send_json(handler, HTTPStatus.OK, state)
            return True
        if len(parts) == 2 and parts[1] == "graph-render-batches":
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Missing graph batch id."})
            return True
        if len(parts) == 3 and parts[1] == "graph-render-batches":
            try:
                self._send_json(handler, HTTPStatus.OK, self._opticalnav_graph_batch_payload(project_dir, parts[2]))
            except KeyError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown graph batch_id: {parts[2]}"})
            return True
        if len(parts) == 4 and parts[1] == "graph-render-batches" and parts[3] == "logs":
            batch_id = parts[2]
            try:
                batch = self._opticalnav_graph_batch_payload(project_dir, batch_id)
            except KeyError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown graph batch_id: {batch_id}"})
                return True
            per_job = int(_maybe_str(query.get("per_job", [None])[0]) or 30)
            entries: list[dict[str, Any]] = []
            for job in batch.get("jobs", []):
                job_id = str(job.get("job_id") or "")
                if not job_id:
                    continue
                log_path = self._job_log_path(job_id)
                if not log_path.exists():
                    continue
                try:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    for line in lines[-per_job:]:
                        entries.append({"job_id": job_id, "line": line})
                except Exception:
                    pass
            self._send_json(handler, HTTPStatus.OK, {"batch_id": batch_id, "entries": entries})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "observations-scan":
            scene_id = parts[2]
            self._send_json(handler, HTTPStatus.OK, self._opticalnav_scan_observations(project_dir, scene_id))
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "room-shell":
            from navigation_dataset.authoring_map import authoring_map_to_payload, load_authoring_map
            scene_id = parts[2]
            map_path = project_dir / "scenes" / scene_id / "authoring_map.json"
            if not map_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "authoring_map.json not found"})
                return True
            try:
                am = authoring_map_to_payload(load_authoring_map(map_path))
                self._send_json(handler, HTTPStatus.OK, {
                    "scene_id": scene_id,
                    "room_shell": _compute_room_shell_geometry(am),
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "walkability-overlay":
            from navigation_dataset.traversability import load_traversability_grid
            from navigation_dataset.walkability_overlay import load_overlay, overlay_stats
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            grid_path = scene_dir / "traversable_grid.npy"
            overlay_path = scene_dir / "walkability_overlay.npy"
            if not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build the traversable grid first."})
                return True
            try:
                grid = load_traversability_grid(grid_path)
                overlay = load_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                self._send_json(handler, HTTPStatus.OK, {
                    "scene_id": scene_id,
                    "grid_spec": {
                        "origin": list(grid.spec.origin),
                        "resolution": grid.spec.resolution,
                        "width": grid.spec.width,
                        "height": grid.spec.height,
                    },
                    "has_overlay": overlay is not None,
                    "stats": overlay_stats(overlay) if overlay is not None else None,
                    "overlay_png_url": f"/api/opticalnav/projects/{parts[0]}/scenes/{scene_id}/walkability-overlay.png" if overlay is not None else None,
                    "modified_at": datetime.fromtimestamp(overlay_path.stat().st_mtime, tz=timezone.utc).isoformat() if overlay_path.exists() else None,
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "walkability-overlay.png":
            from navigation_dataset.traversability import load_traversability_grid
            from navigation_dataset.walkability_overlay import (
                OVERLAY_VALUE_BLOCKED, OVERLAY_VALUE_WALKABLE, load_overlay,
            )
            import io
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            grid_path = scene_dir / "traversable_grid.npy"
            overlay_path = scene_dir / "walkability_overlay.npy"
            if not grid_path.exists() or not overlay_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "No overlay painted yet."})
                return True
            try:
                grid = load_traversability_grid(grid_path)
                overlay = load_overlay(overlay_path, expected_spec=grid.spec)
                if overlay is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Overlay shape mismatch."})
                    return True
                rgba = np.zeros((overlay.shape[0], overlay.shape[1], 4), dtype=np.uint8)
                walk = overlay == OVERLAY_VALUE_WALKABLE
                blk = overlay == OVERLAY_VALUE_BLOCKED
                rgba[walk] = [34, 197, 94, 153]   # green @ 0.6 alpha
                rgba[blk] = [239, 68, 68, 178]    # red   @ 0.7 alpha
                from PIL import Image
                # Flip vertically so PNG top-left matches world max-y / grid row 0.
                img = Image.fromarray(rgba, "RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(png_bytes)))
                handler.send_header("Cache-Control", "no-store")
                handler.end_headers()
                handler.wfile.write(png_bytes)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "traversable-grid":
            from navigation_dataset.traversability import load_traversability_grid, inflate_traversable_grid
            from navigation_dataset.walkability_overlay import load_overlay
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            grid_path = scene_dir / "traversable_grid.npy"
            if not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build the traversable grid first."})
                return True
            try:
                radius_raw = (query.get("robot_radius_m") or [None])[0]
                robot_radius_m = float(radius_raw) if radius_raw is not None else 0.25
                grid = load_traversability_grid(grid_path)
                overlay_path = scene_dir / "walkability_overlay.npy"
                overlay = load_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                base_traversable = grid.traversable.copy()
                if overlay is not None:
                    base_traversable = (base_traversable | (overlay == 1)) & ~(overlay == 2)
                inflated = inflate_traversable_grid(base_traversable, robot_radius_m, grid.spec.resolution)
                # Counts.
                raw_obstacle_cells = int((~base_traversable).sum())
                inflation_only_cells = int((base_traversable & ~inflated).sum())
                hazard_cells = int(grid.hazard.sum())
                traversable_cells = int(inflated.sum())
                origin = list(grid.spec.origin)
                width_m = float(grid.spec.width) * float(grid.spec.resolution)
                height_m = float(grid.spec.height) * float(grid.spec.resolution)
                self._send_json(handler, HTTPStatus.OK, {
                    "scene_id": scene_id,
                    "robot_radius_m": robot_radius_m,
                    "grid_spec": {
                        "origin": origin,
                        "resolution": grid.spec.resolution,
                        "width": grid.spec.width,
                        "height": grid.spec.height,
                    },
                    "bbox": [origin[0], origin[1], origin[0] + width_m, origin[1] + height_m],
                    "stats": {
                        "traversable_cells": traversable_cells,
                        "raw_obstacle_cells": raw_obstacle_cells,
                        "inflation_only_cells": inflation_only_cells,
                        "hazard_cells": hazard_cells,
                    },
                    "png_url": f"/api/opticalnav/projects/{parts[0]}/scenes/{scene_id}/traversable-grid.png?robot_radius_m={robot_radius_m}",
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "traversable-grid.png":
            from navigation_dataset.traversability import load_traversability_grid, inflate_traversable_grid
            from navigation_dataset.walkability_overlay import load_overlay
            import io
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            grid_path = scene_dir / "traversable_grid.npy"
            if not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build the traversable grid first."})
                return True
            try:
                radius_raw = (query.get("robot_radius_m") or [None])[0]
                robot_radius_m = float(radius_raw) if radius_raw is not None else 0.25
                grid = load_traversability_grid(grid_path)
                overlay_path = scene_dir / "walkability_overlay.npy"
                overlay = load_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                base_traversable = grid.traversable.copy()
                if overlay is not None:
                    base_traversable = (base_traversable | (overlay == 1)) & ~(overlay == 2)
                inflated = inflate_traversable_grid(base_traversable, robot_radius_m, grid.spec.resolution)
                raw_obstacle = ~base_traversable
                inflation_only = base_traversable & ~inflated
                rgba = np.zeros((inflated.shape[0], inflated.shape[1], 4), dtype=np.uint8)
                rgba[raw_obstacle] = [239, 68, 68, 130]      # red — real obstacle (carve-out)
                rgba[inflation_only] = [245, 158, 11, 110]   # orange — robot-radius inflation halo
                rgba[grid.hazard] = [168, 85, 247, 110]      # purple — hazard zone (overlay)
                from PIL import Image
                img = Image.fromarray(rgba, "RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_bytes = buf.getvalue()
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "image/png")
                handler.send_header("Content-Length", str(len(png_bytes)))
                handler.send_header("Cache-Control", "no-store")
                handler.end_headers()
                handler.wfile.write(png_bytes)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "render-scene-stats":
            scene_id = parts[2]
            self._send_json(handler, HTTPStatus.OK, self._opticalnav_render_scene_stats(project_dir, scene_id))
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "render-scene-materialization":
            scene_id = parts[2]
            path = project_dir / "scenes" / scene_id / "render_scene_materialization.json"
            if not path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {
                    "error": "render_scene_materialization.json not found. Run Sync Render Scene.",
                    "scene_id": scene_id,
                })
                return True
            try:
                payload = _read_json(path)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, payload)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "xml-scene-index":
            scene_id = parts[2]
            path = project_dir / "scenes" / scene_id / "xml_scene_index.json"
            if not path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {
                    "error": "xml_scene_index.json not found. Run Sync Render Scene.",
                    "scene_id": scene_id,
                })
                return True
            try:
                payload = _read_json(path)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, payload)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "material-debug":
            scene_id = parts[2]
            prim_path = _maybe_str((query.get("prim_path") or [None])[0])
            usd_ref = _maybe_str((query.get("usd_ref") or [None])[0])
            if not prim_path or not usd_ref:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {
                    "error": "prim_path and usd_ref query params required",
                })
                return True
            try:
                res = self._ensure_prim_obj_cached(project_dir, scene_id, usd_ref, prim_path)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return True
            if res is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {
                    "error": "prim mesh not extractable",
                    "scene_id": scene_id, "usd_ref": usd_ref, "prim_path": prim_path,
                })
                return True
            _obj_path, meta = res
            self._send_json(handler, HTTPStatus.OK, {
                "ok": True,
                "scene_id": scene_id,
                "usd_ref": usd_ref,
                "prim_path": prim_path,
                "obj_ref": _obj_path.relative_to(self.repo_root).as_posix()
                    if self.repo_root in _obj_path.parents else str(_obj_path),
                "writer_version": meta.get("writer_version"),
                "has_uv": meta.get("has_uv"),
                "has_normal": meta.get("has_normal"),
                "extracted_material": meta.get("extracted_material"),
            })
            return True
        if len(parts) == 6 and parts[1] == "scenes" and parts[3] == "observations" and parts[5] in self._OPTICALNAV_OBS_PNG_FILENAMES:
            scene_id = parts[2]
            vp_id = parts[4]
            modality = parts[5]
            heading_id = _maybe_str((query.get("heading") or [None])[0]) or ""
            sensor_id = _maybe_str((query.get("sensor_id") or [None])[0])
            if not heading_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "heading query param required"})
                return True
            png_bytes = self._opticalnav_observation_modality_png(project_dir, scene_id, vp_id, heading_id, modality, sensor_id=sensor_id)
            if png_bytes is None:
                suffix = f" for sensor_id={sensor_id}" if sensor_id else ""
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"{modality} preview not found{suffix}"})
                return True
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "image/png")
            handler.send_header("Content-Length", str(len(png_bytes)))
            handler.send_header("Cache-Control", "public, max-age=3600")
            handler.end_headers()
            handler.wfile.write(png_bytes)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "envmaps":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            envmap_dir = scene_dir / "envmaps"
            files = []
            if envmap_dir.exists():
                for item in sorted(envmap_dir.iterdir(), key=lambda p: p.name.lower()):
                    if item.is_file() and item.suffix.lower() in {".exr", ".hdr", ".png", ".jpg", ".jpeg"}:
                        try:
                            ref = item.relative_to(self.repo_root).as_posix()
                        except ValueError:
                            ref = item.as_posix()
                        files.append({
                            "filename": item.name,
                            "envmap_ref": ref,
                            "size_bytes": item.stat().st_size,
                            "updated_at": datetime.fromtimestamp(item.stat().st_mtime, timezone.utc).isoformat(),
                            "previewable": item.suffix.lower() in {".png", ".jpg", ".jpeg"},
                        })
            self._send_json(handler, HTTPStatus.OK, {"ok": True, "scene_id": scene_id, "envmaps": files})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "envmaps":
            # GET /scenes/<scene_id>/envmaps/<filename> — serve raw bytes for UI preview.
            # EXR/HDR aren't browser-renderable but we still return them so an external tool
            # could fetch; the UI only attempts <img> for png/jpg.
            scene_id = parts[2]
            filename = unquote(parts[4])
            envmap_dir = project_dir / "scenes" / scene_id / "envmaps"
            target = envmap_dir / filename
            try:
                target_resolved = target.resolve()
                envmap_dir_resolved = envmap_dir.resolve()
            except OSError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "envmap not found"})
                return True
            # Defense: keep the lookup inside scenes/<id>/envmaps/.
            if envmap_dir_resolved not in target_resolved.parents:
                self._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "envmap path outside scene dir"})
                return True
            if not target_resolved.is_file():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "envmap not found"})
                return True
            mime, _ = mimetypes.guess_type(target_resolved.name)
            if not mime:
                mime = "application/octet-stream"
            data = target_resolved.read_bytes()
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", mime)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "public, max-age=3600")
            handler.end_headers()
            handler.wfile.write(data)
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "mesh-cache":
            # PR2: GET /scenes/<scene_id>/mesh-cache/<filename> — serve OBJ text bytes
            # so the editor's OBJLoader can render the actual render-side mesh instead
            # of a fallback box. Pattern mirrors the envmaps endpoint above.
            scene_id = parts[2]
            filename = unquote(parts[4])
            # Clamp to a basename; reject any path component (../ etc.) up front.
            if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid mesh-cache filename"})
                return True
            mesh_cache_dir = project_dir / "scenes" / scene_id / "mesh_cache"
            target = mesh_cache_dir / filename
            try:
                target_resolved = target.resolve()
                mesh_cache_dir_resolved = mesh_cache_dir.resolve()
            except OSError:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "mesh-cache file not found"})
                return True
            # Defense in depth: even after basename clamp, confirm the resolved file
            # sits inside the scene's mesh_cache dir.
            if mesh_cache_dir_resolved not in target_resolved.parents:
                self._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "mesh-cache path outside scene dir"})
                return True
            if not target_resolved.is_file():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "mesh-cache file not found"})
                return True
            data = target_resolved.read_bytes()
            handler.send_response(HTTPStatus.OK)
            # mesh_cache OBJ filenames already encode (usd_ref|prim_path|mtime|writer_version)
            # so the content is effectively immutable — cache aggressively.
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "public, max-age=86400, immutable")
            # Multi-MB OBJs over ThreadingHTTPServer reliably surfaced
            # ERR_CONTENT_LENGTH_MISMATCH in the browser even though len(data)
            # matched the file. Root cause: BaseHTTPRequestHandler's default
            # protocol_version is HTTP/1.0, which closes the TCP connection
            # immediately on handler return. With multi-MB bodies + multiple
            # concurrent fetches per origin, the close FIN can arrive before
            # the tail of the body is fully ACKed, and the browser flags the
            # delta as a content-length mismatch. Sending `Connection: close`
            # under HTTP/1.0 plus calling `socket.sendall()` directly (rather
            # than going through the wfile wrapper) lets us drain the entire
            # body before any teardown. We also do a graceful half-close
            # (shutdown WR) so the kernel flushes the send buffer before close.
            handler.send_header("Connection", "close")
            handler.end_headers()
            try:
                handler.wfile.flush()
            except OSError:
                pass
            try:
                handler.connection.sendall(data)
            except (BrokenPipeError, ConnectionResetError):
                return True
            try:
                import socket as _socket
                handler.connection.shutdown(_socket.SHUT_WR)
            except OSError:
                pass
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "render-readiness":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            readiness_path = scene_dir / "render_readiness.json"
            if not readiness_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"ok": False, "error": "render_readiness.json not found. Run Sync Render Scene."})
                return True
            self._send_json(handler, HTTPStatus.OK, _read_json(readiness_path))
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "render-config":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            saved_path = scene_dir / "render_config.json"
            if saved_path.exists():
                self._send_json(handler, HTTPStatus.OK, {**_read_json(saved_path), "source": "saved"})
            else:
                result = self._opticalnav_derive_render_config(project_dir, scene_id)
                status = HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND
                self._send_json(handler, status, result)
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "agent-context":
            from navigation_dataset.authoring_map import (
                AuthoringMapValidationError,
                authoring_map_to_payload,
                load_authoring_map,
                starter_authoring_map,
                validate_authoring_map,
            )

            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            if map_path.exists():
                authoring_map = load_authoring_map(map_path)
            else:
                authoring_map = starter_authoring_map(scene_id, None)
            compile_ready = False
            compile_blockers: list[dict] = []
            try:
                validate_authoring_map(authoring_map, require_compile_ready=True)
                compile_ready = True
            except AuthoringMapValidationError as exc:
                compile_blockers = [issue.to_payload() for issue in exc.issues]
            annotation_path = scene_dir / "scene_annotation.json"
            graph_path = scene_dir / "viewpoint_graph.json"
            dataset_json = project_dir / "dataset.json"
            sync = _read_json(scene_dir / "scene_variant.json").get("sync") if (scene_dir / "scene_variant.json").exists() else None
            suggested: list[str] = []
            if not compile_ready:
                suggested.append("add_traversable_region_and_goal_region")
            elif not annotation_path.exists():
                suggested.append("compile_authoring_map")
            elif not graph_path.exists():
                suggested.append("build_traversability_map")
                suggested.append("build_viewpoint_graph")
            else:
                suggested.append("plan_graph_episodes")
            context = {
                "scene_id": scene_id,
                "project_id": parts[0],
                "sync": sync,
                "compile_ready": compile_ready,
                "compile_blockers": compile_blockers,
                "objects": [
                    {"id": obj.id, "type": obj.type, "label": obj.label, "geometry": self._geom_summary(obj.geometry), "material": obj.material}
                    for obj in authoring_map.objects
                ],
                "regions": [
                    {"id": reg.id, "type": reg.type, "label": reg.label, "geometry": self._geom_summary(reg.geometry)}
                    for reg in authoring_map.regions
                ],
                "artifacts": {
                    "authoring_map": map_path.exists(),
                    "annotation": annotation_path.exists(),
                    "graph": graph_path.exists(),
                },
                "suggested_actions": suggested,
                "asset_generation_rules": {
                    "default": "Use active Asset Library assets with usable_by_agent=true. Do not place primitive proxy furniture for final scenes.",
                    "allowed_render_readiness": sorted(self._ASSET_READINESS_USABLE),
                    "asset_endpoint": "/api/opticalnav/agent/assets",
                    "object_create_contract": "Pass asset_id or source_ref for furniture/landmark objects so mesh, texture, and render metadata are preserved.",
                },
            }
            self._send_json(handler, HTTPStatus.OK, context)
            return True
        return False

    def _handle_opticalnav_post(self, handler: BaseHTTPRequestHandler, path: str, payload: Mapping[str, Any]) -> bool:
        if path == "/api/opticalnav/asset-library/import":
            usd_ref = _maybe_str(payload.get("usd_ref") or payload.get("source_ref") or payload.get("glb_ref"))
            if not usd_ref:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "usd_ref/source_ref is required."})
                return True
            try:
                if usd_ref.lower().endswith(".glb"):
                    result = self._opticalnav_import_dtc_glb_source(usd_ref, force=self._coerce_bool(payload.get("force"), False))
                else:
                    result = self._opticalnav_import_asset_library_source(usd_ref, force=self._coerce_bool(payload.get("force"), False))
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, result)
            return True
        if path == "/api/opticalnav/asset-library/assets/bulk-select":
            ids = {str(item) for item in (payload.get("asset_ids") or [])}
            selected = self._coerce_bool(payload.get("selected"), True)
            store = self._read_asset_selection_store()
            overrides = dict(store.get("assets", {}))
            known = {str(asset.get("asset_id")) for asset in self._opticalnav_all_asset_library_assets()}
            changed = 0
            for asset_id in ids:
                if asset_id not in known:
                    continue
                entry = dict(overrides.get(asset_id, {}))
                entry["selected"] = selected
                overrides[asset_id] = entry
                changed += 1
            self._write_asset_selection_store({"assets": overrides})
            self._send_json(handler, HTTPStatus.OK, {"ok": True, "changed": changed, "selected": selected})
            return True
        if path == "/api/opticalnav/agent/assets/activation":
            result = self._opticalnav_apply_agent_asset_activation(payload)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._send_json(handler, status, result)
            return True
        if path == "/api/opticalnav/projects":
            from navigation_dataset.episode_schema import DatasetProject, write_project

            project_name = str(payload.get("project_name") or "OpticalNav-v0.1")
            project_id = self._safe_opticalnav_project_id(project_name)
            project_dir = self._opticalnav_project_dir(project_id)
            if project_dir.exists() and (project_dir / "dataset.json").exists():
                self._send_json(handler, HTTPStatus.CONFLICT, {"error": f"Project already exists: {project_id}", "project_id": project_id})
                return True
            self._opticalnav_create_layout(project_dir)
            project = DatasetProject(
                project_name=project_name,
                dataset_type=str(payload.get("dataset_type") or "Synthetic fine-tuning dataset"),
                target_scenario=str(payload.get("target_scenario") or "glass / mirror / transparent partition navigation"),
                robot_profile=str(payload.get("robot_profile") or "mobile_base_front_camera"),
                modalities=[str(item) for item in payload.get("modalities", ["rgb", "depth", "active_nir_intensity", "hazard_mask"])],
                metadata={"project_id": project_id, "created_at": _utc_now_iso()},
            )
            write_project(project_dir / "dataset.json", project)
            self._send_json(handler, HTTPStatus.CREATED, self._opticalnav_project_summary(project_dir))
            return True
        if not path.startswith("/api/opticalnav/projects/"):
            return False
        rest = path[len("/api/opticalnav/projects/"):].strip("/")
        parts = [unquote(part) for part in rest.split("/") if part]
        if not parts:
            return False
        try:
            project_dir = self._opticalnav_project_dir(parts[0])
        except ValueError as exc:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if not project_dir.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav project_id: {parts[0]}"})
            return True
        if len(parts) == 2 and parts[1] == "scenes":
            from navigation_dataset.episode_schema import read_project, write_project

            scene_id = str(payload.get("scene_id") or "").strip()
            if not scene_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "scene_id is required."})
                return True
            usd_ref = _maybe_str(payload.get("usd_ref"))
            scene_dir = project_dir / "scenes" / scene_id
            scene_dir.mkdir(parents=True, exist_ok=True)
            annotation_path = scene_dir / "scene_annotation.json"
            if not annotation_path.exists():
                annotation_path.write_text(json.dumps(self._opticalnav_starter_annotation(scene_id, usd_ref), ensure_ascii=False, indent=2), encoding="utf-8")
            dataset_path = project_dir / "dataset.json"
            if dataset_path.exists():
                project = read_project(dataset_path)
                scenes = [item for item in project.scenes if not (isinstance(item, Mapping) and item.get("scene_id") == scene_id) and item != scene_id]
                scenes.append({"scene_id": scene_id, "usd_ref": usd_ref, "annotation_ref": f"scenes/{scene_id}/scene_annotation.json"})
                project.scenes = scenes
                write_project(dataset_path, project)
            self._send_json(handler, HTTPStatus.CREATED, {"scene_id": scene_id, "annotation": _read_json(annotation_path), "project": self._opticalnav_project_summary(project_dir)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "envmaps":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            filename = str(payload.get("filename") or "").strip()
            data_b64 = str(payload.get("data_base64") or payload.get("content_base64") or "").strip()
            if not filename or not data_b64:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "filename and data_base64 are required."})
                return True
            suffix = Path(filename).suffix.lower()
            if suffix not in {".exr", ".hdr", ".png", ".jpg", ".jpeg"}:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Envmap must be .exr, .hdr, .png, .jpg, or .jpeg."})
                return True
            if "," in data_b64 and data_b64.lower().startswith("data:"):
                data_b64 = data_b64.split(",", 1)[1]
            try:
                blob = base64.b64decode(data_b64, validate=True)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Invalid base64 payload: {exc}"})
                return True
            if not blob:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Uploaded envmap is empty."})
                return True
            max_bytes = int(os.environ.get("ROBOMITUBA_ENVMAP_UPLOAD_MAX_BYTES", str(256 * 1024 * 1024)))
            if len(blob) > max_bytes:
                self._send_json(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"Envmap upload exceeds {max_bytes} bytes."})
                return True
            stem = Path(filename).stem or "envmap"
            safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in stem).strip("-.") or "envmap"
            digest = hashlib.sha1(blob).hexdigest()[:10]
            out_dir = scene_dir / "envmaps"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{safe_stem[:64]}-{digest}{suffix}"
            out_path.write_bytes(blob)
            try:
                envmap_ref = out_path.relative_to(self.repo_root).as_posix()
            except ValueError:
                envmap_ref = out_path.as_posix()
            self._send_json(handler, HTTPStatus.CREATED, {
                "ok": True,
                "scene_id": scene_id,
                "filename": out_path.name,
                "envmap_ref": envmap_ref,
                "size_bytes": len(blob),
                "content_type": payload.get("content_type") or mimetypes.guess_type(out_path.name)[0] or "application/octet-stream",
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "sync" and parts[4] == "render-scene":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            annotation_path = scene_dir / "scene_annotation.json"
            if not map_path.exists():
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "authoring_map.json is required before render-scene sync."})
                return True
            if not annotation_path.exists():
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "scene_annotation.json is required before render-scene sync."})
                return True
            # Decide sync vs async (default async). Legacy: ?sync=true → inline.
            query_str = urlparse(handler.path).query or ""
            qparams = parse_qs(query_str)
            inline = (qparams.get("sync", ["false"])[0]).lower() in ("1", "true", "yes")
            if inline:
                status_code, body = self._run_render_scene_sync_inner(project_dir, scene_id, payload, sync_job_id=None, progress_cb=None)
                self._send_json(handler, status_code, body)
                return True
            sync_job_id = f"sync-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}-{hashlib.sha1(str(scene_dir).encode()).hexdigest()[:6]}"
            self._patch_opticalnav_annotation_sync(project_dir, scene_id, {
                "render_scene": "pending",
                "render_scene_status": "syncing",
                "render_readiness_status": "pending",
                "sync_job_id": sync_job_id,
                "message": "Render-scene sync is running.",
            })
            self._publish_opticalnav_sync_progress(sync_job_id, {
                "status": "started",
                "processed": 0,
                "total": 0,
                "stage": "queued",
            })

            def _bg() -> None:
                try:
                    status_code, body = self._run_render_scene_sync_inner(
                        project_dir, scene_id, dict(payload),
                        sync_job_id=sync_job_id,
                        progress_cb=lambda p, t, label, stage: self._publish_opticalnav_sync_progress(sync_job_id, {
                            "status": "running",
                            "processed": int(p),
                            "total": int(t),
                            "label": label,
                            "stage": stage,
                        }),
                    )
                    self._publish_opticalnav_sync_progress(sync_job_id, {
                        "status": "done" if status_code == int(HTTPStatus.OK) else "error",
                        "result": body,
                        "status_code": int(status_code),
                    })
                except Exception as exc:
                    self._patch_opticalnav_annotation_sync(project_dir, scene_id, {
                        "render_scene": "blocked",
                        "render_scene_status": "error",
                        "render_readiness_status": "blocked",
                        "sync_job_id": sync_job_id,
                        "message": f"Render-scene sync failed: {exc}",
                    })
                    self._publish_opticalnav_sync_progress(sync_job_id, {
                        "status": "error",
                        "result": {"error": str(exc)},
                        "status_code": int(HTTPStatus.INTERNAL_SERVER_ERROR),
                    })

            threading.Thread(target=_bg, name=f"opticalnav-sync-{sync_job_id}", daemon=True).start()
            self._send_json(handler, HTTPStatus.ACCEPTED, {
                "ok": True,
                "sync_job_id": sync_job_id,
                "scene_id": scene_id,
                "ws_url": f"/api/ws/opticalnav-sync-progress?sync_job_id={sync_job_id}",
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "sync" and parts[4] == "isaac-stage":
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            variant_path = scene_dir / "scene_variant.json"
            overlay_path = scene_dir / "render_scene_overlays.json"
            if not variant_path.exists() or not overlay_path.exists():
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {
                    "ok": False,
                    "stage": "sync_isaac_stage",
                    "status": "blocked",
                    "message": "Render-scene artifacts are required before Isaac stage sync.",
                    "missing": [
                        {
                            "key": "scene_variant",
                            "label": "scene_variant.json",
                            "reason": "Run Sync Render Scene first.",
                            "action": "sync_render_scene",
                        }
                    ],
                })
                return True
            try:
                scene_variant = _read_json(variant_path)
                overlay = _read_json(overlay_path)
                command = self._queue_isaac_command({
                    "command_type": "sync_opticalnav_stage",
                    "scene_id": scene_id,
                    "payload": {
                        "project_id": project_dir.name,
                        "scene_id": scene_id,
                        "scene_variant_ref": variant_path.relative_to(project_dir).as_posix(),
                        "render_scene_overlay_ref": overlay_path.relative_to(project_dir).as_posix(),
                        "scene_variant": scene_variant,
                        "overlay": overlay,
                    },
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.ACCEPTED, {
                "ok": True,
                "stage": "sync_isaac_stage",
                "status": "queued",
                "message": "Isaac stage sync command queued. Keep the Isaac extension connected to apply it.",
                "command": command,
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "map" and parts[4] == "build":
            from navigation_dataset.scene_annotations import read_scene_annotation
            from navigation_dataset.traversability import build_traversability_grid, save_traversability_grid, write_nav_graph
            from navigation_dataset.walkability_overlay import load_overlay as _load_walk_overlay

            annotation_path = project_dir / "scenes" / parts[2] / "scene_annotation.json"
            overlay_path = annotation_path.parent / "walkability_overlay.npy"
            scene_overlay_objects = _load_scene_overlay_objects(annotation_path.parent)
            try:
                annotation = read_scene_annotation(annotation_path)
                # Build a tentative grid first to learn its GridSpec, then re-merge
                # the user overlay if its shape still matches.
                grid = build_traversability_grid(annotation, resolution=float(payload.get("resolution", 0.05)), objects=scene_overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
                overlay = _load_walk_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                if overlay is not None:
                    grid = build_traversability_grid(annotation, resolution=float(payload.get("resolution", 0.05)), walkability_overlay=overlay, objects=scene_overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            grid_path = save_traversability_grid(annotation_path.parent / "traversable_grid.npy", grid)
            graph_path = write_nav_graph(annotation_path.parent / "nav_graph.json", grid)
            graph = _read_json(graph_path)
            self._send_json(handler, HTTPStatus.OK, {
                "scene_id": parts[2],
                "grid_ref": grid_path.relative_to(project_dir).as_posix(),
                "sidecar_ref": grid_path.with_suffix(grid_path.suffix + ".json").relative_to(project_dir).as_posix(),
                "nav_graph_ref": graph_path.relative_to(project_dir).as_posix(),
                "node_count": len(graph.get("nodes", [])),
                "edge_count": len(graph.get("edges", [])),
                "grid": graph.get("grid"),
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "build":
            from navigation_dataset.edge_builder import build_viewpoint_edges, graph_summary
            from navigation_dataset.node_sampler import sample_viewpoint_nodes
            from navigation_dataset.traversability import build_traversability_grid, load_traversability_grid, save_traversability_grid
            from navigation_dataset.viewpoint_graph import ViewpointGraph, write_viewpoint_graph
            from navigation_dataset.walkability_overlay import load_overlay as _load_walk_overlay

            scene_id = parts[2]
            progress_key = f"{project_dir}/{scene_id}"

            def _set_progress(stage: str, frac: float) -> None:
                state = {"stage": stage, "progress": round(frac, 3), "status": "building"}
                with self._graph_build_lock:
                    self._graph_build_progress[progress_key] = state
                # Push to WebSocket subscribers (best-effort, non-blocking).
                with self._graph_build_sub_lock:
                    subs = list(self._graph_build_subscribers.get(progress_key, set()))
                stale: list[_GraphBuildSubscriber] = []
                for sub in subs:
                    try:
                        sub.send_json(state)
                    except Exception:
                        stale.append(sub)
                if stale:
                    with self._graph_build_sub_lock:
                        bucket = self._graph_build_subscribers.get(progress_key, set())
                        for sub in stale:
                            bucket.discard(sub)

            _set_progress("nodes", 0.0)
            try:
                # Always rebuild the traversability grid from the current annotation so that
                # obstacles added since the last explicit "Build Map" are respected.
                annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
                grid_path = project_dir / "scenes" / scene_id / "traversable_grid.npy"
                _overlay_objects = _load_scene_overlay_objects(annotation_path.parent)
                if annotation_path.exists():
                    from navigation_dataset.scene_annotations import read_scene_annotation
                    _annotation = read_scene_annotation(annotation_path)
                    grid_resolution = float(payload.get("resolution", 0.05))
                    grid = build_traversability_grid(_annotation, resolution=grid_resolution, objects=_overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
                    overlay_path = annotation_path.parent / "walkability_overlay.npy"
                    overlay = _load_walk_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                    if overlay is not None:
                        grid = build_traversability_grid(_annotation, resolution=grid_resolution, walkability_overlay=overlay, objects=_overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
                    save_traversability_grid(grid_path, grid)
                else:
                    grid = load_traversability_grid(grid_path)
                heading_count = int(payload.get("heading_count", 12))
                # Doorway / passage thresholds get a guaranteed viewpoint. Doors
                # are usually line geometry → use the segment midpoint.
                _door_seeds: list[tuple[float, float]] = []
                for o in (_overlay_objects or []):
                    if str(o.get("type") or "") not in {"glass_door", "door"}:
                        continue
                    g = o.get("geometry") or {}
                    c = g.get("center")
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        _door_seeds.append((float(c[0]), float(c[1])))
                        continue
                    s, e = g.get("start"), g.get("end")
                    if isinstance(s, (list, tuple)) and isinstance(e, (list, tuple)):
                        _door_seeds.append(((float(s[0]) + float(e[0])) / 2.0, (float(s[1]) + float(e[1])) / 2.0))
                nodes = sample_viewpoint_nodes(
                    grid,
                    max_nodes=int(payload.get("max_nodes", 300)),
                    heading_count=heading_count,
                    min_node_spacing_m=float(payload.get("min_node_spacing_m", 0.5)),
                    min_clearance_m=float(payload.get("min_clearance_m", 0.0)),
                    robot_radius_m=float(payload.get("robot_radius_m", 0.25)),
                    seed=int(payload.get("seed", 0)),
                    opening_seeds=_door_seeds or None,
                    on_progress=lambda f: _set_progress("nodes", f * 0.5),
                )
                # Safety-net prune: drop any node that still lands inside an object
                # footprint (should be ~0 now that the grid masks footprints).
                if bool(payload.get("prune_overlapping", True)) and _overlay_objects:
                    from navigation_dataset.viewpoint_graph import (
                        ViewpointGraph as _VG, find_object_overlapping_nodes as _find_ov, remove_nodes as _rm,
                    )
                    _tmp = _VG(scene_id=scene_id, graph_id="tmp", node_heading_count=heading_count, nodes=nodes)
                    _ov = _find_ov(_tmp, _overlay_objects, margin_m=float(payload.get("prune_margin_m", 0.0)))
                    if _ov:
                        _rm(_tmp, _ov)
                        nodes = _tmp.nodes
                _set_progress("edges", 0.5)
                edges = build_viewpoint_edges(
                    grid,
                    nodes,
                    robot_radius_m=float(payload.get("robot_radius_m", 0.25)),
                    k_neighbors=int(payload.get("k_neighbors", 8)),
                    max_edge_length_m=float(payload.get("max_edge_length_m", 1.5)),
                    on_progress=lambda f: _set_progress("edges", 0.5 + f * 0.5),
                )
                graph = ViewpointGraph(
                    scene_id=scene_id,
                    graph_id=str(payload.get("graph_id") or f"{scene_id}_vg_{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"),
                    node_heading_count=heading_count,
                    nodes=nodes,
                    edges=edges,
                    metadata={
                        "generation_version": "opticalnav-v0.2",
                        "built_at": _utc_now_iso(),
                        "robot_radius_m": float(payload.get("robot_radius_m", 0.25)),
                        "min_node_spacing_m": float(payload.get("min_node_spacing_m", 0.5)),
                        "max_edge_length_m": float(payload.get("max_edge_length_m", 1.5)),
                        "k_neighbors": int(payload.get("k_neighbors", 8)),
                        "seed": int(payload.get("seed", 0)),
                        "grid_resolution_m": float(payload.get("resolution", 0.05)),
                        "scene_variant_id": payload.get("scene_variant_id"),
                    },
                )
                with self._opticalnav_graph_edit_lock(project_dir, scene_id):
                    self._bump_viewpoint_graph_revision(graph)
                    graph_path = write_viewpoint_graph(project_dir / "scenes" / scene_id / "viewpoint_graph.json", graph)
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "build_graph",
                    "graph_id": graph.graph_id,
                    "before": {"nodes": 0, "edges": 0},
                    "after": {"nodes": len(nodes), "edges": len(edges)},
                    "params": dict(graph.metadata),  # full sampler/edge-builder config snapshot
                    "algo_context": {
                        "manual_nodes": sum(1 for n in nodes if (n.extras or {}).get("manual")),
                        "hazard_edges": sum(1 for e in edges if getattr(e, "hazard_crossing", False)),
                    },
                })
            except Exception as exc:
                err_state = {"stage": "error", "progress": 0.0, "status": "error", "error": str(exc)}
                with self._graph_build_lock:
                    self._graph_build_progress[progress_key] = err_state
                with self._graph_build_sub_lock:
                    subs = list(self._graph_build_subscribers.pop(progress_key, set()))
                for sub in subs:
                    try:
                        sub.send_json(err_state)
                    except Exception:
                        pass
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            done_state = {"stage": "done", "progress": 1.0, "status": "done"}
            with self._graph_build_lock:
                self._graph_build_progress.pop(progress_key, None)
            with self._graph_build_sub_lock:
                subs = list(self._graph_build_subscribers.pop(progress_key, set()))
            for sub in subs:
                try:
                    sub.send_json(done_state)
                except Exception:
                    pass
            self._send_json(handler, HTTPStatus.OK, {
                "scene_id": scene_id,
                "graph_ref": graph_path.relative_to(project_dir).as_posix(),
                "graph_id": graph.graph_id,
                **graph_summary(nodes, edges, heading_count=heading_count),
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "rebuild-edges":
            # Re-run edge building over the CURRENT node set (auto + manual nodes
            # preserved, NOT resampled) on a footprint-masked grid. This connects
            # manually-added nodes and drops edges that now cross glass/furniture,
            # without discarding the user's hand-placed nodes.
            from navigation_dataset.edge_builder import build_viewpoint_edges, graph_summary
            from navigation_dataset.traversability import build_traversability_grid, load_traversability_grid
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph
            from navigation_dataset.walkability_overlay import load_overlay as _load_walk_overlay

            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            graph_file = scene_dir / "viewpoint_graph.json"
            if not graph_file.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            _graph_mutation_lock = self._opticalnav_graph_edit_lock(project_dir, scene_id)
            _graph_mutation_lock.acquire()
            _graph_mutation_lock_released = False
            try:
                graph = read_viewpoint_graph(graph_file)
                _before_edges = len(graph.edges)
                meta = graph.metadata or {}
                annotation_path = scene_dir / "scene_annotation.json"
                grid_path = scene_dir / "traversable_grid.npy"
                overlay_objects = _load_scene_overlay_objects(scene_dir)
                grid_resolution = float(payload.get("resolution", meta.get("grid_resolution_m", 0.05)))
                if annotation_path.exists():
                    from navigation_dataset.scene_annotations import read_scene_annotation
                    _annotation = read_scene_annotation(annotation_path)
                    grid = build_traversability_grid(_annotation, resolution=grid_resolution, objects=overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
                    overlay_path = scene_dir / "walkability_overlay.npy"
                    _walk = _load_walk_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                    if _walk is not None:
                        grid = build_traversability_grid(_annotation, resolution=grid_resolution, walkability_overlay=_walk, objects=overlay_objects, robot_height_m=float(payload.get("robot_height_m", 1.2)))
                else:
                    grid = load_traversability_grid(grid_path)
                robot_radius = float(payload.get("robot_radius_m", meta.get("robot_radius_m", 0.25)))
                k_neighbors = int(payload.get("k_neighbors", meta.get("k_neighbors", 8)))
                max_edge = float(payload.get("max_edge_length_m", meta.get("max_edge_length_m", 1.5)))
                new_edges = build_viewpoint_edges(
                    grid, graph.nodes, robot_radius_m=robot_radius, k_neighbors=k_neighbors, max_edge_length_m=max_edge,
                )
                # Keep manual edges that the auto pass didn't reproduce.
                if bool(payload.get("preserve_manual_edges", True)):
                    have = {(e.source, e.target) for e in new_edges}
                    have |= {(e.target, e.source) for e in new_edges}
                    for e in graph.edges:
                        is_manual = bool((e.extras or {}).get("manual")) or str(e.edge_id).startswith("edge_manual")
                        if is_manual and (e.source, e.target) not in have:
                            new_edges.append(e)
                            have.add((e.source, e.target))
                            have.add((e.target, e.source))
                graph.edges = new_edges
                meta["edges_rebuilt_at"] = _utc_now_iso()
                graph.metadata = meta
                self._bump_viewpoint_graph_revision(graph)
                write_viewpoint_graph(graph_file, graph)
                _graph_mutation_lock.release()
                _graph_mutation_lock_released = True
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "rebuild_edges",
                    "graph_id": graph.graph_id,
                    "before": {"nodes": len(graph.nodes), "edges": _before_edges},
                    "after": {"nodes": len(graph.nodes), "edges": len(graph.edges)},
                    "params": {"resolution": grid_resolution, "robot_radius_m": robot_radius,
                               "k_neighbors": k_neighbors, "max_edge_length_m": max_edge,
                               "preserve_manual_edges": bool(payload.get("preserve_manual_edges", True))},
                    "algo_context": {
                        "manual_preserved_count": sum(1 for e in graph.edges if (e.extras or {}).get("manual") or str(e.edge_id).startswith("edge_manual")),
                        "hazard_edges": sum(1 for e in graph.edges if getattr(e, "hazard_crossing", False)),
                    },
                })
                self._send_json(handler, HTTPStatus.OK, {
                    "scene_id": scene_id,
                    "graph_id": graph.graph_id,
                    **graph_summary(graph.nodes, graph.edges, heading_count=graph.node_heading_count),
                })
            except Exception as exc:
                if not _graph_mutation_lock_released:
                    _graph_mutation_lock.release()
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "edits":
            status, response = self._apply_opticalnav_graph_edits(handler, project_dir, parts[2], payload)
            self._send_json(handler, status, response)
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "sweep":
            self._handle_opticalnav_graph_sweep(handler, project_dir, parts[2], payload)
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "nodes":
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph, append_manual_node
            scene_id = parts[2]
            graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            try:
                from navigation_dataset.graph_edit_log import graph_size as _gsz, nearest_node_distance as _nnd
                with self._opticalnav_graph_edit_lock(project_dir, scene_id):
                    graph = read_viewpoint_graph(graph_path)
                    _before = _gsz(graph)
                    x = float(payload.get("x", 0.0))
                    y = float(payload.get("y", 0.0))
                    node = append_manual_node(
                        graph, x, y,
                        heading_count=int(payload["heading_count"]) if payload.get("heading_count") is not None else None,
                    )
                    self._bump_viewpoint_graph_revision(graph)
                    write_viewpoint_graph(graph_path, graph)
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "add_node",
                    "graph_id": getattr(graph, "graph_id", None),
                    "before": _before, "after": _gsz(graph),
                    "params": {"x": x, "y": y, "heading_count": payload.get("heading_count")},
                    "added_node": {"id": node.node_id, "position": [x, y], "headings": len(node.headings)},
                    "algo_context": {"nearest_existing_node_m": _nnd(graph, x, y, exclude=[node.node_id])},
                })
                self._send_json(handler, HTTPStatus.OK, {"node_id": node.node_id, "position": node.position, "headings": len(node.headings)})
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if (
            len(parts) == 6
            and parts[1] == "scenes"
            and parts[3] == "walkability-overlay"
            and parts[4] == "paint"
        ):
            # POST .../walkability-overlay/paint  body: {brush, points: [[x,y]...], radius_m}
            from navigation_dataset.traversability import load_traversability_grid
            from navigation_dataset.walkability_overlay import (
                OVERLAY_VALUE_BLOCKED, OVERLAY_VALUE_ERASE, OVERLAY_VALUE_WALKABLE,
                load_overlay, make_empty_overlay, paint_circle, paint_rectangle,
                paint_strokes, save_overlay, overlay_stats,
            )
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            grid_path = scene_dir / "traversable_grid.npy"
            if not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build the traversable grid first."})
                return True
            try:
                grid = load_traversability_grid(grid_path)
                overlay_path = scene_dir / "walkability_overlay.npy"
                overlay = load_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                if overlay is None:
                    overlay = make_empty_overlay(grid.spec)
                brush_raw = str(payload.get("brush") or "walkable").lower()
                value = {
                    "walkable": OVERLAY_VALUE_WALKABLE,
                    "blocked": OVERLAY_VALUE_BLOCKED,
                    "erase": OVERLAY_VALUE_ERASE,
                }.get(brush_raw, OVERLAY_VALUE_WALKABLE)
                radius_m = float(payload.get("radius_m") or 0.25)
                shape = str(payload.get("shape") or "stroke").lower()
                if shape == "rectangle":
                    bb = payload.get("bbox") or [0, 0, 0, 0]
                    paint_rectangle(
                        overlay, grid.spec,
                        min_x=float(bb[0]), min_y=float(bb[1]),
                        max_x=float(bb[2]), max_y=float(bb[3]),
                        value=value,
                    )
                else:
                    pts_raw = payload.get("points") or []
                    pts: list[tuple[float, float]] = []
                    for item in pts_raw:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            try:
                                pts.append((float(item[0]), float(item[1])))
                            except (TypeError, ValueError):
                                continue
                    if not pts and payload.get("x") is not None and payload.get("y") is not None:
                        paint_circle(overlay, grid.spec,
                                     world_x=float(payload["x"]), world_y=float(payload["y"]),
                                     radius_m=radius_m, value=value)
                    else:
                        paint_strokes(overlay, grid.spec, points=pts, radius_m=radius_m, value=value)
                save_overlay(overlay_path, overlay)
                self._send_json(handler, HTTPStatus.OK, {
                    "ok": True,
                    "scene_id": scene_id,
                    "stats": overlay_stats(overlay),
                    "overlay_png_url": f"/api/opticalnav/projects/{parts[0]}/scenes/{scene_id}/walkability-overlay.png",
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "regenerate-region":
            from navigation_dataset.traversability import load_traversability_grid
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph
            from navigation_dataset.node_sampler import sample_viewpoint_nodes
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            graph_path = scene_dir / "viewpoint_graph.json"
            grid_path = scene_dir / "traversable_grid.npy"
            if not graph_path.exists() or not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build map + graph first."})
                return True
            bbox = payload.get("bbox") or [0, 0, 0, 0]
            try:
                bb_min_x, bb_min_y, bb_max_x, bb_max_y = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            except (TypeError, ValueError, IndexError):
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "bbox must be [min_x, min_y, max_x, max_y]"})
                return True
            _graph_mutation_lock = self._opticalnav_graph_edit_lock(project_dir, scene_id)
            _graph_mutation_lock.acquire()
            _graph_mutation_lock_released = False
            try:
                graph = read_viewpoint_graph(graph_path)
                _before_edges_regen = len(graph.edges)
                grid = load_traversability_grid(grid_path)
                # Build a region mask that's only true inside the requested bbox.
                from navigation_dataset.traversability import world_to_cell as _w2c
                cx0, cy0 = _w2c(grid.spec, min(bb_min_x, bb_max_x), min(bb_min_y, bb_max_y))
                cx1, cy1 = _w2c(grid.spec, max(bb_min_x, bb_max_x), max(bb_min_y, bb_max_y))
                import numpy as _np
                region_mask = _np.zeros_like(grid.traversable, dtype=bool)
                region_mask[max(0, cy0): min(grid.spec.height, cy1 + 1), max(0, cx0): min(grid.spec.width, cx1 + 1)] = True
                # Remove existing AUTO (non-manual) nodes in bbox.
                before = len(graph.nodes)
                graph.nodes = [
                    n for n in graph.nodes
                    if (n.extras.get("manual") if isinstance(n.extras, dict) else False)
                    or not (bb_min_x <= float(n.position[0]) <= bb_max_x and bb_min_y <= float(n.position[1]) <= bb_max_y)
                ]
                removed_nodes = before - len(graph.nodes)
                # Sample new nodes only within the masked region.
                new_nodes = sample_viewpoint_nodes(
                    grid,
                    max_nodes=int(payload.get("max_nodes") or 60),
                    min_node_spacing_m=float(payload.get("min_node_spacing_m") or 0.5),
                    min_clearance_m=float(payload.get("min_clearance_m") or 0.0),
                    robot_radius_m=float(payload.get("robot_radius_m") or 0.25),
                    heading_count=int(payload.get("heading_count") or 8),
                    seed=int(payload.get("seed") or 0),
                    region_mask=region_mask,
                )
                # Append (rename ids that already exist to keep things unique).
                existing_ids = {n.node_id for n in graph.nodes}
                added = 0
                for n in new_nodes:
                    if n.node_id in existing_ids:
                        i = 1
                        while f"{n.node_id}_r{i}" in existing_ids:
                            i += 1
                        n.node_id = f"{n.node_id}_r{i}"
                    existing_ids.add(n.node_id)
                    n.extras = {**(n.extras or {}), "regenerated_region": True}
                    graph.nodes.append(n)
                    added += 1
                # Drop edges with endpoints in bbox (simplistic but effective for MVP).
                kept_edges = []
                removed_edges = 0
                bbox_ids: set[str] = set()
                for n in graph.nodes:
                    if bb_min_x <= float(n.position[0]) <= bb_max_x and bb_min_y <= float(n.position[1]) <= bb_max_y:
                        bbox_ids.add(n.node_id)
                for e in graph.edges:
                    if e.source in bbox_ids or e.target in bbox_ids:
                        removed_edges += 1
                        continue
                    kept_edges.append(e)
                graph.edges = kept_edges
                self._bump_viewpoint_graph_revision(graph)
                write_viewpoint_graph(graph_path, graph)
                _graph_mutation_lock.release()
                _graph_mutation_lock_released = True
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "regenerate_region",
                    "graph_id": getattr(graph, "graph_id", None),
                    "before": {"nodes": before, "edges": _before_edges_regen},
                    "after": {"nodes": len(graph.nodes), "edges": len(graph.edges)},
                    "params": {"bbox": [bb_min_x, bb_min_y, bb_max_x, bb_max_y],
                               "max_nodes": int(payload.get("max_nodes") or 60),
                               "min_node_spacing_m": float(payload.get("min_node_spacing_m") or 0.5),
                               "min_clearance_m": float(payload.get("min_clearance_m") or 0.0),
                               "robot_radius_m": float(payload.get("robot_radius_m") or 0.25),
                               "heading_count": int(payload.get("heading_count") or 8),
                               "seed": int(payload.get("seed") or 0)},
                    "algo_context": {"added_nodes": added, "removed_nodes": removed_nodes,
                                     "removed_edges": removed_edges},
                })
                self._send_json(handler, HTTPStatus.OK, {
                    "ok": True,
                    "added_nodes": added,
                    "removed_nodes": removed_nodes,
                    "removed_edges": removed_edges,
                    "remaining_nodes": len(graph.nodes),
                })
            except Exception as exc:
                if not _graph_mutation_lock_released:
                    _graph_mutation_lock.release()
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "edge-check":
            # POST .../graph/edge-check  body: {source, target, robot_radius_m?, max_edge_length_m?}
            import math as _math
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, find_node
            from navigation_dataset.traversability import load_traversability_grid, inflate_traversable_grid
            from navigation_dataset.walkability_overlay import load_overlay
            from navigation_dataset.edge_builder import line_cells
            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            graph_path = scene_dir / "viewpoint_graph.json"
            grid_path = scene_dir / "traversable_grid.npy"
            if not graph_path.exists() or not grid_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Build the graph + traversable grid first."})
                return True
            source_id = str(payload.get("source") or "")
            target_id = str(payload.get("target") or "")
            if not source_id or not target_id or source_id == target_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "source/target node ids required and must differ"})
                return True
            try:
                graph = read_viewpoint_graph(graph_path)
                src = find_node(graph, source_id)
                tgt = find_node(graph, target_id)
                if src is None or tgt is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Unknown source/target node"})
                    return True
                robot_radius_m = float(payload.get("robot_radius_m") or 0.25)
                max_edge_length_m = float(payload.get("max_edge_length_m") or 1.5)
                grid = load_traversability_grid(grid_path)
                overlay_path = scene_dir / "walkability_overlay.npy"
                overlay = load_overlay(overlay_path, expected_spec=grid.spec) if overlay_path.exists() else None
                base = grid.traversable.copy()
                if overlay is not None:
                    base = (base | (overlay == 1)) & ~(overlay == 2)
                inflated = inflate_traversable_grid(base, robot_radius_m, grid.spec.resolution)
                # Distance + cell walk.
                distance_m = float(_math.hypot(float(tgt.position[0]) - float(src.position[0]), float(tgt.position[1]) - float(src.position[1])))
                within_max = distance_m <= max_edge_length_m
                cells = line_cells(grid, src.position, tgt.position)
                blocked_cells: list[dict[str, Any]] = []
                hazard_crossing = False
                for cx, cy in cells:
                    if not (0 <= cx < grid.spec.width and 0 <= cy < grid.spec.height):
                        blocked_cells.append({"cell": [int(cx), int(cy)], "reason": "out_of_bounds"})
                        continue
                    if not bool(inflated[cy, cx]):
                        # Distinguish raw obstacle vs inflation halo.
                        reason = "raw_obstacle" if not bool(base[cy, cx]) else "inflation_halo"
                        wx = float(grid.spec.origin[0]) + (cx + 0.5) * float(grid.spec.resolution)
                        wy = float(grid.spec.origin[1]) + (cy + 0.5) * float(grid.spec.resolution)
                        blocked_cells.append({"cell": [int(cx), int(cy)], "world": [round(wx, 3), round(wy, 3)], "reason": reason})
                    if bool(grid.hazard[cy, cx]):
                        hazard_crossing = True
                blocked = len(blocked_cells) > 0
                if not within_max:
                    reason = "too_far"
                elif blocked:
                    reason = "blocked_by_obstacle"
                elif hazard_crossing:
                    reason = "hazard_crossing"
                else:
                    reason = "ok"
                would_connect = within_max and not blocked
                self._send_json(handler, HTTPStatus.OK, {
                    "ok": True,
                    "source": source_id,
                    "target": target_id,
                    "would_connect": would_connect,
                    "reason": reason,
                    "distance_m": round(distance_m, 4),
                    "max_edge_length_m": max_edge_length_m,
                    "within_max_edge_length": within_max,
                    "blocked_cell_count": len(blocked_cells),
                    "first_blocked_cell": blocked_cells[0] if blocked_cells else None,
                    "hazard_crossing": hazard_crossing,
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "edges":
            # POST .../graph/edges  body: {source, target, distance_m?, weight?}
            scene_id = parts[2]
            graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            source = str(payload.get("source") or "")
            target = str(payload.get("target") or "")
            if not source or not target or source == target:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "source/target node ids required and must differ"})
                return True
            status, response = self._apply_opticalnav_graph_edits(handler, project_dir, scene_id, {
                "ops": [{
                    "type": "add_edge",
                    "source": source,
                    "target": target,
                    **({"distance_m": payload.get("distance_m")} if payload.get("distance_m") is not None else {}),
                    **({"weight": payload.get("weight")} if payload.get("weight") is not None else {}),
                }]
            })
            if status != HTTPStatus.OK:
                self._send_json(handler, status, response)
                return True
            result = next((item for item in response.get("results", []) if item.get("ok")), None)
            if not result:
                err = next((item for item in response.get("results", []) if not item.get("ok")), None) or {"error": "Could not append edge"}
                self._send_json(handler, HTTPStatus.BAD_REQUEST, err)
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "edge_id": result.get("edge_id"),
                "source": result.get("source"),
                "target": result.get("target"),
                "distance_m": result.get("distance_m"),
                "revision": response.get("revision"),
            })
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "authoring-map" and parts[4] == "compile":
            from navigation_dataset.authoring_compile import AuthoringMapCompileError, compile_authoring_map
            from navigation_dataset.authoring_map import load_authoring_map
            from navigation_dataset.scene_annotations import scene_annotation_to_payload, write_scene_annotation

            scene_id = parts[2]
            map_path = project_dir / "scenes" / scene_id / "authoring_map.json"
            if not map_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "authoring_map.json not found"})
                return True
            try:
                authoring_map = load_authoring_map(map_path)
                usd_ref = None
                dataset_path = project_dir / "dataset.json"
                if dataset_path.exists():
                    dataset = _read_json(dataset_path)
                    for scene_entry in dataset.get("scenes", []):
                        if isinstance(scene_entry, Mapping) and scene_entry.get("scene_id") == scene_id:
                            usd_ref = _maybe_str(scene_entry.get("usd_ref"))
                            break
                result = compile_authoring_map(authoring_map, usd_ref=usd_ref)
                annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
                write_scene_annotation(annotation_path, result.annotation)
            except AuthoringMapCompileError as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, exc.to_payload())
                return True
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "ok": True,
                "stage": "compile_annotation",
                "status": "done",
                "message": "Authoring map compiled to scene_annotation.json.",
                "annotation": scene_annotation_to_payload(result.annotation),
                "annotation_ref": annotation_path.relative_to(project_dir).as_posix(),
                "summary": result.summary,
                "sync": result.sync,
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 3 and parts[1] == "episodes" and parts[2] == "plan":
            from navigation_dataset.exporters.custom_json import write_dataset_index, write_split_files
            from navigation_dataset.rollout import plan_episodes, split_counts_from_spec, write_episodes
            from navigation_dataset.scene_annotations import read_scene_annotation
            from navigation_dataset.traversability import load_traversability_grid

            scene_id = str(payload.get("scene_id") or "").strip()
            if not scene_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "scene_id is required."})
                return True
            try:
                annotation = read_scene_annotation(project_dir / "scenes" / scene_id / "scene_annotation.json")
                grid = load_traversability_grid(project_dir / "scenes" / scene_id / "traversable_grid.npy")
                split_spec = payload.get("splits", {"train": int(payload.get("num_pairs", 10))})
                if isinstance(split_spec, str):
                    split_counts = split_counts_from_spec(split_spec)
                elif isinstance(split_spec, Mapping):
                    split_counts = {str(k): int(v) for k, v in split_spec.items()}
                else:
                    raise ValueError("splits must be an object or 'train:60,val_seen:10' string.")
                modalities = [str(item) for item in payload.get("modalities", ["rgb", "depth", "active_nir_intensity", "hazard_mask"])]
                instruction_types = [str(item) for item in payload.get("instruction_types", ["goal_only", "hazard_aware", "ambiguous"])]
                episodes = plan_episodes(
                    annotation=annotation,
                    grid=grid,
                    num_pairs=int(payload.get("num_pairs", sum(split_counts.values()))),
                    split_counts=split_counts,
                    instruction_types=instruction_types,
                    modalities=modalities,
                    seed=int(payload.get("seed", 0)),
                )
                written = write_episodes(project_dir, episodes)
                write_dataset_index(project_dir)
                write_split_files(project_dir)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "scene_id": scene_id,
                "planned_count": len(written),
                "episodes": [path.relative_to(project_dir).as_posix() for path in written],
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 4 and parts[1] == "graph" and parts[2] == "episodes" and parts[3] == "plan":
            from navigation_dataset.exporters.custom_json import write_dataset_index, write_split_files
            from navigation_dataset.graph_episode_sampler import GRAPH_SCENARIOS, plan_graph_episodes, write_graph_episodes
            from navigation_dataset.rollout import split_counts_from_spec
            from navigation_dataset.scene_annotations import read_scene_annotation
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph

            scene_id = str(payload.get("scene_id") or "").strip()
            if not scene_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "scene_id is required."})
                return True
            try:
                graph = read_viewpoint_graph(project_dir / "scenes" / scene_id / "viewpoint_graph.json")
                annotation_path = project_dir / "scenes" / scene_id / "scene_annotation.json"
                annotation = read_scene_annotation(annotation_path) if annotation_path.exists() else None
                split_spec = payload.get("splits", {"train": int(payload.get("num_pairs", 10))})
                if isinstance(split_spec, str):
                    split_counts = split_counts_from_spec(split_spec)
                elif isinstance(split_spec, Mapping):
                    split_counts = {str(k): int(v) for k, v in split_spec.items()}
                else:
                    raise ValueError("splits must be an object or 'train:60,val_seen:10' string.")
                scenarios = [str(item) for item in payload.get("scenarios", list(GRAPH_SCENARIOS))]
                modalities = [str(item) for item in payload.get("modalities", ["rgb", "depth", "active_nir_intensity", "hazard_mask"])]
                episodes = plan_graph_episodes(
                    graph=graph,
                    num_pairs=int(payload.get("num_pairs", sum(split_counts.values()))),
                    split_counts=split_counts,
                    scenarios=scenarios,
                    modalities=modalities,
                    annotation=annotation,
                    seed=int(payload.get("seed", 0)),
                    observations_root=project_dir / "scenes" / scene_id / "observations",
                )
                written = write_graph_episodes(project_dir, episodes)
                write_dataset_index(project_dir)
                write_split_files(project_dir)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "scene_id": scene_id,
                "planned_count": len(written),
                "mode": "viewpoint_graph",
                "episodes": [path.relative_to(project_dir).as_posix() for path in written],
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 3 and parts[1] == "episodes" and parts[2] == "render":
            self._handle_opticalnav_render(handler, project_dir, payload)
            return True
        if len(parts) == 2 and parts[1] == "validate":
            from navigation_dataset.validation import validate_dataset

            raw_scene_ids = payload.get("scene_ids")
            scene_ids = (
                [str(sid) for sid in raw_scene_ids if sid]
                if isinstance(raw_scene_ids, list) and raw_scene_ids
                else None
            )
            report = validate_dataset(
                project_dir,
                require_observations=bool(payload.get("require_observations", False)),
                scene_ids=scene_ids,
            )
            self._send_json(handler, HTTPStatus.OK, report.to_payload())
            return True
        if len(parts) == 2 and parts[1] == "evaluate":
            from navigation_dataset.evaluator import evaluate_dataset

            success_radius = float(payload.get("success_radius", 0.5))
            result = evaluate_dataset(project_dir, success_radius=success_radius)
            eval_path = project_dir / "evaluation" / f"{payload.get('policy') or 'shortest_oracle'}.json"
            eval_path.parent.mkdir(parents=True, exist_ok=True)
            eval_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(handler, HTTPStatus.OK, {"policy": payload.get("policy") or "shortest_oracle", "evaluation_ref": eval_path.relative_to(project_dir).as_posix(), **result})
            return True
        if len(parts) == 2 and parts[1] == "export":
            from navigation_dataset.exporters.custom_json import (
                build_dataset_index,
                export_dataset_zip,
                write_dataset_index,
                write_split_files,
            )

            raw_ids = payload.get("episode_ids")
            episode_ids = (
                [str(eid) for eid in raw_ids if eid]
                if isinstance(raw_ids, list) and raw_ids
                else None
            )
            raw_scene_ids = payload.get("scene_ids")
            scene_ids = (
                [str(sid) for sid in raw_scene_ids if sid]
                if isinstance(raw_scene_ids, list) and raw_scene_ids
                else None
            )
            only_completed = bool(payload.get("only_completed", False))
            index_path = write_dataset_index(
                project_dir, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
            )
            split_paths = write_split_files(
                project_dir, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
            )
            index_payload = build_dataset_index(
                project_dir, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
            )
            response = {
                "dataset_ref": index_path.relative_to(project_dir).as_posix(),
                "split_refs": [path.relative_to(project_dir).as_posix() for path in split_paths],
                "project": self._opticalnav_project_summary(project_dir),
                "episode_count": index_payload.get("episode_count", 0),
                "total_episode_count_on_disk": index_payload.get("total_episode_count_on_disk", 0),
                "skipped_episode_count": index_payload.get("skipped_episode_count", 0),
                "filter": index_payload.get("filter"),
            }
            if bool(payload.get("zip", False)):
                zip_path = export_dataset_zip(
                    project_dir, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
                )
                response["zip_ref"] = zip_path.relative_to(self.repo_root).as_posix()
                response["download_url"] = f"/artifacts?path={quote(response['zip_ref'])}"
            self._send_json(handler, HTTPStatus.OK, response)
            return True
        if len(parts) == 2 and parts[1] == "export-jobs":
            scene_id = _maybe_str(payload.get("scene_id"))
            if not scene_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "scene_id is required for scene-bundle export"})
                return True
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            raw_ids = payload.get("episode_ids")
            episode_ids = (
                [str(eid) for eid in raw_ids if eid]
                if isinstance(raw_ids, list) and raw_ids
                else None
            )
            only_completed = bool(payload.get("only_completed", True))
            include_episode_thumbnails = bool(payload.get("include_episode_thumbnails", False))
            panorama_observations = bool(payload.get("panorama_observations", True))
            png_only = bool(payload.get("png_only", False))
            include_birdseye = bool(payload.get("include_birdseye", True))
            include_polarization_raw = bool(payload.get("include_polarization_raw", True))
            job_id = f"export-{scene_id}-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"
            with self._export_jobs_lock:
                self._export_jobs[job_id] = {
                    "job_id": job_id,
                    "project_id": parts[0],
                    "scene_id": scene_id,
                    "only_completed": only_completed,
                    "include_episode_thumbnails": include_episode_thumbnails,
                    "status": "queued",
                    "stage": "scope",
                    "stage_label": self._EXPORT_STAGE_LABELS["scope"],
                    "current": 0,
                    "total": 0,
                    "bytes_current": 0,
                    "bytes_total": 0,
                    "message": "queued",
                    "current_file": None,
                    "summary": None,
                    "error": None,
                    "cancel_requested": False,
                    "created_at": _utc_now_iso(),
                }
            threading.Thread(
                target=self._run_export_job,
                args=(job_id, parts[0], project_dir, scene_id, only_completed, episode_ids, include_episode_thumbnails, panorama_observations, png_only, include_birdseye, include_polarization_raw),
                name=f"export-job-{job_id}",
                daemon=True,
            ).start()
            self._send_json(handler, HTTPStatus.ACCEPTED, {
                "job_id": job_id,
                "status": "queued",
                "scene_id": scene_id,
                "ws_url": f"/api/ws/opticalnav-export?job_id={job_id}",
                "status_url": f"/api/opticalnav/projects/{parts[0]}/export-jobs/{job_id}",
            })
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "objects":
            from navigation_dataset.authoring_map import (
                OBJECT_TYPES, REGION_TYPES,
                load_authoring_map, save_authoring_map, starter_authoring_map,
            )

            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            obj_type = str(payload.get("type") or "")
            is_region = bool(payload.get("region", False)) or obj_type in REGION_TYPES
            try:
                authoring_map = load_authoring_map(map_path) if map_path.exists() else starter_authoring_map(scene_id, None)
                existing_ids = {obj.id for obj in authoring_map.objects} | {reg.id for reg in authoring_map.regions}
                if is_region:
                    if obj_type not in REGION_TYPES:
                        self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Unknown region type: {obj_type!r}. Valid: {sorted(REGION_TYPES)}"})
                        return True
                    new_item = self._build_agent_region(dict(payload), existing_ids)
                    authoring_map.regions.append(new_item)
                else:
                    if obj_type not in OBJECT_TYPES:
                        self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Unknown object type: {obj_type!r}. Valid: {sorted(OBJECT_TYPES)}"})
                        return True
                    new_item = self._build_agent_object(dict(payload), existing_ids)
                    authoring_map.objects.append(new_item)
                save_authoring_map(map_path, authoring_map)
            except (KeyError, ValueError) as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.CREATED, {"id": new_item.id, "type": new_item.type, "saved": True})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "objects" and parts[4] == "batch":
            from navigation_dataset.authoring_compile import AuthoringMapCompileError, compile_authoring_map
            from navigation_dataset.authoring_map import (
                OBJECT_TYPES, REGION_TYPES,
                load_authoring_map, save_authoring_map, starter_authoring_map,
            )
            from navigation_dataset.scene_annotations import write_scene_annotation

            scene_id = parts[2]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            auto_compile = bool(payload.get("auto_compile", False))
            try:
                authoring_map = load_authoring_map(map_path) if map_path.exists() else starter_authoring_map(scene_id, None)
                placed_ids: list[str] = []
                for item_req in list(payload.get("objects") or []):
                    item_req = dict(item_req)
                    obj_type = str(item_req.get("type") or "")
                    is_region = bool(item_req.get("region", False)) or obj_type in REGION_TYPES
                    existing_ids = {obj.id for obj in authoring_map.objects} | {reg.id for reg in authoring_map.regions}
                    if is_region:
                        new_item = self._build_agent_region(item_req, existing_ids)
                        authoring_map.regions.append(new_item)
                    else:
                        new_item = self._build_agent_object(item_req, existing_ids)
                        authoring_map.objects.append(new_item)
                    placed_ids.append(new_item.id)
                save_authoring_map(map_path, authoring_map)
            except (KeyError, ValueError) as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            compile_result = None
            if auto_compile:
                annotation_path = scene_dir / "scene_annotation.json"
                try:
                    result = compile_authoring_map(authoring_map)
                    write_scene_annotation(annotation_path, result.annotation)
                    compile_result = {"status": "ok", "annotation_ref": annotation_path.relative_to(project_dir).as_posix()}
                except AuthoringMapCompileError as exc:
                    compile_result = {"status": "blocked", "errors": [issue.to_payload() for issue in exc.issues]}
                except Exception as exc:
                    compile_result = {"status": "error", "error": str(exc)}
            self._send_json(handler, HTTPStatus.CREATED, {"placed": placed_ids, "compile_result": compile_result})
            return True
        if len(parts) == 6 and parts[1] == "scenes" and parts[3] == "objects" and parts[5] == "material":
            from mitsuba_converter.material_library import MATERIAL_CATALOG, hpbrdf_channels_dir
            from navigation_dataset.authoring_map import (
                AuthoringMaterial,
                load_authoring_map, save_authoring_map, starter_authoring_map,
            )

            scene_id, object_id = parts[2], parts[4]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            material_id = str(payload.get("material_id") or "")
            dataset_id = str(payload.get("dataset_id") or "hpbrdf_2025")
            if not material_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "material_id is required."})
                return True
            native_file_path: str | None = None
            for mid, _label, native_path in MATERIAL_CATALOG.get(dataset_id, []):
                if mid == material_id:
                    native_file_path = native_path
                    break
            if native_file_path is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown material_id {material_id!r} in dataset {dataset_id!r}."})
                return True
            local_available = hpbrdf_channels_dir(self.repo_root, material_id) is not None
            map_path = scene_dir / "authoring_map.json"
            try:
                authoring_map = load_authoring_map(map_path) if map_path.exists() else starter_authoring_map(scene_id, None)
                obj = next((o for o in authoring_map.objects if o.id == object_id), None)
                if obj is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown object_id: {object_id!r}"})
                    return True
                obj.material = f"{dataset_id}/{material_id}"
                authoring_map.materials = [m for m in authoring_map.materials if m.material_id != f"{dataset_id}/{material_id}"]
                authoring_map.materials.append(AuthoringMaterial(
                    material_id=f"{dataset_id}/{material_id}",
                    category=dataset_id,
                    params={"dataset_id": dataset_id, "native_file_path": native_file_path},
                ))
                save_authoring_map(map_path, authoring_map)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "object_id": object_id,
                "material_id": material_id,
                "dataset_id": dataset_id,
                "native_file_path": native_file_path,
                "local_available": local_available,
                "applied": True,
            })
            return True
        return False

    def _handle_opticalnav_put(self, handler: BaseHTTPRequestHandler, path: str, payload: Mapping[str, Any]) -> bool:
        if path.startswith("/api/opticalnav/asset-library/assets/"):
            asset_id = unquote(path[len("/api/opticalnav/asset-library/assets/"):].strip("/"))
            if not asset_id or "/" in asset_id:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Invalid asset_id."})
                return True
            result = self._opticalnav_update_asset_library_asset(asset_id, payload)
            if result is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown asset_id: {asset_id}"})
                return True
            self._send_json(handler, HTTPStatus.OK, {"ok": True, "asset": result})
            return True
        if not path.startswith("/api/opticalnav/projects/"):
            return False
        parts = [unquote(part) for part in path[len("/api/opticalnav/projects/"):].strip("/").split("/") if part]
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "usd-ref":
            try:
                project_dir = self._opticalnav_project_dir(parts[0])
                scene_id = parts[2]
                scene_dir = project_dir / "scenes" / scene_id
                if not scene_dir.exists():
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                    return True
                usd_ref = _maybe_str(payload.get("usd_ref"))
                result = self._opticalnav_set_scene_usd_ref(project_dir, scene_id, usd_ref)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "ok": True,
                **result,
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "authoring-map":
            from navigation_dataset.authoring_map import (
                AuthoringMapValidationError,
                authoring_map_to_payload,
                save_authoring_map,
            )

            try:
                project_dir = self._opticalnav_project_dir(parts[0])
                scene_id = parts[2]
                scene_dir = project_dir / "scenes" / scene_id
                if not scene_dir.exists():
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                    return True
                body = dict(payload)
                if str(body.get("scene_id") or "") != scene_id:
                    raise ValueError(f"authoring_map.scene_id must match route scene_id {scene_id!r}.")
                defer_render_scene_sync = bool(body.pop("defer_render_scene_sync", False) or body.pop("skip_render_scene_sync", False))
                path_out = scene_dir / "authoring_map.json"
                save_authoring_map(path_out, body)
                saved = _read_json(path_out)
            except AuthoringMapValidationError as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, exc.to_payload())
                return True
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True

            if defer_render_scene_sync:
                self._patch_opticalnav_annotation_sync(project_dir, scene_id, {
                    "render_scene": "pending",
                    "render_scene_status": "deferred",
                    "render_readiness_status": "pending",
                    "message": "Authoring map changed; compile annotation and sync render scene before rendering.",
                })
                self._send_json(handler, HTTPStatus.OK, {
                    "ok": True,
                    "authoring_map": authoring_map_to_payload(saved),
                    "authoring_map_ref": path_out.relative_to(project_dir).as_posix(),
                    "render_readiness": None,
                    "xml_shape_count": 0,
                    "project": self._opticalnav_project_summary(project_dir),
                })
                return True

            # Phase 3: Immediately regenerate render_scene.xml so it stays in sync
            # with the authoring map without a separate "Sync" step.
            render_scene_path = scene_dir / "render_scene.xml"
            xml_shape_count = 0
            render_readiness: dict[str, Any] | None = None
            try:
                editor_geometry: dict[str, Any] | None = None
                eg_path = scene_dir / "editor_geometry.json"
                if eg_path.exists():
                    try:
                        editor_geometry = _read_json(eg_path)
                    except Exception:
                        pass
                mesh_resolver = self._make_mesh_resolver(project_dir, scene_id)
                mesh_stats: dict[str, int] = {}
                materialization_records: list[dict[str, Any]] = []
                xml_shape_count = _generate_opticalnav_render_scene_xml(
                    saved,
                    saved,  # overlay == authoring map itself (objects live here)
                    render_scene_path,
                    editor_geometry=editor_geometry,
                    repo_root=self.repo_root,
                    mesh_resolver=mesh_resolver,
                    mesh_stats=mesh_stats,
                    materialization_records=materialization_records,
                )
                scene_mesh_cache_dir = self._opticalnav_mesh_cache_dir(project_dir, scene_id)
                mesh_stats["scene_mesh_cache"] = _stage_xml_obj_filenames_to_scene_mesh_cache(
                    render_scene_path,
                    scene_mesh_cache_dir=scene_mesh_cache_dir,
                    repo_root=self.repo_root,
                )
                preview_mesh_manifest = _build_editor_preview_mesh_manifest(
                    render_scene_path,
                    scene_mesh_cache_dir=scene_mesh_cache_dir,
                    repo_root=self.repo_root,
                    materialization_records=materialization_records,
                )
                mesh_stats["editor_preview_mesh_cache"] = preview_mesh_manifest.get("stats", {})
                try:
                    (scene_dir / "editor_preview_mesh_manifest.json").write_text(
                        json.dumps(preview_mesh_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                except Exception as exc:
                    mesh_stats["editor_preview_mesh_manifest_error"] = str(exc)
                render_scene_ref = render_scene_path.relative_to(self.repo_root).as_posix()
                try:
                    audit_payload = _build_materialization_audit(
                        scene_id=scene_id,
                        overlay_objects=list(saved.get("objects") or []),
                        materialization_records=materialization_records,
                        mesh_stats=mesh_stats,
                    )
                    (scene_dir / "render_scene_materialization.json").write_text(
                        json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                except Exception as exc:
                    mesh_stats["materialization_audit_error"] = str(exc)
                try:
                    xml_index = _build_xml_scene_index(
                        render_scene_path,
                        scene_id=scene_id,
                        materialization_records=materialization_records,
                        preview_mesh_manifest=preview_mesh_manifest.get("shapes", {}),
                    )
                    if xml_index is not None:
                        (scene_dir / "xml_scene_index.json").write_text(
                            json.dumps(xml_index, ensure_ascii=False, indent=2), encoding="utf-8",
                        )
                except Exception as exc:
                    mesh_stats["xml_scene_index_error"] = str(exc)
                render_readiness = _build_opticalnav_render_readiness(
                    saved,
                    repo_root=self.repo_root,
                    render_scene_path=render_scene_path,
                    render_scene_ref=render_scene_ref,
                    overlay_shape_count=xml_shape_count,
                )
                # Update scene_variant.json pointer so Graph Sweep picks up the fresh XML.
                sv_path = scene_dir / "scene_variant.json"
                sv: dict[str, Any] = {}
                if sv_path.exists():
                    try:
                        sv = dict(_read_json(sv_path))
                    except Exception:
                        pass
                sv["render_sync_mode"] = "editor_generated_xml"
                sv["overlay_scene_xml_ref"] = render_scene_ref
                sv["base_scene_xml_ref"] = None
                sv_path.write_text(json.dumps(sv, ensure_ascii=False, indent=2), encoding="utf-8")

                # Write render_readiness.json so loadRenderReadiness() reads OK on page reload.
                readiness_path = scene_dir / "render_readiness.json"
                readiness_path.write_text(json.dumps(render_readiness, ensure_ascii=False, indent=2), encoding="utf-8")

                # Update scene_annotation.json sync status so sync_status.render_scene === 'synced'.
                # This is read by _opticalnav_render_precondition_payload() before allowing renders.
                # We patch metadata.sync directly in raw JSON to avoid triggering full annotation
                # validation (which requires goal_regions/traversable_regions and would fail
                # silently on uncommitted scenes, leaving the old "blocked" state in place).
                annotation_path = scene_dir / "scene_annotation.json"
                if annotation_path.exists():
                    try:
                        _sv_ref = sv_path.relative_to(project_dir).as_posix()
                        _overlay_ref = render_scene_path.relative_to(project_dir).as_posix()
                        _raw = json.loads(annotation_path.read_text(encoding="utf-8"))
                        _raw.setdefault("metadata", {})["sync"] = {
                            **dict(_raw.get("metadata", {}).get("sync", {})),
                            "render_scene": "synced" if render_readiness.get("ok") else "blocked",
                            "render_scene_mode": "editor_generated_xml",
                            "render_scene_xml_ref": render_scene_ref,
                            "scene_variant_ref": _sv_ref,
                            "render_scene_overlay_ref": _overlay_ref,
                            "render_readiness_ref": readiness_path.relative_to(project_dir).as_posix(),
                            "render_readiness_status": render_readiness.get("status"),
                        }
                        annotation_path.write_text(json.dumps(_raw, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass  # Annotation may not exist yet; not fatal

            except Exception as xml_exc:
                # XML generation failure is non-fatal for the authoring save itself;
                # the response will include the error so the UI can surface it.
                render_readiness = {
                    "ok": False,
                    "status": "blocked",
                    "errors": [{"key": "xml_gen", "message": str(xml_exc)}],
                }
                try:
                    readiness_path = scene_dir / "render_readiness.json"
                    readiness_path.write_text(json.dumps(render_readiness, ensure_ascii=False, indent=2), encoding="utf-8")
                    self._patch_opticalnav_annotation_sync(project_dir, scene_id, {
                        "render_scene": "blocked",
                        "render_scene_status": "error",
                        "render_readiness_ref": readiness_path.relative_to(project_dir).as_posix(),
                        "render_readiness_status": "blocked",
                        "message": f"Render-scene XML generation failed: {xml_exc}",
                    })
                except Exception:
                    pass

            self._send_json(handler, HTTPStatus.OK, {
                "ok": True,
                "authoring_map": authoring_map_to_payload(saved),
                "authoring_map_ref": path_out.relative_to(project_dir).as_posix(),
                "render_readiness": render_readiness,
                "xml_shape_count": xml_shape_count,
                "project": self._opticalnav_project_summary(project_dir),
            })
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "annotation":
            from navigation_dataset.scene_annotations import scene_annotation_from_payload, write_scene_annotation

            try:
                project_dir = self._opticalnav_project_dir(parts[0])
                annotation = scene_annotation_from_payload(dict(payload))
                if annotation.scene_id != parts[2]:
                    raise ValueError(f"annotation.scene_id must match route scene_id {parts[2]!r}.")
                path_out = project_dir / "scenes" / parts[2] / "scene_annotation.json"
                write_scene_annotation(path_out, annotation)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {"ok": True, "annotation": _read_json(path_out), "project": self._opticalnav_project_summary(project_dir)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "render-config":
            try:
                project_dir = self._opticalnav_project_dir(parts[0])
                scene_id = parts[2]
                scene_dir = project_dir / "scenes" / scene_id
                if not scene_dir.exists():
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                    return True
                config = {
                    "scene_id": scene_id,
                    "scene_state": payload.get("scene_state"),
                    "camera_spec": payload.get("camera_spec"),
                    "updated_at": _utc_now_iso(),
                }
                saved_path = scene_dir / "render_config.json"
                saved_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {"ok": True, **config, "source": "saved"})
            return True
        return False

    def _handle_delete(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            if self._proxy_to_render_queue(handler, "DELETE"):
                return
            if path.startswith("/api/opticalnav/"):
                if self._handle_opticalnav_delete(handler, path):
                    return
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav route: {path}"})
                return
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})
        except _ClientDisconnectedError:
            return
        except Exception as exc:
            try:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except _ClientDisconnectedError:
                return

    def _handle_opticalnav_delete(self, handler: BaseHTTPRequestHandler, path: str) -> bool:
        if not path.startswith("/api/opticalnav/projects/"):
            return False
        parts = [unquote(part) for part in path[len("/api/opticalnav/projects/"):].strip("/").split("/") if part]
        if len(parts) < 1:
            return False
        try:
            project_dir = self._opticalnav_project_dir(parts[0])
        except ValueError as exc:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if not project_dir.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav project_id: {parts[0]}"})
            return True
        if len(parts) == 3 and parts[1] == "export-jobs":
            job_id = parts[2]
            with self._export_jobs_lock:
                state = self._export_jobs.get(job_id)
                if state is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown export job: {job_id}"})
                    return True
                state["cancel_requested"] = True
                self._export_jobs[job_id] = state
            self._send_json(handler, HTTPStatus.ACCEPTED, {"job_id": job_id, "cancel_requested": True})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "observations" and parts[4] == "":
            # DELETE .../scenes/{scene_id}/observations/ — never happens (trailing slash guard)
            pass
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "nodes":
            # Batch removal: DELETE .../graph/nodes with body {"node_ids": [...]}.
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph, remove_nodes
            scene_id = parts[2]
            try:
                payload = self._read_request_body(handler)
            except Exception:
                payload = {}
            raw_ids = (payload or {}).get("node_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {
                    "error": "DELETE /graph/nodes requires a single node_id (.../graph/nodes/{node_id}) or a JSON body {\"node_ids\": [...]}"
                })
                return True
            node_ids = [str(n) for n in raw_ids]
            graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            try:
                from navigation_dataset.graph_edit_log import graph_size as _gsz, node_record as _nrec
                with self._opticalnav_graph_edit_lock(project_dir, scene_id):
                    graph = read_viewpoint_graph(graph_path)
                    _before = _gsz(graph)
                    # Resolve node positions/provenance BEFORE removal (lost afterwards).
                    _deleted = [r for r in (_nrec(graph, nid) for nid in node_ids) if r is not None]
                    removed = remove_nodes(graph, node_ids)
                    if removed:
                        self._bump_viewpoint_graph_revision(graph)
                        write_viewpoint_graph(graph_path, graph)
                _reason = (payload or {}).get("reason")
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "delete_nodes",
                    "graph_id": getattr(graph, "graph_id", None),
                    "before": _before, "after": _gsz(graph),
                    "params": {"requested": node_ids, "reason": _reason},
                    "deleted_nodes": _deleted,
                    "algo_context": {
                        "from_overlap_prune": _reason == "overlap_prune",
                        "manual_count": sum(1 for r in _deleted if (r.get("extras") or {}).get("manual")),
                        "regenerated_count": sum(1 for r in _deleted if (r.get("extras") or {}).get("regenerated_region")),
                    },
                })
                self._send_json(handler, HTTPStatus.OK, {
                    "ok": True,
                    "removed": removed,
                    "removed_count": len(removed),
                    "requested": len(node_ids),
                    "remaining_nodes": len(graph.nodes),
                })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 6 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "nodes":
            from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph, remove_node
            scene_id = parts[2]
            node_id = parts[5]
            graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            try:
                from navigation_dataset.graph_edit_log import graph_size as _gsz, node_record as _nrec, nearest_node_distance as _nnd
                with self._opticalnav_graph_edit_lock(project_dir, scene_id):
                    graph = read_viewpoint_graph(graph_path)
                    _before = _gsz(graph)
                    _rec = _nrec(graph, node_id)  # resolve BEFORE removal
                    ok = remove_node(graph, node_id)
                    if not ok:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"node_id not found: {node_id}"})
                        return True
                    self._bump_viewpoint_graph_revision(graph)
                    write_viewpoint_graph(graph_path, graph)
                _pos = (_rec or {}).get("position") or [None, None]
                _log_graph_edit(handler, project_dir, scene_id, {
                    "operation": "delete_node",
                    "graph_id": getattr(graph, "graph_id", None),
                    "before": _before, "after": _gsz(graph),
                    "params": {"node_id": node_id},
                    "deleted_nodes": [_rec] if _rec else [],
                    "algo_context": {
                        "was_manual": bool((( _rec or {}).get("extras") or {}).get("manual")),
                        "was_regenerated": bool((( _rec or {}).get("extras") or {}).get("regenerated_region")),
                        "clearance_m": (_rec or {}).get("clearance_m"),
                        "nearest_remaining_node_m": (_nnd(graph, _pos[0], _pos[1]) if _pos[0] is not None else None),
                    },
                })
                self._send_json(handler, HTTPStatus.OK, {"ok": True, "removed": node_id, "remaining_nodes": len(graph.nodes)})
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 6 and parts[1] == "scenes" and parts[3] == "graph" and parts[4] == "edges":
            scene_id = parts[2]
            edge_id = parts[5]
            graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
            if not graph_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
                return True
            status, response = self._apply_opticalnav_graph_edits(handler, project_dir, scene_id, {
                "ops": [{"type": "delete_edge", "edge_id": edge_id}]
            })
            if status != HTTPStatus.OK:
                self._send_json(handler, status, response)
                return True
            result = next((item for item in response.get("results", []) if item.get("ok")), None)
            if not result:
                err = next((item for item in response.get("results", []) if not item.get("ok")), None) or {"error": f"edge_id not found: {edge_id}"}
                self._send_json(handler, HTTPStatus.NOT_FOUND, err)
                return True
            self._send_json(handler, HTTPStatus.OK, {
                "ok": True,
                "removed": edge_id,
                "remaining_edges": response.get("edge_count"),
                "revision": response.get("revision"),
            })
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "walkability-overlay":
            scene_id = parts[2]
            overlay_path = project_dir / "scenes" / scene_id / "walkability_overlay.npy"
            if not overlay_path.exists():
                self._send_json(handler, HTTPStatus.OK, {"ok": True, "already_empty": True})
                return True
            try:
                overlay_path.unlink()
                self._send_json(handler, HTTPStatus.OK, {"ok": True})
            except OSError as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return True
        if len(parts) == 4 and parts[1] == "scenes" and parts[3] == "observations":
            scene_id = parts[2]
            try:
                payload = self._read_request_body(handler)
            except Exception:
                payload = {}
            self._handle_opticalnav_clear_observations(handler, project_dir, scene_id, payload or {})
            return True
        if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "objects":
            from navigation_dataset.authoring_map import load_authoring_map, save_authoring_map

            scene_id, object_id = parts[2], parts[4]
            scene_dir = project_dir / "scenes" / scene_id
            if not scene_dir.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                return True
            map_path = scene_dir / "authoring_map.json"
            if not map_path.exists():
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "authoring_map.json not found"})
                return True
            try:
                authoring_map = load_authoring_map(map_path)
                obj_count_before = len(authoring_map.objects) + len(authoring_map.regions)
                authoring_map.objects = [obj for obj in authoring_map.objects if obj.id != object_id]
                authoring_map.regions = [reg for reg in authoring_map.regions if reg.id != object_id]
                if len(authoring_map.objects) + len(authoring_map.regions) == obj_count_before:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown object_id: {object_id!r}"})
                    return True
                save_authoring_map(map_path, authoring_map)
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return True
            self._send_json(handler, HTTPStatus.OK, {"deleted": True, "id": object_id})
            return True
        return False

    def _handle_opticalnav_clear_observations(
        self, handler: BaseHTTPRequestHandler, project_dir: Path, scene_id: str, payload: Mapping[str, Any]
    ) -> None:
        from navigation_dataset.viewpoint_graph import read_viewpoint_graph, write_viewpoint_graph

        graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
        if not graph_path.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
            return

        node_ids_filter: set[str] | None = None
        raw_ids = payload.get("node_ids")
        if isinstance(raw_ids, list) and raw_ids:
            node_ids_filter = {str(n) for n in raw_ids}

        try:
            with self._opticalnav_graph_edit_lock(project_dir, scene_id):
                graph = read_viewpoint_graph(graph_path)
                obs_root = project_dir / "scenes" / scene_id / "observations"
                cleared_nodes: list[str] = []
                for node in graph.nodes:
                    if node_ids_filter is not None and node.node_id not in node_ids_filter:
                        continue
                    had_obs = any(heading.sensor_observations for heading in node.headings)
                    for heading in node.headings:
                        heading.sensor_observations = {}
                    node_obs_dir = obs_root / node.node_id
                    if node_obs_dir.exists():
                        shutil.rmtree(node_obs_dir, ignore_errors=True)
                    if had_obs:
                        cleared_nodes.append(node.node_id)
                self._bump_viewpoint_graph_revision(graph)
                write_viewpoint_graph(graph_path, graph)
        except Exception as exc:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(handler, HTTPStatus.OK, {
            "cleared_nodes": len(cleared_nodes),
            "node_ids": cleared_nodes,
        })

    def _handle_opticalnav_graph_sweep(self, handler: BaseHTTPRequestHandler, project_dir: Path, scene_id: str, payload: Mapping[str, Any]) -> None:
        from navigation_dataset.sensor_sweep import build_sweep_render_requests, build_custom_position_render_requests, render_viewpoint_sweep_direct
        from navigation_dataset.viewpoint_graph import read_viewpoint_graph

        custom_positions = list(payload.get("custom_positions") or [])
        modalities = [str(item) for item in payload.get("modalities", ["rgb", "depth", "active_nir_intensity", "hazard_mask"])]
        backend = str(payload.get("backend") or "daemon")
        scene_state_payload = payload.get("scene_state")
        camera_spec_payload = payload.get("camera_spec")
        camera_height_m = float(payload.get("camera_height_m") or 1.0)
        node_heights_raw = payload.get("node_heights")
        node_heights = dict(node_heights_raw) if isinstance(node_heights_raw, Mapping) else None
        render_settings_raw = payload.get("render_settings")
        render_settings = dict(render_settings_raw) if isinstance(render_settings_raw, dict) else {}
        skip_existing_observations = bool(
            payload.get("skip_existing_observations")
            or payload.get("only_missing")
            or payload.get("resume_missing_only")
        )

        precondition = self._opticalnav_render_precondition_payload(project_dir, [scene_id], payload, mode="graph_sweep")
        if precondition is not None:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, precondition)
            return

        # Resolve scene ref: ONLY from scene_variant.json (overlay_scene_xml_ref > base_scene_xml_ref).
        # Catalog match is NOT used here — render_scene.xml generated at sync time is authoritative.
        # If no XML is found, return an error requiring the user to run Sync Render Scene first.
        _sv_path = project_dir / "scenes" / scene_id / "scene_variant.json"
        resolved_scene_ref: str | None = None
        if _sv_path.exists():
            _sv = _read_json(_sv_path)
            for _key in ("overlay_scene_xml_ref", "base_scene_xml_ref"):
                _ref = _maybe_str(_sv.get(_key))
                if _ref and resolve_repo_path(self.repo_root, _ref).exists():
                    resolved_scene_ref = _ref
                    break
        if not resolved_scene_ref:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {
                "error": "No render scene XML found for this scene. Run 'Sync Render Scene' first.",
                "scene_id": scene_id,
                "hint": "scene_variant.json has no valid base_scene_xml_ref or overlay_scene_xml_ref.",
            })
            return
        # Always rebuild canonical scene_state — never inherit stale job_id from caller.
        scene_state_payload = {
            "job_id": f"opticalnav-{scene_id}-template",
            "scene_id": scene_id,
            "frame_id": f"{scene_id}_frame_template",
            "timestamp": _utc_now_iso(),
            "scene_snapshot_ref": resolved_scene_ref,
            "mitsuba_scene_ref": resolved_scene_ref,
            "extras": {},
        }

        # Custom positions: no graph required
        if custom_positions and not payload.get("node_ids"):
            precondition = self._opticalnav_render_precondition_payload(project_dir, [scene_id], payload, mode="graph_sweep")
            if precondition is not None:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, precondition)
                return
            batch_id = f"opticalnav-custom-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"
            jobs = []
            skipped_existing = 0
            requested_count = 0
            try:
                sweep_requests = build_custom_position_render_requests(
                    custom_positions,
                    scene_state_payload=dict(scene_state_payload),
                    camera_spec_payload=dict(camera_spec_payload),
                    modalities=modalities,
                    scene_id=scene_id,
                    camera_height_m=camera_height_m,
                    render_settings=render_settings,
                )
                requested_count = len(sweep_requests)
                if skip_existing_observations:
                    kept_requests = []
                    for sweep_request in sweep_requests:
                        if self._opticalnav_sweep_output_exists(project_dir, scene_id, sweep_request, modalities):
                            skipped_existing += 1
                        else:
                            kept_requests.append(sweep_request)
                    sweep_requests = kept_requests
                gpu_indices = _render_gpu_indices_from_env()
                shard_assignments = _interleaved_gpu_shard_assignments(len(sweep_requests), gpu_indices)
                for sweep_request, shard in zip(sweep_requests, shard_assignments):
                    runtime_overrides = {
                        "shard_index": shard["shard_index"],
                        "shard_count": shard["shard_count"],
                        "shard_item_index": shard["shard_item_index"],
                        "shard_size": shard["shard_size"],
                    }
                    if _static_gpu_shards_enabled():
                        runtime_overrides["worker_gpu_index"] = shard["target_gpu_index"]
                    sweep_request.request.extras["opticalnav_project_id"] = project_dir.name
                    sweep_request.request.extras["opticalnav_scene_id"] = scene_id
                    sweep_request.request.extras["opticalnav_vp_id"] = sweep_request.node_id
                    sweep_request.request.extras["opticalnav_heading_id"] = sweep_request.heading_id
                    accepted = self.submit(
                        sweep_request.request,
                        variant=str(payload.get("variant") or self.variant),
                        runtime_overrides=runtime_overrides,
                    )
                    jobs.append({
                        "job_id": accepted.job_id,
                        "scene_id": scene_id,
                        "node_id": sweep_request.node_id,
                        "heading_id": sweep_request.heading_id,
                        "render_mode": sweep_request.request.extras.get("render_mode"),
                        "preview_id": sweep_request.request.extras.get("preview_id"),
                        "sensor_id": sweep_request.request.camera_specs[0].camera_id if sweep_request.request.camera_specs else None,
                        "modality": modalities[0] if len(modalities) == 1 else None,
                        "status_url": accepted.status_url,
                        **runtime_overrides,
                        **({"target_gpu_index": shard["target_gpu_index"]} if _static_gpu_shards_enabled() else {}),
                    })
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "submitted_jobs": jobs})
                return
            batch = {
                "batch_id": batch_id,
                "project_id": project_dir.name,
                "scene_id": scene_id,
                "backend": "daemon",
                "created_at": _utc_now_iso(),
                "modalities": modalities,
                "scheduling_policy": "interleaved_gpu_shards" if _static_gpu_shards_enabled() else _dynamic_gpu_scheduling_policy(),
                "gpu_indices": _render_gpu_indices_from_env(),
                "static_gpu_shards": _static_gpu_shards_enabled(),
                "skip_existing_observations": skip_existing_observations,
                "requested_jobs": requested_count or len(jobs),
                "skipped_existing": skipped_existing,
                "jobs": jobs,
            }
            batch_path = project_dir / "graph_render_batches" / f"{batch_id}.json"
            batch_path.parent.mkdir(parents=True, exist_ok=True)
            batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
            n = len(jobs)
            self._send_json(handler, HTTPStatus.ACCEPTED, {
                **batch,
                "counts": {"queued": n, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0},
                "progress": {"completed": 0, "failed": 0, "total": n, "fraction": 0.0},
            })
            return

        graph_path = project_dir / "scenes" / scene_id / "viewpoint_graph.json"
        if not graph_path.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "viewpoint_graph.json not found"})
            return
        precondition = self._opticalnav_render_precondition_payload(project_dir, [scene_id], payload, mode="graph_sweep")
        if precondition is not None:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, precondition)
            return
        if backend == "direct":
            # Synchronous path: read graph and render inline (CLI / test use).
            try:
                graph = read_viewpoint_graph(graph_path)
                updated = render_viewpoint_sweep_direct(
                    graph,
                    dataset_root=project_dir,
                    graph_path=graph_path,
                    scene_state_payload=dict(scene_state_payload),
                    camera_spec_payload=dict(camera_spec_payload),
                    modalities=modalities,
                    render_fn=self.render_fn,
                    variant=str(payload.get("variant") or self.variant),
                )
            except Exception as exc:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            rendered = sum(1 for node in updated.nodes for heading in node.headings if heading.sensor_observations)
            self._send_json(handler, HTTPStatus.OK, {"backend": "direct", "graph_id": updated.graph_id, "rendered_node_headings": rendered})
            return
        if backend != "daemon":
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "backend must be 'direct' or 'daemon'."})
            return

        # Daemon path: return a batch stub immediately, build + submit jobs in background.
        # Reading the graph (potentially MB-scale JSON) and submitting hundreds of jobs
        # to the worker queue takes seconds-to-minutes and must not block the HTTP handler.
        node_ids_filter = [str(n) for n in payload["node_ids"]] if payload.get("node_ids") else None
        batch_id = f"opticalnav-graph-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"
        batch_path = project_dir / "graph_render_batches" / f"{batch_id}.json"
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        stub = {
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "scene_id": scene_id,
            "backend": "daemon",
            "created_at": _utc_now_iso(),
            "modalities": modalities,
            "status": "building",
            "skip_existing_observations": skip_existing_observations,
            "jobs": [],
            "counts": {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0},
            "progress": {"completed": 0, "failed": 0, "total": 0, "fraction": 0.0},
        }
        batch_path.write_text(json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8")
        threading.Thread(
            target=self._run_graph_sweep_submission,
            kwargs=dict(
                batch_id=batch_id,
                batch_path=batch_path,
                project_dir=project_dir,
                scene_id=scene_id,
                graph_path=graph_path,
                scene_state_payload=dict(scene_state_payload),
                camera_spec_payload=dict(camera_spec_payload),
                modalities=modalities,
                node_ids_filter=node_ids_filter,
                camera_height_m=camera_height_m,
                render_settings=render_settings,
                node_heights=node_heights,
                variant=str(payload.get("variant") or self.variant),
                skip_existing_observations=skip_existing_observations,
            ),
            daemon=True,
            name=f"sweep-{batch_id}",
        ).start()
        self._send_json(handler, HTTPStatus.ACCEPTED, stub)

    def _run_graph_sweep_submission(
        self,
        *,
        batch_id: str,
        batch_path: "Path",
        project_dir: "Path",
        scene_id: str,
        graph_path: "Path",
        scene_state_payload: dict,
        camera_spec_payload: dict,
        modalities: list,
        node_ids_filter: "list[str] | None",
        camera_height_m: float,
        render_settings: dict,
        node_heights: "dict | None",
        variant: str,
        skip_existing_observations: bool = False,
    ) -> None:
        """Background thread: read graph, build RenderRequests, submit all jobs."""
        from navigation_dataset.sensor_sweep import build_sweep_render_requests
        from navigation_dataset.viewpoint_graph import read_viewpoint_graph
        try:
            graph = read_viewpoint_graph(graph_path)
            sweep_requests = build_sweep_render_requests(
                graph,
                scene_state_payload=scene_state_payload,
                camera_spec_payload=camera_spec_payload,
                modalities=modalities,
                job_id_mode="per_heading",
                node_ids=node_ids_filter,
                camera_height_m=camera_height_m,
                render_settings=render_settings,
                node_heights=node_heights,
            )
            requested_count = len(sweep_requests)
            skipped_existing = 0
            if skip_existing_observations:
                kept_requests = []
                for sweep_request in sweep_requests:
                    if self._opticalnav_sweep_output_exists(project_dir, scene_id, sweep_request, modalities):
                        skipped_existing += 1
                    else:
                        kept_requests.append(sweep_request)
                sweep_requests = kept_requests
            gpu_indices = _render_gpu_indices_from_env()
            shard_assignments = _interleaved_gpu_shard_assignments(len(sweep_requests), gpu_indices)
            jobs = []
            for sweep_request, shard in zip(sweep_requests, shard_assignments):
                runtime_overrides = {
                    "shard_index": shard["shard_index"],
                    "shard_count": shard["shard_count"],
                    "shard_item_index": shard["shard_item_index"],
                    "shard_size": shard["shard_size"],
                }
                if _static_gpu_shards_enabled():
                    runtime_overrides["worker_gpu_index"] = shard["target_gpu_index"]
                sweep_request.request.extras["opticalnav_project_id"] = project_dir.name
                sweep_request.request.extras["opticalnav_scene_id"] = scene_id
                sweep_request.request.extras["opticalnav_vp_id"] = sweep_request.node_id
                sweep_request.request.extras["opticalnav_heading_id"] = sweep_request.heading_id
                accepted = self.submit(
                    sweep_request.request,
                    variant=variant,
                    runtime_overrides=runtime_overrides,
                    lazy_persist=True,
                )
                jobs.append({
                    "job_id": accepted.job_id,
                    "scene_id": scene_id,
                    "graph_id": graph.graph_id,
                    "node_id": sweep_request.node_id,
                    "heading_id": sweep_request.heading_id,
                    "status_url": accepted.status_url,
                    **runtime_overrides,
                        **({"target_gpu_index": shard["target_gpu_index"]} if _static_gpu_shards_enabled() else {}),
                })
            n = len(jobs)
            batch = {
                "batch_id": batch_id,
                "project_id": project_dir.name,
                "scene_id": scene_id,
                "graph_id": graph.graph_id,
                "backend": "daemon",
                "created_at": _utc_now_iso(),
                "modalities": modalities,
                "scheduling_policy": "interleaved_gpu_shards" if _static_gpu_shards_enabled() else _dynamic_gpu_scheduling_policy(),
                "gpu_indices": _render_gpu_indices_from_env(),
                "static_gpu_shards": _static_gpu_shards_enabled(),
                "skip_existing_observations": skip_existing_observations,
                "requested_jobs": requested_count,
                "skipped_existing": skipped_existing,
                "jobs": jobs,
                "status": "ready",
                "counts": {"queued": n, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0},
                "progress": {"completed": 0, "failed": 0, "total": n, "fraction": 0.0},
            }
            batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            import traceback
            print(f"[daemon] sweep-submission-thread error batch_id={batch_id}: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                error_batch = {
                    "batch_id": batch_id,
                    "project_id": project_dir.name,
                    "scene_id": scene_id,
                    "backend": "daemon",
                    "status": "error",
                    "error": str(exc),
                    "jobs": [],
                    "counts": {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0, "unknown": 0},
                    "progress": {"completed": 0, "failed": 0, "total": 0, "fraction": 0.0},
                }
                batch_path.write_text(json.dumps(error_batch, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _handle_opticalnav_render(self, handler: BaseHTTPRequestHandler, project_dir: Path, payload: Mapping[str, Any]) -> None:
        from navigation_dataset.episode_schema import read_episode, write_episode
        from navigation_dataset.renderer import build_episode_render_requests, render_episode_direct

        modalities = [str(item) for item in payload.get("modalities", ["rgb", "depth", "active_nir_intensity", "hazard_mask"])]
        backend = str(payload.get("backend") or "daemon")
        scene_state_payload = payload.get("scene_state")
        camera_spec_payload = payload.get("camera_spec")
        episode_ids = payload.get("episode_ids")
        split = _maybe_str(payload.get("split"))
        if isinstance(episode_ids, list) and episode_ids:
            paths = [self._opticalnav_find_episode(project_dir, str(episode_id)) for episode_id in episode_ids]
        else:
            paths = self._opticalnav_episode_files(project_dir, split=split)
        if not paths:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "No episodes matched render request."})
            return
        scene_ids = []
        for path in paths:
            try:
                scene_ids.append(read_episode(path).scene_id)
            except Exception:
                pass
        precondition = self._opticalnav_render_precondition_payload(project_dir, scene_ids, payload, mode="episode_render")
        if precondition is not None:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, precondition)
            return
        if backend == "direct":
            rendered = []
            for path in paths:
                episode = read_episode(path)
                updated = render_episode_direct(
                    episode,
                    dataset_root=project_dir,
                    scene_state_payload=dict(scene_state_payload),
                    camera_spec_payload=dict(camera_spec_payload),
                    modalities=modalities,
                    render_fn=self.render_fn,
                    variant=str(payload.get("variant") or self.variant),
                )
                write_episode(path, updated)
                rendered.append({"episode_id": updated.episode_id, "timestep_count": len(updated.timesteps)})
            self._send_json(handler, HTTPStatus.OK, {"backend": "direct", "rendered": rendered})
            return
        if backend != "daemon":
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "backend must be 'direct' or 'daemon'."})
            return
        batch_id = f"opticalnav-{_utc_now().strftime('%Y%m%dT%H%M%S%f')}"
        jobs = []
        try:
            for path in paths:
                episode = read_episode(path)
                requests = build_episode_render_requests(
                    episode,
                    scene_state_payload=dict(scene_state_payload),
                    camera_spec_payload=dict(camera_spec_payload),
                    modalities=modalities,
                    job_id_mode="per_timestep",
                )
                for request in requests:
                    accepted = self.submit(request, variant=str(payload.get("variant") or self.variant))
                    timestep_index = int(request.extras.get("timestep_index", -1))
                    jobs.append({
                        "job_id": accepted.job_id,
                        "episode_id": episode.episode_id,
                        "timestep_index": timestep_index,
                        "status_url": accepted.status_url,
                    })
        except Exception as exc:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "submitted_jobs": jobs})
            return
        batch = {
            "batch_id": batch_id,
            "project_id": project_dir.name,
            "backend": "daemon",
            "created_at": _utc_now_iso(),
            "modalities": modalities,
            "jobs": jobs,
        }
        batch_path = project_dir / "render_batches" / f"{batch_id}.json"
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        self._send_json(handler, HTTPStatus.ACCEPTED, self._opticalnav_render_batch_payload(project_dir, batch_id))

    def _handle_head(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        path = parsed.path
        if path.startswith("/api/opticalnav/projects/"):
            rest = path[len("/api/opticalnav/projects/"):].strip("/")
            parts = [unquote(part) for part in rest.split("/") if part]
            if len(parts) == 5 and parts[1] == "scenes" and parts[3] == "mesh-cache":
                try:
                    project_dir = self._opticalnav_project_dir(parts[0])
                except ValueError:
                    handler.send_response(HTTPStatus.BAD_REQUEST)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                scene_id = parts[2]
                filename = unquote(parts[4])
                if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
                    handler.send_response(HTTPStatus.BAD_REQUEST)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                mesh_cache_dir = project_dir / "scenes" / scene_id / "mesh_cache"
                target = mesh_cache_dir / filename
                try:
                    target_resolved = target.resolve()
                    mesh_cache_dir_resolved = mesh_cache_dir.resolve()
                except OSError:
                    handler.send_response(HTTPStatus.NOT_FOUND)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                if mesh_cache_dir_resolved not in target_resolved.parents:
                    handler.send_response(HTTPStatus.FORBIDDEN)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                if not target_resolved.is_file():
                    handler.send_response(HTTPStatus.NOT_FOUND)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                try:
                    size = target_resolved.stat().st_size
                except OSError:
                    handler.send_response(HTTPStatus.NOT_FOUND)
                    handler.send_header("Content-Length", "0")
                    handler.end_headers()
                    return
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "text/plain; charset=utf-8")
                handler.send_header("Content-Length", str(size))
                handler.send_header("Cache-Control", "public, max-age=86400, immutable")
                handler.send_header("Connection", "close")
                handler.end_headers()
                return
        handler.send_response(HTTPStatus.NOT_FOUND)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/health":
                self._send_json(handler, HTTPStatus.OK, self._health_payload())
                return
            if self._proxy_to_render_queue(handler, "GET"):
                return
            if path == "/static/tailwind.css":
                self._serve_static_file(handler, self._static_dir / "tailwind.css")
                return
            if path.startswith("/static/app/"):
                # Serve SvelteKit build assets
                rel = path[len("/static/app/"):]
                self._serve_spa_file(handler, self._spa_dir / rel)
                return
            if path.startswith("/_app/"):
                # SvelteKit emits root-relative assets when paths.base is empty.
                self._serve_spa_file(handler, self._spa_dir / path.lstrip("/"))
                return
            if path == "/artifacts":
                artifact_path = _maybe_str(query.get("path", [None])[0])
                if not artifact_path:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Missing path query parameter."})
                    return
                self._serve_repo_artifact(handler, artifact_path)
                return
            if path == "/api/summary":
                self._send_json(handler, HTTPStatus.OK, self._summary_payload())
                return
            if path == "/api/render-jobs":
                self._send_json(handler, HTTPStatus.OK, {"jobs": self._job_records(limit=250)})
                return
            if path.startswith("/api/opticalnav/"):
                if self._handle_opticalnav_get(handler, path, query):
                    return
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav route: {path}"})
                return
            if path.startswith("/api/render-jobs/") and path.endswith("/log"):
                job_id = path[len("/api/render-jobs/"):-len("/log")]
                log_path = self._job_log_path(job_id)
                if not log_path.exists():
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "No log found for this job.", "job_id": job_id})
                    return
                try:
                    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    limit = int(_maybe_str(query.get("limit", [None])[0]) or 500)
                    tail = lines[-limit:] if len(lines) > limit else lines
                    self._send_json(handler, HTTPStatus.OK, {"job_id": job_id, "lines": tail, "total_lines": len(lines)})
                except Exception as exc:
                    self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            if path == "/api/scenes":
                self._send_json(handler, HTTPStatus.OK, {"scenes": self._scene_records()})
                return
            if path == "/api/debug/events":
                since = int(_maybe_str(query.get("since", [None])[0]) or 0)
                with self._condition:
                    events = [e for e in self._debug_events if e["id"] > since]
                self._send_json(handler, HTTPStatus.OK, {"events": events, "latest_id": self._debug_event_counter})
                return
            if path == "/api/isaac/scenes":
                self._send_json(handler, HTTPStatus.OK, {"scenes": self._isaac_scene_catalog_records()})
                return
            if path == "/api/material-presets":
                self._send_json(handler, HTTPStatus.OK, {"presets": self._material_presets()})
                return
            if path == "/api/material-library":
                from .material_library import get_library_response
                self._send_json(handler, HTTPStatus.OK, get_library_response(self.repo_root))
                return
            if path == "/api/preview-objects":
                from .sphere_preview import list_preview_objects, DEFAULT_PREVIEW_OBJECT
                self._send_json(handler, HTTPStatus.OK, {
                    "objects": list_preview_objects(),
                    "default": DEFAULT_PREVIEW_OBJECT,
                })
                return
            if path == "/api/material-jobs":
                self._send_json(handler, HTTPStatus.OK, {"jobs": _list_material_jobs()})
                return
            if path == "/api/dataset-download/status":
                self._handle_dataset_download_status(handler, query)
                return
            if path == "/api/user-settings":
                self._handle_user_settings_get(handler)
                return
            if path.startswith("/api/material-preview/"):
                self._handle_material_preview_get(handler, path, query)
                return
            if path == "/api/isaac/commands":
                self._send_json(handler, HTTPStatus.OK, {"commands": self._list_isaac_commands()})
                return
            if path == "/api/camera-rigs":
                self._send_json(handler, HTTPStatus.OK, self._list_camera_rigs())
                return
            if path == "/api/camera-rigs/ranger-mini/mesh":
                self._send_json(handler, HTTPStatus.OK, self._ranger_mini_mesh_for_camera_rig())
                return
            if path.startswith("/api/camera-rigs/"):
                rig_id = unquote(path[len("/api/camera-rigs/") :].rstrip("/"))
                if not rig_id:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "rig_id is required."})
                    return
                try:
                    self._send_json(handler, HTTPStatus.OK, self._load_camera_rig(rig_id))
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown camera rig: {rig_id}"})
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if path == "/api/isaac/telemetry/recent":
                limit = int(_maybe_str(query.get("limit", [None])[0]) or 25)
                self._send_json(handler, HTTPStatus.OK, {"events": self._telemetry_recent_rows(limit=max(1, min(limit, 200)))})
                return
            if path == "/api/isaac/telemetry/stats":
                self._send_json(handler, HTTPStatus.OK, self._telemetry_stats(limit=1200))
                return
            if path == "/api/isaac/commands/next":
                self._send_json(handler, HTTPStatus.OK, {"command": self._next_isaac_command()})
                return
            if path.startswith("/api/isaac/scenes/"):
                scene_id = path[len("/api/isaac/scenes/") :].rstrip("/")
                try:
                    self._send_json(handler, HTTPStatus.OK, self._isaac_scene_detail(scene_id))
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown Isaac scene_id: {scene_id}"})
                return
            if path == "/api/isaac/captures/latest":
                scene_id = _maybe_str(query.get("scene_id", [None])[0])
                capture = self._latest_capture_record(scene_id=scene_id)
                if capture is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "No captures available."})
                    return
                self._send_json(handler, HTTPStatus.OK, capture)
                return
            if path.startswith("/api/isaac/captures/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) == 5:
                    job_id = parts[3]
                    frame_id = parts[4]
                    try:
                        self._send_json(handler, HTTPStatus.OK, self._capture_detail_by_ids(job_id, frame_id))
                    except KeyError:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown capture: {job_id}/{frame_id}"})
                    return
            if path.startswith("/api/scenes/") and path.endswith("/floorplan"):
                scene_id = path[len("/api/scenes/") : -len("/floorplan")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._ensure_floorplan(scene_id))
                return
            if path.startswith("/api/scenes/") and path.endswith("/diagram-3d"):
                scene_id = path[len("/api/scenes/") : -len("/diagram-3d")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._scene_diagram_3d(scene_id))
                return
            if path.startswith("/api/scenes/") and path.endswith("/occupancy-map"):
                scene_id = unquote(path[len("/api/scenes/") : -len("/occupancy-map")].rstrip("/"))
                cell_size = float(query.get("cell_size", ["0.05"])[0])
                height_min = float(query.get("height_min", ["0.1"])[0])
                height_max = float(query.get("height_max", ["1.5"])[0])
                show_furniture = query.get("furniture", ["1"])[0] not in ("0", "false", "")
                payload = self._scene_occupancy_map(
                    scene_id,
                    cell_size=cell_size, height_min=height_min, height_max=height_max,
                    show_furniture=show_furniture,
                )
                self._send_json(handler, HTTPStatus.OK, payload)
                return
            if path.startswith("/api/scenes/") and path.endswith("/occupancy-map.png"):
                scene_id = unquote(path[len("/api/scenes/") : -len("/occupancy-map.png")].rstrip("/"))
                cell_size = float(query.get("cell_size", ["0.05"])[0])
                height_min = float(query.get("height_min", ["0.1"])[0])
                height_max = float(query.get("height_max", ["1.5"])[0])
                show_furniture = query.get("furniture", ["1"])[0] not in ("0", "false", "")
                grid = self._build_occupancy_grid(
                    scene_id, cell_size=cell_size, height_min=height_min, height_max=height_max,
                )
                if grid.get("status") != "ready":
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": grid.get("reason") or "unavailable"})
                    return
                png = self._render_occupancy_png(grid["_layers"], show_furniture=show_furniture)
                self._send_bytes(handler, HTTPStatus.OK, png, content_type="image/png",
                                 extra_headers={"Cache-Control": "private, max-age=15"})
                return
            if path.startswith("/api/scenes/") and path.endswith("/material-targets"):
                scene_id = path[len("/api/scenes/") : -len("/material-targets")].rstrip("/")
                try:
                    payload = self._scene_material_targets(scene_id)
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                    return
                except FileNotFoundError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, payload)
                return
            if path.startswith("/api/scenes/") and "/geometry/" in path:
                parts = path[len("/api/scenes/") :].split("/geometry/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1].endswith(".obj"):
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Expected /api/scenes/{scene_id}/geometry/{mesh_id}.obj"})
                    return
                scene_id = unquote(parts[0].rstrip("/"))
                mesh_id = unquote(parts[1][:-len(".obj")])
                self._serve_scene_geometry(handler, scene_id, mesh_id)
                return
            if path.startswith("/api/scenes/") and path.endswith("/captures"):
                scene_id = path[len("/api/scenes/") : -len("/captures")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, {"scene_id": scene_id, "captures": self._scene_detail(scene_id)["captures"]})
                return
            if path.startswith("/api/scenes/") and path.endswith("/render-options"):
                scene_id = path[len("/api/scenes/") : -len("/render-options")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._load_scene_render_options(scene_id))
                return
            if path.startswith("/api/scenes/"):
                scene_id = path[len("/api/scenes/") :].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._scene_detail(scene_id))
                return
            if path == "/api/integrations/isaac":
                self._send_json(handler, HTTPStatus.OK, self._isaac_guide_payload())
                return
            if path == "/isaac/session":
                self._send_json(handler, HTTPStatus.OK, self._active_isaac_session_summary(include_inventory=False))
                return

            if path == "/isaac/session/inventory":
                session = self._isaac_session
                if session is None:
                    self._send_json(handler, HTTPStatus.OK, {"status": "inactive", "object_inventory": []})
                else:
                    inventory = self._get_cached_session_inventory(session)
                    self._send_json(handler, HTTPStatus.OK, {"status": "active", "object_inventory": inventory})
                return
            if path.startswith("/jobs/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) == 2:
                    job_id = parts[1]
                    try:
                        status = self.get_status(job_id)
                    except KeyError:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown job_id: {job_id}"})
                        return
                    self._send_json(handler, HTTPStatus.OK, render_job_status_to_payload(status))
                    return

                if len(parts) == 3 and parts[2] == "manifest":
                    job_id = parts[1]
                    try:
                        manifest = self.get_manifest(job_id)
                    except KeyError:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown job_id: {job_id}"})
                        return
                    except RuntimeError as exc:
                        self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                        return
                    self._send_json(handler, HTTPStatus.OK, observation_bundle_manifest_to_payload(manifest))
                    return

            # SPA catch-all: serve index.html for all non-API GET routes
            self._serve_spa_index(handler)
        except _ClientDisconnectedError:
            return
        except Exception as exc:  # pragma: no cover - defensive path
            try:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except _ClientDisconnectedError:
                return

    def _serve_spa_index(self, handler: BaseHTTPRequestHandler) -> None:
        index = self._spa_dir / "index.html"
        if not index.exists():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {
                "error": "SPA not built. Run: cd apps/webui && npm run build"
            })
            return
        body = index.read_bytes()
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if self._proxy_to_render_queue(handler, "POST"):
                return
            payload = self._read_request_body(handler)

            if path == "/api/dataset-download":
                self._handle_dataset_download_post(handler, payload)
                return

            if path == "/api/user-settings":
                self._handle_user_settings_post(handler, payload)
                return

            if path.startswith("/api/material-preview/curated/") and path.endswith("/invalidate"):
                material_id = path[len("/api/material-preview/curated/"):-len("/invalidate")].strip("/")
                self._handle_invalidate_curated(handler, material_id)
                return

            if path.startswith("/api/material-preview/measured/") and path.endswith("/invalidate"):
                rest = path[len("/api/material-preview/measured/"):-len("/invalidate")].strip("/")
                parts = rest.split("/", 1)
                if len(parts) != 2:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "expected /api/material-preview/measured/{dataset_id}/{material_id}/invalidate"})
                    return
                self._handle_invalidate_measured(handler, parts[0], parts[1])
                return

            if path == "/api/material-previews/batch-invalidate":
                self._handle_batch_invalidate(handler, payload)
                return
            if path == "/api/material-jobs/clear-finished":
                cleared = _clear_finished_material_jobs()
                self._send_json(handler, HTTPStatus.OK, {"cleared": cleared})
                return
            if path == "/render":
                try:
                    accepted = self.submit_payload(payload)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.ACCEPTED, render_job_accepted_to_payload(accepted))
                return

            if path.startswith("/api/opticalnav/"):
                if self._handle_opticalnav_post(handler, path, payload):
                    return
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav route: {path}"})
                return

            if path == "/api/tests/smoke-render":
                scene_id = _maybe_str(payload.get("scene_id"))
                try:
                    accepted = self._enqueue_smoke_render(scene_id=scene_id)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.ACCEPTED, render_job_accepted_to_payload(accepted))
                return

            if path.startswith("/api/scenes/") and path.endswith("/prepare-basic"):
                scene_id = path[len("/api/scenes/"):-len("/prepare-basic")].rstrip("/")
                try:
                    result = self.prepare_basic_scene(scene_id)
                except KeyError:
                    self._send_json(
                        handler,
                        HTTPStatus.NOT_FOUND,
                        {"error": f"Unknown or unprepared scene_id: {scene_id}"},
                    )
                    return
                except FileNotFoundError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, {"scene_id": scene_id, **result})
                return

            if path.startswith("/api/render-jobs/") and path.endswith("/retry"):
                job_id = path[len("/api/render-jobs/"):-len("/retry")]
                with self._condition:
                    original = self._jobs.get(job_id)
                if original is None or original.status.status not in ("failed", "cancelled"):
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Job not found or not retryable.", "job_id": job_id})
                    return
                accepted = self.submit(original.render_request)
                self._send_json(handler, HTTPStatus.ACCEPTED, render_job_accepted_to_payload(accepted))
                return

            if path.startswith("/api/render-jobs/") and path.endswith("/delete"):
                job_id = path[len("/api/render-jobs/"):-len("/delete")]
                force_flag = _maybe_str(query.get("force", [None])[0]) or ""
                force = force_flag.lower() in {"1", "true", "yes", "on"}
                try:
                    self.delete_job(job_id, force=force)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, {"job_id": job_id, "deleted": True, "forced": force})
                return

            if path == "/api/isaac/scenes/register":
                try:
                    result = self._register_isaac_scene(payload)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return
            if path == "/api/isaac/commands":
                try:
                    result = self._queue_isaac_command(payload)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.ACCEPTED, result)
                return
            if path.startswith("/api/camera-rigs/"):
                rig_id = unquote(path[len("/api/camera-rigs/") :].rstrip("/"))
                if not rig_id:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "rig_id is required."})
                    return
                try:
                    result = self._save_camera_rig(rig_id, payload)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return
            if path == "/api/isaac/commands/start":
                try:
                    result = self._start_isaac_command(payload)
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return
            if path.startswith("/api/isaac/commands/") and path.endswith("/progress"):
                command_id = path[len("/api/isaac/commands/") : -len("/progress")].rstrip("/")
                try:
                    result = self._update_isaac_command_progress(command_id, payload)
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown command_id: {command_id}"})
                    return
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return
            if path.startswith("/api/isaac/commands/") and path.endswith("/complete"):
                command_id = path[len("/api/isaac/commands/") : -len("/complete")].rstrip("/")
                try:
                    result = self._complete_isaac_command(command_id, payload)
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown command_id: {command_id}"})
                    return
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return

            if path.startswith("/jobs/") and path.endswith("/cancel"):
                parts = [part for part in path.split("/") if part]
                if len(parts) == 3:
                    job_id = parts[1]
                    try:
                        status = self.cancel(job_id)
                    except KeyError:
                        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown job_id: {job_id}"})
                        return
                    except RuntimeError as exc:
                        self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                        return
                    self._send_json(handler, HTTPStatus.OK, render_job_status_to_payload(status))
                    return

            if path == "/isaac/render":
                timeout_s = float(payload.get("timeout_s", 600.0))
                try:
                    result = self._handle_isaac_render_blocked(payload, timeout_s=timeout_s)
                except TimeoutError:
                    self._send_json(handler, 504, {"error": "Render timed out"})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return

            if path == "/isaac/render/submit":
                try:
                    accepted = self._handle_isaac_render_submit(payload)
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.ACCEPTED, render_job_accepted_to_payload(accepted))
                return

            if path == "/isaac/session/open":
                try:
                    summary = self._open_isaac_session(payload)
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, summary)
                return

            if path == "/isaac/session/update_state":
                try:
                    summary = self._update_isaac_state(payload)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, summary)
                return

            if path == "/isaac/session/update_materials":
                try:
                    summary = self._update_isaac_materials(payload)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, summary)
                return

            if path == "/isaac/session/update_selection":
                try:
                    summary = self._update_isaac_selection(payload)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, summary)
                return

            if path == "/isaac/session/register_sensors":
                try:
                    summary = self._register_isaac_sensors(payload)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, summary)
                return

            if path == "/isaac/capture":
                try:
                    result = self._handle_isaac_session_capture(payload)
                except RuntimeError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except TimeoutError:
                    self._send_json(handler, 504, {"error": "Render timed out"})
                    return
                except (KeyError, ValueError) as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                if isinstance(result, RenderJobAccepted):
                    self._send_json(handler, HTTPStatus.ACCEPTED, render_job_accepted_to_payload(result))
                else:
                    self._send_json(handler, HTTPStatus.OK, result)
                return

            if path.startswith("/api/scenes/") and path.endswith("/render-options"):
                scene_id = path[len("/api/scenes/") : -len("/render-options")].rstrip("/")
                modalities = payload.get("modalities", [])
                invalid = [m for m in modalities if m not in SUPPORTED_MODALITIES]
                if invalid:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Unsupported modalities: {invalid}"})
                    return
                options_path = self._render_options_path(scene_id)
                options_path.parent.mkdir(parents=True, exist_ok=True)
                data: dict[str, Any] = {
                    "scene_id": scene_id,
                    "modalities": modalities,
                    "spp": int(payload.get("spp", 64)),
                    "width": int(payload.get("width", 1280)),
                    "height": int(payload.get("height", 720)),
                    "upscale": str(payload.get("upscale", "none")),
                    "updated_at": _utc_now_iso(),
                }
                options_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                self._send_json(handler, HTTPStatus.OK, data)
                return

            if path.startswith("/api/scenes/") and path.endswith("/material-overrides/batch"):
                scene_id = path[len("/api/scenes/") : -len("/material-overrides/batch")].rstrip("/")
                overrides = payload.get("overrides")
                if not isinstance(overrides, list):
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "'overrides' must be a list"})
                    return
                replace_mode = _maybe_str(payload.get("replace_mode")) or "merge"
                try:
                    result = self.apply_material_overrides_batch(
                        scene_id,
                        overrides=overrides,
                        replace_mode=replace_mode,
                    )
                except KeyError:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
                    return
                except FileNotFoundError as exc:
                    self._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
                    return
                except ValueError as exc:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(handler, HTTPStatus.OK, result)
                return

            if path.startswith("/api/scenes/") and path.endswith("/apply-measured-material"):
                scene_id = path[len("/api/scenes/") : -len("/apply-measured-material")].rstrip("/")
                prim_path = payload.get("prim_path")
                bsdf_type = payload.get("bsdf_type", "measured_polarized")
                measured_file_path = payload.get("measured_file_path") or ""
                dataset_id = payload.get("dataset_id", "")
                material_id = payload.get("material_id", "")
                if not prim_path:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "prim_path required"})
                    return
                if not measured_file_path:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "measured_file_path required (material not downloaded)"})
                    return
                session = self._isaac_session
                if session is None or session.scene_id != scene_id:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"No active session for scene {scene_id!r}"})
                    return
                override = BsdfOverride(
                    bsdf_type=bsdf_type,
                    measured_file_path=measured_file_path,
                    dataset_id=dataset_id or None,
                    material_id=material_id or None,
                )
                session.material_overrides[prim_path] = override
                existing_obj = session.objects.get(prim_path)
                if existing_obj is not None:
                    existing_obj.bsdf_override = override
                    existing_obj.bsdf_override_key = f"{dataset_id}/{material_id}" if dataset_id else bsdf_type
                session.updated_at = _utc_now_iso()
                session.material_revision += 1
                session.material_dirty = True
                self._send_json(handler, HTTPStatus.OK, {
                    "prim_path": prim_path,
                    "bsdf_type": bsdf_type,
                    "dataset_id": dataset_id,
                    "material_id": material_id,
                    "measured_file_path": measured_file_path,
                    "status": "applied",
                })
                return

            if path.startswith("/api/scenes/") and path.endswith("/apply-curated-material"):
                from .curated_library import get_curated_material

                scene_id = path[len("/api/scenes/") : -len("/apply-curated-material")].rstrip("/")
                prim_path = payload.get("prim_path")
                material_id = payload.get("material_id", "")
                if not prim_path:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "prim_path required"})
                    return
                if not material_id:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "material_id required"})
                    return
                mat = get_curated_material(material_id)
                if mat is None:
                    self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown curated material: {material_id}"})
                    return
                session = self._isaac_session
                if session is None or session.scene_id != scene_id:
                    self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"No active session for scene {scene_id!r}"})
                    return
                override = BsdfOverride(
                    bsdf_type="curated",
                    material_id=mat.material_id,
                    extras={
                        "curated_bsdf_spec": dict(mat.bsdf_spec),
                        "curated_category": mat.category,
                        "curated_display_name": mat.display_name,
                    },
                )
                session.material_overrides[prim_path] = override
                existing_obj = session.objects.get(prim_path)
                if existing_obj is not None:
                    existing_obj.bsdf_override = override
                    existing_obj.bsdf_override_key = f"curated/{mat.material_id}"
                session.updated_at = _utc_now_iso()
                session.material_revision += 1
                session.material_dirty = True
                self._send_json(handler, HTTPStatus.OK, {
                    "prim_path": prim_path,
                    "bsdf_type": "curated",
                    "material_id": mat.material_id,
                    "category": mat.category,
                    "display_name": mat.display_name,
                    "status": "applied",
                })
                return

            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})
        except _ClientDisconnectedError:
            return
        except Exception as exc:  # pragma: no cover - defensive path
            try:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except _ClientDisconnectedError:
                return

    def _handle_put(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            if self._proxy_to_render_queue(handler, "PUT"):
                return
            payload = self._read_request_body(handler)
            if path.startswith("/api/opticalnav/"):
                if self._handle_opticalnav_put(handler, path, payload):
                    return
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown OpticalNav route: {path}"})
                return
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})
        except _ClientDisconnectedError:
            return
        except Exception as exc:  # pragma: no cover - defensive path
            try:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except _ClientDisconnectedError:
                return

    def _default_shape_map_ref(self, snapshot: Any) -> str | None:
        explicit_ref = getattr(snapshot, "shape_map_ref", None)
        if explicit_ref:
            return str(explicit_ref)
        scene_snapshot_ref = getattr(snapshot, "scene_snapshot_ref", None)
        if isinstance(scene_snapshot_ref, str) and scene_snapshot_ref.endswith(".json"):
            candidate = Path(scene_snapshot_ref).with_name("shape_map.json").as_posix()
            resolved = resolve_repo_path(self.repo_root, candidate)
            if resolved.exists():
                return candidate
        scene_ref = getattr(snapshot, "mitsuba_scene_ref", None)
        if isinstance(scene_ref, str) and scene_ref:
            scene_path = Path(scene_ref)
            candidates = [
                scene_path.with_suffix(".shape_map.json").as_posix(),
                scene_path.with_name(f"{scene_path.stem}.shape_map.json").as_posix(),
                scene_path.with_name("shape_map.json").as_posix(),
            ]
            for candidate in candidates:
                resolved = resolve_repo_path(self.repo_root, candidate)
                if resolved.exists():
                    return candidate
        return None

    def _prim_to_shape_ids_for_snapshot(self, snapshot: Any) -> dict[str, list[str]]:
        shape_map_ref = self._default_shape_map_ref(snapshot)
        if not shape_map_ref:
            raise ValueError("IsaacStateSnapshot must include shape_map_ref or provide a discoverable sibling shape_map.json.")
        payload = read_shape_mapping(shape_map_ref, repo_root=self.repo_root)
        prim_to_shape_ids = payload.get("prim_to_shape_ids", {})
        if not isinstance(prim_to_shape_ids, Mapping):
            raise ValueError(f"Invalid shape mapping payload in {shape_map_ref}: missing prim_to_shape_ids object.")
        return {
            str(prim_path): [str(shape_id) for shape_id in shape_ids]
            for prim_path, shape_ids in prim_to_shape_ids.items()
            if isinstance(shape_ids, list)
        }

    def _render_request_from_isaac_snapshot(self, snapshot: Any) -> tuple[RenderRequest, str]:
        scene_xml = resolve_repo_path(self.repo_root, snapshot.mitsuba_scene_ref)
        if not scene_xml.exists():
            raise ValueError(f"Scene XML not found: {snapshot.mitsuba_scene_ref}")
        cam = snapshot.camera
        if cam is None:
            raise ValueError("IsaacStateSnapshot must include a camera for Isaac render endpoints.")

        prim_to_shape_ids = self._prim_to_shape_ids_for_snapshot(snapshot)
        scene_override = _isaac_snapshot_to_scene_override(snapshot)
        if scene_override is None:
            scene_override = SceneOverrideSpec(prim_to_shape_ids=prim_to_shape_ids)
        else:
            scene_override.prim_to_shape_ids = prim_to_shape_ids
        # Layer the agent-driven sidecar (if any) on top so persisted picks
        # survive across daemon restarts and reach renders that don't go through
        # an Isaac session-mutated snapshot.
        self._merge_sidecar_overrides(scene_override, snapshot.mitsuba_scene_ref)

        timestamp = str(snapshot.timestamp)
        stamp = timestamp.replace(":", "").replace("-", "").replace("+", "").replace("T", "_")
        job_id = make_job_id("isaac") if not snapshot.snapshot_id else f"isaac-{snapshot.snapshot_id}"
        frame_id = f"frame_{stamp}" if stamp else f"frame_{snapshot.snapshot_id}"
        request_id = f"request_{snapshot.snapshot_id}"
        scene_snapshot_ref = snapshot.scene_snapshot_ref or snapshot.shape_map_ref or snapshot.mitsuba_scene_ref
        shape_map_ref = self._default_shape_map_ref(snapshot)

        scene_state = SceneState(
            job_id=job_id,
            scene_id=str(snapshot.scene_id),
            frame_id=frame_id,
            timestamp=timestamp,
            scene_snapshot_ref=str(scene_snapshot_ref),
            mitsuba_scene_ref=str(snapshot.mitsuba_scene_ref),
            scene_version=snapshot.extras.get("scene_version"),
            illumination_setup=snapshot.extras.get("illumination_setup", "ambient_room"),
            extras={
                "snapshot_id": snapshot.snapshot_id,
                "shape_map_ref": shape_map_ref,
            },
        )
        camera_spec = CameraSpec(
            camera_id=cam.camera_id or "isaac_viewport",
            name=cam.name or "Isaac Active Viewport",
            camera_to_world=normalize_mat4_storage(cam.camera_to_world).reshape(-1).astype(float).tolist(),
            fov_deg=float(cam.fov_deg),
            resolution=list(cam.resolution) if cam.resolution is not None else None,
            sensor_modality=cam.sensor_modality,
            sensor_sync_group=cam.sensor_sync_group,
            calibration_ref=cam.calibration_ref,
            source_camera_id=cam.source_camera_id,
            extras=dict(cam.extras),
        )
        _snap_modalities = list(snapshot.modalities) if snapshot.modalities else []
        if not _snap_modalities:
            _saved = self._load_scene_render_options(str(snapshot.scene_id))
            _snap_modalities = _saved.get("modalities", ["rgb"])
        _snap_render_settings = dict(snapshot.render_settings)
        render_request = RenderRequest(
            request_id=request_id,
            job_id=job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=scene_state,
            camera_specs=[camera_spec],
            modalities=_snap_modalities,
            robot_state=snapshot.robot_state or RobotState(),
            render_settings=_snap_render_settings,
            scene_override=scene_override,
            assist_light=AssistLightSpec(**snapshot.extras["assist_light"]) if isinstance(snapshot.extras.get("assist_light"), Mapping) else None,
            depth_approx=DepthApproxSpec(**snapshot.extras["depth_approx"]) if isinstance(snapshot.extras.get("depth_approx"), Mapping) else None,
            extras={
                "source": "isaac_extension",
                "snapshot_id": snapshot.snapshot_id,
                "shape_map_ref": shape_map_ref,
                "submit_mode": snapshot.submit_mode,
                **dict(snapshot.extras),
            },
        )
        return render_request, str(shape_map_ref)

    def _active_isaac_session_summary(self, *, include_inventory: bool = True) -> dict[str, Any]:
        session = self._isaac_session
        if session is None:
            return {"status": "inactive", "session": None}
        robot_inventory = self._session_robot_inventory(session)
        scene_record = next((item for item in self._isaac_scene_catalog_records() if item.get("scene_id") == session.scene_id), None)
        result: dict[str, Any] = {
            "status": "active",
            "session": {
                "scene_id": session.scene_id,
                "usd_stage_path": scene_record.get("usd_stage_path") if scene_record else None,
                "mitsuba_scene_ref": session.mitsuba_scene_ref,
                "shape_map_ref": session.shape_map_ref,
                "scene_snapshot_ref": session.scene_snapshot_ref,
                "opened_at": session.opened_at,
                "updated_at": session.updated_at,
                "object_count": len(session.objects),
                "material_override_count": len(session.material_overrides),
                "sensor_count": len(session.sensors),
                "sensor_ids": sorted(session.sensors.keys()),
                "robot_count": len(robot_inventory),
                "robot_inventory": robot_inventory,
                "selected_prim_paths": list(session.selected_prim_paths),
                "session_revision": int(session.session_revision),
                "state_revision": int(session.state_revision),
                "material_revision": int(session.material_revision),
                "sensor_revision": int(session.sensor_revision),
                "state_dirty": bool(session.state_dirty),
                "material_dirty": bool(session.material_dirty),
                "material_overrides": {
                    prim_path: override.bsdf_type
                    for prim_path, override in sorted(session.material_overrides.items())
                },
                "material_override_details": {
                    prim_path: bsdf_override_to_payload(override)
                    for prim_path, override in sorted(session.material_overrides.items())
                },
                "active_viewport_camera": self._active_viewport_camera_payload(session),
            },
        }
        if include_inventory:
            result["session"]["object_inventory"] = self._session_object_inventory(session)
        return result

    def _get_cached_session_inventory(self, session: "_IsaacActiveSession") -> list[Any]:
        """Return _session_object_inventory() with a 3-second TTL cache."""
        now = time.monotonic()
        if self._session_inventory_cache is not None and (now - self._session_inventory_cache_ts) < 3.0:
            return self._session_inventory_cache
        inventory = self._session_object_inventory(session)
        self._session_inventory_cache = inventory
        self._session_inventory_cache_ts = now
        return inventory

    def _invalidate_session_inventory_cache(self) -> None:
        self._session_inventory_cache = None
        self._session_inventory_cache_ts = 0.0

    def _require_active_isaac_session(self) -> _IsaacActiveSession:
        if self._isaac_session is None:
            raise RuntimeError("No active Isaac scene session. Call POST /isaac/session/open first.")
        return self._isaac_session

    def _matches_active_isaac_session(self, session_open: IsaacSessionOpen) -> bool:
        session = self._isaac_session
        if session is None:
            return False
        return (
            session.scene_id == session_open.scene_id
            and session.mitsuba_scene_ref == session_open.mitsuba_scene_ref
            and session.shape_map_ref == session_open.shape_map_ref
        )

    def _set_render_job_extra(self, job_id: str, key: str, value: Any) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status.extras[key] = value
            self._persist_status_unlocked(job)

    def _wait_for_render_job(self, job_id: str, *, timeout_s: float) -> RenderJobStatus:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while True:
                job = self._jobs.get(job_id)
                if job is None:
                    raise KeyError(job_id)
                status = job.status.status
                if status in {"succeeded", "failed", "cancelled"}:
                    return RenderJobStatus(**render_job_status_to_payload(job.status))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for render job {job_id}")
                self._condition.wait(timeout=min(0.5, remaining))

    def _blocking_render_result(self, status: RenderJobStatus) -> dict[str, Any]:
        if status.status == "failed":
            raise RuntimeError(status.error or f"Render job failed: {status.job_id}")
        if status.status == "cancelled":
            raise RuntimeError(f"Render job cancelled: {status.job_id}")
        manifest = self.get_manifest(status.job_id)
        return {
            "status": "completed",
            "job_id": status.job_id,
            "frame_id": status.frame_id,
            "manifest_path": status.manifest_path,
            "artifacts": _artifact_paths_from_bundle(manifest),
        }

    def _open_isaac_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_open_payload = payload.get("session_open") if isinstance(payload.get("session_open"), Mapping) else payload
        session_open = isaac_session_open_from_payload(dict(session_open_payload))
        if self._matches_active_isaac_session(session_open):
            session = self._require_active_isaac_session()
            session.updated_at = _utc_now_iso()
            session.session_revision += 1
            summary = self._active_isaac_session_summary(include_inventory=False)
            summary["reused"] = True
            self._broadcast_scene_telemetry(force=True)
            return summary
        scene_xml = resolve_repo_path(self.repo_root, session_open.mitsuba_scene_ref)
        if not scene_xml.exists():
            raise ValueError(f"Scene XML not found: {session_open.mitsuba_scene_ref}")
        shape_map_payload = read_shape_mapping(session_open.shape_map_ref, repo_root=self.repo_root)
        prim_to_shape_ids = shape_map_payload.get("prim_to_shape_ids", {})
        if not isinstance(prim_to_shape_ids, Mapping):
            raise ValueError(f"Invalid shape map payload in {session_open.shape_map_ref}: missing prim_to_shape_ids.")

        scene_snapshot_ref = session_open.scene_snapshot_ref or shape_map_payload.get("scene_snapshot_ref")
        timestamp = _utc_now_iso()
        self._isaac_session = _IsaacActiveSession(
            scene_id=session_open.scene_id,
            mitsuba_scene_ref=session_open.mitsuba_scene_ref,
            shape_map_ref=session_open.shape_map_ref,
            scene_snapshot_ref=str(scene_snapshot_ref) if scene_snapshot_ref else None,
            prim_to_shape_ids={
                str(prim_path): [str(shape_id) for shape_id in shape_ids]
                for prim_path, shape_ids in prim_to_shape_ids.items()
                if isinstance(shape_ids, list)
            },
            objects={},
            material_overrides={},
            sensors={},
            selected_prim_paths=[],
            opened_at=timestamp,
            updated_at=timestamp,
            session_revision=1,
            state_revision=0,
            material_revision=0,
            sensor_revision=0,
            state_dirty=True,
            material_dirty=False,
        )
        self._invalidate_session_inventory_cache()
        summary = self._active_isaac_session_summary(include_inventory=False)
        summary["reused"] = False
        self._broadcast_scene_telemetry(force=True)
        return summary

    def _update_isaac_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._require_active_isaac_session()
        patch_payload = payload.get("state_patch") if isinstance(payload.get("state_patch"), Mapping) else payload
        state_patch = isaac_state_patch_from_payload(dict(patch_payload))
        for obj in state_patch.objects:
            existing = session.objects.get(obj.prim_path)
            if existing is not None and obj.visible is None:
                obj.visible = existing.visible
            session.objects[obj.prim_path] = obj
            if obj.bsdf_override is not None:
                session.material_overrides[obj.prim_path] = obj.bsdf_override
        session.updated_at = state_patch.timestamp or _utc_now_iso()
        session.state_revision += 1
        session.state_dirty = False
        self._invalidate_session_inventory_cache()
        summary = self._active_isaac_session_summary(include_inventory=False)
        summary["updated_objects"] = len(state_patch.objects)
        return summary

    def _update_isaac_materials(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._require_active_isaac_session()
        patch_payload = payload.get("material_patch") if isinstance(payload.get("material_patch"), Mapping) else payload
        material_patch = isaac_material_patch_from_payload(dict(patch_payload))
        clear_paths = material_patch.extras.get("clear_paths") if isinstance(material_patch.extras, dict) else None
        if isinstance(clear_paths, list):
            for prim_path in clear_paths:
                path = str(prim_path or "")
                if not path:
                    continue
                session.material_overrides.pop(path, None)
                existing = session.objects.get(path)
                if existing is not None:
                    existing.bsdf_override = None
                    existing.bsdf_override_key = None
        for prim_path, override in material_patch.overrides.items():
            session.material_overrides[prim_path] = override
            existing = session.objects.get(prim_path)
            if existing is not None:
                existing.bsdf_override = override
                existing.bsdf_override_key = override.bsdf_type
        session.updated_at = material_patch.timestamp or _utc_now_iso()
        session.material_revision += 1
        session.material_dirty = False
        self._invalidate_session_inventory_cache()
        summary = self._active_isaac_session_summary(include_inventory=False)
        summary["updated_materials"] = len(material_patch.overrides)
        summary["cleared_materials"] = len(clear_paths) if isinstance(clear_paths, list) else 0
        return summary

    def _update_isaac_selection(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._require_active_isaac_session()
        selected_payload = payload.get("selected_prim_paths")
        if not isinstance(selected_payload, list):
            raise ValueError("selected_prim_paths must be a list.")
        prev_paths = set(session.selected_prim_paths)
        session.selected_prim_paths = [str(path) for path in selected_payload if isinstance(path, str) and path]
        session.updated_at = _utc_now_iso()
        # Fire debug event only when selection actually changes
        new_paths = set(session.selected_prim_paths)
        if new_paths != prev_paths:
            if new_paths:
                label = session.selected_prim_paths[0].split("/")[-1]
                extra = f" +{len(new_paths)-1}" if len(new_paths) > 1 else ""
                self._push_debug_event("selection", f"🖱 선택: {label}{extra}", {"paths": session.selected_prim_paths})
            else:
                self._push_debug_event("selection", "🖱 선택 해제", {"paths": []})
        summary = self._active_isaac_session_summary(include_inventory=False)
        summary["selected_prim_count"] = len(session.selected_prim_paths)
        return summary

    def _register_isaac_sensors(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._require_active_isaac_session()
        sensors_payload = payload.get("sensors")
        if isinstance(sensors_payload, list):
            sensors = [isaac_sensor_spec_from_payload(dict(item)) for item in sensors_payload if isinstance(item, Mapping)]
        else:
            single_payload = payload.get("sensor") if isinstance(payload.get("sensor"), Mapping) else payload
            sensors = [isaac_sensor_spec_from_payload(dict(single_payload))]
        for sensor in sensors:
            prev = session.sensors.get(sensor.sensor_id)
            session.sensors[sensor.sensor_id] = sensor
            # Fire debug event when the viewport camera moves (any translation or rotation)
            if sensor.camera_to_world is not None:
                # Compare full matrix rounded to 1 decimal to avoid jitter noise
                _mat_vals = list(sensor.camera_to_world)
                new_sig = tuple(round(float(v), 1) for v in _mat_vals)
                prev_sig = tuple(round(float(v), 1) for v in list(prev.camera_to_world)) if (prev and prev.camera_to_world is not None) else None
                if new_sig != prev_sig:
                    # Extract translation: matrix[:3, 3] after normalising storage order
                    try:
                        _m = normalize_mat4_storage(_mat_vals)  # → (4,4) column-major
                        x, y, z = float(_m[0, 3]), float(_m[1, 3]), float(_m[2, 3])
                    except Exception:
                        x, y, z = 0.0, 0.0, 0.0
                    self._push_debug_event(
                        "camera",
                        f"📷 카메라 이동: ({x:.1f}, {y:.1f}, {z:.1f})",
                        {"sensor_id": sensor.sensor_id, "pos": [x, y, z], "fov_deg": sensor.fov_deg},
                    )
        session.updated_at = _utc_now_iso()
        session.sensor_revision += 1
        self._broadcast_scene_telemetry()
        # Lightweight response — inventory rebuild not needed for sensor registration
        summary = self._active_isaac_session_summary(include_inventory=False)
        summary["registered_sensors"] = [sensor.sensor_id for sensor in sensors]
        return summary

    def _camera_spec_from_isaac_sensor(self, sensor: IsaacSensorSpec) -> CameraSpec:
        if sensor.camera_to_world is None or sensor.fov_deg is None:
            raise ValueError(f"Registered sensor {sensor.sensor_id} is missing camera_to_world or fov_deg.")
        camera_to_world = normalize_mat4_storage(sensor.camera_to_world).reshape(-1).astype(float).tolist()
        return CameraSpec(
            camera_id=sensor.sensor_id,
            name=sensor.name,
            camera_to_world=camera_to_world,
            fov_deg=float(sensor.fov_deg),
            resolution=list(sensor.resolution) if sensor.resolution is not None else None,
            sensor_modality="multimodal",
            sensor_sync_group=sensor.sensor_sync_group,
            calibration_ref=sensor.calibration_ref,
            source_camera_id=sensor.pose_source,
            extras=dict(sensor.extras),
        )

    def _render_request_from_active_isaac_session(self, capture_request: IsaacCaptureRequest) -> RenderRequest:
        session = self._require_active_isaac_session()
        sync_mode = str(capture_request.extras.get("sync_mode") or "full_resync")
        sync_policy = str(capture_request.extras.get("sync_policy") or "auto")
        force_resync = bool(capture_request.extras.get("force_resync", False))
        if capture_request.sensor_id:
            sensor = session.sensors.get(capture_request.sensor_id)
            if sensor is None:
                raise ValueError(f"Unknown sensor_id for active Isaac session: {capture_request.sensor_id}")
            camera_spec = self._camera_spec_from_isaac_sensor(sensor)
            requested_modalities = list(capture_request.modalities or sensor.modalities or ["rgb"])
            sensor_resolution = list(sensor.resolution) if sensor.resolution is not None else None
        elif capture_request.camera is not None:
            camera_spec = capture_request.camera
            requested_modalities = list(capture_request.modalities or ["rgb"])
            sensor_resolution = list(camera_spec.resolution) if camera_spec.resolution is not None else None
        else:
            raise ValueError("Isaac capture requires either sensor_id or inline camera.")

        timestamp = _utc_now_iso()
        stamp = self._timestamp_slug()
        job_id = make_job_id("isaac-session")
        frame_id = f"frame_{stamp}"
        request_id = f"request_{stamp}"
        scene_override = SceneOverrideSpec(
            prim_to_shape_ids=dict(session.prim_to_shape_ids),
            bsdf_overrides={prim_path: override for prim_path, override in session.material_overrides.items()},
            transform_overrides={
                prim_path: list(obj.transform)
                for prim_path, obj in session.objects.items()
                if obj.transform is not None
            },
            extras={
                "source": "isaac_session_v2",
                "object_count": len(session.objects),
                "sync_mode": sync_mode,
                "state_revision": int(session.state_revision),
                "material_revision": int(session.material_revision),
            },
        )
        render_settings = dict(capture_request.render_settings)
        if sensor_resolution:
            render_settings.setdefault("width", int(sensor_resolution[0]))
            if len(sensor_resolution) > 1:
                render_settings.setdefault("height", int(sensor_resolution[1]))
        sensor_extras = dict(camera_spec.extras or {})
        if "nir_intensity" in requested_modalities:
            if sensor_extras.get("wavelength_min_nm") is not None:
                render_settings.setdefault("nir_wavelength_min_nm", float(sensor_extras["wavelength_min_nm"]))
            if sensor_extras.get("wavelength_max_nm") is not None:
                render_settings.setdefault("nir_wavelength_max_nm", float(sensor_extras["wavelength_max_nm"]))
            if sensor_extras.get("active_emitter_radiance") is not None:
                render_settings.setdefault("nir_active_emitter_radiance", float(sensor_extras["active_emitter_radiance"]))
        if "lidar_point_cloud" in requested_modalities:
            for extra_key, setting_key in (
                ("horizontal_fov_deg", "lidar_horizontal_fov_deg"),
                ("vertical_fov_min_deg", "lidar_vertical_fov_min_deg"),
                ("vertical_fov_max_deg", "lidar_vertical_fov_max_deg"),
                ("min_range_m", "lidar_min_range_m"),
                ("max_range_m", "lidar_max_range_m"),
                ("wavelength_nm", "lidar_wavelength_nm"),
            ):
                if sensor_extras.get(extra_key) is not None:
                    render_settings.setdefault(setting_key, float(sensor_extras[extra_key]))
        assist_light = None
        if any(modality in requested_modalities for modality in ("active_nir_intensity", "nir_intensity")):
            assist_light = AssistLightSpec(
                mode="camera_aligned_rect",
                distance_m=0.14,
                size_world=[4.8, 3.6],
                spectrum_mode="nir_grayscale_proxy",
                polarized=False,
                extras={"radiance": float(render_settings.get("nir_active_emitter_radiance", 40.0))},
            )
        scene_state = SceneState(
            job_id=job_id,
            scene_id=session.scene_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_snapshot_ref=session.scene_snapshot_ref or session.shape_map_ref,
            mitsuba_scene_ref=session.mitsuba_scene_ref,
            scene_version="isaac_session_v2",
            illumination_setup="ambient_room",
            extras={"shape_map_ref": session.shape_map_ref},
        )
        return RenderRequest(
            request_id=request_id,
            job_id=job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=scene_state,
            camera_specs=[camera_spec],
            modalities=requested_modalities,
            robot_state=RobotState(),
            render_settings=render_settings,
            scene_override=scene_override,
            assist_light=assist_light,
            extras={
                "source": "isaac_session_v2",
                "submit_mode": capture_request.submit_mode,
                "shape_map_ref": session.shape_map_ref,
                "sync_policy": sync_policy,
                "sync_mode": sync_mode,
                "force_resync": force_resync,
                "session_revision": int(session.session_revision),
                "state_revision": int(session.state_revision),
                "material_revision": int(session.material_revision),
                "sensor_revision": int(session.sensor_revision),
                **dict(capture_request.extras),
            },
        )

    def _handle_isaac_session_capture(self, payload: dict[str, Any]) -> Any:
        capture_payload = payload.get("capture_request") if isinstance(payload.get("capture_request"), Mapping) else payload
        capture_request = isaac_capture_request_from_payload(dict(capture_payload))
        render_request = self._render_request_from_active_isaac_session(capture_request)
        variant = str(payload.get("variant") or render_request.render_settings.get("variant") or self.variant)
        runtime_overrides = payload.get("runtime_overrides") or {}
        command_id = _maybe_str(payload.get("command_id"))
        accepted = self.submit(render_request, variant=variant, runtime_overrides=runtime_overrides)
        if command_id:
            self._set_render_job_extra(accepted.job_id, "isaac_command_id", command_id)
        if capture_request.submit_mode == "async":
            return accepted
        timeout_s = float(payload.get("timeout_s", 600.0))
        status = self._wait_for_render_job(accepted.job_id, timeout_s=timeout_s)
        result = self._blocking_render_result(status)
        result["session"] = self._active_isaac_session_summary()["session"]
        return result

    def _handle_isaac_render_submit(self, payload: dict[str, Any]) -> RenderJobAccepted:
        snapshot = isaac_state_snapshot_from_payload(payload["isaac_state"])
        render_request, _shape_map_ref = self._render_request_from_isaac_snapshot(snapshot)
        variant = str(payload.get("variant") or render_request.render_settings.get("variant") or self.variant)
        runtime_overrides = payload.get("runtime_overrides") or {}
        return self.submit(render_request, variant=variant, runtime_overrides=runtime_overrides)

    def _handle_isaac_render_blocked(self, payload: dict[str, Any], *, timeout_s: float = 600.0) -> dict[str, Any]:
        """Handle POST /isaac/render in blocked mode — wait for render, return artifacts immediately."""
        snapshot = isaac_state_snapshot_from_payload(payload["isaac_state"])
        render_request, shape_map_ref = self._render_request_from_isaac_snapshot(snapshot)
        variant = str(payload.get("variant") or render_request.render_settings.get("variant") or self.variant)
        accepted = self.submit(render_request, variant=variant, runtime_overrides=payload.get("runtime_overrides") or {})
        status = self._wait_for_render_job(accepted.job_id, timeout_s=timeout_s)
        result = self._blocking_render_result(status)
        result["snapshot_id"] = snapshot.snapshot_id
        result["shape_map_ref"] = shape_map_ref
        return result

    def _isaac_render_stage_message(self, stage: str, payload: Mapping[str, Any] | None = None) -> str:
        ctx = payload if isinstance(payload, Mapping) else {}
        camera_id = _maybe_str(ctx.get("camera_id"))
        pass_name = _maybe_str(ctx.get("pass"))
        spp = ctx.get("spp")
        pass_index = ctx.get("pass_index")
        total_passes = ctx.get("total_passes")
        pass_suffix = f" ({pass_name})" if pass_name else ""
        cam_suffix = f" · {camera_id}" if camera_id else ""
        spp_suffix = f" · {spp} spp" if spp else ""
        count_suffix = f" [{pass_index}/{total_passes}]" if pass_index and total_passes else ""
        if stage == "ambient":
            return f"Rendering ambient branch{cam_suffix}."
        if stage == "active":
            return f"Rendering active/NIR branch{cam_suffix}."
        if stage == "polar":
            return f"Rendering polarization branch{cam_suffix}."
        if stage == "staging_scene":
            return f"Preparing scene XML{pass_suffix}{count_suffix}."
        if stage == "loading_scene":
            sub = _maybe_str(ctx.get("sub_step"))
            mesh_n = ctx.get("mesh_count")
            tex_n = ctx.get("texture_count")
            sub_label_map = {
                "parsing_xml":        "Parsing scene XML",
                "loading_meshes":     f"Loading meshes ({mesh_n})" if isinstance(mesh_n, int) and mesh_n else "Loading meshes",
                "uploading_textures": f"Uploading textures ({tex_n})" if isinstance(tex_n, int) and tex_n else "Uploading textures",
                "compiling_optix":    "Compiling OptiX shaders (may take minutes)",
                "ready":              "Scene loaded into GPU",
                "cached":             "Scene already in GPU cache",
            }
            base = sub_label_map.get(sub or "", "Loading scene into GPU memory")
            elapsed = ctx.get("elapsed_s") if ctx else None
            elapsed_suffix = f" · {elapsed:.0f}s" if isinstance(elapsed, (int, float)) and not sub else ""
            return f"{base}{elapsed_suffix}{pass_suffix}{spp_suffix}{count_suffix}."
        if stage == "rendering":
            return f"Ray tracing{pass_suffix}{spp_suffix}{count_suffix}."
        if stage == "saving_output":
            return f"Writing EXR output{pass_suffix}{count_suffix}."
        if stage == "writing_manifest":
            return "Writing observation manifest."
        return stage.replace("_", " ").strip().capitalize()

    def _job_priority(self, job: "_QueuedJob") -> int:
        raw = job.render_request.render_settings.get("priority", job.render_request.extras.get("priority", 0))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _enqueue_pending_unlocked(self, job_id: str, job: "_QueuedJob") -> None:
        """Insert into the pending queue with higher numeric priority first."""
        priority = self._job_priority(job)
        job.status.extras["priority"] = priority
        if not self._pending:
            self._pending.append(job_id)
            return
        for index, existing_id in enumerate(self._pending):
            existing = self._jobs.get(existing_id)
            if existing is None:
                continue
            if priority > self._job_priority(existing):
                self._pending.insert(index, job_id)
                return
        self._pending.append(job_id)

    def _max_render_retries(self, job: "_QueuedJob") -> int:
        raw = job.render_request.render_settings.get("max_retries")
        if raw is None:
            raw = os.environ.get("ROBOMITUBA_RENDER_MAX_RETRIES", "1")
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 1

    def _job_texture_profile(self, job: "_QueuedJob") -> int:
        candidates = [
            job.status.extras.get("texture_profile_override"),
            job.status.extras.get("texture_profile"),
        ]
        progress_context = job.status.extras.get("progress_context")
        if isinstance(progress_context, Mapping):
            candidates.append(progress_context.get("texture_profile"))
        candidates.append(os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION"))
        for value in candidates:
            try:
                if value is not None:
                    return max(0, int(str(value).strip() or "0"))
            except (TypeError, ValueError):
                continue
        return 0

    def _is_gpu_scene_prepare_failure(self, job: "_QueuedJob") -> bool:
        if job.status.progress_stage in {"staging_scene", "loading_scene"}:
            return True
        progress_context = job.status.extras.get("progress_context")
        return isinstance(progress_context, Mapping) and bool(progress_context.get("sub_step"))

    def _should_texture_downgrade_retry(self, job: "_QueuedJob", *, reason: str, message: str) -> bool:
        if bool(job.status.extras.get("texture_downgrade_retry")):
            return False
        texture_profile = self._job_texture_profile(job)
        if texture_profile <= 1024:
            return False
        if not self._is_gpu_scene_prepare_failure(job):
            return False
        if reason in {"worker_exited", "worker_pipe_broken", "heartbeat_timeout"}:
            return True
        message_l = message.lower()
        return reason == "render_exception" and any(
            token in message_l
            for token in (
                "cuda_error_out_of_memory",
                "out of memory",
                "cuda_check",
                "could not initialize optix",
                "texture audit failed",
            )
        )

    def _retry_render_job(self, job_id: str, *, reason: str, message: str) -> bool:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status.status == "cancelled":
                return False
            downgrade_texture = self._should_texture_downgrade_retry(job, reason=reason, message=message)
            if reason not in _RETRYABLE_RENDER_FAILURE_REASONS and not downgrade_texture:
                return False
            attempts = int(job.status.extras.get("retry_attempts", 0) or 0)
            max_retries = self._max_render_retries(job)
            if attempts >= max_retries:
                return False
            job.status.status = "queued"
            job.status.started_at = None
            job.status.worker_started_at = None
            job.status.finished_at = None
            job.status.progress_stage = "retry_queued"
            job.status.error = None
            job.status.extras["retry_attempts"] = attempts + 1
            job.status.extras["last_retry_reason"] = reason
            job.status.extras["last_retry_message"] = message
            retry_message = f"Retry {attempts + 1}/{max_retries} after {reason}"
            if downgrade_texture:
                job.status.extras["texture_downgrade_retry"] = True
                job.status.extras["texture_profile_override"] = 1024
                job.status.extras["texture_profile"] = 1024
                retry_message += " · texture_profile=max1024"
            self._enqueue_pending_unlocked(job_id, job)
            self._persist_status_unlocked(job)
            self._condition.notify_all()
        self._record_render_job_telemetry(job, event_type="retry_queued")
        self._append_job_log_line(
            job,
            event_type="retry",
            stage="retry_queued",
            message=retry_message,
        )
        return True

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._shutdown:
                    self._condition.wait()
                if self._shutdown and not self._pending:
                    return
                job_id = self._pending.popleft()
                job = self._jobs.get(job_id)
                if job is None or job.status.status == "cancelled":
                    continue
                job.status.status = "running"
                job.status.started_at = _utc_now_iso()
                job.status.worker_started_at = job.status.started_at if _RENDER_INPROCESS else None
                job.status.progress_stage = "starting"
            # Disk I/O outside the lock.
            # For lazy_persist jobs (bulk sweep), the request file and initial "queued"
            # telemetry were deferred to here so that submit() is near-instant.
            if job.lazy_persist:
                self._persist_request_unlocked(job)
                self._record_render_job_telemetry(job, event_type="queued")
            self._persist_status_unlocked(job)
            self._record_render_job_telemetry(job, event_type="running")
            self._append_job_log_line(job, event_type="running", stage="starting", message="Job started")

            try:
                scene_cache_key = self._scene_cache_key(job.render_request, job.variant)
                with self._condition:
                    cache_stats = self._scene_cache_stats.setdefault(scene_cache_key, {"submissions": 0, "runs": 0})
                    cache_stats["runs"] += 1
                    cache_stats["last_started_at"] = job.status.started_at
                    job.status.extras["scene_cache_runs"] = int(cache_stats["runs"])
                # Disk I/O outside the lock
                self._persist_status_unlocked(job)

                if _RENDER_INPROCESS:
                    # Legacy path: drive the render inline. Daemon thread
                    # blocks here for the full render, picking up the next
                    # job only when this one is done.
                    bundle = self.render_fn(
                        job.render_request,
                        repo_root=self.repo_root,
                        variant=job.variant,
                        progress_callback=lambda stage, payload=None: self._update_progress(job_id, stage, payload),
                    )
                    manifest_path = f"{bundle.bundle_root}/manifest.json"
                    self._mark_succeeded(job_id, manifest_path=manifest_path)
                else:
                    # Phase R-4: hand the render to the worker subprocess.
                    # The dispatcher thread returns immediately and starts
                    # accepting the next job; the worker manager's reader
                    # listener will call _mark_succeeded / _mark_failed
                    # when the worker emits its terminal event.
                    self._submit_render_job_to_worker(job_id, job)
            except Exception as exc:  # pragma: no cover - exercised in tests via failure path
                self._mark_failed(job_id, str(exc))

    def _submit_render_job_to_worker(self, job_id: str, job: "_QueuedJob") -> None:
        """Send a queued render job to the worker subprocess.

        Wraps the RenderRequest payload + envelope and pushes it onto the
        WorkerManager. Failure to serialise / submit is mapped onto a
        synthetic failed event so the job state still finalises.
        """
        try:
            request_payload = render_request_to_payload(job.render_request)
        except Exception as exc:
            self._mark_failed(job_id, f"serialize_failed: {exc}")
            return
        env_overrides: dict[str, str] = {}
        texture_profile_override = job.status.extras.get("texture_profile_override")
        if texture_profile_override is not None:
            env_overrides["ROBOMITUBA_TEXTURE_MAX_RESOLUTION"] = str(texture_profile_override)
        spec: dict[str, Any] = {
            "request_payload": request_payload,
            "repo_root": str(self.repo_root),
            "variant": job.variant,
            "disable_cuda": str(os.environ.get("ROBOMITUBA_FULL_RENDER_DISABLE_CUDA", "0")).strip().lower()
            in {"1", "true", "yes", "on"},
        }
        if env_overrides:
            spec["env_overrides"] = env_overrides
        payload = {
            "job_id": job_id,
            "kind": "render_job",
            "spec": spec,
        }
        worker_gpu_index = job.runtime_overrides.get("worker_gpu_index")
        if worker_gpu_index is not None:
            try:
                payload["worker_gpu_index"] = int(worker_gpu_index)
            except (TypeError, ValueError):
                payload["worker_gpu_index"] = worker_gpu_index
        mgr = self._ensure_render_worker_manager()
        mgr.submit(payload)
        target_gpu = payload.get("worker_gpu_index")
        target_suffix = f" target_gpu={target_gpu}" if target_gpu is not None else ""
        print(
            f"[daemon] render_queue: enqueue (subprocess) job_id={job_id} "
            f"variant={job.variant}{target_suffix}",
            file=sys.stderr, flush=True,
        )

    @staticmethod
    def _opticalnav_modality_output_names(modality: str) -> tuple[str, ...]:
        mapping = {
            "rgb": ("rgb.png", "rgb.exr"),
            "depth": ("depth.png", "depth.exr", "depth_jet_colorbar.png"),
            "albedo": ("albedo.png", "albedo.exr"),
            "active_nir_intensity": ("active_nir_intensity.png", "active_nir_intensity.exr"),
            "hazard_mask": ("hazard_mask.png",),
            "polar_rgb_preview": ("polar_rgb_preview.png",),
            "dop": ("dop_red_black_colorbar.png", "dop.exr"),
            "aolp": ("aolp_rainbow_colorbar.png", "aolp.exr"),
            "s1": ("s1_bwr_colorbar.png", "s1.exr"),
            "s2": ("s2_bwr_colorbar.png", "s2.exr"),
            "s1_over_s0": ("s1_over_s0_bwr_colorbar.png",),
            "s2_over_s0": ("s2_over_s0_bwr_colorbar.png",),
        }
        key = str(modality or "").strip()
        return mapping.get(key, (f"{key}.png", f"{key}.exr"))

    def _opticalnav_copy_observation_files(
        self,
        *,
        project_id: str,
        scene_id: str,
        vp_id: str,
        heading_id: str,
        job_id: str,
        frame_id: str,
        camera_id: str,
    ) -> bool:
        """Copy bridge-job camera outputs into the consolidated OpticalNav tree."""
        try:
            import shutil
            src_dir = (
                self.repo_root / "out" / "bridge_jobs" / job_id / "observations" / frame_id /
                "cameras" / camera_id
            )
            if not src_dir.exists():
                cameras_root = self.repo_root / "out" / "bridge_jobs" / job_id / "observations" / frame_id / "cameras"
                first_camera_dir = next((item for item in sorted(cameras_root.iterdir()) if item.is_dir()), None) if cameras_root.exists() else None
                if first_camera_dir is None:
                    return False
                src_dir = first_camera_dir
                camera_id = first_camera_dir.name
            dst_dir = self.repo_root / "out" / "opticalnav" / project_id / "scenes" / scene_id / "observations" / vp_id / heading_id
            sensor_dst_dir = dst_dir / "sensors" / camera_id
            copy_map = {
                "rgb.png": "rgb.png",
                "depth_jet_colorbar.png": "depth.png",
                "albedo.png": "albedo.png",
                "active_nir_intensity.png": "active_nir_intensity.png",
                "hazard_mask.png": "hazard_mask.png",
                "polar_rgb_preview.png": "polar_rgb_preview.png",
                "dop_red_black_colorbar.png": "dop_red_black_colorbar.png",
                "aolp_rainbow_colorbar.png": "aolp_rainbow_colorbar.png",
                "s1_bwr_colorbar.png": "s1_bwr_colorbar.png",
                "s2_bwr_colorbar.png": "s2_bwr_colorbar.png",
                "s1_over_s0_bwr_colorbar.png": "s1_over_s0_bwr_colorbar.png",
                "s2_over_s0_bwr_colorbar.png": "s2_over_s0_bwr_colorbar.png",
            }
            copied = False
            for src_name, dst_name in copy_map.items():
                src = src_dir / src_name
                if src.exists():
                    if not copied:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        sensor_dst_dir.mkdir(parents=True, exist_ok=True)
                        copied = True
                    shutil.copy2(src, sensor_dst_dir / dst_name)
                    shutil.copy2(src, dst_dir / dst_name)
            try:
                for src in src_dir.iterdir():
                    if not src.is_file() or src.suffix.lower() != ".exr":
                        continue
                    if not copied:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        sensor_dst_dir.mkdir(parents=True, exist_ok=True)
                        copied = True
                    shutil.copy2(src, sensor_dst_dir / src.name)
            except OSError:
                pass
            if copied:
                index_path = dst_dir / "_sensor_index.json"
                try:
                    index = _read_json(index_path) if index_path.exists() else {"sensors": {}}
                except Exception:
                    index = {"sensors": {}}
                sensors = dict(index.get("sensors") or {})
                sensors[camera_id] = {
                    "camera_id": camera_id,
                    "updated_at": _utc_now_iso(),
                    "files": sorted(item.name for item in sensor_dst_dir.iterdir() if item.is_file()),
                }
                index_path.write_text(json.dumps({"sensors": sensors}, ensure_ascii=False, indent=2), encoding="utf-8")
            return copied
        except Exception:
            return False

    def _opticalnav_sweep_output_exists(self, project_dir: Path, scene_id: str, sweep_request: Any, modalities: Sequence[str]) -> bool:
        request = sweep_request.request
        camera_specs = list(getattr(request, "camera_specs", []) or [])
        camera_id = str(getattr(camera_specs[0], "camera_id", "") or "opticalnav_front_cam") if camera_specs else "opticalnav_front_cam"
        vp_id = str(sweep_request.node_id)
        heading_id = str(sweep_request.heading_id)
        dst_dir = project_dir / "scenes" / scene_id / "observations" / vp_id / heading_id
        sensor_dst_dir = dst_dir / "sensors" / camera_id

        def _has_consolidated() -> bool:
            for modality in modalities:
                names = self._opticalnav_modality_output_names(str(modality))
                if not any((sensor_dst_dir / name).exists() or (dst_dir / name).exists() for name in names):
                    return False
            return True

        if _has_consolidated():
            return True

        manifest_path = self.repo_root / "out" / "bridge_jobs" / request.job_id / "observations" / request.frame_id / "manifest.json"
        if manifest_path.exists():
            self._opticalnav_copy_observation_files(
                project_id=project_dir.name,
                scene_id=scene_id,
                vp_id=vp_id,
                heading_id=heading_id,
                job_id=request.job_id,
                frame_id=request.frame_id,
                camera_id=camera_id,
            )
            return True
        return False

    def _opticalnav_copy_observation_rgb(self, job: "_QueuedJob") -> None:
        """Copy modality preview PNGs (rgb/depth/etc.) to the consolidated observations dir."""
        try:
            import shutil
            ex = job.render_request.extras
            proj_id = ex.get("opticalnav_project_id")
            sc_id = ex.get("opticalnav_scene_id")
            vp_id = ex.get("opticalnav_vp_id")
            h_id = ex.get("opticalnav_heading_id")
            if not (proj_id and sc_id and vp_id and h_id):
                return
            frame_id = job.render_request.frame_id
            camera_specs = list(getattr(job.render_request, "camera_specs", []) or [])
            camera_id = str(getattr(camera_specs[0], "camera_id", "") or "opticalnav_front_cam") if camera_specs else "opticalnav_front_cam"
            if self._opticalnav_copy_observation_files(
                project_id=str(proj_id), scene_id=str(sc_id), vp_id=str(vp_id), heading_id=str(h_id),
                job_id=job.render_request.job_id, frame_id=frame_id, camera_id=camera_id,
            ):
                return
            src_dir = (
                self.repo_root / "out" / "bridge_jobs" /
                job.render_request.job_id / "observations" / frame_id /
                "cameras" / camera_id
            )
            if not src_dir.exists():
                cameras_root = self.repo_root / "out" / "bridge_jobs" / job.render_request.job_id / "observations" / frame_id / "cameras"
                first_camera_dir = next((item for item in sorted(cameras_root.iterdir()) if item.is_dir()), None) if cameras_root.exists() else None
                if first_camera_dir is None:
                    return
                src_dir = first_camera_dir
                camera_id = first_camera_dir.name
            dst_dir = (
                self.repo_root / "out" / "opticalnav" / proj_id /
                "scenes" / sc_id / "observations" / vp_id / h_id
            )
            sensor_dst_dir = dst_dir / "sensors" / camera_id
            # bridge-job filename → consolidated UI-facing filename
            copy_map = {
                "rgb.png": "rgb.png",
                "depth_jet_colorbar.png": "depth.png",
                "albedo.png": "albedo.png",
                "active_nir_intensity.png": "active_nir_intensity.png",
                "hazard_mask.png": "hazard_mask.png",
                "polar_rgb_preview.png": "polar_rgb_preview.png",
                "dop_red_black_colorbar.png": "dop_red_black_colorbar.png",
                "aolp_rainbow_colorbar.png": "aolp_rainbow_colorbar.png",
                "s1_bwr_colorbar.png": "s1_bwr_colorbar.png",
                "s2_bwr_colorbar.png": "s2_bwr_colorbar.png",
                "s1_over_s0_bwr_colorbar.png": "s1_over_s0_bwr_colorbar.png",
                "s2_over_s0_bwr_colorbar.png": "s2_over_s0_bwr_colorbar.png",
            }
            copied = False
            for src_name, dst_name in copy_map.items():
                src = src_dir / src_name
                if src.exists():
                    if not copied:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        sensor_dst_dir.mkdir(parents=True, exist_ok=True)
                        copied = True
                    shutil.copy2(src, sensor_dst_dir / dst_name)
                    # Legacy compatibility: keep the modality-level file too.
                    # With multiple same-modality sensors this is only a fallback; the
                    # UI now queries sensors/{camera_id}/... for precise matching.
                    shutil.copy2(src, dst_dir / dst_name)
            # Also propagate every HDR `.exr` modality next to the PNG previews.
            # The export bundle and downstream VLN evaluators consume EXR (rgb,
            # depth, normal, polarization stokes, ...) — the PNG-only copy_map
            # above used to leave EXR stranded under `out/bridge_jobs/...`,
            # so consolidated `observations/<vp>/<heading>/sensors/<cam>/` was
            # missing all HDR data.
            try:
                for src in src_dir.iterdir():
                    if not src.is_file() or src.suffix.lower() != ".exr":
                        continue
                    if not copied:
                        dst_dir.mkdir(parents=True, exist_ok=True)
                        sensor_dst_dir.mkdir(parents=True, exist_ok=True)
                        copied = True
                    shutil.copy2(src, sensor_dst_dir / src.name)
            except OSError:
                pass
            if copied:
                index_path = dst_dir / "_sensor_index.json"
                try:
                    index = _read_json(index_path) if index_path.exists() else {"sensors": {}}
                except Exception:
                    index = {"sensors": {}}
                sensors = dict(index.get("sensors") or {})
                sensors[camera_id] = {
                    "camera_id": camera_id,
                    "updated_at": _utc_now_iso(),
                    "files": sorted(item.name for item in sensor_dst_dir.iterdir() if item.is_file()),
                }
                index_path.write_text(json.dumps({"sensors": sensors}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _mark_succeeded(self, job_id: str, *, manifest_path: str, event_ts: Any = None) -> None:
        with self._condition:
            job = self._jobs[job_id]
            if job.status.status == "cancelled":
                return
            job.status.status = "succeeded"
            job.status.finished_at = _event_ts_iso(event_ts) or _utc_now_iso()
            job.status.progress_stage = "complete"
            job.status.manifest_path = manifest_path
            job.status.error = None
            # New observation bundles written — invalidate the bundle manifest cache
            self._bundle_manifest_cache = None
            self._bundle_manifest_cache_ts = 0.0
        self._update_job_render_timing_summary(job, manifest_path=manifest_path)
        # Disk I/O outside the lock
        self._persist_status_unlocked(job)
        self._opticalnav_copy_observation_rgb(job)
        with self._condition:
            self._condition.notify_all()
        self._record_render_job_telemetry(job, event_type="complete")
        self._append_job_log_line(job, event_type="complete", stage="complete", message="Job succeeded", event_ts=event_ts)

    def _mark_failed(self, job_id: str, error: str, *, event_ts: Any = None) -> None:
        with self._condition:
            job = self._jobs[job_id]
            if job.status.status == "cancelled":
                return
            job.status.status = "failed"
            job.status.finished_at = _event_ts_iso(event_ts) or _utc_now_iso()
            job.status.progress_stage = "failed"
            job.status.error = error
            self._condition.notify_all()
        # Disk I/O outside the lock
        self._persist_status_unlocked(job)
        self._record_render_job_telemetry(job, event_type="failed")
        self._append_job_log_line(job, event_type="failed", stage="failed", message=error or "Job failed", event_ts=event_ts)

    def _update_progress(self, job_id: str, stage: str, payload: Mapping[str, Any] | None, *, event_ts: Any = None) -> None:
        command_id = None
        progress_counts = None
        message = self._isaac_render_stage_message(stage, payload)
        job_for_persist = None
        should_persist = False
        now_s = time.monotonic()
        interval_s = _render_progress_persist_interval_s()
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status.status != "running":
                return
            job.status.progress_stage = stage
            if payload:
                job.status.extras["progress_context"] = dict(payload)
                if payload.get("total_passes"):
                    progress_counts = {
                        "loaded": int(payload.get("pass_index", 0) or 0),
                        "total": int(payload.get("total_passes", 0) or 0),
                    }
                if "texture_profile" in payload:
                    job.status.extras["texture_profile"] = payload.get("texture_profile")
                if isinstance(payload.get("texture_audit"), dict):
                    job.status.extras["texture_audit"] = dict(payload.get("texture_audit") or {})
                if stage == "loading_scene" and payload.get("cached"):
                    job.status.extras["scene_cache_hit"] = True
            command_id = _maybe_str(job.status.extras.get("isaac_command_id"))
            should_persist = interval_s == 0.0 or job.last_progress_persist_s == 0.0 or (now_s - job.last_progress_persist_s) >= interval_s
            if should_persist:
                job.last_progress_persist_s = now_s
                job_for_persist = job
            self._condition.notify_all()
        # Progress events are high-frequency and arrive on the worker stdout
        # reader thread. Keep most of them in memory only; terminal events still
        # persist immediately. This prevents status/log/telemetry I/O from
        # delaying completed events behind stale progress events.
        if job_for_persist is not None:
            self._persist_status_unlocked(job_for_persist)
            self._append_job_log_line(job_for_persist, event_type="progress", stage=stage, message=message, event_ts=event_ts)
        if command_id and should_persist:
            try:
                self._update_isaac_command_progress(
                    command_id,
                    {
                        "status": "running",
                        "progress_stage": stage,
                        "progress_message": message,
                        "progress_origin": "daemon_render",
                        **({"progress_counts": progress_counts} if progress_counts else {}),
                    },
                )
            except Exception:
                pass

    def _scene_cache_key(self, render_request: RenderRequest, variant: str) -> str:
        branch_policy = str(render_request.extras.get("branch_policy", "default"))
        return f"{render_request.scene_state.mitsuba_scene_ref}|{branch_policy}|{variant}"

    def _status_path(self, job_id: str) -> Path:
        return self.repo_root / "out" / "bridge_jobs" / job_id / "job_status.json"

    def _job_log_path(self, job_id: str) -> Path:
        return self.repo_root / "out" / "bridge_jobs" / job_id / "render_progress.log"

    def _append_job_log_line(self, job: "_QueuedJob", *, event_type: str, stage: str, message: str, event_ts: Any = None) -> None:
        try:
            log_path = self._job_log_path(job.render_request.job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = _event_ts_iso(event_ts) or _utc_now_iso()
            line = f"[{ts}] [{event_type.upper():<8}] {stage:<25} {message}\n"
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass

    def _request_path(self, job: _QueuedJob) -> Path:
        return self.repo_root / "out" / "bridge_jobs" / job.render_request.job_id / "requests" / f"{job.render_request.frame_id}.json"

    def _persist_request_unlocked(self, job: _QueuedJob) -> None:
        request_path = self._request_path(job)
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps(job.request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_status_unlocked(self, job: _QueuedJob) -> None:
        status_path = self._status_path(job.render_request.job_id)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        write_render_job_status(status_path, job.status)
        # Invalidate cached file scan so next request sees the updated status
        self._invalidate_job_status_cache()

    def _proxy_to_render_queue(self, handler: BaseHTTPRequestHandler, method: str, body: bytes | None = None) -> bool:
        """Forward render/preview/job requests from backend-only mode to the GPU queue daemon."""
        if not _backend_only_mode():
            return False
        parsed = urlparse(handler.path)
        if not _is_render_queue_proxy_path(method, parsed.path):
            return False
        queue_url = _render_queue_url()
        if not queue_url:
            self._send_json(handler, HTTPStatus.BAD_GATEWAY, {"error": "render_queue_url_missing"})
            return True
        target = f"{queue_url}{handler.path}"
        headers: dict[str, str] = {}
        content_type = handler.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type
        accept = handler.headers.get("Accept")
        if accept:
            headers["Accept"] = accept
        if body is None and method.upper() in {"POST", "PUT", "PATCH"}:
            length = int(handler.headers.get("Content-Length", "0") or "0")
            body = handler.rfile.read(length) if length > 0 else b""
        data = body if method.upper() in {"POST", "PUT", "PATCH"} else None
        timeout_s = float(os.environ.get("ROBOMITUBA_RENDER_QUEUE_PROXY_TIMEOUT_S", "600") or "600")
        req = urllib.request.Request(target, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = resp.read()
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                extra_headers = {
                    "X-Robomituba-Proxied-To": queue_url,
                    "Cache-Control": resp.headers.get("Cache-Control", "no-store"),
                }
                self._send_bytes(handler, int(resp.status), payload, content_type=content_type, extra_headers=extra_headers)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json; charset=utf-8") if exc.headers else "application/json; charset=utf-8"
            self._send_bytes(
                handler,
                int(exc.code),
                payload,
                content_type=content_type,
                extra_headers={"X-Robomituba-Proxied-To": queue_url},
            )
        except Exception as exc:
            self._send_json(
                handler,
                HTTPStatus.BAD_GATEWAY,
                {
                    "error": "render_queue_proxy_failed",
                    "render_queue_url": queue_url,
                    "detail": str(exc),
                },
            )
        return True

    def _read_request_body(self, handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        length = int(handler.headers.get("Content-Length", "0") or "0")
        body = handler.rfile.read(length) if length > 0 else b""
        if not body:
            return {}
        content_type = handler.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type == "application/json":
            return json.loads(body.decode("utf-8"))
        if content_type == "application/x-www-form-urlencoded":
            parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            return {key: values[-1] if values else "" for key, values in parsed.items()}
        raise ValueError(f"Unsupported Content-Type: {content_type or 'unknown'}")

    def _send_json(
        self,
        handler: BaseHTTPRequestHandler,
        status_code: int,
        payload: Mapping[str, Any],
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        if status_code >= 400 and os.environ.get("ROBOMITUBA_DAEMON_DEBUG_LOG") in {"1", "true", "yes", "on"}:
            compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            print(f"[http] {handler.command} {handler.path} -> {status_code} {compact}", file=sys.stderr, flush=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(
            handler,
            status_code,
            encoded,
            content_type="application/json; charset=utf-8",
            extra_headers=extra_headers,
        )

    def _send_html(self, handler: BaseHTTPRequestHandler, status_code: int, html: str) -> None:
        encoded = html.encode("utf-8")
        self._send_bytes(handler, status_code, encoded, content_type="text/html; charset=utf-8")

    def _send_bytes(
        self,
        handler: BaseHTTPRequestHandler,
        status_code: int,
        payload: bytes,
        *,
        content_type: str,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        try:
            handler.send_response(status_code)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(payload)))
            if extra_headers:
                for key, value in extra_headers.items():
                    handler.send_header(key, value)
            handler.send_header("Connection", "close")
            handler.end_headers()
            try:
                handler.wfile.flush()
            except OSError:
                pass
            handler.connection.sendall(payload)
            try:
                import socket as _socket
                handler.connection.shutdown(_socket.SHUT_WR)
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError):
            raise _ClientDisconnectedError from None

    # ── Dataset auto-download ────────────────────────────────────────────────

    def _handle_dataset_download_post(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        dataset_id = payload.get("dataset_id", "")
        if not dataset_id:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "dataset_id required"})
            return
        force = bool(payload.get("force", False))
        only = payload.get("material_ids")
        only_set: set[str] | None = set(only) if isinstance(only, list) else None
        from .material_library import get_library_grouped
        groups = get_library_grouped(self.repo_root)
        group = next((g for g in groups if g["dataset_id"] == dataset_id), None)
        if not group:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "dataset not found"})
            return
        pending = [
            (m["material_id"], m["display_name"], m["native_file"], m["download_url"])
            for m in group["materials"]
            if m.get("download_url")
            and (force or m["status"] == "not_downloaded")
            and (only_set is None or m["material_id"] in only_set)
        ]
        if not pending:
            self._send_json(handler, HTTPStatus.OK, {"status": "nothing_to_download", "job_id": None})
            return
        # Resolve dataset's local_root once so the worker thread can apply the
        # user's storage override (~/.robomituba/settings.json) per file.
        from .material_library import load_dataset_config, _dataset_config_by_id
        cfg_by_id = _dataset_config_by_id(load_dataset_config(self.repo_root))
        dataset_local_root = (cfg_by_id.get(dataset_id) or {}).get("local_root")
        job_id = f"dl-{_utc_now_iso().replace(':', '').replace('-', '').replace('.', '')}"
        job: dict[str, Any] = {
            "done": 0, "total": len(pending), "current_name": "",
            "status": "running", "errors": [],
        }
        with _download_jobs_lock:
            _download_jobs[job_id] = job
        threading.Thread(
            target=self._run_download_job,
            args=(job_id, pending, dataset_id, dataset_local_root),
            daemon=True,
        ).start()
        self._send_json(handler, HTTPStatus.OK, {"job_id": job_id})

    # ── Preview cache invalidation ───────────────────────────────────────────

    def _preview_cache_dir(self) -> Path:
        return self.repo_root / "out" / "material_previews"

    def _handle_invalidate_curated(self, handler: BaseHTTPRequestHandler, material_id: str) -> None:
        from .curated_library import get_curated_material

        mat = get_curated_material(material_id)
        if mat is None:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown curated material: {material_id}"})
            return
        removed = self._invalidate_curated_files(material_id)
        # Create a server-side job so the materials page bottom panel can show
        # progress + history that survives browser refresh, then kick off the
        # actual render in the background. This way the user doesn't have to
        # wait for the browser to issue the follow-up GET to drive the render.
        job = self._enqueue_curated_render(mat, material_id)
        self._send_json(handler, HTTPStatus.OK, {
            "ok": True,
            "material_id": material_id,
            "removed": removed,
            "job": job,
        })

    def _enqueue_curated_render(
        self, mat: Any, material_id: str, *, object_id: str = "sphere",
    ) -> dict[str, Any] | None:
        """Spawn the curated-preview Mitsuba render in a BG thread and create
        a tracked job entry. Returns the job dict (or None if a render for
        this material+object was already in flight)."""
        from .sphere_preview import (
            _build_scene_dict,
            _ensure_mitsuba_variant,
            _mitsuba_render_lock,
            _pick_variant_for,
            _render_to_png,
            _supersample_default,
            resolve_preview_object,
        )

        object_id = resolve_preview_object(object_id)
        cache_dir = self._preview_cache_dir()
        out = cache_dir / "curated" / f"{material_id}_{object_id}.png"
        key = f"curated:{material_id}:{object_id}"

        if not _claim_preview_inflight(key):
            return None  # render already in flight; an existing job covers it

        job = _create_material_job(
            key=f"curated/{material_id}/{object_id}",
            title="프리뷰 재렌더",
            subtitle=f"{getattr(mat, 'display_name', material_id)} · {object_id}",
            action="rerender",
        )
        job_id = job["id"]

        # Resolve the Mitsuba variant up-front only on the in-process
        # path — the closure below captures it. In subprocess mode we
        # deliberately skip this so the daemon process never has to
        # import mitsuba; the worker does its own ``_pick_variant_for``
        # and emits a ``plugin_unavailable`` failed event if no GPU
        # variant is available, which the listener maps onto the same
        # "Mitsuba variant unavailable" status.
        variant: str | None = None
        if _RENDER_INPROCESS:
            variant = _pick_variant_for("rgb")
            if variant is None:
                _release_preview_inflight(key)
                _finish_material_job(job_id, "failed", "Mitsuba variant unavailable")
                return job

        bsdf_spec = mat.bsdf_spec

        def _render_curated() -> None:
            try:
                # Variant + scene dict build + render must all happen under
                # the global Mitsuba lock — `_build_scene_dict` constructs
                # `mi.ScalarTransform4f` inline, which fails if the variant
                # isn't set in this process yet.
                from .user_settings import get_material_preview_spp
                # Phase A-2: curated default 2048 → 768. The sphere-only rig
                # at 192² × 2× supersample (effective 8192 samples/pixel @ 2048)
                # was massively oversampled for diffuse / roughplastic / conductor;
                # 768 stays visually clean for all 9 curated plugin types and
                # cuts the path-tracing share of wall-clock by ~3×.
                # User overrides via `material_preview_spp` setting still win.
                spp = get_material_preview_spp(default=768)
                ss = _supersample_default()
                target_size = 192
                render_size = target_size * ss
                with _mitsuba_render_lock:
                    _ensure_mitsuba_variant(variant)
                    _update_material_job_stage(
                        job_id, "scene_build",
                        f"씬 dict 빌드 중 (spp={spp}, render={render_size}px, object={object_id})",
                    )
                    scene_dict = _build_scene_dict(
                        bsdf_spec, size=render_size, spp=spp, object_id=object_id,
                    )

                    def _progress(current: int, total: int) -> None:
                        pct = int(round(current / max(total, 1) * 100))
                        _update_material_job_stage(
                            job_id,
                            "rendering",
                            f"Mitsuba 렌더 중 ({material_id}/{object_id}) {current}/{total} · {pct}% · spp={spp}",
                        )
                        _update_material_job_progress(job_id, current, total)

                    _update_material_job_stage(
                        job_id, "rendering",
                        f"Mitsuba 렌더 중 ({material_id}/{object_id}) 0/0 · spp={spp}",
                    )
                    _render_to_png(
                        scene_dict, out, variant=variant, spp=spp,
                        progress_cb=_progress,
                        supersample=ss, target_size=target_size,
                        bench_label=f"curated/{material_id}/{object_id}",
                    )
                _update_material_job_stage(job_id, "saved", "PNG 저장 완료")
                _finish_material_job(job_id, "success")
            except Exception as exc:
                _finish_material_job(job_id, "failed", str(exc))
                raise

        if _RENDER_INPROCESS:
            _spawn_preview_render(key, _render_curated)
        else:
            from .user_settings import get_material_preview_spp
            spp = get_material_preview_spp(default=768)
            ss = _supersample_default()
            target_size = 192
            payload = {
                "kind": "curated_preview",
                "spec": {
                    "material_id": material_id,
                    "object_id": object_id,
                    "out_path": str(out),
                    "spp": int(spp),
                    "target_size": int(target_size),
                    "supersample": int(ss),
                    "bench_label": f"curated/{material_id}/{object_id}",
                },
            }
            _spawn_preview_render_subprocess(
                self, key, payload, material_job_id=job_id,
            )
        return job

    def _invalidate_curated_files(self, material_id: str) -> list[str]:
        """Delete the baked + cache PNG (and sidecar) for one curated id.

        The next GET on the preview URL will re-render on-demand; the next bake
        will write a fresh sidecar with a current rig_hash.
        """
        from .curated_library import curated_preview_path

        removed: list[str] = []
        baked = curated_preview_path(self.repo_root, material_id)
        for p in (baked, baked.with_suffix(".meta.json")):
            if p.exists():
                try:
                    p.unlink()
                    removed.append(str(p.relative_to(self.repo_root)))
                except OSError:
                    pass
        cached = self._preview_cache_dir() / "curated" / f"{material_id}.png"
        if cached.exists():
            try:
                cached.unlink()
                removed.append(str(cached.relative_to(self.repo_root)))
            except OSError:
                pass
        return removed

    def _handle_invalidate_measured(
        self,
        handler: BaseHTTPRequestHandler,
        dataset_id: str,
        material_id: str,
    ) -> None:
        removed = self._invalidate_measured_files(dataset_id, material_id)
        # Look up the file path for this material (so we can drive the BG
        # render without needing the client to GET the preview URL).
        from .material_library import get_library_grouped
        groups = get_library_grouped(self.repo_root)
        group = next((g for g in groups if g["dataset_id"] == dataset_id), None)
        mat_entry = next((m for m in (group["materials"] if group else []) if m["material_id"] == material_id), None)
        file_path = mat_entry.get("native_file") if mat_entry else None
        display_name = mat_entry.get("display_name", material_id) if mat_entry else material_id
        job = self._enqueue_measured_render(dataset_id, material_id, file_path, display_name)
        self._send_json(handler, HTTPStatus.OK, {
            "ok": True,
            "dataset_id": dataset_id,
            "material_id": material_id,
            "removed": removed,
            "job": job,
        })

    def _enqueue_measured_render(
        self,
        dataset_id: str,
        material_id: str,
        measured_file_path: str | None,
        display_name: str,
        *,
        object_id: str = "sphere",
    ) -> dict[str, Any] | None:
        """Spawn the measured-preview render in a BG thread + register a job.

        The BG task acquires `_mitsuba_render_lock` itself so the job's
        `stage` accurately reflects whether it's "queued" (waiting for the
        lock) vs "rendering" (actually inside `mi.render`). Calling
        `get_measured_preview` directly would set stage to "rendering"
        immediately even when the task is sitting behind N other renders
        in the lock queue, which is what made the panel look like all jobs
        were rendering at once when in fact only one was active.
        """
        from .sphere_preview import get_measured_preview, resolve_preview_object

        object_id = resolve_preview_object(object_id)
        key = f"measured:{dataset_id}:{material_id}:{object_id}"
        if not _claim_preview_inflight(key):
            # Already rendering — surface the existing material_job so the UI
            # has something to show instead of a silent 200 with no row.
            existing_key = f"{dataset_id}/{material_id}/{object_id}"
            with _material_jobs_lock:
                for j in _material_jobs:
                    if j.get("key") == existing_key and j.get("status") == "running":
                        return dict(j)
            return None
        job = _create_material_job(
            key=f"{dataset_id}/{material_id}/{object_id}",
            title="프리뷰 재렌더",
            subtitle=f"{display_name} · {object_id}",
            action="rerender",
        )
        job_id = job["id"]

        if not measured_file_path:
            _release_preview_inflight(key)
            _finish_material_job(job_id, "failed", "measured_file_path missing")
            return job

        from .sphere_preview import _mitsuba_render_lock
        from .material_library import hpbrdf_channels_dir

        repo_root = self.repo_root
        cache_dir = self._preview_cache_dir()
        # If a channel-split mirror exists for this hpBRDF material,
        # take that path INSTEAD of loading the 13 GB monolithic file —
        # the latter is what's been crashing the daemon with CUDA OOM
        # on shared-GPU boxes. channel-split keeps each render under
        # ~200 MB by loading one .pbrdf wavelength at a time.
        channels_dir: Path | None = None
        if dataset_id == "hpbrdf_2025":
            channels_dir = hpbrdf_channels_dir(repo_root, material_id)

        def _render_measured() -> None:
            try:
                # Acquire the Mitsuba lock OURSELVES (it's reentrant — see
                # sphere_preview._mitsuba_render_lock) so the stage stays
                # "queued"/"큐 대기 중" while waiting and only flips to
                # "rendering" once we're actually about to enter mi.render.
                # `get_measured_preview` re-acquires the same RLock internally
                # — that's a no-op since we already hold it on this thread.
                from .user_settings import get_material_preview_spp
                spp = get_material_preview_spp(default=384)
                if channels_dir is not None:
                    # Channel-split path — render N=4 RGB+NIR sequentially.
                    # No outer lock here: each per-wavelength render takes
                    # the lock itself inside `_render_single_channel_to_array`.
                    from .sphere_preview import (
                        get_channel_split_preview, RGBNIR_DEFAULT,
                    )
                    n_channels = len(RGBNIR_DEFAULT)
                    _update_material_job_stage(
                        job_id, "rendering",
                        f"Mitsuba 채널-split 렌더 중 ({material_id}) "
                        f"0/{n_channels} RGB+NIR · spp={spp}",
                    )
                    def _on_channel(done: int, total: int) -> None:
                        _update_material_job_stage(
                            job_id, "rendering",
                            f"Mitsuba 채널-split 렌더 중 ({material_id}) "
                            f"{done}/{total} RGB+NIR · spp={spp}",
                        )
                        _update_material_job_progress(job_id, done, total)
                    result = get_channel_split_preview(
                        material_id, channels_dir, cache_dir,
                        mode="rgbnir", spp=spp,
                        progress_cb=_on_channel,
                        object_id=object_id,
                    )
                else:
                    with _mitsuba_render_lock:
                        _update_material_job_stage(
                            job_id, "rendering",
                            f"Mitsuba 렌더 중 ({material_id}/{object_id}) · spp={spp}",
                        )
                        result = get_measured_preview(
                            dataset_id, material_id, measured_file_path, repo_root, cache_dir,
                            spp=spp, object_id=object_id,
                        )
                if result.path is None:
                    status_msg = {
                        "plugin_unavailable": (
                            "GPU(CUDA) 변종이 빌드되지 않았거나, 이 재질이 패치된 "
                            "Mitsuba 빌드를 요구합니다 (hpBRDF 등)"
                        ),
                        "mitsuba_unavailable": "Mitsuba 임포트 실패",
                        "load_error": "파일 파싱 실패 (포맷 불일치)",
                        "optix_unavailable": (
                            "OptiX 초기화 실패 — 호스트 NVIDIA 드라이버가 OptiX 8 요구사항(R535+)보다 낮습니다. "
                            "ROBOMITUBA_DISABLE_CUDA=1 로 CPU variant를 사용하세요."
                        ),
                        "gpu_oom": (
                            "GPU/host-pinned 메모리 부족 — hpBRDF는 파일당 13 GB라 "
                            "다른 큰 작업 종료 후 재시도하세요"
                        ),
                        "not_downloaded": "원본 파일 없음 — 먼저 다운로드 필요",
                        "placeholder": "원본 파일 없음 — placeholder 사용",
                    }.get(result.status, f"render unavailable: {result.status}")
                    _finish_material_job(job_id, "failed", status_msg)
                else:
                    _update_material_job_stage(job_id, "saved", "PNG 저장 완료")
                    _finish_material_job(job_id, "success")
            except Exception as exc:
                _finish_material_job(job_id, "failed", str(exc))
                raise

        if _RENDER_INPROCESS:
            _spawn_preview_render(key, _render_measured)
        else:
            from .user_settings import get_material_preview_spp
            spp = get_material_preview_spp(default=384)
            if channels_dir is not None:
                payload = {
                    "kind": "channel_split_preview",
                    "spec": {
                        "dataset_id": dataset_id,
                        "material_id": material_id,
                        "object_id": object_id,
                        "use_channel_split": True,
                        "channels_dir": str(channels_dir),
                        "cache_dir": str(cache_dir),
                        "repo_root": str(repo_root),
                        "spp": int(spp),
                        "bench_label": f"channel/{material_id}",
                    },
                }
            else:
                payload = {
                    "kind": "measured_preview",
                    "spec": {
                        "dataset_id": dataset_id,
                        "material_id": material_id,
                        "measured_file_path": measured_file_path,
                        "object_id": object_id,
                        "use_channel_split": False,
                        "cache_dir": str(cache_dir),
                        "repo_root": str(repo_root),
                        "spp": int(spp),
                        "bench_label": f"measured/{dataset_id}/{material_id}/{object_id}",
                    },
                }
            _spawn_preview_render_subprocess(
                self, key, payload, material_job_id=job_id,
            )
        return job

    def _invalidate_measured_files(self, dataset_id: str, material_id: str) -> list[str]:
        """Best-effort delete of measured cache PNGs.

        Cache filenames follow ``{safe_id}_{size}.png`` where safe_id is a
        sanitized form of dataset_id+material_id; we glob anything with the
        material_id substring to catch all sizes / variants.
        """
        cache_root = self._preview_cache_dir()
        removed: list[str] = []
        measured_dir = cache_root / "measured"
        if measured_dir.exists():
            # Match "{anything containing dataset_id and material_id}*.png"
            for p in measured_dir.glob("*.png"):
                stem = p.stem
                if dataset_id in stem and material_id in stem:
                    try:
                        p.unlink()
                        removed.append(str(p.relative_to(self.repo_root)))
                    except OSError:
                        pass
        # Channel-split cache lives separately and is keyed only on
        # material_id (no dataset prefix). Glob for it too so re-render
        # actually drops the stale PNG instead of serving the cached one.
        cs_dir = cache_root / "channel_split"
        if cs_dir.exists():
            for p in cs_dir.glob(f"{material_id}__*.png"):
                try:
                    p.unlink()
                    removed.append(str(p.relative_to(self.repo_root)))
                except OSError:
                    pass
            # Phase 9 added a per-material directory layout containing the
            # composite + per-band PNGs + manifest.json. The flat-glob
            # above only catches the legacy file; we also need to wipe the
            # whole directory so the next render starts from a clean slate
            # (otherwise stale band PNGs persist after re-render).
            per_mat_dir = cs_dir / material_id.replace("/", "_").replace(".", "_")
            if per_mat_dir.exists() and per_mat_dir.is_dir():
                import shutil as _shutil
                try:
                    _shutil.rmtree(per_mat_dir)
                    removed.append(str(per_mat_dir.relative_to(self.repo_root)) + "/")
                except OSError:
                    pass
        return removed

    def _handle_batch_invalidate(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        items = payload.get("items")
        if not isinstance(items, list):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "items[] required"})
            return
        # Look up library once so we can resolve display names + measured file
        # paths for the per-item job entries.
        from .curated_library import get_curated_material
        from .material_library import get_library_grouped
        groups = get_library_grouped(self.repo_root)
        measured_index: dict[tuple[str, str], dict[str, Any]] = {}
        for g in groups:
            for m in g["materials"]:
                measured_index[(g["dataset_id"], m["material_id"])] = m

        processed = 0
        all_removed: list[str] = []
        errors: list[dict[str, str]] = []
        spawned_jobs: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                errors.append({"item": str(item), "error": "not an object"})
                continue
            kind = item.get("type")
            try:
                if kind == "curated":
                    mid = item.get("material_id", "")
                    if not mid:
                        errors.append({"item": str(item), "error": "material_id required"})
                        continue
                    all_removed.extend(self._invalidate_curated_files(mid))
                    processed += 1
                    cmat = get_curated_material(mid)
                    if cmat is not None:
                        job = self._enqueue_curated_render(cmat, mid)
                        if job is not None:
                            spawned_jobs.append(job)
                elif kind == "measured":
                    ds = item.get("dataset_id", "")
                    mid = item.get("material_id", "")
                    if not ds or not mid:
                        errors.append({"item": str(item), "error": "dataset_id + material_id required"})
                        continue
                    all_removed.extend(self._invalidate_measured_files(ds, mid))
                    processed += 1
                    mentry = measured_index.get((ds, mid))
                    if mentry is not None:
                        job = self._enqueue_measured_render(
                            ds, mid, mentry.get("native_file"), mentry.get("display_name", mid)
                        )
                        if job is not None:
                            spawned_jobs.append(job)
                else:
                    errors.append({"item": str(item), "error": f"unknown type: {kind}"})
            except Exception as exc:
                errors.append({"item": str(item), "error": str(exc)})
        self._send_json(handler, HTTPStatus.OK, {
            "processed": processed,
            "removed": all_removed,
            "errors": errors,
            "jobs": spawned_jobs,
        })

    def _run_download_job(
        self,
        job_id: str,
        pending: list[tuple[str, str, str, str]],
        dataset_id: str = "",
        dataset_local_root: str | None = None,
    ) -> None:
        from .user_settings import resolve_dataset_path
        job = _download_jobs[job_id]
        # Register in the materials-page job table too, so download progress
        # shows up alongside preview-render jobs.
        mat_job = _create_material_job(
            key=f"download:{dataset_id or 'dataset'}:{job_id}",
            title="데이터셋 다운로드",
            subtitle=f"{dataset_id or 'dataset'} ({len(pending)}개 파일)",
            action="redownload",
        )
        mat_job_id = mat_job["id"]
        _update_material_job_stage(mat_job_id, "downloading", "큐 대기 중")
        for mat_id, mat_name, native_file, url in pending:
            job["current_name"] = mat_name
            job["current_done_bytes"] = 0
            job["current_total_bytes"] = 0
            job["current_speed_bps"] = 0.0
            dest = resolve_dataset_path(self.repo_root, dataset_id, native_file, dataset_local_root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Per-file rolling sample window for instantaneous speed (~3s).
            samples: list[tuple[float, int]] = []
            speed_window_s = 3.0

            def _on_progress(done: int, total: int, _name: str = mat_name) -> None:
                now = time.time()
                samples.append((now, int(done)))
                cutoff = now - speed_window_s
                while len(samples) > 2 and samples[0][0] < cutoff:
                    samples.pop(0)
                speed_bps = 0.0
                if len(samples) >= 2:
                    dt = samples[-1][0] - samples[0][0]
                    db = samples[-1][1] - samples[0][1]
                    if dt > 0 and db > 0:
                        speed_bps = db / dt
                job["current_done_bytes"] = int(done)
                job["current_total_bytes"] = int(total)
                job["current_speed_bps"] = float(speed_bps)
                speed_str = f" · {_human_bytes(speed_bps)}/s" if speed_bps > 0 else ""
                if total > 0:
                    pct = int(done * 100 / total)
                    msg = f"{_name} · {_human_bytes(done)} / {_human_bytes(total)} ({pct}%){speed_str}"
                else:
                    msg = f"{_name} · {_human_bytes(done)}{speed_str}"
                _update_material_job_stage(mat_job_id, "downloading", msg)
                _set_material_job_bytes(mat_job_id, int(done), int(total), speed_bps=speed_bps)

            try:
                if url.startswith("hf-dataset://"):
                    repo_id, filename = _parse_hf_dataset_url(url)
                    _download_hf_dataset_file(repo_id, filename, dest, progress_cb=_on_progress)
                else:
                    _update_material_job_stage(
                        mat_job_id, "downloading", f"{mat_name} (zip)"
                    )
                    self._download_zip_extract(url, dest, mat_name, job)
            except Exception as exc:
                job["errors"].append(f"{mat_name}: {exc}")
            job["done"] += 1
        job["status"] = "done"
        if job["errors"]:
            _finish_material_job(
                mat_job_id, "failed",
                "; ".join(job["errors"][:3]) + (" …" if len(job["errors"]) > 3 else ""),
            )
        else:
            _finish_material_job(mat_job_id, "success")

    def _download_zip_extract(self, url: str, dest: Path, mat_name: str, job: dict) -> None:
        """Original ZIP-based downloader (pbrdf_2020 etc.)."""
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            urllib.request.urlretrieve(url, tmp_path)
            with zipfile.ZipFile(tmp_path) as zf:
                pbsdf_names = [n for n in zf.namelist() if n.endswith(".pbsdf") or n.endswith(".bsdf")]
                if pbsdf_names:
                    dest.write_bytes(zf.read(pbsdf_names[0]))
                else:
                    job["errors"].append(f"{mat_name}: no .pbsdf in zip")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _handle_dataset_download_status(self, handler: BaseHTTPRequestHandler, query: dict) -> None:
        job_id = (query.get("job_id") or [""])[0]
        with _download_jobs_lock:
            job = _download_jobs.get(job_id)
        if not job:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "job not found"})
            return
        self._send_json(handler, HTTPStatus.OK, job)

    # ── User settings (storage path overrides etc.) ─────────────────────────

    def _handle_user_settings_get(self, handler: BaseHTTPRequestHandler) -> None:
        from .user_settings import load_user_settings, settings_path
        self._send_json(handler, HTTPStatus.OK, {
            "settings": load_user_settings(),
            "settings_path": str(settings_path()),
        })

    def _handle_user_settings_post(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        from .user_settings import load_user_settings, save_user_settings, MIN_PREVIEW_SPP, MAX_PREVIEW_SPP
        if not isinstance(payload, dict):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "payload must be an object"})
            return
        overrides = payload.get("dataset_storage_overrides")
        if overrides is not None and not isinstance(overrides, dict):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "dataset_storage_overrides must be an object"})
            return
        current = load_user_settings()
        if overrides is not None:
            cleaned: dict[str, str] = {}
            for k, v in overrides.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                v = v.strip()
                if v:
                    cleaned[k] = v
            current["dataset_storage_overrides"] = cleaned
        if "material_preview_spp" in payload:
            spp_val = payload.get("material_preview_spp")
            if spp_val in (None, "", 0, "0"):
                current.pop("material_preview_spp", None)
            else:
                try:
                    n = int(spp_val)
                except (TypeError, ValueError):
                    self._send_json(
                        handler, HTTPStatus.BAD_REQUEST,
                        {"error": "material_preview_spp must be an integer"},
                    )
                    return
                if not (MIN_PREVIEW_SPP <= n <= MAX_PREVIEW_SPP):
                    self._send_json(
                        handler, HTTPStatus.BAD_REQUEST,
                        {"error": f"material_preview_spp must be in [{MIN_PREVIEW_SPP}, {MAX_PREVIEW_SPP}]"},
                    )
                    return
                current["material_preview_spp"] = n
        save_user_settings(current)
        self._send_json(handler, HTTPStatus.OK, {"settings": current})

    def _handle_material_preview_get(
        self,
        handler: BaseHTTPRequestHandler,
        path: str,
        query: dict,
    ) -> None:
        """Serve a Mitsuba-rendered preview PNG for a preset or measured BSDF.

        Honors ``?object=<sphere|french_bread|...>`` query — falls back to
        DEFAULT_PREVIEW_OBJECT if missing or unknown.
        """
        from .sphere_preview import (
            get_preset_preview, get_measured_preview, peek_measured_preview,
            peek_channel_split_preview, resolve_preview_object,
        )
        from .material_library import hpbrdf_channels_dir as _hpbrdf_ch_dir

        cache_dir = self.repo_root / "out" / "material_previews"
        object_id = resolve_preview_object(_maybe_str(query.get("object", [None])[0]))
        # /api/material-preview/curated/{material_id}
        if path.startswith("/api/material-preview/curated/"):
            material_id = path[len("/api/material-preview/curated/"):].strip("/")
            self._serve_curated_preview(handler, material_id, cache_dir, object_id=object_id)
            return
        # /api/material-preview/preset/{bsdf_type}
        if path.startswith("/api/material-preview/preset/"):
            bsdf_type = path[len("/api/material-preview/preset/"):].strip("/")
            png_path = get_preset_preview(bsdf_type, cache_dir, object_id=object_id)
            if png_path is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Preview unavailable for preset: {bsdf_type}"})
                return
            self._send_bytes(handler, HTTPStatus.OK, png_path.read_bytes(), content_type="image/png")
            return
        # ── Phase 10 sub-routes (must match BEFORE the catch-all measured) ──
        #   GET /api/material-preview/measured/{ds}/{mid}/modalities
        #   GET /api/material-preview/measured/{ds}/{mid}/file/{filename}
        if path.startswith("/api/material-preview/measured/") and "/modalities" in path:
            rest = path[len("/api/material-preview/measured/"):].strip("/")
            if rest.endswith("/modalities"):
                core = rest[:-len("/modalities")]
                parts = core.split("/", 1)
                if len(parts) == 2:
                    self._handle_modalities_get(handler, parts[0], parts[1], query)
                    return
        if path.startswith("/api/material-preview/measured/") and "/file/" in path:
            rest = path[len("/api/material-preview/measured/"):].strip("/")
            ds_mid, _, filename = rest.partition("/file/")
            if ds_mid and filename:
                parts = ds_mid.split("/", 1)
                if len(parts) == 2:
                    self._handle_modality_file_get(handler, parts[0], parts[1], filename, query)
                    return

        # /api/material-preview/measured/{dataset_id}/{material_id}?file=<repo_relative_path>
        if path.startswith("/api/material-preview/measured/"):
            rest = path[len("/api/material-preview/measured/"):].strip("/")
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Expected /measured/{dataset_id}/{material_id}"})
                return
            dataset_id, material_id = parts
            file_param = _maybe_str(query.get("file", [None])[0])
            if not file_param:
                self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Missing ?file= query parameter"})
                return
            # Channel-split cache lives at a separate path keyed only on
            # (material_id, mode, size) — peek that FIRST when this
            # material has a local mirror, otherwise the GET would forever
            # 202-loop because peek_measured_preview only knows about the
            # `measured/` subdir.
            if dataset_id == "hpbrdf_2025" and _hpbrdf_ch_dir(self.repo_root, material_id) is not None:
                cs_cached = peek_channel_split_preview(
                    material_id, cache_dir, mode="rgbnir", object_id=object_id,
                )
                if cs_cached is not None and cs_cached.path is not None:
                    self._send_bytes(
                        handler,
                        HTTPStatus.OK,
                        cs_cached.path.read_bytes(),
                        content_type="image/png",
                        extra_headers={"X-Preview-Status": "channel_split"},
                    )
                    return
            # Cache hit → serve immediately. Cache miss → delegate to the same
            # enqueue helper that the invalidate POST uses. Critically this
            # path used to spawn a BG render directly with no job entry, so
            # GET-triggered renders (e.g. card image fetches on a fresh page
            # load) finished invisibly — they never showed up in the bottom
            # panel and `_finish_material_job` had nothing to mark complete.
            cached = peek_measured_preview(
                dataset_id, material_id, file_param, self.repo_root, cache_dir,
                object_id=object_id,
            )
            if cached is not None and cached.path is not None:
                self._send_bytes(
                    handler,
                    HTTPStatus.OK,
                    cached.path.read_bytes(),
                    content_type="image/png",
                    extra_headers={"X-Preview-Status": cached.status},
                )
                return
            # Look up the display name so the job entry reads nicely in the
            # bottom panel. Fall back to material_id if it's not in the
            # current library response.
            from .material_library import get_library_grouped
            groups = get_library_grouped(self.repo_root)
            display_name = material_id
            for g in groups:
                if g["dataset_id"] != dataset_id:
                    continue
                for m in g["materials"]:
                    if m["material_id"] == material_id:
                        display_name = m.get("display_name", material_id)
                        break
                break
            self._enqueue_measured_render(
                dataset_id, material_id, file_param, display_name, object_id=object_id,
            )
            self._send_json(
                handler,
                HTTPStatus.ACCEPTED,
                {"status": "rendering", "dataset_id": dataset_id, "material_id": material_id, "object_id": object_id},
                extra_headers={"X-Preview-Status": "rendering", "Retry-After": "2"},
            )
            return
        self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Unknown material-preview path: {path}"})

    # ── Phase 10: modality discovery + per-band file serve ───────────────
    def _handle_modalities_get(
        self,
        handler: BaseHTTPRequestHandler,
        dataset_id: str,
        material_id: str,
        query: dict,
    ) -> None:
        """List the rendered modalities (composite + per-band, plus future
        Stokes products) for one material as a JSON catalogue. Frontend
        uses this to render the band toggle + grid modal data-driven.
        Returns one synthetic composite entry as a fallback when only the
        legacy flat cache exists.
        """
        from .sphere_preview import (
            material_band_dir, material_band_manifest_path,
            channel_split_cache_path, resolve_preview_object,
        )
        size = int(query.get("size", [192])[0]) if query.get("size") else 192
        object_id = resolve_preview_object(_maybe_str(query.get("object", [None])[0]))
        cache_dir = self._preview_cache_dir()

        ds_enc = quote(dataset_id, safe="")
        mid_enc = quote(material_id, safe="")
        # Per-band /file/ URLs need to keep the object_id around so the
        # follow-up GETs land in the same per-object dir.
        obj_q = f"&object={quote(object_id, safe='')}" if object_id else ""
        composite_fallback_url = (
            f"/api/material-preview/measured/{ds_enc}/{mid_enc}?size={size}{obj_q}"
        )

        manifest_path = material_band_manifest_path(material_id, cache_dir, object_id=object_id)
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                self._send_json(
                    handler, HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"manifest parse failed: {exc}"},
                )
                return
            entries = payload.get("entries", [])
            needs_rerender = False
        else:
            legacy = channel_split_cache_path(
                material_id, cache_dir, mode="rgbnir", size=size, object_id=object_id,
            )
            if not legacy.exists():
                # No render yet for this (material, object_id). Return 200 with
                # an empty list + needs_rerender=true so the frontend can show
                # a friendly "프리뷰 미생성" state instead of swallowing a 404
                # network error. The composite fallback URL still points at the
                # measured GET, which itself enqueues a render on cache miss.
                self._send_json(handler, HTTPStatus.OK, {
                    "material_id": material_id,
                    "default_url": composite_fallback_url,
                    "modalities": [],
                    "needs_rerender": True,
                })
                return
            entries = [{
                "kind": "composite", "label": "RGB (legacy)",
                "url": composite_fallback_url, "group": "composite",
            }]
            needs_rerender = True

        modalities = []
        default_url: str | None = None
        for e in entries:
            # Manifest entries store a bare filename → resolve via /file/.
            # The legacy fallback already has a fully-qualified URL.
            url = e.get("url")
            if not url:
                fname = e.get("file")
                if not fname:
                    continue
                url = (
                    f"/api/material-preview/measured/{ds_enc}/{mid_enc}/file/"
                    f"{quote(fname, safe='')}?object={quote(object_id, safe='')}"
                )
            entry_out = {
                "kind": e.get("kind", "band"),
                "label": e.get("label", url),
                "group": e.get("group", "spectral"),
                "url": url,
            }
            for opt in ("wavelength_nm", "is_nir"):
                if opt in e:
                    entry_out[opt] = e[opt]
            modalities.append(entry_out)
            if e.get("kind") == "composite" and default_url is None:
                default_url = url

        self._send_json(handler, HTTPStatus.OK, {
            "material_id": material_id,
            "default_url": default_url or composite_fallback_url,
            "modalities": modalities,
            # Hint the UI: legacy cache → only composite available; user
            # must rerender to populate per-band PNGs.
            "needs_rerender": needs_rerender,
        })

    def _handle_modality_file_get(
        self,
        handler: BaseHTTPRequestHandler,
        dataset_id: str,
        material_id: str,
        filename: str,
        query: dict | None = None,
    ) -> None:
        """Static-serve a single PNG out of the per-material channel-split
        directory. Path-traversal guard: filename must be a bare basename
        (no ``..``, no ``/``, no leading ``.``) and the resolved path must
        stay inside the material's directory. ``?object=`` scopes lookups
        to the per-object subdirectory.
        """
        from .sphere_preview import material_band_dir, resolve_preview_object
        # First-line guard: reject anything that isn't a plain basename.
        if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid filename"})
            return
        if ".." in filename:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid filename"})
            return

        object_id = resolve_preview_object(
            _maybe_str(((query or {}).get("object", [None]) or [None])[0])
        )
        cache_dir = self._preview_cache_dir()
        bdir = material_band_dir(material_id, cache_dir, object_id=object_id).resolve()
        target = (bdir / filename).resolve()
        # Defense in depth: even if the basename guard slips, ensure the
        # resolved target stays under the material dir.
        try:
            target.relative_to(bdir)
        except ValueError:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "path escape"})
            return
        if not target.exists() or not target.is_file():
            self._send_json(
                handler, HTTPStatus.NOT_FOUND,
                {"error": "modality file not found", "filename": filename},
            )
            return
        # Only PNG-bearing files are served from this route.
        if target.suffix.lower() != ".png":
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "only .png served"})
            return

        self._send_bytes(
            handler, HTTPStatus.OK, target.read_bytes(),
            content_type="image/png",
            extra_headers={"Cache-Control": "public, max-age=86400"},
        )

    def _serve_curated_preview(
        self,
        handler: BaseHTTPRequestHandler,
        material_id: str,
        cache_dir: Path,
        *,
        object_id: str = "sphere",
    ) -> None:
        """Serve the pre-baked curated material PNG, falling back to on-demand render.

        The pre-baked PNGs in ``assets/material_previews/curated/`` only
        exist for the default sphere preview object — anything else has to
        go through the on-demand render path.
        """
        from .curated_library import curated_preview_path, get_curated_material
        from .sphere_preview import DEFAULT_PREVIEW_OBJECT, resolve_preview_object

        object_id = resolve_preview_object(object_id)

        mat = get_curated_material(material_id)
        if mat is None:
            self._send_json(
                handler,
                HTTPStatus.NOT_FOUND,
                {"error": f"Unknown curated material: {material_id}"},
                extra_headers={"X-Preview-Status": "unknown"},
            )
            return

        # Baked PNG only exists for the default object (sphere). For other
        # objects we always render on demand.
        if object_id == DEFAULT_PREVIEW_OBJECT:
            baked = curated_preview_path(self.repo_root, material_id)
            if baked.exists():
                self._send_bytes(
                    handler,
                    HTTPStatus.OK,
                    baked.read_bytes(),
                    content_type="image/png",
                    extra_headers={
                        "X-Preview-Status": "baked",
                        "Cache-Control": "public, max-age=86400",
                    },
                )
                return

        # Cache miss path — see `_enqueue_curated_render` below.
        out = cache_dir / "curated" / f"{material_id}_{object_id}.png"
        if out.exists():
            self._send_bytes(
                handler,
                HTTPStatus.OK,
                out.read_bytes(),
                content_type="image/png",
                extra_headers={"X-Preview-Status": "ok"},
            )
            return

        self._enqueue_curated_render(mat, material_id, object_id=object_id)
        self._send_json(
            handler,
            HTTPStatus.ACCEPTED,
            {"status": "rendering", "material_id": material_id, "object_id": object_id},
            extra_headers={"X-Preview-Status": "rendering", "Retry-After": "2"},
        )

    def _serve_static_file(self, handler: BaseHTTPRequestHandler, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Static asset not found: {path.name}"})
            return
        self._serve_file(handler, path, default_type="text/css; charset=utf-8")

    def _serve_spa_file(self, handler: BaseHTTPRequestHandler, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"SPA asset not found: {path.name}"})
            return
        self._serve_file(handler, path)

    def _serve_repo_artifact(self, handler: BaseHTTPRequestHandler, repo_relative_path: str) -> None:
        candidate = resolve_repo_path(self.repo_root, repo_relative_path).resolve()
        try:
            candidate.relative_to(self.repo_root)
        except ValueError:
            self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Artifact path must stay within repo root."})
            return
        if not candidate.exists() or not candidate.is_file():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Artifact not found: {repo_relative_path}"})
            return
        self._serve_file(handler, candidate)

    def _serve_scene_geometry(self, handler: BaseHTTPRequestHandler, scene_id: str, mesh_id: str) -> None:
        detail = self._scene_detail(scene_id).get("scene")
        if not detail:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown scene_id: {scene_id}"})
            return

        snapshot_ref = _maybe_str(detail.get("scene_snapshot_ref"))
        snapshot, _cameras, _lights = self._load_snapshot_sidecars(snapshot_ref)
        if snapshot is None:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "Scene snapshot unavailable.", "scene_id": scene_id})
            return

        match = None
        for mesh in snapshot.meshes:
            candidates = {
                mesh.mesh_id,
                mesh.source_path,
                mesh.name,
                Path(mesh.geometry_path).stem if mesh.geometry_path else "",
            }
            if mesh_id in candidates:
                match = mesh
                break

        if match is None or not match.geometry_path:
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Geometry not found for mesh_id: {mesh_id}", "scene_id": scene_id})
            return

        self._serve_repo_artifact(handler, match.geometry_path)

    def _serve_file(self, handler: BaseHTTPRequestHandler, path: Path, *, default_type: str | None = None) -> None:
        payload = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))
        content_type = default_type or mime_type or "application/octet-stream"
        self._send_bytes(handler, HTTPStatus.OK, payload, content_type=content_type)

    def _last_command_of_type(self, *types: str) -> "_IsaacRemoteCommand | None":
        with self._condition:
            commands = [cmd for cmd in self._isaac_commands.values() if cmd.command_type in types]
        if not commands:
            return None
        commands.sort(key=lambda c: _safe_sort_ts(c.updated_at or c.completed_at or c.created_at), reverse=True)
        return commands[0]

    def _bridge_pipeline_status(self) -> list[dict[str, Any]]:
        """Derive 8-stage pipeline status from in-memory data."""
        session = self._isaac_session

        def _step(key: str, label: str, label_kr: str, status: str, *,
                   last_ok_at: str | None = None, last_error_at: str | None = None,
                   last_error_msg: str | None = None, detail: str | None = None) -> dict[str, Any]:
            return {
                "key": key, "label": label, "label_kr": label_kr, "status": status,
                "last_ok_at": last_ok_at, "last_error_at": last_error_at,
                "last_error_msg": last_error_msg, "detail": detail,
            }

        def _from_command(key: str, label: str, label_kr: str, cmd: "_IsaacRemoteCommand | None", *,
                          warn_if: bool = False) -> dict[str, Any]:
            if cmd is None:
                return _step(key, label, label_kr, "inactive")
            if cmd.status == "succeeded":
                st = "warn" if warn_if else "ok"
                return _step(key, label, label_kr, st, last_ok_at=cmd.completed_at or cmd.updated_at)
            if cmd.status in ("failed", "cancelled"):
                return _step(key, label, label_kr, "error",
                              last_error_at=cmd.completed_at or cmd.updated_at,
                              last_error_msg=cmd.error)
            if cmd.status in ("queued", "dispatched", "running"):
                return _step(key, label, label_kr, "warn", detail=cmd.progress_stage or cmd.status)
            return _step(key, label, label_kr, "inactive")

        last_succeeded_job = next(
            (j for j in sorted(self._jobs.values(), key=lambda x: _safe_sort_ts(x.status.finished_at), reverse=True)
             if j.status.status == "succeeded"), None
        )
        last_manifest_job = next(
            (j for j in sorted(self._jobs.values(), key=lambda x: _safe_sort_ts(x.status.finished_at), reverse=True)
             if j.status.manifest_path), None
        )

        steps = [
            _step("connected", "Isaac Connected", "Isaac 연결",
                  "ok" if session else "inactive",
                  last_ok_at=session.opened_at if session else None),
            _from_command("scene_loaded", "Scene Loaded", "Scene 로드",
                          self._last_command_of_type("load_scene")),
            _from_command("render_ready", "Render-Ready", "렌더 준비",
                          self._last_command_of_type("prepare_render_ready")),
            _from_command("session_connected", "Session Connected", "세션 연결",
                          self._last_command_of_type("connect_session")),
            _from_command("session_synced", "Session Synced", "세션 동기화",
                          self._last_command_of_type("sync_session"),
                          warn_if=bool(session and session.state_dirty)),
            _from_command("render_dispatched", "Render Dispatched", "렌더 요청",
                          self._last_command_of_type("render_current_view", "render_sensor")),
            _step("mitsuba_done", "Mitsuba Done", "렌더 완료",
                  "ok" if last_succeeded_job else "inactive",
                  last_ok_at=last_succeeded_job.status.finished_at if last_succeeded_job else None),
            _step("capture_attached", "Capture Attached", "캡처 연결",
                  "ok" if last_manifest_job else "inactive",
                  last_ok_at=last_manifest_job.status.finished_at if last_manifest_job else None),
        ]
        return steps

    def _health_detail_text(self) -> str:
        from datetime import datetime, timezone as _tz

        summary = self._summary_payload()
        parts = []
        worker_state = summary.get("worker_state", "idle")
        queue_length = int(summary.get("queue_length", 0))
        failed_count = int(summary.get("failed_jobs", 0))
        isaac_connected = summary.get("isaac_connected", False)
        avg_rt = summary.get("avg_render_time_s")
        today_completed = int(summary.get("today_completed", 0))

        if worker_state == "running":
            parts.append("worker running")
        else:
            parts.append("worker idle")

        if queue_length > 0:
            parts.append(f"queue {queue_length}")
        else:
            parts.append("queue empty")

        if failed_count > 0:
            parts.append(f"{failed_count} failed")

        if not isaac_connected:
            parts.append("Isaac disconnected")
        else:
            parts.append("Isaac connected")

        if today_completed > 0 and avg_rt:
            parts.append(f"today {today_completed} renders · avg {avg_rt:.0f}s")
        elif today_completed > 0:
            parts.append(f"{today_completed} renders today")

        return " · ".join(parts)

    def _stuck_jobs(self, *, threshold_s: float = 600.0) -> list[dict[str, Any]]:
        from datetime import datetime, timezone as _tz
        now = _utc_now()
        stuck = []
        for job in self._job_records():
            if job["status"] != "running":
                continue
            started_at = job.get("started_at")
            if not started_at:
                continue
            try:
                started_dt = datetime.fromisoformat(started_at).astimezone(_tz.utc)
                if (now - started_dt).total_seconds() >= threshold_s:
                    stuck.append(job)
            except Exception:
                pass
        return stuck

    def _active_isaac_command_summary(self) -> dict[str, Any] | None:
        """Return the most recent in-flight Isaac command, if any."""
        with self._condition:
            active = [
                cmd for cmd in self._isaac_commands.values()
                if cmd.status in {"queued", "dispatched", "running"}
            ]
        if not active:
            return None
        active.sort(key=lambda c: _safe_sort_ts(c.updated_at or c.created_at), reverse=True)
        cmd = active[0]
        elapsed_s = None
        try:
            started_at = datetime.fromisoformat(cmd.created_at).astimezone(timezone.utc)
            elapsed_s = max(0, int((_utc_now() - started_at).total_seconds()))
        except Exception:
            elapsed_s = None
        payload = self._isaac_command_payload(cmd)
        payload["elapsed_s"] = elapsed_s
        return payload

    def _latest_isaac_command_summary(self) -> dict[str, Any] | None:
        with self._condition:
            commands = list(self._isaac_commands.values())
        if not commands:
            return None
        commands.sort(key=lambda c: _safe_sort_ts(c.updated_at or c.completed_at or c.created_at), reverse=True)
        return self._isaac_command_payload(commands[0])

    def _material_presets(self) -> list[dict[str, Any]]:
        return [dict(item) for item in MATERIAL_PRESETS]

    def _session_object_inventory(self, session: _IsaacActiveSession) -> list[dict[str, Any]]:
        selected_paths = {str(path) for path in session.selected_prim_paths if str(path)}
        explicit_paths = {
            str(path)
            for path in (
                list(session.prim_to_shape_ids.keys())
                + list(session.objects.keys())
                + list(session.material_overrides.keys())
                + list(selected_paths)
            )
            if str(path).startswith("/")
        }
        nodes: dict[str, dict[str, Any]] = {}

        def ensure_node(path: str) -> None:
            parts = [part for part in path.split("/") if part]
            if not parts:
                return
            current = ""
            for depth, part in enumerate(parts):
                current += f"/{part}"
                if current not in nodes:
                    nodes[current] = {
                        "path": current,
                        "name": part,
                        "depth": depth,
                        "kind": "group",
                        "selected": False,
                        "shape_count": 0,
                        "has_state": False,
                        "visible": None,
                        "override_bsdf": None,
                    }

        for path in explicit_paths:
            ensure_node(path)

        for path, node in nodes.items():
            object_state = session.objects.get(path)
            override = session.material_overrides.get(path)
            if override is None and object_state is not None:
                override = object_state.bsdf_override
            node["selected"] = path in selected_paths
            node["shape_count"] = len(session.prim_to_shape_ids.get(path, []))
            node["has_state"] = object_state is not None
            node["visible"] = object_state.visible if object_state is not None else None
            node["override_bsdf"] = override.bsdf_type if override is not None else None
            node["transform"] = list(object_state.transform) if object_state is not None and object_state.transform else None
            if path in explicit_paths and (node["shape_count"] or node["has_state"] or node["override_bsdf"] is not None):
                node["kind"] = "object"

        object_translations: dict[str, tuple[float, float, float]] = {}
        for prim_path, object_state in session.objects.items():
            translation = _object_transform_translation(object_state.transform)
            if translation is None:
                continue
            object_translations[str(prim_path)] = (float(translation[0]), float(translation[1]), float(translation[2]))

        def _synthetic_transform_from_translation(translation: tuple[float, float, float]) -> list[float]:
            tx, ty, tz = translation
            return [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                tx, ty, tz, 1.0,
            ]

        # Build ancestor→[descendant translations] map in O(N·depth) instead of O(N²)
        # For each object path, walk up the hierarchy and accumulate translation into each ancestor node
        ancestor_translations: dict[str, list[tuple[float, float, float]]] = {}
        ancestor_shape_counts: dict[str, int] = {}
        for obj_path, translation in object_translations.items():
            parts = [p for p in obj_path.split("/") if p]
            ancestor = ""
            for part in parts:
                ancestor += f"/{part}"
                if ancestor not in ancestor_translations:
                    ancestor_translations[ancestor] = []
                ancestor_translations[ancestor].append(translation)
            # Accumulate shape counts along ancestry
            obj_shapes = len(session.prim_to_shape_ids.get(obj_path, []))
            if obj_shapes:
                ancestor = ""
                for part in parts:
                    ancestor += f"/{part}"
                    ancestor_shape_counts[ancestor] = ancestor_shape_counts.get(ancestor, 0) + obj_shapes

        for path, node in nodes.items():
            if node.get("transform"):
                continue
            descendant_points = ancestor_translations.get(path)
            if not descendant_points:
                continue
            count = len(descendant_points)
            centroid = (
                sum(item[0] for item in descendant_points) / count,
                sum(item[1] for item in descendant_points) / count,
                sum(item[2] for item in descendant_points) / count,
            )
            node["transform"] = _synthetic_transform_from_translation(centroid)
            if not node.get("shape_count"):
                node["shape_count"] = ancestor_shape_counts.get(path, 0) or count

        robot_root_paths = {
            path
            for path, node in nodes.items()
            if str(node.get("name") or "").lower().startswith("rangermini")
        }
        for path, node in nodes.items():
            matched_root = next(
                (root for root in sorted(robot_root_paths, key=len, reverse=True) if path == root or path.startswith(f"{root}/")),
                None,
            )
            if not matched_root:
                continue
            node["robot_root_path"] = matched_root
            node["robot_member"] = True
            node["robot_root"] = path == matched_root
            if path == matched_root:
                node["kind"] = "robot"

        result = list(nodes.values())
        result.sort(key=lambda item: tuple(part for part in item["path"].split("/") if part))
        return result

    def _session_robot_inventory(self, session: _IsaacActiveSession) -> list[dict[str, Any]]:
        inventory = self._session_object_inventory(session)
        selected_paths = [str(path) for path in session.selected_prim_paths if isinstance(path, str)]
        robot_nodes = [
            node for node in inventory
            if isinstance(node, Mapping) and node.get("robot_root") is True and isinstance(node.get("path"), str)
        ]
        if not robot_nodes:
            fallback_roots: set[str] = set()
            for path in selected_paths:
                if "/RangerMini" in path or path.rsplit("/", 1)[-1].lower().startswith("rangermini"):
                    fallback_roots.add(path)
                elif "/base_link" in path:
                    fallback_roots.add(path.rsplit("/base_link", 1)[0])
            if fallback_roots:
                for node in inventory:
                    node_path = str(node.get("path") or "")
                    if node_path in fallback_roots:
                        node["robot_root"] = True
                        node["robot_member"] = True
                        node["robot_root_path"] = node_path
                        node["kind"] = "robot"
                        robot_nodes.append(node)
        robots: list[dict[str, Any]] = []
        for node in robot_nodes:
            path = str(node["path"])
            descendants = [
                item for item in inventory
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and str(item.get("path")).startswith(f"{path}/")
            ]
            translation = _object_transform_translation(node.get("transform")) if isinstance(node.get("transform"), list) else None
            robots.append(
                {
                    "path": path,
                    "name": str(node.get("name") or path.rsplit("/", 1)[-1] or path),
                    "label": str(node.get("name") or path.rsplit("/", 1)[-1] or path),
                    "shape_count": int(node.get("shape_count") or 0),
                    "member_count": len(descendants),
                    "selected": any(sel == path or sel.startswith(f"{path}/") for sel in selected_paths),
                    "transform": list(node["transform"]) if isinstance(node.get("transform"), list) else None,
                    "translation": list(translation) if translation is not None else None,
                    "override_count": sum(1 for item in descendants if item.get("override_bsdf")),
                    "hidden_count": sum(1 for item in descendants if item.get("visible") is False),
                    "active_count": sum(1 for item in descendants if item.get("has_state")),
                }
            )
        robots.sort(key=lambda item: item["path"])
        return robots

    def _normalize_command_error(self, message: str | None, *, scene_id: str | None = None) -> str:
        raw = str(message or "").strip()
        if not raw:
            return "Unknown Isaac command failure."
        if "registered but not render-ready" in raw:
            return raw
        if "/isaac/session/open" in raw and "No such file or directory" in raw and "shape_map" in raw:
            scene_label = scene_id or "selected scene"
            try:
                missing_path = raw.split("No such file or directory:", 1)[1].strip().strip("{} ").strip('"').strip("'")
            except Exception:
                missing_path = "shape_map_ref"
            return (
                f"Scene {scene_label} is registered but not render-ready. "
                f"shape_map_ref missing on disk: {missing_path}. "
                "Open the USD only if you just want to inspect it in Isaac, or prepare render-ready files before rendering."
            )
        if "No such file or directory" in raw and "shape_map" in raw:
            scene_label = scene_id or "selected scene"
            return (
                f"Scene {scene_label} is registered but not render-ready. "
                "shape_map_ref is missing on disk. Prepare render-ready files before rendering."
            )
        return raw

    @staticmethod
    def _gpu_stats() -> list[dict[str, Any]]:
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                timeout=2, stderr=subprocess.DEVNULL
            ).decode()
            gpus = []
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 4:
                    gpus.append({
                        "index": int(parts[0]),
                        "util_pct": int(parts[1]),
                        "mem_used_mb": int(parts[2]),
                        "mem_total_mb": int(parts[3]),
                    })
            return gpus
        except Exception:
            return []

    def _health_payload(self) -> dict[str, Any]:
        # Fast path: in-memory reads only — no disk I/O, no telemetry scan.
        # _summary_payload() is too heavy (glob + telemetry JSONL) for a 1s poll endpoint.
        with self._condition:
            running_jobs = [job for job in self._jobs.values() if job.status.status == "running"]
            worker_state = "running" if running_jobs else "idle"
            active_stage = running_jobs[0].status.progress_stage if running_jobs else None
            queue_length = len(self._pending)
            variant = self.variant
            worker_manager = self._render_worker_manager
        render_workers = worker_manager.health() if worker_manager is not None else None
        session = self._isaac_session
        return {
            "status": "ok",
            "base_url": self.base_url,
            "worker_state": worker_state,
            "active_stage": active_stage,
            "queue_length": queue_length,
            "variant": variant,
            "backend_only": _backend_only_mode(),
            "render_queue_enabled": not _backend_only_mode(),
            "render_workers": render_workers,
            "isaac_connected": session is not None,
            "isaac_scene_id": session.scene_id if session else None,
            "isaac_opened_at": session.opened_at if session else None,
            "isaac_updated_at": session.updated_at if session else None,
            "isaac_sensor_count": len(session.sensors) if session else 0,
            "active_isaac_command": self._active_isaac_command_summary(),
            "latest_isaac_command": self._latest_isaac_command_summary(),
            "gpus": self._gpu_stats(),
        }

    def _snapshot_state(self) -> tuple[list[str], dict[str, RenderJobStatus], dict[str, dict[str, Any]]]:
        with self._condition:
            pending = list(self._pending)
            jobs = {job_id: RenderJobStatus(**render_job_status_to_payload(job.status)) for job_id, job in self._jobs.items()}
            cache_stats = {key: dict(value) for key, value in self._scene_cache_stats.items()}
        return pending, jobs, cache_stats

    def _status_file_records(self) -> dict[str, RenderJobStatus]:
        """Read job_status.json files, TTL-cached and mtime-incremental.

        On a cache miss we re-glob the job dirs but only re-deserialize files
        whose mtime changed since last seen (terminal jobs never change, so
        they are parsed once and reused). This keeps the scan cheap even with
        thousands of jobs on a slow network mount. TTL via
        ``ROBOMITUBA_JOB_SCAN_TTL_S``.
        """
        now = time.monotonic()
        if self._job_status_cache is not None and (now - self._job_status_cache_ts) < self._job_status_ttl_s:
            return self._job_status_cache  # type: ignore[return-value]
        records: dict[str, RenderJobStatus] = {}
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            self._job_status_cache = records
            self._job_status_cache_ts = now
            return records
        index = self._job_status_index
        seen: set[str] = set()
        for status_path in root.glob("*/job_status.json"):
            key = str(status_path)
            seen.add(key)
            try:
                mtime = status_path.stat().st_mtime
            except OSError:
                continue
            cached = index.get(key)
            if cached is not None and cached[0] == mtime:
                status = cached[1]
            else:
                try:
                    status = read_render_job_status(status_path)
                except Exception:
                    continue
                index[key] = (mtime, status)
            records[status.job_id] = status
        # Forget index entries whose files were archived/removed.
        if len(index) > len(seen):
            for key in [k for k in index if k not in seen]:
                index.pop(key, None)
        self._job_status_cache = records
        self._job_status_cache_ts = now
        return records

    def _invalidate_job_status_cache(self) -> None:
        """Call this whenever a new job is submitted or status changes to force cache refresh."""
        self._job_status_cache = None
        self._job_status_cache_ts = 0.0
        threading.Thread(target=self._push_job_status_to_subscribers, daemon=True).start()

    def _job_status_ws_payload(self) -> dict[str, Any]:
        jobs = self._job_records(limit=250)
        log_tails: dict[str, list[str]] = {}
        for job in jobs:
            if job.get("status") == "running":
                jid = str(job.get("job_id") or "")
                if jid:
                    log_path = self._job_log_path(jid)
                    try:
                        if log_path.exists():
                            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                            log_tails[jid] = lines[-20:]
                    except Exception:
                        pass
        return {"jobs": jobs, "log_tails": log_tails}

    def _push_job_status_to_subscribers(self) -> None:
        with self._job_status_sub_lock:
            subscribers = list(self._job_status_subscribers)
        if not subscribers:
            return
        try:
            payload = self._job_status_ws_payload()
        except Exception:
            return
        stale: list[_JobStatusSubscriber] = []
        for sub in subscribers:
            try:
                sub.send_json(payload)
            except Exception:
                stale.append(sub)
        if stale:
            with self._job_status_sub_lock:
                for sub in stale:
                    self._job_status_subscribers.discard(sub)

    def _load_saved_request(self, job_id: str, frame_id: str) -> RenderRequest | None:
        request_path = self.repo_root / "out" / "bridge_jobs" / job_id / "requests" / f"{frame_id}.json"
        if not request_path.exists():
            request_dir = request_path.parent
            matches = sorted(request_dir.glob("*.json")) if request_dir.exists() else []
            if not matches:
                return None
            request_path = matches[-1]
        try:
            return render_request_from_payload(_read_json(request_path))
        except Exception:
            return None

    def _collect_render_pass_records(self, node: Any) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if isinstance(node, Mapping):
            if "task" in node and "scene" in node:
                records.append(dict(node))
            for value in node.values():
                records.extend(self._collect_render_pass_records(value))
        elif isinstance(node, list):
            for item in node:
                records.extend(self._collect_render_pass_records(item))
        return records

    def _render_timing_summary_from_bundle(self, bundle: ObservationBundleManifest) -> dict[str, Any] | None:
        timing_log_ref = _maybe_str(bundle.extras.get("timing_log_ref")) if isinstance(bundle.extras, Mapping) else None
        if not timing_log_ref:
            return None
        timing_log_path = resolve_repo_path(self.repo_root, timing_log_ref)
        if not timing_log_path.exists():
            return None
        try:
            timing_payload = json.loads(timing_log_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        pass_records = self._collect_render_pass_records(timing_payload.get("cameras", {}))
        pass_count = len(pass_records)
        scene_cache_hits = sum(1 for record in pass_records if bool(record.get("scene_cache_hit", False)))
        return {
            "timing_log_ref": timing_log_ref,
            "pass_count": pass_count,
            "scene_cache_hits": scene_cache_hits,
            "scene_cache_misses": max(0, pass_count - scene_cache_hits),
            "scene_cache_hit_ratio": (float(scene_cache_hits) / float(pass_count)) if pass_count else 0.0,
            "load_scene_total_s": sum(float(record.get("load_scene_s", 0.0) or 0.0) for record in pass_records),
            "render_total_s": sum(float(record.get("render_s", 0.0) or 0.0) for record in pass_records),
            "total_s": sum(float(record.get("total_s", 0.0) or 0.0) for record in pass_records),
            "tasks": sorted({str(record.get("task") or "unknown") for record in pass_records}),
        }

    def _update_job_render_timing_summary(self, job: _QueuedJob, *, manifest_path: str) -> None:
        manifest_abs = resolve_repo_path(self.repo_root, manifest_path)
        if not manifest_abs.exists():
            return
        try:
            bundle = read_observation_bundle_manifest(manifest_abs)
        except Exception:
            return
        summary = self._render_timing_summary_from_bundle(bundle)
        if summary is None:
            return
        job.status.extras["render_timing_summary"] = summary

    def _job_record_from_status(self, status: RenderJobStatus, *, queue_position: int | None) -> dict[str, Any]:
        from datetime import datetime, timezone as _tz
        request = self._load_saved_request(status.job_id, status.frame_id)
        scene_id = request.scene_state.scene_id if request is not None else None
        scene_version = request.scene_state.scene_version if request is not None else None
        age_s: float | None = None
        elapsed_s: float | None = None
        queue_wait_s: float | None = None
        is_stuck = False
        ref_ts = status.submitted_at
        if ref_ts:
            try:
                ref_dt = datetime.fromisoformat(ref_ts).astimezone(_tz.utc)
                age_s = max(0.0, (_utc_now() - ref_dt).total_seconds())
            except Exception:
                pass
        run_started_at = status.worker_started_at or status.started_at
        if status.submitted_at and run_started_at:
            queue_wait_s = self._seconds_between(status.submitted_at, run_started_at)
        if run_started_at:
            end_ts = status.finished_at or _utc_now_iso()
            elapsed_s = self._seconds_between(run_started_at, end_ts)
            if status.status == "running" and elapsed_s is not None:
                is_stuck = elapsed_s >= 600.0
        return {
            "job_id": status.job_id,
            "frame_id": status.frame_id,
            "status": status.status,
            "submitted_at": status.submitted_at,
            "started_at": status.started_at,
            "worker_started_at": status.worker_started_at,
            "finished_at": status.finished_at,
            "progress_stage": status.progress_stage,
            "manifest_path": status.manifest_path,
            "error": status.error,
            "scene_id": scene_id,
            "scene_version": scene_version,
            "queue_position": queue_position,
            "age_s": age_s,
            "elapsed_s": round(elapsed_s, 2) if elapsed_s is not None else None,
            "queue_wait_s": round(queue_wait_s, 2) if queue_wait_s is not None else None,
            "is_stuck": is_stuck,
            "extras": dict(status.extras),
        }

    def _job_records(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        pending, memory_statuses, _cache_stats = self._snapshot_state()
        statuses = self._status_file_records()
        statuses.update(memory_statuses)
        queue_positions = {job_id: index + 1 for index, job_id in enumerate(pending)}
        records = [
            self._job_record_from_status(status, queue_position=queue_positions.get(job_id))
            for job_id, status in statuses.items()
        ]
        records.sort(key=lambda item: _safe_sort_ts(item["submitted_at"]), reverse=False)
        records.reverse()
        return records[:limit] if limit is not None else records

    def _recent_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        return self._job_records(limit=limit)

    def _failed_jobs(self, *, limit: int) -> list[dict[str, Any]]:
        failures = [item for item in self._job_records() if item["status"] == "failed"]
        return failures[:limit]

    def _activity_feed(self, limit: int = 12) -> list[dict[str, Any]]:
        """Return recent activity items for the home page feed."""
        from datetime import datetime, timezone as _tz

        def _time_ago(ts: str | None) -> str:
            if not ts:
                return "—"
            try:
                dt = datetime.fromisoformat(ts).astimezone(_tz.utc)
                delta = int((_utc_now() - dt).total_seconds())
                if delta < 60:
                    return f"{delta}s ago"
                if delta < 3600:
                    return f"{delta // 60}m ago"
                if delta < 86400:
                    return f"{delta // 3600}h ago"
                return f"{delta // 86400}d ago"
            except Exception:
                return ts[:16] if len(ts) >= 16 else ts

        items: list[dict[str, Any]] = []
        seen_command_keys: set[tuple[str, str, str]] = set()
        for job in self._job_records():
            status = job["status"]
            if status == "succeeded":
                items.append({
                    "type": "render",
                    "label": f"Render completed · {job.get('scene_id') or job['job_id'][:12]}",
                    "time_ago": _time_ago(job.get("finished_at")),
                    "job_id": job["job_id"],
                })
            elif status == "failed":
                items.append({
                    "type": "fail",
                    "label": f"Render failed · {job.get('scene_id') or job['job_id'][:12]}",
                    "time_ago": _time_ago(job.get("finished_at") or job.get("submitted_at")),
                    "job_id": job["job_id"],
                })
        for command in self._list_isaac_commands(limit=limit):
            status = command.get("status")
            scene_id = command.get("scene_id") or "scene"
            label = self._normalize_command_error(command.get("error") or command.get("progress_message") or command.get("command_type") or "Isaac command", scene_id=scene_id)
            command_type = str(command.get("command_type") or "command")
            if status == "failed":
                dedupe_key = ("fail", str(scene_id), label)
                if dedupe_key in seen_command_keys:
                    continue
                seen_command_keys.add(dedupe_key)
                items.append(
                    {
                        "type": "fail",
                        "label": f"Isaac failed · {scene_id} · {label}",
                        "time_ago": _time_ago(command.get("updated_at") or command.get("completed_at") or command.get("created_at")),
                        "command_id": command["command_id"],
                    }
                )
            elif status == "succeeded":
                dedupe_key = ("done", str(scene_id), command_type)
                if dedupe_key in seen_command_keys:
                    continue
                seen_command_keys.add(dedupe_key)
                items.append(
                    {
                        "type": "scene",
                        "label": f"Isaac done · {scene_id} · {label}",
                        "time_ago": _time_ago(command.get("updated_at") or command.get("completed_at") or command.get("created_at")),
                        "command_id": command["command_id"],
                    }
                )
            elif status in {"queued", "dispatched", "running"}:
                dedupe_key = ("active", str(scene_id), command_type)
                if dedupe_key in seen_command_keys:
                    continue
                seen_command_keys.add(dedupe_key)
                items.append(
                    {
                        "type": "system",
                        "label": f"Isaac active · {scene_id} · {label}",
                        "time_ago": _time_ago(command.get("updated_at") or command.get("created_at")),
                        "command_id": command["command_id"],
                    }
                )
        items.sort(key=lambda x: x["time_ago"], reverse=False)
        return items[:limit]

    def _environment_checks(self) -> list[dict[str, Any]]:
        """Return environment diagnostic check results."""
        import os
        checks: list[dict[str, Any]] = []

        # Daemon always reachable (we are serving)
        checks.append({"icon": "✅", "label": "Daemon listening", "detail": self.base_url, "status": "ok"})

        # repo_root exists and writable
        if self.repo_root.exists():
            writable = os.access(self.repo_root, os.W_OK)
            checks.append({
                "icon": "✅" if writable else "⚠️",
                "label": "Repo root writable",
                "detail": str(self.repo_root),
                "status": "ok" if writable else "warn",
            })
        else:
            checks.append({"icon": "❌", "label": "Repo root missing", "detail": str(self.repo_root), "status": "fail"})

        # out/bridge_jobs exists
        jobs_dir = self.repo_root / "out" / "bridge_jobs"
        checks.append({
            "icon": "✅" if jobs_dir.exists() else "⚠️",
            "label": "Jobs output dir",
            "detail": str(jobs_dir),
            "status": "ok" if jobs_dir.exists() else "warn",
        })

        # WSL GPU path
        wsl_lib = Path("/usr/lib/wsl/lib")
        checks.append({
            "icon": "✅" if wsl_lib.exists() else "⚠️",
            "label": "WSL GPU lib path",
            "detail": str(wsl_lib),
            "status": "ok" if wsl_lib.exists() else "warn",
        })

        # Mitsuba variant configured
        variant_ok = bool(self.variant and self.variant != "none")
        checks.append({
            "icon": "✅" if variant_ok else "❌",
            "label": "Mitsuba variant configured",
            "detail": self.variant or "(not set)",
            "status": "ok" if variant_ok else "fail",
        })

        return checks

    def _bundle_manifests(self, *, force_refresh: bool = False) -> list[ObservationBundleManifest]:
        """Glob observation bundle manifests, TTL-cached and mtime-incremental.

        The nested ``*/observations/*/manifest.json`` glob over thousands of
        jobs plus deserializing each was the single slowest control-plane scan
        on the CIFS mount (~2 min cold). The per-path index reuses parsed
        manifests for files whose mtime is unchanged. TTL via
        ``ROBOMITUBA_BUNDLE_SCAN_TTL_S``.
        """
        now = time.monotonic()
        if (
            not force_refresh
            and self._bundle_manifest_cache is not None
            and (now - self._bundle_manifest_cache_ts) < self._bundle_manifest_ttl_s
        ):
            return self._bundle_manifest_cache  # type: ignore[return-value]
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            result: list[ObservationBundleManifest] = []
            self._bundle_manifest_cache = result
            self._bundle_manifest_cache_ts = now
            return result
        index = self._bundle_manifest_index
        seen: set[str] = set()
        bundles: list[ObservationBundleManifest] = []
        for manifest_path in root.glob("*/observations/*/manifest.json"):
            key = str(manifest_path)
            seen.add(key)
            try:
                mtime = manifest_path.stat().st_mtime
            except OSError:
                continue
            cached = index.get(key)
            if cached is not None and cached[0] == mtime:
                bundles.append(cached[1])
            else:
                try:
                    bundle = read_observation_bundle_manifest(manifest_path)
                except Exception:
                    continue
                index[key] = (mtime, bundle)
                bundles.append(bundle)
        # Forget index entries whose files were archived/removed.
        if len(index) > len(seen):
            for key in [k for k in index if k not in seen]:
                index.pop(key, None)
        bundles.sort(key=lambda item: _safe_sort_ts(item.timestamp), reverse=True)
        self._bundle_manifest_cache = bundles
        self._bundle_manifest_cache_ts = now
        return bundles

    def _artifact_href(self, repo_relative_path: str | None) -> str | None:
        if not repo_relative_path:
            return None
        return f"/artifacts?path={quote(repo_relative_path, safe='/')}"

    def _pick_preview_path(self, artifact_paths: Mapping[str, Any]) -> str | None:
        preferred_keys = [
            "png",
            "preview_png",
            "colorbar_png",
            "image",
        ]
        for key in preferred_keys:
            value = artifact_paths.get(key)
            if isinstance(value, str) and value:
                return value
        for value in artifact_paths.values():
            if isinstance(value, str) and value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return value
        return None

    def _capture_camera_payload_from_spec(self, camera: CameraSpec | None) -> dict[str, Any] | None:
        if camera is None:
            return None
        try:
            origin, target, up = camera_to_world_to_lookat(camera.camera_to_world)
        except Exception:
            return None
        return {
            "camera_id": camera.camera_id,
            "camera_name": camera.name,
            "camera_origin": origin.tolist(),
            "camera_target": target.tolist(),
            "camera_up": up.tolist(),
            "camera_fov_deg": float(camera.fov_deg),
            "camera_to_world": list(normalize_mat4_storage(camera.camera_to_world).reshape(-1).astype(float).tolist()),
        }

    def _capture_records(self, bundle: ObservationBundleManifest) -> list[dict[str, Any]]:
        camera_map = {camera.camera_id: camera for camera in bundle.camera_specs}
        per_camera: dict[str, dict[str, Any]] = {}
        for artifact in bundle.artifacts:
            camera_id = artifact.camera_id
            camera_payload = self._capture_camera_payload_from_spec(camera_map.get(camera_id))
            capture = per_camera.setdefault(
                camera_id,
                {
                    "job_id": bundle.job_id,
                    "frame_id": bundle.frame_id,
                    "scene_id": bundle.scene_id,
                    "timestamp": bundle.timestamp,
                    "camera_id": camera_id,
                    "camera_name": camera_map.get(camera_id).name if camera_map.get(camera_id) else camera_id,
                    "sensor_sync_group": camera_map.get(camera_id).sensor_sync_group if camera_map.get(camera_id) else None,
                    "calibration_ref": camera_map.get(camera_id).calibration_ref if camera_map.get(camera_id) else None,
                    "scene_ref": bundle.scene_state.mitsuba_scene_ref,
                    "manifest_path": f"{bundle.bundle_root}/manifest.json",
                    "manifest_href": self._artifact_href(f"{bundle.bundle_root}/manifest.json"),
                    "modalities": [],
                    "preview_items": [],
                    "status": "completed",
                },
            )
            if camera_payload:
                capture.update(camera_payload)
            capture["modalities"].append(artifact.modality)
            preview_path = self._pick_preview_path(artifact.artifact_paths)
            capture["preview_items"].append(
                {
                    "modality": artifact.modality,
                    "href": self._artifact_href(preview_path),
                    "raw_paths": dict(artifact.artifact_paths),
                }
            )
        records = list(per_camera.values())
        records.sort(key=lambda item: (item["timestamp"], item["camera_id"]), reverse=True)
        return records

    def _scene_records(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for bundle in self._bundle_manifests():
            capture_records = self._capture_records(bundle)
            scene = grouped.setdefault(
                bundle.scene_id,
                {
                    "scene_id": bundle.scene_id,
                    "scene_version": bundle.scene_state.scene_version,
                    "illumination_setup": bundle.scene_state.illumination_setup,
                    "latest_timestamp": bundle.timestamp,
                    "capture_count": 0,
                    "camera_ids": set(),
                    "latest_capture": None,
                },
            )
            scene["capture_count"] += len(capture_records)
            scene["camera_ids"].update(record["camera_id"] for record in capture_records)
            if scene["latest_capture"] is None or (bundle.timestamp or "") > (scene["latest_timestamp"] or ""):
                scene["latest_timestamp"] = bundle.timestamp
                scene["latest_capture"] = capture_records[0] if capture_records else None

        records = []
        for scene in grouped.values():
            records.append(
                {
                    "scene_id": scene["scene_id"],
                    "scene_version": scene["scene_version"],
                    "illumination_setup": scene["illumination_setup"],
                    "latest_timestamp": scene["latest_timestamp"],
                    "capture_count": scene["capture_count"],
                    "camera_count": len(scene["camera_ids"]),
                    "latest_capture": scene["latest_capture"],
                }
            )
        records.sort(key=lambda item: _safe_sort_ts(item["latest_timestamp"]), reverse=False)
        records.reverse()
        return records[:limit] if limit is not None else records

    def _scene_detail(self, scene_id: str) -> dict[str, Any]:
        captures: list[dict[str, Any]] = []
        scene_record = None
        catalog = {item["scene_id"]: item for item in self._isaac_scene_catalog_records()}
        for bundle in self._bundle_manifests():
            if bundle.scene_id != scene_id:
                continue
            captures.extend(self._capture_records(bundle))
            if scene_record is None:
                scene_record = {
                    "scene_id": bundle.scene_id,
                    "scene_version": bundle.scene_state.scene_version,
                    "illumination_setup": bundle.scene_state.illumination_setup,
                    "scene_snapshot_ref": bundle.scene_state.scene_snapshot_ref,
                    "mitsuba_scene_ref": bundle.scene_state.mitsuba_scene_ref,
                    "capture_count": 0,
                }
        captures.sort(key=lambda item: _safe_sort_ts(item["timestamp"]), reverse=False)
        captures.reverse()
        catalog_record = catalog.get(scene_id)
        if scene_record is None:
            if catalog_record is not None:
                scene_record = {
                    "scene_id": catalog_record["scene_id"],
                    "scene_version": catalog_record.get("scene_version"),
                    "illumination_setup": catalog_record.get("illumination_setup"),
                    "scene_snapshot_ref": catalog_record.get("scene_snapshot_ref"),
                    "mitsuba_scene_ref": catalog_record.get("mitsuba_scene_ref"),
                    "usd_stage_path": catalog_record.get("usd_stage_path"),
                    "shape_map_ref": catalog_record.get("shape_map_ref"),
                    "render_ready": catalog_record.get("render_ready"),
                    "mitsuba_scene_exists": catalog_record.get("mitsuba_scene_exists"),
                    "shape_map_exists": catalog_record.get("shape_map_exists"),
                    "capture_count": int(catalog_record.get("capture_count", 0) or 0),
                    "camera_count": int(catalog_record.get("camera_count", 0) or 0),
                    "latest_timestamp": catalog_record.get("latest_timestamp"),
                    "source": catalog_record.get("source"),
                }
        elif scene_record is not None:
            scene_record["capture_count"] = len(captures)
            scene_record["camera_count"] = len({capture["camera_id"] for capture in captures})
        if scene_record is not None and catalog_record is not None:
            for key in (
                "usd_stage_path",
                "shape_map_ref",
                "material_overrides_ref",
                "render_ready",
                "readiness_status",
                "mitsuba_scene_exists",
                "shape_map_exists",
                "source",
                "latest_timestamp",
            ):
                if key in catalog_record:
                    scene_record[key] = catalog_record.get(key)
        if scene_record is not None:
            healed_snapshot_ref = self._resolve_scene_snapshot_ref(
                scene_snapshot_ref=_maybe_str(scene_record.get("scene_snapshot_ref")),
                shape_map_ref=_maybe_str(scene_record.get("shape_map_ref")),
                mitsuba_scene_ref=_maybe_str(scene_record.get("mitsuba_scene_ref")),
            )
            if healed_snapshot_ref:
                scene_record["scene_snapshot_ref"] = healed_snapshot_ref
            scene_record = self._attach_load_prep_summary(scene_record)
        return {
            "scene_id": scene_id,
            "scene": scene_record,
            "captures": captures,
            "latest_capture": captures[0] if captures else None,
        }

    def _scene_snapshot_usd_stage_ref(self, scene_snapshot_ref: str | None) -> str | None:
        snapshot, _cameras, _lights = self._load_snapshot_sidecars(scene_snapshot_ref)
        return snapshot.usd_stage_path if snapshot is not None else None

    def _human_bytes(self, value: int | None) -> str | None:
        if value is None:
            return None
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(value)
        unit_index = 0
        while size >= 1024.0 and unit_index < len(units) - 1:
            size /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size)} {units[unit_index]}"
        return f"{size:.1f} {units[unit_index]}"

    def _resolve_isaac_catalog_path(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        path_str = str(raw_path).strip()
        if not path_str:
            return None
        if path_str.startswith("\\\\"):
            marker = "\\workspace\\jinnyeong\\project\\robomituba\\"
            lowered = path_str.lower()
            marker_index = lowered.find(marker)
            if marker_index >= 0:
                suffix = path_str[marker_index + len(marker) :].replace("\\", "/")
                return self.repo_root / suffix
            return None
        if len(path_str) > 1 and path_str[1] == ":":
            lowered = path_str.replace("\\", "/").lower()
            marker = "/workspace/jinnyeong/project/robomituba/"
            marker_index = lowered.find(marker)
            if marker_index >= 0:
                suffix = path_str.replace("\\", "/")[marker_index + len(marker) :]
                return self.repo_root / suffix
            return None
        path = Path(path_str)
        if path.is_absolute():
            return path
        return resolve_repo_path(self.repo_root, path_str)

    def _guess_scene_asset_root(self, stage_path: Path) -> Path | None:
        if stage_path.is_dir():
            return stage_path
        parent = stage_path.parent
        if parent.name.lower() == "usd" and parent.parent.exists():
            return parent.parent
        for ancestor in [parent, *parent.parents]:
            try:
                has_textures = (ancestor / "textures").exists()
                has_usd = (ancestor / "USD").exists() or (ancestor / "usd").exists()
            except Exception:
                continue
            if has_textures or has_usd:
                return ancestor
            if ancestor == self.repo_root:
                break
        return parent if parent.exists() else None

    def _measure_path_size(self, path: Path) -> dict[str, Any]:
        cache_key = str(path.resolve()) if path.exists() else str(path)
        cached = self._path_size_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        payload: dict[str, Any] = {
            "exists": path.exists(),
            "bytes": None,
            "file_count": 0,
        }
        if not path.exists():
            self._path_size_cache[cache_key] = dict(payload)
            return payload
        if path.is_file():
            payload["bytes"] = int(path.stat().st_size)
            payload["file_count"] = 1
            self._path_size_cache[cache_key] = dict(payload)
            return payload
        total_bytes = 0
        file_count = 0
        for root, _dirs, files in os.walk(path):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    total_bytes += int(file_path.stat().st_size)
                    file_count += 1
                except OSError:
                    continue
        payload["bytes"] = total_bytes
        payload["file_count"] = file_count
        self._path_size_cache[cache_key] = dict(payload)
        return payload

    def _load_prep_summary(self, usd_stage_path: str | None) -> dict[str, Any]:
        stage_path = self._resolve_isaac_catalog_path(usd_stage_path)
        if stage_path is None:
            return {
                "stage_path_local": None,
                "stage_exists": False,
                "stage_size_bytes": None,
                "stage_size_label": None,
                "asset_root_local": None,
                "asset_root_exists": False,
                "asset_root_size_bytes": None,
                "asset_root_size_label": None,
                "asset_file_count": 0,
                "size_tier": "unknown",
                "advisory_en": "Scene size is not available from this path yet.",
                "advisory_kr": "이 경로에서는 아직 장면 크기를 계산할 수 없습니다.",
            }
        stage_stats = self._measure_path_size(stage_path)
        asset_root = self._guess_scene_asset_root(stage_path)
        asset_stats = self._measure_path_size(asset_root) if asset_root is not None else {"exists": False, "bytes": None, "file_count": 0}
        reference_bytes = asset_stats.get("bytes") if asset_stats.get("exists") else stage_stats.get("bytes")
        size_tier = "light"
        advisory_en = "Light scene. Isaac should open this without much waiting."
        advisory_kr = "가벼운 장면입니다. Isaac에서 비교적 빠르게 열릴 가능성이 큽니다."
        if reference_bytes is None:
            size_tier = "unknown"
            advisory_en = "Scene size is still unknown. Be ready for a cold load."
            advisory_kr = "장면 크기를 아직 알 수 없습니다. 처음 로딩은 시간이 걸릴 수 있습니다."
        elif reference_bytes >= 5 * 1024**3:
            size_tier = "huge"
            advisory_en = "Huge scene. Isaac may spend a while loading assets and textures."
            advisory_kr = "매우 큰 장면입니다. Isaac이 에셋과 텍스처를 오래 로딩할 수 있습니다."
        elif reference_bytes >= 1 * 1024**3:
            size_tier = "heavy"
            advisory_en = "Heavy scene. Expect a noticeable load and streaming phase."
            advisory_kr = "무거운 장면입니다. 로딩과 스트리밍에 시간이 꽤 걸릴 수 있습니다."
        elif reference_bytes >= 200 * 1024**2:
            size_tier = "medium"
            advisory_en = "Medium scene. Load should be fine, but textures may take a moment."
            advisory_kr = "중간 규모 장면입니다. 기본 로딩은 괜찮지만 텍스처 로딩에 잠시 걸릴 수 있습니다."
        return {
            "stage_path_local": str(stage_path),
            "stage_exists": bool(stage_stats.get("exists")),
            "stage_size_bytes": stage_stats.get("bytes"),
            "stage_size_label": self._human_bytes(stage_stats.get("bytes")),
            "asset_root_local": str(asset_root) if asset_root is not None else None,
            "asset_root_exists": bool(asset_stats.get("exists")),
            "asset_root_size_bytes": asset_stats.get("bytes"),
            "asset_root_size_label": self._human_bytes(asset_stats.get("bytes")),
            "asset_file_count": int(asset_stats.get("file_count", 0) or 0),
            "size_tier": size_tier,
            "advisory_en": advisory_en,
            "advisory_kr": advisory_kr,
        }

    def _attach_load_prep_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(record)
        enriched.update(self._load_prep_summary(_maybe_str(record.get("usd_stage_path"))))
        return enriched

    def _infer_shape_map_ref(self, *, scene_snapshot_ref: str | None, mitsuba_scene_ref: str | None) -> str | None:
        if scene_snapshot_ref and scene_snapshot_ref.endswith(".json"):
            candidate = Path(scene_snapshot_ref).with_name("shape_map.json").as_posix()
            resolved = resolve_repo_path(self.repo_root, candidate)
            if resolved.exists():
                return candidate
        if mitsuba_scene_ref:
            scene_path = Path(mitsuba_scene_ref)
            candidates = [
                scene_path.with_suffix(".shape_map.json").as_posix(),
                scene_path.with_name(f"{scene_path.stem}.shape_map.json").as_posix(),
                scene_path.with_name("shape_map.json").as_posix(),
            ]
            for candidate in candidates:
                resolved = resolve_repo_path(self.repo_root, candidate)
                if resolved.exists():
                    return candidate
        return None

    def _known_isaac_scene_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for bundle in self._bundle_manifests():
            scene_id = bundle.scene_id
            latest_capture_records = self._capture_records(bundle)
            latest_capture = latest_capture_records[0] if latest_capture_records else None
            shape_map_ref = _maybe_str(bundle.scene_state.extras.get("shape_map_ref")) or self._infer_shape_map_ref(
                scene_snapshot_ref=bundle.scene_state.scene_snapshot_ref,
                mitsuba_scene_ref=bundle.scene_state.mitsuba_scene_ref,
            )
            usd_stage_path = self._scene_snapshot_usd_stage_ref(bundle.scene_state.scene_snapshot_ref)
            record = records.get(scene_id)
            if record is None or (bundle.timestamp or "") > (record.get("latest_timestamp") or ""):
                records[scene_id] = {
                    "scene_id": scene_id,
                    "source": "known_export",
                    "usd_stage_path": usd_stage_path,
                    "scene_snapshot_ref": bundle.scene_state.scene_snapshot_ref,
                    "mitsuba_scene_ref": bundle.scene_state.mitsuba_scene_ref,
                    "shape_map_ref": shape_map_ref,
                    "scene_version": bundle.scene_state.scene_version,
                    "illumination_setup": bundle.scene_state.illumination_setup,
                    "latest_timestamp": bundle.timestamp,
                    "latest_capture": latest_capture,
                    "capture_count": len(latest_capture_records),
                }
        return records

    def _registered_isaac_scene_records(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for scene_id, payload in self._load_registered_isaac_scenes().items():
            usd_stage_path = _maybe_str(payload.get("usd_stage_path"))
            records[scene_id] = {
                "scene_id": scene_id,
                "source": "registered",
                "usd_stage_path": usd_stage_path,
                "scene_snapshot_ref": _maybe_str(payload.get("scene_snapshot_ref")),
                "mitsuba_scene_ref": _maybe_str(payload.get("mitsuba_scene_ref")),
                "shape_map_ref": _maybe_str(payload.get("shape_map_ref")),
                "scene_version": _maybe_str(payload.get("scene_version")),
                "illumination_setup": _maybe_str(payload.get("illumination_setup")),
                "texture_cache_status": _maybe_str(payload.get("texture_cache_status")),
                "texture_cache_root": _maybe_str(payload.get("texture_cache_root")),
                "texture_cache_bytes": payload.get("texture_cache_bytes"),
                "texture_cache_file_count": payload.get("texture_cache_file_count"),
                "texture_cache_last_synced_at": _maybe_str(payload.get("texture_cache_last_synced_at")),
                "texture_cache_source_mode": _maybe_str(payload.get("texture_cache_source_mode")),
                "latest_timestamp": _maybe_str(payload.get("updated_at")) or _maybe_str(payload.get("created_at")),
                "latest_capture": None,
                "capture_count": 0,
            }
        return records

    def _isaac_scene_catalog_records(self) -> list[dict[str, Any]]:
        records = self._known_isaac_scene_records()
        with self._condition:
            preparing_scene_ids = {
                command.scene_id
                for command in self._isaac_commands.values()
                if command.scene_id
                and command.command_type == "prepare_render_ready"
                and command.status in {"queued", "dispatched", "running"}
            }
        for scene_id, registered in self._registered_isaac_scene_records().items():
            if scene_id not in records:
                records[scene_id] = registered
                continue
            merged = records[scene_id]
            for key in (
                "usd_stage_path",
                "scene_snapshot_ref",
                "mitsuba_scene_ref",
                "shape_map_ref",
                "material_overrides_ref",
                "scene_version",
                "illumination_setup",
                "texture_cache_status",
                "texture_cache_root",
                "texture_cache_bytes",
                "texture_cache_file_count",
                "texture_cache_last_synced_at",
                "texture_cache_source_mode",
            ):
                if registered.get(key):
                    merged[key] = registered[key]
            merged["source"] = "known_export+registered"
            if registered.get("latest_timestamp") and (registered["latest_timestamp"] > (merged.get("latest_timestamp") or "")):
                merged["latest_timestamp"] = registered["latest_timestamp"]
        scene_summaries = {item["scene_id"]: item for item in self._scene_records()}
        for scene_id, record in records.items():
            summary = scene_summaries.get(scene_id)
            if summary is not None:
                record["capture_count"] = summary.get("capture_count", record.get("capture_count", 0))
                record["camera_count"] = summary.get("camera_count", record.get("camera_count", 0))
                if summary.get("latest_capture"):
                    record["latest_capture"] = summary["latest_capture"]
                    record["latest_timestamp"] = summary.get("latest_timestamp", record.get("latest_timestamp"))
            else:
                record.setdefault("capture_count", 0)
                record.setdefault("camera_count", 0)
            mitsuba_scene_ref = _maybe_str(record.get("mitsuba_scene_ref"))
            shape_map_ref = _maybe_str(record.get("shape_map_ref"))
            record["mitsuba_scene_exists"] = bool(mitsuba_scene_ref and resolve_repo_path(self.repo_root, mitsuba_scene_ref).exists())
            record["shape_map_exists"] = bool(shape_map_ref and resolve_repo_path(self.repo_root, shape_map_ref).exists())
            record["render_ready"] = bool(record["mitsuba_scene_exists"] and record["shape_map_exists"])
            record["texture_cache_source_mode"] = record.get("texture_cache_source_mode") or self._classify_windows_path_mode(_maybe_str(record.get("usd_stage_path")))
            if not record.get("texture_cache_status"):
                if record["texture_cache_source_mode"] in {"mapped_drive", "local_mirror"}:
                    record["texture_cache_status"] = "bypassed"
                elif record["texture_cache_source_mode"] == "unc":
                    record["texture_cache_status"] = "missing"
                else:
                    record["texture_cache_status"] = "unknown"
            if scene_id in preparing_scene_ids:
                record["readiness_status"] = "preparing"
            else:
                record["readiness_status"] = "render-ready" if record["render_ready"] else "open-only"
            record = self._attach_load_prep_summary(record)
            records[scene_id] = record
        result = list(records.values())
        result.sort(key=lambda item: _safe_sort_ts(item.get("latest_timestamp")), reverse=False)
        result.reverse()
        return result

    def _isaac_scene_detail(self, scene_id: str) -> dict[str, Any]:
        catalog = {item["scene_id"]: item for item in self._isaac_scene_catalog_records()}
        record = catalog.get(scene_id)
        if record is None:
            raise KeyError(scene_id)
        captures = self._scene_detail(scene_id).get("captures", [])
        return {
            "scene": self._attach_load_prep_summary(record),
            "captures": captures,
            "latest_capture": record.get("latest_capture") or (captures[0] if captures else None),
        }

    def _resolve_mitsuba_scene_ref_on_disk(self, mitsuba_ref: str) -> str | None:
        """Return a repo-relative XML path that exists on disk.

        The registered ``mitsuba_scene_ref`` may be stale (e.g. points at
        ``scene.xml`` when only ``scene_curated_shell_furniture_sanitized.xml``
        is present). Probe the parent directory and prefer, in order:
        a file whose ``<stem>.scene_snapshot.json`` already exists, then a
        file containing ``sanitized``, then the first ``.xml`` found.
        """
        if not mitsuba_ref:
            return None
        direct = resolve_repo_path(self.repo_root, mitsuba_ref)
        if direct.exists():
            return mitsuba_ref
        parent = direct.parent
        if not parent.exists():
            return None
        xml_files = sorted(parent.glob("*.xml"))
        if not xml_files:
            return None
        best = next((f for f in xml_files if f.with_suffix(".scene_snapshot.json").exists()), None)
        if best is None:
            best = next((f for f in xml_files if "sanitized" in f.stem.lower()), None)
        if best is None:
            best = xml_files[0]
        return to_repo_relative_posix(self.repo_root, best)

    def _merge_sidecar_overrides(self, spec: SceneOverrideSpec, mitsuba_scene_ref: str | None) -> None:
        """Layer persisted agent overrides onto a SceneOverrideSpec in place.

        Sidecar wins for prims it covers — explicit on-disk picks override
        whatever a stale Isaac session put on the spec. No-op when there's no
        sidecar for the scene.
        """
        if not mitsuba_scene_ref:
            return
        try:
            stored = _load_material_overrides(self.repo_root, mitsuba_scene_ref)
        except Exception:
            return
        if not stored:
            return
        bsdf_overrides = dict(spec.bsdf_overrides or {})
        for prim_path, entry in stored.items():
            bsdf_overrides[prim_path] = entry.to_bsdf_override()
        spec.bsdf_overrides = bsdf_overrides

    def prepare_basic_scene(self, scene_id: str) -> dict[str, Any]:
        """Build a SceneSnapshot + shape_map from the Mitsuba XML on disk and
        re-register the scene so the 3D Blueprint view can render without Isaac.
        """
        detail = self._scene_detail(scene_id)
        scene_record = detail.get("scene") or {}
        registered_ref = _maybe_str(scene_record.get("mitsuba_scene_ref"))
        if not registered_ref:
            raise KeyError(scene_id)
        mitsuba_ref = self._resolve_mitsuba_scene_ref_on_disk(registered_ref) or registered_ref
        result = prepare_basic_scene_from_disk(
            scene_id,
            mitsuba_scene_ref=mitsuba_ref,
            repo_root=self.repo_root,
        )
        self._register_isaac_scene(
            {
                "scene_id": scene_id,
                # _register_isaac_scene requires a usd_stage_path; fall back to the
                # XML ref when no USD was previously registered (offline scenes).
                "usd_stage_path": _maybe_str(scene_record.get("usd_stage_path")) or mitsuba_ref,
                "mitsuba_scene_ref": mitsuba_ref,
                "scene_snapshot_ref": result["scene_snapshot_ref"],
                "shape_map_ref": result["shape_map_ref"],
                "scene_version": _maybe_str(scene_record.get("scene_version")),
                "illumination_setup": _maybe_str(scene_record.get("illumination_setup")),
                "source": "local_xml_v1",
            }
        )
        return result

    def _scene_material_targets(self, scene_id: str) -> dict[str, Any]:
        """Enumerate per-shape semantic context for an external LLM agent.

        Pairs each Mitsuba ``<shape>`` with its USD prim path (via shape_map)
        and any override the agent has already persisted to the sidecar, so
        the agent can resume an in-progress run without re-deciding shapes.
        """
        detail = self._scene_detail(scene_id)
        scene_record = detail.get("scene") or {}
        registered_ref = _maybe_str(scene_record.get("mitsuba_scene_ref"))
        if not registered_ref:
            raise KeyError(scene_id)
        mitsuba_ref = self._resolve_mitsuba_scene_ref_on_disk(registered_ref) or registered_ref
        xml_path = resolve_repo_path(self.repo_root, mitsuba_ref)
        if not xml_path.exists():
            raise FileNotFoundError(f"Mitsuba XML not found on disk: {mitsuba_ref}")

        targets = enumerate_xml_targets(xml_path)

        # Resolve prim_path per shape from the shape_map (build inverse).
        shape_id_to_prim: dict[str, str] = {}
        shape_map_ref = _maybe_str(scene_record.get("shape_map_ref"))
        if shape_map_ref:
            try:
                mapping = read_shape_mapping(shape_map_ref, repo_root=self.repo_root)
                for prim_path, shape_ids in (mapping.get("prim_to_shape_ids") or {}).items():
                    if not isinstance(shape_ids, list):
                        continue
                    for sid in shape_ids:
                        shape_id_to_prim[str(sid)] = str(prim_path)
            except Exception:
                pass

        # Existing overrides (so the agent can resume).
        stored = _load_material_overrides(self.repo_root, mitsuba_ref)

        out_targets: list[dict[str, Any]] = []
        targetable = 0
        for entry in targets:
            shape_id = entry["shape_id"]
            prim_path = shape_id_to_prim.get(shape_id) or f"/xml/{shape_id}"
            geometry_file = entry.get("geometry_file")
            geometry_repo = (
                to_repo_relative_posix(self.repo_root, Path(geometry_file))
                if geometry_file and Path(geometry_file).is_absolute()
                else geometry_file
            )
            applied = stored.get(prim_path)
            target = {
                "prim_path": prim_path,
                "shape_ids": [shape_id],
                "primitive": entry.get("primitive"),
                "geometry_file": geometry_repo,
                "embedded_emitter": bool(entry.get("embedded_emitter")),
                "current_bsdf": entry.get("current_bsdf"),
                "applied_override": (
                    {
                        "bsdf_type": applied.bsdf_type,
                        "dataset_id": applied.dataset_id,
                        "material_id": applied.material_id,
                        "tier": applied.tier,
                        "source": applied.source,
                        "updated_at": applied.updated_at,
                    }
                    if applied is not None
                    else None
                ),
            }
            if not target["embedded_emitter"] and target["geometry_file"]:
                targetable += 1
            out_targets.append(target)

        return {
            "scene_id": scene_id,
            "mitsuba_scene_ref": mitsuba_ref,
            "shape_count": len(out_targets),
            "targetable": targetable,
            "applied_count": len(stored),
            "material_overrides_ref": _overrides_ref_for_scene(self.repo_root, mitsuba_ref) if stored else None,
            "targets": out_targets,
        }

    def apply_material_overrides_batch(
        self,
        scene_id: str,
        *,
        overrides: list[Mapping[str, Any]],
        replace_mode: str = "merge",
    ) -> dict[str, Any]:
        """Persist a chunk of agent-picked BRDF overrides to the sidecar.

        Mirrors successful entries to the live Isaac session if one is open
        for this scene so the in-flight render reflects the new picks
        immediately. Returns per-entry status so the agent can keep its other
        picks even when one prim fails (unknown prim, missing measured file,
        unknown curated material, ...).
        """
        from .curated_library import get_curated_material

        detail = self._scene_detail(scene_id)
        scene_record = detail.get("scene") or {}
        registered_ref = _maybe_str(scene_record.get("mitsuba_scene_ref"))
        if not registered_ref:
            raise KeyError(scene_id)
        mitsuba_ref = self._resolve_mitsuba_scene_ref_on_disk(registered_ref) or registered_ref
        xml_path = resolve_repo_path(self.repo_root, mitsuba_ref)
        if not xml_path.exists():
            raise FileNotFoundError(f"Mitsuba XML not found on disk: {mitsuba_ref}")

        # Resolve known prim paths from shape_map; agent prim paths must be in
        # the map (or use the local "/xml/{shape_id}" convention).
        valid_prim_paths: set[str] = set()
        prim_to_shape_ids: dict[str, list[str]] = {}
        shape_map_ref = _maybe_str(scene_record.get("shape_map_ref"))
        if shape_map_ref:
            try:
                mapping = read_shape_mapping(shape_map_ref, repo_root=self.repo_root)
                for prim_path, shape_ids in (mapping.get("prim_to_shape_ids") or {}).items():
                    if not isinstance(shape_ids, list):
                        continue
                    valid_prim_paths.add(str(prim_path))
                    prim_to_shape_ids[str(prim_path)] = [str(sid) for sid in shape_ids]
            except Exception:
                pass
        # Also accept synthetic /xml/{shape_id} refs from the offline-built snapshot.
        for entry in enumerate_xml_targets(xml_path):
            valid_prim_paths.add(f"/xml/{entry['shape_id']}")

        existing = _load_material_overrides(self.repo_root, mitsuba_ref)
        if replace_mode == "replace_all":
            existing = {}
        elif replace_mode != "merge":
            raise ValueError(f"Unknown replace_mode: {replace_mode!r}")

        applied: list[StoredOverride] = []
        skipped: list[dict[str, Any]] = []
        for raw in overrides:
            prim_path = _maybe_str(raw.get("prim_path") if isinstance(raw, Mapping) else None)
            if not prim_path:
                skipped.append({"prim_path": None, "reason": "missing_prim_path"})
                continue
            if prim_path not in valid_prim_paths:
                skipped.append({"prim_path": prim_path, "reason": "unknown_prim_path"})
                continue
            bsdf_type = _maybe_str(raw.get("bsdf_type")) or ""
            if not bsdf_type:
                skipped.append({"prim_path": prim_path, "reason": "missing_bsdf_type"})
                continue
            extras: dict[str, Any] = dict(raw.get("extras") or {})
            measured_file_path: str | None = None
            dataset_id = _maybe_str(raw.get("dataset_id"))
            material_id = _maybe_str(raw.get("material_id"))
            material_name = _maybe_str(raw.get("material"))

            if bsdf_type == "curated":
                if not material_id:
                    skipped.append({"prim_path": prim_path, "reason": "missing_curated_material_id"})
                    continue
                mat = get_curated_material(material_id)
                if mat is None:
                    skipped.append({"prim_path": prim_path, "reason": "unknown_curated_material", "material_id": material_id})
                    continue
                extras.setdefault("curated_bsdf_spec", dict(mat.bsdf_spec))
                extras.setdefault("curated_category", mat.category)
                extras.setdefault("curated_display_name", mat.display_name)
            elif bsdf_type in ("measured", "measured_polarized"):
                measured_file_path = _maybe_str(raw.get("measured_file_path"))
                if not measured_file_path:
                    skipped.append({"prim_path": prim_path, "reason": "missing_measured_file_path"})
                    continue
                if not resolve_repo_path(self.repo_root, measured_file_path).exists():
                    skipped.append(
                        {
                            "prim_path": prim_path,
                            "reason": "measured_file_missing",
                            "measured_file_path": measured_file_path,
                        }
                    )
                    continue
            # else: parametric BSDF (diffuse/conductor/...) — accept verbatim.

            stored = StoredOverride(
                prim_path=prim_path,
                bsdf_type=bsdf_type,
                dataset_id=dataset_id,
                material_id=material_id,
                measured_file_path=measured_file_path,
                base_color=list(raw["base_color"]) if isinstance(raw.get("base_color"), (list, tuple)) else None,
                roughness=raw.get("roughness") if isinstance(raw.get("roughness"), (int, float)) else None,
                metallic=raw.get("metallic") if isinstance(raw.get("metallic"), (int, float)) else None,
                ior=raw.get("ior") if isinstance(raw.get("ior"), (int, float)) else None,
                material=material_name,
                tier=int(raw["tier"]) if isinstance(raw.get("tier"), (int, float)) else None,
                rationale=_maybe_str(raw.get("rationale")),
                source=_maybe_str(raw.get("source")) or "agent_v1",
                extras=extras,
            )
            applied.append(stored)

        merged = _merge_material_overrides(existing, applied)
        sidecar_path = _save_material_overrides(self.repo_root, mitsuba_ref, merged, scene_id=scene_id)
        sidecar_ref = to_repo_relative_posix(self.repo_root, sidecar_path)

        # Update catalog so subsequent scene reads see the new ref.
        self._register_isaac_scene(
            {
                "scene_id": scene_id,
                "usd_stage_path": _maybe_str(scene_record.get("usd_stage_path")) or mitsuba_ref,
                "mitsuba_scene_ref": mitsuba_ref,
                "material_overrides_ref": sidecar_ref,
            }
        )

        # Mirror to live Isaac session if one is open for this scene.
        material_revision: int | None = None
        session = self._isaac_session
        if session is not None and session.scene_id == scene_id:
            for stored in applied:
                session.material_overrides[stored.prim_path] = stored.to_bsdf_override()
                obj = session.objects.get(stored.prim_path)
                if obj is not None:
                    obj.bsdf_override = session.material_overrides[stored.prim_path]
                    obj.bsdf_override_key = (
                        f"{stored.dataset_id}/{stored.material_id}"
                        if stored.dataset_id and stored.material_id
                        else (stored.bsdf_type or "override")
                    )
            if applied:
                session.updated_at = _utc_now_iso()
                session.material_revision += 1
                session.material_dirty = True
                material_revision = session.material_revision

        return {
            "scene_id": scene_id,
            "mitsuba_scene_ref": mitsuba_ref,
            "applied_count": len(applied),
            "skipped": skipped,
            "material_overrides_ref": sidecar_ref,
            "total_overrides": len(merged),
            "material_revision": material_revision,
        }

    def _register_isaac_scene(self, payload: dict[str, Any]) -> dict[str, Any]:
        usd_stage_path = _maybe_str(payload.get("usd_stage_path"))
        if not usd_stage_path:
            raise ValueError("usd_stage_path is required to register an Isaac scene.")
        scene_id = _maybe_str(payload.get("scene_id")) or Path(usd_stage_path).stem or f"scene-{self._timestamp_slug()}"
        scenes = self._load_registered_isaac_scenes()
        now = _utc_now_iso()
        existing = dict(scenes.get(scene_id, {}))
        existing.update(
            {
                "scene_id": scene_id,
                "usd_stage_path": usd_stage_path,
                "scene_snapshot_ref": _maybe_str(payload.get("scene_snapshot_ref")) or existing.get("scene_snapshot_ref"),
                "mitsuba_scene_ref": _maybe_str(payload.get("mitsuba_scene_ref")) or existing.get("mitsuba_scene_ref"),
                "shape_map_ref": _maybe_str(payload.get("shape_map_ref")) or existing.get("shape_map_ref"),
                "material_overrides_ref": _maybe_str(payload.get("material_overrides_ref")) or existing.get("material_overrides_ref"),
                "scene_version": _maybe_str(payload.get("scene_version")) or existing.get("scene_version"),
                "illumination_setup": _maybe_str(payload.get("illumination_setup")) or existing.get("illumination_setup"),
                "texture_cache_status": _maybe_str(payload.get("texture_cache_status")) or existing.get("texture_cache_status"),
                "texture_cache_root": _maybe_str(payload.get("texture_cache_root")) or existing.get("texture_cache_root"),
                "texture_cache_bytes": payload.get("texture_cache_bytes") if payload.get("texture_cache_bytes") is not None else existing.get("texture_cache_bytes"),
                "texture_cache_file_count": payload.get("texture_cache_file_count") if payload.get("texture_cache_file_count") is not None else existing.get("texture_cache_file_count"),
                "texture_cache_last_synced_at": _maybe_str(payload.get("texture_cache_last_synced_at")) or existing.get("texture_cache_last_synced_at"),
                "texture_cache_source_mode": _maybe_str(payload.get("texture_cache_source_mode")) or existing.get("texture_cache_source_mode"),
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
            }
        )
        scenes[scene_id] = existing
        self._write_registered_isaac_scenes(scenes)
        return self._isaac_scene_detail(scene_id)

    def _latest_capture_record(self, *, scene_id: str | None = None) -> dict[str, Any] | None:
        def _find_capture(force_refresh: bool) -> dict[str, Any] | None:
            bundles = self._bundle_manifests(force_refresh=force_refresh)
            if scene_id:
                for bundle in bundles:
                    if bundle.scene_id != scene_id:
                        continue
                    captures = self._capture_records(bundle)
                    if captures:
                        return captures[0]
                return None
            for bundle in bundles:
                captures = self._capture_records(bundle)
                if captures:
                    return captures[0]
            return None

        if scene_id:
            try:
                detail = self._scene_detail(scene_id)
            except KeyError:
                detail = None
            if detail is not None:
                capture = detail.get("latest_capture")
                if capture is not None:
                    return capture
            capture = _find_capture(force_refresh=False)
            if capture is not None:
                return capture
            return _find_capture(force_refresh=True)
        capture = _find_capture(force_refresh=False)
        if capture is not None:
            return capture
        return _find_capture(force_refresh=True)

    def _capture_detail_by_ids(self, job_id: str, frame_id: str) -> dict[str, Any]:
        manifest_path = self.repo_root / "out" / "bridge_jobs" / job_id / "observations" / frame_id / "manifest.json"
        if not manifest_path.exists():
            raise KeyError(f"{job_id}/{frame_id}")
        bundle = read_observation_bundle_manifest(manifest_path)
        captures = self._capture_records(bundle)
        if not captures:
            raise KeyError(f"{job_id}/{frame_id}")
        return {
            "job_id": job_id,
            "frame_id": frame_id,
            "scene_id": bundle.scene_id,
            "timestamp": bundle.timestamp,
            "captures": captures,
            "latest_capture": captures[0],
        }

    def _summary_payload(self) -> dict[str, Any]:
        pending, _memory_statuses, cache_stats = self._snapshot_state()
        jobs = self._job_records()
        scenes = self._scene_records()
        telemetry = self._telemetry_stats(limit=1200)
        failed_jobs = [job for job in jobs if job["status"] == "failed"]
        worker_state = "running" if any(job["status"] == "running" for job in jobs) else "idle"
        active_stage = next((job["progress_stage"] for job in jobs if job["status"] == "running"), None)
        scene_cache_items = [
            {
                "key": key,
                "submissions": int(value.get("submissions", 0)),
                "runs": int(value.get("runs", 0)),
                "last_submitted_at": value.get("last_submitted_at"),
                "last_started_at": value.get("last_started_at"),
            }
            for key, value in cache_stats.items()
        ]
        scene_cache_items.sort(key=lambda item: _safe_sort_ts(item.get("last_started_at") or item.get("last_submitted_at")), reverse=False)
        scene_cache_items.reverse()
        # ── New fields: today_completed, avg_render_time_s, health_status ──
        from datetime import date as _date
        today_prefix = _date.today().strftime("%Y-%m-%d")
        today_completed = sum(
            1 for job in jobs
            if job["status"] == "succeeded" and (job.get("finished_at") or "").startswith(today_prefix)
        )
        recent_completed = [
            job for job in jobs
            if job["status"] == "succeeded" and (job.get("worker_started_at") or job.get("started_at")) and job.get("finished_at")
        ][-5:]
        avg_render_time_s: float | None = None
        if recent_completed:
            def _parse_ts(s: str) -> float:
                from datetime import datetime, timezone
                try:
                    return datetime.fromisoformat(s).astimezone(timezone.utc).timestamp()
                except Exception:
                    return 0.0
            durations = [
                _parse_ts(j["finished_at"]) - _parse_ts(j.get("worker_started_at") or j["started_at"])
                for j in recent_completed
                if _parse_ts(j["finished_at"]) > _parse_ts(j.get("worker_started_at") or j["started_at"])
            ]
            avg_render_time_s = sum(durations) / len(durations) if durations else None

        if any(job["status"] == "running" for job in jobs):
            health_status = "degraded"
        elif failed_jobs and not any(job["status"] == "succeeded" for job in jobs):
            health_status = "blocked"
        else:
            health_status = "healthy"

        latest_failure_error: str | None = None
        if failed_jobs:
            latest_failure_error = failed_jobs[0].get("error")

        return {
            "base_url": self.base_url,
            "repo_root": str(self.repo_root),
            "variant": self.variant,
            "worker_state": worker_state,
            "active_stage": active_stage,
            "queue_length": len(pending),
            "running_jobs": sum(1 for job in jobs if job["status"] == "running"),
            "queued_jobs": sum(1 for job in jobs if job["status"] == "queued"),
            "failed_jobs": len(failed_jobs),
            "scene_count": len(scenes),
            "latest_scene_id": scenes[0]["scene_id"] if scenes else None,
            "current_scene_id": (self._isaac_session.scene_id if self._isaac_session is not None else (scenes[0]["scene_id"] if scenes else None)),
            "latest_failure_job_id": failed_jobs[0]["job_id"] if failed_jobs else None,
            "latest_failure_error": latest_failure_error,
            "scene_cache_stats": scene_cache_items,
            "today_completed": today_completed,
            "avg_render_time_s": avg_render_time_s,
            "health_status": health_status,
            "isaac_connected": self._isaac_session is not None,
            "isaac_scene_id": self._isaac_session.scene_id if self._isaac_session else None,
            "isaac_opened_at": self._isaac_session.opened_at if self._isaac_session else None,
            "isaac_updated_at": self._isaac_session.updated_at if self._isaac_session else None,
            "isaac_sensor_count": len(self._isaac_session.sensors) if self._isaac_session else 0,
            "active_isaac_command": self._active_isaac_command_summary(),
            "latest_isaac_command": self._latest_isaac_command_summary(),
            "telemetry_summary": {
                "recent_event_count": len(self._telemetry_recent_rows(limit=20)),
                "stage_stat_count": len(telemetry.get("stage_stats", [])),
                "error_summary": telemetry.get("error_summary", []),
                "path_mode_summary": telemetry.get("path_mode_summary", []),
            },
        }

    def _timestamp_slug(self) -> str:
        return _utc_now().strftime("%Y%m%dT%H%M%S")

    def _enqueue_smoke_render(self, *, scene_id: str | None = None) -> RenderJobAccepted:
        detail = self._scene_detail(scene_id) if scene_id else None
        capture = detail["latest_capture"] if detail else None
        if capture is None:
            scenes = self._scene_records(limit=1)
            if not scenes or scenes[0]["latest_capture"] is None:
                raise RuntimeError("No scene capture is available to clone into a smoke render.")
            capture = scenes[0]["latest_capture"]

        request = self._load_saved_request(capture["job_id"], capture["frame_id"])
        if request is None:
            raise RuntimeError("No saved request JSON is available for the latest capture.")

        stamp = self._timestamp_slug()
        request_dict = render_request_to_payload(request)
        request_dict["request_id"] = f"smoke-request-{stamp}"
        request_dict["job_id"] = f"smoke-{stamp}"
        request_dict["frame_id"] = f"frame_{stamp}"
        request_dict["timestamp"] = _utc_now_iso()
        _smoke_options = self._load_scene_render_options(scene_id or _maybe_str(request_dict.get("scene_state", {}).get("scene_id")))
        request_dict["modalities"] = _smoke_options.get("modalities", ["rgb", "depth"])
        _smoke_spp = _smoke_options.get("spp", 64)
        request_dict["render_settings"] = {
            **request_dict.get("render_settings", {}),
            "width": 640,
            "height": 360,
            "path_spp": _smoke_spp,
            "aov_spp": 8,
            "samples_per_pass": 16,
        }
        request_dict["scene_state"] = {
            **request_dict["scene_state"],
            "job_id": request_dict["job_id"],
            "frame_id": request_dict["frame_id"],
            "timestamp": request_dict["timestamp"],
        }
        request_dict["extras"] = {
            **request_dict.get("extras", {}),
            "smoke_test": True,
        }
        smoke_request = render_request_from_payload(request_dict)
        return self.submit(smoke_request)

    def _isaac_guide_payload(self) -> dict[str, Any]:
        repo_root = str(self.repo_root).replace("\\", "\\\\")
        windows_repo_root = r"%ROBOMITUBA_WINDOWS_REPO_ROOT%"
        windows_apps_dir = windows_repo_root + r"\apps"
        windows_moorelane_usd = windows_repo_root + r"\assets\moorelane\Intel_mooreLane_v1_2_0\Intel_mooreLane\USD\MooreLane_ASWF_0623.usda"
        windows_bat_path = windows_repo_root + r"\apps\isaac_extension\isaac-sim-robomituba.example.bat"
        script_path = str(self.repo_root / "apps" / "isaac" / "capture_current_view.py").replace("\\", "\\\\")
        return {
            "daemon_url": self.base_url,
            "helper_import_snippet": "\n".join(
                [
                    "import sys",
                    "import os",
                    r'sys.path.insert(0, os.path.join(os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT", r"J:\project\robomituba"), "apps"))',
                    "from isaac_extension import connect_daemon",
                ]
            ),
            "helper_render_snippet": "\n".join(
                [
                    "import omni.usd",
                    "",
                    "daemon = connect_daemon()",
                    "",
                    "scenes = daemon.list_scenes()",
                    "print([scene['scene_id'] for scene in scenes])",
                    "",
                    'daemon.load_scene(scene_id="moorelane")',
                    "stage = omni.usd.get_context().get_stage()",
                    "",
                    '# Place the robot, move joints/objects, and define your working view in Isaac',
                    'daemon.connect_scene_session("moorelane")',
                    'daemon.sync_scene_state(stage, "moorelane")',
                    'result = daemon.render_current_view("moorelane", submit_mode="blocking")',
                    'print(result["manifest_path"])',
                    'daemon.open_capture(scene_id="moorelane")',
                ]
            ),
            "windows_launcher_snippet": "\n".join(
                [
                    "@echo off",
                    "setlocal",
                    "",
                    'set "SCRIPT_DIR=%~dp0"',
                    'if not defined ROBOMITUBA_WINDOWS_REPO_ROOT set "ROBOMITUBA_WINDOWS_REPO_ROOT=J:\\project\\robomituba"',
                    'set "ROBOMITUBA_ROOT=%ROBOMITUBA_WINDOWS_REPO_ROOT%"',
                    'set "ROBOMITUBA_APPS=%ROBOMITUBA_ROOT%\\apps"',
                    'set "ROBOMITUBA_BRIDGE_SRC=%ROBOMITUBA_ROOT%\\modules\\robomituba_bridge\\src"',
                    'set "ROBOMITUBA_CONVERTER_SRC=%ROBOMITUBA_ROOT%\\modules\\mitsuba_converter\\src"',
                    "",
                    'set "PYTHONPATH=%ROBOMITUBA_APPS%;%ROBOMITUBA_BRIDGE_SRC%;%ROBOMITUBA_CONVERTER_SRC%;%PYTHONPATH%"',
                    "",
                    'call "%SCRIPT_DIR%isaac-sim.bat" ^',
                    '  --ext-folder "%ROBOMITUBA_APPS%" ^',
                    '  --enable isaac_extension ^',
                    '  --/app/python/extraPaths/0="%ROBOMITUBA_APPS%" ^',
                    '  --/app/python/extraPaths/1="%ROBOMITUBA_BRIDGE_SRC%" ^',
                    '  --/app/python/extraPaths/2="%ROBOMITUBA_CONVERTER_SRC%" ^',
                    "  %*",
                ]
            ),
            "windows_launcher_path": windows_bat_path,
            "moorelane_open_only_snippet": "\n".join(
                [
                    "from isaac_extension import connect_daemon",
                    "",
                    "daemon = connect_daemon()",
                    "",
                    'daemon.load_scene(',
                    f'    usd_path=rf"{windows_moorelane_usd}"',
                    ")",
                ]
            ),
            "moorelane_register_snippet": "\n".join(
                [
                    "from isaac_extension import connect_daemon",
                    "",
                    "daemon = connect_daemon()",
                    "",
                    "daemon.register_scene(",
                    '    scene_id="moorelane",',
                    f'    usd_stage_path=rf"{windows_moorelane_usd}",',
                    '    mitsuba_scene_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml",',
                    '    shape_map_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.shape_map.json",',
                    ")",
                ]
            ),
            "session_import_snippet": "\n".join(
                [
                    "import sys",
                    f'sys.path.insert(0, r"{windows_apps_dir}")',
                    "from isaac_extension.stage_capture import capture_session_open, capture_state_patch, capture_current_view_sensor_spec, capture_current_view_camera",
                    "from isaac_extension.daemon_client import open_isaac_session, update_isaac_state, register_isaac_sensors, capture_isaac_view",
                ]
            ),
            "session_render_snippet": "\n".join(
                [
                    "import omni.usd",
                    "stage = omni.usd.get_context().get_stage()",
                    "",
                    "open_isaac_session(",
                    f'    capture_session_open(',
                    '        scene_id="moorelane",',
                    '        mitsuba_scene_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml",',
                    '        shape_map_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.shape_map.json",',
                    "    ),",
                    f'    "{self.base_url}",',
                    ")",
                    "update_isaac_state(capture_state_patch(stage), daemon_url=" + f'"{self.base_url}")',
                    "register_isaac_sensors([capture_current_view_sensor_spec(modalities=['rgb', 'depth', 's1', 'dop'])], daemon_url=" + f'"{self.base_url}")',
                    "result = capture_isaac_view(",
                    f'    daemon_url="{self.base_url}",',
                    "    modalities=['rgb', 'depth', 's1', 'dop'],",
                    "    submit_mode='blocking',",
                    ")",
                    'print(result["manifest_path"])',
                ]
            ),
            # --- Blocked mode (new): Isaac Extension / IsaacStateSnapshot ---
            "extension_import_snippet": "\n".join(
                [
                    "import sys",
                    f'sys.path.insert(0, r"{windows_apps_dir}")',
                    "from isaac_extension.stage_capture import capture_isaac_state",
                    "from isaac_extension.daemon_client import submit_isaac_state_render, enqueue_isaac_state_render",
                    "from robomituba_bridge import BsdfOverride",
                ]
            ),
            "extension_render_snippet": "\n".join(
                [
                    "import omni.usd",
                    "stage = omni.usd.get_context().get_stage()",
                    "",
                    "snapshot = capture_isaac_state(",
                    '    stage,',
                    '    scene_id="moorelane",',
                    '    mitsuba_scene_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml",',
                    '    shape_map_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.shape_map.json",',
                    "    bsdf_overrides_by_path={",
                    '        "/World/Table": BsdfOverride(bsdf_type="mirror_black_enamel"),',
                    "    },",
                    '    modalities=["rgb", "depth", "s1", "dop"],',
                    '    submit_mode="blocking",',
                    ")",
                    "",
                    "result = submit_isaac_state_render(",
                    f'    snapshot, "{self.base_url}", timeout_s=120.0',
                    ")",
                    'print(result["manifest_path"])',
                    'print(result["artifacts"])',
                    "",
                    'accepted = enqueue_isaac_state_render(snapshot, "' + f"{self.base_url}" + '")',
                    'print(accepted["status_url"])',
                ]
            ),
            # --- Queue mode (legacy): RenderRequest + job polling ---
            "import_snippet": "\n".join(
                [
                    "import runpy",
                    f'ns = runpy.run_path(r"{script_path}")',
                ]
            ),
            "submit_snippet": "\n".join(
                [
                    'accepted = ns["capture_and_submit_current_view_request"](',
                    f'    repo_root=r"{repo_root}",',
                    '    mitsuba_scene_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml",',
                    f'    daemon_url="{self.base_url}",',
                    ")",
                    "print(accepted)",
                ]
            ),
            "poll_snippet": "\n".join(
                [
                    'status = ns["wait_for_render_job"](',
                    '    accepted["job_id"],',
                    f'    daemon_url="{self.base_url}",',
                    "    poll_interval_s=1.0,",
                    "    timeout_s=1800.0,",
                    ")",
                    'print(status["manifest_path"])',
                ]
            ),
            # ── New: quickstart cards & steps ──────────────────────────
            "quickstart_choices": [
                {
                    "icon": "⚡",
                    "title_en": "Quick Single Render",
                    "title_kr": "바로 한 장 렌더",
                    "desc_en": "Render the current viewport once. Best for quick checks.",
                    "desc_kr": "현재 viewport 기준으로 즉시 렌더합니다. 빠른 확인에 적합.",
                    "tab": "control-plane",
                },
                {
                    "icon": "🔄",
                    "title_en": "Session + Repeat Render",
                    "title_kr": "세션 연결 반복 작업",
                    "desc_en": "Open a scene, sync stage state, render repeatedly. Best for real workflows.",
                    "desc_kr": "scene을 열고, stage 상태를 동기화하고, 반복 렌더합니다. 실제 작업 흐름에 적합.",
                    "tab": "control-plane",
                },
                {
                    "icon": "📋",
                    "title_en": "Async Queue Render",
                    "title_kr": "잡 큐 비동기",
                    "desc_en": "Submit jobs and poll for results. Best for long or batch renders.",
                    "desc_kr": "작업을 제출하고 결과를 polling합니다. 긴 작업이나 대량 처리에 적합.",
                    "tab": "queue",
                },
            ],
            "quickstart_steps": [
                {"en": "Check daemon is reachable", "kr": "daemon 연결 확인"},
                {"en": "Prepare or register a scene", "kr": "scene 준비 또는 등록"},
                {"en": "Connect a session", "kr": "session 연결"},
                {"en": "Run the render", "kr": "render 실행"},
                {"en": "Open the latest capture", "kr": "최신 capture 확인"},
            ],
            # ── New: Windows launcher paths ─────────────────────────────
            "windows_isaac_sim_root": r"C:\isaac_sim_win",
            "windows_exts_user_path": r"C:\isaac_sim_win\extsUser\robomituba.isaac_extension",
            "windows_wsl_exts_path": "/mnt/c/isaac_sim_win/extsUser/robomituba.isaac_extension",
            # ── Checklist ───────────────────────────────────────────────
            "checklist": [
                {
                    "en": 'Isaac should add the robomituba <code>apps/</code> directory to <code>sys.path</code> (or <code>PYTHONPATH</code>) before importing extension helpers.',
                    "kr": 'Isaac은 extension helper를 import하기 전에 robomituba의 <code>apps/</code> 디렉터리를 <code>sys.path</code> 또는 <code>PYTHONPATH</code>에 추가해야 합니다.',
                },
                {
                    "en": 'Preferred startup path: launch Isaac with the provided <code>.bat</code> so the <code>isaac_extension</code> panel auto-loads. Script Editor snippets are still supported for debugging and quick tests.',
                    "kr": '권장 시작 경로는 제공된 <code>.bat</code> 로 Isaac을 실행해 <code>isaac_extension</code> 패널을 자동 로드하는 것입니다. Script Editor 스니펫은 디버깅과 빠른 테스트용으로 계속 지원됩니다.',
                },
                {
                    "en": "The daemon must be reachable from the Isaac host at the URL shown on this page.",
                    "kr": "이 페이지에 표시된 URL로 Isaac host에서 daemon에 접속할 수 있어야 합니다.",
                },
                {
                    "en": "WSL: set <code>LD_LIBRARY_PATH=/usr/lib/wsl/lib</code> before launching the daemon for GPU Mitsuba renders.",
                    "kr": "WSL에서는 GPU Mitsuba 렌더를 위해 daemon 실행 전에 <code>LD_LIBRARY_PATH=/usr/lib/wsl/lib</code> 를 설정해야 합니다.",
                },
                {
                    "en": "New default flow: open one active Isaac session once, then call <code>/isaac/capture</code> for one-click current view renders.",
                    "kr": "새 기본 흐름은 active Isaac session을 한 번 열고, 이후 <code>/isaac/capture</code> 로 현재 시점을 원클릭 렌더하는 방식입니다.",
                },
                {
                    "en": "Blocked mode (<code>/isaac/render</code>) holds the HTTP connection open until rendering completes. Use async submit for longer jobs.",
                    "kr": "Blocked mode(<code>/isaac/render</code>)는 렌더가 끝날 때까지 HTTP 연결을 유지합니다. 시간이 긴 작업은 async submit을 사용하세요.",
                },
                {
                    "en": "The base scene XML (<code>mitsuba_scene_ref</code>) and explicit shape map (<code>shape_map_ref</code>) must already exist on disk. The daemon patches them at render time; it does not rebuild them from USD.",
                    "kr": "base scene XML(<code>mitsuba_scene_ref</code>)과 explicit shape map(<code>shape_map_ref</code>)은 미리 디스크에 존재해야 합니다. daemon은 렌더 시점에 patch만 적용하며 USD에서 다시 빌드하지 않습니다.",
                },
                {
                    "en": "Prefer setting <code>ROBOMITUBA_WINDOWS_REPO_ROOT</code> to a mapped drive or local SSD mirror such as <code>J:\\project\\robomituba</code>. UNC can open USD stages, but textures are usually more stable from mapped/local paths.",
                    "kr": "가능하면 <code>ROBOMITUBA_WINDOWS_REPO_ROOT</code> 를 <code>J:\\project\\robomituba</code> 같은 mapped drive나 로컬 SSD mirror로 설정하세요. UNC로도 USD stage를 열 수는 있지만, 텍스처는 mapped/local 경로 쪽이 더 안정적인 경우가 많습니다.",
                },
            ],
        }

    def _resolve_scene_snapshot_ref(
        self,
        *,
        scene_snapshot_ref: str | None = None,
        shape_map_ref: str | None = None,
        mitsuba_scene_ref: str | None = None,
    ) -> str | None:
        """Find a usable repo-relative `.scene_snapshot.json` ref.

        Old bundles sometimes store a `.shape_map.json` path in the
        scene_snapshot_ref slot; honor a real `.scene_snapshot.json` first,
        then derive one by convention from sibling shape_map / mitsuba refs.
        """
        candidates: list[str] = []
        for ref in (scene_snapshot_ref, shape_map_ref, mitsuba_scene_ref):
            if not ref:
                continue
            ref_str = str(ref)
            if ref_str.endswith(".scene_snapshot.json"):
                candidates.append(ref_str)
            posix = Path(ref_str).as_posix()
            stem_path = Path(posix)
            sibling = stem_path.with_name(f"{stem_path.stem.split('.')[0]}.scene_snapshot.json").as_posix()
            if sibling not in candidates:
                candidates.append(sibling)
            named = stem_path.with_name("scene_snapshot.json").as_posix()
            if named not in candidates:
                candidates.append(named)
        for candidate in candidates:
            if not candidate.endswith(".json"):
                continue
            try:
                resolved = resolve_repo_path(self.repo_root, candidate)
            except Exception:
                continue
            if resolved.exists():
                return candidate
        return None

    def _load_snapshot_sidecars(self, scene_snapshot_ref: str | None) -> tuple[SceneSnapshot | None, list[dict[str, Any]], list[dict[str, Any]]]:
        if not scene_snapshot_ref or not scene_snapshot_ref.endswith(".json"):
            return None, [], []
        path = resolve_repo_path(self.repo_root, scene_snapshot_ref)
        if not path.exists():
            return None, [], []
        try:
            scene_payload = _read_json(path)
        except Exception:
            return None, [], []

        cameras_payload: list[dict[str, Any]] = []
        lights_payload: list[dict[str, Any]] = []
        if path.name == "scene_snapshot.json":
            cameras_path = path.with_name("cameras.json")
            lights_path = path.with_name("lights.json")
            if cameras_path.exists():
                cameras_payload = _read_json(cameras_path).get("cameras", [])
            if lights_path.exists():
                lights_payload = _read_json(lights_path).get("lights", [])
        else:
            cameras_payload = scene_payload.get("cameras", [])
            lights_payload = scene_payload.get("lights", [])

        try:
            snapshot = scene_snapshot_from_payload(scene_payload, materials=[], cameras=cameras_payload, lights=lights_payload)
        except Exception:
            snapshot = None
        return snapshot, cameras_payload, lights_payload

    def _extract_translation(self, transform: list[float] | None) -> list[float] | None:
        return _object_transform_translation(transform)

    def _active_viewport_sensor(self, session: _IsaacActiveSession) -> IsaacSensorSpec | None:
        viewport_candidates = [
            sensor
            for sensor in session.sensors.values()
            if (sensor.sensor_sync_group or "") == "isaac_viewport"
            or sensor.sensor_id in {"isaac_viewport", "viewport_current"}
        ]
        if viewport_candidates:
            viewport_candidates.sort(key=lambda item: (item.sensor_id != "viewport_current", item.sensor_id != "isaac_viewport", item.sensor_id))
            return viewport_candidates[0]
        sensors = list(session.sensors.values())
        return sensors[0] if sensors else None

    def _camera_overlay_payload(self, camera: CameraOverlay, *, kind: str) -> dict[str, Any]:
        return {
            "camera_id": camera.label,
            "label": camera.label,
            "origin": [float(value) for value in camera.origin],
            "target": [float(value) for value in camera.target],
            "fov_deg": float(camera.fov_deg),
            "kind": kind,
            "color": list(camera.color),
        }

    def _active_viewport_camera_payload(self, session: _IsaacActiveSession) -> dict[str, Any] | None:
        sensor = self._active_viewport_sensor(session)
        if sensor is None or sensor.camera_to_world is None or sensor.fov_deg is None:
            return None
        try:
            normalized_camera = normalize_mat4_storage(sensor.camera_to_world)
            origin, target, up = camera_to_world_to_lookat(normalized_camera)
        except Exception:
            return None
        return {
            "sensor_id": sensor.sensor_id,
            "name": sensor.name,
            "sensor_sync_group": sensor.sensor_sync_group,
            "pose_source": sensor.pose_source,
            "camera_to_world": normalized_camera.reshape(-1).astype(float).tolist(),
            "origin": origin.tolist(),
            "target": target.tolist(),
            "up": up.tolist(),
            "fov_deg": float(sensor.fov_deg),
            "resolution": list(sensor.resolution) if sensor.resolution is not None else None,
            "extras": dict(sensor.extras or {}),
        }

    def _obj_local_bounds(self, geometry_path: str | None) -> dict[str, Any] | None:
        if not geometry_path:
            return None
        cache_key = str(geometry_path)
        if cache_key in self._geometry_bounds_cache:
            cached = self._geometry_bounds_cache[cache_key]
            return dict(cached) if isinstance(cached, dict) else None
        path = resolve_repo_path(self.repo_root, geometry_path)
        if not path.exists() or not path.is_file():
            self._geometry_bounds_cache[cache_key] = None
            return None
        min_corner: np.ndarray | None = None
        max_corner: np.ndarray | None = None
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if not line.startswith("v "):
                        continue
                    parts = line.strip().split()
                    if len(parts) < 4:
                        continue
                    point = np.asarray([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float32)
                    min_corner = point.copy() if min_corner is None else np.minimum(min_corner, point)
                    max_corner = point.copy() if max_corner is None else np.maximum(max_corner, point)
        except Exception:
            self._geometry_bounds_cache[cache_key] = None
            return None
        if min_corner is None or max_corner is None:
            self._geometry_bounds_cache[cache_key] = None
            return None
        size = np.maximum(max_corner - min_corner, 1e-4)
        center = (min_corner + max_corner) * 0.5
        payload = {
            "min": min_corner.astype(float).tolist(),
            "max": max_corner.astype(float).tolist(),
            "size": size.astype(float).tolist(),
            "center": center.astype(float).tolist(),
        }
        self._geometry_bounds_cache[cache_key] = dict(payload)
        return payload

    def _transform_bounds_payload(self, bounds: Mapping[str, Any], transform: list[float] | None) -> dict[str, Any] | None:
        min_corner = bounds.get("min")
        max_corner = bounds.get("max")
        if not isinstance(min_corner, list) or not isinstance(max_corner, list) or len(min_corner) < 3 or len(max_corner) < 3:
            return None
        local_min = np.asarray(min_corner[:3], dtype=np.float32)
        local_max = np.asarray(max_corner[:3], dtype=np.float32)
        matrix = np.eye(4, dtype=np.float32)
        if isinstance(transform, list) and len(transform) == 16:
            try:
                matrix = normalize_mat4_storage(transform).astype(np.float32)
            except Exception:
                matrix = np.eye(4, dtype=np.float32)
        corners = np.asarray(
            [
                [local_min[0], local_min[1], local_min[2], 1.0],
                [local_min[0], local_min[1], local_max[2], 1.0],
                [local_min[0], local_max[1], local_min[2], 1.0],
                [local_min[0], local_max[1], local_max[2], 1.0],
                [local_max[0], local_min[1], local_min[2], 1.0],
                [local_max[0], local_min[1], local_max[2], 1.0],
                [local_max[0], local_max[1], local_min[2], 1.0],
                [local_max[0], local_max[1], local_max[2], 1.0],
            ],
            dtype=np.float32,
        )
        world = corners @ matrix.T
        world_min = world[:, :3].min(axis=0)
        world_max = world[:, :3].max(axis=0)
        size = np.maximum(world_max - world_min, 1e-4)
        center = (world_min + world_max) * 0.5
        return {
            "min": world_min.astype(float).tolist(),
            "max": world_max.astype(float).tolist(),
            "size": size.astype(float).tolist(),
            "center": center.astype(float).tolist(),
        }

    @staticmethod
    def _diagram_category(name: str, source_path: str, material_id: str | None = None) -> str:
        key = " ".join([name, source_path, str(material_id or "")]).lower()
        if any(token in key for token in ("rangermini", "robot", "base_link")):
            return "robot"
        if any(token in key for token in ("floor", "ground", "slab", "tile")):
            return "floor"
        # Split roof/ceiling out of "shell" so the UI can hide them in cutaway view.
        if any(token in key for token in ("ceiling", "roof")):
            return "roof"
        if any(token in key for token in ("wall", "shell")):
            return "shell"
        if any(token in key for token in ("glass", "window", "door", "pane")):
            return "glass"
        if any(token in key for token in ("chair", "table", "desk", "cabinet", "sofa", "shelf", "bed", "bench", "kitchen", "counter", "furniture")):
            return "furniture"
        if any(token in key for token in ("frame", "art", "props", "deco", "plant", "lamp")):
            return "props"
        return "other"

    def _scene_diagram_3d(self, scene_id: str) -> dict[str, Any]:
        detail = self._scene_detail(scene_id)
        scene_record = detail.get("scene")
        session = self._isaac_session if self._isaac_session is not None and self._isaac_session.scene_id == scene_id else None
        if scene_record is None:
            return {
                "scene_id": scene_id,
                "status": "unavailable",
                "reason": "unknown_scene",
                "objects": [],
                "robots": [],
                "active_viewport_camera": None,
                "simplification_mode": "proxy_bounds_v1",
            }
        snapshot_ref = self._resolve_scene_snapshot_ref(
            scene_snapshot_ref=(
                _maybe_str(scene_record.get("scene_snapshot_ref"))
                or (session.scene_snapshot_ref if session is not None else None)
            ),
            shape_map_ref=(
                _maybe_str(scene_record.get("shape_map_ref"))
                or (session.shape_map_ref if session is not None else None)
            ),
            mitsuba_scene_ref=(
                _maybe_str(scene_record.get("mitsuba_scene_ref"))
                or (session.mitsuba_scene_ref if session is not None else None)
            ),
        )
        snapshot, _cameras, _lights = self._load_snapshot_sidecars(snapshot_ref)
        if snapshot is None:
            return {
                "scene_id": scene_id,
                "status": "unavailable",
                "reason": f"snapshot_unavailable:{snapshot_ref or 'missing'}",
                "objects": [],
                "robots": self._session_robot_inventory(session) if session is not None else [],
                "active_viewport_camera": self._active_viewport_camera_payload(session) if session is not None else None,
                "simplification_mode": "proxy_bounds_v1",
            }
        selected_paths = {str(path) for path in (session.selected_prim_paths if session is not None else []) if str(path)}
        objects: list[dict[str, Any]] = []
        scene_points: list[np.ndarray] = []

        for mesh in snapshot.meshes:
            geometry_bounds = self._obj_local_bounds(mesh.geometry_path)
            if geometry_bounds is None:
                translation = _object_transform_translation(mesh.transform)
                if translation is None:
                    continue
                tx, ty, tz = (float(translation[0]), float(translation[1]), float(translation[2]))
                geometry_bounds = {
                    "min": [-0.05, -0.05, -0.05],
                    "max": [0.05, 0.05, 0.05],
                    "size": [0.1, 0.1, 0.1],
                    "center": [0.0, 0.0, 0.0],
                }
                transform = [
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    tx, ty, tz, 1.0,
                ]
            else:
                transform = list(mesh.transform) if isinstance(mesh.transform, list) and len(mesh.transform) == 16 else None
            world_bounds = self._transform_bounds_payload(geometry_bounds, transform)
            if world_bounds is None:
                continue
            size = np.asarray(world_bounds["size"], dtype=np.float32)
            volume = float(size[0] * size[1] * size[2])
            category = self._diagram_category(str(mesh.name or ""), str(mesh.source_path or ""), mesh.material_id)
            is_selected = any(
                candidate and (
                    candidate == str(mesh.source_path or "")
                    or str(mesh.source_path or "").startswith(f"{candidate}/")
                    or candidate.startswith(f"{str(mesh.source_path or '')}/")
                )
                for candidate in selected_paths
            )
            record = {
                "id": str(mesh.mesh_id or mesh.source_path or mesh.name or f"mesh_{len(objects)}"),
                "path": str(mesh.source_path or ""),
                "label": str(mesh.name or mesh.mesh_id or "mesh"),
                "kind": str(mesh.primitive or "mesh"),
                "category": category,
                "material_id": mesh.material_id,
                "selected": is_selected,
                "bounds": world_bounds,
                "transform": list(transform) if isinstance(transform, list) else None,
                "vertex_count": mesh.vertex_count,
                "face_count": mesh.face_count,
                "geometry_path": mesh.geometry_path,
                "_volume": volume,
            }
            objects.append(record)
            scene_points.append(np.asarray(world_bounds["min"], dtype=np.float32))
            scene_points.append(np.asarray(world_bounds["max"], dtype=np.float32))

        if not objects:
            return {
                "scene_id": scene_id,
                "status": "empty",
                "reason": "no_proxy_objects",
                "objects": [],
                "robots": self._session_robot_inventory(session) if session is not None else [],
                "active_viewport_camera": self._active_viewport_camera_payload(session) if session is not None else None,
                "simplification_mode": "proxy_bounds_v1",
            }

        scene_min = np.vstack(scene_points).min(axis=0)
        scene_max = np.vstack(scene_points).max(axis=0)
        scene_size = np.maximum(scene_max - scene_min, 1e-4)
        scene_volume = float(scene_size[0] * scene_size[1] * scene_size[2])
        # Height-fallback: meshes sitting in the top 30% of the scene that didn't
        # match a roof/ceiling token by name still belong above the user → roof.
        roof_height_threshold = float(scene_min[1] + (scene_max[1] - scene_min[1]) * 0.7)
        for record in objects:
            if record["category"] in {"shell", "other"} and record["bounds"]["min"][1] >= roof_height_threshold:
                record["category"] = "roof"
        must_keep = {
            record["id"]
            for record in objects
            if record["selected"] or record["category"] in {"floor", "shell", "glass", "robot"}
        }
        sorted_objects = sorted(objects, key=lambda item: float(item.get("_volume") or 0.0), reverse=True)
        included: list[dict[str, Any]] = []
        for record in sorted_objects:
            volume_ratio = float(record.get("_volume") or 0.0) / scene_volume if scene_volume > 0 else 0.0
            if record["id"] in must_keep or volume_ratio >= 0.0005 or len(included) < 160:
                included.append(record)
        included_ids = {item["id"] for item in included}
        omitted_count = len(objects) - len(included_ids)
        included.sort(key=lambda item: (item["category"] not in {"floor", "shell", "glass"}, item["label"]))
        final_objects = []
        for record in included:
            stripped = {key: value for key, value in record.items() if not key.startswith("_")}
            final_objects.append(stripped)

        # Aggregate rooms by prim path heuristic: second segment is the room,
        # except under /ROOT/Core/* where the third segment names the actual room.
        rooms_acc: dict[str, dict[str, Any]] = {}
        for record in final_objects:
            path = str(record.get("path") or "")
            parts = [p for p in path.split("/") if p]
            if len(parts) < 2:
                continue
            room_id = parts[2] if (len(parts) >= 3 and parts[1].lower() == "core") else parts[1]
            slot = rooms_acc.get(room_id)
            mn = record["bounds"]["min"]
            mx = record["bounds"]["max"]
            if slot is None:
                rooms_acc[room_id] = {
                    "id": room_id,
                    "label": room_id,
                    "object_count": 1,
                    "min": [float(mn[0]), float(mn[1]), float(mn[2])],
                    "max": [float(mx[0]), float(mx[1]), float(mx[2])],
                }
            else:
                slot["object_count"] += 1
                slot["min"] = [min(slot["min"][i], float(mn[i])) for i in range(3)]
                slot["max"] = [max(slot["max"][i], float(mx[i])) for i in range(3)]
        rooms: list[dict[str, Any]] = []
        for slot in rooms_acc.values():
            mn = slot["min"]; mx = slot["max"]
            size = [max(mx[i] - mn[i], 1e-4) for i in range(3)]
            center = [(mn[i] + mx[i]) * 0.5 for i in range(3)]
            rooms.append({
                "id": slot["id"], "label": slot["label"], "object_count": slot["object_count"],
                "bounds": {"min": mn, "max": mx, "size": size, "center": center},
            })
        rooms.sort(key=lambda r: -r["object_count"])

        robots = self._session_robot_inventory(session) if session is not None else []
        active_camera = self._active_viewport_camera_payload(session) if session is not None else None
        status = "partial" if omitted_count > 0 else "ready"
        return {
            "scene_id": scene_id,
            "status": status,
            "reason": "tiny_objects_omitted" if omitted_count > 0 else None,
            "simplification_mode": "proxy_bounds_v1",
            "objects": final_objects,
            "robots": robots,
            "rooms": rooms,
            "active_viewport_camera": active_camera,
            "summary": {
                "object_count_total": len(objects),
                "object_count_included": len(final_objects),
                "object_count_omitted": omitted_count,
                "scene_bounds": {
                    "min": scene_min.astype(float).tolist(),
                    "max": scene_max.astype(float).tolist(),
                    "size": scene_size.astype(float).tolist(),
                    "center": ((scene_min + scene_max) * 0.5).astype(float).tolist(),
                },
            },
        }

    # ── Navigation occupancy / cost map ─────────────────────────────────────

    _OCCUPANCY_LEGEND = [
        {"key": "wall",      "color": "#1f2937", "label_en": "Wall",      "label_kr": "벽"},
        {"key": "glass",     "color": "#06b6d4", "label_en": "Glass",     "label_kr": "유리"},
        {"key": "risk",      "color": "#f97316", "label_en": "Risk zone", "label_kr": "위험구역"},
        {"key": "furniture", "color": "#9ca3af", "label_en": "Furniture", "label_kr": "가구"},
        {"key": "free",      "color": "#f9fafb", "label_en": "Free",      "label_kr": "빈 공간"},
    ]

    def _build_occupancy_grid(
        self,
        scene_id: str,
        *,
        cell_size: float,
        height_min: float,
        height_max: float,
    ) -> dict[str, Any]:
        """Project mesh AABBs onto an XZ grid for navigation planning.

        Returns the metadata dict + raw layer arrays. Both the JSON and PNG
        endpoints share this single source so the picture and the legend
        always agree.
        """
        diagram = self._scene_diagram_3d(scene_id)
        bounds = (diagram.get("summary") or {}).get("scene_bounds")
        if not bounds:
            return {"status": "unavailable", "scene_id": scene_id, "reason": diagram.get("reason") or "no_bounds"}
        cell_size = max(0.01, float(cell_size))
        x_min = float(bounds["min"][0]); z_min = float(bounds["min"][2])
        x_max = float(bounds["max"][0]); z_max = float(bounds["max"][2])
        width = max(1, int(np.ceil((x_max - x_min) / cell_size)))
        height = max(1, int(np.ceil((z_max - z_min) / cell_size)))
        # Layers: wall, glass, furniture (+ risk derived from glass dilation).
        wall = np.zeros((height, width), dtype=bool)
        glass = np.zeros((height, width), dtype=bool)
        furniture = np.zeros((height, width), dtype=bool)
        layer_for = {
            "shell": wall,
            "glass": glass,
            "furniture": furniture,
            "props": furniture,
            "other": furniture,
        }
        for obj in diagram.get("objects", []):
            cat = obj.get("category")
            target = layer_for.get(cat)
            if target is None:
                continue
            mn = obj["bounds"]["min"]; mx = obj["bounds"]["max"]
            # Filter to the robot collision band.
            if mx[1] < height_min or mn[1] > height_max:
                continue
            x0 = max(0, int(np.floor((mn[0] - x_min) / cell_size)))
            x1 = min(width, int(np.ceil((mx[0] - x_min) / cell_size)))
            z0 = max(0, int(np.floor((mn[2] - z_min) / cell_size)))
            z1 = min(height, int(np.ceil((mx[2] - z_min) / cell_size)))
            if x0 >= x1 or z0 >= z1:
                continue
            target[z0:z1, x0:x1] = True
        # Risk zone = glass dilated by 0.3m, minus the glass itself.
        risk_radius_cells = max(1, int(round(0.3 / cell_size)))
        if glass.any():
            # Cheap manual dilation via numpy slicing — avoids scipy dependency.
            dilated = glass.copy()
            for shift in range(1, risk_radius_cells + 1):
                dilated[shift:, :] |= glass[:-shift, :]
                dilated[:-shift, :] |= glass[shift:, :]
                dilated[:, shift:] |= glass[:, :-shift]
                dilated[:, :-shift] |= glass[:, shift:]
            risk = dilated & ~glass
        else:
            risk = np.zeros_like(glass)
        return {
            "status": "ready",
            "scene_id": scene_id,
            "cell_size": cell_size,
            "height_min": height_min,
            "height_max": height_max,
            "width": width,
            "height": height,
            "bounds_xz": {"min": [x_min, z_min], "max": [x_max, z_max]},
            "scene_bounds": bounds,
            "robots": diagram.get("robots", []),
            "rooms": diagram.get("rooms", []),
            "_layers": {"wall": wall, "glass": glass, "furniture": furniture, "risk": risk},
        }

    def _render_occupancy_png(self, layers: Mapping[str, np.ndarray], *, show_furniture: bool = True) -> bytes:
        from PIL import Image as _PILImage
        # Composite color map (RGB).
        wall = layers["wall"]; glass = layers["glass"]; risk = layers["risk"]; furniture = layers["furniture"]
        h, w = wall.shape
        rgb = np.full((h, w, 3), 0xF9, dtype=np.uint8)  # free = #f9fafb
        rgb[..., 1] = 0xFA; rgb[..., 2] = 0xFB
        if show_furniture:
            rgb[furniture] = (0x9C, 0xA3, 0xAF)
        rgb[risk] = (0xF9, 0x73, 0x16)
        rgb[glass] = (0x06, 0xB6, 0xD4)
        rgb[wall] = (0x1F, 0x29, 0x37)
        # Light grid every 1m
        cell_idx_per_meter = max(1, int(round(1.0 / 0.05)))  # tuned alongside default cell_size
        # PIL expects rows from top: our z axis grows downward already (z_min at top row 0).
        img = _PILImage.fromarray(rgb, mode="RGB")
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _scene_occupancy_map(
        self,
        scene_id: str,
        *,
        cell_size: float,
        height_min: float,
        height_max: float,
        show_furniture: bool = True,
    ) -> dict[str, Any]:
        grid = self._build_occupancy_grid(
            scene_id, cell_size=cell_size, height_min=height_min, height_max=height_max,
        )
        if grid.get("status") != "ready":
            return {"scene_id": scene_id, "status": grid.get("status", "unavailable"), "reason": grid.get("reason")}
        # Strip raw arrays from public payload — they're only for the PNG path.
        layers = grid.pop("_layers")
        png = self._render_occupancy_png(layers, show_furniture=show_furniture)
        params = f"cell_size={cell_size}&height_min={height_min}&height_max={height_max}&furniture={1 if show_furniture else 0}"
        grid["composite_png_url"] = f"/api/scenes/{quote(scene_id, safe='')}/occupancy-map.png?{params}"
        grid["composite_png_bytes"] = len(png)
        grid["legend"] = list(self._OCCUPANCY_LEGEND)
        return grid

    def _object_overlays_from_session(self, session: _IsaacActiveSession, *, metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
        world_bounds = metadata.get("world_bounds_xz")
        projection = metadata.get("projection")
        canvas_size = int(metadata.get("canvas_size_px") or 512)
        if not isinstance(world_bounds, Mapping) or not isinstance(projection, Mapping):
            return []
        try:
            x_min = float(world_bounds["x_min"])
            z_max = float(world_bounds["z_max"])
            scale = float(projection["scale_px_per_world_unit"])
            pad_x = float(projection["pad_x"])
            pad_z = float(projection["pad_z"])
        except Exception:
            return []

        overlays: list[dict[str, Any]] = []
        inventory_by_path = {
            str(item["path"]): item
            for item in self._session_object_inventory(session)
            if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        }
        for prim_path, object_state in sorted(session.objects.items()):
            translation = _object_transform_translation(object_state.transform)
            if translation is None:
                continue
            tx, _ty, tz = translation
            px = ((tx - x_min) * scale + pad_x)
            py = ((z_max - tz) * scale + pad_z)
            node = inventory_by_path.get(prim_path, {})
            overlays.append(
                {
                    "path": prim_path,
                    "label": node.get("name") or prim_path.rsplit("/", 1)[-1] or prim_path,
                    "kind": node.get("kind") or "object",
                    "selected": prim_path in session.selected_prim_paths,
                    "override_bsdf": node.get("override_bsdf"),
                    "centroid_world": [float(tx), float(tz)],
                    "centroid_px": [float(px), float(py)],
                    "canvas_size_px": canvas_size,
                }
            )
        return overlays

    def _robot_overlays_from_session(self, session: _IsaacActiveSession, *, metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
        world_bounds = metadata.get("world_bounds_xz")
        projection = metadata.get("projection")
        canvas_size = int(metadata.get("canvas_size_px") or 512)
        if not isinstance(world_bounds, Mapping) or not isinstance(projection, Mapping):
            return []
        try:
            x_min = float(world_bounds["x_min"])
            z_max = float(world_bounds["z_max"])
            scale = float(projection["scale_px_per_world_unit"])
            pad_x = float(projection["pad_x"])
            pad_z = float(projection["pad_z"])
        except Exception:
            return []

        overlays: list[dict[str, Any]] = []
        for robot in self._session_robot_inventory(session):
            translation = robot.get("translation")
            if not isinstance(translation, list) or len(translation) < 3:
                continue
            tx, _ty, tz = float(translation[0]), float(translation[1]), float(translation[2])
            px = ((tx - x_min) * scale + pad_x)
            py = ((z_max - tz) * scale + pad_z)
            overlays.append(
                {
                    "path": robot["path"],
                    "label": robot["label"],
                    "selected": bool(robot.get("selected")),
                    "centroid_world": [tx, tz],
                    "centroid_px": [float(px), float(py)],
                    "canvas_size_px": canvas_size,
                    "member_count": int(robot.get("member_count") or 0),
                    "shape_count": int(robot.get("shape_count") or 0),
                    "override_count": int(robot.get("override_count") or 0),
                }
            )
        return overlays

    def _camera_overlay_from_spec(self, camera: Mapping[str, Any], *, request: bool) -> CameraOverlay | None:
        if "camera_to_world" in camera:
            try:
                origin, target, _up = camera_to_world_to_lookat(camera["camera_to_world"])
                return CameraOverlay(
                    label=str(camera.get("camera_id") or camera.get("name") or "camera"),
                    origin=origin.tolist(),
                    target=target.tolist(),
                    fov_deg=float(camera.get("fov_deg") or 60.0),
                    color=(230, 126, 34) if request else (46, 134, 193),
                    fill_rgba=(230, 126, 34, 48) if request else None,
                )
            except Exception:
                return None

        look_at = camera.get("look_at")
        if isinstance(look_at, Mapping):
            origin = look_at.get("origin")
            target = look_at.get("target")
            if isinstance(origin, list) and isinstance(target, list):
                return CameraOverlay(
                    label=str(camera.get("camera_id") or camera.get("name") or "camera"),
                    origin=origin,
                    target=target,
                    fov_deg=float(camera.get("fov_deg") or 60.0),
                    color=(46, 134, 193),
                    fill_rgba=None,
                )
        return None

    def _light_overlay_from_payload(self, payload: Mapping[str, Any]) -> LightOverlay | None:
        look_at = payload.get("look_at")
        if isinstance(look_at, Mapping) and isinstance(look_at.get("origin"), list):
            position = look_at["origin"]
        else:
            position = self._extract_translation(payload.get("transform"))
        if not isinstance(position, list):
            return None
        return LightOverlay(label=str(payload.get("light_id") or payload.get("name") or "light"), position=position)

    def _ensure_floorplan(self, scene_id: str, *, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = detail or self._scene_detail(scene_id)
        scene_record = detail["scene"]
        latest_capture = detail["latest_capture"]
        if scene_record is None:
            return {
                "scene_id": scene_id,
                "artifact_path": None,
                "artifact_href": None,
                "request_camera_count": 0,
                "snapshot_camera_count": 0,
                "snapshot_light_count": 0,
                "camera_overlays": [],
                "object_overlays": [],
            }

        scene_path = resolve_repo_path(self.repo_root, scene_record["mitsuba_scene_ref"])
        if not scene_path.exists():
            return {
                "scene_id": scene_id,
                "artifact_path": None,
                "artifact_href": None,
                "error": f"Scene ref does not exist: {scene_record['mitsuba_scene_ref']}",
                "request_camera_count": 0,
                "snapshot_camera_count": 0,
                "snapshot_light_count": 0,
                "camera_overlays": [],
                "object_overlays": [],
            }

        request = self._load_saved_request(latest_capture["job_id"], latest_capture["frame_id"]) if latest_capture is not None else None
        request_cameras: list[CameraOverlay] = []
        if request is not None:
            for camera in request.camera_specs:
                overlay = self._camera_overlay_from_spec(
                    {
                        "camera_id": camera.camera_id,
                        "name": camera.name,
                        "camera_to_world": camera.camera_to_world,
                        "fov_deg": camera.fov_deg,
                    },
                    request=True,
                )
                if overlay is not None:
                    request_cameras.append(overlay)

        _snapshot, cameras_payload, lights_payload = self._load_snapshot_sidecars(scene_record.get("scene_snapshot_ref"))
        snapshot_cameras: list[CameraOverlay] = []
        snapshot_lights: list[LightOverlay] = []
        for camera_payload in cameras_payload:
            overlay = self._camera_overlay_from_spec(camera_payload, request=False)
            if overlay is not None:
                snapshot_cameras.append(overlay)
        for light_payload in lights_payload:
            overlay = self._light_overlay_from_payload(light_payload)
            if overlay is not None:
                snapshot_lights.append(overlay)

        cache_dir = self.repo_root / "out" / "control_plane_cache" / "floorplans"
        cache_dir.mkdir(parents=True, exist_ok=True)
        image_path = cache_dir / f"{scene_id}.png"
        metadata_path = cache_dir / f"{scene_id}.json"
        image_rel = to_repo_relative_posix(self.repo_root, image_path)
        metadata_rel = to_repo_relative_posix(self.repo_root, metadata_path)
        expected_cache_key = {
            "floorplan_version": 2,
            "scene_id": scene_id,
            "latest_capture_job_id": latest_capture["job_id"] if latest_capture is not None else None,
            "latest_capture_frame_id": latest_capture["frame_id"] if latest_capture is not None else None,
            "scene_ref": scene_record["mitsuba_scene_ref"],
            "scene_snapshot_ref": scene_record.get("scene_snapshot_ref"),
            "request_camera_count": len(request_cameras),
            "snapshot_camera_count": len(snapshot_cameras),
            "snapshot_light_count": len(snapshot_lights),
        }
        def _response_payload(*, cached: bool) -> dict[str, Any]:
            try:
                metadata = _read_json(metadata_path) if metadata_path.exists() else {}
            except Exception:
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            camera_overlays = [self._camera_overlay_payload(camera, kind="request") for camera in request_cameras]
            camera_overlays.extend(self._camera_overlay_payload(camera, kind="snapshot") for camera in snapshot_cameras)
            session = self._isaac_session if self._isaac_session and self._isaac_session.scene_id == scene_id else None
            active_camera = self._active_viewport_camera_payload(session) if session is not None else None
            if active_camera is not None:
                camera_overlays.insert(
                    0,
                    {
                        "camera_id": active_camera["sensor_id"],
                        "label": active_camera.get("name") or active_camera["sensor_id"],
                        "origin": list(active_camera["origin"]),
                        "target": list(active_camera["target"]),
                        "fov_deg": float(active_camera["fov_deg"]),
                        "kind": "active_viewport",
                        "color": [47, 123, 246],
                    },
                )
            object_overlays = self._object_overlays_from_session(session, metadata=metadata) if session is not None else []
            robot_overlays = self._robot_overlays_from_session(session, metadata=metadata) if session is not None else []
            return {
                "scene_id": scene_id,
                "artifact_path": image_rel,
                "artifact_href": self._artifact_href(image_rel),
                "metadata_path": metadata_rel,
                "metadata_href": self._artifact_href(metadata_rel),
                "request_camera_count": len(request_cameras),
                "snapshot_camera_count": len(snapshot_cameras),
                "snapshot_light_count": len(snapshot_lights),
                "cached": cached,
                "canvas_size_px": metadata.get("canvas_size_px"),
                "world_bounds_xz": metadata.get("world_bounds_xz"),
                "projection": metadata.get("projection"),
                "camera_overlays": camera_overlays,
                "object_overlays": object_overlays,
                "robot_overlays": robot_overlays,
                "active_viewport_camera": active_camera,
            }

        if image_path.exists() and metadata_path.exists():
            try:
                cached_metadata = _read_json(metadata_path)
            except Exception:
                cached_metadata = None
            if isinstance(cached_metadata, dict):
                cache_key = cached_metadata.get("cache_key")
                if isinstance(cache_key, Mapping) and all(cache_key.get(key) == value for key, value in expected_cache_key.items()):
                    return _response_payload(cached=True)
                return _response_payload(cached=True)
        context_points_xz: list[list[float]] = []
        for camera in request_cameras:
            context_points_xz.append([float(camera.origin[0]), float(camera.origin[2])])
            context_points_xz.append([float(camera.target[0]), float(camera.target[2])])
        for camera in snapshot_cameras:
            context_points_xz.append([float(camera.origin[0]), float(camera.origin[2])])
            context_points_xz.append([float(camera.target[0]), float(camera.target[2])])
        session = self._isaac_session if self._isaac_session and self._isaac_session.scene_id == scene_id else None
        active_camera = self._active_viewport_camera_payload(session) if session is not None else None
        if active_camera is not None:
            context_points_xz.append([float(active_camera["origin"][0]), float(active_camera["origin"][2])])
            context_points_xz.append([float(active_camera["target"][0]), float(active_camera["target"][2])])
        render_scene_floorplan(
            scene_path=scene_path,
            output_path=image_path,
            metadata_path=metadata_path,
            request_cameras=request_cameras,
            snapshot_cameras=snapshot_cameras,
            snapshot_lights=snapshot_lights,
            context_points_xz=context_points_xz,
            title=f"{scene_id} floorplan",
        )
        try:
            raw_metadata = _read_json(metadata_path) if metadata_path.exists() else {}
        except Exception:
            raw_metadata = {}
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        raw_metadata["cache_key"] = expected_cache_key
        metadata_path.write_text(json.dumps(raw_metadata, indent=2), encoding="utf-8")
        return _response_payload(cached=False)


def serve_render_daemon(
    *,
    repo_root: str | Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    variant: str = "auto",
) -> RenderDaemon:
    daemon = RenderDaemon(repo_root=repo_root, host=host, port=port, variant=variant)
    daemon.start()
    return daemon
