from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlparse

import numpy as np


DEFAULT_UNC_REPO_ROOT = r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"
DEFAULT_MITSUBA_SCENE_REF = "out/moorelane_full_cam03_rgb_all/scene_full_sanitized_direct.xml"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"


def resolve_windows_repo_root(repo_root: str | None = None) -> str:
    import os

    return (
        repo_root
        or os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
        or os.environ.get("ROBOMITUBA_ROOT")
        or DEFAULT_UNC_REPO_ROOT
    )


DEFAULT_REPO_ROOT = resolve_windows_repo_root()


def _require_isaac_imports():
    import omni.usd  # type: ignore
    from omni.kit.viewport.utility import get_active_viewport  # type: ignore
    from pxr import Usd, UsdGeom  # type: ignore

    return omni.usd, get_active_viewport, Usd, UsdGeom


def _stage_url_to_windows_path(stage_url: str) -> PureWindowsPath:
    if stage_url.startswith("file:"):
        parsed = urlparse(stage_url)
        netloc = unquote(parsed.netloc)
        path = unquote(parsed.path).lstrip("/")
        normalized_path = path.replace("/", "\\")
        if netloc:
            return PureWindowsPath(f"\\\\{netloc}\\{normalized_path}")
        return PureWindowsPath(normalized_path)
    return PureWindowsPath(stage_url)


def _repo_relative_posix(repo_root: str | Path, target: str | Path) -> str:
    root = PureWindowsPath(str(repo_root))
    candidate = PureWindowsPath(str(target))
    return candidate.relative_to(root).as_posix()


