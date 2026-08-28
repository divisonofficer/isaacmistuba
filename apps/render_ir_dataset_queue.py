#!/usr/bin/env python3
"""Render a shuffled, resumable inverse-rendering dataset.

Rolling workers publish into run-global modality directories.  Legacy chunked
workers retain their bounded per-chunk artifact layout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue as thread_queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
for _module in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / _module / "src"))
from mitsuba_converter.material_pipeline import (  # noqa: E402
    OPAQUE_PBR_DOMAIN,
    SPECULAR_MASKED_PBR_DOMAIN,
    STRUCTURAL_SPECULAR_PBR_DOMAIN,
    SUPPORTED_SURFACE_DOMAINS,
    uses_specular_semantic_masks,
    materialize_ir_effective_scene,
    validate_ir_effective_scene,
)

RENDER_APP = REPO_ROOT / "apps" / "render_ir_dataset.py"
GEOMETRY_PROFILE_BUILDER = REPO_ROOT / "apps" / "build_ir_geometry_profile.py"
BLENDER_LAUNCHER = REPO_ROOT / "tools" / "infinigen" / "run_bundled_blender.py"
BLENDER_GT_SCRIPT = REPO_ROOT / "tools" / "infinigen" / "blender_render_kitchen_gt_aov.py"
ASSEMBLE_APP = REPO_ROOT / "apps" / "assemble_ir_dataset.py"
REQUIRED_OBSERVATIONS = {
    "rgb", "rgb_png", "nir_ambient", "nir_flash_direct", "nir_active", "nir_dflash",
}
POLAR_OBSERVATIONS = {"dop", "aolp"}
REQUIRED_GT = {
    "rgb_albedo", "nir_albedo", "roughness_perceptual", "metallic", "depth", "range",
    "normal_geometry_world", "normal_shading_world", "normal_tangent",
}
REQUIRED_MASKS = {"material_id", "object_id", "valid_mask", "replacement_mask"}
SPECULAR_MASKS = {"window_glass", "object_glass", "glass", "mirror"}


def _scene_content_sha256(scene_dir: Path) -> str:
    """Hash every scene input by relative path and bytes for stale-output rejection."""
    digest = hashlib.sha256()
    root = scene_dir.resolve()
    for path in sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".prop_")
    ):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(value, encoding="utf-8")
    temp.replace(path)


def _frame_specs(graph: dict, seed: int) -> list[str]:
    specs = [
        f"{node['node_id']}@{float(heading['yaw_deg']):g}"
        for node in graph["nodes"]
        for heading in node.get("headings", [])
    ]
    random.Random(int(seed)).shuffle(specs)
    return specs


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[start:start + size] for start in range(0, len(values), size)]


def _load_rows(index_path: Path) -> list[dict]:
    if not index_path.is_file():
        return []
    return [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _chunk_complete(
    chunk_dir: Path, expected: int, *, observations_only: bool = False, polarized: bool = False,
    surface_domain: str = "all",
) -> bool:
    rows = _load_rows(chunk_dir / "index.jsonl")
    if len(rows) != int(expected):
        return False
    for row in rows:
        required_observations = REQUIRED_OBSERVATIONS | (POLAR_OBSERVATIONS if polarized else set())
        if not required_observations <= set(row.get("observation_paths") or {}):
            return False
        if not observations_only and not REQUIRED_GT <= set(row.get("gt_paths") or {}):
            return False
        if not observations_only:
            required_masks = REQUIRED_MASKS | (SPECULAR_MASKS if uses_specular_semantic_masks(surface_domain) else set())
            if not required_masks <= set(row.get("mask_paths") or {}):
                return False
        paths = list((row.get("observation_paths") or {}).values())
        if not observations_only:
            paths += list((row.get("gt_paths") or {}).values())
        paths += list((row.get("mask_paths") or {}).values())
        if not paths or any(not Path(path).is_file() for path in paths):
            return False
    return True


def _read_exr(path: Path) -> np.ndarray:
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read EXR: {path}")
    if value.ndim == 3 and value.shape[2] == 3:
        value = value[..., ::-1]
    return np.asarray(value, np.float32)


def _write_rgb_png(exr_path: Path, png_path: Path, exposure: float) -> None:
    linear = np.maximum(_read_exr(exr_path)[..., :3] * float(exposure), 0.0)
    mapped = linear / (1.0 + linear)
    srgb = np.where(mapped <= 0.0031308, mapped * 12.92,
                    1.055 * np.power(mapped, 1.0 / 2.4) - 0.055)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.rint(np.clip(srgb, 0, 1) * 255).astype(np.uint8)).save(png_path)


def _postprocess_chunk(chunk_dir: Path, exposure: float) -> list[dict]:
    rows = _load_rows(chunk_dir / "index.jsonl")
    for row in rows:
        frame_dir = chunk_dir / row["frame_id"]
        png_path = frame_dir / "rgb.png"
        _write_rgb_png(Path(row["observation_paths"]["rgb"]), png_path, exposure)
        row["observation_paths"]["rgb_png"] = str(png_path.resolve())
        row.setdefault("render_config", {})["rgb_png_tonemap"] = {
            "operator": "reinhard", "exposure": float(exposure),
            "transfer": "srgb", "bit_depth": 8,
        }
        _atomic_json(frame_dir / "frame.json", row)
    _atomic_text(
        chunk_dir / "index.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
    )
    return rows


def _relocate_row_paths(row: dict, source_dir: Path, target_dir: Path) -> dict:
    """Rewrite absolute render paths after merging a bounded subprocess batch."""
    source = str(source_dir.resolve())
    target = str(target_dir.resolve())

    def relocate(value: object) -> object:
        if isinstance(value, str) and (value == source or value.startswith(source + os.sep)):
            return target + value[len(source):]
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return value

    return relocate(row)  # type: ignore[return-value]


def _rotation_to_qvec(rotation: np.ndarray) -> np.ndarray:
    """COLMAP Hamilton quaternion (qw, qx, qy, qz) from a world-to-camera R."""
    r = np.asarray(rotation, np.float64).reshape(3, 3)
    trace = float(np.trace(r))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        q = np.asarray([0.25 * s, (r[2, 1] - r[1, 2]) / s,
                        (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s])
    else:
        i = int(np.argmax(np.diag(r)))
        if i == 0:
            s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
            q = np.asarray([(r[2, 1] - r[1, 2]) / s, 0.25 * s,
                            (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s])
        elif i == 1:
            s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
            q = np.asarray([(r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s,
                            0.25 * s, (r[1, 2] + r[2, 1]) / s])
        else:
            s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
            q = np.asarray([(r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s,
                            (r[1, 2] + r[2, 1]) / s, 0.25 * s])
    q /= np.linalg.norm(q)
    return -q if q[0] < 0 else q


def _colmap_export(out: Path, rows: list[dict]) -> None:
    model = out / "colmap" / "sparse" / "0"
    model.mkdir(parents=True, exist_ok=True)
    if not rows:
        _atomic_text(model / "cameras.txt", "")
        _atomic_text(model / "images.txt", "")
        _atomic_text(model / "points3D.txt", "")
        return
    intrinsics = rows[0]["intrinsics"]
    camera_lines = [
        "# Camera list with one line of data per camera:",
        "# CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]",
        f"# Number of cameras: 1",
        (f"1 PINHOLE {intrinsics['width']} {intrinsics['height']} "
         f"{intrinsics['fx']:.12g} {intrinsics['fy']:.12g} "
         f"{intrinsics['cx']:.12g} {intrinsics['cy']:.12g}"),
    ]
    image_lines = [
        "# Image list with two lines of data per image:",
        "# IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME",
        "# POINTS2D[] as (X, Y, POINT3D_ID)",
        f"# Number of images: {len(rows)}, mean observations per image: 0",
    ]
    for image_id, row in enumerate(rows, 1):
        world_to_camera = np.asarray(row["extrinsics"]["world_to_camera_colmap"], np.float64)
        q = _rotation_to_qvec(world_to_camera[:3, :3])
        t = world_to_camera[:3, 3]
        png = Path(row["observation_paths"]["rgb_png"]).resolve()
        name = png.relative_to(out.resolve()).as_posix()
        image_lines.append(
            f"{image_id} {' '.join(f'{v:.12g}' for v in q)} "
            f"{' '.join(f'{v:.12g}' for v in t)} 1 {name}"
        )
        image_lines.append("")
    points_lines = [
        "# 3D point list with one line of data per point:",
        "# POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)",
        "# Number of points: 0, mean track length: 0",
    ]
    _atomic_text(model / "cameras.txt", "\n".join(camera_lines) + "\n")
    _atomic_text(model / "images.txt", "\n".join(image_lines) + "\n")
    _atomic_text(model / "points3D.txt", "\n".join(points_lines) + "\n")


_AUDIT_CONTRACT_KEYS = (
    "schema", "surface_domain", "effective_scene_digest", "shape_count", "bsdf_types",
    "texture_types", "texture_parameters", "normalmap_wrapper_count",
    "measured_polarized_bsdf_count", "polarized_render_requested", "renderer_runtime",
    "observation_mitsuba_variant", "geometry", "specular_semantics",
    "texture_policy", "observation_sampling",
)


def _load_render_input_audit(
    source_dir: Path, *, effective_scene_digest: str, polarized: bool,
) -> dict[str, Any]:
    """Load and verify renderer input provenance before publishing it anywhere."""
    source = source_dir / "render_input_audit.json"
    if not source.is_file():
        raise RuntimeError(f"render batch did not emit input audit: {source_dir}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("effective_scene_digest") != effective_scene_digest:
        raise RuntimeError("render batch input audit effective-scene digest mismatch")
    if bool(payload.get("polarized_render_requested")) != bool(polarized):
        raise RuntimeError("render batch input audit polar mode mismatch")
    return payload


def _assert_matching_input_audits(prior: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in _AUDIT_CONTRACT_KEYS:
        if prior.get(key) != payload.get(key):
            raise RuntimeError(f"render batch input audit differs at {key}")


def _record_chunk_render_input_audit(
    chunk_dir: Path, batch_dir: Path, *, effective_scene_digest: str, polarized: bool,
) -> None:
    """Preserve a validated audit before deleting a worker's scratch batch."""
    payload = _load_render_input_audit(
        batch_dir, effective_scene_digest=effective_scene_digest, polarized=polarized,
    )
    target = chunk_dir / "render_input_audit.json"
    if target.is_file():
        _assert_matching_input_audits(json.loads(target.read_text(encoding="utf-8")), payload)
        return
    _atomic_json(target, payload)


def _adopt_render_input_audit(
    out: Path, source_dir: Path, *, effective_scene_digest: str, polarized: bool,
) -> None:
    """Promote immutable input provenance from a completed chunk to the run root."""
    payload = _load_render_input_audit(
        source_dir, effective_scene_digest=effective_scene_digest, polarized=polarized,
    )
    target = out / "render_input_audit.json"
    if target.is_file():
        _assert_matching_input_audits(json.loads(target.read_text(encoding="utf-8")), payload)
        return
    _atomic_json(target, payload)


