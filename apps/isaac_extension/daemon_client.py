"""Robomituba Isaac Extension — daemon HTTP client."""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
import webbrowser

# Allow importing from repo apps roots when running inside Isaac Sim runtime copies.
_PATH_CANDIDATES = [
    Path(__file__).resolve().parent.parent,
]
_repo_root_env = os.environ.get("ROBOMITUBA_ROOT") or os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
if _repo_root_env:
    _PATH_CANDIDATES.append(Path(_repo_root_env) / "apps")
for _candidate in _PATH_CANDIDATES:
    try:
        if _candidate.exists() and str(_candidate) not in sys.path:
            sys.path.insert(0, str(_candidate))
    except Exception:
        continue

from isaac_capture_current_view_request import _http_json  # noqa: E402

DEFAULT_UNC_REPO_ROOT = r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"
DEFAULT_RENDER_TIMEOUT_S = 1800.0
DEFAULT_LOAD_SCENE_TIMEOUT_S = 1800.0
DEFAULT_FULL_MITSUBA_SCENE_REF = "out/moorelane_full_cam03_rgb_all/scene_full_sanitized_direct.xml"
_FULL_SCENE_SIBLING_CANDIDATES = (
    "scene_full_sanitized_direct.xml",
    "scene.xml",
    "scene_gpu_safe.xml",
)
ProgressCallback = Callable[[str, str, str, str, dict[str, int] | None], None]


def resolve_windows_repo_root(repo_root: str | None = None) -> str:
    return (
        repo_root
        or os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
        or os.environ.get("ROBOMITUBA_ROOT")
        or DEFAULT_UNC_REPO_ROOT
    )


DEFAULT_REPO_ROOT = resolve_windows_repo_root()
DEFAULT_RENDER_PREP_TIMEOUT_S = 300.0
_SENSOR_REGISTER_SUPPRESSED_UNTIL = 0.0
_LAST_VIEWPORT_SENSOR_REGISTER_SIGNATURE: tuple[Any, ...] | None = None
_LAST_VIEWPORT_SENSOR_REGISTER_TS = 0.0
_SENSOR_REGISTER_REFRESH_INTERVAL_S = 30.0
_SENSOR_REGISTER_NO_SESSION_BACKOFF_S = 15.0
_CAMERA_WS_CLIENTS: dict[str, "_CameraTelemetryWebSocket"] = {}
_CAMERA_WS_CLIENTS_LOCK = threading.Lock()


def _is_windows_host() -> bool:
    return os.name == "nt"


def _classify_windows_path_mode(raw_path: str | None) -> str:
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


def _windows_local_cache_root() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "robomituba" / "scene_cache"
    return Path.home() / "AppData" / "Local" / "robomituba" / "scene_cache"


def _guess_scene_asset_root_from_stage(stage_path: Path) -> Path | None:
    try:
        resolved = stage_path.resolve(strict=False)
    except Exception:
        resolved = stage_path
    if resolved.parent.name.lower() == "usd":
        return resolved.parent.parent
    for parent in resolved.parents:
        if parent.name.lower() == "usd":
            return parent.parent
    return resolved.parent if resolved.parent != resolved else None


def _path_tree_signature(root: Path) -> dict[str, Any]:
    payload = {"exists": root.exists(), "bytes": 0, "file_count": 0, "latest_mtime_ns": 0}
    if not root.exists():
        return payload
    total_bytes = 0
    file_count = 0
    latest_mtime_ns = 0
    for candidate in root.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        total_bytes += int(stat.st_size)
        file_count += 1
        latest_mtime_ns = max(latest_mtime_ns, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))))
    payload["bytes"] = total_bytes
    payload["file_count"] = file_count
    payload["latest_mtime_ns"] = latest_mtime_ns
    return payload


def _source_signature_from_stats(stats: dict[str, Any]) -> str:
    if not stats.get("exists"):
        return "missing"
    return f"{int(stats.get('bytes', 0) or 0)}:{int(stats.get('file_count', 0) or 0)}:{int(stats.get('latest_mtime_ns', 0) or 0)}"


class _CameraTelemetryWebSocket:
    def __init__(self, daemon_url: str) -> None:
        self.daemon_url = daemon_url.rstrip("/")
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def send_json(self, payload: Mapping[str, Any], *, timeout_s: float) -> None:
        data = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        with self._lock:
            sock = self._sock
            if sock is None:
                sock = self._connect(timeout_s=timeout_s)
                self._sock = sock
            try:
                sock.settimeout(timeout_s)
                sock.sendall(self._frame(data))
            except Exception:
                self.close()
                raise

    def _connect(self, *, timeout_s: float) -> socket.socket:
        parsed = urlparse(self.daemon_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or (443 if scheme == "https" else 80))
        path_base = parsed.path.rstrip("/")
        path = f"{path_base}/isaac/session/camera_ws" if path_base else "/isaac/session/camera_ws"
        raw_sock = socket.create_connection((host, port), timeout=timeout_s)
        sock: socket.socket
        if scheme == "https":
            sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        else:
            sock = raw_sock
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = "\r\n".join(
            [
                f"GET {path} HTTP/1.1",
                f"Host: {host}:{port}",
                "Upgrade: websocket",
                "Connection: Upgrade",
                f"Sec-WebSocket-Key: {key}",
                "Sec-WebSocket-Version: 13",
                "\r\n",
            ]
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response and len(response) < 8192:
            chunk = sock.recv(1024)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("camera websocket upgrade failed")
        return sock

    def _frame(self, payload: bytes) -> bytes:
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x81])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.extend([0x80 | 126, *length.to_bytes(2, "big")])
        else:
            header.extend([0x80 | 127, *length.to_bytes(8, "big")])
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return bytes(header) + mask + masked


def _camera_ws_client(daemon_url: str | None = None) -> _CameraTelemetryWebSocket:
    url = _resolve_daemon_url(daemon_url)
    with _CAMERA_WS_CLIENTS_LOCK:
        client = _CAMERA_WS_CLIENTS.get(url)
        if client is None:
            client = _CameraTelemetryWebSocket(url)
            _CAMERA_WS_CLIENTS[url] = client
        return client


def _safe_symlink(source: Path, target: Path) -> bool:
    try:
        if target.exists() or target.is_symlink():
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(str(source), str(target), target_is_directory=source.is_dir())
        return True
    except Exception:
        return False