def _current_timestamp() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _coerce_matrix4(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    try:
        if hasattr(value, "tolist"):
            value = value.tolist()
    except Exception:
        pass
    try:
        matrix = np.asarray(value, dtype=np.float32)
    except Exception:
        return None
    if matrix.shape == (16,):
        matrix = matrix.reshape(4, 4)
    if matrix.shape != (4, 4):
        return None
    return matrix


def _extract_viewport_resolution(viewport: Any) -> list[int]:
    candidates = [
        getattr(viewport, "resolution", None),
        getattr(getattr(viewport, "viewport_api", None), "resolution", None),
        getattr(viewport, "texture_resolution", None),
        getattr(getattr(viewport, "viewport_api", None), "texture_resolution", None),
    ]
    for candidate in candidates:
        try:
            if candidate is None:
                continue
            width = int(candidate[0])
            height = int(candidate[1])
            if width > 0 and height > 0:
                return [width, height]
        except Exception:
            continue
    return [1280, 720]


def _fov_from_projection_matrix(projection: np.ndarray | None) -> float | None:
    if projection is None:
        return None
    try:
        horizontal = math.degrees(2.0 * math.atan(1.0 / max(abs(float(projection[0, 0])), 1e-6)))
        vertical = math.degrees(2.0 * math.atan(1.0 / max(abs(float(projection[1, 1])), 1e-6)))
    except Exception:
        return None
    candidates = [value for value in (horizontal, vertical) if math.isfinite(value) and 1.0 <= value <= 179.0]
    if not candidates:
        return None
    return max(candidates)


def _normalize_camera_to_world_matrix(matrix: np.ndarray) -> np.ndarray:
    candidate = np.asarray(matrix, dtype=np.float32)
    if candidate.shape == (16,):
        candidate = candidate.reshape(4, 4)
    if candidate.shape != (4, 4):
        return candidate
    last_col = candidate[:3, 3]
    last_row = candidate[3, :3]
    last_row_strength = float(np.linalg.norm(last_row))
    last_col_strength = float(np.linalg.norm(last_col))
    if last_row_strength > max(1e-4, last_col_strength * 2.0):
        candidate = candidate.T
    return candidate


def _camera_info_from_viewport_matrix_fallback(viewport: Any) -> dict[str, Any] | None:
    api_candidates = [getattr(viewport, "viewport_api", None), viewport]
    for candidate in api_candidates:
        if candidate is None:
            continue
        view_matrix = None
        projection_matrix = None
        for attr in ("get_view_matrix", "view_matrix", "view"):
            try:
                value = getattr(candidate, attr)
            except Exception:
                continue
            try:
                value = value() if callable(value) else value
            except Exception:
                continue
            view_matrix = _coerce_matrix4(value)
            if view_matrix is not None:
                break
        for attr in ("get_projection_matrix", "projection_matrix", "projection"):
            try:
                value = getattr(candidate, attr)
            except Exception:
                continue
            try:
                value = value() if callable(value) else value
            except Exception:
                continue
            projection_matrix = _coerce_matrix4(value)
            if projection_matrix is not None:
                break
        if view_matrix is None:
            continue
        try:
            camera_to_world = np.linalg.inv(view_matrix)
        except Exception:
            continue
        camera_to_world = _normalize_camera_to_world_matrix(camera_to_world)
        fov_deg = _fov_from_projection_matrix(projection_matrix) or 60.0
        camera_path = getattr(viewport, "camera_path", None)
        camera_path_str = getattr(camera_path, "pathString", None) or (str(camera_path) if camera_path is not None else None) or "<viewport>"
        return {
            "camera_path": camera_path_str,
            "camera_to_world": camera_to_world.reshape(-1).astype(float).tolist(),
            "fov_deg": float(fov_deg),
            "resolution": _extract_viewport_resolution(viewport),
        }
    return None


def capture_active_view_camera() -> dict[str, Any]:
    omni_usd, get_active_viewport, Usd, UsdGeom = _require_isaac_imports()

    stage = omni_usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No USD stage is currently open in Isaac Sim.")

    viewport = get_active_viewport()
    camera_path = viewport.camera_path
    camera_path_str = camera_path.pathString if hasattr(camera_path, "pathString") else str(camera_path)
    camera_prim = stage.GetPrimAtPath(camera_path_str)
    if not camera_prim or not camera_prim.IsValid():
        fallback = _camera_info_from_viewport_matrix_fallback(viewport)
        if fallback is not None:
            return fallback
        raise RuntimeError(f"Active viewport camera prim is invalid: {camera_path_str}")

    camera = UsdGeom.Camera(camera_prim)
    xform = UsdGeom.Xformable(camera_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    camera_to_world_matrix = _normalize_camera_to_world_matrix(np.asarray(xform, dtype=np.float32))
    camera_to_world = camera_to_world_matrix.reshape(-1).astype(float).tolist()

    focal_length = float(camera.GetFocalLengthAttr().Get() or 50.0)
    horizontal_aperture = float(camera.GetHorizontalApertureAttr().Get() or 20.955)
    fov_deg = math.degrees(2.0 * math.atan((horizontal_aperture * 0.5) / max(focal_length, 1e-6)))

    width, height = _extract_viewport_resolution(viewport)

    return {
        "camera_path": camera_path_str,
        "camera_to_world": camera_to_world,
        "fov_deg": fov_deg,
        "resolution": [width, height],
    }


def capture_current_view_request(
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
    mitsuba_scene_ref: str = DEFAULT_MITSUBA_SCENE_REF,
    scene_id: str = "moorelane",
    scene_version: str = "curated_shell_furniture_sanitized",
    job_prefix: str = "isaac-current-view",
    frame_prefix: str = "frame",
    request_prefix: str = "request",
):
    from robomituba_bridge import AssistLightSpec, CameraSpec, RenderRequest, RobotState, SceneState, render_request_to_payload

    omni_usd, _get_active_viewport, _Usd, _UsdGeom = _require_isaac_imports()

    repo_root_path = PureWindowsPath(resolve_windows_repo_root(str(repo_root)))
    stage_url = omni_usd.get_context().get_stage_url()
    if not stage_url:
        raise RuntimeError("Current stage does not have a URL. Save the stage or open a USD file first.")

    stage_path = _stage_url_to_windows_path(stage_url)
    timestamp = _current_timestamp()
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    camera_info = capture_active_view_camera()

    job_id = f"{job_prefix}-{stamp}"
    frame_id = f"{frame_prefix}_{stamp}"
    request_id = f"{request_prefix}_{stamp}"

    scene_state = SceneState(
        job_id=job_id,
        scene_id=scene_id,
        frame_id=frame_id,
        timestamp=timestamp,
        scene_snapshot_ref=_repo_relative_posix(repo_root_path, stage_path),
        mitsuba_scene_ref=mitsuba_scene_ref,
        scene_version=scene_version,
        illumination_setup="ambient_room",
        extras={
            "stage_url": stage_url,
        },
    )
    camera_spec = CameraSpec(
        camera_id="viewport_current",
        name="Isaac Active View",
        camera_to_world=list(camera_info["camera_to_world"]),
        fov_deg=float(camera_info["fov_deg"]),
        resolution=list(camera_info["resolution"]),
        sensor_modality="multimodal",
        sensor_sync_group="isaac_viewport",
        calibration_ref="isaac_active_view",
        source_camera_id=camera_info["camera_path"],
        extras={
            "stage_camera_path": camera_info["camera_path"],
        },
    )
    robot_state = RobotState()
    try:
        from isaac_standalone._stage_bridge import extract_snapshot as _extract_snapshot

        scene_snapshot = _extract_snapshot(stage, scene_id=scene_id, frame_id=frame_id)
        if scene_snapshot.robot_state is not None:
            robot_state = scene_snapshot.robot_state
    except Exception:
        robot_state = RobotState()

    request = RenderRequest(
        request_id=request_id,
        job_id=job_id,
        frame_id=frame_id,
        timestamp=timestamp,
        scene_state=scene_state,
        camera_specs=[camera_spec],
        modalities=[
            "rgb",
            "depth",
            "active_nir_intensity",
            "polar_rgb_preview",
            "s1",
            "s2",
            "dop",
            "aolp",
        ],
        robot_state=robot_state,
        render_settings={
            "width": int(camera_info["resolution"][0]),
            "height": int(camera_info["resolution"][1]),
            "path_spp": 4096,
            "aov_spp": 24,
            "polar_spp": 1024,
            "path_max_depth": 5,
            "rr_depth": 6,
            "samples_per_pass": 128,
        },
        scene_override=None,
        assist_light=AssistLightSpec(
            mode="camera_aligned_rect",
            distance_m=0.14,
            size_world=[4.8, 3.6],
            spectrum_mode="nir_grayscale_proxy",
            polarized=True,
            polarizer_angle_deg=0.0,
            extras={"radiance": 40.0},
        ),
        depth_approx=None,
        extras={
            "branch_policy": "ambient_active_split",
            "stage_url": stage_url,
            "stage_camera_path": camera_info["camera_path"],
        },
    )
    _ = render_request_to_payload(request)
    return request


def save_current_view_render_request(
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
    mitsuba_scene_ref: str = DEFAULT_MITSUBA_SCENE_REF,
    scene_id: str = "moorelane",
    scene_version: str = "curated_shell_furniture_sanitized",
    job_prefix: str = "isaac-current-view",
    frame_prefix: str = "frame",
    request_prefix: str = "request",
) -> str:
    from robomituba_bridge import render_request_to_payload

    request = capture_current_view_request(
        repo_root=repo_root,
        mitsuba_scene_ref=mitsuba_scene_ref,
        scene_id=scene_id,
        scene_version=scene_version,
        job_prefix=job_prefix,
        frame_prefix=frame_prefix,
        request_prefix=request_prefix,
    )
    repo_root_path = PureWindowsPath(resolve_windows_repo_root(str(repo_root)))
    requests_dir = Path(str(repo_root_path / "out" / "bridge_jobs" / request.job_id / "requests"))
    requests_dir.mkdir(parents=True, exist_ok=True)
    request_path = requests_dir / f"{request.frame_id}.json"
    request_path.write_text(
        json.dumps(render_request_to_payload(request), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved RenderRequest: {request_path}")
    return str(request_path)


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, *, timeout_s: float = 10.0) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} calling {url}: {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach render daemon at {url}: {exc}") from exc


def submit_render_request(
    render_request,
    *,
    daemon_url: str = DEFAULT_DAEMON_URL,
    runtime_overrides: dict[str, Any] | None = None,
    variant: str | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    from robomituba_bridge import RenderRequest, render_request_to_payload

    if isinstance(render_request, RenderRequest):
        request_payload = render_request_to_payload(render_request)
    else:
        request_payload = dict(render_request)

    payload: dict[str, Any] = {"render_request": request_payload}
    if runtime_overrides:
        payload["runtime_overrides"] = dict(runtime_overrides)
    if variant:
        payload["variant"] = variant
    return _http_json("POST", f"{daemon_url.rstrip('/')}/render", payload, timeout_s=timeout_s)


def get_render_job_status(job_id: str, *, daemon_url: str = DEFAULT_DAEMON_URL, timeout_s: float = 10.0) -> dict[str, Any]:
    return _http_json("GET", f"{daemon_url.rstrip('/')}/jobs/{job_id}", timeout_s=timeout_s)


def wait_for_render_job(
    job_id: str,
    *,
    daemon_url: str = DEFAULT_DAEMON_URL,
    poll_interval_s: float = 1.0,
    timeout_s: float = 600.0,
) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + timeout_s
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_status = get_render_job_status(job_id, daemon_url=daemon_url, timeout_s=min(10.0, poll_interval_s + 5.0))
        if last_status.get("status") in {"succeeded", "failed", "cancelled"}:
            return last_status
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Timed out waiting for render job {job_id}. Last status: {last_status}")


def capture_and_submit_current_view_request(
    *,
    repo_root: str = DEFAULT_REPO_ROOT,
    mitsuba_scene_ref: str = DEFAULT_MITSUBA_SCENE_REF,
    scene_id: str = "moorelane",
    scene_version: str = "curated_shell_furniture_sanitized",
    daemon_url: str = DEFAULT_DAEMON_URL,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    request = capture_current_view_request(
        repo_root=repo_root,
        mitsuba_scene_ref=mitsuba_scene_ref,
        scene_id=scene_id,
        scene_version=scene_version,
    )
    return submit_render_request(request, daemon_url=daemon_url, timeout_s=timeout_s)


if __name__ == "__main__":
    save_current_view_render_request()