def _refresh_global_exports(out: Path, manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for chunk in manifest["chunks"]:
        if chunk["status"] == "complete":
            rows.extend(_load_rows(out / chunk["relative_dir"] / "index.jsonl"))
    _atomic_text(out / "index.jsonl",
                 "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _colmap_export(out, rows)
    return rows


class _ChunkRenderFailed(RuntimeError):
    """A bounded renderer subprocess failed; its completed prefix remains resumable."""

    def __init__(self, chunk_id: int, returncode: int, message: str) -> None:
        super().__init__(message)
        self.chunk_id = int(chunk_id)
        self.returncode = int(returncode)


_ROLLING_STATE_SCHEMA = "robomituba.ir_rolling_queue_state.v2"
_ROLLING_STORAGE_LAYOUT = "modality_first_v1"


def _frame_id_from_spec(spec: str) -> str:
    """Return the stable artifact name for a queued ``node_id@heading`` spec."""
    node_id, separator, heading_text = str(spec).partition("@")
    if not separator or not node_id:
        raise ValueError(f"invalid viewpoint spec: {spec!r}")
    return f"{node_id}__h_{int(round(float(heading_text))) % 360:03d}"


def _rolling_state_path(out: Path) -> Path:
    return out / "rolling_queue_state.json"


def _new_rolling_state(manifest: dict) -> dict[str, Any]:
    """Create frame-granular state while retaining the v2 chunk manifest identity."""
    frames: dict[str, dict[str, Any]] = {}
    order = 0
    for chunk in manifest["chunks"]:
        for spec in chunk["viewpoints"]:
            frame_id = _frame_id_from_spec(spec)
            if frame_id in frames:
                raise ValueError(f"duplicate rolling frame id: {frame_id}")
            frames[frame_id] = {
                "frame_id": frame_id, "viewpoint": str(spec), "chunk_id": int(chunk["chunk_id"]),
                "queue_order": order, "status": "pending", "attempts": 0,
            }
            order += 1
    return {
        "schema": _ROLLING_STATE_SCHEMA,
        "created_at": _utc_now(), "updated_at": _utc_now(), "phase": "passive",
        "contract": {
            "effective_scene_digest": manifest.get("effective_scene_digest"),
            "scene_content_sha256": manifest.get("scene_content_sha256"),
            "configuration": dict(manifest.get("configuration") or {}),
            "frame_count": int(manifest["frame_count"]),
        },
        "frames": frames, "workers": {}, "leases": {}, "phase_summary": {},
    }


def _load_or_create_rolling_state(out: Path, manifest: dict) -> dict[str, Any]:
    path = _rolling_state_path(out)
    expected = _new_rolling_state(manifest)
    if not path.is_file():
        return expected
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != _ROLLING_STATE_SCHEMA:
        raise RuntimeError(f"unsupported rolling queue state schema: {state.get('schema')!r}")
    if state.get("contract") != expected["contract"]:
        raise RuntimeError("rolling queue state does not match queue dataset contract")
    frames = state.get("frames")
    if not isinstance(frames, dict) or set(frames) != set(expected["frames"]):
        raise RuntimeError("rolling queue state does not match manifest frame set")
    state.setdefault("workers", {})
    state.setdefault("leases", {})
    state.setdefault("phase_summary", {})
    return state


def _persist_rolling_state(out: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = _utc_now()
    _atomic_json(_rolling_state_path(out), state)


def _row_has_observations(row: dict, *, polarized: bool, require_rgb_png: bool = True) -> bool:
    required = REQUIRED_OBSERVATIONS | (POLAR_OBSERVATIONS if polarized else set())
    if not require_rgb_png:
        required = required - {"rgb_png"}
    paths = row.get("observation_paths") or {}
    if not required <= set(paths):
        return False
    return all(Path(str(paths[name])).is_file() for name in required)


def _row_matches_rolling_contract(row: dict, args: argparse.Namespace) -> bool:
    if row.get("effective_scene_digest") != args.effective_scene_digest:
        return False
    config = row.get("render_config") or {}
    samples = config.get("observation_spp_by_pass") or {}
    if samples != {
        "rgb": int(args.rgb_spp), "nir_ambient": int(args.nir_ambient_spp),
        "nir_flash_direct": int(args.nir_direct_spp),
    }:
        return False
    return int(config.get("max_depth", -999)) == int(args.max_depth)


def _rolling_frame_entries(state: dict[str, Any], status: str) -> list[dict[str, Any]]:
    return sorted(
        (entry for entry in state["frames"].values() if entry.get("status") == status),
        key=lambda entry: int(entry["queue_order"]),
    )


def _recover_orphaned_rolling_leases(state: dict[str, Any]) -> list[str]:
    """Return frames left in-flight by a stopped parent to a safe queue state.

    A worker owns a lease only while its parent is alive.  On a fresh queue
    invocation there is no live worker behind an on-disk ``leased`` entry, so
    retaining it would silently strand the frame forever.  Worker staging is
    inspected first by :func:`_rolling_record_existing_frames`; consequently
    only entries with no validated staged result reach this recovery path.

    A direct lease without a publishable final frame must repeat the passive
    phase as well: the direct worker is not allowed to manufacture an ambient
    record.  This is deliberately conservative and avoids treating an
    interrupted write as a valid observation.
    """
    recovered: list[str] = []
    for frame_id, entry in state["frames"].items():
        if entry.get("status") != "leased":
            continue
        lease_id = entry.pop("lease_id", None)
        prior_phase = str(entry.get("phase") or "passive")
        entry.pop("worker_gpu_index", None)
        entry["status"] = "pending"
        entry["recovered_from_orphaned_lease"] = {
            "lease_id": lease_id,
            "phase": prior_phase,
            "recovered_at": _utc_now(),
        }
        recovered.append(frame_id)
        if lease_id and isinstance(state.get("leases", {}).get(lease_id), dict):
            state["leases"][lease_id].update({
                "status": "interrupted", "recovered_at": _utc_now(),
                "recovery_reason": "parent_restart_without_valid_staging",
            })
    if recovered:
        # Pending passive work is always the safe common denominator, even if
        # the interrupted worker had entered the direct phase.
        state["phase"] = "passive"
    return recovered


def _rolling_incomplete_status_counts(state: dict[str, Any]) -> dict[str, int]:
    """Count non-terminal frame states for scheduler completion decisions."""
    counts: dict[str, int] = {}
    for entry in state["frames"].values():
        status = str(entry.get("status") or "unknown")
        if status not in {"complete", "failed", "deferred"}:
            counts[status] = counts.get(status, 0) + 1
    return counts


def _rolling_phase_incomplete_status_counts(
    state: dict[str, Any], phase: str,
) -> dict[str, int]:
    """Count states that are unfinished for the requested rolling phase.

    ``passive_complete`` is the expected terminal state of the passive phase,
    but remains non-terminal for the full two-phase scheduler.  Keep the
    run-global counter strict while excluding that hand-off state only at the
    passive/direct phase boundary.
    """
    counts = _rolling_incomplete_status_counts(state)
    if phase == "passive":
        counts.pop("passive_complete", None)
    return counts


def _rolling_record_existing_frames(
    args: argparse.Namespace, manifest: dict, state: dict[str, Any],
) -> None:
    """Adopt only fully validated v2 frames; never trust incomplete batch scratch."""
    by_id = state["frames"]
    # Native rolling layout has one global index and modality directories;
    # chunks are scheduling/progress groups only.
    for row in _load_rows(args.out / "index.jsonl"):
        frame_id = str(row.get("frame_id") or "")
        entry = by_id.get(frame_id)
        if entry is None or not _row_matches_rolling_contract(row, args):
            continue
        if _row_has_observations(row, polarized=bool(args.polar)):
            entry.update({
                "status": "complete", "published_at": entry.get("published_at") or _utc_now(),
                "adopted_from": _ROLLING_STORAGE_LAYOUT, "row": row,
            })
    # Read legacy v2 chunk output as a one-way resume compatibility path.
    for chunk in manifest["chunks"]:
        chunk_dir = args.out / chunk["relative_dir"]
        for row in _load_rows(chunk_dir / "index.jsonl"):
            frame_id = str(row.get("frame_id") or "")
            entry = by_id.get(frame_id)
            if entry is None or not _row_matches_rolling_contract(row, args):
                continue
            if _row_has_observations(row, polarized=bool(args.polar)):
                entry.update({
                    "status": "complete", "published_at": entry.get("published_at") or _utc_now(),
                    "adopted_from": "v2_chunk", "row": row,
                })
    # A previous rolling parent may have crashed between atomic worker staging
    # and parent publication.  Complete staging is publishable; passive-only
    # staging is re-used by the later flash phase.
    staging_root = args.out / ".rolling_frames"
    for frame_id, entry in by_id.items():
        if entry.get("status") == "complete":
            continue
        frame_dir = staging_root / frame_id
        frame_json = frame_dir / "frame.json"
        passive_json = frame_dir / "passive.json"
        if frame_json.is_file():
            try:
                row = json.loads(frame_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if _row_matches_rolling_contract(row, args) and _row_has_observations(
                row, polarized=bool(args.polar), require_rgb_png=False,
            ):
                entry.update({"status": "staged_complete", "row": row, "adopted_from": "rolling_staging"})
        elif passive_json.is_file():
            try:
                passive = json.loads(passive_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            expected = {
                "rgb": int(args.rgb_spp), "nir_ambient": int(args.nir_ambient_spp),
                "nir_flash_direct": int(args.nir_direct_spp),
            }
            paths = passive.get("observation_paths") or {}
            if (
                passive.get("effective_scene_digest") == args.effective_scene_digest
                and ((passive.get("render_config") or {}).get("observation_spp_by_pass") == expected)
                and all(Path(str(paths.get(name, ""))).is_file() for name in ("rgb", "nir_ambient"))
            ):
                entry.update({"status": "passive_complete", "adopted_from": "rolling_passive"})


def _rolling_update_chunk_status(manifest: dict, state: dict[str, Any]) -> None:
    by_chunk: dict[int, list[dict[str, Any]]] = {}
    for entry in state["frames"].values():
        by_chunk.setdefault(int(entry["chunk_id"]), []).append(entry)
    for chunk in manifest["chunks"]:
        entries = by_chunk[int(chunk["chunk_id"])]
        if all(entry.get("status") == "complete" for entry in entries):
            chunk["status"] = "complete"
            chunk["observation_completed_at"] = chunk.get("observation_completed_at") or _utc_now()
        elif chunk.get("status") == "running":
            chunk["status"] = "pending"


def _refresh_rolling_global_exports(out: Path, manifest: dict, state: dict[str, Any]) -> list[dict]:
    rows = [
        entry["row"] for entry in sorted(
            state["frames"].values(), key=lambda item: int(item["queue_order"]),
        )
        if entry.get("status") == "complete" and isinstance(entry.get("row"), dict)
    ]
    _atomic_text(out / "index.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _colmap_export(out, rows)
    return rows


def _write_rolling_report(out: Path, manifest: dict, state: dict[str, Any]) -> None:
    """Small final/progress report without scanning image artifacts again."""
    status_counts: dict[str, int] = {}
    timings: dict[str, list[float]] = {}
    for entry in state["frames"].values():
        status = str(entry.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        for pass_name, timing in (entry.get("timings") or {}).items():
            if isinstance(timing, dict) and "mi_render_s" in timing:
                timings.setdefault(str(pass_name), []).append(float(timing["mi_render_s"]))
    payload = {
        "schema": "robomituba.ir_rolling_queue_report.v1", "generated_at": _utc_now(),
        "effective_scene_digest": manifest.get("effective_scene_digest"),
        "sampling": {
            key: (manifest.get("configuration") or {}).get(key)
            for key in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp", "max_depth")
        },
        "status_counts": status_counts, "phase_summary": state.get("phase_summary") or {},
        "render_timing_s": {
            name: {"frames": len(values), "total": round(sum(values), 6), "mean": round(sum(values) / len(values), 6)}
            for name, values in sorted(timings.items())
        },
    }
    _atomic_json(out / "rolling_queue_report.json", payload)


def _rolling_modality_path(out: Path, modality: str, frame_id: str, suffix: str) -> Path:
    safe_modality = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(modality)).strip("._")
    if not safe_modality:
        raise ValueError(f"invalid rolling modality name: {modality!r}")
    return out / "observations" / safe_modality / f"{frame_id}{suffix}"


def _publish_rolling_frame(args: argparse.Namespace, manifest: dict, state: dict[str, Any], entry: dict[str, Any]) -> dict:
    """Publish one staged frame into run-global modality directories."""
    frame_id = str(entry["frame_id"])
    source = args.out / ".rolling_frames" / frame_id
    row_path = source / "frame.json"
    if not row_path.is_file():
        raise FileNotFoundError(f"rolling staged frame lacks frame.json: {frame_id}")
    row = json.loads(row_path.read_text(encoding="utf-8"))
    if not _row_matches_rolling_contract(row, args) or not _row_has_observations(
        row, polarized=bool(args.polar), require_rgb_png=False,
    ):
        raise RuntimeError(f"rolling staged frame contract invalid: {frame_id}")
    relocated = dict(row)
    relocated_paths: dict[str, str] = {}
    for modality, raw_path in dict(row.get("observation_paths") or {}).items():
        staged_path = Path(str(raw_path)).resolve()
        if not staged_path.is_file():
            raise FileNotFoundError(f"{frame_id}: staged {modality} artifact missing: {staged_path}")
        suffix = "".join(staged_path.suffixes) or ".exr"
        target = _rolling_modality_path(args.out, modality, frame_id, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.publish.tmp")
        temporary.unlink(missing_ok=True)
        try:
            # Staging and publication live below the same dataset root. A hard
            # link makes publication atomic without copying multi-megabyte EXRs.
            os.link(staged_path, temporary)
        except OSError:
            shutil.copy2(staged_path, temporary)
        os.replace(temporary, target)
        relocated_paths[str(modality)] = str(target.resolve())
    rgb_exr = Path(relocated_paths["rgb"])
    rgb_png = _rolling_modality_path(args.out, "rgb", frame_id, ".png")
    rgb_png_tmp = rgb_png.with_name(f".{frame_id}.publish.tmp.png")
    _write_rgb_png(rgb_exr, rgb_png_tmp, args.rgb_exposure)
    os.replace(rgb_png_tmp, rgb_png)
    relocated_paths["rgb_png"] = str(rgb_png.resolve())
    relocated["observation_paths"] = relocated_paths
    relocated.setdefault("render_config", {})["rgb_png_tonemap"] = {
        "operator": "reinhard", "exposure": float(args.rgb_exposure), "transfer": "srgb", "bit_depth": 8,
    }
    frame_path = args.out / "frames" / f"{frame_id}.json"
    relocated["frame_metadata_path"] = str(frame_path.resolve())
    relocated["storage_layout"] = _ROLLING_STORAGE_LAYOUT
    _atomic_json(frame_path, relocated)
    shutil.rmtree(source)
    entry.update({"status": "complete", "row": relocated, "published_at": _utc_now()})
    entry.pop("lease_id", None)
    _rolling_update_chunk_status(manifest, state)
    return relocated


class _RollingWorker:
    """One GPU-pinned JSON-lines renderer process and its stdout reader."""

    def __init__(self, args: argparse.Namespace, *, gpu_index: int, phase: str) -> None:
        self.args = args
        self.gpu_index = int(gpu_index)
        self.phase = str(phase)
        self.process: subprocess.Popen[str] | None = None
        self.messages: thread_queue.Queue[dict[str, Any]] = thread_queue.Queue()
        self._reader: threading.Thread | None = None
        self.busy_lease: dict[str, Any] | None = None
        self.scene_load_s: float | None = None
        self.audit_path: Path | None = None

    @property
    def work_root(self) -> Path:
        return self.args.out / "shared" / "rolling_workers" / f"gpu_{self.gpu_index}" / self.phase

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("rolling worker is already running")
        if self.work_root.exists():
            shutil.rmtree(self.work_root)
        local_nir = self.args.out / "shared" / f"nir_band_{self.args.band}" / f"gpu_{self.gpu_index}"
        command = [
            str(self.args.mitsuba_runtime_info["python"]), "-u", str(RENDER_APP),
            "--scene-dir", str(self.args.scene_dir), "--surface-domain", str(self.args.surface_domain),
            "--out", str(self.work_root), "--observations-only",
            "--worker-stdio", "--worker-phase", self.phase,
            "--rolling-staging-root", str(self.args.out / ".rolling_frames"),
            "--width", str(self.args.width), "--height", str(self.args.height), "--fov", str(self.args.fov),
            "--spp", str(self.args.spp), "--rgb-spp", str(self.args.rgb_spp),
            "--nir-ambient-spp", str(self.args.nir_ambient_spp),
            "--nir-direct-spp", str(self.args.nir_direct_spp), "--max-depth", str(self.args.max_depth),
            "--observation-variant", str(self.args.observation_variant), "--subpixel", str(self.args.subpixel),
            "--band", str(self.args.band), "--nir-cache-dir", str(local_nir),
            "--texture-max-resolution", str(self.args.texture_max_resolution),
            "--texture-cache-dir", str(self.args.texture_cache_dir),
            "--nir-flash-model", "spot", "--nir-flash-offset-y", "-0.10",
            "--nir-flash-beam-width", "22", "--nir-flash-cutoff-angle", "30",
            "--gpu-cleanup-interval", str(self.args.gpu_cleanup_interval),
        ]
        if self.args.polar:
            command.append("--polar")
        environment = _runtime_worker_env(self.gpu_index, self.args.mitsuba_runtime_info)
        environment["ROBOMITUBA_TEXTURE_MAX_RESOLUTION"] = str(self.args.texture_max_resolution)
        environment["ROBOMITUBA_TEXTURE_CACHE_DIR"] = str(self.args.texture_cache_dir)
        self.process = subprocess.Popen(
            command, cwd=REPO_ROOT, env=environment, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
        )

        def reader() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                text = line.rstrip()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    if text:
                        print(f"[rolling-worker gpu={self.gpu_index} {self.phase}] {text}", flush=True)
                    continue
                if isinstance(payload, dict) and payload.get("type"):
                    self.messages.put(payload)
                else:
                    print(f"[rolling-worker gpu={self.gpu_index} {self.phase}] {text}", flush=True)

        self._reader = threading.Thread(target=reader, name=f"ir-rolling-gpu{self.gpu_index}-{self.phase}", daemon=True)
        self._reader.start()

    def wait_ready(self, timeout_s: float = 300.0) -> dict[str, Any]:
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.25)
            except thread_queue.Empty:
                if self.process is None or self.process.poll() is not None:
                    raise RuntimeError(f"worker exited before ready (gpu={self.gpu_index}, phase={self.phase})")
                continue
            if message.get("type") == "ready":
                self.scene_load_s = float(message.get("scene_load_s", 0.0))
                self.audit_path = Path(str(message["audit_path"]))
                return message
            if message.get("type") == "fatal":
                raise RuntimeError(f"worker setup failed: {message.get('error')}")
        raise TimeoutError(f"worker setup timed out (gpu={self.gpu_index}, phase={self.phase})")

    def send_lease(self, lease: dict[str, Any]) -> None:
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise RuntimeError("cannot send a lease to a dead worker")
        self.process.stdin.write(json.dumps({
            "op": "render", "lease_id": lease["lease_id"], "viewpoints": lease["viewpoints"],
        }) + "\n")
        self.process.stdin.flush()
        self.busy_lease = lease

    def poll_message(self) -> dict[str, Any] | None:
        try:
            return self.messages.get_nowait()
        except thread_queue.Empty:
            return None

    def dead(self) -> bool:
        return self.process is None or self.process.poll() is not None

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=30)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                process.terminate()
        if process.poll() is None:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def _rolling_make_lease(entries: list[dict[str, Any]], phase: str) -> dict[str, Any]:
    return {
        "lease_id": f"lease_{phase}_{uuid.uuid4().hex[:16]}", "phase": phase,
        "frame_ids": [entry["frame_id"] for entry in entries],
        "viewpoints": [entry["viewpoint"] for entry in entries],
    }


def _rolling_timing_seconds(timings: dict[str, Any] | None, name: str) -> float:
    """Return wall time for one rendered modality, preferring full render timing."""
    value = (timings or {}).get(name) or {}
    for key in ("total_s", "mi_render_s"):
        try:
            return float(value[key])
        except (KeyError, TypeError, ValueError):
            continue
    return 0.0


def _rolling_frame_progress_line(
    state: dict[str, Any], *, phase: str, gpu: int, result: dict[str, Any], worker_wall_s: float | None,
) -> str:
    """Human-readable, per-frame rolling progress with pass-specific timing."""
    statuses = {"passive_complete", "complete"} if phase == "passive" else {"complete"}
    done = sum(1 for entry in state["frames"].values() if entry.get("status") in statuses)
    total = len(state["frames"])
    timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
    frame_id = str(result.get("frame_id", "unknown"))
    # Direct frames are only published after the enclosing lease succeeds, but
    # this event itself represents one newly finished frame for live progress.
    if phase != "passive" and state["frames"].get(frame_id, {}).get("status") not in statuses:
        done += 1
    if phase == "passive":
        rgb_s = _rolling_timing_seconds(timings, "rgb")
        ambient_s = _rolling_timing_seconds(timings, "nir_ambient")
        detail = f"rgb={rgb_s:.2f}s ambient={ambient_s:.2f}s passive={rgb_s + ambient_s:.2f}s"
    else:
        direct_s = _rolling_timing_seconds(timings, "nir_flash_direct")
        detail = f"nir_direct={direct_s:.2f}s"
    wall = f" frame_wall={float(worker_wall_s):.2f}s" if worker_wall_s is not None else ""
    return f"[rolling] frame {done}/{total} phase={phase} gpu={gpu} id={frame_id} {detail}{wall}"


def _rolling_requeue_failed_lease(
    state: dict[str, Any], lease: dict[str, Any], *, error: str,
) -> list[dict[str, Any]]:
    """Return eligible retry entries; a failed multi-frame lease is split once."""
    retry: list[dict[str, Any]] = []
    split = len(lease["frame_ids"]) > 1
    for frame_id in lease["frame_ids"]:
        entry = state["frames"][frame_id]
        entry.pop("lease_id", None)
        # A passive frame may have reached its atomic staging directory just
        # before the worker crashed.  Its parent received a frame_complete
        # event and has already recorded it, so preserve that completed work.
        if lease["phase"] == "passive" and entry.get("status") == "passive_complete":
            continue
        entry["last_error"] = str(error)
        entry["last_failed_at"] = _utc_now()
        if int(entry.get("attempts", 0)) >= 3:
            entry["status"] = "failed"
            entry["terminal_error"] = str(error)
        else:
            entry["status"] = "passive_complete" if lease["phase"] == "flash_direct" else "pending"
            entry["force_singleton"] = bool(split or entry.get("force_singleton", False))
            retry.append(entry)
    return retry


def _run_rolling_phase(args: argparse.Namespace, manifest: dict, state: dict[str, Any], phase: str) -> tuple[int, set[int]]:
    """Drain one global phase using dynamic leases and persistent GPU scenes."""
    source_status = "pending" if phase == "passive" else "passive_complete"
    pending = deque(_rolling_frame_entries(state, source_status))
    workers: dict[int, _RollingWorker] = {}
    quarantined: set[int] = set()
    failures: dict[int, int] = {int(gpu): 0 for gpu in args.gpu_indices[:args.parallel_chunks]}
    completed = 0

    def persist() -> None:
        state["phase"] = phase
        state["workers"] = {
            str(gpu): {
                "phase": phase, "status": "quarantined" if gpu in quarantined else "ready",
                "scene_load_s": worker.scene_load_s, "failure_streak": failures[gpu],
            }
            for gpu, worker in workers.items()
        }
        phase_summary = state.setdefault("phase_summary", {}).setdefault(phase, {})
        for gpu, worker in workers.items():
            prior = dict(phase_summary.get(str(gpu)) or {})
            phase_summary[str(gpu)] = {
                **prior, "gpu_index": gpu, "scene_load_s": worker.scene_load_s,
                "scene_load_count": int(prior.get("scene_load_count", 0)),
                "failure_streak": failures[gpu], "quarantined": gpu in quarantined,
                "updated_at": _utc_now(),
            }
        _persist_rolling_state(args.out, state)
        manifest["execution"] = {
            "scheduler": "rolling", "lease_size": int(args.lease_size),
            "gpu_indices": list(args.gpu_indices), "parallel_chunks": int(args.parallel_chunks),
            "mitsuba_runtime": dict(args.mitsuba_runtime_info), "phase": phase, "updated_at": _utc_now(),
        }
        manifest["updated_at"] = _utc_now()
        _atomic_json(args.out / "queue_manifest.json", manifest)

    def ready(worker: _RollingWorker) -> bool:
        gpu = worker.gpu_index
        try:
            message = worker.wait_ready()
            if worker.audit_path is not None:
                _adopt_render_input_audit(
                    args.out, worker.work_root,
                    effective_scene_digest=args.effective_scene_digest, polarized=args.polar,
                )
            failures[gpu] = 0
            summary = state.setdefault("phase_summary", {}).setdefault(phase, {})
            previous = dict(summary.get(str(gpu)) or {})
            summary[str(gpu)] = {
                **previous, "gpu_index": gpu,
                "scene_load_count": int(previous.get("scene_load_count", 0)) + 1,
            }
            print(
                f"[rolling] ready gpu={gpu} phase={phase} scene_load_s={message.get('scene_load_s')}", flush=True,
            )
            return True
        except Exception as exc:
            worker.stop()
            workers.pop(gpu, None)
            failures[gpu] += 1
            print(f"[rolling] setup failed gpu={gpu} phase={phase} streak={failures[gpu]}: {exc}", flush=True)
            if failures[gpu] >= 3:
                quarantined.add(gpu)
                print(f"[rolling] quarantine gpu={gpu} phase={phase}", flush=True)
            return False

    def launch(gpu: int, *, defer_ready: bool = False) -> bool:
        worker = _RollingWorker(args, gpu_index=gpu, phase=phase)
        try:
            worker.start()
            workers[gpu] = worker
            return True if defer_ready else ready(worker)
        except Exception as exc:
            worker.stop()
            failures[gpu] += 1
            print(f"[rolling] setup failed gpu={gpu} phase={phase} streak={failures[gpu]}: {exc}", flush=True)
            if failures[gpu] >= 3:
                quarantined.add(gpu)
                print(f"[rolling] quarantine gpu={gpu} phase={phase}", flush=True)
            return False

    started = [int(gpu) for gpu in args.gpu_indices[:args.parallel_chunks] if launch(int(gpu), defer_ready=True)]
    for gpu in started:
        ready(workers[gpu])
    persist()
    try:
        while pending or any(worker.busy_lease is not None for worker in workers.values()):
            # Fill every healthy idle GPU before waiting for another message.
            for gpu, worker in list(workers.items()):
                if worker.busy_lease is not None or not pending:
                    continue
                first = pending.popleft()
                count = 1 if first.pop("force_singleton", False) else int(args.lease_size)
                entries = [first]
                while len(entries) < count and pending and not pending[0].get("force_singleton", False):
                    entries.append(pending.popleft())
                lease = _rolling_make_lease(entries, phase)
                for entry in entries:
                    entry["status"] = "leased"
                    entry["lease_id"] = lease["lease_id"]
                    entry["worker_gpu_index"] = gpu
                    entry["phase"] = phase
                    entry["attempts"] = int(entry.get("attempts", 0)) + 1
                state["leases"][lease["lease_id"]] = {
                    "phase": phase, "gpu_index": gpu, "frame_ids": list(lease["frame_ids"]),
                    "attempt": max(int(entry["attempts"]) for entry in entries), "started_at": _utc_now(),
                }
                worker.send_lease(lease)
                print(f"[rolling] dispatch gpu={gpu} phase={phase} lease={lease['lease_id']} frames={len(entries)}", flush=True)
                persist()

            made_progress = False
            for gpu, worker in list(workers.items()):
                message = worker.poll_message()
                if message is None:
                    if worker.busy_lease is not None and worker.dead():
                        message = {"type": "lease_error", "lease_id": worker.busy_lease["lease_id"], "error": "worker exited"}
                    else:
                        continue
                made_progress = True
                lease = worker.busy_lease
                if message.get("type") == "frame_complete" and lease is not None and message.get("lease_id") == lease["lease_id"]:
                    result = message.get("frame")
                    if not isinstance(result, dict) or str(result.get("frame_id")) not in lease["frame_ids"]:
                        raise RuntimeError(f"rolling worker reported invalid frame event on gpu={gpu}")
                    # The worker emits this only after an atomic per-frame
                    # staging rename.  Persist passive progress immediately
                    # so UI/log n/m advances within a multi-frame lease.
                    if phase == "passive":
                        entry = state["frames"][str(result["frame_id"])]
                        entry["timings"] = result.get("timings")
                        entry["worker_gpu_index"] = gpu
                        entry["status"] = "passive_complete"
                        state["leases"][lease["lease_id"]].update({
                            "status": "partial", "last_frame_id": entry["frame_id"],
                            "last_frame_at": _utc_now(),
                        })
                        persist()
                    print(_rolling_frame_progress_line(
                        state, phase=phase, gpu=gpu, result=result,
                        worker_wall_s=message.get("worker_frame_wall_s"),
                    ), flush=True)
                    continue
                if message.get("type") == "lease_complete" and lease is not None and message.get("lease_id") == lease["lease_id"]:
                    worker.busy_lease = None
                    failures[gpu] = 0
                    for result in message.get("frames") or []:
                        entry = state["frames"][str(result["frame_id"])]
                        entry["timings"] = result.get("timings")
                        entry["worker_gpu_index"] = gpu
                        if phase == "passive":
                            entry["status"] = "passive_complete"
                            entry.pop("lease_id", None)
                        else:
                            _publish_rolling_frame(args, manifest, state, entry)
                            completed += 1
                    state["leases"][lease["lease_id"]].update({"status": "complete", "completed_at": _utc_now()})
                    persist()
                    _refresh_rolling_global_exports(args.out, manifest, state)
                    continue
                if message.get("type") == "lease_error" and lease is not None:
                    worker.busy_lease = None
                    error = str(message.get("error") or "worker lease failed")
                    retry = _rolling_requeue_failed_lease(state, lease, error=error)
                    pending.extendleft(reversed(retry))
                    state["leases"][lease["lease_id"]].update({"status": "failed", "error": error, "failed_at": _utc_now()})
                    failures[gpu] += 1
                    worker.stop()
                    workers.pop(gpu, None)
                    if failures[gpu] >= 3:
                        quarantined.add(gpu)
                        print(f"[rolling] quarantine gpu={gpu} phase={phase}", flush=True)
                    else:
                        launch(gpu)
                    persist()
                    continue
                if message.get("type") == "fatal":
                    raise RuntimeError(f"rolling worker fatal gpu={gpu}: {message.get('error')}")
            if not workers and pending:
                # A scene-load failure is distinct from one bad frame.  Give
                # each GPU three fresh contexts before it is quarantined.
                restartable = [
                    int(gpu) for gpu in args.gpu_indices[:args.parallel_chunks]
                    if int(gpu) not in quarantined
                ]
                if restartable:
                    for gpu in restartable:
                        launch(gpu)
                    persist()
                    continue
                for entry in pending:
                    entry["status"] = "failed"
                    entry["terminal_error"] = f"no healthy GPU worker for {phase}"
                pending.clear()
                persist()
                break
            if not made_progress:
                time.sleep(0.05)
    finally:
        for worker in workers.values():
            worker.stop()
    return completed, quarantined


def _run_rolling_scheduler(args: argparse.Namespace, manifest: dict) -> int:
    """Run passive then flash-direct rolling phases, without changing v2 identity."""
    state = _load_or_create_rolling_state(args.out, manifest)
    for entry in state["frames"].values():
        if entry.get("status") == "deferred":
            entry["status"] = entry.pop("deferred_status", "pending")
    _rolling_record_existing_frames(args, manifest, state)
    recovered = _recover_orphaned_rolling_leases(state)
    if recovered:
        print(
            f"[rolling] recovered {len(recovered)} orphaned lease frame(s) as pending passive work",
            flush=True,
        )
    # A fully staged direct frame is already a valid input to the parent-only
    # publisher.  Publish it before allocating any GPU work on resume.
    for entry in list(_rolling_frame_entries(state, "staged_complete")):
        _publish_rolling_frame(args, manifest, state, entry)
    _rolling_update_chunk_status(manifest, state)
    _persist_rolling_state(args.out, state)
    _atomic_json(args.out / "queue_manifest.json", manifest)
    _refresh_rolling_global_exports(args.out, manifest, state)
    _write_rolling_report(args.out, manifest, state)

    if args.max_chunks is not None:
        eligible_chunks = [
            int(chunk["chunk_id"]) for chunk in manifest["chunks"]
            if any(
                entry.get("status") != "complete" and int(entry["chunk_id"]) == int(chunk["chunk_id"])
                for entry in state["frames"].values()
            )
        ][:int(args.max_chunks)]
        allowed = set(eligible_chunks)
        for entry in state["frames"].values():
            if entry.get("status") in {"pending", "passive_complete"} and int(entry["chunk_id"]) not in allowed:
                entry["deferred_status"] = entry["status"]
                entry["status"] = "deferred"
        _persist_rolling_state(args.out, state)

    if _rolling_frame_entries(state, "failed"):
        _write_rolling_report(args.out, manifest, state)
        return 1
    if not _rolling_frame_entries(state, "pending") and not _rolling_frame_entries(state, "passive_complete"):
        incomplete = _rolling_incomplete_status_counts(state)
        if incomplete:
            print(f"[rolling] refusing successful completion with unfinished frames: {incomplete}", flush=True)
            _write_rolling_report(args.out, manifest, state)
            return 1
        return 0
    if _rolling_frame_entries(state, "pending"):
        _run_rolling_phase(args, manifest, state, "passive")
    if _rolling_frame_entries(state, "failed"):
        _write_rolling_report(args.out, manifest, state)
        return 1
    passive_incomplete = _rolling_phase_incomplete_status_counts(state, "passive")
    if passive_incomplete:
        print(f"[rolling] passive phase did not drain all work: {passive_incomplete}", flush=True)
        _write_rolling_report(args.out, manifest, state)
        return 1
    _run_rolling_phase(args, manifest, state, "flash_direct")
    _rolling_update_chunk_status(manifest, state)
    _persist_rolling_state(args.out, state)
    _atomic_json(args.out / "queue_manifest.json", manifest)
    _refresh_rolling_global_exports(args.out, manifest, state)
    _write_rolling_report(args.out, manifest, state)
    incomplete = _rolling_incomplete_status_counts(state)
    if incomplete:
        print(f"[rolling] flash-direct phase did not drain all work: {incomplete}", flush=True)
    return 1 if _rolling_frame_entries(state, "failed") or incomplete else 0


def _parse_gpu_indices(value: str) -> list[int]:
    """Parse physical CUDA indices once, before the scheduler starts workers."""
    values = [token.strip() for token in str(value).split(",") if token.strip()]
    if not values:
        raise ValueError("at least one CUDA GPU index is required")
    try:
        indices = [int(token) for token in values]
    except ValueError as exc:
        raise ValueError(f"invalid CUDA GPU index list: {value!r}") from exc
    if any(index < 0 for index in indices):
        raise ValueError("CUDA GPU indices must be non-negative")
    if len(set(indices)) != len(indices):
        raise ValueError("CUDA GPU indices must not contain duplicates")
    return indices


_RUNTIME_CHOICES = ("auto", "optix7", "optix8")
_OBSERVATION_VARIANT_CHOICES = (
    "auto", "cuda_ad_rgb", "cuda_ad_spectral",
    "cuda_ad_rgb_polarized", "cuda_ad_spectral_polarized",
)


def _first_gpu_compute_capability() -> str | None:
    """Return the first visible physical GPU's compute capability, if available."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def _path_looks_like_runtime(path: str, runtime: str) -> bool:
    normalized = str(path).replace("\\", "/").lower()
    if runtime == "optix7":
        return "optix7" in normalized
    return "optix7" not in normalized


def _resolve_mitsuba_runtime(
    requested: str,
    *,
    build_dir_override: Path | None = None,
    python_override: Path | None = None,
    pythonpath_override: Path | None = None,
) -> dict[str, str | None]:
    """Resolve a host-local Mitsuba build for the selected OptiX ABI.

    The source checkout is shared through NAS, whereas its Dr.Jit/Mitsuba
    extensions are ABI-specific.  In particular an RTX 3090 + R525 host must
    never inherit a Python path containing the OptiX-8 build.
    """
    if requested not in _RUNTIME_CHOICES:
        raise ValueError(f"unsupported Mitsuba runtime: {requested!r}")
    compute_capability = _first_gpu_compute_capability()
    runtime = requested
    if runtime == "auto":
        runtime = "optix8" if compute_capability == "12.0" else "optix7"

    if runtime == "optix7":
        default_build = os.environ.get(
            "ROBOMITUBA_DEVICE2_MITSUBA_BUILD_DIR",
            str(Path.home() / "robomituba-build" / "mitsuba3-optix7"),
        )
        default_python = os.environ.get(
            "ROBOMITUBA_OPTIX7_MITSUBA_PYTHON",
            "/root/miniconda3/envs/mitsuba_optix7/bin/python",
        )
    else:
        default_build = os.environ.get(
            "ROBOMITUBA_DEVICE1_MITSUBA_BUILD_DIR",
            str(Path.home() / "robomituba-build" / "mitsuba3"),
        )
        default_python = os.environ.get("ROBOMITUBA_OPTIX8_MITSUBA_PYTHON", "/usr/bin/python3")

    generic_build = os.environ.get("ROBOMITUBA_MITSUBA_BUILD_DIR")
    using_generic_build = False
    if build_dir_override is not None:
        build_dir = str(build_dir_override.expanduser().resolve())
    elif generic_build and _path_looks_like_runtime(generic_build, runtime):
        build_dir = str(Path(generic_build).expanduser().resolve())
        using_generic_build = True
    else:
        build_dir = str(Path(default_build).expanduser().resolve())
    if python_override is not None:
        python_executable = str(python_override.expanduser().resolve())
    else:
        generic_python = os.environ.get("ROBOMITUBA_MITSUBA_PYTHON")
        python_executable = generic_python if (using_generic_build and generic_python) else default_python
    pythonpath = str(
        (pythonpath_override.expanduser().resolve() if pythonpath_override is not None
         else Path(build_dir) / "python")
    )
    return {
        "requested": requested,
        "runtime": runtime,
        "compute_capability": compute_capability,
        "build_dir": build_dir,
        "python": python_executable,
        "pythonpath": pythonpath,
    }


def _validate_mitsuba_runtime(runtime: dict[str, str | None]) -> None:
    build_dir = Path(str(runtime["build_dir"]))
    pythonpath = Path(str(runtime["pythonpath"]))
    python_executable = Path(str(runtime["python"]))
    if str(build_dir).startswith("/jarvis/"):
        raise ValueError(f"Mitsuba build must be host-local, not NAS: {build_dir}")
    if not python_executable.is_file():
        raise ValueError(f"Mitsuba Python executable not found: {python_executable}")
    if not pythonpath.is_dir():
        raise ValueError(f"Mitsuba Python build path not found: {pythonpath}")


def _runtime_worker_env(gpu_index: int, runtime: dict[str, str | None]) -> dict[str, str]:
    env = _gpu_worker_env(gpu_index)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(runtime["pythonpath"]), existing) if item
    )
    env["ROBOMITUBA_MITSUBA_RUNTIME"] = str(runtime["runtime"])
    env["ROBOMITUBA_MITSUBA_BUILD_DIR"] = str(runtime["build_dir"])
    env["ROBOMITUBA_MITSUBA_PYTHON"] = str(runtime["python"])
    env["ROBOMITUBA_MITSUBA_PYTHONPATH"] = str(runtime["pythonpath"])
    return env


def _smoke_mitsuba_runtime(
    runtime: dict[str, str | None], *, gpu_index: int, polarized: bool,
    observation_variant: str = "auto",
) -> dict[str, Any]:
    """Fail before dispatching all chunks when an incompatible OptiX ABI is selected."""
    candidates = (
        ("cuda_ad_rgb_polarized", "cuda_ad_spectral_polarized")
        if polarized else ("cuda_ad_rgb", "cuda_ad_spectral")
    )
    code = (
        "import json, mitsuba as mi; "
        "available=list(mi.variants()); "
        f"requested={observation_variant!r}; candidates={candidates!r}; "
        "variant=(requested if requested != 'auto' else "
        "next((candidate for candidate in candidates if candidate in available), None)); "
        "assert variant in available, (requested, candidates, available); "
        "mi.set_variant(variant); "
        "scene = mi.load_dict({'type': 'scene'}); "
        "print(json.dumps({'mitsuba_module': mi.__file__, 'variant': mi.variant(), "
        "'variants': available, 'scene_type': type(scene).__name__}))"
    )
    result = subprocess.run(
        [str(runtime["python"]), "-c", code],
        cwd=REPO_ROOT, env=_runtime_worker_env(gpu_index, runtime),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    output = result.stdout.strip()
    if result.returncode != 0:
        raise RuntimeError(
            f"Mitsuba {runtime['runtime']} runtime smoke failed on GPU {gpu_index}; "
            f"python={runtime['python']} pythonpath={runtime['pythonpath']}\n{output}"
        )
    try:
        payload = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Mitsuba runtime smoke emitted no JSON result:\n{output}") from exc
    selected = payload.get("variant")
    expected = observation_variant if observation_variant != "auto" else None
    valid = selected == expected if expected is not None else selected in candidates
    if not valid:
        accepted = (expected,) if expected is not None else candidates
        raise RuntimeError(
            f"Mitsuba runtime smoke selected {selected!r}, expected one of {accepted!r}"
        )
    return payload


def _gpu_worker_env(gpu_index: int) -> dict[str, str]:
    """Expose exactly one physical GPU to a renderer subprocess.

    Mitsuba sees that device as logical CUDA device 0.  Setting the legacy
    render-GPU selector to 0 prevents a parent daemon setting such as
    ``0,1,...,7`` from re-expanding the child's visibility.
    """
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(int(gpu_index))
    env["ROBOMITUBA_RENDER_GPU_INDICES"] = "0"
    env.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    return env


def _batch_staging_dir(chunk_dir: Path, batch_id: int) -> Path:
    """Return the visible, target-local staging directory for one worker batch."""
    return chunk_dir / f".render_batch_{int(batch_id):03d}"


def _write_batch_staging_status(
    batch_dir: Path, *, chunk_id: int, batch_id: int, gpu_index: int,
    viewpoints: list[str], status: str, attempt: int, returncode: int | None = None,
) -> None:
    """Expose live worker progress without publishing an incomplete frame contract."""
    payload: dict[str, Any] = {
        "schema": "robomituba.ir_render_batch_staging.v1",
        "storage": "target_local_staging",
        "status": str(status),
        "chunk_id": int(chunk_id),
        "batch_id": int(batch_id),
        "gpu_index": int(gpu_index),
        "attempt": int(attempt),
        "frame_count": len(viewpoints),
        "viewpoints": list(viewpoints),
        "updated_at": _utc_now(),
    }
    if returncode is not None:
        payload["returncode"] = int(returncode)
    _atomic_json(batch_dir / "batch_staging.json", payload)


def _run_chunk_worker(
    args: argparse.Namespace,
    chunk: dict[str, Any],
    *,
    gpu_index: int,
) -> dict[str, Any]:
    """Render one logical chunk on one fixed GPU without touching run-global state."""
    chunk_id = int(chunk["chunk_id"])
    chunk_dir = args.out / chunk["relative_dir"]
    existing_rows = _load_rows(chunk_dir / "index.jsonl") if chunk_dir.is_dir() else []
    resume_from = 0
    if (
        0 < len(existing_rows) < int(chunk["frame_count"])
        and _chunk_complete(
            chunk_dir, len(existing_rows), observations_only=args.observations_only, polarized=args.polar, surface_domain=args.surface_domain,
        )
    ):
        # Batches are merged atomically in order, so this prefix can be kept.
        resume_from = len(existing_rows)
        for stale in chunk_dir.glob(".render_batch_*"):
            shutil.rmtree(stale)
    elif chunk_dir.exists() and not _chunk_complete(
        chunk_dir, int(chunk["frame_count"]),
        observations_only=args.observations_only, polarized=args.polar, surface_domain=args.surface_domain,
    ):
        # No trustworthy ordered prefix: clear only this chunk's incomplete output.
        shutil.rmtree(chunk_dir)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    merged_rows: list[dict[str, Any]] = existing_rows[:resume_from]
    viewpoints = list(chunk["viewpoints"])
    # Separate cache roots eliminate unsafe same-path texture writes between GPU
    # workers. They are content-equivalent and remain inside the single run root.
    local_nir = args.out / "shared" / f"nir_band_{args.band}" / f"gpu_{gpu_index}"
    worker_env = _runtime_worker_env(gpu_index, args.mitsuba_runtime_info)
    worker_env["ROBOMITUBA_TEXTURE_MAX_RESOLUTION"] = str(args.texture_max_resolution)
    worker_env["ROBOMITUBA_TEXTURE_CACHE_DIR"] = str(args.texture_cache_dir)
    for batch_start in range(resume_from, len(viewpoints), args.render_batch_size):
        batch_id = batch_start // args.render_batch_size
        # Keep newly written EXR/PNG artifacts in the run directory immediately.
        # Only the final move into <chunk>/<frame> remains atomic.
        batch_dir = _batch_staging_dir(chunk_dir, batch_id)
        if batch_dir.exists():
            shutil.rmtree(batch_dir)
        batch_dir.mkdir(parents=True, exist_ok=True)
        batch_viewpoints = viewpoints[batch_start:batch_start + args.render_batch_size]
        command = [
            str(args.mitsuba_runtime_info["python"]), "-u", str(RENDER_APP),
            "--scene-dir", str(args.scene_dir), "--surface-domain", str(args.surface_domain),
            "--out", str(batch_dir), "--viewpoints", ",".join(batch_viewpoints),
            "--width", str(args.width), "--height", str(args.height),
            "--fov", str(args.fov), "--spp", str(args.spp),
            "--rgb-spp", str(args.rgb_spp),
            "--nir-ambient-spp", str(args.nir_ambient_spp),
            "--nir-direct-spp", str(args.nir_direct_spp),
            "--max-depth", str(args.max_depth),
            "--observation-variant", str(args.observation_variant),
            "--subpixel", str(args.subpixel), "--band", str(args.band),
            "--nir-cache-dir", str(local_nir),
            "--texture-max-resolution", str(args.texture_max_resolution),
            "--texture-cache-dir", str(args.texture_cache_dir),
            "--nir-flash-model", "spot", "--nir-flash-offset-y", "-0.10",
            "--nir-flash-beam-width", "22", "--nir-flash-cutoff-angle", "30",
        ]
        if args.polar:
            command.append("--polar")
        if args.observations_only:
            command.append("--observations-only")
        if args.async_io:
            command.append("--async-io")
        command.extend(("--gpu-cleanup-interval", str(args.gpu_cleanup_interval)))
        print(
            f"[queue] gpu={gpu_index} start chunk={chunk_id:03d} batch={batch_id:03d} "
            f"frames={len(batch_viewpoints)} attempts={args.batch_retries}",
            flush=True,
        )
        result: subprocess.CompletedProcess[str] | None = None
        for batch_attempt in range(1, args.batch_retries + 1):
            # A crashed CUDA context cannot be reused. A fresh subprocess gives
            # this batch the same isolation boundary as the daemon worker manager.
            if batch_attempt > 1:
                if batch_dir.exists():
                    shutil.rmtree(batch_dir)
                batch_dir.mkdir(parents=True, exist_ok=True)
                print(
                    f"[queue] gpu={gpu_index} retry chunk={chunk_id:03d} batch={batch_id:03d} "
                    f"attempt={batch_attempt}/{args.batch_retries} (fresh worker)",
                    flush=True,
                )
                time.sleep(min(5.0, float(batch_attempt - 1)))
            _write_batch_staging_status(
                batch_dir, chunk_id=chunk_id, batch_id=batch_id, gpu_index=gpu_index,
                viewpoints=batch_viewpoints, status="running", attempt=batch_attempt,
            )
            result = subprocess.run(command, cwd=REPO_ROOT, env=worker_env)
            if result.returncode == 0:
                _write_batch_staging_status(
                    batch_dir, chunk_id=chunk_id, batch_id=batch_id, gpu_index=gpu_index,
                    viewpoints=batch_viewpoints, status="complete", attempt=batch_attempt,
                )
                break
            _write_batch_staging_status(
                batch_dir, chunk_id=chunk_id, batch_id=batch_id, gpu_index=gpu_index,
                viewpoints=batch_viewpoints, status="failed", attempt=batch_attempt,
                returncode=result.returncode,
            )
            print(
                f"[queue] gpu={gpu_index} batch failed chunk={chunk_id:03d} batch={batch_id:03d} "
                f"attempt={batch_attempt}/{args.batch_retries} returncode={result.returncode}",
                flush=True,
            )
        assert result is not None
        if result.returncode != 0:
            raise _ChunkRenderFailed(
                chunk_id, int(result.returncode),
                f"GPU {gpu_index} failed chunk {chunk_id:03d} batch {batch_id:03d}",
            )
        batch_rows = _load_rows(batch_dir / "index.jsonl")
        if len(batch_rows) != len(batch_viewpoints):
            raise RuntimeError(
                f"chunk {chunk_id:03d} batch {batch_id:03d} returned {len(batch_rows)} rows, "
                f"expected {len(batch_viewpoints)}"
            )
        _record_chunk_render_input_audit(
            chunk_dir, batch_dir,
            effective_scene_digest=args.effective_scene_digest, polarized=args.polar,
        )
        for row in batch_rows:
            relocated = _relocate_row_paths(row, batch_dir, chunk_dir)
            source_frame = batch_dir / row["frame_id"]
            target_frame = chunk_dir / row["frame_id"]
            if target_frame.exists():
                shutil.rmtree(target_frame)
            shutil.move(str(source_frame), str(target_frame))
            _atomic_json(target_frame / "frame.json", relocated)
            merged_rows.append(relocated)
        shutil.rmtree(batch_dir)
        _atomic_text(
            chunk_dir / "index.jsonl",
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in merged_rows),
        )
        # A persisted prefix must include the derived RGB PNG before a later
        # batch fails, otherwise resume would not be safe past this point.
        _postprocess_chunk(chunk_dir, args.rgb_exposure)
        print(
            f"[queue] gpu={gpu_index} complete chunk={chunk_id:03d} batch={batch_id:03d} "
            f"merged_frames={len(merged_rows)}",
            flush=True,
        )
    _atomic_text(
        chunk_dir / "index.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in merged_rows),
    )
    _postprocess_chunk(chunk_dir, args.rgb_exposure)
    if not _chunk_complete(
        chunk_dir, int(chunk["frame_count"]),
        observations_only=args.observations_only, polarized=args.polar, surface_domain=args.surface_domain,
    ):
        raise RuntimeError(f"chunk {chunk_id:03d} failed post-render completeness check")
    return {
        "chunk_id": chunk_id,
        "gpu_index": int(gpu_index),
        "frame_count": int(chunk["frame_count"]),
        "chunk_dir": str(chunk_dir.resolve()),
    }


def _new_manifest(args: argparse.Namespace, graph: dict, scene_hash: str | None = None) -> dict:
    specs = _frame_specs(graph, args.shuffle_seed)
    groups = _chunks(specs, args.chunk_size)
    return {
        "schema": "robomituba.ir_render_queue.v2",
        "created_at": _utc_now(),
        "scene_dir": str(args.scene_dir.resolve()),
        "source_scene_dir": str(getattr(args, "source_scene_dir", args.scene_dir).resolve()),
        "surface_domain": str(getattr(args, "surface_domain", SPECULAR_MASKED_PBR_DOMAIN)),
        "effective_scene_digest": getattr(args, "effective_scene_digest", None),
        "scene_content_sha256": scene_hash or _scene_content_sha256(args.scene_dir),
        "frame_count": len(specs),
        "shuffle_seed": int(args.shuffle_seed),
        "chunk_size": int(args.chunk_size),
        "configuration": {
            "width": args.width, "height": args.height, "spp": args.spp,
            "rgb_spp": int(getattr(args, "rgb_spp", args.spp)),
            "nir_ambient_spp": int(getattr(args, "nir_ambient_spp", args.spp)),
            "nir_direct_spp": int(getattr(args, "nir_direct_spp", args.spp)),
            "max_depth": int(getattr(args, "max_depth", 8)),
            "subpixel": args.subpixel, "fov": args.fov, "band": args.band,
            "observation_variant": str(getattr(args, "observation_variant", "auto")),
            "rgb_png_exposure": args.rgb_exposure,
            "render_batch_size": int(getattr(args, "render_batch_size", 20)),
            "pbr_gt_provider": str(getattr(args, "pbr_gt_provider", "mitsuba_property")),
            "geometry_profile": str(getattr(args, "geometry_profile", "full")),
            "geometry_digest": (getattr(args, "geometry_profile_payload", None) or {}).get("geometry_digest"),
            "geometry_scene_dir": str(getattr(args, "geometry_scene_dir", args.scene_dir).resolve()),
            "polarized": bool(getattr(args, "polar", False)),
            # This changes rendered pixels, so it belongs to the immutable
            # dataset configuration. The cache directory itself does not.
            "texture_max_resolution": int(getattr(args, "texture_max_resolution", 0)),
            "storage_layout": (
                _ROLLING_STORAGE_LAYOUT if str(getattr(args, "scheduler", "rolling")) == "rolling"
                else "chunk_frame_v1"
            ),
        },
        "chunks": [
            {"chunk_id": i, "relative_dir": f"chunks/chunk_{i:03d}",
             "status": "pending", "frame_count": len(group), "viewpoints": group}
            for i, group in enumerate(groups)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--surface-domain", choices=sorted(SUPPORTED_SURFACE_DOMAINS), default=STRUCTURAL_SPECULAR_PBR_DOMAIN,
        help="specular_masked_pbr retains glass/mirrors and emits first-hit semantic masks",
    )
    parser.add_argument("--effective-scene-dir", type=Path,
                        help="reuse or publish the effective scene here (defaults under --out)")
    parser.add_argument("--pbr-gt-provider", choices=("blender_aov", "mitsuba_property"),
                        default="blender_aov")
    parser.add_argument("--geometry-profile", choices=("ir_semantic_lod_v1", "full"), default="ir_semantic_lod_v1",
                        help="common geometry for Mitsuba and Blender GT; full is an explicit debug opt-out")
    parser.add_argument("--geometry-profile-dir", type=Path,
                        help="IR-only derived geometry artifact root (defaults under --out)")
    parser.add_argument("--rebuild-geometry-profile", action="store_true",
                        help="discard and rebuild the generated IR geometry profile")
    parser.add_argument("--resume-geometry-profile", action="store_true",
                        help="reuse and strictly validate existing Stage-1 atlases; bake only missing geometry units")
    parser.add_argument("--source-blend", type=Path,
                        help="required for blender_aov PBR GT; source .blend remains read-only")
    parser.add_argument("--blender-gt-script", type=Path, default=BLENDER_GT_SCRIPT)
    parser.add_argument("--blender-samples", type=int, default=1)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--shuffle-seed", type=int, default=20260806)
    parser.add_argument("--width", type=int, default=684)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--spp", type=int,
                        help="legacy common observation SPP; when supplied, unset pass-specific values inherit it")
    parser.add_argument("--rgb-spp", type=int,
                        help="RGB passive SPP (default profile: 2000; otherwise inherits explicit --spp)")
    parser.add_argument("--nir-ambient-spp", type=int,
                        help="NIR ambient SPP (default profile: 1500; otherwise inherits explicit --spp)")
    parser.add_argument("--nir-direct-spp", type=int,
                        help="NIR flash-direct SPP (default profile: 384; otherwise inherits explicit --spp)")
    parser.add_argument("--max-depth", type=int, default=8,
                        help="path-integrator maximum depth for all observation passes")
    parser.add_argument("--subpixel", type=int, default=1)
    parser.add_argument("--band", type=int, default=854)
    parser.add_argument(
        "--polar", action="store_true",
        help="include Stokes-derived DoP/AoLP observation artifacts; recorded in the immutable queue contract",
    )
    parser.add_argument(
        "--observation-variant", choices=_OBSERVATION_VARIANT_CHOICES, default="auto",
        help="Mitsuba observation carrier; auto uses RGB when unpolarized and RGB-polarized when compiled",
    )
    parser.add_argument("--rgb-exposure", type=float, default=1.0)
    parser.add_argument(
        "--texture-max-resolution", type=int,
        default=int(os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "256") or 256),
        help="IR render bitmap max edge; source GLB/PBR atlases remain unchanged (default: 256)",
    )
    parser.add_argument(
        "--texture-cache-dir", type=Path,
        default=Path(os.environ.get(
            "ROBOMITUBA_TEXTURE_CACHE_DIR", str(Path.home() / "robomituba-cache" / "ir_texture_downsampled"),
        )),
        help="host-local shared cache for bounded IR render textures",
    )
    parser.add_argument(
        "--render-batch-size", type=int, default=20,
        help="chunked scheduler only: frames per renderer subprocess inside each logical chunk",
    )
    parser.add_argument(
        "--batch-retries", type=int, default=3,
        help="fresh worker attempts per failed render batch (daemon-style crash recovery)",
    )
    parser.add_argument(
        "--gpu-indices",
        default=os.environ.get(
            "ROBOMITUBA_RENDER_GPU_INDICES", os.environ.get("CUDA_VISIBLE_DEVICES", "0"),
        ),
        help="comma-separated physical CUDA GPU indices; each active chunk gets exactly one",
    )
    parser.add_argument(
        "--parallel-chunks", type=int,
        help="rolling: persistent GPU worker count; chunked: concurrent chunks (defaults to GPU count)",
    )
    parser.add_argument(
        "--scheduler", choices=("rolling", "chunked"), default="rolling",
        help="rolling keeps one scene per GPU/phase; chunked preserves the legacy bounded subprocess scheduler",
    )
    parser.add_argument(
        "--lease-size", type=int, default=4,
        help="rolling scheduler frames per dynamic lease (last lease shrinks automatically)",
    )
    parser.add_argument(
        "--mitsuba-runtime", choices=_RUNTIME_CHOICES,
        default=os.environ.get("ROBOMITUBA_MITSUBA_RUNTIME", "auto"),
        help="auto selects OptiX 7 except on sm_120 hosts; explicit optix7 pins the R525-compatible local build",
    )
    parser.add_argument("--mitsuba-build-dir", type=Path,
                        help="host-local selected Mitsuba build root (contains python/)")
    parser.add_argument("--mitsuba-python", type=Path,
                        help="Python executable that matches the selected Mitsuba build")
    parser.add_argument("--mitsuba-pythonpath", type=Path,
                        help="Mitsuba build python directory; defaults to --mitsuba-build-dir/python")
    parser.add_argument(
        "--runtime-smoke-only", action="store_true",
        help="verify the selected CUDA spectral (or polarized) OptiX runtime, then exit without creating a dataset",
    )
    parser.add_argument("--max-chunks", type=int, help="stop after this many chunks this run")
    parser.add_argument(
        "--observations-only", action="store_true",
        help="render GPU RGB/NIR observations now and defer Blender/property GT generation",
    )
    parser.add_argument(
        "--gpu-cleanup-interval", type=int, default=4,
        help="flush the Dr.Jit allocator every N frames inside each worker",
    )
    parser.add_argument(
        "--async-io", action="store_true",
        help="overlap bounded EXR writes with subsequent GPU renders",
    )
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if args.chunk_size < 1:
        parser.error("--chunk-size must be positive")
    if args.spp is None:
        # New IR default: conservative passive sampling plus the validated
        # lower-cost flash-direct pass.  Explicit --spp retains the old
        # "apply one value to every pass" contract.
        args.spp = 2000
        defaults = {"rgb_spp": 2000, "nir_ambient_spp": 1500, "nir_direct_spp": 384}
    else:
        defaults = {name: int(args.spp) for name in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp")}
    for name in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp"):
        if getattr(args, name) is None:
            setattr(args, name, defaults[name])
        if int(getattr(args, name)) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_depth == 0 or args.max_depth < -1:
        parser.error("--max-depth must be -1 (unlimited) or a positive integer")
    if args.render_batch_size < 1:
        parser.error("--render-batch-size must be positive")
    if args.lease_size < 1:
        parser.error("--lease-size must be positive")
    if args.batch_retries < 1:
        parser.error("--batch-retries must be positive")
    if args.max_chunks is not None and args.max_chunks < 1:
        parser.error("--max-chunks must be positive")
    if args.gpu_cleanup_interval < 1:
        parser.error("--gpu-cleanup-interval must be positive")
    if args.texture_max_resolution < 0:
        parser.error("--texture-max-resolution must be non-negative")
    args.texture_cache_dir = args.texture_cache_dir.expanduser().resolve()
    if str(args.texture_cache_dir).startswith("/jarvis/"):
        parser.error("--texture-cache-dir must be host-local, not /jarvis/NAS")
    try:
        args.gpu_indices = _parse_gpu_indices(args.gpu_indices)
    except ValueError as exc:
        parser.error(str(exc))
    if args.parallel_chunks is None:
        args.parallel_chunks = len(args.gpu_indices)
    if args.parallel_chunks < 1:
        parser.error("--parallel-chunks must be positive")
    if args.parallel_chunks > len(args.gpu_indices):
        parser.error("--parallel-chunks cannot exceed the number of --gpu-indices")
    try:
        args.mitsuba_runtime_info = _resolve_mitsuba_runtime(
            args.mitsuba_runtime,
            build_dir_override=args.mitsuba_build_dir,
            python_override=args.mitsuba_python,
            pythonpath_override=args.mitsuba_pythonpath,
        )
        _validate_mitsuba_runtime(args.mitsuba_runtime_info)
    except ValueError as exc:
        parser.error(str(exc))
    runtime = args.mitsuba_runtime_info
    print(
        f"[queue] mitsuba_runtime={runtime['runtime']} requested={runtime['requested']} "
        f"compute_cap={runtime['compute_capability'] or 'unknown'} "
        f"python={runtime['python']} pythonpath={runtime['pythonpath']}",
        flush=True,
    )
    if args.runtime_smoke_only:
        try:
            smoke = _smoke_mitsuba_runtime(
                runtime, gpu_index=args.gpu_indices[0], polarized=bool(args.polar),
                observation_variant=args.observation_variant,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            f"[queue] runtime smoke PASS gpu={args.gpu_indices[0]} "
            f"variant={smoke['variant']} module={smoke['mitsuba_module']}",
            flush=True,
        )
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    original_source_scene_dir = args.scene_dir.resolve()
    if args.source_blend is not None and not args.source_blend.is_file():
        parser.error(f"source blend not found: {args.source_blend}")
    geometry_profile_payload: dict[str, Any] | None = None
    geometry_scene_dir = original_source_scene_dir
    if args.geometry_profile == "ir_semantic_lod_v1":
        if (original_source_scene_dir / "ir_scene_domain.json").is_file():
            parser.error("--geometry-profile=ir_semantic_lod_v1 requires an authoring scene, not an effective scene")
        if args.source_blend is None:
            parser.error("--source-blend is required for the default ir_semantic_lod_v1 geometry profile")
        geometry_profile_dir = (args.geometry_profile_dir or (args.out / "ir_geometry")).resolve()
        geometry_command = [
            sys.executable, str(GEOMETRY_PROFILE_BUILDER),
            "--source-scene-dir", str(original_source_scene_dir),
            "--source-blend", str(args.source_blend.resolve()),
            "--out", str(geometry_profile_dir), "--profile", args.geometry_profile,
        ]
        if args.rebuild_geometry_profile:
            geometry_command.append("--force")
        if args.resume_geometry_profile:
            geometry_command.append("--resume")
        print(f"[queue] geometry profile {args.geometry_profile} -> {geometry_profile_dir}", flush=True)
        try:
            subprocess.run(geometry_command, cwd=REPO_ROOT, check=True)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"IR geometry profile build failed: {exc}") from exc
        profile_path = geometry_profile_dir / "ir_geometry_profile.json"
        geometry_profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        geometry_scene_dir = Path(geometry_profile_payload["derived_scene_dir"]).resolve()
        args.source_blend = Path(geometry_profile_payload["derived_blend"]).resolve()
    if args.pbr_gt_provider == "blender_aov" and not args.observations_only and args.source_blend is None:
        parser.error("--source-blend is required when --pbr-gt-provider=blender_aov")
    if (geometry_scene_dir / "ir_scene_domain.json").is_file():
        effective_contract = validate_ir_effective_scene(geometry_scene_dir)
        if effective_contract.get("surface_domain") != args.surface_domain:
            parser.error("prepared effective scene does not match --surface-domain")
        effective_scene_dir = geometry_scene_dir
    else:
        effective_scene_dir = (args.effective_scene_dir or (args.out / "ir_effective_scene")).resolve()
        effective_contract = materialize_ir_effective_scene(
            geometry_scene_dir, effective_scene_dir, surface_domain=args.surface_domain,
            geometry_profile=geometry_profile_payload, reuse_existing=True,
        )
    args.source_scene_dir = original_source_scene_dir
    args.geometry_scene_dir = geometry_scene_dir
    args.geometry_profile_payload = geometry_profile_payload
    args.scene_dir = effective_scene_dir
    args.effective_scene_digest = str(effective_contract["effective_scene_digest"])
    graph = json.loads((args.scene_dir / "viewpoint_graph.json").read_text(encoding="utf-8"))
    scene_hash = _scene_content_sha256(args.scene_dir)
    manifest_path = args.out / "queue_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = _new_manifest(args, graph, scene_hash)
        # Queue v2 manifests created before bounded subprocess batches did not
        # record this field. Adopt the current default while preserving their
        # shuffle/scene identity so an interrupted queue can resume safely.
        existing_configuration = dict(manifest.get("configuration") or {})
        completed_chunks = [
            chunk for chunk in manifest.get("chunks") or [] if chunk.get("status") == "complete"
        ]
        legacy_published_prefix = any(
            (args.out / str(chunk.get("relative_dir") or "") / "index.jsonl").is_file()
            and (args.out / str(chunk.get("relative_dir") or "") / "index.jsonl").stat().st_size > 0
            for chunk in manifest.get("chunks") or []
        )
        if "storage_layout" not in existing_configuration:
            if args.scheduler == "rolling" and not completed_chunks and not legacy_published_prefix:
                existing_configuration["storage_layout"] = _ROLLING_STORAGE_LAYOUT
            elif args.scheduler == "chunked":
                existing_configuration["storage_layout"] = "chunk_frame_v1"
        if "observation_variant" not in existing_configuration:
            existing_configuration["observation_variant"] = (
                "cuda_ad_spectral_polarized" if existing_configuration.get("polarized")
                else "cuda_ad_spectral"
            )
        if "texture_max_resolution" not in existing_configuration:
            # Queue manifests written before IR texture capping have no
            # corresponding rendered output in this failure-recovery case.
            # Adopt the safe profile only when no completed chunk exists;
            # never silently mix capped and uncapped observations.
            if not completed_chunks and not legacy_published_prefix:
                existing_configuration["texture_max_resolution"] = int(args.texture_max_resolution)
        # Before pass-specific sampling was introduced, ``spp`` was used for
        # all three observation passes and the integrator depth was fixed at
        # eight.  Preserve that exact rendering contract on resume.
        for key in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp"):
            existing_configuration.setdefault(key, int(existing_configuration.get("spp", args.spp)))
        existing_configuration.setdefault("max_depth", 8)
        # Batch size is an execution-safety knob, not dataset identity. Permit
        # lowering it after a CUDA subprocess failure while keeping scene,
        # shuffle, resolution, spp, and band immutable.
        existing_configuration["render_batch_size"] = args.render_batch_size
        manifest["configuration"] = existing_configuration
        for key in (
            "schema", "scene_dir", "source_scene_dir", "surface_domain", "effective_scene_digest",
            "scene_content_sha256", "frame_count", "shuffle_seed", "chunk_size", "configuration",
        ):
            if manifest.get(key) != expected.get(key):
                raise SystemExit(
                    f"existing queue is stale or incompatible at {key}; "
                    "use a new output directory"
                )
        for chunk in manifest["chunks"]:
            if chunk["status"] == "running":
                chunk["status"] = "pending"
        # A prior parent process cannot have live worker threads after restart.
        manifest.pop("active_chunks", None)
        manifest.pop("active_chunk_id", None)
    else:
        manifest = _new_manifest(args, graph, scene_hash)

    for chunk in manifest["chunks"]:
        chunk_dir = args.out / chunk["relative_dir"]
        if _chunk_complete(
            chunk_dir, chunk["frame_count"], observations_only=args.observations_only, polarized=args.polar, surface_domain=args.surface_domain
        ):
            chunk["status"] = "complete"
            chunk.setdefault("completed_at", _utc_now())
    manifest["updated_at"] = _utc_now()
    _atomic_json(manifest_path, manifest)
    completed_rows = _refresh_global_exports(args.out, manifest)
    print(f"[queue] frames={manifest['frame_count']} chunks={len(manifest['chunks'])} "
          f"complete_frames={len(completed_rows)} seed={manifest['shuffle_seed']}", flush=True)
    if args.plan_only:
        planned = [chunk for chunk in manifest["chunks"] if chunk["status"] != "complete"]
        if args.max_chunks is not None:
            planned = planned[:args.max_chunks]
        print(
            f"[queue] plan pending_chunks={len(planned)} workers={args.parallel_chunks} "
            f"gpus={','.join(str(index) for index in args.gpu_indices[:args.parallel_chunks])}",
            flush=True,
        )
        return 0

    if args.scheduler == "rolling":
        try:
            smoke = _smoke_mitsuba_runtime(
                args.mitsuba_runtime_info, gpu_index=args.gpu_indices[0], polarized=bool(args.polar),
                observation_variant=args.observation_variant,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            f"[queue] runtime smoke PASS gpu={args.gpu_indices[0]} "
            f"variant={smoke['variant']} module={smoke['mitsuba_module']}", flush=True,
        )
        print(
            f"[queue] rolling scheduler frames={manifest['frame_count']} workers={args.parallel_chunks} "
            f"lease_size={args.lease_size} gpus={','.join(str(index) for index in args.gpu_indices[:args.parallel_chunks])}",
            flush=True,
        )
        rolling_returncode = _run_rolling_scheduler(args, manifest)
        if rolling_returncode:
            print("[queue] rolling scheduler finished with incomplete or failed frames; rerun to resume", flush=True)
            return int(rolling_returncode)
        all_complete = all(chunk.get("status") == "complete" for chunk in manifest["chunks"])
        if all_complete and not args.observations_only and args.pbr_gt_provider == "blender_aov":
            blender_out = args.out / "blender_gt"
            blender_command = _blender_gt_command(args, blender_out)
            print(f"[queue] Blender PBR GT -> {blender_out}", flush=True)
            result = subprocess.run(blender_command, cwd=REPO_ROOT)
            if result.returncode != 0:
                return int(result.returncode)
            result = subprocess.run([
                sys.executable, str(ASSEMBLE_APP), "--dataset", str(args.out),
                "--blender-gt", str(blender_out), "--effective-scene", str(args.scene_dir),
            ], cwd=REPO_ROOT)
            if result.returncode != 0:
                return int(result.returncode)
            manifest["blender_gt"] = {
                "provider": "blender_aov", "path": str(blender_out.resolve()),
                "effective_scene_digest": args.effective_scene_digest, "completed_at": _utc_now(),
            }
            manifest["updated_at"] = _utc_now()
            _atomic_json(manifest_path, manifest)
        print("[queue] rolling scheduler stopped normally", flush=True)
        return 0

    processed = 0
    pending_chunks = [chunk for chunk in manifest["chunks"] if chunk["status"] != "complete"]
    if args.max_chunks is not None:
        pending_chunks = pending_chunks[:args.max_chunks]
    worker_gpus = deque(args.gpu_indices[:args.parallel_chunks])
    pending = deque(pending_chunks)
    inflight: dict[Future[dict[str, Any]], tuple[dict[str, Any], int]] = {}
    scheduler_failed = False
    scheduler_returncode = 0

    def _persist_scheduler_state() -> None:
        active = [
            {
                "chunk_id": int(chunk["chunk_id"]),
                "gpu_index": int(gpu),
                "started_at": chunk.get("started_at"),
            }
            for chunk, gpu in inflight.values()
        ]
        if active:
            manifest["active_chunks"] = sorted(active, key=lambda item: item["gpu_index"])
        else:
            manifest.pop("active_chunks", None)
        # v2 had only one active ID.  Keep it as a compatibility hint for a
        # single in-flight worker, but never make it authoritative again.
        if len(active) == 1:
            manifest["active_chunk_id"] = active[0]["chunk_id"]
        else:
            manifest.pop("active_chunk_id", None)
        manifest["execution"] = {
            "gpu_indices": list(args.gpu_indices),
            "parallel_chunks": int(args.parallel_chunks),
            "mitsuba_runtime": dict(args.mitsuba_runtime_info),
            "updated_at": _utc_now(),
        }
        manifest["updated_at"] = _utc_now()
        _atomic_json(manifest_path, manifest)

    def _submit_available(executor: ThreadPoolExecutor) -> None:
        while pending and worker_gpus and not scheduler_failed:
            chunk = pending.popleft()
            gpu_index = worker_gpus.popleft()
            chunk["status"] = "running"
            chunk["started_at"] = _utc_now()
            chunk["worker_gpu_index"] = int(gpu_index)
            chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
            future = executor.submit(
                _run_chunk_worker, args, chunk, gpu_index=gpu_index,
            )
            inflight[future] = (chunk, gpu_index)
            print(
                f"[queue] dispatch gpu={gpu_index} chunk={int(chunk['chunk_id']):03d} "
                f"frames={chunk['frame_count']} attempt={chunk['attempts']} "
                f"batches={math.ceil(int(chunk['frame_count']) / args.render_batch_size)}",
                flush=True,
            )
        _persist_scheduler_state()

    if pending:
        try:
            smoke = _smoke_mitsuba_runtime(
                args.mitsuba_runtime_info, gpu_index=args.gpu_indices[0], polarized=bool(args.polar),
                observation_variant=args.observation_variant,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(
            f"[queue] runtime smoke PASS gpu={args.gpu_indices[0]} "
            f"variant={smoke['variant']} module={smoke['mitsuba_module']}",
            flush=True,
        )
        print(
            f"[queue] scheduler chunks={len(pending)} workers={args.parallel_chunks} "
            f"gpus={','.join(str(index) for index in args.gpu_indices[:args.parallel_chunks])}",
            flush=True,
        )
        with ThreadPoolExecutor(
            max_workers=args.parallel_chunks, thread_name_prefix="ir-render-chunk",
        ) as executor:
            _submit_available(executor)
            while inflight:
                finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for future in finished:
                    chunk, gpu_index = inflight.pop(future)
                    worker_gpus.append(gpu_index)
                    try:
                        result = future.result()
                        chunk_dir = Path(result["chunk_dir"])
                        _adopt_render_input_audit(
                            args.out, chunk_dir,
                            effective_scene_digest=args.effective_scene_digest, polarized=args.polar,
                        )
                        chunk["status"] = "complete"
                        chunk["completed_at"] = _utc_now()
                        chunk.pop("returncode", None)
                        chunk.pop("failure", None)
                        processed += 1
                        _persist_scheduler_state()
                        rows = _refresh_global_exports(args.out, manifest)
                        print(
                            f"[queue] complete gpu={gpu_index} chunk={int(chunk['chunk_id']):03d} "
                            f"complete_frames={len(rows)}",
                            flush=True,
                        )
                    except Exception as exc:  # record all worker failures for resume
                        code = int(getattr(exc, "returncode", 1) or 1)
                        chunk["status"] = "failed"
                        chunk["returncode"] = code
                        chunk["failure"] = str(exc)
                        chunk["failed_at"] = _utc_now()
                        scheduler_failed = True
                        scheduler_returncode = scheduler_returncode or code
                        _persist_scheduler_state()
                        print(
                            f"[queue] failed gpu={gpu_index} chunk={int(chunk['chunk_id']):03d} "
                            f"returncode={code}: {exc}",
                            flush=True,
                        )
                # A failure stops further dispatch. Existing workers are still
                # allowed to finish and commit their independent complete chunks.
                _submit_available(executor)
    if scheduler_failed:
        print(
            f"[queue] stopped after failed chunk; completed_chunks={processed}; "
            "rerun the same command to resume unfinished chunks",
            flush=True,
        )
        return scheduler_returncode or 1
    all_complete = all(chunk.get("status") == "complete" for chunk in manifest["chunks"])
    if all_complete and not args.observations_only and args.pbr_gt_provider == "blender_aov":
        blender_out = args.out / "blender_gt"
        blender_command = _blender_gt_command(args, blender_out)
        print(f"[queue] Blender PBR GT -> {blender_out}", flush=True)
        result = subprocess.run(blender_command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return int(result.returncode)
        assemble_command = [
            sys.executable, str(ASSEMBLE_APP), "--dataset", str(args.out),
            "--blender-gt", str(blender_out), "--effective-scene", str(args.scene_dir),
        ]
        result = subprocess.run(assemble_command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return int(result.returncode)
        manifest["blender_gt"] = {
            "provider": "blender_aov", "path": str(blender_out.resolve()),
            "effective_scene_digest": args.effective_scene_digest,
            "completed_at": _utc_now(),
        }
        manifest["updated_at"] = _utc_now()
        _atomic_json(manifest_path, manifest)
    print(f"[queue] stopped normally processed_chunks={processed}", flush=True)
    return 0


def _blender_gt_command(args: argparse.Namespace, blender_out: Path) -> list[str]:
    """Build the strict GT command from the completed observation contract."""
    pose_manifest = args.out / "index.jsonl"
    if not pose_manifest.is_file():
        raise FileNotFoundError(f"completed observation pose manifest is absent: {pose_manifest}")
    return [
        sys.executable, str(BLENDER_LAUNCHER), "--background", str(args.source_blend.resolve()),
        "--python", str(args.blender_gt_script.resolve()), "--",
        "--scene-graph", str(args.scene_dir / "viewpoint_graph.json"),
        "--out", str(blender_out), "--width", str(args.width), "--height", str(args.height),
        "--fov", str(args.fov), "--samples", str(args.blender_samples),
        "--ir-scene-domain", str(args.scene_dir / "ir_scene_domain.json"),
        "--pose-manifest", str(pose_manifest), "--require-pose-manifest", "--resume",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
