from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlparse


DEFAULT_REPO_ROOT = r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"
DEFAULT_MITSUBA_SCENE_REF = "out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"


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
        if netloc:
            return PureWindowsPath(f"\\\\{netloc}\\{path.replace('/', '\\')}")
        return PureWindowsPath(path.replace("/", "\\"))
    return PureWindowsPath(stage_url)


def _repo_relative_posix(repo_root: str | Path, target: str | Path) -> str:
    root = PureWindowsPath(str(repo_root))
    candidate = PureWindowsPath(str(target))
    return candidate.relative_to(root).as_posix()


def _current_timestamp() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


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
        raise RuntimeError(f"Active viewport camera prim is invalid: {camera_path_str}")

    camera = UsdGeom.Camera(camera_prim)
    xform = UsdGeom.Xformable(camera_prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    camera_to_world = [float(xform[row][col]) for row in range(4) for col in range(4)]

    focal_length = float(camera.GetFocalLengthAttr().Get() or 50.0)
    horizontal_aperture = float(camera.GetHorizontalApertureAttr().Get() or 20.955)
    fov_deg = math.degrees(2.0 * math.atan((horizontal_aperture * 0.5) / max(focal_length, 1e-6)))

    resolution = getattr(viewport, "resolution", None)
    if resolution is None:
        width, height = 1280, 720
    else:
        width, height = int(resolution[0]), int(resolution[1])

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

    repo_root_path = PureWindowsPath(repo_root)
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
        robot_state=RobotState(),
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
    repo_root_path = PureWindowsPath(repo_root)
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