def _mirror_tree_windows(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("robocopy"):
        cmd = [
            "robocopy",
            str(source),
            str(target),
            "/MIR",
            "/R:1",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        if completed.returncode >= 8:
            raise RuntimeError(
                f"robocopy failed with exit code {completed.returncode}: {(completed.stderr or completed.stdout).strip()}"
            )
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _prepare_cache_target(target: Path) -> None:
    if target.is_symlink():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class _SceneTextureCacheLayout:
    scene_id: str
    source_stage_path: Path
    source_asset_root: Path
    source_usd_root: Path
    source_instances_root: Path
    source_texture_root: Path
    cache_scene_root: Path
    cache_asset_root: Path
    cache_usd_root: Path
    cache_instances_root: Path
    cache_texture_root: Path
    cache_manifest_path: Path
    cache_stage_path: Path


def _scene_texture_cache_layout(scene_id: str, source_stage_path: Path) -> _SceneTextureCacheLayout:
    source_asset_root = _guess_scene_asset_root_from_stage(source_stage_path)
    if source_asset_root is None:
        raise RuntimeError(f"Unable to infer asset root from stage path: {source_stage_path}")
    source_usd_root = source_asset_root / "USD"
    source_instances_root = source_asset_root / "Instances"
    source_texture_root = source_asset_root / "textures"
    relative_stage_path = source_stage_path.relative_to(source_asset_root)
    cache_scene_root = _windows_local_cache_root() / scene_id
    cache_asset_root = cache_scene_root / source_asset_root.name
    cache_usd_root = cache_asset_root / "USD"
    cache_instances_root = cache_asset_root / "Instances"
    cache_texture_root = cache_asset_root / "textures"
    cache_manifest_path = cache_scene_root / "cache_manifest.json"
    cache_stage_path = cache_asset_root / relative_stage_path
    return _SceneTextureCacheLayout(
        scene_id=scene_id,
        source_stage_path=source_stage_path,
        source_asset_root=source_asset_root,
        source_usd_root=source_usd_root,
        source_instances_root=source_instances_root,
        source_texture_root=source_texture_root,
        cache_scene_root=cache_scene_root,
        cache_asset_root=cache_asset_root,
        cache_usd_root=cache_usd_root,
        cache_instances_root=cache_instances_root,
        cache_texture_root=cache_texture_root,
        cache_manifest_path=cache_manifest_path,
        cache_stage_path=cache_stage_path,
    )


def _read_cache_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _combined_cache_signature(*parts: dict[str, Any]) -> str:
    serialized: list[str] = []
    for part in parts:
        serialized.append(_source_signature_from_stats(part))
    return "|".join(serialized)


def _register_scene_cache_status(
    scene_id: str,
    *,
    usd_stage_path: str,
    cache_payload: dict[str, Any],
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> None:
    try:
        register_scene_with_daemon(
            daemon_url=daemon_url,
            scene_id=scene_id,
            usd_stage_path=usd_stage_path,
            timeout_s=timeout_s,
            extra_fields=cache_payload,
        )
    except Exception:
        return


def _resolve_daemon_url(daemon_url: str | None = None) -> str:
    return (daemon_url or os.environ.get("ROBOMITUBA_DAEMON_URL") or DEFAULT_DAEMON_URL).rstrip("/")


def _snapshot_payload(snapshot: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_state_snapshot_to_payload

    return {"isaac_state": isaac_state_snapshot_to_payload(snapshot)}


def _session_open_payload(session_open: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_session_open_to_payload

    return isaac_session_open_to_payload(session_open)


def _state_patch_payload(state_patch: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_state_patch_to_payload

    return isaac_state_patch_to_payload(state_patch)


def _material_patch_payload(material_patch: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_material_patch_to_payload

    return isaac_material_patch_to_payload(material_patch)


def _sensor_spec_payload(sensor_spec: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_sensor_spec_to_payload

    return isaac_sensor_spec_to_payload(sensor_spec)


def _capture_request_payload(capture_request: Any) -> dict[str, Any]:
    from robomituba_bridge import isaac_capture_request_to_payload

    return isaac_capture_request_to_payload(capture_request)


def _require_isaac_context():
    import omni.usd  # type: ignore

    return omni.usd.get_context()


def _repo_relative_to_local_path(path: str, *, repo_root: str = DEFAULT_REPO_ROOT) -> str:
    repo_root = resolve_windows_repo_root(repo_root)
    if not path:
        raise ValueError("Path must not be empty.")
    raw = str(path)
    if PurePosixPath(raw).is_absolute():
        return raw
    if raw.startswith(("file:", "omniverse://", "\\\\")) or (len(raw) > 1 and raw[1] == ":"):
        return raw
    return str(PureWindowsPath(repo_root) / PurePosixPath(raw))


def _repo_relative_exists(path: str | None, *, repo_root: str = DEFAULT_REPO_ROOT) -> bool:
    if not path:
        return False
    try:
        return Path(_repo_relative_to_local_path(path, repo_root=repo_root)).exists()
    except Exception:
        return False


def _shape_map_coverage(scene: dict[str, Any], *, repo_root: str = DEFAULT_REPO_ROOT) -> dict[str, float | int | None]:
    shape_map_ref = str(scene.get("shape_map_ref") or "")
    if not shape_map_ref or not _repo_relative_exists(shape_map_ref, repo_root=repo_root):
        return {"mapped_prim_count": None, "unmatched_prim_count": None, "coverage_ratio": None}
    try:
        payload = json.loads(Path(_repo_relative_to_local_path(shape_map_ref, repo_root=repo_root)).read_text(encoding="utf-8"))
    except Exception:
        return {"mapped_prim_count": None, "unmatched_prim_count": None, "coverage_ratio": None}
    prim_map = payload.get("prim_to_shape_ids") if isinstance(payload, dict) else None
    unmatched = payload.get("unmatched_prim_paths") if isinstance(payload, dict) else None
    mapped_count = len(prim_map) if isinstance(prim_map, dict) else None
    unmatched_count = len(unmatched) if isinstance(unmatched, list) else None
    coverage_ratio: float | None = None
    if mapped_count is not None and unmatched_count is not None and (mapped_count + unmatched_count) > 0:
        coverage_ratio = float(mapped_count) / float(mapped_count + unmatched_count)
    return {
        "mapped_prim_count": mapped_count,
        "unmatched_prim_count": unmatched_count,
        "coverage_ratio": coverage_ratio,
    }


def _preferred_mitsuba_scene_ref(scene: dict[str, Any], *, repo_root: str = DEFAULT_REPO_ROOT) -> str | None:
    current_ref = str(scene.get("mitsuba_scene_ref") or "")
    candidate_refs: list[str] = []
    if current_ref:
        current_path = PurePosixPath(current_ref)
        for sibling_name in _FULL_SCENE_SIBLING_CANDIDATES:
            sibling_ref = current_path.with_name(sibling_name).as_posix()
            if sibling_ref not in candidate_refs:
                candidate_refs.append(sibling_ref)
    if DEFAULT_FULL_MITSUBA_SCENE_REF not in candidate_refs:
        candidate_refs.append(DEFAULT_FULL_MITSUBA_SCENE_REF)
    for candidate in candidate_refs:
        if candidate != current_ref and _repo_relative_exists(candidate, repo_root=repo_root):
            return candidate
    return current_ref or None


def _pick_preview_path(capture_payload: dict[str, Any]) -> str | None:
    preview_items = capture_payload.get("preview_items")
    if isinstance(preview_items, list):
        for item in preview_items:
            href = item.get("href")
            if isinstance(href, str) and href:
                raw_paths = item.get("raw_paths") or {}
                for key in ("png", "preview_png", "colorbar_png", "image"):
                    candidate = raw_paths.get(key)
                    if isinstance(candidate, str) and candidate:
                        return candidate
                if isinstance(raw_paths, dict):
                    for candidate in raw_paths.values():
                        if isinstance(candidate, str) and candidate.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                            return candidate
    return None


def _emit_progress(
    progress_callback: ProgressCallback | None,
    *,
    status: str = "running",
    stage: str,
    message: str,
    origin: str = "isaac_app",
    counts: dict[str, int] | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(status, stage, message, origin, counts)


def _coerce_stage_loading_counts(status: Any) -> tuple[str | None, dict[str, int] | None]:
    message: str | None = None
    counts: dict[str, int] | None = None
    if isinstance(status, (list, tuple)):
        if len(status) >= 1 and isinstance(status[0], str):
            message = status[0] or None
        if len(status) >= 3:
            loaded = status[1]
            total = status[2]
            if isinstance(loaded, (int, float)) and isinstance(total, (int, float)):
                counts = {"loaded": int(loaded), "total": int(total)}
    elif isinstance(status, dict):
        maybe_message = status.get("message")
        if isinstance(maybe_message, str) and maybe_message:
            message = maybe_message
        loaded = status.get("loaded")
        total = status.get("total")
        if isinstance(loaded, (int, float)) and isinstance(total, (int, float)):
            counts = {"loaded": int(loaded), "total": int(total)}
    elif isinstance(status, str) and status:
        message = status
    return message, counts


def _stage_streaming_busy(context: Any) -> bool:
    try:
        status = context.get_stage_streaming_status()
    except Exception:
        return False
    if isinstance(status, bool):
        return status
    if isinstance(status, dict):
        return any(bool(value) for value in status.values())
    if isinstance(status, (list, tuple, set)):
        return any(bool(value) for value in status)
    if isinstance(status, (int, float)):
        return bool(status)
    if isinstance(status, str):
        normalized = status.strip().lower()
        return normalized in {"busy", "loading", "streaming", "true", "1"}
    return False


def _supports_context_method(context: Any, name: str) -> bool:
    try:
        if name not in dir(context):
            return False
        method = getattr(context, name, None)
    except Exception:
        return False
    return callable(method)


def _start_stage_loading_monitor(
    context: Any,
    progress_callback: ProgressCallback | None,
) -> tuple[threading.Event, threading.Thread | None]:
    stop_event = threading.Event()
    if progress_callback is None:
        return stop_event, None

    def _monitor() -> None:
        last_signature: tuple[Any, ...] | None = None
        last_emit_at = 0.0
        started_at = time.monotonic()
        last_probe_error: str | None = None
        while not stop_event.wait(0.25):
            message: str | None = None
            counts: dict[str, int] | None = None
            streaming = False
            probe_error: str | None = None
            try:
                message, counts = _coerce_stage_loading_counts(context.get_stage_loading_status())
            except Exception as exc:
                probe_error = f"{type(exc).__name__}: {exc}"
            try:
                streaming = _stage_streaming_busy(context)
            except Exception as exc:
                if probe_error is None:
                    probe_error = f"{type(exc).__name__}: {exc}"
            stage = "assets_loading"
            rendered_message = message or "Loading scene assets in Isaac."
            if counts and counts.get("total", 0) > 0:
                loaded = max(0, counts.get("loaded", 0))
                total = max(0, counts.get("total", 0))
                if total > 0 and loaded >= total:
                    stage = "assets_loaded"
                    rendered_message = "Scene assets loaded."
                else:
                    rendered_message = f"Loading scene assets ({loaded} / {total})."
            elif streaming:
                stage = "streaming_scene"
                rendered_message = "Preparing Hydra and streaming scene data."
            else:
                stage = "opening_stage"
                elapsed_s = max(1, int(time.monotonic() - started_at))
                rendered_message = f"Opening scene in Isaac. Still waiting for deeper load signals ({elapsed_s}s elapsed)."
                if probe_error and probe_error != last_probe_error:
                    rendered_message = f"{rendered_message} Progress probe is not ready yet: {probe_error}."
                    last_probe_error = probe_error
            signature = (stage, rendered_message, tuple(sorted((counts or {}).items())))
            now = time.monotonic()
            heartbeat = False
            if signature == last_signature and now - last_emit_at < 2.0:
                continue
            if signature == last_signature:
                heartbeat = True
            last_signature = signature
            last_emit_at = now
            _emit_progress(
                progress_callback,
                stage=stage,
                message=(
                    f"{rendered_message} Still working…"
                    if heartbeat and stage in {"opening_stage", "assets_loading", "streaming_scene"}
                    else rendered_message
                ),
                origin="isaac_internal" if stage in {"assets_loading", "assets_loaded", "streaming_scene"} else "isaac_app",
                counts=counts,
            )

    thread = threading.Thread(target=_monitor, name="robomituba-stage-progress", daemon=True)
    thread.start()
    return stop_event, thread


def _stop_stage_loading_monitor(stop_event: threading.Event, monitor_thread: threading.Thread | None) -> None:
    stop_event.set()
    if monitor_thread is not None:
        monitor_thread.join(timeout=1.0)


def _open_stage_with_callback(context: Any, open_path: str) -> None:
    finished = threading.Event()
    result: dict[str, Any] = {"success": None, "error": ""}

    def _on_finish(success: bool, error: str) -> None:
        result["success"] = bool(success)
        result["error"] = str(error or "")
        finished.set()

    started = context.open_stage_with_callback(open_path, _on_finish)
    if isinstance(started, tuple):
        started_ok = bool(started[0])
        started_error = str(started[1]) if len(started) > 1 else ""
        if not started_ok:
            raise RuntimeError(started_error or f"USD stage open failed: {open_path}")
    elif isinstance(started, bool) and not started:
        raise RuntimeError(f"USD stage open failed to start: {open_path}")

    while not finished.wait(0.1):
        continue
    if result["success"] is False:
        raise RuntimeError(result["error"] or f"USD stage open failed: {open_path}")


def _open_stage_async(context: Any, open_path: str) -> None:
    async_result = context.open_stage_async(open_path)
    if inspect.isawaitable(async_result):
        success, error = asyncio.run(async_result)
    else:
        success, error = async_result
    if not success:
        raise RuntimeError(str(error or f"USD stage open failed: {open_path}"))


def _open_stage_with_progress(
    context: Any,
    open_path: str,
    *,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if _supports_context_method(context, "open_stage_with_callback"):
        _emit_progress(
            progress_callback,
            stage="opening_stage",
            message="Opening scene in Isaac with callback-based progress monitoring.",
            origin="isaac_app",
        )
        _open_stage_with_callback(context, open_path)
        return
    if _supports_context_method(context, "open_stage_async"):
        _emit_progress(
            progress_callback,
            stage="opening_stage",
            message="Opening scene in Isaac with async progress monitoring.",
            origin="isaac_app",
        )
        _open_stage_async(context, open_path)
        return
    _emit_progress(
        progress_callback,
        stage="opening_stage",
        message="Opening scene in Isaac with blocking stage open.",
        origin="isaac_app",
    )
    context.open_stage(open_path)


def submit_isaac_state_render(
    snapshot: Any,
    daemon_url: str | None = None,
    *,
    timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
    variant: str | None = None,
) -> dict[str, Any]:
    """POST /isaac/render and wait for completion."""
    payload = _snapshot_payload(snapshot)
    payload["timeout_s"] = timeout_s
    if variant:
        payload["variant"] = variant
    url = f"{_resolve_daemon_url(daemon_url)}/isaac/render"
    return _http_json("POST", url, payload, timeout_s=timeout_s + 10.0)


def enqueue_isaac_state_render(
    snapshot: Any,
    daemon_url: str | None = None,
    *,
    timeout_s: float = 10.0,
    variant: str | None = None,
) -> dict[str, Any]:
    """POST /isaac/render/submit and return a queued job envelope."""
    payload = _snapshot_payload(snapshot)
    if variant:
        payload["variant"] = variant
    url = f"{_resolve_daemon_url(daemon_url)}/isaac/render/submit"
    return _http_json("POST", url, payload, timeout_s=timeout_s)


def get_isaac_session(*, daemon_url: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/isaac/session", timeout_s=timeout_s)


def _active_session_payload(session_summary: dict[str, Any]) -> dict[str, Any]:
    session = session_summary.get("session")
    return dict(session) if isinstance(session, Mapping) else {}


def _session_matches_scene(session_summary: dict[str, Any], scene: dict[str, Any]) -> bool:
    session = _active_session_payload(session_summary)
    if session_summary.get("status") != "active" or not session:
        return False
    return (
        str(session.get("scene_id") or "") == str(scene.get("scene_id") or "")
        and str(session.get("mitsuba_scene_ref") or "") == str(scene.get("mitsuba_scene_ref") or "")
        and str(session.get("shape_map_ref") or "") == str(scene.get("shape_map_ref") or "")
    )


def _resolve_render_sync_mode(
    *,
    session_summary: dict[str, Any],
    scene: dict[str, Any],
    sync_policy: str,
    force_resync: bool,
    state_dirty: bool | None,
    material_dirty: bool | None,
) -> str:
    normalized_policy = str(sync_policy or "auto").strip().lower()
    if normalized_policy == "force_full" or force_resync:
        return "full_resync"
    if not _session_matches_scene(session_summary, scene):
        return "full_resync"
    session = _active_session_payload(session_summary)
    if bool(state_dirty) or bool(session.get("state_dirty")):
        return "full_resync"
    if bool(material_dirty) or bool(session.get("material_dirty")):
        return "material_delta"
    return "camera_only"


def list_scenes_from_daemon(*, daemon_url: str | None = None, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    payload = _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/scenes", timeout_s=timeout_s)
    return list(payload.get("scenes", []))


def get_scene_from_daemon(scene_id: str, *, daemon_url: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/scenes/{scene_id}", timeout_s=timeout_s)


def list_isaac_commands(*, daemon_url: str | None = None, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    payload = _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands", timeout_s=timeout_s)
    return list(payload.get("commands", []))


def next_isaac_command(*, daemon_url: str | None = None, timeout_s: float = 10.0) -> dict[str, Any] | None:
    payload = _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands/next", timeout_s=timeout_s)
    command = payload.get("command")
    return command if isinstance(command, dict) else None


def queue_isaac_command(
    command_type: str,
    *,
    scene_id: str | None = None,
    payload: dict[str, Any] | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {"command_type": command_type}
    if scene_id:
        request_payload["scene_id"] = scene_id
    if payload:
        request_payload["payload"] = dict(payload)
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands", request_payload, timeout_s=timeout_s)


def start_isaac_command(
    command_type: str,
    *,
    scene_id: str | None = None,
    payload: dict[str, Any] | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {"command_type": command_type}
    if scene_id:
        request_payload["scene_id"] = scene_id
    if payload:
        request_payload["payload"] = dict(payload)
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands/start", request_payload, timeout_s=timeout_s)


def update_isaac_command_progress(
    command_id: str,
    *,
    status: str = "running",
    progress_stage: str,
    progress_message: str,
    progress_origin: str = "isaac_app",
    progress_counts: dict[str, int] | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "status": status,
        "progress_stage": progress_stage,
        "progress_message": progress_message,
        "progress_origin": progress_origin,
    }
    if progress_counts:
        request_payload["progress_counts"] = dict(progress_counts)
    return _http_json(
        "POST",
        f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands/{command_id}/progress",
        request_payload,
        timeout_s=timeout_s,
    )


def complete_isaac_command(
    command_id: str,
    *,
    status: str = "succeeded",
    result: dict[str, Any] | None = None,
    error: str | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {"status": status}
    if result is not None:
        request_payload["result"] = dict(result)
    if error is not None:
        request_payload["error"] = str(error)
    return _http_json(
        "POST",
        f"{_resolve_daemon_url(daemon_url)}/api/isaac/commands/{command_id}/complete",
        request_payload,
        timeout_s=timeout_s,
    )


def _render_ready_error(scene_id: str, scene: dict[str, Any]) -> RuntimeError:
    mitsuba_scene_ref = scene.get("mitsuba_scene_ref")
    shape_map_ref = scene.get("shape_map_ref")
    mitsuba_scene_exists = scene.get("mitsuba_scene_exists")
    shape_map_exists = scene.get("shape_map_exists")
    if not mitsuba_scene_ref or not shape_map_ref:
        return RuntimeError(
            f"Scene {scene_id} is not render-ready yet. "
            f"It must include both mitsuba_scene_ref and shape_map_ref in the daemon catalog."
        )
    if mitsuba_scene_exists is False or shape_map_exists is False:
        missing_parts: list[str] = []
        if mitsuba_scene_exists is False:
            missing_parts.append(f"mitsuba_scene_ref missing on disk: {mitsuba_scene_ref}")
        if shape_map_exists is False:
            missing_parts.append(f"shape_map_ref missing on disk: {shape_map_ref}")
        detail = "; ".join(missing_parts)
        return RuntimeError(
            f"Scene {scene_id} is registered but not render-ready. {detail}. "
            "Open the USD with daemon.load_scene(usd_path=...) if you only want to inspect the scene in Isaac, "
            "or generate/register the missing files before calling render_current_view()."
        )
    return RuntimeError(f"Scene {scene_id} is not render-ready.")


def _normalize_session_open_error(
    exc: RuntimeError,
    *,
    scene_id: str | None = None,
    shape_map_ref: str | None = None,
) -> RuntimeError:
    message = str(exc)
    if (
        "/isaac/session/open" in message
        and "No such file or directory" in message
        and shape_map_ref
        and "shape_map" in shape_map_ref
    ):
        scene_label = scene_id or "selected scene"
        return RuntimeError(
            f"Scene {scene_label} is registered but not render-ready. "
            f"shape_map_ref missing on disk: {shape_map_ref}. "
            "Open the USD with daemon.load_scene(usd_path=...) if you only want to inspect the scene in Isaac, "
            "or generate/register the missing files before calling render_current_view()."
        )
    return exc


def register_scene_with_daemon(
    *,
    daemon_url: str | None = None,
    usd_stage_path: str,
    scene_id: str | None = None,
    mitsuba_scene_ref: str | None = None,
    shape_map_ref: str | None = None,
    scene_snapshot_ref: str | None = None,
    scene_version: str | None = None,
    illumination_setup: str | None = None,
    extra_fields: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"usd_stage_path": usd_stage_path}
    if scene_id:
        payload["scene_id"] = scene_id
    if mitsuba_scene_ref:
        payload["mitsuba_scene_ref"] = mitsuba_scene_ref
    if shape_map_ref:
        payload["shape_map_ref"] = shape_map_ref
    if scene_snapshot_ref:
        payload["scene_snapshot_ref"] = scene_snapshot_ref
    if scene_version:
        payload["scene_version"] = scene_version
    if illumination_setup:
        payload["illumination_setup"] = illumination_setup
    if extra_fields:
        payload.update(dict(extra_fields))
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/api/isaac/scenes/register", payload, timeout_s=timeout_s)


def open_isaac_session(
    session_open: Any,
    daemon_url: str | None = None,
    *,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    try:
        return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/session/open", _session_open_payload(session_open), timeout_s=timeout_s)
    except RuntimeError as exc:
        raise _normalize_session_open_error(
            exc,
            scene_id=getattr(session_open, "scene_id", None),
            shape_map_ref=getattr(session_open, "shape_map_ref", None),
        ) from exc


def get_scene_texture_cache_status(
    scene_id: str,
    scene: dict[str, Any],
    *,
    daemon_url: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    usd_stage_path = str(scene.get("usd_stage_path") or "")
    source_stage_path = Path(_repo_relative_to_local_path(usd_stage_path, repo_root=repo_root))
    source_mode = _classify_windows_path_mode(str(source_stage_path))
    base_payload: dict[str, Any] = {
        "scene_id": scene_id,
        "texture_cache_status": "missing",
        "texture_cache_root": None,
        "texture_cache_bytes": None,
        "texture_cache_file_count": None,
        "texture_cache_last_synced_at": None,
        "texture_cache_source_mode": source_mode,
        "texture_cache_hit": False,
        "open_stage_path": str(source_stage_path),
    }
    if not _is_windows_host():
        base_payload["texture_cache_status"] = "bypassed"
        return base_payload
    if source_mode != "unc":
        base_payload["texture_cache_status"] = "bypassed"
        return base_payload
    try:
        layout = _scene_texture_cache_layout(scene_id, source_stage_path)
    except Exception:
        return base_payload
    manifest = _read_cache_manifest(layout.cache_manifest_path)
    texture_stats = _path_tree_signature(layout.source_texture_root)
    usd_stats = _path_tree_signature(layout.source_usd_root)
    instances_stats = _path_tree_signature(layout.source_instances_root)
    source_signature = _combined_cache_signature(texture_stats, usd_stats, instances_stats)
    cached_signature = str(manifest.get("source_signature") or "")
    has_cache = bool(
        layout.cache_texture_root.exists()
        and layout.cache_usd_root.exists()
        and layout.cache_stage_path.exists()
        and manifest.get("status") == "ready"
    )
    stale = has_cache and cached_signature and cached_signature != source_signature
    if has_cache and not stale:
        base_payload.update(
            {
                "texture_cache_status": "ready",
                "texture_cache_root": str(layout.cache_texture_root),
                "texture_cache_bytes": int(manifest.get("bytes", 0) or 0),
                "texture_cache_file_count": int(manifest.get("file_count", 0) or 0),
                "texture_cache_last_synced_at": manifest.get("last_cached_at"),
                "texture_cache_hit": True,
            }
        )
        base_payload["open_stage_path"] = str(layout.cache_stage_path)
        return base_payload
    base_payload.update(
        {
            "texture_cache_status": "stale" if stale else "missing",
            "texture_cache_root": str(layout.cache_texture_root),
            "texture_cache_bytes": int(manifest.get("bytes", 0) or 0) if manifest else None,
            "texture_cache_file_count": int(manifest.get("file_count", 0) or 0) if manifest else None,
            "texture_cache_last_synced_at": manifest.get("last_cached_at"),
        }
    )
    return base_payload


def ensure_scene_texture_cache(
    scene_id: str,
    scene: dict[str, Any],
    *,
    daemon_url: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    timeout_s: float = 10.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    status = get_scene_texture_cache_status(
        scene_id,
        scene,
        daemon_url=daemon_url,
        repo_root=repo_root,
        timeout_s=timeout_s,
    )
    usd_stage_path = str(scene.get("usd_stage_path") or "")
    if status["texture_cache_status"] in {"bypassed", "ready"}:
        _register_scene_cache_status(
            scene_id,
            daemon_url=daemon_url,
            usd_stage_path=usd_stage_path,
            timeout_s=timeout_s,
            cache_payload={key: status.get(key) for key in (
                "texture_cache_status",
                "texture_cache_root",
                "texture_cache_bytes",
                "texture_cache_file_count",
                "texture_cache_last_synced_at",
                "texture_cache_source_mode",
            )},
        )
        return status

    source_stage_path = Path(_repo_relative_to_local_path(usd_stage_path, repo_root=repo_root))
    layout = _scene_texture_cache_layout(scene_id, source_stage_path)
    texture_stats = _path_tree_signature(layout.source_texture_root)
    usd_stats = _path_tree_signature(layout.source_usd_root)
    instances_stats = _path_tree_signature(layout.source_instances_root)
    source_signature = _combined_cache_signature(texture_stats, usd_stats, instances_stats)
    _emit_progress(
        progress_callback,
        stage="preparing_cache",
        message="Checking local texture cache before opening the scene.",
    )
    _register_scene_cache_status(
        scene_id,
        daemon_url=daemon_url,
        usd_stage_path=usd_stage_path,
        timeout_s=timeout_s,
        cache_payload={
            "texture_cache_status": "caching",
            "texture_cache_root": str(layout.cache_texture_root),
            "texture_cache_source_mode": status["texture_cache_source_mode"],
        },
    )
    layout.cache_asset_root.mkdir(parents=True, exist_ok=True)
    copy_message = "Caching scene assets to local SSD before opening in Isaac."
    file_count = int(texture_stats.get("file_count", 0) or 0)
    total_bytes = int(texture_stats.get("bytes", 0) or 0)
    if file_count > 0 and total_bytes > 0:
        gib = total_bytes / float(1024 ** 3)
        copy_message = (
            f"Caching scene compatibility subset to local SSD "
            f"(textures {file_count} files, {gib:.1f} GiB; plus USD/Instances layers)."
        )
    _emit_progress(progress_callback, stage="copying_textures", message=copy_message)
    _prepare_cache_target(layout.cache_usd_root)
    _prepare_cache_target(layout.cache_instances_root)
    _prepare_cache_target(layout.cache_texture_root)
    if layout.source_usd_root.exists():
        _mirror_tree_windows(layout.source_usd_root, layout.cache_usd_root)
    if layout.source_instances_root.exists():
        _mirror_tree_windows(layout.source_instances_root, layout.cache_instances_root)
    _mirror_tree_windows(layout.source_texture_root, layout.cache_texture_root)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    if len(now_iso) > 5:
        now_iso = f"{now_iso[:-2]}:{now_iso[-2:]}"
    manifest = {
        "scene_id": scene_id,
        "source_texture_root": str(layout.source_texture_root),
        "source_usd_root": str(layout.source_usd_root),
        "source_instances_root": str(layout.source_instances_root),
        "cached_texture_root": str(layout.cache_texture_root),
        "cached_usd_root": str(layout.cache_usd_root),
        "cached_instances_root": str(layout.cache_instances_root),
        "source_signature": source_signature,
        "source_mode": status["texture_cache_source_mode"],
        "file_count": int(texture_stats.get("file_count", 0) or 0),
        "bytes": int(texture_stats.get("bytes", 0) or 0),
        "usd_file_count": int(usd_stats.get("file_count", 0) or 0),
        "instances_file_count": int(instances_stats.get("file_count", 0) or 0),
        "last_cached_at": now_iso,
        "status": "ready",
    }
    _write_json_file(layout.cache_manifest_path, manifest)
    ready_payload = {
        "scene_id": scene_id,
        "texture_cache_status": "ready" if layout.cache_stage_path.exists() else "missing",
        "texture_cache_root": str(layout.cache_texture_root),
        "texture_cache_bytes": manifest["bytes"],
        "texture_cache_file_count": manifest["file_count"],
        "texture_cache_last_synced_at": manifest["last_cached_at"],
        "texture_cache_source_mode": status["texture_cache_source_mode"],
        "texture_cache_hit": False,
        "open_stage_path": str(layout.cache_stage_path if layout.cache_stage_path.exists() else source_stage_path),
    }
    _register_scene_cache_status(
        scene_id,
        daemon_url=daemon_url,
        usd_stage_path=usd_stage_path,
        timeout_s=timeout_s,
        cache_payload={key: ready_payload.get(key) for key in (
            "texture_cache_status",
            "texture_cache_root",
            "texture_cache_bytes",
            "texture_cache_file_count",
            "texture_cache_last_synced_at",
            "texture_cache_source_mode",
        )},
    )
    return ready_payload


def load_scene_from_daemon(
    *,
    daemon_url: str | None = None,
    scene_id: str | None = None,
    usd_path: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    timeout_s: float = DEFAULT_LOAD_SCENE_TIMEOUT_S,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    _emit_progress(progress_callback, stage="resolving_scene", message="Resolving scene path from daemon catalog.")
    cache_status: dict[str, Any] | None = None
    if scene_id:
        payload = get_scene_from_daemon(scene_id, daemon_url=daemon_url, timeout_s=timeout_s)
        scene = payload.get("scene") or {}
        resolved_path = scene.get("usd_stage_path")
        if not resolved_path:
            raise RuntimeError(f"Scene {scene_id} does not include usd_stage_path in daemon catalog.")
        open_path = _repo_relative_to_local_path(resolved_path, repo_root=repo_root)
        if _is_windows_host():
            cache_status = ensure_scene_texture_cache(
                scene_id,
                scene,
                daemon_url=daemon_url,
                repo_root=repo_root,
                timeout_s=max(timeout_s, 30.0),
                progress_callback=progress_callback,
            )
            open_path = str(cache_status.get("open_stage_path") or open_path)
    elif usd_path:
        open_path = _repo_relative_to_local_path(usd_path, repo_root=repo_root)
        payload = {"scene": {"scene_id": scene_id or Path(open_path).stem, "usd_stage_path": usd_path}}
    else:
        raise ValueError("load_scene_from_daemon requires either scene_id or usd_path.")

    context = _require_isaac_context()
    _emit_progress(progress_callback, stage="opening_stage", message="Opening scene in Isaac.")
    stop_event, monitor_thread = _start_stage_loading_monitor(context, progress_callback)
    try:
        _open_stage_with_progress(context, open_path, progress_callback=progress_callback)
    finally:
        _stop_stage_loading_monitor(stop_event, monitor_thread)
    if _stage_streaming_busy(context):
        _emit_progress(progress_callback, stage="streaming_scene", message="Waiting for scene streaming to settle.", origin="isaac_internal")
        deadline = time.monotonic() + max(timeout_s, 10.0)
        while _stage_streaming_busy(context) and time.monotonic() < deadline:
            time.sleep(0.2)
    _emit_progress(progress_callback, stage="ready", message="Scene open completed.", origin="isaac_internal")
    return {
        "status": "opened",
        "scene_id": (payload.get("scene") or {}).get("scene_id"),
        "usd_stage_path": open_path,
        "texture_cache": cache_status,
    }


def connect_scene_session_from_daemon(
    scene_id: str,
    *,
    daemon_url: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    timeout_s: float = 10.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    try:
        from isaac_extension.stage_capture import capture_session_open
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import capture_session_open

    _emit_progress(progress_callback, stage="collecting_scene_refs", message="Collecting scene session references from daemon.")
    payload = get_scene_from_daemon(scene_id, daemon_url=daemon_url, timeout_s=timeout_s)
    scene = payload.get("scene") or {}
    coverage = _shape_map_coverage(scene, repo_root=repo_root)
    preferred_scene_ref = _preferred_mitsuba_scene_ref(scene, repo_root=repo_root)
    current_scene_ref = str(scene.get("mitsuba_scene_ref") or "")
    should_upgrade_variant = (
        bool(preferred_scene_ref)
        and preferred_scene_ref != current_scene_ref
        and (
            "scene_curated_shell_furniture" in current_scene_ref
            or coverage.get("mapped_prim_count") == 0
        )
    )
    if should_upgrade_variant:
        _emit_progress(
            progress_callback,
            stage="collecting_scene_refs",
            message="Current Mitsuba scene looks curated or under-mapped. Preparing fuller scene coverage.",
        )
        prepared = prepare_render_ready_from_daemon(
            scene_id,
            stage=_require_isaac_context().get_stage(),
            daemon_url=daemon_url,
            repo_root=repo_root,
            mitsuba_scene_ref=preferred_scene_ref,
            timeout_s=max(timeout_s, 30.0),
            progress_callback=progress_callback,
        )
        scene = dict(prepared.get("scene") or {})
    if (
        not scene.get("mitsuba_scene_ref")
        or not scene.get("shape_map_ref")
        or scene.get("mitsuba_scene_exists") is False
        or scene.get("shape_map_exists") is False
    ):
        raise _render_ready_error(scene_id, scene)
    try:
        active_session = get_isaac_session(daemon_url=daemon_url, timeout_s=min(timeout_s, 5.0))
    except Exception:
        active_session = {"status": "inactive", "session": None}
    if _session_matches_scene(active_session, scene):
        _emit_progress(progress_callback, stage="opening_session", message="Reusing the already-open Isaac session for this scene.")
        _register_active_viewport_sensor_best_effort(
            daemon_url=daemon_url,
            timeout_s=min(timeout_s, 10.0),
            progress_callback=progress_callback,
        )
        result = dict(active_session)
        result["reused"] = True
        return result
    _emit_progress(progress_callback, stage="opening_session", message="Opening active Isaac session.")
    session_result = open_isaac_session(
        capture_session_open(
            scene_id=scene_id,
            mitsuba_scene_ref=scene["mitsuba_scene_ref"],
            shape_map_ref=scene["shape_map_ref"],
            scene_snapshot_ref=scene.get("scene_snapshot_ref"),
        ),
        daemon_url,
        timeout_s=timeout_s,
    )
    _register_active_viewport_sensor_best_effort(
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, 10.0),
        progress_callback=progress_callback,
    )
    if isinstance(session_result, dict):
        session_result["reused"] = bool(session_result.get("reused", False))
    return session_result


def update_isaac_state(
    state_patch: Any,
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/session/update_state", _state_patch_payload(state_patch), timeout_s=timeout_s)


def sync_scene_state_to_daemon(
    stage: Any,
    scene_id: str,
    *,
    daemon_url: str | None = None,
    bsdf_overrides_by_path: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
    progress_callback: ProgressCallback | None = None,
    ensure_session: bool = True,
) -> dict[str, Any]:
    try:
        from isaac_extension.stage_capture import capture_material_patch, capture_selected_prim_paths, capture_state_patch
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import capture_material_patch, capture_selected_prim_paths, capture_state_patch

    if ensure_session:
        connect_scene_session_from_daemon(
            scene_id,
            daemon_url=daemon_url,
            timeout_s=timeout_s,
            progress_callback=progress_callback,
        )
    _emit_progress(progress_callback, stage="capturing_stage_state", message="Capturing current stage state from Isaac.")
    state_result = update_isaac_state(
        capture_state_patch(stage, scene_id=scene_id, bsdf_overrides_by_path=bsdf_overrides_by_path or {}),
        daemon_url=daemon_url,
        timeout_s=timeout_s,
    )
    _emit_progress(progress_callback, stage="uploading_patch", message="Uploading state patch to daemon.")
    if bsdf_overrides_by_path:
        _emit_progress(progress_callback, stage="serializing_patch", message="Preparing BSDF override patch.")
        update_isaac_materials(
            capture_material_patch(bsdf_overrides_by_path),
            daemon_url=daemon_url,
            timeout_s=timeout_s,
        )
    _register_active_viewport_sensor_best_effort(
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, 10.0),
        progress_callback=progress_callback,
    )
    update_isaac_selection(
        capture_selected_prim_paths(stage),
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, 10.0),
    )
    return state_result


def update_isaac_materials(
    material_patch: Any,
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/session/update_materials", _material_patch_payload(material_patch), timeout_s=timeout_s)


def update_isaac_selection(
    selected_prim_paths: list[str],
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    payload = {"selected_prim_paths": [str(path) for path in selected_prim_paths if str(path)]}
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/session/update_selection", payload, timeout_s=timeout_s)


def register_isaac_sensors(
    sensors: list[Any],
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    payload = {"sensors": [_sensor_spec_payload(sensor) for sensor in sensors]}
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/session/register_sensors", payload, timeout_s=timeout_s)


def register_isaac_sensors_ws(
    sensors: list[Any],
    *,
    daemon_url: str | None = None,
    timeout_s: float = 1.0,
) -> None:
    payload = {"sensors": [_sensor_spec_payload(sensor) for sensor in sensors]}
    _camera_ws_client(daemon_url).send_json(payload, timeout_s=timeout_s)


def capture_active_viewport_camera_signature(*, decimals: int = 5) -> tuple[Any, ...] | None:
    try:
        try:
            from isaac_extension.stage_capture import capture_current_view_camera
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from stage_capture import capture_current_view_camera

        camera = capture_current_view_camera()
    except Exception:
        return None
    camera_to_world = tuple(round(float(value), decimals) for value in list(camera.camera_to_world or []))
    resolution = tuple(int(value) for value in list(camera.resolution or []))
    return (
        str(camera.source_camera_id or ""),
        round(float(camera.fov_deg or 0.0), 2),
        resolution,
        camera_to_world,
    )


def _register_active_viewport_sensor_best_effort(
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
    modalities: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any] | None:
    global _SENSOR_REGISTER_SUPPRESSED_UNTIL
    global _LAST_VIEWPORT_SENSOR_REGISTER_SIGNATURE
    global _LAST_VIEWPORT_SENSOR_REGISTER_TS

    now = time.monotonic()
    if now < _SENSOR_REGISTER_SUPPRESSED_UNTIL:
        return None

    try:
        try:
            from isaac_extension.stage_capture import capture_current_view_sensor_spec
        except ImportError:  # pragma: no cover - Isaac runtime fallback
            from stage_capture import capture_current_view_sensor_spec

        modalities_key = tuple(sorted(str(modality) for modality in list(modalities or ["rgb"])))
        camera_signature = capture_active_viewport_camera_signature()
        signature = (modalities_key, camera_signature)
        if (
            camera_signature is not None
            and signature == _LAST_VIEWPORT_SENSOR_REGISTER_SIGNATURE
            and now - _LAST_VIEWPORT_SENSOR_REGISTER_TS < _SENSOR_REGISTER_REFRESH_INTERVAL_S
        ):
            return None

        _emit_progress(
            progress_callback,
            stage="syncing_viewport_camera",
            message="Syncing the active Isaac viewport camera to daemon.",
            origin="isaac_app",
        )
        sensor = capture_current_view_sensor_spec(modalities=list(modalities or ["rgb"]))
        try:
            register_isaac_sensors_ws(
                [sensor],
                daemon_url=daemon_url,
                timeout_s=min(timeout_s, 1.0),
            )
            result: dict[str, Any] | None = None
        except Exception:
            result = register_isaac_sensors(
                [sensor],
                daemon_url=daemon_url,
                timeout_s=timeout_s,
            )
        _LAST_VIEWPORT_SENSOR_REGISTER_SIGNATURE = signature
        _LAST_VIEWPORT_SENSOR_REGISTER_TS = now
        return result
    except Exception as exc:
        if "No active Isaac scene session" in str(exc):
            _SENSOR_REGISTER_SUPPRESSED_UNTIL = time.monotonic() + _SENSOR_REGISTER_NO_SESSION_BACKOFF_S
        _emit_progress(
            progress_callback,
            stage="syncing_viewport_camera",
            message=f"Active viewport camera is not available yet: {exc}",
            origin="isaac_app",
        )
        return None

def sync_active_viewport_camera_to_daemon(
    *,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
    modalities: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any] | None:
    return _register_active_viewport_sensor_best_effort(
        daemon_url=daemon_url,
        timeout_s=timeout_s,
        modalities=modalities,
        progress_callback=progress_callback,
    )


def list_material_presets(*, daemon_url: str | None = None, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    payload = _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/material-presets", timeout_s=timeout_s)
    return list(payload.get("presets", []))


def prepare_render_ready_from_daemon(
    scene_id: str,
    *,
    stage: Any | None = None,
    daemon_url: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    mitsuba_scene_ref: str | None = None,
    timeout_s: float = 30.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    try:
        from isaac_extension.stage_capture import generate_shape_map_for_stage
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import generate_shape_map_for_stage

    payload = get_scene_from_daemon(scene_id, daemon_url=daemon_url, timeout_s=min(timeout_s, 10.0))
    scene = payload.get("scene") or {}
    selected_scene_ref = str(mitsuba_scene_ref or _preferred_mitsuba_scene_ref(scene, repo_root=repo_root) or scene.get("mitsuba_scene_ref") or "")
    if not selected_scene_ref:
        raise RuntimeError(
            f"Scene {scene_id} does not have mitsuba_scene_ref yet. Register the Mitsuba XML before preparing render-ready files."
        )
    if selected_scene_ref != str(scene.get("mitsuba_scene_ref") or ""):
        _emit_progress(
            progress_callback,
            stage="collecting_scene_refs",
            message=f"Switching to fuller Mitsuba scene variant for {scene_id}: {selected_scene_ref}",
        )
    if stage is None:
        stage = _require_isaac_context().get_stage()
    if stage is None:
        raise RuntimeError("No USD stage open in Isaac Sim.")
    _emit_progress(progress_callback, stage="capturing_stage_state", message="Capturing current Isaac stage for shape-map generation.")
    generated = generate_shape_map_for_stage(
        stage,
        scene_id=scene_id,
        mitsuba_scene_ref=selected_scene_ref,
        shape_map_ref=(str(scene.get("shape_map_ref") or "") or None) if selected_scene_ref == str(scene.get("mitsuba_scene_ref") or "") else None,
        scene_snapshot_ref=str(scene.get("scene_snapshot_ref") or "") or None,
        repo_root=repo_root,
    )
    _emit_progress(progress_callback, stage="uploading_patch", message="Registering generated shape map with daemon.")
    registered = register_scene_with_daemon(
        daemon_url=daemon_url,
        usd_stage_path=str(scene.get("usd_stage_path") or ""),
        scene_id=scene_id,
        mitsuba_scene_ref=selected_scene_ref,
        shape_map_ref=str(generated["shape_map_ref"]),
        scene_snapshot_ref=str(scene.get("scene_snapshot_ref") or "") or None,
        scene_version=str(scene.get("scene_version") or "") or None,
        illumination_setup=str(scene.get("illumination_setup") or "") or None,
        timeout_s=min(timeout_s, 10.0),
    )
    _emit_progress(progress_callback, stage="ready", message="Scene is now render-ready.")
    return {
        "status": "prepared",
        "scene_id": scene_id,
        "mitsuba_scene_ref": selected_scene_ref,
        "shape_map_ref": generated["shape_map_ref"],
        "generated": generated,
        "scene": registered.get("scene"),
    }


def capture_isaac(
    capture_request: Any,
    *,
    daemon_url: str | None = None,
    timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
    variant: str | None = None,
    command_id: str | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _capture_request_payload(capture_request)
    if extras:
        merged_extras = dict(payload.get("extras") or {})
        merged_extras.update(dict(extras))
        payload["extras"] = merged_extras
    payload["timeout_s"] = timeout_s
    if variant:
        payload["variant"] = variant
    if command_id:
        payload["command_id"] = command_id
    return _http_json("POST", f"{_resolve_daemon_url(daemon_url)}/isaac/capture", payload, timeout_s=timeout_s + 10.0)


def render_current_view_from_daemon(
    scene_id: str,
    *,
    stage: Any | None = None,
    daemon_url: str | None = None,
    submit_mode: str = "async",
    modalities: list[str] | None = None,
    render_settings: dict[str, Any] | None = None,
    bsdf_overrides_by_path: dict[str, Any] | None = None,
    timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
    variant: str | None = None,
    progress_callback: ProgressCallback | None = None,
    command_id: str | None = None,
    sync_policy: str = "auto",
    force_resync: bool = False,
    state_dirty: bool | None = None,
    material_dirty: bool | None = None,
) -> dict[str, Any]:
    try:
        from isaac_extension.stage_capture import capture_current_view_sensor_spec, capture_material_patch
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import capture_current_view_sensor_spec, capture_material_patch

    if stage is None:
        stage = _require_isaac_context().get_stage()
    try:
        scene_payload = get_scene_from_daemon(scene_id, daemon_url=daemon_url, timeout_s=min(timeout_s, 10.0))
        scene = dict(scene_payload.get("scene") or {})
    except Exception:
        scene = {"scene_id": scene_id}
    _emit_progress(progress_callback, stage="ensuring_session", message="Ensuring active Isaac session exists.")
    connect_scene_session_from_daemon(
        scene_id,
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
        progress_callback=progress_callback,
    )
    try:
        session_summary = get_isaac_session(daemon_url=daemon_url, timeout_s=min(timeout_s, 10.0))
    except Exception:
        session_summary = {"status": "inactive", "session": None}
    sync_mode = _resolve_render_sync_mode(
        session_summary=session_summary,
        scene=scene,
        sync_policy=sync_policy,
        force_resync=force_resync,
        state_dirty=state_dirty,
        material_dirty=material_dirty,
    )
    if sync_mode == "full_resync":
        sync_scene_state_to_daemon(
            stage,
            scene_id,
            daemon_url=daemon_url,
            bsdf_overrides_by_path=bsdf_overrides_by_path,
            timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
            progress_callback=progress_callback,
            ensure_session=False,
        )
    elif sync_mode == "material_delta" and bsdf_overrides_by_path:
        _emit_progress(progress_callback, stage="serializing_patch", message="Uploading material-only patch to daemon.")
        update_isaac_materials(
            capture_material_patch(bsdf_overrides_by_path),
            daemon_url=daemon_url,
            timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
        )
    _emit_progress(progress_callback, stage="capturing_view", message="Capturing current viewport sensor definition.")
    register_isaac_sensors(
        [capture_current_view_sensor_spec(modalities=list(modalities or ["rgb"]))],
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
    )
    _emit_progress(progress_callback, stage="sending_capture_request", message="Submitting current-view capture request to daemon.")
    result = capture_isaac_view(
        daemon_url=daemon_url,
        modalities=modalities,
        submit_mode=submit_mode,
        render_settings=render_settings,
        timeout_s=timeout_s,
        variant=variant,
        command_id=command_id,
        extras={
            "sync_policy": sync_policy,
            "sync_mode": sync_mode,
            "force_resync": force_resync,
        },
    )
    if isinstance(result, dict):
        result.setdefault("sync_mode", sync_mode)
    return result


def render_sensor_from_daemon(
    scene_id: str,
    sensor_id: str,
    *,
    stage: Any | None = None,
    daemon_url: str | None = None,
    submit_mode: str = "blocking",
    modalities: list[str] | None = None,
    render_settings: dict[str, Any] | None = None,
    bsdf_overrides_by_path: dict[str, Any] | None = None,
    timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
    variant: str | None = None,
    progress_callback: ProgressCallback | None = None,
    command_id: str | None = None,
    sync_policy: str = "auto",
    force_resync: bool = False,
    state_dirty: bool | None = None,
    material_dirty: bool | None = None,
) -> dict[str, Any]:
    from robomituba_bridge import IsaacCaptureRequest
    try:
        from isaac_extension.stage_capture import capture_material_patch
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import capture_material_patch

    if stage is None:
        stage = _require_isaac_context().get_stage()
    try:
        scene_payload = get_scene_from_daemon(scene_id, daemon_url=daemon_url, timeout_s=min(timeout_s, 10.0))
        scene = dict(scene_payload.get("scene") or {})
    except Exception:
        scene = {"scene_id": scene_id}
    _emit_progress(progress_callback, stage="ensuring_session", message="Ensuring active Isaac session exists.")
    connect_scene_session_from_daemon(
        scene_id,
        daemon_url=daemon_url,
        timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
        progress_callback=progress_callback,
    )
    try:
        session_summary = get_isaac_session(daemon_url=daemon_url, timeout_s=min(timeout_s, 10.0))
    except Exception:
        session_summary = {"status": "inactive", "session": None}
    sync_mode = _resolve_render_sync_mode(
        session_summary=session_summary,
        scene=scene,
        sync_policy=sync_policy,
        force_resync=force_resync,
        state_dirty=state_dirty,
        material_dirty=material_dirty,
    )
    if sync_mode == "full_resync":
        sync_scene_state_to_daemon(
            stage,
            scene_id,
            daemon_url=daemon_url,
            bsdf_overrides_by_path=bsdf_overrides_by_path,
            timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
            progress_callback=progress_callback,
            ensure_session=False,
        )
    elif sync_mode == "material_delta" and bsdf_overrides_by_path:
        _emit_progress(progress_callback, stage="serializing_patch", message="Uploading material-only patch to daemon.")
        update_isaac_materials(
            capture_material_patch(bsdf_overrides_by_path),
            daemon_url=daemon_url,
            timeout_s=min(timeout_s, DEFAULT_RENDER_PREP_TIMEOUT_S),
        )
    _emit_progress(progress_callback, stage="resolving_sensor", message=f"Resolving sensor {sensor_id}.")
    capture_request = IsaacCaptureRequest(
        sensor_id=sensor_id,
        modalities=list(modalities or []),
        submit_mode=submit_mode,
        render_settings=dict(render_settings or {}),
        extras={
            "sync_policy": sync_policy,
            "sync_mode": sync_mode,
            "force_resync": force_resync,
        },
    )
    _emit_progress(progress_callback, stage="sending_capture_request", message="Submitting sensor capture request to daemon.")
    result = capture_isaac(
        capture_request,
        daemon_url=daemon_url,
        timeout_s=timeout_s,
        variant=variant,
        command_id=command_id,
    )
    if isinstance(result, dict):
        result.setdefault("sync_mode", sync_mode)
    return result


def get_latest_capture_from_daemon(
    *,
    scene_id: str | None = None,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    if scene_id:
        return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/captures/latest?scene_id={scene_id}", timeout_s=timeout_s)
    return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/captures/latest", timeout_s=timeout_s)


def get_capture_from_daemon(job_id: str, frame_id: str, *, daemon_url: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/api/isaac/captures/{job_id}/{frame_id}", timeout_s=timeout_s)


def open_capture_from_daemon(
    *,
    daemon_url: str | None = None,
    scene_id: str | None = None,
    job_id: str | None = None,
    frame_id: str | None = None,
    repo_root: str = DEFAULT_REPO_ROOT,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    if job_id and frame_id:
        capture_payload = get_capture_from_daemon(job_id, frame_id, daemon_url=daemon_url, timeout_s=timeout_s)
        capture = capture_payload.get("latest_capture") or {}
    else:
        capture = get_latest_capture_from_daemon(scene_id=scene_id, daemon_url=daemon_url, timeout_s=timeout_s)
    preview_path = _pick_preview_path(capture)
    if not preview_path:
        raise RuntimeError("No preview artifact was found for the selected capture.")
    local_path = _repo_relative_to_local_path(preview_path, repo_root=repo_root)
    if os.name == "nt":
        os.startfile(local_path)  # type: ignore[attr-defined]
    else:
        webbrowser.open(local_path)
    return {
        "status": "opened",
        "artifact_path": preview_path,
        "local_path": local_path,
        "capture": capture,
    }


def request_apply_material_override(
    scene_id: str,
    *,
    prim_paths: list[str],
    bsdf_type: str,
    daemon_url: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    return queue_isaac_command(
        "apply_material_override",
        scene_id=scene_id,
        payload={
            "prim_paths": [str(path) for path in prim_paths if str(path)],
            "bsdf_type": str(bsdf_type),
        },
        daemon_url=daemon_url,
        timeout_s=timeout_s,
    )


def capture_isaac_view(
    *,
    daemon_url: str | None = None,
    modalities: list[str] | None = None,
    submit_mode: str = "blocking",
    render_settings: dict[str, Any] | None = None,
    timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
    variant: str | None = None,
    command_id: str | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from robomituba_bridge import IsaacCaptureRequest
    try:
        from isaac_extension.stage_capture import capture_current_view_camera
    except ImportError:  # pragma: no cover - Isaac runtime fallback
        from stage_capture import capture_current_view_camera

    capture_request = IsaacCaptureRequest(
        camera=capture_current_view_camera(),
        modalities=list(modalities or ["rgb"]),
        submit_mode=submit_mode,
        render_settings=dict(render_settings or {}),
    )
    return capture_isaac(
        capture_request,
        daemon_url=daemon_url,
        timeout_s=timeout_s,
        variant=variant,
        command_id=command_id,
        extras=extras,
    )


def get_render_job_status(job_id: str, *, daemon_url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{_resolve_daemon_url(daemon_url)}/jobs/{job_id}", timeout_s=timeout_s)


def wait_for_render_job(
    job_id: str,
    *,
    daemon_url: str | None = None,
    poll_interval_s: float = 1.0,
    timeout_s: float = 600.0,
    on_status: "Callable[[dict[str, Any]], None] | None" = None,
) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout_s
    last_status: dict[str, Any] | None = None
    consecutive_errors = 0
    while time.monotonic() < deadline:
        try:
            last_status = get_render_job_status(job_id, daemon_url=daemon_url, timeout_s=15.0)
            consecutive_errors = 0
        except Exception as poll_err:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                raise RuntimeError(
                    f"Failed to reach daemon after 5 consecutive attempts while polling job {job_id}: {poll_err}"
                ) from poll_err
            time.sleep(poll_interval_s)
            continue
        if on_status is not None:
            try:
                on_status(last_status)
            except Exception:
                pass
        if last_status.get("status") in {"succeeded", "failed", "cancelled"}:
            return last_status
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Timed out waiting for render job {job_id}. Last status: {last_status}")


@dataclass(frozen=True)
class RobomitubaDaemonClient:
    url: str = DEFAULT_DAEMON_URL
    repo_root: str = DEFAULT_REPO_ROOT

    def list_scenes(self, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        return list_scenes_from_daemon(daemon_url=self.url, timeout_s=timeout_s)

    def get_scene(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return get_scene_from_daemon(scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def list_commands(self, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        return list_isaac_commands(daemon_url=self.url, timeout_s=timeout_s)

    def register_scene(
        self,
        *,
        usd_stage_path: str,
        scene_id: str | None = None,
        mitsuba_scene_ref: str | None = None,
        shape_map_ref: str | None = None,
        scene_snapshot_ref: str | None = None,
        scene_version: str | None = None,
        illumination_setup: str | None = None,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        return register_scene_with_daemon(
            daemon_url=self.url,
            usd_stage_path=usd_stage_path,
            scene_id=scene_id,
            mitsuba_scene_ref=mitsuba_scene_ref,
            shape_map_ref=shape_map_ref,
            scene_snapshot_ref=scene_snapshot_ref,
            scene_version=scene_version,
            illumination_setup=illumination_setup,
            timeout_s=timeout_s,
        )

    def load_scene(
        self,
        *,
        scene_id: str | None = None,
        usd_path: str | None = None,
        timeout_s: float = DEFAULT_LOAD_SCENE_TIMEOUT_S,
    ) -> dict[str, Any]:
        return load_scene_from_daemon(
            daemon_url=self.url,
            scene_id=scene_id,
            usd_path=usd_path,
            repo_root=self.repo_root,
            timeout_s=timeout_s,
        )

    def get_session(self, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return get_isaac_session(daemon_url=self.url, timeout_s=timeout_s)

    def list_material_presets(self, *, timeout_s: float = 10.0) -> list[dict[str, Any]]:
        return list_material_presets(daemon_url=self.url, timeout_s=timeout_s)

    def get_scene_texture_cache_status(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        payload = self.get_scene(scene_id, timeout_s=timeout_s)
        return get_scene_texture_cache_status(
            scene_id,
            payload.get("scene") or {},
            daemon_url=self.url,
            repo_root=self.repo_root,
            timeout_s=timeout_s,
        )

    def ensure_scene_texture_cache(self, scene_id: str, *, timeout_s: float = 30.0) -> dict[str, Any]:
        payload = self.get_scene(scene_id, timeout_s=min(timeout_s, 10.0))
        return ensure_scene_texture_cache(
            scene_id,
            payload.get("scene") or {},
            daemon_url=self.url,
            repo_root=self.repo_root,
            timeout_s=timeout_s,
        )

    def connect_scene_session(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return connect_scene_session_from_daemon(scene_id, daemon_url=self.url, repo_root=self.repo_root, timeout_s=timeout_s)

    def prepare_render_ready(
        self,
        scene_id: str,
        *,
        stage: Any | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        return prepare_render_ready_from_daemon(
            scene_id,
            stage=stage,
            daemon_url=self.url,
            repo_root=self.repo_root,
            timeout_s=timeout_s,
        )

    def request_load_scene(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return queue_isaac_command("load_scene", scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def request_prepare_render_ready(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return queue_isaac_command("prepare_render_ready", scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def request_connect_session(self, scene_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return queue_isaac_command("connect_session", scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def request_sync_session(self, scene_id: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
        return queue_isaac_command("sync_session", scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def update_selection(self, selected_prim_paths: list[str], *, timeout_s: float = 10.0) -> dict[str, Any]:
        return update_isaac_selection(selected_prim_paths, daemon_url=self.url, timeout_s=timeout_s)

    def sync_scene_state(
        self,
        stage: Any,
        scene_id: str,
        *,
        bsdf_overrides_by_path: dict[str, Any] | None = None,
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        return sync_scene_state_to_daemon(
            stage,
            scene_id,
            daemon_url=self.url,
            bsdf_overrides_by_path=bsdf_overrides_by_path,
            timeout_s=timeout_s,
        )

    def render_current_view(
        self,
        scene_id: str,
        *,
        stage: Any | None = None,
        submit_mode: str = "blocking",
        modalities: list[str] | None = None,
        render_settings: dict[str, Any] | None = None,
        bsdf_overrides_by_path: dict[str, Any] | None = None,
        timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
        variant: str | None = None,
        sync_policy: str = "auto",
        force_resync: bool = False,
    ) -> dict[str, Any]:
        return render_current_view_from_daemon(
            scene_id,
            stage=stage,
            daemon_url=self.url,
            submit_mode=submit_mode,
            modalities=modalities,
            render_settings=render_settings,
            bsdf_overrides_by_path=bsdf_overrides_by_path,
            timeout_s=timeout_s,
            variant=variant,
            sync_policy=sync_policy,
            force_resync=force_resync,
        )

    def request_render_current_view(
        self,
        scene_id: str,
        *,
        submit_mode: str = "blocking",
        modalities: list[str] | None = None,
        sync_policy: str = "auto",
        force_resync: bool = False,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"submit_mode": submit_mode, "sync_policy": sync_policy, "force_resync": force_resync}
        if modalities:
            payload["modalities"] = list(modalities)
        return queue_isaac_command(
            "render_current_view",
            scene_id=scene_id,
            payload=payload,
            daemon_url=self.url,
            timeout_s=timeout_s,
        )

    def render_sensor(
        self,
        scene_id: str,
        sensor_id: str,
        *,
        stage: Any | None = None,
        submit_mode: str = "blocking",
        modalities: list[str] | None = None,
        render_settings: dict[str, Any] | None = None,
        bsdf_overrides_by_path: dict[str, Any] | None = None,
        timeout_s: float = DEFAULT_RENDER_TIMEOUT_S,
        variant: str | None = None,
        sync_policy: str = "auto",
        force_resync: bool = False,
    ) -> dict[str, Any]:
        return render_sensor_from_daemon(
            scene_id,
            sensor_id,
            stage=stage,
            daemon_url=self.url,
            submit_mode=submit_mode,
            modalities=modalities,
            render_settings=render_settings,
            bsdf_overrides_by_path=bsdf_overrides_by_path,
            timeout_s=timeout_s,
            variant=variant,
            sync_policy=sync_policy,
            force_resync=force_resync,
        )

    def latest_capture(self, *, scene_id: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
        return get_latest_capture_from_daemon(scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def request_open_latest_capture(self, *, scene_id: str | None = None, timeout_s: float = 10.0) -> dict[str, Any]:
        return queue_isaac_command("open_latest_capture", scene_id=scene_id, daemon_url=self.url, timeout_s=timeout_s)

    def request_apply_material_override(
        self,
        scene_id: str,
        *,
        prim_paths: list[str],
        bsdf_type: str,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        return request_apply_material_override(
            scene_id,
            prim_paths=prim_paths,
            bsdf_type=bsdf_type,
            daemon_url=self.url,
            timeout_s=timeout_s,
        )

    def get_capture(self, job_id: str, frame_id: str, *, timeout_s: float = 10.0) -> dict[str, Any]:
        return get_capture_from_daemon(job_id, frame_id, daemon_url=self.url, timeout_s=timeout_s)

    def open_capture(
        self,
        *,
        scene_id: str | None = None,
        job_id: str | None = None,
        frame_id: str | None = None,
        timeout_s: float = 10.0,
    ) -> dict[str, Any]:
        return open_capture_from_daemon(
            daemon_url=self.url,
            scene_id=scene_id,
            job_id=job_id,
            frame_id=frame_id,
            repo_root=self.repo_root,
            timeout_s=timeout_s,
        )


def connect_daemon(
    daemon_url: str | None = None,
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
) -> RobomitubaDaemonClient:
    return RobomitubaDaemonClient(url=_resolve_daemon_url(daemon_url), repo_root=resolve_windows_repo_root(repo_root))
