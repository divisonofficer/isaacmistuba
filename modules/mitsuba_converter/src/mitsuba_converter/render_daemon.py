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
from pathlib import Path
import math
import shutil
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, unquote, urlparse
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


RenderFn = Callable[..., ObservationBundleManifest]
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _safe_sort_ts(value: str | None) -> tuple[int, str]:
    return (1 if value else 0, value or "")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _maybe_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


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


def _spawn_preview_render(key: str, render_fn: Any) -> None:
    """Run `render_fn()` in a background daemon thread under inflight tracking."""
    def _task() -> None:
        try:
            render_fn()
        except Exception as exc:
            print(
                f"[daemon] preview render failed ({key}): {exc}",
                file=sys.stderr,
                flush=True,
            )
        finally:
            _release_preview_inflight(key)

    threading.Thread(
        target=_task,
        daemon=True,
        name=f"preview-{key.replace(':', '-').replace('/', '-')}",
    ).start()


class RenderDaemon:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        host: str = "127.0.0.1",
        port: int = 8765,
        variant: str = "cuda_ad_spectral",
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

        asset_root = Path(__file__).resolve().parent
        self._static_dir = asset_root / "static"
        self._spa_dir = asset_root / "static" / "app"

    def _isaac_scene_catalog_path(self) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "isaac_scene_catalog.json"

    def _isaac_command_telemetry_path(self) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "isaac_command_telemetry.jsonl"

    def _render_options_path(self, scene_id: str) -> Path:
        return self.repo_root / "out" / "control_plane_cache" / "scene_render_options" / f"{scene_id}.json"

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
        scene_ctx = self._scene_telemetry_context(job.render_request.scene_state.scene_id)
        timestamp = job.status.finished_at or job.status.started_at or job.status.submitted_at or _utc_now_iso()
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
            "elapsed_s": self._seconds_between(job.status.submitted_at, timestamp),
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
            self._record_isaac_command_telemetry(command, event_type="complete")
            return self._isaac_command_payload(command)

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

    def start(self) -> None:
        if self._server is not None:
            return

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
                    self.daemon._handle_get(self)
                except Exception:
                    self._log_exception("GET")
                    raise

            def do_POST(self) -> None:  # noqa: N802
                try:
                    self.daemon._handle_post(self)
                except Exception:
                    self._log_exception("POST")
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
    ) -> RenderJobAccepted:
        render_request, render_settings_variant = _extract_render_settings_variant(render_request)
        chosen_variant = str(variant or render_settings_variant or self.variant)
        runtime_override_payload = dict(runtime_overrides or {})
        request_payload = render_request_to_payload(render_request)
        scene_cache_key = self._scene_cache_key(render_request, chosen_variant)

        with self._condition:
            if render_request.job_id in self._jobs:
                raise ValueError(f"Duplicate job_id already queued or rendered: {render_request.job_id}")

            submitted_at = _utc_now_iso()
            cache_stats = self._scene_cache_stats.setdefault(scene_cache_key, {"submissions": 0, "runs": 0})
            cache_stats["submissions"] += 1
            cache_stats["last_submitted_at"] = submitted_at

            status = RenderJobStatus(
                job_id=render_request.job_id,
                frame_id=render_request.frame_id,
                status="queued",
                submitted_at=submitted_at,
                progress_stage="queued",
                extras={
                    "request_id": render_request.request_id,
                    "variant": chosen_variant,
                    "scene_cache_key": scene_cache_key,
                    "scene_cache_submissions": int(cache_stats["submissions"]),
                    "sync_mode": str(render_request.extras.get("sync_mode") or "unknown"),
                    "sync_policy": str(render_request.extras.get("sync_policy") or "default"),
                },
            )
            job = _QueuedJob(
                render_request=render_request,
                status=status,
                request_payload=request_payload,
                variant=chosen_variant,
                runtime_overrides=runtime_override_payload,
            )
            self._jobs[render_request.job_id] = job
            self._pending.append(render_request.job_id)
            queue_position = len(self._pending)
            self._persist_request_unlocked(job)
            self._persist_status_unlocked(job)
            self._condition.notify_all()
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
                return RenderJobStatus(**render_job_status_to_payload(job.status))
            if job.status.status == "running":
                raise RuntimeError("Queued cancellation is supported, but running renders are not interruptible in v1.")
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

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/health":
                self._send_json(handler, HTTPStatus.OK, self._health_payload())
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
            return f"{base}{pass_suffix}{spp_suffix}{count_suffix}."
        if stage == "rendering":
            return f"Ray tracing{pass_suffix}{spp_suffix}{count_suffix}."
        if stage == "saving_output":
            return f"Writing EXR output{pass_suffix}{count_suffix}."
        if stage == "writing_manifest":
            return "Writing observation manifest."
        return stage.replace("_", " ").strip().capitalize()

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
                job.status.progress_stage = "starting"
            # Disk I/O outside the lock
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

                bundle = self.render_fn(
                    job.render_request,
                    repo_root=self.repo_root,
                    variant=job.variant,
                    progress_callback=lambda stage, payload=None: self._update_progress(job_id, stage, payload),
                )
                manifest_path = f"{bundle.bundle_root}/manifest.json"
                self._mark_succeeded(job_id, manifest_path=manifest_path)
            except Exception as exc:  # pragma: no cover - exercised in tests via failure path
                self._mark_failed(job_id, str(exc))

    def _mark_succeeded(self, job_id: str, *, manifest_path: str) -> None:
        with self._condition:
            job = self._jobs[job_id]
            job.status.status = "succeeded"
            job.status.finished_at = _utc_now_iso()
            job.status.progress_stage = "complete"
            job.status.manifest_path = manifest_path
            job.status.error = None
            # New observation bundles written — invalidate the bundle manifest cache
            self._bundle_manifest_cache = None
            self._bundle_manifest_cache_ts = 0.0
        self._update_job_render_timing_summary(job, manifest_path=manifest_path)
        # Disk I/O outside the lock
        self._persist_status_unlocked(job)
        with self._condition:
            self._condition.notify_all()
        self._record_render_job_telemetry(job, event_type="complete")
        self._append_job_log_line(job, event_type="complete", stage="complete", message="Job succeeded")

    def _mark_failed(self, job_id: str, error: str) -> None:
        with self._condition:
            job = self._jobs[job_id]
            job.status.status = "failed"
            job.status.finished_at = _utc_now_iso()
            job.status.progress_stage = "failed"
            job.status.error = error
            self._condition.notify_all()
        # Disk I/O outside the lock
        self._persist_status_unlocked(job)
        self._record_render_job_telemetry(job, event_type="failed")
        self._append_job_log_line(job, event_type="failed", stage="failed", message=error or "Job failed")

    def _update_progress(self, job_id: str, stage: str, payload: Mapping[str, Any] | None) -> None:
        command_id = None
        progress_counts = None
        message = self._isaac_render_stage_message(stage, payload)
        job_for_persist = None
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
            command_id = _maybe_str(job.status.extras.get("isaac_command_id"))
            job_for_persist = job
            self._condition.notify_all()
        # Disk I/O outside the lock — prevents blocking HTTP handlers during rendering
        if job_for_persist is not None:
            self._persist_status_unlocked(job_for_persist)
            self._record_render_job_telemetry(job_for_persist, event_type="progress")
            self._append_job_log_line(job_for_persist, event_type="progress", stage=stage, message=message)
        if command_id:
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

    def _append_job_log_line(self, job: "_QueuedJob", *, event_type: str, stage: str, message: str) -> None:
        try:
            log_path = self._job_log_path(job.render_request.job_id)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            ts = _utc_now_iso()
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
            handler.end_headers()
            handler.wfile.write(payload)
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

    def _enqueue_curated_render(self, mat: Any, material_id: str) -> dict[str, Any] | None:
        """Spawn the curated-preview Mitsuba render in a BG thread and create
        a tracked job entry. Returns the job dict (or None if a render for
        this material was already in flight)."""
        from .sphere_preview import (
            _build_scene_dict,
            _ensure_mitsuba_variant,
            _mitsuba_render_lock,
            _pick_variant_for,
            _render_to_png,
            _supersample_default,
        )

        cache_dir = self._preview_cache_dir()
        out = cache_dir / "curated" / f"{material_id}.png"
        key = f"curated:{material_id}"

        if not _claim_preview_inflight(key):
            return None  # render already in flight; an existing job covers it

        job = _create_material_job(
            key=f"curated/{material_id}",
            title="프리뷰 재렌더",
            subtitle=getattr(mat, "display_name", material_id),
            action="rerender",
        )
        job_id = job["id"]

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
                spp = get_material_preview_spp(default=2048)
                ss = _supersample_default()
                target_size = 192
                render_size = target_size * ss
                with _mitsuba_render_lock:
                    _ensure_mitsuba_variant(variant)
                    _update_material_job_stage(
                        job_id, "scene_build",
                        f"씬 dict 빌드 중 (spp={spp}, render={render_size}px)",
                    )
                    scene_dict = _build_scene_dict(bsdf_spec, size=render_size, spp=spp)

                    def _progress(current: int, total: int) -> None:
                        pct = int(round(current / max(total, 1) * 100))
                        _update_material_job_stage(
                            job_id,
                            "rendering",
                            f"Mitsuba 렌더 중 ({material_id}) {current}/{total} · {pct}% · spp={spp}",
                        )
                        _update_material_job_progress(job_id, current, total)

                    _update_material_job_stage(
                        job_id, "rendering", f"Mitsuba 렌더 중 ({material_id}) 0/0 · spp={spp}"
                    )
                    _render_to_png(
                        scene_dict, out, variant=variant, spp=spp,
                        progress_cb=_progress,
                        supersample=ss, target_size=target_size,
                    )
                _update_material_job_stage(job_id, "saved", "PNG 저장 완료")
                _finish_material_job(job_id, "success")
            except Exception as exc:
                _finish_material_job(job_id, "failed", str(exc))
                raise

        _spawn_preview_render(key, _render_curated)
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
        from .sphere_preview import get_measured_preview

        key = f"measured:{dataset_id}:{material_id}"
        if not _claim_preview_inflight(key):
            # Already rendering — surface the existing material_job so the UI
            # has something to show instead of a silent 200 with no row.
            existing_key = f"{dataset_id}/{material_id}"
            with _material_jobs_lock:
                for j in _material_jobs:
                    if j.get("key") == existing_key and j.get("status") == "running":
                        return dict(j)
            return None
        job = _create_material_job(
            key=f"{dataset_id}/{material_id}",
            title="프리뷰 재렌더",
            subtitle=display_name,
            action="rerender",
        )
        job_id = job["id"]

        if not measured_file_path:
            _release_preview_inflight(key)
            _finish_material_job(job_id, "failed", "measured_file_path missing")
            return job

        from .sphere_preview import _mitsuba_render_lock

        repo_root = self.repo_root
        cache_dir = self._preview_cache_dir()

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
                with _mitsuba_render_lock:
                    _update_material_job_stage(
                        job_id, "rendering", f"Mitsuba 렌더 중 ({material_id}) · spp={spp}"
                    )
                    result = get_measured_preview(
                        dataset_id, material_id, measured_file_path, repo_root, cache_dir,
                        spp=spp,
                    )
                if result.path is None:
                    status_msg = {
                        "plugin_unavailable": (
                            "GPU(CUDA) 변종이 빌드되지 않았거나, 이 재질이 패치된 "
                            "Mitsuba 빌드를 요구합니다 (hpBRDF 등)"
                        ),
                        "mitsuba_unavailable": "Mitsuba 임포트 실패",
                        "load_error": "파일 파싱 실패 (포맷 불일치)",
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

        _spawn_preview_render(key, _render_measured)
        return job

    def _invalidate_measured_files(self, dataset_id: str, material_id: str) -> list[str]:
        """Best-effort delete of measured cache PNGs.

        Cache filenames follow ``{safe_id}_{size}.png`` where safe_id is a
        sanitized form of dataset_id+material_id; we glob anything with the
        material_id substring to catch all sizes / variants.
        """
        cache_dir = self._preview_cache_dir() / "measured"
        if not cache_dir.exists():
            return []
        removed: list[str] = []
        # Match "{anything containing dataset_id and material_id}*.png"
        for p in cache_dir.glob("*.png"):
            stem = p.stem
            if dataset_id in stem and material_id in stem:
                try:
                    p.unlink()
                    removed.append(str(p.relative_to(self.repo_root)))
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
        """Serve a Mitsuba-rendered sphere preview PNG for a preset or measured BSDF."""
        from .sphere_preview import get_preset_preview, get_measured_preview, peek_measured_preview

        cache_dir = self.repo_root / "out" / "material_previews"
        # /api/material-preview/curated/{material_id}
        if path.startswith("/api/material-preview/curated/"):
            material_id = path[len("/api/material-preview/curated/"):].strip("/")
            self._serve_curated_preview(handler, material_id, cache_dir)
            return
        # /api/material-preview/preset/{bsdf_type}
        if path.startswith("/api/material-preview/preset/"):
            bsdf_type = path[len("/api/material-preview/preset/"):].strip("/")
            png_path = get_preset_preview(bsdf_type, cache_dir)
            if png_path is None:
                self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Preview unavailable for preset: {bsdf_type}"})
                return
            self._send_bytes(handler, HTTPStatus.OK, png_path.read_bytes(), content_type="image/png")
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
            # Cache hit → serve immediately. Cache miss → delegate to the same
            # enqueue helper that the invalidate POST uses. Critically this
            # path used to spawn a BG render directly with no job entry, so
            # GET-triggered renders (e.g. card image fetches on a fresh page
            # load) finished invisibly — they never showed up in the bottom
            # panel and `_finish_material_job` had nothing to mark complete.
            cached = peek_measured_preview(dataset_id, material_id, file_param, self.repo_root, cache_dir)
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
            self._enqueue_measured_render(dataset_id, material_id, file_param, display_name)
            self._send_json(
                handler,
                HTTPStatus.ACCEPTED,
                {"status": "rendering", "dataset_id": dataset_id, "material_id": material_id},
                extra_headers={"X-Preview-Status": "rendering", "Retry-After": "2"},
            )
            return
        self._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"Unknown material-preview path: {path}"})

    def _serve_curated_preview(
        self,
        handler: BaseHTTPRequestHandler,
        material_id: str,
        cache_dir: Path,
    ) -> None:
        """Serve the pre-baked curated material PNG, falling back to on-demand render."""
        from .curated_library import curated_preview_path, get_curated_material

        mat = get_curated_material(material_id)
        if mat is None:
            self._send_json(
                handler,
                HTTPStatus.NOT_FOUND,
                {"error": f"Unknown curated material: {material_id}"},
                extra_headers={"X-Preview-Status": "unknown"},
            )
            return

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
        out = cache_dir / "curated" / f"{material_id}.png"
        if out.exists():
            self._send_bytes(
                handler,
                HTTPStatus.OK,
                out.read_bytes(),
                content_type="image/png",
                extra_headers={"X-Preview-Status": "ok"},
            )
            return

        # Cache miss — delegate to the same enqueue path used by invalidate.
        # That path correctly sets the Mitsuba variant inside the render lock
        # before calling `_build_scene_dict` (which constructs
        # `mi.ScalarTransform4f` and would otherwise raise "Cannot access
        # 'ScalarTransform4f' before setting a variant"), AND creates a
        # tracked material-job so the frontend bottom panel sees this render
        # alongside ones triggered via invalidate.
        self._enqueue_curated_render(mat, material_id)
        self._send_json(
            handler,
            HTTPStatus.ACCEPTED,
            {"status": "rendering", "material_id": material_id},
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
        session = self._isaac_session
        return {
            "status": "ok",
            "base_url": self.base_url,
            "worker_state": worker_state,
            "active_stage": active_stage,
            "queue_length": queue_length,
            "variant": variant,
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
        """Read job_status.json files from disk with a 2-second TTL cache."""
        now = time.monotonic()
        if self._job_status_cache is not None and (now - self._job_status_cache_ts) < 2.0:
            return self._job_status_cache  # type: ignore[return-value]
        records: dict[str, RenderJobStatus] = {}
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            self._job_status_cache = records
            self._job_status_cache_ts = now
            return records
        for status_path in root.glob("*/job_status.json"):
            try:
                status = read_render_job_status(status_path)
            except Exception:
                continue
            records[status.job_id] = status
        self._job_status_cache = records
        self._job_status_cache_ts = now
        return records

    def _invalidate_job_status_cache(self) -> None:
        """Call this whenever a new job is submitted or status changes to force cache refresh."""
        self._job_status_cache = None
        self._job_status_cache_ts = 0.0

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
        is_stuck = False
        ref_ts = status.submitted_at
        if ref_ts:
            try:
                ref_dt = datetime.fromisoformat(ref_ts).astimezone(_tz.utc)
                age_s = max(0.0, (_utc_now() - ref_dt).total_seconds())
                if status.status == "running" and status.started_at:
                    started_dt = datetime.fromisoformat(status.started_at).astimezone(_tz.utc)
                    is_stuck = (_utc_now() - started_dt).total_seconds() >= 600.0
            except Exception:
                pass
        return {
            "job_id": status.job_id,
            "frame_id": status.frame_id,
            "status": status.status,
            "submitted_at": status.submitted_at,
            "started_at": status.started_at,
            "finished_at": status.finished_at,
            "progress_stage": status.progress_stage,
            "manifest_path": status.manifest_path,
            "error": status.error,
            "scene_id": scene_id,
            "scene_version": scene_version,
            "queue_position": queue_position,
            "age_s": age_s,
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
        """Glob + deserialize observation bundle manifests with a 3-second TTL cache."""
        now = time.monotonic()
        if (
            not force_refresh
            and self._bundle_manifest_cache is not None
            and (now - self._bundle_manifest_cache_ts) < 3.0
        ):
            return self._bundle_manifest_cache  # type: ignore[return-value]
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            result: list[ObservationBundleManifest] = []
            self._bundle_manifest_cache = result
            self._bundle_manifest_cache_ts = now
            return result
        bundles: list[ObservationBundleManifest] = []
        for manifest_path in root.glob("*/observations/*/manifest.json"):
            try:
                bundles.append(read_observation_bundle_manifest(manifest_path))
            except Exception:
                continue
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
            if job["status"] == "succeeded" and job.get("started_at") and job.get("finished_at")
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
                _parse_ts(j["finished_at"]) - _parse_ts(j["started_at"])
                for j in recent_completed
                if _parse_ts(j["finished_at"]) > _parse_ts(j["started_at"])
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
        script_path = str(self.repo_root / "apps" / "isaac_capture_current_view_request.py").replace("\\", "\\\\")
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
        if any(token in key for token in ("wall", "shell", "ceiling", "roof")):
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
        snapshot_ref = (
            _maybe_str(scene_record.get("scene_snapshot_ref"))
            or (session.scene_snapshot_ref if session is not None else None)
            or (session.shape_map_ref if session is not None else None)
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
    variant: str = "cuda_ad_spectral",
) -> RenderDaemon:
    daemon = RenderDaemon(repo_root=repo_root, host=host, port=port, variant=variant)
    daemon.start()
    return daemon
