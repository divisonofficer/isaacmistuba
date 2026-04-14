from __future__ import annotations

from collections import deque
import concurrent.futures
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, quote, urlparse

import numpy as np
from jinja2 import Environment, FileSystemLoader, select_autoescape

from robomituba_bridge import (
    AssistLightSpec,
    CameraSpec,
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

from .multimodal import camera_to_world_to_lookat
from .observation_bridge import render_timestep_bundle_split_lighting
from .scene_floorplan import CameraOverlay, LightOverlay, render_scene_floorplan


RenderFn = Callable[..., ObservationBundleManifest]


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


@dataclass
class _QueuedJob:
    render_request: RenderRequest
    status: RenderJobStatus
    request_payload: dict[str, Any]
    variant: str
    runtime_overrides: dict[str, Any]


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
        self._shutdown = False
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None

        asset_root = Path(__file__).resolve().parent
        self._templates_dir = asset_root / "templates"
        self._static_dir = asset_root / "static"
        self._jinja = Environment(
            loader=FileSystemLoader(str(self._templates_dir)),
            autoescape=select_autoescape(("html", "xml")),
        )

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
                return

            def do_GET(self) -> None:  # noqa: N802
                self.daemon._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                self.daemon._handle_post(self)

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

    def submit_payload(self, payload: Mapping[str, Any]) -> RenderJobAccepted:
        request_payload = dict(payload)
        runtime_overrides = request_payload.pop("runtime_overrides", None)
        variant = request_payload.pop("variant", self.variant)
        nested_request = request_payload.pop("render_request", None)
        if request_payload:
            if nested_request is not None:
                raise ValueError("Unexpected keys alongside render_request envelope.")
            nested_request = payload
            runtime_overrides = None
            variant = self.variant

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
        return self.submit(render_request, variant=str(variant), runtime_overrides=dict(runtime_overrides))

    def submit(
        self,
        render_request: RenderRequest,
        *,
        variant: str | None = None,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> RenderJobAccepted:
        chosen_variant = str(variant or self.variant)
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

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/health":
                self._send_json(handler, HTTPStatus.OK, self._health_payload())
                return
            if path in {"/", "/admin"}:
                self._send_html(handler, HTTPStatus.OK, self._render_page("home.html", nav_key="home", page_title="Operations Home", page_subtitle="Warm Mitsuba daemon, scene bundles, and quick smoke actions.", recent_jobs=self._recent_jobs(limit=8), failed_jobs=self._failed_jobs(limit=5), scenes=self._scene_records(limit=6)))
                return
            if path == "/jobs":
                self._send_html(handler, HTTPStatus.OK, self._render_page("jobs.html", nav_key="jobs", page_title="Render Jobs", page_subtitle="Daemon queue and historical job state from out/bridge_jobs.", jobs=self._job_records(limit=100)))
                return
            if path == "/scenes":
                self._send_html(handler, HTTPStatus.OK, self._render_page("scenes.html", nav_key="scenes", page_title="Scene Explorer", page_subtitle="Observation bundle centric view of scenes and captures.", scenes=self._scene_records()))
                return
            if path.startswith("/scenes/"):
                scene_id = path[len("/scenes/"):]
                scene_detail = self._scene_detail(scene_id)
                floorplan = self._ensure_floorplan(scene_id)
                self._send_html(handler, HTTPStatus.OK, self._render_page("scene_detail.html", nav_key="scenes", page_title=f"Scene · {scene_id}", page_subtitle="Top-down floorplan, overlay cameras, and modality explorer.", scene=scene_detail["scene"], captures=scene_detail["captures"], latest_capture=scene_detail["latest_capture"], floorplan=floorplan))
                return
            if path == "/system":
                self._send_html(handler, HTTPStatus.OK, self._render_page("system.html", nav_key="system", page_title="System", page_subtitle="Worker, cache, and runtime overview.", jobs=self._job_records(limit=20)))
                return
            if path == "/integrations/isaac":
                self._send_html(handler, HTTPStatus.OK, self._render_page("isaac.html", nav_key="isaac", page_title="Isaac Integration", page_subtitle="Current viewport capture and daemon submit flow.", guide=self._isaac_guide_payload()))
                return
            if path == "/static/tailwind.css":
                self._serve_static_file(handler, self._static_dir / "tailwind.css")
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
            if path == "/api/scenes":
                self._send_json(handler, HTTPStatus.OK, {"scenes": self._scene_records()})
                return
            if path.startswith("/api/scenes/") and path.endswith("/floorplan"):
                scene_id = path[len("/api/scenes/") : -len("/floorplan")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._ensure_floorplan(scene_id))
                return
            if path.startswith("/api/scenes/") and path.endswith("/captures"):
                scene_id = path[len("/api/scenes/") : -len("/captures")].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, {"scene_id": scene_id, "captures": self._scene_detail(scene_id)["captures"]})
                return
            if path.startswith("/api/scenes/"):
                scene_id = path[len("/api/scenes/") :].rstrip("/")
                self._send_json(handler, HTTPStatus.OK, self._scene_detail(scene_id))
                return
            if path == "/api/integrations/isaac":
                self._send_json(handler, HTTPStatus.OK, self._isaac_guide_payload())
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

            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})
        except _ClientDisconnectedError:
            return
        except Exception as exc:  # pragma: no cover - defensive path
            try:
                self._send_json(handler, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            except _ClientDisconnectedError:
                return

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        try:
            parsed = urlparse(handler.path)
            path = parsed.path
            payload = self._read_request_body(handler)

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
                timeout_s = float(payload.get("timeout_s", 120.0))
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
            camera_to_world=list(cam.camera_to_world),
            fov_deg=float(cam.fov_deg),
            resolution=list(cam.resolution) if cam.resolution is not None else None,
            sensor_modality=cam.sensor_modality,
            sensor_sync_group=cam.sensor_sync_group,
            calibration_ref=cam.calibration_ref,
            source_camera_id=cam.source_camera_id,
            extras=dict(cam.extras),
        )
        render_request = RenderRequest(
            request_id=request_id,
            job_id=job_id,
            frame_id=frame_id,
            timestamp=timestamp,
            scene_state=scene_state,
            camera_specs=[camera_spec],
            modalities=list(snapshot.modalities) if snapshot.modalities else ["rgb"],
            robot_state=snapshot.robot_state or RobotState(),
            render_settings=dict(snapshot.render_settings),
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

    def _handle_isaac_render_submit(self, payload: dict[str, Any]) -> RenderJobAccepted:
        snapshot = isaac_state_snapshot_from_payload(payload["isaac_state"])
        render_request, _shape_map_ref = self._render_request_from_isaac_snapshot(snapshot)
        variant = str(payload.get("variant") or render_request.render_settings.get("variant") or self.variant)
        runtime_overrides = payload.get("runtime_overrides") or {}
        return self.submit(render_request, variant=variant, runtime_overrides=runtime_overrides)

    def _handle_isaac_render_blocked(self, payload: dict[str, Any], *, timeout_s: float = 120.0) -> dict[str, Any]:
        """Handle POST /isaac/render in blocked mode — wait for render, return artifacts immediately."""
        snapshot = isaac_state_snapshot_from_payload(payload["isaac_state"])
        render_request, shape_map_ref = self._render_request_from_isaac_snapshot(snapshot)
        variant = str(payload.get("variant") or render_request.render_settings.get("variant") or self.variant)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                self.render_fn,
                render_request,
                repo_root=self.repo_root,
                variant=variant,
                progress_callback=None,
            )
            bundle = future.result(timeout=timeout_s)

        return {
            "status": "completed",
            "snapshot_id": snapshot.snapshot_id,
            "job_id": render_request.job_id,
            "frame_id": render_request.frame_id,
            "shape_map_ref": shape_map_ref,
            "manifest_path": f"{bundle.bundle_root}/manifest.json",
            "artifacts": _artifact_paths_from_bundle(bundle),
        }

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
                self._persist_status_unlocked(job)

            try:
                scene_cache_key = self._scene_cache_key(job.render_request, job.variant)
                with self._condition:
                    cache_stats = self._scene_cache_stats.setdefault(scene_cache_key, {"submissions": 0, "runs": 0})
                    cache_stats["runs"] += 1
                    cache_stats["last_started_at"] = job.status.started_at
                    job.status.extras["scene_cache_runs"] = int(cache_stats["runs"])
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
            self._persist_status_unlocked(job)

    def _mark_failed(self, job_id: str, error: str) -> None:
        with self._condition:
            job = self._jobs[job_id]
            job.status.status = "failed"
            job.status.finished_at = _utc_now_iso()
            job.status.progress_stage = "failed"
            job.status.error = error
            self._persist_status_unlocked(job)

    def _update_progress(self, job_id: str, stage: str, payload: Mapping[str, Any] | None) -> None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None or job.status.status != "running":
                return
            job.status.progress_stage = stage
            if payload:
                job.status.extras["progress_context"] = dict(payload)
            self._persist_status_unlocked(job)

    def _scene_cache_key(self, render_request: RenderRequest, variant: str) -> str:
        branch_policy = str(render_request.extras.get("branch_policy", "default"))
        return f"{render_request.scene_state.mitsuba_scene_ref}|{branch_policy}|{variant}"

    def _status_path(self, job_id: str) -> Path:
        return self.repo_root / "out" / "bridge_jobs" / job_id / "job_status.json"

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

    def _send_json(self, handler: BaseHTTPRequestHandler, status_code: int, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(handler, status_code, encoded, content_type="application/json; charset=utf-8")

    def _send_html(self, handler: BaseHTTPRequestHandler, status_code: int, html: str) -> None:
        encoded = html.encode("utf-8")
        self._send_bytes(handler, status_code, encoded, content_type="text/html; charset=utf-8")

    def _send_bytes(self, handler: BaseHTTPRequestHandler, status_code: int, payload: bytes, *, content_type: str) -> None:
        try:
            handler.send_response(status_code)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            raise _ClientDisconnectedError from None

    def _serve_static_file(self, handler: BaseHTTPRequestHandler, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"Static asset not found: {path.name}"})
            return
        self._serve_file(handler, path, default_type="text/css; charset=utf-8")

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

    def _serve_file(self, handler: BaseHTTPRequestHandler, path: Path, *, default_type: str | None = None) -> None:
        payload = path.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(path))
        content_type = default_type or mime_type or "application/octet-stream"
        self._send_bytes(handler, HTTPStatus.OK, payload, content_type=content_type)

    def _nav_items(self) -> list[dict[str, str]]:
        return [
            {"key": "home", "label": "Home", "href": "/"},
            {"key": "scenes", "label": "Scenes", "href": "/scenes"},
            {"key": "jobs", "label": "Jobs", "href": "/jobs"},
            {"key": "system", "label": "System", "href": "/system"},
            {"key": "isaac", "label": "Isaac Guide", "href": "/integrations/isaac"},
        ]

    def _render_page(self, template_name: str, *, nav_key: str, page_title: str, page_subtitle: str = "", flash_message: str | None = None, **context: Any) -> str:
        template = self._jinja.get_template(template_name)
        summary = self._summary_payload()
        return template.render(
            page_title=page_title,
            page_subtitle=page_subtitle,
            nav_key=nav_key,
            nav_items=self._nav_items(),
            base_url=self.base_url,
            latest_scene_id=summary.get("latest_scene_id"),
            summary=summary,
            flash_message=flash_message,
            **context,
        )

    def _health_payload(self) -> dict[str, Any]:
        summary = self._summary_payload()
        return {
            "status": "ok",
            "base_url": self.base_url,
            "worker_state": summary["worker_state"],
            "queue_length": summary["queue_length"],
            "variant": summary["variant"],
        }

    def _snapshot_state(self) -> tuple[list[str], dict[str, RenderJobStatus], dict[str, dict[str, Any]]]:
        with self._condition:
            pending = list(self._pending)
            jobs = {job_id: RenderJobStatus(**render_job_status_to_payload(job.status)) for job_id, job in self._jobs.items()}
            cache_stats = {key: dict(value) for key, value in self._scene_cache_stats.items()}
        return pending, jobs, cache_stats

    def _status_file_records(self) -> dict[str, RenderJobStatus]:
        records: dict[str, RenderJobStatus] = {}
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            return records
        for status_path in root.glob("*/job_status.json"):
            try:
                status = read_render_job_status(status_path)
            except Exception:
                continue
            records[status.job_id] = status
        return records

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

    def _job_record_from_status(self, status: RenderJobStatus, *, queue_position: int | None) -> dict[str, Any]:
        request = self._load_saved_request(status.job_id, status.frame_id)
        scene_id = request.scene_state.scene_id if request is not None else None
        scene_version = request.scene_state.scene_version if request is not None else None
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

    def _bundle_manifests(self) -> list[ObservationBundleManifest]:
        root = self.repo_root / "out" / "bridge_jobs"
        if not root.exists():
            return []
        bundles: list[ObservationBundleManifest] = []
        for manifest_path in root.glob("*/observations/*/manifest.json"):
            try:
                bundles.append(read_observation_bundle_manifest(manifest_path))
            except Exception:
                continue
        bundles.sort(key=lambda item: _safe_sort_ts(item.timestamp), reverse=True)
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

    def _capture_records(self, bundle: ObservationBundleManifest) -> list[dict[str, Any]]:
        camera_map = {camera.camera_id: camera for camera in bundle.camera_specs}
        per_camera: dict[str, dict[str, Any]] = {}
        for artifact in bundle.artifacts:
            camera_id = artifact.camera_id
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
                },
            )
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
        if scene_record is not None:
            scene_record["capture_count"] = len(captures)
            scene_record["camera_count"] = len({capture["camera_id"] for capture in captures})
        return {
            "scene_id": scene_id,
            "scene": scene_record,
            "captures": captures,
            "latest_capture": captures[0] if captures else None,
        }

    def _summary_payload(self) -> dict[str, Any]:
        pending, _memory_statuses, cache_stats = self._snapshot_state()
        jobs = self._job_records()
        scenes = self._scene_records()
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
            "latest_failure_job_id": failed_jobs[0]["job_id"] if failed_jobs else None,
            "scene_cache_stats": scene_cache_items,
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
        request_dict["modalities"] = ["rgb", "depth"]
        request_dict["render_settings"] = {
            **request_dict.get("render_settings", {}),
            "width": 640,
            "height": 360,
            "path_spp": 64,
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
        apps_dir = str(self.repo_root / "apps").replace("\\", "\\\\")
        script_path = str(self.repo_root / "apps" / "isaac_capture_current_view_request.py").replace("\\", "\\\\")
        return {
            "daemon_url": self.base_url,
            # --- Blocked mode (new): Isaac Extension / IsaacStateSnapshot ---
            "extension_import_snippet": "\n".join(
                [
                    "import sys",
                    f'sys.path.insert(0, r"{apps_dir}")',
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
            "checklist": [
                "Isaac should add the robomituba <code>apps/</code> directory to sys.path (or PYTHONPATH) before importing extension helpers.",
                "The daemon must be reachable from the Isaac host at the URL shown on this page.",
                "WSL: set LD_LIBRARY_PATH=/usr/lib/wsl/lib before launching the daemon for GPU Mitsuba renders.",
                "Blocked mode (/isaac/render) holds the HTTP connection open until rendering completes — use async submit for longer jobs.",
                "The base scene XML (mitsuba_scene_ref) and explicit shape map (shape_map_ref) must already exist on disk; the daemon patches them at render time, it does not rebuild them from USD.",
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
        if not isinstance(transform, list) or len(transform) != 16:
            return None
        return [float(transform[3]), float(transform[7]), float(transform[11])]

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

    def _ensure_floorplan(self, scene_id: str) -> dict[str, Any]:
        detail = self._scene_detail(scene_id)
        scene_record = detail["scene"]
        latest_capture = detail["latest_capture"]
        if scene_record is None or latest_capture is None:
            return {
                "scene_id": scene_id,
                "artifact_path": None,
                "artifact_href": None,
                "request_camera_count": 0,
                "snapshot_camera_count": 0,
                "snapshot_light_count": 0,
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
            }

        request = self._load_saved_request(latest_capture["job_id"], latest_capture["frame_id"])
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
        render_scene_floorplan(
            scene_path=scene_path,
            output_path=image_path,
            metadata_path=metadata_path,
            request_cameras=request_cameras,
            snapshot_cameras=snapshot_cameras,
            snapshot_lights=snapshot_lights,
            title=f"{scene_id} floorplan",
        )
        image_rel = to_repo_relative_posix(self.repo_root, image_path)
        metadata_rel = to_repo_relative_posix(self.repo_root, metadata_path)
        return {
            "scene_id": scene_id,
            "artifact_path": image_rel,
            "artifact_href": self._artifact_href(image_rel),
            "metadata_path": metadata_rel,
            "metadata_href": self._artifact_href(metadata_rel),
            "request_camera_count": len(request_cameras),
            "snapshot_camera_count": len(snapshot_cameras),
            "snapshot_light_count": len(snapshot_lights),
        }


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
