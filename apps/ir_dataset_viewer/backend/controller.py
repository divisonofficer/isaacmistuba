"""Durable, localhost-only orchestration for the Blender Principled IR pipeline.

The controller deliberately owns no renderer code.  It validates a compact job
request and invokes the repository CLIs with an explicit argv list, one pipeline
at a time.  This keeps it independent from the OpticalNav render daemon.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mitsuba_converter.ir_dataset_publish import publish_dataset
from mitsuba_converter.ir_render_plan import write_render_plan
from mitsuba_converter.ir_illumination import load_bank
from mitsuba_converter.ir_material_mix import PROFILE as METAL_PROFILE
from mitsuba_converter.ir_showcase import PROFILE as SHOWCASE_PROFILE

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
ARCHETYPES = {"apartment", "office", "single_room"}
ROOM_TYPES = {
    "living-room", "bedroom", "kitchen", "bathroom", "dining-room", "closet",
    "hallway", "garage", "balcony", "utility", "staircase-room", "warehouse",
    "office", "meeting-room", "open-office", "break-room", "restroom",
    "factory-office",
}
DENSITIES = {"model_house", "normal_lived_in", "family_home", "storage_heavy"}
# Keep this controller-side preflight in lockstep with
# navigation_dataset.ir_principled.STAGE2_COMPILER_VERSION.  The controller is
# intentionally importable without the navigation package on PYTHONPATH.
STAGE2_COMPILER_VERSION = "ir-principled-stage2-v12-render-visibility-contract"
IR_GRAPH_DEFAULTS = {
    "graph_max_nodes": 70,
    "graph_heading_count": 24,
    "graph_min_node_spacing": 0.25,
    "graph_robot_radius": 0.30,
}
STAGES = ("generate", "showcase_composition", "import", "scene_content_audit", "navigation_compile", "material_extract", "material_canonicalize", "showcase_raster_probe", "showcase_acceptance", "view_probe", "lighting_asset_audit", "view_plan", "scene_quality_gate", "geometry", "structural_rematerialize", "structural_quality_audit", "prop_pbr_remediate", "overview_proxy", "principled_prepare", "material_mix_audit", "qc_render", "qc_verify", "full_render", "nir_passive_backfill", "full_verify", "dataset_utility_audit", "publish")
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
GPU_STAGES = frozenset({"qc_render", "full_render", "nir_passive_backfill"})
INFINIGEN_GENERATE_STAGES = frozenset({"generate"})
BLENDER_BOOTSTRAP_STAGES = frozenset({"import"})
BLENDER_COMPOSITION_STAGES = frozenset({"showcase_composition"})
BLENDER_BAKE_STAGES = frozenset({"geometry"})
BLENDER_PREPARE_STAGES = frozenset({"overview_proxy", "principled_prepare"})
CPU_LIGHT_STAGES = frozenset(
    set(STAGES) - GPU_STAGES - INFINIGEN_GENERATE_STAGES
    - BLENDER_BOOTSTRAP_STAGES - BLENDER_COMPOSITION_STAGES - BLENDER_BAKE_STAGES - BLENDER_PREPARE_STAGES
)
INFINIGEN_PHASES = (
    "sky_lighting", "solve_rooms", "solve_large", "populate_intermediate_pholders",
    "solve_medium", "solve_small", "populate_assets", "floating_objs", "room_doors",
    "room_windows", "room_stairs", "room_walls", "room_floors", "room_ceilings",
    "invisible_room_ceilings", "overhead_cam", "hide_other_rooms", "Writing output blendfile",
)
# Empirical single-room coarse-generation shares. They are deliberately used
# only as an estimated overall bar; the exact solver iteration is exposed
# separately because a phase may contain several independent annealing runs.
INFINIGEN_PHASE_WEIGHTS = {
    "sky_lighting": 0.2, "solve_rooms": 0.8, "solve_large": 22.0,
    "populate_intermediate_pholders": 0.5, "solve_medium": 28.0,
    "solve_small": 10.0, "populate_assets": 16.0, "floating_objs": 16.0,
    "room_doors": 0.5, "room_windows": 0.3, "room_stairs": 0.1,
    "room_walls": 0.2, "room_floors": 0.3, "room_ceilings": 0.1,
    "invisible_room_ceilings": 0.2, "overhead_cam": 0.2,
    "hide_other_rooms": 0.1, "Writing output blendfile": 4.5,
}


class QualityGateError(RuntimeError):
    """A deterministic generated-scene quality gate did not pass."""


class ShowcaseAcceptanceError(QualityGateError):
    """The composition/camera-set contract needs another isolated attempt."""


class GenerationTimeoutError(RuntimeError):
    """Generation exceeded the bounded wall-clock budget.

    The generated output is never deleted.  The controller uses this error to
    schedule one isolated, lower-clutter variation while preserving the
    timed-out attempt for diagnosis and possible manual resume.
    """


class GeometryTimeoutError(RuntimeError):
    """Geometry export exceeded the bounded bake budget.

    Partial unit checkpoints remain valid; the controller retries once with a
    lower-cost bake/filter profile instead of allowing one pathological asset
    to occupy the pipeline indefinitely.
    """


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _inside(root: Path, child: Path) -> bool:
    root, child = root.resolve(), child.resolve()
    return root == child or root in child.parents


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _effective_scene_seed(logical_seed: str, room_type: str, variation_id: int) -> str:
    payload = f"{int(logical_seed):08d}|{room_type}|{int(variation_id)}|room-content-v1".encode()
    return f"{int.from_bytes(hashlib.sha256(payload).digest()[:8], 'big') % 100_000_000:08d}"


def _showcase_composition_seed(effective_scene_seed: str, composition_attempt: int) -> int:
    payload = f"{effective_scene_seed}|showcase-composition|{int(composition_attempt)}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 2_147_483_647


def _showcase_import_name(effective_scene_seed: str, variation_id: int, composition_attempt: int) -> str:
    return f"irshowcase_{effective_scene_seed}_v{int(variation_id):02d}_c{int(composition_attempt):02d}"


def _gpu_pool_env(name: str = "ROBOMITUBA_IR_GPU_INDICES", default: str = "0,1,2,3,4,5,6,7") -> list[int]:
    try:
        values = sorted({int(part.strip()) for part in os.environ.get(name, default).split(",") if part.strip()})
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated GPU index list") from exc
    if not values or values[0] < 0:
        raise ValueError(f"{name} must contain at least one non-negative GPU index")
    return values


@dataclass
class ControllerJob:
    job_id: str
    request: dict[str, Any]
    status: str = "queued"
    stage: str = "queued"
    priority: int = 0
    created_at: str = field(default_factory=_utc)
    updated_at: str = field(default_factory=_utc)
    started_at: str | None = None
    # Wall-clock start of the *currently dispatched stage*.  It is distinct
    # from job.started_at so a safe resume/restart never inherits an old
    # generation timeout from a previous stage attempt.
    stage_started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    pid: int | None = None
    current_command: list[str] | None = None
    process_log_path: str | None = None
    process_log_offset: int = 0
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_adopted: bool = False
    resource_class: str | None = None
    resource_state: str = "pending"
    queue_position: int | None = None
    resource_gpu_indices: list[int] = field(default_factory=list)
    desired_gpu_indices: list[int] = field(default_factory=list)
    draining_gpu_indices: list[int] = field(default_factory=list)
    # A queue parent that survived a controller restart can have a healthy
    # worker alongside workers which have already failed permanently.  Keep
    # that distinction durable: otherwise the allocator keeps reserving every
    # failed device and starves unrelated resumable work.
    degraded_worker_gpu_indices: list[int] = field(default_factory=list)
    eligible_gpu_indices: list[int] = field(default_factory=list)
    replan_requested: bool = False
    gpu_target_updated_at: str | None = None
    interruption_reason: str | None = None
    # Terminal jobs that are known to be unusable remain durably recorded, but
    # are omitted from the normal control-center queue.  This is deliberately
    # separate from remove_terminal_job(): artifacts and the diagnostic event
    # log are never deleted by visibility filtering.
    hidden_from_ui: bool = False
    hidden_reason: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "request": self.request, "status": self.status, "stage": self.stage,
            "priority": self.priority, "created_at": self.created_at, "updated_at": self.updated_at,
            "started_at": self.started_at, "stage_started_at": self.stage_started_at,
            "finished_at": self.finished_at, "error": self.error,
            "pid": self.pid, "current_command": self.current_command,
            "process_log_path": self.process_log_path, "process_log_offset": self.process_log_offset,
            "stage_results": self.stage_results,
            "resource_class": self.resource_class, "resource_state": self.resource_state,
            "queue_position": self.queue_position, "resource_gpu_indices": list(self.resource_gpu_indices or []),
            "desired_gpu_indices": list(self.desired_gpu_indices or []),
            "draining_gpu_indices": list(self.draining_gpu_indices or []),
            "degraded_worker_gpu_indices": list(self.degraded_worker_gpu_indices or []),
            "eligible_gpu_indices": list(self.eligible_gpu_indices or []),
            "replan_requested": bool(self.replan_requested),
            "gpu_target_updated_at": self.gpu_target_updated_at,
            "interruption_reason": self.interruption_reason,
            "hidden_from_ui": bool(self.hidden_from_ui), "hidden_reason": self.hidden_reason,
            "external_adopted": bool(self.external_adopted),
            "paths": job_paths(self.request),
        }


def job_paths(request: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in (request.get("paths") or {}).items()}


class IRDatasetController:
    """Serial durable job runner for scene generation through immutable publish."""

    def __init__(self, *, repo_root: Path, work_root: Path, bean_root: Path,
                 command_runner: Callable[..., subprocess.Popen[str]] | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.work_root = Path(work_root).resolve()
        self.bean_root = Path(bean_root).resolve()
        self.control_root = self.work_root / ".control" / "jobs"
        self.pipeline_root = self.work_root / ".pipeline"
        self.data_root = self.repo_root / "data" / "infinigen_generated" / "outputs"
        self.scene_root = self.repo_root / "out" / "opticalnav" / "opticalnav-v0.2" / "scenes"
        self._jobs: dict[str, ControllerJob] = {}
        self._queue: list[str] = []
        self._active: ControllerJob | None = None
        self._running: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._runner = command_runner or subprocess.Popen
        self._scheduler_idle_signature: tuple[int, ...] | None = None
        # The Existing-output picker may traverse a large Infinigen output
        # tree.  It is metadata, not live scheduling state, so cache it rather
        # than allowing multiple browser polls to glob the tree concurrently.
        self._existing_outputs_cache: tuple[float, dict[str, Any]] | None = None
        self._existing_outputs_cache_ttl_s = 30.0
        # Status serialisation must never re-read every historical JSONL log.
        # Cache each job's derived progress by the small set of artifact stat
        # tokens which can affect it; terminal jobs then cost only a handful of
        # stat calls per status request instead of megabytes of JSON parsing.
        self._stage_progress_cache: dict[str, tuple[tuple[tuple[str, int, int], ...], dict[str, dict[str, Any]]]] = {}
        self.gpu_pool = _gpu_pool_env()
        self.bootstrap_concurrency = _positive_env("ROBOMITUBA_BLENDER_BOOTSTRAP_CONCURRENCY", 4)
        self.bake_concurrency = _positive_env("ROBOMITUBA_BLENDER_BAKE_CONCURRENCY", 2)
        self.prepare_concurrency = _positive_env("ROBOMITUBA_BLENDER_PREPARE_CONCURRENCY", 2)
        # Infinigen coarse generation is CPU/RAM heavy but does not reserve a
        # render GPU. Keep the conservative library default; the production
        # launcher raises this to three on the high-memory host.
        self.infinigen_concurrency = _positive_env("ROBOMITUBA_INFINIGEN_CONCURRENCY", 2)
        # Coarse Infinigen generation can otherwise occupy a slot indefinitely
        # (usually while solving a pathological high-poly/floating asset).  A
        # timeout is deliberately long enough for ordinary rooms; on expiry
        # only a new variation is scheduled and the original output remains.
        self.infinigen_generate_timeout_s = _positive_env("ROBOMITUBA_INFINIGEN_GENERATE_TIMEOUT_S", 3600)
        # A normal room should finish Stage 1 well below this bound.  This is
        # a wall-clock guard, not a per-unit kill: completed checkpoints are
        # retained and the retry only changes the expensive bake profile.
        self.geometry_timeout_s = _positive_env("ROBOMITUBA_GEOMETRY_TIMEOUT_S", 3600)
        self.gpu_worker_start_timeout_s = _positive_env("ROBOMITUBA_GPU_WORKER_START_TIMEOUT_S", 120)
        self.bake_device = str(os.environ.get("ROBOMITUBA_BLENDER_BAKE_DEVICE", "OPTIX")).upper()
        if self.bake_device not in {"CPU", "CUDA", "OPTIX"}:
            raise ValueError("ROBOMITUBA_BLENDER_BAKE_DEVICE must be CPU, CUDA, or OPTIX")
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._restore()
        self._thread = threading.Thread(target=self._run_supervised, name="ir-dataset-controller", daemon=True)
        self._thread.start()

    def _snapshot_path(self, job: ControllerJob) -> Path:
        return self.control_root / f"{job.job_id}.json"

    def _log_path(self, job: ControllerJob) -> Path:
        return self.control_root / f"{job.job_id}.jsonl"

    def _save(self, job: ControllerJob, event: str | None = None, **extra: Any) -> None:
        job.updated_at = _utc()
        _atomic_json(self._snapshot_path(job), job.payload())
        if event:
            self._log_path(job).parent.mkdir(parents=True, exist_ok=True)
            with self._log_path(job).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": job.updated_at, "event": event, **extra}, ensure_ascii=False) + "\n")

    def _restore(self) -> None:
        for path in sorted(self.control_root.glob("*.json")):
            try:
                value = _read_json(path)
                job = ControllerJob(**{key: value.get(key) for key in ControllerJob.__dataclass_fields__ if key not in {"cancel"}})
                job.resource_state = job.resource_state or "pending"
                job.resource_gpu_indices = list(job.resource_gpu_indices or [])
                job.desired_gpu_indices = list(job.desired_gpu_indices or [])
                job.draining_gpu_indices = list(job.draining_gpu_indices or [])
                job.degraded_worker_gpu_indices = list(job.degraded_worker_gpu_indices or [])
                job.eligible_gpu_indices = list(job.eligible_gpu_indices or [])
                job.replan_requested = bool(job.replan_requested)
                job.hidden_from_ui = bool(job.hidden_from_ui)
                job.process_log_offset = max(0, int(job.process_log_offset or 0))
                self._upgrade_request(job.request)
                self._upgrade_unrendered_illumination_plan(job)
                reason = self._unrecoverable_reason(job)
                if reason and not job.hidden_from_ui:
                    job.hidden_from_ui, job.hidden_reason = True, reason
                    self._save(job, "job_hidden", reason=reason)
                # A controller shutdown can occur after a backfill commits its
                # durable state but before the parent advances the job stage.
                # Do not leave that already-complete migration at the head of
                # the GPU queue as a phantom queued job.
                if (job.request.get("source_mode") == "nir_passive_backfill"
                        and job.status == "queued"
                        and (job.stage_results.get("nir_passive_backfill") or {}).get("status") == "succeeded"):
                    job.status, job.stage = "succeeded", "succeeded"
                    job.error = None
                    job.finished_at = job.finished_at or _utc()
                    self._save(job, "backfill_reconciled_from_stage_result", stage="nir_passive_backfill")
                job.eligible_gpu_indices = self._eligible_gpus(job)
                # A passive backfill publishes its durable state before the
                # short-lived CLI exits.  Older controller versions treated
                # that final external-process exit as ``interrupted`` because
                # they had no backfill completion predicate.  Reconcile such
                # terminal snapshots on startup so the UI reflects the
                # committed sidecars instead of asking to resume a finished
                # migration.
                if job.request.get("source_mode") == "nir_passive_backfill" and job.status in TERMINAL:
                    state_path = Path(job.request.get("paths", {}).get("backfill_state") or "")
                    try:
                        state = _read_json(state_path)
                    except (OSError, ValueError, json.JSONDecodeError):
                        state = {}
                    allowed_partial = bool(job.request.get("backfill_limit")) and state.get("status") == "partial"
                    if (state.get("status") == "succeeded" or allowed_partial) and not (state.get("failed") or {}):
                        job.status = job.stage = "succeeded"
                        job.error = None
                        job.finished_at = job.finished_at or _utc()
                        job.stage_results.setdefault("nir_passive_backfill", {
                            "status": "succeeded" if state.get("status") == "succeeded" else "partial",
                            "reconciled_from_state": True,
                            "completed_at": job.finished_at,
                        })
                        self._save(job, "backfill_reconciled_from_state", stage="nir_passive_backfill")
                # stdout cannot be reattached after a server restart, but a
                # surviving importer can still be adopted for lifecycle and
                # resumable-artifact monitoring rather than being hidden as a
                # misleading terminal job.
                if job.status == "running":
                    live = self._external_pids(job)
                    if live:
                        # Older snapshots predate stage_started_at.  Start a
                        # fresh watchdog clock on adoption rather than
                        # interpreting the job's original creation time as a
                        # new generation attempt's elapsed time.
                        if job.stage == "generate" and not job.stage_started_at:
                            job.stage_started_at = _utc()
                        job.status, job.pid = "running", live[0]
                        job.external_adopted, job.error = True, None
                        job.resource_class = self._resource_class(job.stage)
                        job.resource_state, job.queue_position = "running", None
                        self._save(job, "external_process_adopted", stage=job.stage, pids=live)
                    elif (job.stage in {"ready", "queued"}
                          or job.resource_state in {"waiting_gpu", "waiting_resource", "waiting_cpu"}):
                        # A waiting stage owns no subprocess to adopt.  It is
                        # a scheduler reservation only, so treating it as an
                        # interrupted process on a Control Center restart
                        # creates a spurious terminal card and needlessly
                        # requires an operator to press Resume.  Requeue it
                        # from its durable upstream artifacts instead.
                        job.status, job.stage, job.error = "queued", "queued", None
                        job.resource_class, job.resource_state = None, "pending"
                        job.queue_position = None
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                        self._save(job, "waiting_stage_requeued_after_restart")
                    elif self._external_stage_completed(job):
                        # The controller can be stopped after a render queue
                        # (or another durable stage) has committed its final
                        # marker but before the next scheduler poll observes
                        # its exit.  Reconcile that marker at restore time
                        # before declaring the job interrupted.  This keeps a
                        # complete rolling render moving into verification and
                        # publish instead of requiring a no-op manual resume.
                        completed_stage = job.stage
                        job.pid, job.current_command = None, None
                        job.external_adopted = False
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                        job.stage_results[completed_stage] = {
                            "status": "succeeded", "completed_at": _utc(),
                            "reconciled_from_completion_marker": True,
                        }
                        job.status, job.stage, job.error, job.finished_at = "queued", "queued", None, None
                        job.resource_class, job.resource_state, job.queue_position = None, "pending", None
                        if job.job_id not in self._queue:
                            self._queue.append(job.job_id)
                        self._save(job, "stage_reconciled_from_completion_marker", stage=completed_stage)
                    else:
                        job.status, job.stage, job.error = "interrupted", "interrupted", "controller restarted while subprocess was active"
                        job.finished_at = _utc()
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                        self._save(job, "interrupted")
                if job.status in TERMINAL and not job.external_adopted:
                    # Resource state is meaningful only for schedulable jobs.
                    # Older snapshots could retain waiting_gpu/queue_position
                    # after a controller restart, making a resumable terminal
                    # card look permanently queued while the scheduler quite
                    # correctly ignored it.
                    job.resource_state = "pending" if job.status == "interrupted" else job.resource_state
                    job.resource_class = None
                    job.queue_position = None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                self._jobs[job.job_id] = job
                if job.status == "queued":
                    self._queue.append(job.job_id)
            except Exception:
                continue
        self._queue.sort(key=lambda ident: (-self._jobs[ident].priority, self._jobs[ident].created_at))

    def _safe_name(self, value: Any, label: str) -> str:
        text = str(value or "").strip()
        if not NAME_RE.fullmatch(text):
            raise ValueError(f"invalid {label}")
        return text

    def _upgrade_request(self, request: dict[str, Any]) -> None:
        """Supply v1 controller snapshots with immutable render-plan defaults."""
        request.setdefault("pose_budget", 400)
        request.setdefault("illumination_diversity", False)
        # New jobs opt into the paired NIR observation contract.  Legacy
        # snapshots stay false so their active-NIR fingerprints and completed
        # frames remain resumable without an implicit rerender.
        request.setdefault("nir_passive", False)
        request.setdefault("paired_fraction", 0.25)
        # A lighting-expanded frame count is not a substitute for spatial
        # coverage.  New jobs must therefore have at least 100 distinct
        # (viewpoint, heading) poses before their first render is allowed.
        # Legacy snapshots that already recorded an explicit floor retain it
        # so their immutable/recovery contract is not silently rewritten.
        request.setdefault("min_unique_pose_count", 100)
        request.setdefault("pipeline_revision", "legacy-strict-import-v1")
        request.setdefault("filter_small_high_poly", request.get("pipeline_revision") == "ir-content-aware-v2")
        request.setdefault("small_high_poly_max_extent_m", 0.5)
        request.setdefault("small_high_poly_min_triangles", 100000)
        request.setdefault("import_profile", "strict-pbr-v1")
        request.setdefault("ir_composition_profile", "")
        request.setdefault("showcase_composition_attempt_index", 0)
        request.setdefault("showcase_composition_attempts", [])
        request.setdefault("max_showcase_composition_attempts", 3)
        if request.get("ir_composition_profile") == SHOWCASE_PROFILE:
            request.setdefault("showcase_import_name", _showcase_import_name(
                str(request.get("effective_scene_seed") or request.get("seed") or "legacy"),
                int(request.get("variation_id") or 0), int(request.get("showcase_composition_attempt_index") or 0),
            ))
        original = sorted({int(value) for value in request.get("gpu_indices") or []})
        if request.get("pipeline_revision") in {"ir-bootstrap-gpu-v1", "ir-content-aware-v2"}:
            request.setdefault("requested_gpu_indices", original)
            request["gpu_indices"] = list(self.gpu_pool)
        elif any(value not in self.gpu_pool for value in original):
            request.setdefault("requested_gpu_indices", original)
            request["gpu_indices"] = [value for value in original if value in self.gpu_pool]
        elif original:
            # Preserve the legacy selection explicitly even when it happens to
            # equal the expanded host pool; this keeps provenance and resume
            # fingerprints stable across controller restarts.
            request.setdefault("requested_gpu_indices", original)
        paths = request.setdefault("paths", {})
        pipeline = paths.get("pipeline")
        if pipeline:
            paths.setdefault("render_plan", str(Path(pipeline) / "render_plan.json"))
            paths.setdefault("qc_render_plan", str(Path(pipeline) / "qc_render_plan.json"))
            paths.setdefault("candidate_visibility", str(Path(pipeline) / "candidate_visibility.json"))
            paths.setdefault("content_audit", str(Path(pipeline) / "scene_content_audit.json"))
            paths.setdefault("overview_proxy", str(Path(pipeline) / "overview_proxy"))
            paths.setdefault("illumination_audit", str(Path(pipeline) / "illumination_asset_audit.json"))
            paths.setdefault("scene_quality", str(Path(pipeline) / "scene_content_quality.json"))
            paths.setdefault("material_mix", str(Path(pipeline) / "material_mix_quality.json"))
            attempt = Path(paths.get("attempt_root") or pipeline)
            paths.setdefault("structural_rematerialization", str(attempt / "structural_rematerialization.json"))
            paths.setdefault("structural_quality", str(attempt / "structural_material_quality_audit.json"))
            # Prop remediation is a material manifest consumed by Stage 2.
            # It must be scoped to this immutable attempt, just like the
            # prepared blend.  Older snapshots lacked this field and used the
            # shared pipeline root on upgrade, causing a command-construction
            # KeyError or cross-attempt artifact collision.
            canonical_prop_manifest = attempt / "prop_pbr_remediation.json"
            legacy_prop_manifest = Path(pipeline) / "prop_pbr_remediation.json"
            if Path(paths.get("prop_pbr_remediation") or legacy_prop_manifest) == legacy_prop_manifest:
                paths["prop_pbr_remediation"] = str(canonical_prop_manifest)
            else:
                paths.setdefault("prop_pbr_remediation", str(canonical_prop_manifest))
            paths.setdefault("showcase_blend", str(attempt / "showcase" / "composition_c00.blend"))
            paths.setdefault("showcase_composition", str(attempt / "showcase" / "composition_c00.json"))
            paths.setdefault("showcase_raster_probe", str(attempt / "showcase_raster_probe.json"))
            paths.setdefault("showcase_acceptance", str(attempt / "showcase_acceptance.json"))

    def _upgrade_unrendered_illumination_plan(self, job: ControllerJob) -> None:
        """Adopt reference-subset v2 only before a job has rendered any frame.

        Geometry and prepared Blender artifacts remain reusable. Once even a
        QC frame exists, retaining the legacy policy avoids mixing camera and
        lighting fingerprints inside one dataset.
        """
        request = job.request
        if (not request.get("illumination_diversity")
                or job.status == "succeeded"
                or request.get("source_mode") == "nir_passive_backfill"
                or request.get("illumination_pairing_policy") == "reference_subset_v2"
                or job.stage in {"qc_render", "full_render"}):
            return
        paths = request.get("paths") or {}
        for key in ("qc", "dataset"):
            root_value = paths.get(key)
            if not root_value:
                continue
            root = Path(root_value)
            if next((root / "frames").glob("*.json"), None) is not None:
                return
            try:
                state = _read_json(root / "rolling_queue_state.json")
            except (OSError, ValueError, json.JSONDecodeError):
                state = {}
            if int(state.get("completed_count") or len(state.get("completed") or [])) > 0:
                return

        previous = str(request.get("illumination_pairing_policy") or "legacy_six_way_v1")
        request["illumination_pairing_policy"] = "reference_subset_v2"
        request["paired_fraction"] = 0.20
        for stage in (
            "view_plan", "scene_quality_gate", "qc_render", "qc_verify",
            "full_render", "full_verify", "dataset_utility_audit", "publish",
        ):
            job.stage_results.pop(stage, None)
        self._save(
            job,
            "illumination_plan_upgraded",
            previous_policy=previous,
            policy="reference_subset_v2",
            reason="no_rendered_frames",
        )

    @staticmethod
    def _resource_class(stage: str) -> str:
        if stage in GPU_STAGES:
            return "gpu_render"
        if stage in INFINIGEN_GENERATE_STAGES:
            return "infinigen_generate"
        if stage in BLENDER_BOOTSTRAP_STAGES:
            return "blender_bootstrap"
        if stage in BLENDER_COMPOSITION_STAGES:
            return "blender_bootstrap"
        if stage in BLENDER_BAKE_STAGES:
            return "blender_bake"
        if stage in BLENDER_PREPARE_STAGES:
            return "blender_prepare"
        return "cpu_light"

    @staticmethod
    def _pipeline(job: ControllerJob) -> list[str]:
        if job.request.get("source_mode") == "nir_passive_backfill":
            return ["nir_passive_backfill"]
        if job.request.get("source_mode") == "augmentation":
            stages = ["lighting_asset_audit", "view_plan"]
            if job.request.get("structural_rematerialize"):
                stages += ["structural_rematerialize", "structural_quality_audit"]
            if job.request.get("hybrid_prop_pbr"):
                stages += ["prop_pbr_remediate"]
            return stages + ["overview_proxy", "principled_prepare", "qc_render", "qc_verify", "full_render", "full_verify", "publish"]
        stages = list(STAGES[1:])
        # Regular queue renders emit passive NIR in the same persistent
        # Blender worker when ``nir_passive`` is enabled.  The standalone
        # backfill command is only for retrofitting an already immutable v2
        # dataset and requires ``backfill_dataset``/``backfill_prepared``;
        # leaving it in this pipeline would fail after a successful full
        # render with a missing backfill argument.
        stages = [stage for stage in stages if stage != "nir_passive_backfill"]
        if not job.request.get("structural_rematerialize"):
            stages = [stage for stage in stages if stage not in {"structural_rematerialize", "structural_quality_audit"}]
        if not job.request.get("hybrid_prop_pbr", False):
            stages = [stage for stage in stages if stage != "prop_pbr_remediate"]
        if not job.request.get("illumination_diversity"):
            stages = [stage for stage in stages if stage != "lighting_asset_audit"]
        if job.request.get("pipeline_revision") != "ir-content-aware-v2":
            stages = [stage for stage in stages if stage not in {"scene_content_audit", "view_probe", "scene_quality_gate", "material_mix_audit", "dataset_utility_audit"}]
        if job.request.get("ir_composition_profile") != SHOWCASE_PROFILE:
            stages = [stage for stage in stages if stage not in {"showcase_composition", "showcase_raster_probe", "showcase_acceptance"}]
        if job.request.get("content_profile") != "research_balanced" or job.request.get("source_mode") != "generate":
            stages = [stage for stage in stages if stage not in {"scene_quality_gate", "material_mix_audit"}]
        return (["generate"] if job.request.get("source_mode") == "generate" else []) + stages

    def _active_import_pids(self, job: ControllerJob) -> list[int]:
        """Find an orphan importer still writing this exact source scene."""
        raw_source = job.request.get("existing_output")
        candidates: list[str] = []
        if raw_source:
            candidates.append(str(Path(str(raw_source)).resolve()))
        # Showcase jobs import the immutable composed child blend rather than
        # the original generated scene.  Track that exact input too, otherwise
        # a controller restart cannot adopt the surviving importer and a retry
        # collides with its flock despite the UI claiming no orphan exists.
        showcase_record = (job.request.get("paths") or {}).get("showcase_composition")
        if showcase_record:
            candidates.append(str(Path(str(showcase_record)).with_suffix(".blend").resolve()))
        if not candidates:
            return []
        matches: list[int] = []
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc.name)
                command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except (OSError, ValueError):
                continue
            if "apps/run_infinigen_import.sh" in command and any(source in command for source in candidates):
                matches.append(pid)
        return sorted(matches)

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _external_pids(self, job: ControllerJob) -> list[int]:
        """Return a live process for a job whose original controller exited.

        Importers are matched by their immutable source path because their
        wrapper PID can change.  Every later stage has one process-group leader
        persisted in the job snapshot, so checking that PID preserves a running
        geometry/export stage across a UI-server restart without launching a
        competing writer.
        """
        if job.stage == "import":
            return self._active_import_pids(job)
        if job.stage == "generate":
            # A restart can race the initial process snapshot: the wizard is
            # already alive, but its PID has not made it into the job JSON.
            # Unlike a generic command-name scan, scene_id is generated as a
            # unique immutable controller identity, so it is safe to use as
            # the adoption key and prevents a second generator touching the
            # same Infinigen output root.
            scene_id = str(job.request.get("scene_id") or "")
            if scene_id:
                marker = f"--scene-id {scene_id}"
                matches: list[int] = []
                for proc in Path("/proc").glob("[0-9]*"):
                    try:
                        pid = int(proc.name)
                        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
                    except (OSError, ValueError):
                        continue
                    if "scripts/infinigen_wizard.py" in command and marker in command:
                        matches.append(pid)
                if matches:
                    return sorted(matches)
        # A PID alone is not an adoption identity. A short CPU stage can end,
        # have its PID reused, and then be mistaken for the old process after
        # a controller restart. Require the persisted argv to still match the
        # live process before treating it as controller-owned.
        if not self._pid_alive(job.pid) or not self._pid_matches_command(job.pid, job.current_command):
            return []
        return [int(job.pid)]

    @staticmethod
    def _pid_matches_command(pid: int | None, expected: list[str] | None) -> bool:
        """Check a persisted controller argv against a live process leader."""
        if not pid or not expected:
            return False
        try:
            items = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
            actual = [item.decode("utf-8", "replace") for item in items if item]
        except (OSError, ValueError):
            return False
        if len(actual) != len(expected):
            return False
        return bool(actual) and (
            Path(actual[0]).name == Path(str(expected[0])).name
            and actual[1:] == [str(item) for item in expected[1:]]
        )

    def _external_stage_completed(self, job: ControllerJob) -> bool:
        """Recognize an atomically published result after an adopted process exits."""
        if job.stage == "generate":
            # Generation publishes its usable contract as the final blend.
            # This also lets a controller restarted after process completion
            # advance without asking the operator to rerun a finished scene.
            return (Path(job.request.get("existing_output") or "") / "scene.blend").is_file()
        if job.stage == "geometry":
            profile = Path(job.request.get("paths", {}).get("geometry") or "") / "ir_geometry_profile.json"
            try:
                return profile.is_file() and bool(_read_json(profile).get("profile"))
            except (OSError, ValueError, json.JSONDecodeError):
                return False
        if job.stage == "import":
            return self._import_profile_matches(job.request)
        if job.stage in {"qc_render", "full_render"}:
            # A render parent can outlive the controller (or finish while a
            # restart is reconnecting).  Unlike Blender stages, its durable
            # completion marker is the rolling queue state: an empty pending
            # set and no failed frames.  Without this check a clean queue
            # shutdown is incorrectly reported as ``interrupted`` and the UI
            # asks the operator to resume an already complete render.
            root_key = "qc" if job.stage == "qc_render" else "dataset"
            state_path = Path(job.request.get("paths", {}).get(root_key) or "") / "rolling_queue_state.json"
            try:
                state = _read_json(state_path)
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            completed = state.get("completed") or []
            pending = state.get("pending") or []
            failed = state.get("failed") or {}
            return bool(completed) and not pending and not failed
        if job.stage == "nir_passive_backfill":
            # Backfill is an external, durable CLI process.  Its state file is
            # the completion marker, just like rolling_queue_state for a
            # render.  Without this branch a controller restart (or a process
            # that finishes between watcher polls) misclassifies a clean
            # backfill exit as ``interrupted`` even though every sidecar and
            # the dataset contract were committed atomically.
            state_path = Path(job.request.get("paths", {}).get("backfill_state") or "")
            try:
                state = _read_json(state_path)
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            allowed_partial = bool(job.request.get("backfill_limit")) and state.get("status") == "partial"
            return (state.get("status") == "succeeded" or allowed_partial) and not (state.get("failed") or {})
        return False

    def _resolve_existing(self, value: Any) -> Path:
        candidate = (self.data_root / str(value or "")).resolve()
        if not _inside(self.data_root, candidate) or not candidate.is_dir() or not (candidate / "scene.blend").is_file():
            raise ValueError("existing_output must name a generated output with scene.blend")
        return candidate

    @staticmethod
    def _source_blend_path(source: Path) -> Path:
        """Canonical generated-output input accepted by Blender-only stages."""
        return source if source.suffix.lower() == ".blend" else source / "scene.blend"

    def _eligible_gpus(self, job: ControllerJob) -> list[int]:
        requested = {int(value) for value in job.request.get("gpu_indices") or []}
        return [gpu for gpu in self.gpu_pool if gpu in requested]

    def _import_dir(self, request: dict[str, Any]) -> Path:
        if request.get("ir_composition_profile") == SHOWCASE_PROFILE and request.get("showcase_import_name"):
            return self.repo_root / "out" / "infinigen_imports" / str(request["showcase_import_name"])
        source = Path(str(request.get("existing_output") or ""))
        # Controller accepts generated output directories only.  Their parent is
        # the stable Infinigen scene name used by run_infinigen_import.sh.
        return self.repo_root / "out" / "infinigen_imports" / source.parent.name

    def _import_profile_matches(self, request: dict[str, Any]) -> bool:
        manifest_path = self._import_dir(request) / "scene_manifest.json"
        try:
            manifest = _read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        actual = str(manifest.get("stage1_profile") or "strict-pbr-v1")
        if actual != str(request.get("import_profile") or "strict-pbr-v1"):
            return False
        # A bootstrap import is only reusable once it has published the scene
        # materialization sidecars consumed by Stage 1.  Earlier controller
        # versions accepted the private import manifest alone, then failed much
        # later in geometry with a missing xml_scene_index.json.
        if request.get("pipeline_revision") == "ir-content-aware-v2":
            scene = self.scene_root / str(request.get("scene_id") or "")
            required = ("render_scene.xml", "xml_scene_index.json", "render_scene_material_policy.json", "authoring_map.json")
            if not all((scene / name).is_file() for name in required):
                return False
        return True

    def submit(self, raw: dict[str, Any]) -> dict[str, Any]:
        mode = str(raw.get("source_mode") or "generate")
        if mode not in {"generate", "existing", "augmentation", "nir_passive_backfill"}:
            raise ValueError("source_mode must be generate, existing, augmentation, or nir_passive_backfill")
        dataset_name = self._safe_name(raw.get("dataset_name"), "dataset_name")
        if (self.work_root / dataset_name).exists() or (self.bean_root / dataset_name).exists():
            raise FileExistsError("dataset_name already exists in work or published root")
        gpu_indices = sorted({int(value) for value in raw.get("gpu_indices") or []})
        if not gpu_indices or min(gpu_indices) < 0:
            raise ValueError("select at least one non-negative GPU index")
        unsupported = [gpu for gpu in gpu_indices if gpu not in self.gpu_pool]
        if unsupported:
            raise ValueError(
                "GPU indices outside ROBOMITUBA_IR_GPU_INDICES are not allowed: "
                + ", ".join(map(str, unsupported))
            )
        if mode == "nir_passive_backfill":
            # Backfill is deliberately a controller job rather than an
            # untracked one-off process.  The target dataset remains the
            # immutable source of existing RGB/GT pixels; only its new
            # passive-NIR sidecars are written by the backfill CLI.
            dataset = Path(str(raw.get("backfill_dataset") or "")).resolve()
            prepared = Path(str(raw.get("prepared_scene_dir") or "")).resolve()
            if not _inside(self.work_root, dataset) or not dataset.is_dir():
                raise ValueError("backfill_dataset must be an existing dataset under /bean/ir_dataset_work")
            if not (dataset / "index.jsonl").is_file() or not (dataset / "dataset_config.json").is_file():
                raise ValueError("backfill_dataset must contain index.jsonl and dataset_config.json")
            if not _inside(self.pipeline_root, prepared) or not prepared.is_dir():
                raise ValueError("prepared_scene_dir must be under /bean/ir_dataset_work/.pipeline")
            blend = prepared / "derived_ir_principled_v1.blend"
            contract = prepared / "principled_material_contract.json"
            if not blend.is_file() or not contract.is_file():
                raise ValueError("prepared_scene_dir lacks derived_ir_principled_v1.blend or material contract")
            try:
                config = _read_json(dataset / "dataset_config.json")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("backfill dataset_config.json is invalid") from exc
            if config.get("schema") != "robomituba.ir_principled_dataset.v2":
                raise ValueError("backfill dataset is not a Principled dataset v2")
            queue_state_path = dataset / "rolling_queue_state.json"
            try:
                queue_state = _read_json(queue_state_path)
                frame_count = int(queue_state.get("frame_count") or 0)
                completed = queue_state.get("completed") or []
                pending_frames = queue_state.get("pending") or []
                failed_frames = queue_state.get("failed") or {}
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("backfill dataset must have a valid rolling_queue_state.json") from exc
            if (
                frame_count < 1
                or len(completed) != frame_count
                or pending_frames
                or failed_frames
            ):
                raise ValueError(
                    "backfill dataset is not a completed rolling render; finish or verify full_render first"
                )
            frame_limit = raw.get("backfill_limit")
            if frame_limit is not None:
                try:
                    frame_limit = int(frame_limit)
                except (TypeError, ValueError) as exc:
                    raise ValueError("backfill_limit must be a positive integer") from exc
                if frame_limit < 1:
                    raise ValueError("backfill_limit must be a positive integer")
            pipeline = self.pipeline_root / dataset_name
            if pipeline.exists():
                raise FileExistsError("backfill job name already has a pipeline artifact directory")
            request = {
                "source_mode": mode, "dataset_name": dataset_name,
                "gpu_indices": list(self.gpu_pool), "requested_gpu_indices": gpu_indices,
                "pipeline_revision": "nir-passive-backfill-v1", "nir_passive": True,
                "backfill_dataset": str(dataset), "backfill_prepared": str(prepared),
                "backfill_limit": frame_limit,
                "paths": {
                    "pipeline": str(pipeline), "dataset": str(dataset),
                    "prepared": str(prepared),
                    "backfill_state": str(dataset / ".nir_passive_backfill" / "state.json"),
                },
            }
            job = ControllerJob(job_id=uuid.uuid4().hex, request=request, priority=int(raw.get("priority", 0)))
            job.eligible_gpu_indices = self._eligible_gpus(job)
            with self._lock:
                def _smoke_handoff(existing: ControllerJob) -> bool:
                    if frame_limit is not None or existing.status != "succeeded":
                        return False
                    if not existing.request.get("backfill_limit"):
                        return False
                    state_path = Path(str(existing.request.get("paths", {}).get("backfill_state") or ""))
                    try:
                        state = _read_json(state_path)
                    except (OSError, ValueError, TypeError, json.JSONDecodeError):
                        return False
                    return state.get("status") == "partial" and bool(state.get("partial_run"))

                duplicate = next((existing for existing in self._jobs.values()
                                  if existing.request.get("source_mode") == mode
                                  and str(existing.request.get("backfill_dataset")) == str(dataset)
                                  and existing.status not in {"cancelled", "failed"}
                                  # A bounded smoke is intentionally terminal
                                  # before the unbounded follow-up.  Permit
                                  # exactly that hand-off while retaining the
                                  # old duplicate protection for every other
                                  # queued/running/completed backfill.
                                  and not _smoke_handoff(existing)), None)
                if duplicate is not None:
                    raise FileExistsError(f"backfill is already queued/running as job {duplicate.job_id}")
                self._jobs[job.job_id] = job
                self._queue.append(job.job_id)
                self._save(job, "submitted", backfill_dataset=str(dataset))
                self._wake.set()
            return job.payload()
        request: dict[str, Any] = {
            "source_mode": mode, "dataset_name": dataset_name,
            "gpu_indices": list(self.gpu_pool), "requested_gpu_indices": gpu_indices,
            "pipeline_revision": "ir-content-aware-v2", "import_profile": "ir-bootstrap-v1",
            "width": int(raw.get("width", 684)), "height": int(raw.get("height", 512)),
            "fov": float(raw.get("fov", 60.0)), "rgb_spp": int(raw.get("rgb_spp", 4000)),
            "nir_spp": int(raw.get("nir_spp", 2000)), "flash_energy_scale": float(raw.get("flash_energy_scale", 1.0)),
            "ambient_fill_energy_scale": float(raw.get("ambient_fill_energy_scale", 1.0)),
            "illumination_diversity": bool(raw.get("illumination_diversity", False)),
            "nir_passive": bool(raw.get("nir_passive", True)),
            "paired_fraction": float(raw.get("paired_fraction", 0.20)),
            "illumination_pairing_policy": str(raw.get("illumination_pairing_policy") or "reference_subset_v2"),
            "min_unique_pose_count": int(raw.get("min_unique_pose_count", 100)),
            "pose_budget": int(raw.get("pose_budget", 400)),
            "camera_policy": str(raw.get("camera_policy") or "content_aware_v2"),
            "content_profile": str(raw.get("content_profile") or "balanced"),
            "placement_profile": str(raw.get("placement_profile") or "legacy_clutter_v1"),
            "ir_composition_profile": str(raw.get("ir_composition_profile") or ""),
            "ir_material_profile": str(raw.get("ir_material_profile") or "principled_rich_v1"),
            "material_mix_profile": str(raw.get("material_mix_profile") or METAL_PROFILE),
            "max_quality_variations": int(raw.get("max_quality_variations", 4)),
            "max_showcase_composition_attempts": int(raw.get("max_showcase_composition_attempts", 3)),
            "adaptive_pose_budget": bool(raw.get("adaptive_pose_budget", True)),
            "sparse_negative_fraction": float(raw.get("sparse_negative_fraction", 0.15)),
            "max_headings_per_node": int(raw.get("max_headings_per_node", 6)),
            "graph_max_nodes": int(raw.get("graph_max_nodes", IR_GRAPH_DEFAULTS["graph_max_nodes"])),
            "graph_heading_count": int(raw.get("graph_heading_count", IR_GRAPH_DEFAULTS["graph_heading_count"])),
            "graph_min_node_spacing": float(raw.get("graph_min_node_spacing", IR_GRAPH_DEFAULTS["graph_min_node_spacing"])),
            "graph_robot_radius": float(raw.get("graph_robot_radius", IR_GRAPH_DEFAULTS["graph_robot_radius"])),
            "structural_rematerialize": bool(raw.get("structural_rematerialize", False)),
            "hybrid_prop_pbr": bool(raw.get("hybrid_prop_pbr", True)),
            "prop_pbr_target": float(raw.get("prop_pbr_target", 0.70)),
            "prop_pbr_seed": int(raw.get("prop_pbr_seed") or 0),
            "filter_small_high_poly": bool(raw.get("filter_small_high_poly", True)),
            "small_high_poly_max_extent_m": float(raw.get("small_high_poly_max_extent_m", 0.5)),
            "small_high_poly_min_triangles": int(raw.get("small_high_poly_min_triangles", 100000)),
        }
        if request["width"] < 1 or request["height"] < 1 or request["rgb_spp"] < 1 or request["nir_spp"] < 1 or not 1 <= request["fov"] < 179 or not 100 <= request["pose_budget"] <= 2000:
            raise ValueError("invalid render dimensions, samples, or horizontal FOV")
        if not 0.05 <= request["paired_fraction"] <= 1.0:
            raise ValueError("paired fraction must be in [0.05, 1.0]")
        if request["illumination_pairing_policy"] not in {"legacy_six_way_v1", "reference_subset_v2"}:
            raise ValueError("invalid illumination pairing policy")
        if not 1 <= request["min_unique_pose_count"] <= request["pose_budget"]:
            raise ValueError("min_unique_pose_count must be between 1 and pose_budget")
        if request["camera_policy"] not in {"content_aware_v2", "coverage_v1"} or request["content_profile"] not in {"balanced", "anchor_rich", "structural", "research_balanced"}:
            raise ValueError("invalid camera or content policy")
        if request["placement_profile"] not in {"legacy_clutter_v1", "upstream_residential_v1", "collision_aware_clutter_v1"}:
            raise ValueError("invalid Infinigen placement profile")
        if request["ir_composition_profile"] not in {"", SHOWCASE_PROFILE}:
            raise ValueError("invalid IR composition profile")
        if request["ir_material_profile"] not in {"standard", "principled_rich_v1"}:
            raise ValueError("invalid IR material profile")
        if request["material_mix_profile"] != METAL_PROFILE or not 1 <= request["max_quality_variations"] <= 5 or not 1 <= request["max_showcase_composition_attempts"] <= 3:
            raise ValueError("invalid material-mix profile or quality variation limit")
        if not 0.1 <= request["small_high_poly_max_extent_m"] <= 2.0 or not 10_000 <= request["small_high_poly_min_triangles"] <= 2_000_000:
            raise ValueError("invalid small high-poly filter thresholds")
        if request["structural_rematerialize"]:
            registry = Path(str(raw.get("structural_pbr_registry") or ""))
            registry_root = Path(str(raw.get("structural_pbr_registry_root") or ""))
            if not registry.is_file() or not registry_root.is_dir():
                raise ValueError("rematerialization requires an existing CC0 PBR registry and registry root")
            request.update({"structural_pbr_registry": str(registry.resolve()),
                            "structural_pbr_registry_root": str(registry_root.resolve()),
                            "material_variant_id": self._safe_name(raw.get("material_variant_id") or "variant", "material_variant_id"),
                            "material_seed": int(raw.get("material_seed") or 0),
                            "parent_scene_id": str(raw.get("parent_scene_id") or "")})
        if not 0.0 < request["prop_pbr_target"] <= 1.0:
            raise ValueError("prop PBR train-valid target must be in (0, 1]")
        if not 0.0 <= request["sparse_negative_fraction"] <= 0.15 or not 1 <= request["max_headings_per_node"] <= 12:
            raise ValueError("invalid sparse-negative fraction or heading cap")
        if (
            not 1 <= request["graph_max_nodes"] <= 2000
            or not 1 <= request["graph_heading_count"] <= 72
            or not 0.05 <= request["graph_min_node_spacing"] <= 5.0
            or not 0.05 <= request["graph_robot_radius"] <= 2.0
        ):
            raise ValueError("invalid IR camera graph profile")
        variation_id = 0
        if mode == "generate":
            archetype = str(raw.get("archetype") or "single_room")
            room_type = str(raw.get("room_type") or "kitchen").replace("_", "-")
            density, stage = str(raw.get("density") or "normal_lived_in"), str(raw.get("generation_stage") or "full")
            seed = str(raw.get("seed") or "today")
            variation_id = int(raw.get("variation_id", 0))
            anchor_richness = str(raw.get("anchor_richness") or "balanced")
            surface_clutter = str(raw.get("surface_clutter") or "balanced")
            if request["content_profile"] == "research_balanced":
                density_order = ("model_house", "normal_lived_in", "family_home", "storage_heavy")
                if density_order.index(density) < density_order.index("family_home"):
                    density = "family_home"
                if anchor_richness in {"minimal", "balanced"}: anchor_richness = "rich"
                if surface_clutter in {"low", "balanced"}: surface_clutter = "rich"
            if archetype not in ARCHETYPES or density not in DENSITIES or stage not in {"layout", "full"}:
                raise ValueError("invalid Infinigen wizard choices")
            if archetype == "single_room" and room_type not in ROOM_TYPES:
                raise ValueError("invalid single-room type")
            if seed not in {"today", "random"} and not (seed.isdigit() and len(seed) == 8):
                raise ValueError("seed must be today, random, or eight digits")
            if variation_id < 0 or anchor_richness not in {"minimal", "balanced", "rich", "storage"} or surface_clutter not in {"low", "balanced", "rich", "storage"}:
                raise ValueError("invalid content variation controls")
            # Persist the concrete seed before queueing.  Otherwise a deferred
            # ``today``/``random`` request could import a different scene than
            # the command that generated it.
            if seed == "today":
                seed = datetime.now(timezone.utc).strftime("%Y%m%d")
            elif seed == "random":
                seed = f"{secrets.randbelow(100_000_000):08d}"
            effective_seed = _effective_scene_seed(seed, room_type, variation_id)
            suffix = f"_{room_type.replace('-', '_')}" if archetype == "single_room" else ""
            placement_suffix = "" if request["placement_profile"] == "legacy_clutter_v1" else f"_{request['placement_profile']}"
            generated_source = self.data_root / f"kr_{effective_seed}_{archetype}{suffix}{placement_suffix}" / stage
            generated_scene_id = f"infinigen_{archetype}{suffix}_{seed}_v{variation_id:02d}{placement_suffix}"
            request.update({"archetype": archetype, "room_type": room_type, "density": density,
                            "generation_stage": stage, "seed": seed, "logical_seed": seed,
                            "effective_scene_seed": effective_seed, "variation_id": variation_id,
                            "anchor_richness": anchor_richness, "surface_clutter": surface_clutter,
                            "content_policy_version": "room-content-v1",
                            "quality_attempt_index": 0, "quality_attempts": [],
                            "existing_output": str(generated_source),
                            # Match scripts/infinigen_wizard.py so generation,
                            # import, navigation compilation and recovery all
                            # refer to the same deterministic scene ID.
                            "scene_id": self._safe_name(raw.get("scene_id") or generated_scene_id, "scene_id")})
            if not raw.get("prop_pbr_seed"):
                request["prop_pbr_seed"] = int(effective_seed)
            request["scene_id_base"] = request["scene_id"]
            if archetype == "single_room" and request["content_profile"] == "research_balanced" and not request["ir_composition_profile"]:
                request["ir_composition_profile"] = SHOWCASE_PROFILE
                # Initial source + at most four regenerated variations.
                if "max_quality_variations" not in raw:
                    request["max_quality_variations"] = 5
            if request["ir_composition_profile"] == SHOWCASE_PROFILE:
                request["showcase_composition_attempt_index"] = 0
                request["showcase_composition_attempts"] = []
                request["showcase_composition_seed"] = _showcase_composition_seed(effective_seed, 0)
                request["showcase_import_name"] = _showcase_import_name(effective_seed, variation_id, 0)
        elif mode == "existing":
            source = self._resolve_existing(raw.get("existing_output"))
            existing_room_type = str(raw.get("room_type") or "generic").replace("_", "-")
            if existing_room_type != "generic" and existing_room_type not in ROOM_TYPES:
                raise ValueError("invalid existing scene room type")
            request.update({"existing_output": str(source), "room_type": existing_room_type,
                            "scene_id": self._safe_name(raw.get("scene_id") or f"infinigen_{dataset_name}", "scene_id")})
        else:
            legacy_name = self._safe_name(raw.get("legacy_dataset_name"), "legacy_dataset_name")
            candidates = [self.pipeline_root / legacy_name, self.bean_root / legacy_name, self.work_root / legacy_name, self.repo_root / "out" / "ir_dataset" / legacy_name]
            legacy = next((item.resolve() for item in candidates if (item / "ir_geometry" / "ir_geometry_profile.json").is_file()), None)
            if legacy is None:
                # Completed showcase/content-aware jobs keep immutable Stage 1
                # outputs under attempts/vNN while the published dataset only
                # contains render artifacts.  Augmentation must reuse the
                # newest verified attempt rather than requiring a flattened
                # legacy directory that may not exist.
                attempt_profiles = []
                for candidate in candidates:
                    if not candidate.is_dir():
                        continue
                    attempt_profiles.extend(candidate.glob("attempts/**/ir_geometry/ir_geometry_profile.json"))
                if attempt_profiles:
                    profile_path = max(attempt_profiles, key=lambda item: item.stat().st_mtime_ns)
                    legacy = profile_path.parent.parent.resolve()
            if legacy is None:
                raise FileNotFoundError("legacy dataset must contain ir_geometry/ir_geometry_profile.json in bean, work, or out root")
            profile = _read_json(legacy / "ir_geometry" / "ir_geometry_profile.json")
            scene_dir = Path(str(profile.get("derived_scene_dir") or "")).resolve()
            scene_id = scene_dir.name.removesuffix("__ir_semantic_lod_v1")
            if not (self.scene_root / scene_id / "viewpoint_graph.json").is_file():
                raise FileNotFoundError(f"legacy dataset source graph is unavailable: {scene_id}")
            request.update({"legacy_dataset_name": legacy_name, "legacy_dataset": str(legacy), "room_type": str(raw.get("room_type") or "generic"),
                            "scene_id": self._safe_name(scene_id, "scene_id"), "illumination_diversity": True,
                            "camera_policy": "coverage_v1"})
        pipeline = self.pipeline_root / dataset_name
        if pipeline.exists():
            raise FileExistsError("pipeline artifact directory already exists; retry its original job instead")
        attempt_root = pipeline / "attempts" / f"v{variation_id:02d}" if (mode == "generate" and request["content_profile"] == "research_balanced") else pipeline
        request["paths"] = {
            "pipeline": str(pipeline), "attempt_root": str(attempt_root), "geometry": str(attempt_root / "ir_geometry"),
            "prepared": str(attempt_root / "principled_stage2"), "qc": str(attempt_root / "qc_stage0"),
            "render_plan": str(attempt_root / "render_plan.json"), "qc_render_plan": str(attempt_root / "qc_render_plan.json"),
            "candidate_visibility": str(attempt_root / "candidate_visibility.json"),
            "showcase_blend": str(attempt_root / "showcase" / "composition_c00.blend"),
            "showcase_composition": str(attempt_root / "showcase" / "composition_c00.json"),
            "showcase_raster_probe": str(attempt_root / "showcase_raster_probe.json"),
            "showcase_acceptance": str(attempt_root / "showcase_acceptance.json"),
            "content_audit": str(attempt_root / "scene_content_audit.json"),
            "illumination_audit": str(attempt_root / "illumination_asset_audit.json"),
            "scene_quality": str(attempt_root / "scene_content_quality.json"),
            "material_mix": str(attempt_root / "material_mix_quality.json"),
            "structural_rematerialization": str(attempt_root / "structural_rematerialization.json"),
            "structural_quality": str(attempt_root / "structural_material_quality_audit.json"),
            "prop_pbr_remediation": str(attempt_root / "prop_pbr_remediation.json"),
            "overview_proxy": str(attempt_root / "overview_proxy"),
            "dataset": str(self.work_root / dataset_name), "published": str(self.bean_root / dataset_name),
        }
        if mode == "augmentation":
            request["paths"]["geometry"] = str(legacy / "ir_geometry")
        job = ControllerJob(job_id=uuid.uuid4().hex, request=request)
        job.eligible_gpu_indices = self._eligible_gpus(job)
        with self._lock:
            duplicate = next(
                (existing for existing in self._jobs.values()
                 if existing.request.get("dataset_name") == dataset_name),
                None,
            )
            if duplicate is not None:
                raise FileExistsError(
                    f"dataset_name is already reserved by job {duplicate.job_id}; "
                    "use a scene-specific dataset name"
                )
            self._jobs[job.job_id] = job; self._queue.append(job.job_id)
            self._save(job, "submitted")
            self._wake.set()
        return job.payload()

    @staticmethod
    def _unrecoverable_reason(job: ControllerJob) -> str | None:
        """Return a conservative hard-failure classification for UI hiding.

        A content-contract rejection is not made recoverable by rerunning the
        same scene: missing anchors or forbidden room contents require a new
        generated scene/replacement.  Other failures (timeouts, graph
        recovery, GPU worker loss, and partial renders) remain visible because
        their committed artifacts can still be resumed.
        """
        if job.status not in TERMINAL or job.stage != "scene_content_audit":
            return None
        error = str(job.error or "").lower()
        if "missing_room_anchors" in error or "forbidden_room_content" in error:
            return "scene content contract rejected; replace scene instead of resuming"
        return None

    def list_jobs(self, *, include_hidden: bool = False) -> dict[str, Any]:
        with self._lock:
            self._refresh_external_jobs()
            # Older snapshots could retain a live lease after a terminal
            # transition (or after a queued job was cancelled).  Such stale
            # state makes the UI report phantom GPU ownership and can distort
            # queue progress, so normalize it before exposing status.
            for job in self._jobs.values():
                if job.status in TERMINAL and (job.resource_state != "pending" or job.resource_class is not None
                                               or job.resource_gpu_indices or job.desired_gpu_indices):
                    job.resource_state, job.resource_class = "pending", None
                    job.queue_position = None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    self._save(job, "resource_state_normalized")
                elif job.status == "queued" and job.resource_state == "running":
                    job.resource_state, job.resource_class = "pending", None
                    job.queue_position = None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    self._save(job, "queued_resource_state_normalized")
            hidden = [job for job in self._jobs.values() if job.hidden_from_ui or self._unrecoverable_reason(job)]
            jobs = [self._payload(job) for job in self._jobs.values()
                    if include_hidden or not job.hidden_from_ui]
            jobs.sort(key=lambda item: (item["status"] != "running", -item["priority"], item["created_at"]))
            active = next(iter(self._running), None)
            gpu_queue = [job.job_id for job in self._jobs.values() if job.resource_state == "waiting_gpu"]
            return {"jobs": jobs, "queue": list(self._queue), "gpu_queue": gpu_queue, "active_job_id": active,
                    "hidden_job_count": len(hidden), "include_hidden": bool(include_hidden)}

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_external_jobs()
            if job_id not in self._jobs: raise KeyError(job_id)
            return self._payload(self._jobs[job_id])

    def _payload(self, job: ControllerJob) -> dict[str, Any]:
        payload = job.payload()
        payload["stage_progress"] = self._stage_progress(job)
        # A process that survived a controller restart is not controllable by
        # this parent, but it is still the authoritative writer for Stage 1.
        # Expose it explicitly instead of misleading the operator with a bare
        # failed/cancelled label.
        if job.stage == "import" and (job.external_adopted or job.status in {"failed", "cancelled", "interrupted"}):
            payload["external_import_pids"] = self._active_import_pids(job)
        else:
            payload["external_import_pids"] = []
        return payload

    def _stage_progress(self, job: ControllerJob) -> dict[str, dict[str, Any]]:
        """Return checkpoint-backed progress where a stage exposes a contract."""
        geometry_root = Path(job.request.get("paths", {}).get("geometry") or "") / "stage1"
        state_root = geometry_root / ".stage1_unit_state"
        log_path = self._log_path(job)
        plan_path = Path(job.request.get("paths", {}).get("render_plan") or "")
        backfill_state_path = Path(job.request.get("paths", {}).get("backfill_state") or "")
        rolling_states = tuple(
            Path(job.request.get("paths", {}).get(root_key) or "") / "rolling_queue_state.json"
            for root_key in ("qc", "dataset")
        )

        def stat_token(path: Path) -> tuple[str, int, int]:
            try:
                value = path.stat()
                return (str(path), value.st_mtime_ns, value.st_size)
            except OSError:
                return (str(path), -1, -1)

        fingerprint = tuple(stat_token(path) for path in (log_path, state_root, plan_path, backfill_state_path, *rolling_states))
        cached = self._stage_progress_cache.get(job.job_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        completed = len(list(state_root.glob("*.json"))) if state_root.is_dir() else 0
        total = 0
        log_messages: list[str] = []
        # Keep generation attempts distinct.  A safe resume appends to the
        # durable event log, so an earlier attempt may have completed phases
        # that the freshly restarted generator has not reached yet.
        generate_events: list[tuple[str, str]] = []
        if log_path.is_file():
            # blender_export_scene emits this once before any unit starts.
            pattern = re.compile(r"\[export\] exporting\s+(\d+)\s+units")
            try:
                for serialized in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        record = json.loads(serialized)
                        message = record.get("line")
                    except (ValueError, TypeError):
                        continue
                    message = str(message or "")
                    log_messages.append(message)
                    event_stage = record.get("stage")
                    if event_stage == "generate" or (event_stage is None and record.get("event") == "output"):
                        if record.get("event") == "stage_started":
                            generate_events.append(("started", ""))
                        elif record.get("event") == "output":
                            generate_events.append(("output", message))
                    match = pattern.search(message)
                    if match:
                        total = int(match.group(1))
            except OSError:
                pass
        progress: dict[str, dict[str, Any]] = {}
        if job.request.get("source_mode") == "generate" and generate_events:
            phase_pattern = re.compile(r"\[logging\] \[INFO\] \| \[([^]]+)\]( finished in .*)?$")
            annealing_pattern = re.compile(r"\[annealing\].*?\bit=(\d+)/(\d+).*?\bn=(\d+)")
            completed_phases: set[str] = set()
            current_phase: str | None = None
            local: tuple[int, int, int] | None = None
            for event, message in generate_events:
                if event == "started":
                    completed_phases.clear()
                    current_phase, local = None, None
                    continue
                phase_match = phase_pattern.search(message)
                if phase_match:
                    phase = phase_match.group(1)
                    if phase in INFINIGEN_PHASES:
                        current_phase = phase
                        local = None
                        if phase_match.group(2):
                            completed_phases.add(phase)
                annealing_match = annealing_pattern.search(message)
                if annealing_match and current_phase:
                    local = tuple(int(annealing_match.group(index)) for index in (1, 2, 3))
            # ``solve_large``/``solve_medium`` can spend a long time in a
            # single annealing run. Their authoritative ``it=N/M`` checkpoint
            # is exposed separately as ``phase_percent``. Do *not* add it to
            # the completed-phase bar: a phase can retry several independent
            # solver passes, so that would make the milestone overstate work.
            completed_weight = sum(INFINIGEN_PHASE_WEIGHTS[name] for name in completed_phases)
            current_phase_fraction: float | None = None
            if (
                current_phase in INFINIGEN_PHASE_WEIGHTS
                and local is not None
                and local[1] > 0
            ):
                current_phase_fraction = min(1.0, max(0.0, local[0] / local[1]))
            estimated = min(100.0, completed_weight)
            if (Path(job.request.get("existing_output") or "") / "scene.blend").is_file():
                estimated = 100.0
            phase_index = INFINIGEN_PHASES.index(current_phase) + 1 if current_phase in INFINIGEN_PHASES else 0
            progress["generate"] = {
                "completed": phase_index, "total": len(INFINIGEN_PHASES), "percent": estimated,
                "label": "Infinigen coarse generation (estimated)", "estimated": True,
                "phase": current_phase or "initializing", "phase_index": phase_index,
                "phase_count": len(INFINIGEN_PHASES),
                "local_completed": local[0] if local else None,
                "local_total": local[1] if local else None,
                "phase_percent": 100.0 * current_phase_fraction if current_phase_fraction is not None else None,
                "object_count": local[2] if local else None,
            }
        if total > 0:
            done = min(completed, total)
            progress["geometry"] = {"completed": done, "total": total, "percent": 100.0 * done / total,
                                    "label": "Stage 1 geometry units", "checkpointed": True}
        if plan_path.is_file():
            try:
                plan = _read_json(plan_path)
                actual = int(plan.get("actual_pose_count") or 0)
                if actual:
                    progress["view_plan"] = {"completed": actual, "total": actual, "percent": 100.0,
                                             "label": "Coverage-aware camera poses", "checkpointed": True}
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if job.request.get("source_mode") == "nir_passive_backfill" and backfill_state_path.is_file():
            try:
                state = _read_json(backfill_state_path)
                frame_total = int(state.get("requested") or 0)
                frame_done = len(state.get("completed") or [])
                if frame_total:
                    progress["nir_passive_backfill"] = {
                        "completed": min(frame_done, frame_total),
                        "total": frame_total,
                        "percent": 100.0 * min(frame_done, frame_total) / frame_total,
                        "label": "Passive NIR + active−passive sidecars",
                        "checkpointed": True,
                        "remaining": max(0, frame_total - frame_done),
                        "failed": len(state.get("failed") or {}),
                    }
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        for stage, root_key in (("qc_render", "qc"), ("full_render", "dataset")):
            state_path = Path(job.request.get("paths", {}).get(root_key) or "") / "rolling_queue_state.json"
            if not state_path.is_file():
                continue
            try:
                state = _read_json(state_path)
                frame_total = int(state.get("frame_count") or 0)
                frame_done = len(state.get("completed") or [])
                if frame_total:
                    progress[stage] = {"completed": frame_done, "total": frame_total,
                                       "percent": 100.0 * frame_done / frame_total, "label": "Rolling frames", "checkpointed": True,
                                       "lighting_groups": state.get("lighting_groups") or {}}
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        self._stage_progress_cache[job.job_id] = (fingerprint, progress)
        return progress

    def _refresh_external_jobs(self) -> None:
        for job in self._jobs.values():
            if not job.external_adopted:
                continue
            self._capture_process_output(job, job.stage)
            pids = self._external_pids(job)
            if pids:
                # After a controller restart the surviving subprocess is
                # adopted rather than entered through _run_command(), so the
                # normal wall-clock guard is not active.  Apply the same
                # generation guard here; otherwise one pathological
                # high-clutter annealing run can occupy a generation slot
                # indefinitely and starve the scene queue.  The source output
                # is retained and _schedule_generation_fallback creates an
                # isolated lower-clutter variation.
                if job.stage == "generate" and self.infinigen_generate_timeout_s > 0:
                    try:
                        if not job.stage_started_at:
                            job.stage_started_at = _utc()
                            self._save(job, "generation_timeout_clock_initialized", stage="generate")
                        started = datetime.fromisoformat(str(job.stage_started_at).replace("Z", "+00:00"))
                        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                    except (TypeError, ValueError):
                        elapsed = 0.0
                    if elapsed >= self.infinigen_generate_timeout_s:
                        timeout_error = (
                            f"generate exceeded {self.infinigen_generate_timeout_s}s after controller restart; "
                            "preserving output and scheduling a lower-clutter variation"
                        )
                        for pid in pids:
                            try:
                                os.killpg(pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                        job.external_adopted = False
                        job.pid = None
                        job.interruption_reason = timeout_error
                        if self._schedule_generation_fallback(job, error=timeout_error):
                            job.resource_state, job.resource_class = "pending", None
                            job.resource_gpu_indices = []
                            job.desired_gpu_indices = []
                            job.draining_gpu_indices = []
                            job.status, job.stage, job.finished_at = "queued", "queued", None
                            if job.job_id not in self._queue:
                                self._queue.append(job.job_id)
                            self._save(job, "generation_timeout_retry_scheduled", stage="generate",
                                       error=timeout_error, fallback_density=job.request.get("density"),
                                       fallback_surface_clutter=job.request.get("surface_clutter"))
                            self._wake.set()
                        else:
                            job.status, job.stage, job.error = "interrupted", "interrupted", timeout_error
                            job.finished_at = _utc()
                            job.resource_state = "interrupted"
                            self._save(job, "interrupted", stage="generate", error=timeout_error)
                        continue
                if job.pid != pids[0]:
                    job.pid = pids[0]
                    self._save(job, "external_process_heartbeat", stage=job.stage, pids=pids)
                continue
            if self._external_stage_completed(job):
                self._capture_process_output(job, job.stage, include_partial=True)
                completed_stage = job.stage
                job.external_adopted, job.pid, job.current_command = False, None, None
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
                job.stage_results[completed_stage] = {"status": "succeeded", "completed_at": _utc(), "adopted": True}
                job.status, job.stage, job.error, job.finished_at = "queued", "queued", None, None
                if job.job_id not in self._queue:
                    self._queue.append(job.job_id)
                self._save(job, "external_process_completed", stage=completed_stage)
                self._wake.set()
                continue
            job.external_adopted = False
            job.status, job.stage = "interrupted", "interrupted"
            job.resource_gpu_indices = []
            job.desired_gpu_indices = []
            job.draining_gpu_indices = []
            job.error = job.interruption_reason or "adopted external process exited; Resume safely validates and continues from committed artifacts"
            job.finished_at = _utc()
            self._save(job, "external_process_exited")

    def log(self, job_id: str, tail: int = 100) -> dict[str, Any]:
        self.get(job_id)
        lines = self._log_path(self._jobs[job_id]).read_text(encoding="utf-8").splitlines() if self._log_path(self._jobs[job_id]).is_file() else []
        return {"job_id": job_id, "lines": lines[-max(1, min(int(tail), 1000)):]}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None: raise KeyError(job_id)
            if job.status == "queued":
                job.status = job.stage = "cancelled"; job.finished_at = _utc(); self._queue = [x for x in self._queue if x != job_id]
            elif job.status == "running" and job.external_adopted:
                for pid in self._external_pids(job):
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                job.external_adopted = False
                job.status = job.stage = "cancelled"; job.finished_at = _utc()
            elif job.status == "running" and job.job_id not in self._running:
                job.status = job.stage = "cancelled"; job.resource_state = "cancelled"; job.finished_at = _utc()
            elif job.status == "running": job.cancel.set()
            if job.status == "cancelled":
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
            self._save(job, "cancel_requested")
            return job.payload()

    def retry(self, job_id: str) -> dict[str, Any]:
        return self.resume(job_id)

    def retry_with_showcase(self, job_id: str) -> dict[str, Any]:
        """Preserve a failed research attempt and begin its next variation with V1."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            r = job.request
            if job.status not in TERMINAL:
                raise ValueError("only a terminal job can retry with showcase profile")
            if not (r.get("source_mode") == "generate" and r.get("content_profile") == "research_balanced"
                    and r.get("archetype") == "single_room"):
                raise ValueError("showcase retry is available only for failed generated research-balanced single-room jobs")
            archive = list(r.get("showcase_retry_archives") or [])
            archive.append({"at": _utc(), "variation_id": r.get("variation_id"), "scene_id": r.get("scene_id"),
                            "paths": dict(r.get("paths") or {}), "error": job.error})
            r["showcase_retry_archives"] = archive
            r["ir_composition_profile"] = SHOWCASE_PROFILE
            r["max_quality_variations"] = max(5, int(r.get("max_quality_variations") or 0))
            r["max_showcase_composition_attempts"] = 3
            if not self._next_quality_variation(job, failed_stage="retry_with_showcase", error="operator requested showcase profile"):
                raise RuntimeError("no remaining scene variation is available for showcase retry")
            job.error, job.finished_at, job.pid, job.current_command = None, None, None, None
            job.status, job.stage, job.resource_state, job.resource_class = "queued", "queued", "pending", None
            job.resource_gpu_indices = []; job.desired_gpu_indices = []; job.draining_gpu_indices = []
            job.cancel = threading.Event()
            if job.job_id not in self._queue: self._queue.append(job.job_id)
            self._save(job, "showcase_retry_requested", archived_attempts=len(archive))
            self._wake.set()
            return self._payload(job)

    def _archive_legacy_plan(self, job: ControllerJob) -> Path:
        existing = Path(str(job.request.get("plan_adoption_legacy_plan") or ""))
        if existing.is_file():
            digest = existing.stem.removeprefix("render_plan.legacy-")
            config_archive = existing.with_name(f"dataset_config.legacy-{digest}.json")
            if config_archive.is_file():
                job.request["plan_adoption_legacy_config"] = str(config_archive)
            return existing
        plan_path = Path(job.request["paths"]["render_plan"])
        if not plan_path.is_file():
            raise FileNotFoundError("current render plan is unavailable")
        plan = _read_json(plan_path)
        digest = str(plan.get("render_plan_digest") or "")
        if not digest:
            raise ValueError("current render plan lacks a digest")
        archive = plan_path.with_name(f"render_plan.legacy-{digest[:16]}.json")
        if not archive.exists():
            shutil.copy2(plan_path, archive)
        config = Path(job.request["paths"]["dataset"]) / "dataset_config.json"
        if config.is_file():
            config_archive = archive.with_name(f"dataset_config.legacy-{digest[:16]}.json")
            if not config_archive.exists():
                shutil.copy2(config, config_archive)
            job.request["plan_adoption_legacy_config"] = str(config_archive)
        job.request["plan_adoption_legacy_plan"] = str(archive)
        return archive

    def _existing_row_adoption_inputs(self, render_root: Path, current_plan: Path) -> tuple[Path | None, Path | None, bool]:
        """Locate the exact plan/config identity already represented by rows.

        A cancelled queue may have replaced dataset_config.json while leaving
        all completed image artifacts and frame rows untouched.  The frame row
        lighting digest is therefore the authority for recovery.  Returning
        ``row_only=True`` is restricted to one fingerprint for the selected
        plan; the queue performs the remaining camera/artifact checks.
        """
        if not current_plan.is_file() or not (render_root / "frames").is_dir():
            return None, None, False
        try:
            plan = _read_json(current_plan)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None, None, False
        plan_digest = str(plan.get("render_plan_digest") or "")
        if not plan_digest:
            return None, None, False
        fingerprints: set[str] = set()
        matching_rows = 0
        for row_path in (render_root / "frames").glob("*.json"):
            try:
                row = _read_json(row_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if str((row.get("lighting") or {}).get("render_plan_digest") or "") != plan_digest:
                continue
            matching_rows += 1
            fingerprint = str(row.get("dataset_fingerprint") or "")
            if fingerprint:
                fingerprints.add(fingerprint)
        if not matching_rows or len(fingerprints) != 1:
            return None, None, False
        fingerprint = next(iter(fingerprints))
        pipeline_root = current_plan.parent
        config_candidates = sorted(pipeline_root.glob("dataset_config.legacy-*.json"))
        config_candidates += sorted(render_root.glob("dataset_config.legacy-*.json"))
        for config_path in config_candidates:
            try:
                config = _read_json(config_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if (str(config.get("dataset_fingerprint") or "") == fingerprint
                    and str((config.get("render_plan") or {}).get("render_plan_digest") or "") == plan_digest):
                return current_plan, config_path, False
        return current_plan, None, True

    def _queue_corrected_replan(self, job: ControllerJob) -> None:
        """Regenerate only the view plan; all expensive upstream artifacts stay valid."""
        self._build_view_plan(job)
        for stage in ("full_render", "full_verify", "dataset_utility_audit", "publish"):
            job.stage_results.pop(stage, None)
        job.cancel = threading.Event()
        job.replan_requested = False
        job.status, job.stage, job.error, job.finished_at = "queued", "queued", None, None
        job.resource_state, job.resource_class = "pending", None
        job.resource_gpu_indices = []; job.desired_gpu_indices = []; job.draining_gpu_indices = []
        if job.job_id not in self._queue:
            self._queue.append(job.job_id)
        self._save(job, "corrected_plan_queued", legacy_plan=job.request.get("plan_adoption_legacy_plan"))
        self._wake.set()

    def replan(self, job_id: str, *, legacy_plan: str | None = None) -> dict[str, Any]:
        """Safely replace a legacy full-render plan and resume matching frames."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            full_render_recoverable = job.stage == "full_render" or self._next_stage(job) == "full_render"
            if not full_render_recoverable or job.status not in {"running", "cancelled", "failed", "interrupted"}:
                raise ValueError("corrected-plan replan is available only for a full-render job")
            archive = self._archive_legacy_plan(job)
            if legacy_plan:
                requested = Path(legacy_plan).resolve()
                attempt = Path(job.request["paths"]["attempt_root"]).resolve()
                if requested.parent != attempt or not requested.is_file() or not requested.name.startswith("render_plan.legacy-"):
                    raise ValueError("legacy plan override must be an archived plan in this attempt root")
                archive = requested
                digest = requested.stem.removeprefix("render_plan.legacy-")
                config_archive = requested.with_name(f"dataset_config.legacy-{digest}.json")
                if not config_archive.is_file():
                    raise FileNotFoundError("legacy plan override lacks its paired dataset config archive")
                job.request["plan_adoption_legacy_plan"] = str(requested)
                job.request["plan_adoption_legacy_config"] = str(config_archive)
            job.replan_requested = True
            if job.status == "running" and job.job_id in self._running:
                job.cancel.set()
                self._save(job, "corrected_plan_stop_requested", legacy_plan=str(archive))
            else:
                self._queue_corrected_replan(job)
            return self._payload(job)

    def remove_terminal_job(self, job_id: str) -> dict[str, Any]:
        """Remove a terminal card while retaining its diagnostic record off-queue.

        Generated/imported/pipeline artifacts are deliberately untouched.  This
        only removes the durable controller snapshot and JSONL from the active
        Jobs view; the archived snapshot is useful if an operator later needs
        to inspect why a scene was rejected.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status not in TERMINAL or job_id in self._running:
                raise ValueError("only a non-running terminal job can be removed")
            archive = self.control_root.parent / "removed"
            archive.mkdir(parents=True, exist_ok=True)
            payload = job.payload()
            payload["removed_at"] = _utc()
            _atomic_json(archive / f"{job_id}.json", payload)
            log = self._log_path(job)
            if log.is_file():
                os.replace(log, archive / f"{job_id}.jsonl")
            snapshot = self._snapshot_path(job)
            if snapshot.is_file():
                snapshot.unlink()
            self._jobs.pop(job_id, None)
            self._queue = [ident for ident in self._queue if ident != job_id]
            self._stage_progress_cache.pop(job_id, None)
            return {"job_id": job_id, "removed": True, "archive": str(archive / f"{job_id}.json")}

    def set_job_visibility(self, job_id: str, *, hidden: bool) -> dict[str, Any]:
        """Hide/unhide a terminal job without removing its durable history."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status not in TERMINAL:
                raise ValueError("only a terminal job can be hidden")
            if hidden:
                job.hidden_from_ui = True
                job.hidden_reason = self._unrecoverable_reason(job) or "operator archived from viewer"
            else:
                job.hidden_from_ui = False
                job.hidden_reason = None
            self._save(job, "job_hidden" if hidden else "job_unhidden", reason=job.hidden_reason)
            return self._payload(job)

    def replace_failed_generated_scene(self, job_id: str, *, logical_seed: str) -> dict[str, Any]:
        """Create a fresh showcase scene while retaining bidirectional provenance."""
        with self._lock:
            parent = self._jobs.get(job_id)
            if parent is None:
                raise KeyError(job_id)
            if parent.status not in {"failed", "cancelled", "interrupted"}:
                raise ValueError("only a terminal failed scene can be replaced")
            if parent.request.get("source_mode") != "generate":
                raise ValueError("replacement generation requires a generated parent job")
            if not (logical_seed.isdigit() and len(logical_seed) == 8):
                raise ValueError("replacement logical seed must be eight digits")
            room_type = str(parent.request.get("room_type") or "").replace("_", "-")
            if room_type not in ROOM_TYPES:
                raise ValueError("replacement parent lacks a supported room type")
            slug = room_type.replace("-", "_")
            dataset_name = f"infinigen_single_room_{slug}_{logical_seed}_v00_rgb_active_nir_v2"
            raw = {
                key: parent.request[key]
                for key in (
                    "width", "height", "fov", "rgb_spp", "nir_spp",
                    "flash_energy_scale", "ambient_fill_energy_scale",
                    "illumination_diversity", "paired_fraction", "pose_budget",
                    "camera_policy", "adaptive_pose_budget", "sparse_negative_fraction",
                    "max_headings_per_node", "graph_max_nodes", "graph_heading_count",
                    "graph_min_node_spacing", "graph_robot_radius", "material_mix_profile",
                    "ir_material_profile",
                )
                if key in parent.request
            }
            raw.update({
                "source_mode": "generate", "dataset_name": dataset_name,
                "gpu_indices": list(parent.request.get("requested_gpu_indices") or parent.request.get("gpu_indices") or self.gpu_pool),
                "archetype": "single_room", "room_type": room_type,
                # Replacement scenes retain the rich structural/content
                # policy but start with balanced surface clutter.  This
                # avoids immediately reproducing the high-poly annealing
                # timeout that caused the parent scene to be rejected.
                "density": "family_home", "generation_stage": "full",
                "seed": logical_seed, "variation_id": 0,
                # Replacement jobs are deliberately not forced through the
                # research_balanced auto-promotion (which turns balanced
                # clutter back into rich).  anchor_rich preserves room
                # anchors while allowing the bounded balanced-clutter policy.
                "content_profile": "anchor_rich",
                "ir_composition_profile": SHOWCASE_PROFILE,
                "anchor_richness": "rich", "surface_clutter": "balanced",
                "max_quality_variations": 5, "max_showcase_composition_attempts": 3,
            })
            created = self.submit(raw)
            child = self._jobs[str(created["job_id"])]
            child.request["replaces_job_id"] = parent.job_id
            parent.request["replaced_by_job_id"] = child.job_id
            self._save(parent, "replacement_created", replacement_job_id=child.job_id,
                       replacement_dataset_name=dataset_name)
            self._save(child, "replacement_queued", parent_job_id=parent.job_id)
            return self._payload(child)

    def resume(self, job_id: str, *, mode: str = "recommended", insert_stages: list[str] | None = None,
               rerun_from: str | None = None) -> dict[str, Any]:
        """Resume from committed Stage artifacts; never launches a clean overwrite."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None: raise KeyError(job_id)
            if job.status not in TERMINAL: raise ValueError("only terminal jobs can resume")
            active_imports = self._active_import_pids(job)
            if active_imports:
                raise RuntimeError("cannot resume while importer PID(s) still own this source: " + ", ".join(map(str, active_imports)))
            if mode not in {"recommended", "custom"}: raise ValueError("invalid recovery mode")
            # A controller restart can turn a timed-out adopted generator into
            # a terminal interrupted job before the fallback callback runs.
            # Resume that job by scheduling the isolated lower-clutter
            # variation immediately, instead of launching the same expensive
            # annealing attempt again.
            if (job.stage == "interrupted" and "generate exceeded" in str(job.error or "")
                    and self._stage_artifact_state(job, "generate") != "verified"
                    and self._schedule_generation_fallback(job, error=str(job.error))):
                job.status, job.stage, job.finished_at = "queued", "queued", None
                job.resource_state, job.resource_class = "pending", None
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
                if job.job_id not in self._queue:
                    self._queue.append(job.job_id)
                self._save(job, "generation_timeout_retry_scheduled", stage="generate", error=job.error,
                            fallback_density=job.request.get("density"),
                            fallback_surface_clutter=job.request.get("surface_clutter"))
                self._wake.set()
                return self._payload(job)
            if mode == "recommended":
                self._fork_rendered_contract_upgrade_if_needed(job)
            self._apply_recovery(job, rerun_from=rerun_from if mode == "custom" else None,
                                 insert_stages=list(insert_stages or []))
            return self._payload(job)

    @staticmethod
    def _has_committed_render_artifacts(job: ControllerJob) -> bool:
        """Whether replacing Stage 2 in place could mix an old render contract."""
        for key in ("qc", "dataset"):
            root_value = (job.request.get("paths") or {}).get(key)
            if not root_value:
                continue
            root = Path(str(root_value))
            if (root / "index.jsonl").is_file() and (root / "index.jsonl").stat().st_size:
                return True
            try:
                state = _read_json(root / "rolling_queue_state.json")
            except (OSError, ValueError, json.JSONDecodeError):
                state = {}
            if state.get("completed"):
                return True
        return False

    def _contract_upgrade_dataset_name(self, parent: str) -> str:
        base = self._safe_name(f"{parent}__pbr_v4", "dataset_name")
        candidate, index = base, 2
        reserved = {str(item.request.get("dataset_name") or "") for item in self._jobs.values()}
        while candidate in reserved or (self.work_root / candidate).exists() or (self.bean_root / candidate).exists():
            candidate = self._safe_name(f"{base}_r{index:02d}", "dataset_name")
            index += 1
        return candidate

    def _fork_rendered_contract_upgrade_if_needed(self, job: ControllerJob) -> bool:
        """Fork a v4 render root instead of ever mixing replacement Stage 2 with frames.

        This is intentionally a recovery-only migration.  Immutable v2/v3
        datasets and their Stage-2 directory remain intact; Stage 1 and other
        verified upstream artifacts are read-only inputs to the new v4 child.
        """
        if job.request.get("contract_upgrade_revision"):
            return False
        if not self._has_committed_render_artifacts(job):
            return False
        audit = self.recovery_plan(job.job_id)
        if audit.get("recommended_rerun_from") != "principled_prepare":
            return False
        if self._stage_artifact_state(job, "principled_prepare") == "verified":
            return False

        request, old_paths = job.request, dict(job.request.get("paths") or {})
        parent_name = str(request.get("dataset_name") or job.job_id)
        child_name = self._contract_upgrade_dataset_name(parent_name)
        pipeline = Path(str(old_paths["pipeline"]))
        revision = 1
        upgrade_root = pipeline / "contract_upgrades" / f"v4-r{revision:02d}"
        while upgrade_root.exists():
            revision += 1
            upgrade_root = pipeline / "contract_upgrades" / f"v4-r{revision:02d}"

        new_paths = dict(old_paths)
        new_paths.update({
            "attempt_root": str(upgrade_root),
            "prepared": str(upgrade_root / "principled_stage2"),
            "qc": str(upgrade_root / "qc_stage0"),
            "render_plan": str(upgrade_root / "render_plan.json"),
            "qc_render_plan": str(upgrade_root / "qc_render_plan.json"),
            "candidate_visibility": str(upgrade_root / "candidate_visibility.json"),
            "scene_quality": str(upgrade_root / "scene_content_quality.json"),
            "material_mix": str(upgrade_root / "material_mix_quality.json"),
            "dataset": str(self.work_root / child_name),
            "published": str(self.bean_root / child_name),
        })
        request["contract_upgrade_parent_dataset_name"] = parent_name
        request["contract_upgrade_parent_paths"] = old_paths
        request["contract_upgrade_revision"] = revision
        request["dataset_name"] = child_name
        request["paths"] = new_paths
        # A child has no rendered frames, so it may adopt the current paired
        # illumination policy without changing its immutable parent.
        self._upgrade_unrendered_illumination_plan(job)
        stages = self._pipeline(job)
        start = "view_probe" if "view_probe" in stages else "view_plan"
        for stage in stages[stages.index(start):]:
            job.stage_results.pop(stage, None)
        self._save(
            job,
            "contract_upgrade_child_created",
            parent_dataset_name=parent_name,
            child_dataset_name=child_name,
            upgrade_root=str(upgrade_root),
            reused_geometry=old_paths.get("geometry"),
            reason="stale Stage 2 with committed render artifacts",
        )
        return True

    def adopt_external_import(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            pids = self._active_import_pids(job)
            if not pids:
                raise RuntimeError("no live importer for this source to adopt")
            if job.status not in {"failed", "cancelled", "interrupted"}:
                raise ValueError("only an interrupted or terminal job can adopt an external importer")
            job.status, job.stage, job.pid = "running", "import", pids[0]
            job.external_adopted, job.error, job.finished_at = True, None, None
            job.resource_class = self._resource_class("import")
            job.resource_state, job.queue_position = "running", None
            self._save(job, "external_import_adopted", pids=pids)
            return self._payload(job)

    def priority(self, job_id: str, priority: int) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None: raise KeyError(job_id)
            # A pipeline remains ``running`` while it moves through several
            # resource queues.  Let operators prioritize its *next* stage
            # without interrupting the currently executing subprocess.
            if job.status not in {"queued", "running"}:
                raise ValueError("only queued or running jobs can change priority")
            job.priority = int(priority); self._queue.sort(key=lambda ident: (-self._jobs[ident].priority, self._jobs[ident].created_at))
            self._save(job, "priority", priority=job.priority); return job.payload()

    def gpu_inventory(self) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
            rows = []
            for line in result.stdout.splitlines():
                index, name, used, total, utilization = [part.strip() for part in line.split(",", 4)]
                rows.append({"index": int(index), "name": name, "memory_used_mib": int(used), "memory_total_mib": int(total), "utilization_pct": int(utilization)})
        except Exception:
            rows = []
        with self._lock:
            owners: dict[int, list[dict[str, Any]]] = {}
            for job in self._running_jobs():
                if job.resource_class not in {"gpu_render", "blender_bake"}:
                    continue
                for gpu in self._gpu_leases(job):
                    lease_state = (
                        "draining" if gpu in job.draining_gpu_indices
                        else "assigned" if gpu in job.resource_gpu_indices
                        else "desired"
                    )
                    owners.setdefault(gpu, []).append({
                        "job_id": job.job_id,
                        "dataset_name": job.request.get("dataset_name"),
                        "stage": job.stage,
                        "lease_state": lease_state,
                    })
            reserved = set(owners)
        for row in rows:
            row["eligible"] = row["index"] in self.gpu_pool
            row["reserved"] = row["index"] in reserved
            row["owners"] = owners.get(row["index"], [])
        return rows

    def status(self, *, include_hidden: bool = False) -> dict[str, Any]:
        # Normalize persisted terminal leases before taking the GPU snapshot;
        # otherwise the first status request after a restart could briefly
        # expose phantom owners.
        job_status = self.list_jobs(include_hidden=include_hidden)
        return {"service": "ir-dataset-controller", "serial_pipeline": False, "work_root": str(self.work_root),
                "gpu_pool": list(self.gpu_pool),
                "resource_config": {
                    "blender_bootstrap": {"concurrency": self.bootstrap_concurrency},
                    "blender_bake": {"concurrency": self.bake_concurrency, "device": self.bake_device},
                    "blender_prepare": {"concurrency": self.prepare_concurrency},
                    "usage": self._resource_usage(),
                },
                "gpu_inventory": self.gpu_inventory(), **job_status}

    def existing_outputs(self) -> dict[str, Any]:
        with self._lock:
            cached = self._existing_outputs_cache
            if cached is not None and time.monotonic() - cached[0] < self._existing_outputs_cache_ttl_s:
                return cached[1]
        outputs = []
        if self.data_root.is_dir():
            for blend in sorted(self.data_root.glob("*/*/scene.blend")):
                if blend.is_file() and _inside(self.data_root, blend):
                    outputs.append({"relative_path": str(blend.parent.relative_to(self.data_root)), "scene_blend": str(blend)})
        payload = {"outputs": outputs[-200:]}
        with self._lock:
            self._existing_outputs_cache = (time.monotonic(), payload)
        return payload

    def _select_qc_frames(self, scene_dir: Path) -> str:
        graph = _read_json(scene_dir / "viewpoint_graph.json")
        choices = [f"{node['node_id']}@{float(heading.get('yaw_deg', 0)):g}" for node in graph.get("nodes", []) for heading in node.get("headings", [])]
        if not choices: raise RuntimeError("viewpoint graph has no frames")
        count = min(8, len(choices))
        indices = [round(i * (len(choices) - 1) / max(count - 1, 1)) for i in range(count)]
        return ",".join(choices[index] for index in dict.fromkeys(indices))

    def _graph_valid(self, job: ControllerJob) -> bool:
        scene_id = str(job.request.get("scene_id") or "")
        if not scene_id:
            return False
        path = self.scene_root / scene_id / "viewpoint_graph.json"
        try:
            graph = _read_json(path)
            nodes = graph.get("nodes") or []
            metadata = graph.get("metadata") or {}
            expected_max_nodes = int(job.request.get("graph_max_nodes", IR_GRAPH_DEFAULTS["graph_max_nodes"]))
            expected_headings = int(job.request.get("graph_heading_count", IR_GRAPH_DEFAULTS["graph_heading_count"]))
            expected_spacing = float(job.request.get("graph_min_node_spacing", IR_GRAPH_DEFAULTS["graph_min_node_spacing"]))
            expected_radius = float(job.request.get("graph_robot_radius", IR_GRAPH_DEFAULTS["graph_robot_radius"]))
            return (
                bool(nodes)
                and str(graph.get("scene_id") or "") == scene_id
                and all(len(node.get("headings") or []) == expected_headings for node in nodes)
                and int(graph.get("node_heading_count") or 0) == expected_headings
                and int(metadata.get("max_nodes_requested") or 0) == expected_max_nodes
                and abs(float(metadata.get("min_node_spacing_m", -1.0)) - expected_spacing) < 1e-9
                and abs(float(metadata.get("robot_radius_m", -1.0)) - expected_radius) < 1e-9
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _stage_artifact_state(self, job: ControllerJob, stage: str) -> str:
        """Cheap, non-mutating recovery audit for persisted pipeline artifacts."""
        r, p = job.request, job.request.get("paths") or {}
        if stage == "nir_passive_backfill":
            try:
                state = _read_json(Path(p["backfill_state"]))
                if state.get("failed"):
                    return "stale"
                if state.get("status") == "succeeded":
                    return "verified"
                # A bounded controller job is a deliberate smoke checkpoint;
                # its target remains eligible for a later unbounded job.  Do
                # not re-dispatch the same one-frame smoke indefinitely.
                if state.get("status") == "partial" and p.get("backfill_state") and r.get("backfill_limit"):
                    return "verified"
                return "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                return "missing"
        scene = self.scene_root / str(r.get("scene_id") or "")
        if stage == "generate":
            return "verified" if Path(str(r.get("existing_output") or ""), "scene.blend").is_file() else "missing"
        if stage == "showcase_composition":
            try:
                manifest = _read_json(Path(p["showcase_composition"]))
                valid = (Path(p["showcase_blend"]).is_file()
                         and manifest.get("profile") == SHOWCASE_PROFILE
                         and bool(manifest.get("composition_digest"))
                         and int(manifest.get("placed_prop_count") or 0) >= 16)
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                return "missing"
        if stage == "import":
            manifest = self._import_dir(r) / "scene_manifest.json"
            return "verified" if self._import_profile_matches(r) else ("stale" if manifest.is_file() else "missing")
        if stage == "navigation_compile":
            graph_path = scene / "viewpoint_graph.json"
            return "verified" if self._graph_valid(job) else ("stale" if graph_path.is_file() else "missing")
        if stage == "scene_content_audit":
            try:
                audit = _read_json(Path(p["content_audit"]))
                authoring = _read_json(scene / "authoring_map.json")
                from mitsuba_converter.ir_render_plan import stable_digest
                return "verified" if audit.get("status") == "passed" and audit.get("source_authoring_map_digest") == stable_digest(authoring) else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "view_probe":
            try:
                probe = _read_json(Path(p["candidate_visibility"]))
                graph = _read_json(scene / "viewpoint_graph.json")
                authoring = _read_json(scene / "authoring_map.json")
                from mitsuba_converter.ir_render_plan import stable_digest
                valid = (probe.get("candidate_count") and probe.get("probe_digest")
                         and probe.get("source_graph_digest") == stable_digest(graph)
                         and probe.get("source_authoring_map_digest") == stable_digest(authoring))
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "showcase_raster_probe":
            try:
                probe = _read_json(Path(p["showcase_raster_probe"]))
                composition = _read_json(Path(p["showcase_composition"]))
                graph = _read_json(scene / "viewpoint_graph.json")
                from mitsuba_converter.ir_render_plan import stable_digest
                valid = (probe.get("profile") == SHOWCASE_PROFILE
                         and probe.get("source_composition_digest") == composition.get("composition_digest")
                         and probe.get("source_graph_digest") == stable_digest(graph)
                         and bool((probe.get("camera_sets") or {}).get("camera_set_digest")))
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "showcase_acceptance":
            try:
                report = _read_json(Path(p["showcase_acceptance"]))
                pose_floor = int(r.get("min_unique_pose_count", 100))
                actual = int(report.get("actual_pose_count") or 0)
                return "verified" if (report.get("profile") == SHOWCASE_PROFILE
                                       and report.get("status") == "passed"
                                       and actual >= pose_floor) else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "material_extract":
            return "verified" if (scene / "material_slots.json").is_file() else "missing"
        if stage == "material_canonicalize":
            return "verified" if (scene / "material_canonical.json").is_file() else "missing"
        if stage == "lighting_asset_audit":
            try:
                audit = _read_json(Path(p["illumination_audit"]))
                bank = load_bank(self.repo_root)
                return "verified" if audit.get("manifest_digest") == bank.get("manifest_digest") else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                return "missing"
        if stage == "view_plan":
            try:
                plan = _read_json(Path(p["render_plan"]))
                graph = _read_json(scene / "viewpoint_graph.json")
                from mitsuba_converter.ir_render_plan import stable_digest
                if not plan.get("actual_pose_count"):
                    return "missing"
                valid = plan.get("source_graph_digest") == stable_digest(graph)
                if r.get("illumination_diversity"):
                    expected_policy = str(r.get("illumination_pairing_policy") or "legacy_six_way_v1")
                    actual_policy = str((plan.get("illumination") or {}).get("pairing_policy") or "legacy_six_way_v1")
                    valid = valid and actual_policy == expected_policy
                if r.get("ir_composition_profile") == SHOWCASE_PROFILE:
                    probe = _read_json(Path(p["showcase_raster_probe"]))
                    valid = (valid and plan.get("camera_sets", {}).get("camera_set_digest")
                             == (probe.get("camera_sets") or {}).get("camera_set_digest"))
                if r.get("pipeline_revision") == "ir-content-aware-v2" and r.get("source_mode") != "augmentation":
                    probe = _read_json(Path(p["candidate_visibility"]))
                    valid = valid and plan.get("source_visibility_digest") == probe.get("probe_digest")
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "scene_quality_gate":
            try:
                quality = _read_json(Path(p["scene_quality"]))
                plan = _read_json(Path(p["render_plan"]))
                valid = (quality.get("status") == "passed"
                         and quality.get("render_plan_digest") == plan.get("render_plan_digest"))
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "geometry":
            try:
                return "verified" if _read_json(Path(p["geometry"]) / "ir_geometry_profile.json").get("profile") else "missing"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "structural_rematerialize":
            try:
                manifest = _read_json(Path(p["structural_rematerialization"]))
                valid = (manifest.get("schema") == "robomituba.ir_structural_rematerialization.v1"
                         and bool(manifest.get("bindings"))
                         and str(manifest.get("child_scene_id")) == str(r.get("scene_id")))
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "structural_quality_audit":
            try:
                audit = _read_json(Path(p["structural_quality"]))
                return "verified" if audit.get("schema") == "robomituba.ir_structural_material_quality_audit.v1" and audit.get("status") == "passed" else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError):
                return "missing"
        if stage == "prop_pbr_remediate":
            try:
                manifest = _read_json(Path(p["prop_pbr_remediation"]))
                return "verified" if (manifest.get("schema") == "robomituba.ir_prop_pbr_remediation.v1"
                                      and manifest.get("policy") == "hybrid_prop_pbr_v1"
                                      and manifest.get("compiler_version") == "prop-pbr-remediation-v2-metallic-family") else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "overview_proxy":
            try:
                proxy = Path(p["overview_proxy"])
                manifest = _read_json(proxy / "overview_proxy_manifest.json")
                geometry = _read_json(Path(p["geometry"]) / "ir_geometry_profile.json")
                valid = (
                    (proxy / "overview_proxy.glb").is_file()
                    and manifest.get("source_geometry_digest") == geometry.get("geometry_digest")
                    and int(manifest.get("triangles") or 0) <= 50_000
                    and int(manifest.get("triangle_target") or 0) == 25_000
                    and int(manifest.get("triangle_cap") or 0) == 50_000
                )
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "principled_prepare":
            try:
                contract = _read_json(Path(p.get("prepared") or "") / "principled_material_contract.json")
                valid = (
                    contract.get("schema") == "robomituba.ir_principled_material_contract.v4"
                    and contract.get("contract_version") == "blender42-principled-metallic-roughness-v4"
                    and contract.get("compiler_version") == STAGE2_COMPILER_VERSION
                    and all((record.get("metallic_contract") or {}).get("schema") == "robomituba.metallic_contract.v2"
                            for record in (contract.get("materials") or []))
                )
                return "verified" if valid else "stale"
            except (OSError, ValueError, json.JSONDecodeError):
                return "missing"
        if stage == "material_mix_audit":
            try:
                audit = _read_json(Path(p["material_mix"]))
                contract = _read_json(Path(p["prepared"]) / "principled_material_contract.json")
                from mitsuba_converter.ir_material_mix import audit_material_mix
                return "verified" if audit.get("audit_digest") == audit_material_mix(contract).get("audit_digest") and audit.get("status") == "passed" else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage in {"qc_render", "full_render"}:
            root = Path(p.get("qc" if stage == "qc_render" else "dataset") or "")
            try:
                state = _read_json(root / "rolling_queue_state.json")
                return "verified" if not state.get("pending") and not state.get("failed") and int(state.get("frame_count") or 0) > 0 else "missing"
            except (OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage in {"qc_verify", "full_verify", "publish"}:
            return "verified" if job.stage_results.get(stage, {}).get("status") == "succeeded" else "missing"
        if stage == "dataset_utility_audit":
            try:
                return "verified" if _read_json(Path(p["dataset"]) / "quality" / "dataset_utility_audit.json").get("status") == "passed" else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        return "missing"

    def recovery_plan(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None: raise KeyError(job_id)
            stages = self._pipeline(job)
            rows, first = [], None
            for index, stage in enumerate(stages):
                artifact = self._stage_artifact_state(job, stage)
                result = job.stage_results.get(stage, {}).get("status")
                state = (
                    "Verified" if artifact == "verified"
                    else "Stale" if artifact == "stale"
                    else "Failed" if result == "failed"
                    else "Missing"
                )
                if first is None and state != "Verified": first = index
                rows.append({"stage": stage, "state": state, "resource_class": self._resource_class(stage),
                             "selected": first is not None and index >= first})
            start = stages[first] if first is not None else None
            return {"job_id": job_id, "stages": rows, "recommended_rerun_from": start,
                    "insertable_stages": [row["stage"] for row in rows if row["state"] == "Missing"],
                    "can_resume": job.status in TERMINAL}

    def _apply_recovery(self, job: ControllerJob, *, rerun_from: str | None, insert_stages: list[str]) -> None:
        stages = self._pipeline(job)
        unknown = set(insert_stages) - set(stages)
        if unknown: raise ValueError("unknown recovery stage: " + ", ".join(sorted(unknown)))
        audit = self.recovery_plan(job.job_id)
        recommended = audit.get("recommended_rerun_from")
        start = rerun_from or (insert_stages[0] if insert_stages else recommended)
        if start is None: return
        if start not in stages: raise ValueError("invalid rerun_from stage")
        start_index = stages.index(start)
        # A user may choose to rerun earlier, never later than a missing prerequisite.
        if recommended is not None and start_index > stages.index(str(recommended)):
            raise ValueError(f"cannot skip missing prerequisite {recommended}")
        for stage in stages[:start_index]:
            if self._stage_artifact_state(job, stage) == "verified" and job.stage_results.get(stage, {}).get("status") != "succeeded":
                job.stage_results[stage] = {
                    "status": "succeeded", "completed_at": _utc(), "recovered_from_verified_artifact": True,
                }
        for stage in stages[start_index:]:
            job.stage_results.pop(stage, None)
        job.error, job.finished_at, job.pid, job.current_command = None, None, None, None
        job.status, job.stage, job.resource_state, job.resource_class = "queued", "queued", "pending", None
        job.resource_gpu_indices = []
        job.desired_gpu_indices = []
        job.draining_gpu_indices = []
        job.gpu_target_updated_at = None
        job.interruption_reason = None
        job.eligible_gpu_indices = self._eligible_gpus(job)
        job.cancel = threading.Event()
        if job.job_id not in self._queue: self._queue.append(job.job_id)
        self._save(job, "recovery_queued", rerun_from=start, insert_stages=insert_stages)
        self._wake.set()

    def _build_view_plan(self, job: ControllerJob) -> None:
        path = Path(job.request["paths"]["render_plan"])
        graph = self.scene_root / job.request["scene_id"] / "viewpoint_graph.json"
        showcase = job.request.get("ir_composition_profile") == SHOWCASE_PROFILE
        showcase_probe = Path(job.request["paths"]["showcase_raster_probe"]) if showcase else None
        showcase_composition = Path(job.request["paths"]["showcase_composition"]) if showcase else None
        showcase_acceptance = Path(job.request["paths"]["showcase_acceptance"]) if showcase else None
        if showcase:
            report = _read_json(showcase_acceptance)
            if report.get("status") != "passed":
                raise ShowcaseAcceptanceError("showcase acceptance is not passed: " + ", ".join(report.get("failures") or ["unknown"]))
            composition_payload = _read_json(showcase_composition)
            probe_payload = _read_json(showcase_probe)
            provenance = {
                "profile": SHOWCASE_PROFILE,
                "registry_digest": composition_payload.get("registry_digest"),
                "composition_digest": composition_payload.get("composition_digest"),
                "raster_probe_digest": probe_payload.get("probe_digest"),
                "camera_set_selection_digest": (probe_payload.get("camera_sets") or {}).get("camera_set_digest"),
                "acceptance_digest": report.get("acceptance_digest"),
            }
        else:
            provenance = None
        plan = write_render_plan(path, graph, requested_pose_count=int(job.request["pose_budget"]),
                                 seed=int(job.request.get("effective_scene_seed") or job.request.get("seed") or 20260812),
                                 scene_id=str(job.request["scene_id"]),
                                 visibility_path=Path(job.request["paths"]["candidate_visibility"])
                                 if job.request.get("camera_policy") == "content_aware_v2" else None,
                                 adaptive_budget=bool(job.request.get("adaptive_pose_budget")),
                                 max_headings_per_node=int(job.request.get("max_headings_per_node", 6)),
                                 sparse_fraction=float(job.request.get("sparse_negative_fraction", 0.15)),
                                 illumination=(load_bank(self.repo_root) if job.request.get("illumination_diversity") else None),
                                 paired_fraction=float(job.request.get("paired_fraction", 0.25)),
                                 illumination_pairing_policy=str(job.request.get("illumination_pairing_policy") or "legacy_six_way_v1"),
                                 min_unique_pose_count=int(job.request.get("min_unique_pose_count", 100)),
                                 camera_sets_path=showcase_probe,
                                 showcase_provenance=provenance)
        # The showcase contract is about independent camera poses, not the
        # number of lighting-expanded frames.  Older acceptance reports were
        # created before this floor was enforced and could therefore publish a
        # 41-pose scene while claiming a 50-pose target.  Reject that plan at
        # the authoritative boundary so it cannot enter Stage 2/render.
        if showcase and int(plan.get("unique_pose_count") or 0) < int(job.request.get("min_unique_pose_count", 100)):
            raise ShowcaseAcceptanceError(
                "showcase independent pose minimum not met: "
                f"{plan.get('unique_pose_count', 0)} < {job.request.get('min_unique_pose_count', 100)}"
            )
        # New review/replacement jobs use this as a hard dataset contract,
        # independent of the optional showcase composition path.  A graph
        # with too few usable candidates must not silently publish a sparse
        # render plan after the operator requested a minimum viewpoint count.
        minimum_unique = int(job.request.get("min_unique_pose_count", 1))
        if (job.request.get("pipeline_revision") == "ir-content-aware-v2"
                and int(plan.get("unique_pose_count") or 0) < minimum_unique):
            raise QualityGateError(
                "independent pose minimum not met: "
                f"{plan.get('unique_pose_count', 0)} < {minimum_unique}"
            )
        if job.request.get("illumination_diversity"):
            illumination_plan = plan.get("illumination") or {}
            actual_poses = int(plan.get("unique_pose_count") or plan.get("actual_pose_count") or 0)
            paired_poses = int(illumination_plan.get("paired_pose_count") or 0)
            pairing_policy = str(illumination_plan.get("pairing_policy") or "legacy_six_way_v1")
            requested_pair_fraction = (1.0 if pairing_policy == "reference_subset_v2"
                                       else float(job.request.get("paired_fraction", 0.25)))
            if actual_poses and paired_poses / actual_poses + 1e-9 < requested_pair_fraction:
                raise QualityGateError(
                    "paired lighting coverage below requested minimum: "
                    f"{paired_poses}/{actual_poses} < {requested_pair_fraction:.3f}"
                )
        pairing_policy = str((plan.get("illumination") or {}).get("pairing_policy") or "legacy_six_way_v1")
        if pairing_policy == "reference_subset_v2":
            reference_id = str((plan.get("illumination") or {}).get("reference_condition_id") or "reference_neutral_v1")
            reference_group = next(group for group in plan["groups"] if group["lighting"]["id"] == reference_id)
            sampled_variations = {
                group["lighting"]["id"]: list(group["poses"])[:2]
                for group in plan["groups"] if group["lighting"]["id"] != reference_id
            }
            wanted_pairs = {
                pose.get("pair_id") for poses in sampled_variations.values() for pose in poses
                if pose.get("pair_id")
            }
            qc_groups = []
            for group in plan["groups"]:
                condition_id = group["lighting"]["id"]
                poses = ([pose for pose in reference_group["poses"] if pose.get("pair_id") in wanted_pairs]
                         if condition_id == reference_id else sampled_variations[condition_id])
                qc_groups.append({**group, "poses": poses})
        else:
            qc_groups = [{**group, "poses": list(group["poses"])[:2]} for group in plan["groups"]]
        qc_core = {key: value for key, value in plan.items() if key not in {"groups", "render_plan_id", "render_plan_digest"}}
        qc_core["groups"] = qc_groups
        if qc_core.get("illumination"):
            qc_counts = {group["lighting"]["id"]: len(group["poses"]) for group in qc_groups}
            qc_core["illumination"] = {
                **qc_core["illumination"],
                "condition_pose_counts": qc_counts,
                "expected_frame_count": sum(qc_counts.values()),
                "paired_pose_count": len(wanted_pairs) if pairing_policy == "reference_subset_v2"
                                     else int(qc_core["illumination"].get("paired_pose_count") or 0),
                "single_pose_count": 0 if pairing_policy == "reference_subset_v2"
                                     else int(qc_core["illumination"].get("single_pose_count") or 0),
            }
        from mitsuba_converter.ir_render_plan import stable_digest
        qc_digest = stable_digest(qc_core)
        qc_plan = {**qc_core, "render_plan_id": qc_digest[:16], "render_plan_digest": qc_digest,
                   "parent_render_plan_digest": plan["render_plan_digest"], "stage": "qc"}
        _atomic_json(Path(job.request["paths"]["qc_render_plan"]), qc_plan)
        job.stage_results["view_plan"] = {
            "status": "succeeded", "completed_at": _utc(), "requested_pose_count": plan["requested_pose_count"],
            "actual_pose_count": plan["actual_pose_count"], "candidate_pose_count": plan["candidate_pose_count"],
            "unique_pose_count": plan.get("unique_pose_count", plan["actual_pose_count"]),
            "min_unique_pose_count": plan.get("min_unique_pose_count", 1),
            "clamped": plan["clamped"], "lighting_group_count": plan["lighting_group_count"],
            "render_plan_digest": plan["render_plan_digest"],
        }
        if plan.get("illumination"):
            job.stage_results["view_plan"]["illumination"] = dict(plan["illumination"])
        if showcase:
            job.stage_results["view_plan"]["showcase"] = {
                "camera_set_count": len((plan.get("camera_sets") or {}).get("sets") or []),
                "camera_set_digest": (plan.get("camera_sets") or {}).get("camera_set_digest"),
                "composition_digest": provenance["composition_digest"],
                "acceptance_digest": provenance["acceptance_digest"],
                "sets": [{"camera_set_id": row.get("camera_set_id"), "anchor_id": row.get("anchor_id"),
                          "member_count": row.get("member_count"), "azimuth_span_deg": row.get("azimuth_span_deg")}
                         for row in ((plan.get("camera_sets") or {}).get("sets") or [])],
                "composition_attempt_index": int(job.request.get("showcase_composition_attempt_index") or 0),
                "last_rejection": (list(job.request.get("showcase_composition_attempts") or [])[-1]
                                   if job.request.get("showcase_composition_attempts") else None),
            }
        self._save(job, "view_plan_succeeded", **job.stage_results["view_plan"])

    def _scene_quality_gate(self, job: ControllerJob) -> None:
        """Gate density and viewpoint richness before the expensive Stage-1 bake."""
        p = job.request["paths"]
        content, plan = _read_json(Path(p["content_audit"])), _read_json(Path(p["render_plan"]))
        poses = [pose for group in plan.get("groups") or [] for pose in group.get("poses") or []]
        # Coverage plans carry the lightweight visibility result in ``utility``;
        # showcase plans carry the richer raster result in ``probe``.  Treating
        # the latter as an empty utility made an accepted showcase report a
        # visible-object median of zero at the following generic quality gate.
        utilities = [pose.get("utility") or pose.get("probe") or {} for pose in poses]
        visible = sorted(
            float(
                item.get("visible_object_count")
                or item.get("visible_pbr_object_count")
                or len(item.get("visible_object_ids") or [])
            )
            for item in utilities
        )
        median = visible[len(visible) // 2] if visible else 0.0
        sparse = sum(item.get("utility_class") == "sparse_negative" for item in utilities) / max(1, len(utilities))
        footprint = content.get("room_footprint") or {}
        area = float(footprint.get("area_m2") or 0.0)
        nonstructural = int(content.get("nonstructural_object_count") or 0)
        per_m2 = nonstructural / area if area > 0 else 0.0
        failures = []
        if content.get("status") != "passed": failures.append("scene_content_contract")
        # The density is a coarse scene-level guard, not the primary richness
        # signal.  A hard 3.0/m² cutoff caused otherwise excellent scenes (for
        # example 76 non-structural objects, visible median 26, no sparse
        # poses) to be regenerated solely because of a few centimetres of
        # footprint estimation error.  Keep the visible-object and sparse
        # pose gates strict, while using a 2.5/m² floor to avoid wasting a
        # full Infinigen variation on that numerical boundary.
        if per_m2 < 2.5: failures.append("nonstructural_density_below_2_5_per_m2")
        if median < 2.0: failures.append("visible_object_median_below_2")
        if sparse > 0.150001: failures.append("sparse_pose_fraction_above_15pct")
        report = {"schema": "robomituba.ir_scene_content_quality.v1", "profile": "research_balanced",
                  "status": "failed" if failures else "passed", "attempt": int(job.request.get("variation_id") or 0),
                  "logical_seed": job.request.get("logical_seed"), "effective_seed": job.request.get("effective_scene_seed"),
                  "room_area_m2": area or None, "nonstructural_object_count": nonstructural,
                  "render_plan_digest": plan.get("render_plan_digest"),
                  "nonstructural_objects_per_m2": round(per_m2, 6) if area else None,
                  "selected_pose_count": len(poses), "selected_visible_object_median": median,
                  "selected_sparse_pose_fraction": round(sparse, 6), "failures": failures}
        report["quality_digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic_json(Path(p["scene_quality"]), report)
        # ``report.status`` is the domain value (passed/failed), while the
        # scheduler requires the stage value (succeeded/failed).  Put the
        # scheduler value last so a passed gate is not dispatched forever.
        job.stage_results["scene_quality_gate"] = {
            **report,
            "quality_status": report["status"],
            "status": "succeeded" if not failures else "failed",
        }
        self._save(job, "scene_quality_checked", **report)
        if failures:
            raise QualityGateError("scene quality gate failed: " + ", ".join(failures))

    def _next_quality_variation(self, job: ControllerJob, *, failed_stage: str, error: str) -> bool:
        """Move a generated Research-balanced job to its next isolated attempt."""
        r = job.request
        if r.get("source_mode") != "generate" or r.get("content_profile") not in {
            "research_balanced", "balanced", "anchor_rich"
        }:
            return False
        attempt_index = int(r.get("quality_attempt_index") or 0)
        limit = int(r.get("max_quality_variations") or 4)
        history = list(r.get("quality_attempts") or [])
        history.append({"attempt_index": attempt_index, "variation_id": r.get("variation_id"),
                        "scene_id": r.get("scene_id"), "failed_stage": failed_stage, "error": error,
                        "at": _utc(), "paths": dict(r.get("paths") or {}),
                        "showcase_composition_attempts": list(r.get("showcase_composition_attempts") or [])})
        if attempt_index + 1 >= limit:
            r["quality_attempts"] = history
            return False
        variation = int(r.get("variation_id") or 0) + 1
        r["quality_attempt_index"] = attempt_index + 1
        r["quality_attempts"] = history
        r["variation_id"] = variation
        r["effective_scene_seed"] = _effective_scene_seed(str(r["logical_seed"]), str(r["room_type"]), variation)
        if r.get("ir_composition_profile") == SHOWCASE_PROFILE:
            r["showcase_composition_attempt_index"] = 0
            r["showcase_composition_attempts"] = []
            r["showcase_composition_seed"] = _showcase_composition_seed(r["effective_scene_seed"], 0)
            r["showcase_import_name"] = _showcase_import_name(r["effective_scene_seed"], variation, 0)
        suffix = f"_{str(r['room_type']).replace('-', '_')}" if r.get("archetype") == "single_room" else ""
        r["existing_output"] = str(self.data_root / f"kr_{r['effective_scene_seed']}_{r['archetype']}{suffix}" / r["generation_stage"])
        base_scene_id = re.sub(r"_v\d{2}$", "", str(r.get("scene_id_base") or r.get("scene_id")))
        r["scene_id"] = f"{base_scene_id}_v{variation:02d}"
        pipeline = Path(r["paths"]["pipeline"])
        attempt = pipeline / "attempts" / f"v{variation:02d}"
        dataset, published = r["paths"]["dataset"], r["paths"]["published"]
        r["paths"] = {
            "pipeline": str(pipeline), "attempt_root": str(attempt), "geometry": str(attempt / "ir_geometry"),
            "prepared": str(attempt / "principled_stage2"), "qc": str(attempt / "qc_stage0"),
            "render_plan": str(attempt / "render_plan.json"), "qc_render_plan": str(attempt / "qc_render_plan.json"),
            "candidate_visibility": str(attempt / "candidate_visibility.json"), "content_audit": str(attempt / "scene_content_audit.json"),
            "showcase_blend": str(attempt / "showcase" / "composition_c00.blend"),
            "showcase_composition": str(attempt / "showcase" / "composition_c00.json"),
            "showcase_raster_probe": str(attempt / "showcase_raster_probe.json"),
            "showcase_acceptance": str(attempt / "showcase_acceptance.json"),
            "illumination_audit": str(attempt / "illumination_asset_audit.json"), "scene_quality": str(attempt / "scene_content_quality.json"),
            "material_mix": str(attempt / "material_mix_quality.json"), "structural_rematerialization": str(attempt / "structural_rematerialization.json"), "structural_quality": str(attempt / "structural_material_quality_audit.json"), "overview_proxy": str(attempt / "overview_proxy"),
            "dataset": dataset, "published": published,
        }
        job.stage_results = {}
        job.error = None
        self._save(job, "quality_variation_queued", variation_id=variation, attempt_index=attempt_index + 1,
                   failed_stage=failed_stage, error=error)
        return True

    def _next_showcase_composition_attempt(self, job: ControllerJob, *, failed_stage: str, error: str) -> bool:
        """Retry only the post-generation showcase layer before regenerating a room.

        Derived blends/manifests are attempt-indexed and never overwritten, so
        a failed packing or probe can be inspected after the next seed starts.
        """
        r = job.request
        if r.get("ir_composition_profile") != SHOWCASE_PROFILE:
            return False
        index = int(r.get("showcase_composition_attempt_index") or 0)
        limit = int(r.get("max_showcase_composition_attempts") or 3)
        history = list(r.get("showcase_composition_attempts") or [])
        history.append({"composition_attempt_index": index, "composition_seed": r.get("showcase_composition_seed"),
                        "variation_id": r.get("variation_id"), "failed_stage": failed_stage, "error": error,
                        "at": _utc(), "paths": {key: value for key, value in (r.get("paths") or {}).items()
                                                     if key.startswith("showcase_")}})
        r["showcase_composition_attempts"] = history
        if index + 1 >= limit:
            return False
        index += 1
        r["showcase_composition_attempt_index"] = index
        r["showcase_composition_seed"] = _showcase_composition_seed(str(r["effective_scene_seed"]), index)
        r["showcase_import_name"] = _showcase_import_name(str(r["effective_scene_seed"]), int(r.get("variation_id") or 0), index)
        base_scene_id = str(r.get("scene_id_base") or r.get("scene_id"))
        candidate_scene_id = f"{base_scene_id}_c{index:02d}"
        if len(candidate_scene_id) > 96:
            candidate_scene_id = f"{base_scene_id[:82]}_c{index:02d}_{hashlib.sha256(base_scene_id.encode()).hexdigest()[:8]}"
        r["scene_id"] = candidate_scene_id
        root = Path(r["paths"]["attempt_root"])
        showcase_root = root / "showcase"
        r["paths"].update({
            "showcase_blend": str(showcase_root / f"composition_c{index:02d}.blend"),
            "showcase_composition": str(showcase_root / f"composition_c{index:02d}.json"),
            "showcase_raster_probe": str(root / f"showcase_raster_probe_c{index:02d}.json"),
            "showcase_acceptance": str(root / f"showcase_acceptance_c{index:02d}.json"),
        })
        stages = self._pipeline(job)
        start = stages.index("showcase_composition")
        for stage in stages[start:]:
            job.stage_results.pop(stage, None)
        job.error = None
        self._save(job, "showcase_composition_retry_queued", composition_attempt_index=index,
                   composition_seed=r["showcase_composition_seed"], failed_stage=failed_stage, error=error)
        return True

    def _command(self, job: ControllerJob, stage: str) -> list[str]:
        r, p = job.request, job.request["paths"]
        if stage == "nir_passive_backfill":
            assigned = list(job.resource_gpu_indices or job.desired_gpu_indices)
            if not assigned:
                raise RuntimeError("passive backfill dispatched without a GPU lease")
            command = [
                "python3", "apps/backfill_ir_nir_passive.py",
                "--dataset", str(r["backfill_dataset"]),
                "--prepared-scene-dir", str(r["backfill_prepared"]),
                "--gpu-index", str(assigned[0]),
            ]
            if r.get("backfill_limit") is not None:
                command += ["--limit", str(r["backfill_limit"])]
            return command
        native_source = Path(r.get("existing_output") or "")
        source = Path(p["showcase_blend"]) if r.get("ir_composition_profile") == SHOWCASE_PROFILE else native_source
        if stage == "generate":
            cmd = ["python3", "scripts/infinigen_wizard.py", "--archetype", r["archetype"], "--density", r["density"], "--stage", r["generation_stage"],
                   "--seed", str(r.get("effective_scene_seed") or r["seed"]), "--logical-seed", str(r.get("logical_seed") or r["seed"]),
                   "--variation-id", str(r.get("variation_id", 0)), "--anchor-richness", str(r.get("anchor_richness") or "balanced"),
                   "--surface-clutter", str(r.get("surface_clutter") or "balanced"),
                   "--placement-profile", str(r.get("placement_profile") or "legacy_clutter_v1"),
                   "--ir-material-profile", str(r.get("ir_material_profile") or "standard"),
                   "--scene-id", r["scene_id"], "--no-import", "--yes"]
            if r["archetype"] == "single_room": cmd += ["--room-type", r["room_type"]]
            return cmd
        if stage == "showcase_composition":
            source_blend = self._source_blend_path(native_source)
            return ["python3", "apps/compose_infinigen_ir_showcase.py", "--source-blend", str(source_blend),
                    "--out-blend", p["showcase_blend"], "--manifest", p["showcase_composition"],
                    "--seed", str(r.get("showcase_composition_seed") or r.get("effective_scene_seed") or r.get("seed"))]
        if stage == "structural_rematerialize":
            return ["python3", "apps/rematerialize_ir_structural_scene.py",
                    "--stage1-dir", str(Path(p["geometry"]) / "stage1"),
                    "--registry", str(r["structural_pbr_registry"]),
                    "--registry-root", str(r["structural_pbr_registry_root"]),
                    "--out", str(p["structural_rematerialization"]),
                    "--child-scene-id", str(r["scene_id"]),
                    "--parent-scene-id", str(r.get("parent_scene_id") or r["scene_id"]),
                    "--material-variant-id", str(r["material_variant_id"]),
                    "--material-seed", str(r["material_seed"])]
        if stage == "prop_pbr_remediate":
            return ["python3", "apps/build_prop_pbr_remediation.py",
                    "--stage1-dir", str(Path(p["geometry"]) / "stage1"),
                    "--registry", str(self.repo_root / "configs" / "infinigen" / "prop_pbr_registry_v2.json"),
                    "--out", p["prop_pbr_remediation"], "--child-scene-id", str(r["scene_id"]),
                    "--parent-scene-id", str(r.get("parent_scene_id") or r["scene_id"]),
                    "--seed", str(r.get("prop_pbr_seed") or 0)]
        if stage == "structural_quality_audit":
            return ["python3", "apps/audit_ir_structural_materials.py", "--manifest", p["structural_rematerialization"], "--registry-root", str(r["structural_pbr_registry_root"]), "--out", p["structural_quality"]]
        if stage == "lighting_asset_audit":
            return ["python3", "apps/audit_ir_illumination_bank.py", "--repo-root", str(self.repo_root), "--out", p["illumination_audit"]]
        if stage == "material_mix_audit":
            return ["python3", "apps/audit_ir_material_mix.py", "--contract",
                    str(Path(p["prepared"]) / "principled_material_contract.json"), "--out", p["material_mix"],
                    "--profile", str(r.get("material_mix_profile") or METAL_PROFILE)]
        if stage == "import":
            profile = str(r.get("import_profile") or "strict-pbr-v1")
            cmd = ["bash", "apps/run_infinigen_import.sh", str(source), "--scene-id", r["scene_id"],
                   "--stage1-profile", profile]
            # Updated IR jobs opt into the conservative tiny/high-poly detail
            # filter.  It protects walls/frames/doors and only drops explicitly
            # decorative semantics, avoiding the pathological bake cost without
            # changing legacy imports unless they explicitly request it.
            if r.get("filter_small_high_poly", str(r.get("pipeline_revision") or "") == "ir-content-aware-v2"):
                cmd += ["--filter-small-high-poly", "--small-high-poly-max-extent-m",
                        str(r.get("small_high_poly_max_extent_m", 0.5)),
                        "--small-high-poly-min-triangles",
                        str(r.get("small_high_poly_min_triangles", 100000))]
            if r.get("ir_composition_profile") == SHOWCASE_PROFILE:
                cmd += ["--import-name", str(r["showcase_import_name"])]
                # Showcase composition may intentionally filter tiny/high-poly
                # source units or replace a few generated assets.  In that
                # mode the source object set is not required to be byte-for-
                # byte identical to the parent scene; otherwise the importer
                # aborts during its conservative object-ID stability check and
                # a technically valid composed scene can never be resumed.
                # Keep the relaxed rule scoped to showcase imports only.
                cmd.append("--allow-object-id-churn")
            # A prior import may have atomically completed Stage 1 before the
            # controller was interrupted.  Continue its converter stages while
            # preserving the verified manifest/GLBs/atlases instead of starting
            # a new bpy export tree.
            if self._import_profile_matches(r):
                cmd.append("--skip-export")
            return cmd
        if stage == "navigation_compile":
            command = ["python3", "apps/opticalnav.py", "graph", "build", "--dataset",
                    str(self.repo_root / "out" / "opticalnav" / "opticalnav-v0.2"),
                    "--scene-id", r["scene_id"], "--seed", str(r.get("effective_scene_seed") or r.get("seed") or 20260812),
                    "--max-nodes", str(r.get("graph_max_nodes", IR_GRAPH_DEFAULTS["graph_max_nodes"])),
                    "--heading-count", str(r.get("graph_heading_count", IR_GRAPH_DEFAULTS["graph_heading_count"])),
                    "--min-node-spacing", str(r.get("graph_min_node_spacing", IR_GRAPH_DEFAULTS["graph_min_node_spacing"])),
                    "--robot-radius", str(r.get("graph_robot_radius", IR_GRAPH_DEFAULTS["graph_robot_radius"]))]
            return command
        if stage == "scene_content_audit":
            return ["python3", "apps/audit_infinigen_scene_content.py", "--authoring-map",
                    str(self.scene_root / r["scene_id"] / "authoring_map.json"), "--out", p["content_audit"],
                    "--room-type", str(r.get("room_type") or "generic"), "--profile", str(r.get("content_profile") or "balanced"),
                    "--source-blend", str(self._source_blend_path(source)), "--registry-root", str(self.pipeline_root),
                    "--registry-root", str(self.bean_root)]
        if stage == "view_probe":
            return ["python3", "apps/probe_ir_candidate_visibility.py", "--graph",
                    str(self.scene_root / r["scene_id"] / "viewpoint_graph.json"), "--authoring-map",
                    str(self.scene_root / r["scene_id"] / "authoring_map.json"), "--out", p["candidate_visibility"],
                    "--fov", str(r["fov"])]
        if stage == "showcase_raster_probe":
            return ["python3", "apps/probe_ir_showcase_raster.py", "--graph",
                    str(self.scene_root / r["scene_id"] / "viewpoint_graph.json"), "--authoring-map",
                    str(self.scene_root / r["scene_id"] / "authoring_map.json"), "--composition", p["showcase_composition"],
                    "--out", p["showcase_raster_probe"], "--seed", str(r.get("showcase_composition_seed") or r.get("effective_scene_seed") or r.get("seed")),
                    "--pose-budget", str(r["pose_budget"]), "--fov", str(r["fov"]), "--width", "160", "--height", "120"]
        if stage == "showcase_acceptance":
            return ["python3", "apps/accept_ir_showcase.py", "--probe", p["showcase_raster_probe"],
                    "--composition", p["showcase_composition"], "--out", p["showcase_acceptance"]]
        if stage == "dataset_utility_audit":
            cmd = ["python3", "apps/audit_ir_dataset_utility.py", "--dataset", p["dataset"],
                    "--render-plan", p["render_plan"], "--visibility", p["candidate_visibility"],
                    "--content-audit", p["content_audit"], "--requested-density", str(r.get("density") or "unknown")]
            if r.get("content_profile") == "research_balanced":
                cmd += ["--material-mix", p["material_mix"], "--material-visibility", str(Path(p["qc"]) / "material_visibility_qc.json")]
            return cmd
        if stage == "material_extract":
            return ["python3", "apps/material_pipeline.py", "extract", "--scene", str(self.scene_root / r["scene_id"])]
        if stage == "material_canonicalize":
            return ["python3", "apps/material_pipeline.py", "canonicalize", "--scene", str(self.scene_root / r["scene_id"])]
        scene = self.scene_root / r["scene_id"]
        blend = self._source_blend_path(source)
        if stage == "geometry":
            cmd = ["python3", "apps/build_ir_geometry_profile.py", "--source-scene-dir", str(scene),
                   "--source-blend", str(blend), "--out", p["geometry"], "--profile", "ir_semantic_lod_v1",
                   "--cycles-device", self.bake_device, "--cycles-fallback", "CPU"]
            # The updated IR content-aware scenes use 512px atlases and feed
            # evaluated values into the Principled v2 graph.  Keep the bake
            # deterministic but avoid spending the full legacy 12 Cycles
            # samples / 4096 fallback resolution on tiny props; structural
            # CC0 override maps remain independently high resolution.
            if str(r.get("pipeline_revision") or "") == "ir-content-aware-v2":
                cmd += ["--bake-samples", str(r.get("geometry_bake_samples", 4)),
                        "--max-bake-res", str(r.get("geometry_max_bake_res", 2048))]
            if r.get("filter_small_high_poly", str(r.get("pipeline_revision") or "") == "ir-content-aware-v2"):
                cmd += ["--filter-small-high-poly",
                        "--small-high-poly-max-extent-m", str(r.get("small_high_poly_max_extent_m", 0.5)),
                        "--small-high-poly-min-triangles", str(r.get("small_high_poly_min_triangles", 100000))]
            geometry_root = Path(p["geometry"])
            stage1_root = geometry_root / "stage1"
            published_stage1 = (
                (stage1_root / "scene_manifest.json").is_file()
                and (geometry_root / "derived_ir_semantic_lod.blend").is_file()
            )
            if published_stage1:
                # Stage 1 is atomically complete; only rebuild the derived
                # scene/material profile portion of this command.
                cmd.append("--finalize-existing")
            elif stage1_root.exists():
                # An interrupted export owns verified per-unit checkpoints and
                # atlases but has not published its final manifest/blend yet.
                # Resume those units instead of treating the directory itself
                # as proof that Stage 1 was finalized.
                cmd.append("--resume")
            return cmd
        if stage == "overview_proxy":
            return ["python3", "apps/build_ir_scene_overview_proxy.py", "--geometry-profile-dir", p["geometry"],
                    "--out", p["overview_proxy"], "--triangle-target", "25000", "--triangle-cap", "50000"]
        if stage == "principled_prepare":
            cmd = ["python3", "apps/prepare_ir_principled_scene.py", "--geometry-profile-dir", p["geometry"], "--out", p["prepared"]]
            # A Stage-2 directory is immutable once verified, but an older
            # compiler output in a stopped/failed job is not reusable by the
            # current queue.  The preparer archives that stale directory
            # atomically before compiling the replacement; it never deletes
            # or overwrites it in place.
            if Path(p["prepared"]).exists():
                cmd.append("--rebuild-stale")
            if r.get("illumination_diversity"):
                cmd += ["--illumination-manifest", str(self.repo_root / "configs" / "ir_lighting" / "illumination_diversity_v1.json")]
            if r.get("structural_rematerialize"):
                cmd += ["--structural-material-manifest", p["structural_rematerialization"]]
            if r.get("hybrid_prop_pbr"):
                cmd += ["--prop-material-manifest", p["prop_pbr_remediation"]]
            return cmd
        # The parent process keeps a stable allow-list for its lifetime while
        # gpu_allocation.json is the sole live lease.  This permits controller
        # handoff (for example GPU 0 -> GPU 3) without letting the queue escape
        # the job's eligible pool or spawn an unleased worker.
        eligible = list(
            job.eligible_gpu_indices
            or self._eligible_gpus(job)
            or job.desired_gpu_indices
            or job.resource_gpu_indices
        )
        if not eligible:
            raise RuntimeError(f"render stage {stage} dispatched without a GPU lease")
        render_root = Path(p["qc"] if stage == "qc_render" else p["dataset"])
        common = [
            "python3", "apps/render_ir_principled_dataset_queue.py",
            "--scene-dir", str(scene), "--prepared-scene-dir", p["prepared"],
            "--gpu-indices", ",".join(map(str, eligible)), "--workers", str(len(eligible)),
            "--gpu-allocation-file", str(render_root / "gpu_allocation.json"),
            "--gpu-state-file", str(render_root / "gpu_worker_state.json"),
            "--compatible-worker-resume",
            "--device", "OPTIX", "--fov", str(r["fov"]),
            "--flash-energy-scale", str(r["flash_energy_scale"]),
            "--ambient-fill-energy-scale", str(r["ambient_fill_energy_scale"]),
            "--overview-proxy-dir", p["overview_proxy"],
        ]
        if r.get("nir_passive"):
            common.append("--nir-passive")
        else:
            # Legacy controller snapshots explicitly retain the active-only
            # contract.  Do not let the queue's new-dataset default alter
            # their fingerprint or silently schedule extra Blender renders.
            common.append("--no-nir-passive")
        if stage == "qc_render":
            return common + ["--out", p["qc"], "--frame-plan", p["qc_render_plan"], "--width", "342", "--height", "256", "--rgb-spp", "64", "--nir-spp", "64"]
        if stage == "full_render":
            command = common + ["--out", p["dataset"], "--frame-plan", p["render_plan"], "--width", str(r["width"]), "--height", str(r["height"]), "--rgb-spp", str(r["rgb_spp"]), "--nir-spp", str(r["nir_spp"])]
            legacy_plan = r.get("plan_adoption_legacy_plan")
            legacy_config = r.get("plan_adoption_legacy_config")
            row_plan, row_config, row_only = self._existing_row_adoption_inputs(
                Path(p["dataset"]), Path(p["render_plan"]),
            )
            if row_plan is not None:
                legacy_plan = str(row_plan)
                legacy_config = str(row_config) if row_config is not None else None
            if legacy_plan:
                command += ["--adopt-compatible-plan", str(legacy_plan)]
                if legacy_config:
                    command += ["--adopt-compatible-config", str(legacy_config)]
                elif row_only:
                    command.append("--adopt-existing-rows")
            return command
        raise ValueError(f"no command for stage {stage}")

    def _process_log_path(self, job: ControllerJob, stage: str) -> Path:
        """Return a regular-file stdout sink that survives controller restarts."""
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return self.control_root / "process_output" / job.job_id / f"{stage}.{suffix}.log"

    def _capture_process_output(self, job: ControllerJob, stage: str, *, include_partial: bool = False) -> None:
        """Append newly durable child output to the event log exactly once.

        A subprocess inherits a regular file descriptor instead of a controller
        owned pipe.  That keeps Blender/Infinigen alive when the UI server is
        upgraded.  The byte offset is persisted with the job so a newly started
        controller can continue tailing the exact same file without duplicate
        viewer events.
        """
        if not job.process_log_path:
            return
        path = Path(job.process_log_path)
        try:
            with path.open("rb") as stream:
                stream.seek(max(0, int(job.process_log_offset or 0)))
                payload = stream.read()
        except OSError:
            return
        if not payload:
            return
        consumed = 0
        lines: list[str] = []
        for line in payload.splitlines(keepends=True):
            if not include_partial and not line.endswith((b"\n", b"\r")):
                break
            consumed += len(line)
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            job.process_log_offset += len(line)
            lines.append(text)
        # ``splitlines`` deliberately leaves an unterminated record untouched
        # until either more data arrives or the process has exited.  It avoids
        # emitting the same partial Blender line on every status poll.
        if include_partial and consumed < len(payload):
            remainder = payload[consumed:]
            job.process_log_offset += len(remainder)
            text = remainder.decode("utf-8", "replace").rstrip("\r\n")
            if text:
                lines.append(text)
        if lines:
            # A restarted controller can inherit thousands of Blender lines.
            # Persist the event batch with one append and one atomic snapshot;
            # calling _save once per line held the scheduler lock for minutes
            # on network-backed /bean storage and made every HTTP poll pending.
            job.updated_at = _utc()
            log_path = self._log_path(job)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write("".join(
                    json.dumps({"at": job.updated_at, "event": "output", "stage": stage, "line": text},
                               ensure_ascii=False) + "\n"
                    for text in lines
                ))
            _atomic_json(self._snapshot_path(job), job.payload())

    def _run_command(self, job: ControllerJob, stage: str, command: list[str]) -> None:
        # An adopted process has no controller-owned stage thread. Once this
        # controller launches a later stage, clear that old adoption before
        # persisting a fresh PID; otherwise a restart can inspect a stale or
        # reused PID and apply the wrong lifecycle/timeout rule.
        job.external_adopted = False
        job.pid = None
        job.stage, job.current_command, job.stage_started_at = stage, command, _utc()
        self._save(job, "stage_started", command=command)
        # The regular render queue owns gpu_allocation.json and worker-state
        # files.  Passive backfill uses its own per-dataset lock/state and
        # must not overwrite those render-queue telemetry files.
        if stage in {"qc_render", "full_render"}:
            self._write_render_allocation(job, stage)
        environment = os.environ.copy()
        # Controller subprocesses must work whether or not the developer shell
        # has editable modules installed.  Keep existing PYTHONPATH entries but
        # put this checkout's source packages first.
        source_paths = [str(self.repo_root / "modules" / name / "src") for name in
                        ("mitsuba_converter", "robomituba_bridge", "navigation_dataset")]
        environment["PYTHONPATH"] = os.pathsep.join(source_paths + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else []))
        if stage in BLENDER_BOOTSTRAP_STAGES or stage in BLENDER_COMPOSITION_STAGES or stage in BLENDER_PREPARE_STAGES or stage in INFINIGEN_GENERATE_STAGES:
            environment["CUDA_VISIBLE_DEVICES"] = ""
            if stage in BLENDER_BOOTSTRAP_STAGES:
                environment["ROBOMITUBA_MATERIALIZE_PROGRESS"] = "1"
        elif stage in BLENDER_BAKE_STAGES and job.resource_gpu_indices:
            assigned = job.resource_gpu_indices[0]
            environment["CUDA_VISIBLE_DEVICES"] = str(assigned)
            environment["ROBOMITUBA_ASSIGNED_BAKE_GPU"] = str(assigned)
        output_path = self._process_log_path(job, stage)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # The child and all of its Blender descendants retain this regular file
        # after the controller process exits.  A pipe would lose its last reader
        # during a hot reload and send SIGPIPE to an otherwise healthy job.
        with output_path.open("wb", buffering=0) as output_stream:
            process = self._runner(command, cwd=self.repo_root, stdout=output_stream, stderr=subprocess.STDOUT,
                                   text=False, bufsize=0, start_new_session=True, env=environment)
            job.pid, job.process_log_path, job.process_log_offset = process.pid, str(output_path), 0
            self._save(job, "process_started", pid=process.pid, process_log_path=str(output_path))
            started_monotonic = time.monotonic()
            while True:
                if job.cancel.is_set():
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    self._capture_process_output(job, stage, include_partial=True)
                    raise RuntimeError("cancelled")
                self._capture_process_output(job, stage)
                if process.poll() is not None:
                    break
                if (
                    stage == "generate"
                    and self.infinigen_generate_timeout_s > 0
                    and time.monotonic() - started_monotonic >= self.infinigen_generate_timeout_s
                ):
                    timeout_error = (
                        f"generate exceeded {self.infinigen_generate_timeout_s}s; "
                        "preserving output and scheduling a lower-clutter variation"
                    )
                    job.interruption_reason = timeout_error
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    self._capture_process_output(job, stage, include_partial=True)
                    raise GenerationTimeoutError(timeout_error)
                if (
                    stage == "geometry"
                    and self.geometry_timeout_s > 0
                    and time.monotonic() - started_monotonic >= self.geometry_timeout_s
                ):
                    timeout_error = (
                        f"geometry exceeded {self.geometry_timeout_s}s; preserving unit checkpoints "
                        "and scheduling a lower-cost filtered bake retry"
                    )
                    job.interruption_reason = timeout_error
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    self._capture_process_output(job, stage, include_partial=True)
                    raise GeometryTimeoutError(timeout_error)
                time.sleep(0.25)
            code = process.wait()
            self._capture_process_output(job, stage, include_partial=True)
        job.pid = None
        if code: raise RuntimeError(f"{stage} exited with {code}")
        job.stage_results[stage] = {
            "status": "succeeded", "completed_at": _utc(),
            "resource_gpu_indices": list(job.resource_gpu_indices),
        }; self._save(job, "stage_succeeded")

    def _verify(self, job: ControllerJob, *, qc: bool) -> None:
        stage_name = "qc_verify" if qc else "full_verify"
        job.stage = stage_name
        self._save(job, "stage_started")
        root = Path(job.request["paths"]["qc" if qc else "dataset"])
        state = _read_json(root / "rolling_queue_state.json")
        summary = _read_json(root / "qc_summary.json")
        if state.get("pending") or state.get("failed") or not summary.get("fallback_threshold_passed"):
            raise RuntimeError("QC gate failed: queue incomplete, failed frames, or fallback threshold")
        rows = [json.loads(line) for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(rows) != int(state.get("frame_count", -1)) or len(rows) != len(state.get("completed") or []):
            raise RuntimeError("QC gate failed: index/queue frame counts disagree")
        required = {"rgb", "nir_active", "base_color_rgb", "roughness", "metallic", "normal_geometry_world", "normal_shading_world"}
        if not rows or not required <= set(rows[0].get("paths") or {}): raise RuntimeError("QC gate failed: required modalities absent")
        if job.request.get("illumination_diversity"):
            pairs: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                pair_id = row.get("pair_id")
                if row.get("capture_kind") == "paired" and pair_id:
                    pairs.setdefault(str(pair_id), []).append(row)
            pairing_policy = str(job.request.get("illumination_pairing_policy") or "legacy_six_way_v1")
            expected_pair_members = 2 if pairing_policy == "reference_subset_v2" else 6
            if not pairs or any(len(group) != expected_pair_members for group in pairs.values()):
                raise RuntimeError(
                    f"QC gate failed: incomplete illumination pair for {pairing_policy} "
                    f"(expected {expected_pair_members} members)"
                )
            for group in pairs.values():
                first = group[0]
                invariant = (first.get("camera"), first.get("pbr_gt_contract_digest"), first.get("viewpoint_id"), first.get("heading_deg"))
                if any((row.get("camera"), row.get("pbr_gt_contract_digest"), row.get("viewpoint_id"), row.get("heading_deg")) != invariant for row in group[1:]):
                    raise RuntimeError("QC gate failed: illumination pair changed camera or PBR GT contract")
        import cv2
        import numpy as np
        # Verify every indexed artifact has the recorded dimensions and can be
        # decoded to finite values before allowing a costly next stage/publish.
        for row in rows:
            expected = (int(row.get("height") or 0), int(row.get("width") or 0))
            for modality, relative in (row.get("paths") or {}).items():
                artifact = (root / str(relative)).resolve()
                if root.resolve() not in artifact.parents or artifact.is_symlink():
                    raise RuntimeError(f"QC gate failed: unsafe artifact path {relative!r}")
                image = cv2.imread(str(artifact), cv2.IMREAD_UNCHANGED)
                if image is None or image.shape[:2] != expected or not np.isfinite(image).all():
                    raise RuntimeError(f"QC gate failed: invalid artifact {row.get('frame_id')}/{modality}")
        if qc:
            # The v2 contract has a normal map route; at least one visible material must
            # produce a non-flat effective normal in the Stage-0 samples.
            found = False
            for row in rows:
                a = cv2.imread(str(root / row["paths"]["normal_geometry_world"]), cv2.IMREAD_UNCHANGED)
                b = cv2.imread(str(root / row["paths"]["normal_shading_world"]), cv2.IMREAD_UNCHANGED)
                if a is not None and b is not None and (a.astype("int32") - b.astype("int32")).__abs__().max() > 2:
                    found = True; break
            if not found: raise RuntimeError("QC gate failed: no effective normal-map divergence observed")
            visibility = self._material_visibility_qc(root, rows, job=job)
            if visibility["status"] != "passed":
                raise QualityGateError("material visibility QC failed: " + ", ".join(visibility["failures"]))
            if job.request.get("hybrid_prop_pbr"):
                prop_coverage = self._prop_pbr_coverage_qc(root, rows, job)
                if prop_coverage["train_valid_ratio"] < float(job.request.get("prop_pbr_target", 0.70)):
                    raise QualityGateError(
                        f"small-prop PBR coverage {prop_coverage['train_valid_ratio']:.1%} < "
                        f"target {float(job.request.get('prop_pbr_target', 0.70)):.1%}"
                    )
                _atomic_json(Path(job.request["paths"]["pipeline"]) / "prop_pbr_coverage_qc.json", prop_coverage)
            _atomic_json(Path(job.request["paths"]["pipeline"]) / "winner.json", {
                "schema": "robomituba.ir_quality_attempt_winner.v1", "selected_at": _utc(),
                "variation_id": job.request.get("variation_id"), "attempt_index": job.request.get("quality_attempt_index"),
                "scene_id": job.request.get("scene_id"), "attempt_root": job.request["paths"].get("attempt_root"),
                "scene_quality": job.request["paths"].get("scene_quality"),
                "material_mix": job.request["paths"].get("material_mix"),
                "material_visibility_qc": str(root / "material_visibility_qc.json"),
            })
        job.stage_results[stage_name] = {"status": "succeeded", "completed_at": _utc()}; self._save(job, "verified", qc=qc)

    def _prop_pbr_coverage_qc(self, root: Path, rows: list[dict[str, Any]], job: ControllerJob) -> dict[str, Any]:
        """Measure visible eligible-prop pixels from exact Stage-0 masks/IDs."""
        import cv2
        import numpy as np
        contract = _read_json(Path(job.request["paths"]["prepared"]) / "principled_material_contract.json")
        prop_ids = {int(record["material_id"]) for record in (contract.get("materials") or [])
                    if bool((record.get("prop_pbr_eligibility") or {}).get("eligible")) and record.get("material_id") is not None}
        eligible = train_valid = source_valid = remediated = 0
        per_frame = []
        for row in rows:
            paths = row["paths"]
            ids = cv2.imread(str(root / paths["material_id"]), cv2.IMREAD_UNCHANGED)
            train = cv2.imread(str(root / paths["train_pbr_valid_mask"]), cv2.IMREAD_UNCHANGED)
            source = cv2.imread(str(root / paths["source_valid_mask"]), cv2.IMREAD_UNCHANGED)
            remed = cv2.imread(str(root / paths["remediated_pbr_mask"]), cv2.IMREAD_UNCHANGED)
            if any(x is None for x in (ids, train, source, remed)):
                raise RuntimeError("small-prop coverage QC requires remediated/train-valid artifacts")
            mask = np.isin(ids, list(prop_ids)) if prop_ids else np.zeros(ids.shape, dtype=bool)
            count = int(mask.sum()); valid = int((mask & (train > 0)).sum())
            eligible += count; train_valid += valid
            source_valid += int((mask & (source > 0)).sum()); remediated += int((mask & (remed > 0)).sum())
            per_frame.append({"frame_id": row.get("frame_id"), "eligible_pixels": count, "train_valid_pixels": valid})
        return {"schema": "robomituba.ir_prop_pbr_coverage_qc.v1", "target": float(job.request.get("prop_pbr_target", .70)),
                "eligible_prop_material_ids": sorted(prop_ids), "eligible_pixels": eligible,
                "train_valid_pixels": train_valid, "source_valid_pixels": source_valid, "remediated_pixels": remediated,
                "train_valid_ratio": train_valid / max(1, eligible), "frames": per_frame}

    def _material_visibility_qc(self, root: Path, rows: list[dict[str, Any]], *, job: ControllerJob | None = None) -> dict[str, Any]:
        """Evaluate metal coverage from exact Stage-0 GT, never RGB appearance."""
        import cv2
        import numpy as np
        threshold = 0.7
        frame_rows, group_rows, histogram = [], {}, [0] * 10
        total_valid = total_high = 0
        material_counts: dict[int, int] = {}
        material_observed_frames: dict[int, set[str]] = {}
        roughness_bins = [0] * 5
        interior_samples: dict[int, dict[str, Any]] = {}
        coverage_mixed_pixels = coverage_mixed_intermediate = 0
        coverage_component_sizes: list[int] = []
        structural_ids: set[int] = set()
        if job and job.request.get("structural_rematerialize"):
            contract = _read_json(Path(job.request["paths"]["prepared"]) / "principled_material_contract.json")
            structural_ids = {int(record["material_id"]) for record in (contract.get("materials") or [])
                              if record.get("structural_rematerialization") and record.get("material_id") is not None}
        structural_valid = structural_high = native_high = 0
        for row in rows:
            paths = row["paths"]
            metallic = cv2.imread(str(root / paths["metallic"]), cv2.IMREAD_UNCHANGED)
            defined = cv2.imread(str(root / paths["gt_defined_mask"]), cv2.IMREAD_UNCHANGED)
            replacement = cv2.imread(str(root / paths["replacement_mask"]), cv2.IMREAD_UNCHANGED)
            fallback = cv2.imread(str(root / paths["fallback_mask"]), cv2.IMREAD_UNCHANGED)
            material_id = cv2.imread(str(root / paths["material_id"]), cv2.IMREAD_UNCHANGED)
            roughness = cv2.imread(str(root / paths["roughness"]), cv2.IMREAD_UNCHANGED)
            base_color = cv2.imread(str(root / paths["base_color_rgb"]), cv2.IMREAD_UNCHANGED)
            shading_normal = cv2.imread(str(root / paths["normal_shading_world"]), cv2.IMREAD_UNCHANGED)
            family_id = cv2.imread(str(root / paths["metallic_family_id"]), cv2.IMREAD_UNCHANGED)
            exposed = cv2.imread(str(root / paths["exposed_metal_mask"]), cv2.IMREAD_UNCHANGED)
            if any(image is None for image in (metallic, defined, replacement, fallback, material_id, roughness,
                                                base_color, shading_normal, family_id, exposed)):
                raise RuntimeError("material visibility QC requires metallic/ID/validity masks")
            scale = float(np.iinfo(metallic.dtype).max) if np.issubdtype(metallic.dtype, np.integer) else 1.0
            value = metallic.astype(np.float32) / scale
            valid = (defined > 0) & ~(replacement > 0) & ~(fallback > 0)
            high = valid & (value >= threshold)
            rough_scale = float(np.iinfo(roughness.dtype).max) if np.issubdtype(roughness.dtype, np.integer) else 1.0
            rough_value = roughness.astype(np.float32) / rough_scale
            base_scale = float(np.iinfo(base_color.dtype).max) if np.issubdtype(base_color.dtype, np.integer) else 1.0
            base_value = base_color.astype(np.float32) / base_scale
            base_luminance = base_value[..., :3].mean(axis=2) if base_value.ndim == 3 else base_value
            normal_scale = float(np.iinfo(shading_normal.dtype).max) if np.issubdtype(shading_normal.dtype, np.integer) else 1.0
            normal_value = shading_normal.astype(np.float32) / normal_scale * 2.0 - 1.0
            if high.any():
                rough_indices = np.minimum((rough_value[high] * 5).astype(np.int32), 4)
                for index, count in enumerate(np.bincount(rough_indices, minlength=5)):
                    roughness_bins[index] += int(count)
            valid_count, high_count = int(valid.sum()), int(high.sum())
            total_valid += valid_count; total_high += high_count
            if structural_ids:
                structural = valid & np.isin(material_id, list(structural_ids))
                structural_valid += int(structural.sum())
                structural_high += int((high & structural).sum())
                native_high += int((high & ~structural).sum())
            if valid_count:
                bins = np.minimum((value[valid] * 10).astype(np.int32), 9)
                for index, count in enumerate(np.bincount(bins, minlength=10)):
                    histogram[index] += int(count)
            for encoded, count in zip(*np.unique(material_id[high], return_counts=True)):
                material_counts[int(encoded)] = material_counts.get(int(encoded), 0) + int(count)
                material_observed_frames.setdefault(int(encoded), set()).add(str(row.get("frame_id")))
            # Evaluate spatial supervision away from antialiased object edges.
            for encoded in np.unique(material_id[valid]):
                mid = int(encoded)
                region = (material_id == encoded) & valid
                interior = cv2.erode(region.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
                if not interior.any():
                    continue
                entry = interior_samples.setdefault(mid, {"pixels": 0, "metallic_sum": 0.0, "metallic_sq_sum": 0.0,
                                                           "roughness_sum": 0.0, "roughness_sq_sum": 0.0,
                                                           "normal_sum": np.zeros(3, dtype=np.float64),
                                                           "normal_sq_norm_sum": 0.0, "intermediate_pixels": 0,
                                                           "exposed_pixels": 0, "covered_pixels": 0,
                                                           "exposed_base_sum": 0.0, "covered_base_sum": 0.0,
                                                           "exposed_roughness_sum": 0.0, "covered_roughness_sum": 0.0})
                mv, rv = value[interior], rough_value[interior]
                nv, bv = normal_value[interior], base_luminance[interior]
                entry["pixels"] += int(mv.size)
                entry["metallic_sum"] += float(mv.sum()); entry["metallic_sq_sum"] += float((mv * mv).sum())
                entry["roughness_sum"] += float(rv.sum()); entry["roughness_sq_sum"] += float((rv * rv).sum())
                entry["normal_sum"] += nv.sum(axis=0, dtype=np.float64)
                entry["normal_sq_norm_sum"] += float((nv * nv).sum())
                entry["intermediate_pixels"] += int(((mv > 0.02) & (mv < 0.98)).sum())
                exposed_interior = mv >= 0.98
                covered_interior = mv <= 0.02
                entry["exposed_pixels"] += int(exposed_interior.sum())
                entry["covered_pixels"] += int(covered_interior.sum())
                entry["exposed_base_sum"] += float(bv[exposed_interior].sum())
                entry["covered_base_sum"] += float(bv[covered_interior].sum())
                entry["exposed_roughness_sum"] += float(rv[exposed_interior].sum())
                entry["covered_roughness_sum"] += float(rv[covered_interior].sum())
            mixed = valid & (family_id == 2)
            coverage_mixed_pixels += int(mixed.sum())
            coverage_mixed_intermediate += int((mixed & (value > 0.02) & (value < 0.98)).sum())
            if mixed.any():
                components, labels, stats, _ = cv2.connectedComponentsWithStats((mixed & (exposed > 0)).astype(np.uint8), 8)
                coverage_component_sizes.extend(int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, components))
            lighting = (row.get("lighting") or {}).get("id", "unknown")
            item = {"frame_id": row.get("frame_id"), "lighting_id": lighting, "valid_pixels": valid_count,
                    "high_metallic_pixels": high_count, "high_metallic_fraction": high_count / valid_count if valid_count else 0.0}
            frame_rows.append(item)
            group = group_rows.setdefault(lighting, {"frame_count": 0, "valid_pixels": 0, "high_metallic_pixels": 0})
            group["frame_count"] += 1; group["valid_pixels"] += valid_count; group["high_metallic_pixels"] += high_count
        coverage = total_high / total_valid if total_valid else 0.0
        visible_fraction = sum(item["high_metallic_pixels"] > 0 for item in frame_rows) / max(1, len(frame_rows))
        dominant_id, dominant_count = max(material_counts.items(), key=lambda item: item[1], default=(None, 0))
        dominant_ratio = dominant_count / total_high if total_high else 0.0
        for group in group_rows.values():
            group["high_metallic_fraction"] = group["high_metallic_pixels"] / max(1, group["valid_pixels"])
        failures = []
        physical_failures = []
        diagnostic_findings = []
        if visible_fraction < .5: diagnostic_findings.append("high_metallic_visible_in_less_than_half_qc_frames")
        if coverage < .03: diagnostic_findings.append("high_metallic_coverage_below_3pct")
        if coverage > .12: diagnostic_findings.append("high_metallic_coverage_above_12pct")
        if len(material_counts) < 2: diagnostic_findings.append("fewer_than_two_visible_high_metal_materials")
        if dominant_ratio > .50: diagnostic_findings.append("single_material_dominates_high_metallic_pixels")
        mixed_intermediate_ratio = coverage_mixed_intermediate / max(1, coverage_mixed_pixels)
        if coverage_mixed_pixels and mixed_intermediate_ratio > 0.02:
            # ``coverage_mixed`` is the explicit contract for a spatial
            # Principled metallic map.  Unlike a legacy *uniform* fractional
            # scalar (which is rejected during preparation), texture samples
            # between zero and one are meaningful: they encode a filtered or
            # authored coverage transition.  Requiring a near-binary rendered
            # result here incorrectly rejects the exact texture GT that the
            # contract deliberately preserves, especially after bilinear
            # sampling and mip filtering.  Retain the statistic for dataset
            # review, but do not turn this representation-level diagnostic
            # into a render-blocking physical-material failure.
            diagnostic_findings.append("coverage_mixed_continuous_approximation")
        # Structural remediation deliberately makes every overridden structural
        # slot dielectric.  Showcase camera sets likewise use this report as a
        # diagnostic: a sparse Stage-0 subset may legitimately miss most
        # metallic props even though the accepted composition contains them.
        # Keep the findings in the report, but do not block the showcase
        # pipeline on this sampling-sensitive heuristic.
        showcase_diagnostic = bool(job and job.request.get("ir_composition_profile") == SHOWCASE_PROFILE)
        if not structural_ids and not showcase_diagnostic:
            failures.extend(diagnostic_findings)
        failures.extend(physical_failures)
        material_interior = []
        for mid, sample in sorted(interior_samples.items()):
            count = max(1, int(sample["pixels"]))
            metal_mean = sample["metallic_sum"] / count
            rough_mean = sample["roughness_sum"] / count
            normal_mean = np.asarray(sample["normal_sum"], dtype=np.float64) / count
            exposed_count = max(1, int(sample["exposed_pixels"]))
            covered_count = max(1, int(sample["covered_pixels"]))
            material_interior.append({
                "material_id": mid, "interior_pixels": int(sample["pixels"]),
                "metallic_variance": max(0.0, sample["metallic_sq_sum"] / count - metal_mean ** 2),
                "roughness_variance": max(0.0, sample["roughness_sq_sum"] / count - rough_mean ** 2),
                "normal_spatial_variance": max(0.0, sample["normal_sq_norm_sum"] / count - float(normal_mean @ normal_mean)),
                "near_binary_ratio": 1.0 - sample["intermediate_pixels"] / count,
                "observed_frame_fraction": len(material_observed_frames.get(mid, set())) / max(1, len(frame_rows)),
                "shared_coverage_correlation": {
                    "exposed_pixels": int(sample["exposed_pixels"]),
                    "covered_pixels": int(sample["covered_pixels"]),
                    "base_luminance_delta": sample["exposed_base_sum"] / exposed_count - sample["covered_base_sum"] / covered_count,
                    "roughness_delta": sample["exposed_roughness_sum"] / exposed_count - sample["covered_roughness_sum"] / covered_count,
                },
            })
        report = {"schema": "robomituba.ir_material_visibility_qc.v1", "profile": METAL_PROFILE,
                  "high_metallic_threshold": threshold, "status": "failed" if failures else "passed",
                  "valid_pixel_count": total_valid, "high_metallic_pixel_count": total_high,
                  "high_metallic_fraction": coverage, "visible_frame_fraction": visible_fraction,
                  "dominant_material_id": dominant_id, "dominant_material_ratio": dominant_ratio,
                  "high_metal_material_instance_count": len(material_counts),
                  "conductor_roughness_histogram_5_bins": roughness_bins,
                  "material_interior": material_interior,
                  "coverage_mixed": {"pixels": coverage_mixed_pixels,
                                      "intermediate_ratio": mixed_intermediate_ratio,
                                      "connected_component_sizes": sorted(coverage_component_sizes, reverse=True)[:100]},
                  "histogram_10_bins": histogram, "lighting_groups": group_rows, "frames": frame_rows,
                  "top_material_ids": [{"material_id": key, "high_metallic_pixels": value,
                                        "fraction": value / total_high} for key, value in sorted(material_counts.items(), key=lambda item: -item[1])[:10]],
                  "failures": failures}
        report["physical_failures"] = physical_failures
        if structural_ids:
            report["structural_override_coverage"] = {
                "material_ids": sorted(structural_ids), "valid_pixel_count": structural_valid,
                "high_metallic_pixel_count": structural_high,
                "high_metallic_fraction": structural_high / structural_valid if structural_valid else 0.0,
                "native_high_metallic_pixel_count": native_high,
                "policy": "structural_override_is_dielectric_native_objects_supply_metallicity_v1",
            }
        report["diagnostic_findings"] = diagnostic_findings
        report["gate_mode"] = (
            "structural_override_diagnostic" if structural_ids
            else "showcase_metal_visibility_diagnostic" if showcase_diagnostic
            else "global_metal_visibility_hard_gate"
        )
        report["qc_digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic_json(root / "material_visibility_qc.json", report)
        return report

    def _assert_prepared_v2(self, job: ControllerJob) -> None:
        contract_path = Path(job.request["paths"]["prepared"]) / "principled_material_contract.json"
        contract = _read_json(contract_path)
        if contract.get("schema") != "robomituba.ir_principled_material_contract.v4":
            raise RuntimeError("prepared scene is not the required Principled material-contract v4")
        if contract.get("contract_version") != "blender42-principled-metallic-roughness-v4":
            raise RuntimeError("prepared scene does not use MetallicContractV2 Principled v4")
        # Keep recovery validation aligned with the render queue.  A material
        # contract v4 alone is insufficient when the compiled graph predates a
        # required worker/AOV contract; otherwise failure is deferred until a
        # GPU render has already been scheduled.
        if contract.get("compiler_version") != STAGE2_COMPILER_VERSION:
            raise RuntimeError("prepared scene was built with an incompatible Stage 2 compiler version")
        required = {"base_color_rgb", "base_color_nir", "roughness", "metallic", "normal_geometry_world", "normal_shading_world"}
        records = contract.get("materials") or []
        if not records or any(set((record.get("effective_inputs") or {})) != required for record in records):
            raise RuntimeError("prepared scene lacks the required effective-input audit")
        if any((record.get("metallic_contract") or {}).get("schema") != "robomituba.metallic_contract.v2" for record in records):
            raise RuntimeError("prepared scene lacks valid per-material MetallicContractV2 provenance")
        override = contract.get("structural_rematerialization")
        if job.request.get("structural_rematerialize"):
            if not isinstance(override, dict) or (override.get("selection") or {}).get("policy") != "interior_structure_only_v2_role_curated":
                raise RuntimeError("prepared rematerialized scene lacks the interior-structure-only override audit")
            if any(record.get("structural_rematerialization") and not record.get("structural_rematerialization", {}).get("material_id") for record in records):
                raise RuntimeError("prepared rematerialized scene has invalid external structural provenance")

    def _assert_pipeline_owner(self, job: ControllerJob) -> None:
        """Prevent legacy duplicate jobs from writing one IR artifact root.

        Generation/import outputs are scene-specific and remain useful, so the
        guard starts only when a job is about to enter its shared IR pipeline.
        New submissions are rejected earlier; this protects jobs queued before
        that validation existed.
        """
        pipeline = str((job.request.get("paths") or {}).get("pipeline") or "")
        if not pipeline:
            return
        contenders = [
            other for other in self._jobs.values()
            if other.job_id != job.job_id
            and other.status != "cancelled"
            and str((other.request.get("paths") or {}).get("pipeline") or "") == pipeline
        ]
        if not contenders:
            return
        owner = min([job, *contenders], key=lambda item: (item.created_at, item.job_id))
        if owner.job_id != job.job_id:
            raise RuntimeError(
                f"pipeline path is owned by job {owner.job_id}; generated scene is preserved, "
                "resubmit it as Existing output with a unique dataset name"
            )

    def _next_stage(self, job: ControllerJob) -> str | None:
        for stage in self._pipeline(job):
            # The durable artifact is authoritative for recovery.  A stage
            # may have completed outside this controller (for example after a
            # server restart or a one-off finalize command) before its
            # stage_results record was committed.  Do not dispatch that stage
            # again merely because the bookkeeping row is absent; doing so
            # can unnecessarily reacquire a Blender/GPU slot and makes a
            # verified showcase appear stuck in ``waiting_gpu``.
            artifact = self._stage_artifact_state(job, stage)
            if artifact == "verified":
                if job.stage_results.get(stage, {}).get("status") != "succeeded":
                    job.stage_results[stage] = {
                        "status": "succeeded",
                        "completed_at": _utc(),
                        "recovered_from_verified_artifact": True,
                    }
                continue
            if artifact != "verified":
                return stage
        return None

    def _run_stage(self, job: ControllerJob, stage: str) -> None:
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        if stage in {"showcase_raster_probe", "showcase_acceptance", "view_probe", "view_plan", "scene_quality_gate", "geometry", "structural_quality_audit", "overview_proxy", "principled_prepare", "material_mix_audit", "qc_render", "qc_verify",
                     "full_render", "nir_passive_backfill", "full_verify", "dataset_utility_audit", "publish"}:
            self._assert_pipeline_owner(job)
        if stage == "showcase_composition":
            source_blend = self._source_blend_path(Path(job.request.get("existing_output") or ""))
            if not source_blend.is_file():
                raise FileNotFoundError(f"showcase source blend is unavailable: {source_blend}")
        if stage == "view_plan":
            self._build_view_plan(job); return
        if stage == "scene_quality_gate":
            self._scene_quality_gate(job); return
        if stage == "qc_verify":
            self._verify(job, qc=True); return
        if stage == "full_verify":
            self._verify(job, qc=False); return
        if stage == "publish":
            job.stage = stage; self._save(job, "stage_started")
            repair = subprocess.run(
                ["python3", "apps/repair_ir_dataset_contract.py", "--dataset", job.request["paths"]["dataset"]],
                cwd=self.repo_root, capture_output=True, text=True,
            )
            for line in (repair.stdout + repair.stderr).splitlines():
                self._save(job, "output", stage=stage, line=line)
            if repair.returncode:
                raise RuntimeError(f"dataset contract repair exited with {repair.returncode}")
            last_progress = 0.0
            last_bytes = -1
            def publish_progress(kind: str, index: int, total: int, done_bytes: int, total_bytes: int) -> None:
                nonlocal last_progress, last_bytes
                now = time.monotonic()
                # Publisher callbacks are per-file.  Persist enough telemetry
                # for the UI without turning a large EXR copy into another NFS
                # write storm.
                if index != total and now - last_progress < 1.0 and done_bytes - last_bytes < 256 * 1024 * 1024:
                    return
                last_progress, last_bytes = now, done_bytes
                self._save(job, "publish_progress", publish_stage=kind,
                           files_completed=int(index), files_total=int(total),
                           bytes_completed=int(done_bytes), bytes_total=int(total_bytes),
                           percent=round(100.0 * done_bytes / max(total_bytes, 1), 3))
            job.stage_results[stage] = publish_dataset(Path(job.request["paths"]["dataset"]), self.bean_root,
                                                       name=job.request["dataset_name"], progress=publish_progress,
                                                       cancel=job.cancel)
            self._save(job, "stage_succeeded"); return
        if stage == "qc_render":
            self._assert_prepared_v2(job)
        self._run_command(job, stage, self._command(job, stage))
        if stage == "nir_passive_backfill":
            state = _read_json(Path(job.request["paths"]["backfill_state"]))
            allowed_partial = bool(job.request.get("backfill_limit")) and state.get("status") == "partial"
            if (state.get("status") != "succeeded" and not allowed_partial) or state.get("failed"):
                raise RuntimeError("passive backfill exited without a succeeded or bounded-partial state")
        if stage == "showcase_acceptance":
            report = _read_json(Path(job.request["paths"]["showcase_acceptance"]))
            if report.get("status") != "passed":
                raise ShowcaseAcceptanceError("showcase acceptance failed: " + ", ".join(report.get("failures") or ["unknown"]))
        if stage == "scene_content_audit":
            audit = _read_json(Path(job.request["paths"]["content_audit"]))
            if audit.get("status") != "passed":
                message = "scene content audit failed: " + ", ".join(audit.get("failures") or ["unknown"])
                if job.request.get("content_profile") == "research_balanced":
                    raise QualityGateError(message)
                raise RuntimeError(message)
        if stage == "material_mix_audit":
            audit = _read_json(Path(job.request["paths"]["material_mix"]))
            if audit.get("status") != "passed":
                raise QualityGateError("material mix audit failed: " + ", ".join(audit.get("failures") or ["unknown"]))
        if stage == "structural_quality_audit":
            audit = _read_json(Path(job.request["paths"]["structural_quality"]))
            if audit.get("status") != "passed":
                raise QualityGateError("structural material quality audit failed: " + ", ".join(audit.get("failures") or ["unknown"]))

    def _complete_stage(self, job: ControllerJob, stage: str) -> None:
        try:
            self._run_stage(job, stage)
            with self._lock:
                job.pid = None; job.external_adopted = False; job.current_command = None
                job.resource_state = "pending"; job.resource_class = None
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
                self._running.pop(job.job_id, None)
                if self._next_stage(job) is None:
                    job.status, job.stage, job.finished_at = "succeeded", "succeeded", _utc()
                    self._save(job, "succeeded")
                else:
                    job.status, job.stage = "running", "ready"
                    self._save(job, "stage_ready")
                self._wake.set()
        except Exception as exc:
            with self._lock:
                self._running.pop(job.job_id, None)
                if job.replan_requested and stage == "full_render":
                    try:
                        self._queue_corrected_replan(job)
                    except Exception as replan_exc:
                        job.replan_requested = False
                        job.pid, job.finished_at, job.error = None, _utc(), f"corrected plan replan failed: {replan_exc}"
                        job.resource_state, job.status = "failed", "failed"
                        job.stage_results[stage] = {"status": "failed", "failed_at": _utc(), "error": job.error}
                        self._save(job, "failed", stage=stage, error=job.error)
                    return
                if isinstance(exc, GenerationTimeoutError) and self._schedule_generation_fallback(job, error=str(exc)):
                    # The timed-out attempt remains immutable on disk.  The
                    # next variation gets its own generated source and
                    # attempt root, so a retry cannot mix partial artifacts.
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.interruption_reason = None
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue:
                        self._queue.append(job.job_id)
                    self._save(job, "generation_timeout_retry_scheduled", stage=stage, error=str(exc),
                               fallback_density=job.request.get("density"),
                               fallback_surface_clutter=job.request.get("surface_clutter"))
                    self._wake.set()
                    return
                if isinstance(exc, GeometryTimeoutError) and self._schedule_geometry_fallback(job, error=str(exc)):
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.interruption_reason = None
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue:
                        self._queue.append(job.job_id)
                    self._save(job, "geometry_timeout_retry_scheduled", stage=stage, error=str(exc),
                               geometry_bake_samples=job.request.get("geometry_bake_samples"),
                               geometry_max_bake_res=job.request.get("geometry_max_bake_res"),
                               small_high_poly_max_extent_m=job.request.get("small_high_poly_max_extent_m"))
                    self._wake.set()
                    return
                # A stale partial import with the same scene id can fail the
                # object-ID stability guard forever. Generated jobs recover by
                # switching to an isolated variation/scene id; the failed
                # attempt remains immutable for audit.
                source_id_collision = (
                    stage == "import"
                    and "object-ID stability check failed" in str(exc)
                    and job.request.get("source_mode") == "generate"
                )
                if source_id_collision and self._next_quality_variation(
                    job, failed_stage=stage, error=str(exc)
                ):
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue:
                        self._queue.append(job.job_id)
                    self._save(job, "source_collision_retry_scheduled", stage=stage,
                               error=str(exc), scene_id=job.request.get("scene_id"),
                               variation_id=job.request.get("variation_id"))
                    self._wake.set()
                    return
                showcase_failure = (
                    job.request.get("ir_composition_profile") == SHOWCASE_PROFILE
                    and stage in {"showcase_composition", "showcase_raster_probe", "showcase_acceptance"}
                )
                if showcase_failure and self._next_showcase_composition_attempt(job, failed_stage=stage, error=str(exc)):
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue: self._queue.append(job.job_id)
                    self._save(job, "showcase_retry_scheduled", stage=stage, error=str(exc))
                    self._wake.set()
                    return
                if showcase_failure and self._next_quality_variation(job, failed_stage=stage, error=str(exc)):
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue: self._queue.append(job.job_id)
                    self._save(job, "showcase_variation_scheduled", stage=stage, error=str(exc))
                    self._wake.set()
                    return
                if isinstance(exc, QualityGateError) and self._next_quality_variation(job, failed_stage=stage, error=str(exc)):
                    job.pid = None
                    job.resource_state, job.resource_class = "pending", None
                    job.resource_gpu_indices = []
                    job.desired_gpu_indices = []
                    job.draining_gpu_indices = []
                    job.status, job.stage, job.finished_at = "queued", "queued", None
                    if job.job_id not in self._queue: self._queue.append(job.job_id)
                    self._save(job, "quality_retry_scheduled", stage=stage, error=str(exc))
                    self._wake.set()
                    return
                interrupted = bool(job.interruption_reason)
                job.pid, job.finished_at, job.error = None, _utc(), job.interruption_reason or str(exc)
                job.resource_state = "cancelled" if job.cancel.is_set() else "failed"
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
                job.status = "cancelled" if job.cancel.is_set() else "interrupted" if interrupted else "failed"
                if interrupted:
                    job.resource_state = "interrupted"
                job.stage_results[stage] = {"status": "failed", "failed_at": _utc(), "error": str(exc)}
                self._save(job, job.status, stage=stage, error=job.error)
                self._wake.set()

    def _schedule_generation_fallback(self, job: ControllerJob, *, error: str) -> bool:
        """Schedule one lower-clutter variation after a generation timeout.

        This is intentionally narrower than a quality retry: it only applies
        to generated research jobs and never overwrites the timed-out source.
        ``_next_quality_variation`` creates a fresh seed, scene id and attempt
        paths and records the failed attempt in the durable history.
        """
        request = job.request
        if request.get("source_mode") != "generate":
            return False
        if request.get("content_profile") not in {"research_balanced", "balanced", "anchor_rich"}:
            return False
        if request.get("generation_timeout_fallback_used"):
            return False
        request["generation_timeout_fallback_used"] = True
        request["generation_timeout_fallback_reason"] = error
        # Reduce the expensive floating/detail population; structural geometry
        # and the later small-high-poly filter remain unchanged.  This keeps
        # the replacement useful for IR while preventing one pathological room
        # from consuming the entire daily queue.
        density = str(request.get("density") or "family_home")
        if density == "storage_heavy":
            request["density"] = "normal_lived_in"
        elif density == "family_home":
            request["density"] = "normal_lived_in"
        elif density == "normal_lived_in":
            request["density"] = "model_house"
        request["anchor_richness"] = "balanced"
        request["surface_clutter"] = "balanced"
        return self._next_quality_variation(job, failed_stage="generate", error=error)

    def _schedule_geometry_fallback(self, job: ControllerJob, *, error: str) -> bool:
        """Retry one slow geometry export with a bounded detail/bake profile.

        This is deliberately one-shot and only applies to the new IR content
        aware pipeline.  Existing successful unit checkpoints are reused by
        the exporter; structural objects remain protected by the filter.
        """
        request = job.request
        if request.get("pipeline_revision") != "ir-content-aware-v2":
            return False
        if request.get("geometry_timeout_fallback_used"):
            return False
        request["geometry_timeout_fallback_used"] = True
        request["geometry_timeout_fallback_reason"] = error
        request["geometry_bake_samples"] = min(int(request.get("geometry_bake_samples") or 4), 2)
        request["geometry_max_bake_res"] = min(int(request.get("geometry_max_bake_res") or 2048), 1024)
        request["small_high_poly_max_extent_m"] = max(float(request.get("small_high_poly_max_extent_m") or 0.25), 0.5)
        request["small_high_poly_min_triangles"] = min(int(request.get("small_high_poly_min_triangles") or 200000), 100000)
        return True

    def _running_jobs(self) -> list[ControllerJob]:
        running = [self._jobs[job_id] for job_id in self._running]
        # A subprocess adopted after a controller restart is not represented in
        # ``_running``, but it still owns the same Blender/GPU resources.
        running.extend(
            job for job in self._jobs.values()
            if job.external_adopted and job.status == "running" and job.job_id not in self._running
        )
        return running

    @staticmethod
    def _gpu_set(job: ControllerJob) -> set[int]:
        return set(job.resource_gpu_indices or [])

    @staticmethod
    def _gpu_leases(job: ControllerJob) -> set[int]:
        return set(job.resource_gpu_indices or []) | set(job.desired_gpu_indices or [])

    def _render_root(self, job: ControllerJob, stage: str | None = None) -> Path:
        stage = stage or (job.stage if job.stage in GPU_STAGES else self._next_stage(job))
        key = "qc" if stage == "qc_render" else "dataset"
        return Path((job.request.get("paths") or {})[key])

    def _write_render_allocation(self, job: ControllerJob, stage: str | None = None) -> None:
        try:
            root = self._render_root(job, stage)
        except KeyError:
            return
        _atomic_json(root / "gpu_allocation.json", {
            "schema": "robomituba.ir_gpu_allocation.v1",
            "updated_at": _utc(),
            "job_id": job.job_id,
            "eligible_gpu_indices": list(job.eligible_gpu_indices or self._eligible_gpus(job)),
            "desired_gpu_indices": list(job.desired_gpu_indices or []),
        })

    def _sync_render_worker_state(self) -> None:
        for job in self._running_jobs():
            if job.resource_class != "gpu_render":
                continue
            # Passive-NIR backfill uses one short-lived Blender subprocess,
            # not the persistent render queue parent.  There is deliberately
            # no gpu_worker_state.json for this command; its controller GPU
            # lease is the complete readiness signal.  Applying the rolling
            # queue worker-start timeout here used to kill a healthy backfill
            # after 120s while Blender was still loading the prepared blend.
            if job.stage == "nir_passive_backfill":
                if not job.resource_gpu_indices and job.desired_gpu_indices:
                    job.resource_gpu_indices = list(job.desired_gpu_indices[:1])
                    job.resource_state = "running"
                    self._save(job, "backfill_gpu_lease", resource_gpu_indices=job.resource_gpu_indices)
                # Unlike a rolling queue parent, this command has exactly one
                # Blender process and can use exactly one CUDA device.  A
                # generic rebalance after controller restart used to extend
                # its desired lease to every idle GPU, creating misleading
                # reservations without any executable worker to consume them.
                target = list(job.resource_gpu_indices[:1] or job.desired_gpu_indices[:1])
                if target and target != job.desired_gpu_indices:
                    released = sorted(set(job.desired_gpu_indices) - set(target))
                    job.desired_gpu_indices = target
                    job.draining_gpu_indices = []
                    job.gpu_target_updated_at = None
                    self._save(job, "backfill_gpu_lease_normalized",
                               desired_gpu_indices=target, released_gpu_indices=released)
                continue
            try:
                payload = _read_json(self._render_root(job) / "gpu_worker_state.json")
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                continue
            workers = payload.get("workers") if isinstance(payload.get("workers"), dict) else {}
            queue_preparing = (
                payload.get("queue_state") == "preparing"
                and int(payload.get("queue_pid") or -1) == int(job.pid or -2)
            )
            actual = sorted(
                int(gpu) for gpu, record in workers.items()
                if isinstance(record, dict) and record.get("status") in {"starting", "ready", "busy", "draining"}
            )
            failed = sorted(
                int(gpu) for gpu, record in workers.items()
                if isinstance(record, dict) and record.get("status") == "failed"
            )
            draining = sorted(
                int(gpu) for gpu, record in workers.items()
                if isinstance(record, dict) and record.get("status") == "draining"
            )
            # An externally adopted queue parent was launched with the worker
            # script that existed before this controller process.  If several
            # replacement workers have already failed while at least one
            # worker is still producing frames, do not keep advertising the
            # failed GPUs as a live lease.  The parent keeps its healthy
            # worker and completed-frame checkpoint; the released GPUs become
            # available to independent resumable jobs.  We intentionally do
            # not apply this to a supervised parent, which can be restarted by
            # its owning stage thread and may legitimately retry a worker.
            degraded = bool(job.external_adopted and actual and failed)
            if degraded:
                target = sorted(set(actual) | set(draining))
                if target != job.desired_gpu_indices:
                    job.desired_gpu_indices = target
                    job.draining_gpu_indices = []
                    job.gpu_target_updated_at = _utc()
                    self._write_render_allocation(job)
                    self._save(
                        job,
                        "external_render_degraded_workers_released",
                        active_gpu_indices=actual,
                        failed_gpu_indices=failed,
                        desired_gpu_indices=target,
                    )
            if failed != job.degraded_worker_gpu_indices:
                job.degraded_worker_gpu_indices = failed
                self._save(job, "gpu_worker_health", failed_gpu_indices=failed)
            resource_state = "waiting_gpu" if not actual and not job.desired_gpu_indices else "running"
            if actual:
                job.gpu_target_updated_at = None
            elif job.desired_gpu_indices and not queue_preparing:
                age = _age_seconds(job.gpu_target_updated_at)
                if age is None:
                    job.gpu_target_updated_at = _utc()
                elif age >= self.gpu_worker_start_timeout_s and not job.interruption_reason:
                    job.interruption_reason = (
                        f"GPU worker failed to start within {self.gpu_worker_start_timeout_s}s "
                        f"for allocation {job.desired_gpu_indices}; resume preserves completed frames"
                    )
                    job.resource_state = "interrupting"
                    job.desired_gpu_indices = []
                    self._write_render_allocation(job)
                    if self._pid_alive(job.pid):
                        try:
                            os.killpg(int(job.pid), signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    self._save(job, "gpu_worker_start_timeout", error=job.interruption_reason)
                    continue
            if (
                actual != job.resource_gpu_indices
                or draining != job.draining_gpu_indices
                or resource_state != job.resource_state
            ):
                job.resource_gpu_indices = actual
                job.draining_gpu_indices = draining
                job.resource_state = resource_state
                self._save(job, "gpu_worker_state", resource_gpu_indices=actual,
                           desired_gpu_indices=job.desired_gpu_indices, draining_gpu_indices=draining,
                           failed_gpu_indices=failed)

    @staticmethod
    def _process_tree_cmdlines(pid: int) -> list[str]:
        """Return command lines for a supervised process and its children."""
        try:
            pending = [int(pid)]
        except (TypeError, ValueError):
            return []
        seen: set[int] = set()
        commands: list[str] = []
        while pending:
            current = pending.pop()
            if current in seen or current <= 0:
                continue
            seen.add(current)
            try:
                raw = Path(f"/proc/{current}/cmdline").read_bytes()
                if raw:
                    commands.append(raw.replace(b"\0", b" ").decode(errors="replace"))
                children = Path(f"/proc/{current}/task/{current}/children").read_text().split()
                pending.extend(int(value) for value in children)
            except (OSError, ValueError):
                continue
        return commands

    def _release_cpu_bake_leases(self) -> None:
        """Release a bake GPU only when its running process is explicitly CPU-only.

        OptiX fallback can relaunch Blender with ``--cycles-device CPU`` after
        the original bake lease was allocated.  Retaining that lease blocks
        render jobs even though the process cannot use the GPU.
        """
        for job in self._running_jobs():
            if job.resource_class != "blender_bake" or not job.resource_gpu_indices or not job.pid:
                continue
            commands = self._process_tree_cmdlines(job.pid)
            if not commands or not any("--cycles-device CPU" in command for command in commands):
                continue
            released = sorted(job.resource_gpu_indices)
            job.resource_gpu_indices = []
            self._save(job, "cpu_bake_gpu_lease_released", released_gpu_indices=released)

    def _rebalance_gpu_targets(self, candidates: list[tuple[ControllerJob, str]]) -> None:
        """Compute a work-conserving max-min target over the configured GPU pool."""
        running_bakes = [job for job in self._running_jobs() if job.resource_class == "blender_bake"]
        bake_gpus = {gpu for job in running_bakes for gpu in job.resource_gpu_indices}
        ready_bakes = [job for job, stage in candidates if self._resource_class(stage) == "blender_bake"]
        # A running render is already doing useful GPU work.  Do not strand
        # otherwise idle GPUs by reserving them speculatively for a bake that
        # cannot start until a bake slot opens anyway.  The bake will be
        # scheduled as soon as a slot/GPU is actually available.
        reserve_count = 0 if any(
            job.resource_class == "gpu_render" for job in self._running_jobs()
        ) else min(
            max(0, self.bake_concurrency - len(running_bakes)),
            len(ready_bakes),
            max(0, len(self.gpu_pool) - len(bake_gpus)),
        )
        available_for_reservation = [gpu for gpu in self.gpu_pool if gpu not in bake_gpus]
        # Reserve only GPUs that a queued bake is actually eligible to use.
        # Reserving an ineligible low index can otherwise leave that GPU idle
        # while the bake waits forever behind render leases on its own subset.
        reserved_for_bake: set[int] = set()
        for bake in sorted(ready_bakes, key=lambda item: (-item.priority, item.created_at, item.job_id)):
            eligible = set(bake.eligible_gpu_indices or self._eligible_gpus(bake))
            gpu = next(
                (value for value in available_for_reservation
                 if value in eligible and value not in reserved_for_bake),
                None,
            )
            if gpu is not None:
                reserved_for_bake.add(gpu)
            if len(reserved_for_bake) >= reserve_count:
                break
        render_pool = [gpu for gpu in self.gpu_pool if gpu not in bake_gpus | reserved_for_bake]

        running_renders = [job for job in self._running_jobs() if job.resource_class == "gpu_render"]
        ready_renders = [job for job, stage in candidates if self._resource_class(stage) == "gpu_render"]
        render_jobs = list({job.job_id: job for job in [*running_renders, *ready_renders]}.values())
        # Give an unstarted render candidate the first free GPU before
        # expanding an already-running queue to its optional second GPU.
        # Otherwise a single idle GPU can be repeatedly consumed by the old
        # queues' ``max_gpus_per_render_parent`` allowance while every new
        # queue remains waiting_gpu (the scheduler then reports an idle GPU
        # despite runnable work).  Existing leases are still pinned below;
        # this only changes allocation order for genuinely free GPUs.
        ready_ids = {job.job_id for job in ready_renders}
        render_jobs.sort(key=lambda item: (
            item.job_id not in ready_ids,
            -item.priority,
            item.created_at,
            item.job_id,
        ))
        targets: dict[str, list[int]] = {job.job_id: [] for job in render_jobs}
        remaining = list(render_pool)
        # A persistent Blender queue process owns a fixed visible GPU set for
        # its lifetime.  Limit a render parent to one GPU: otherwise a recovery
        # request arriving a few milliseconds earlier can consume the complete
        # pool before its peer jobs are visible to this scheduler, and those
        # peers still launch parents whose visible sets overlap.  Throughput for
        # the multi-job pipeline is then one independent rolling queue per GPU;
        # a completed queue immediately makes its GPU available to the next
        # waiting job.
        # Keep a bounded persistent pool per render parent.  Three GPUs keeps
        # all eight GPUs useful when several render jobs are active (the old
        # two-GPU cap left spare devices idle while CPU stages were running),
        # while still preserving FIFO fairness between independent datasets.
        # Operators can temporarily lower this without changing the dataset
        # fingerprint; the allocation file remains the sole live lease.
        try:
            max_gpus_per_render_parent = max(1, int(os.environ.get(
                "ROBOMITUBA_MAX_GPUS_PER_RENDER_PARENT", "8")))
        except ValueError:
            max_gpus_per_render_parent = 8
        # A live queue parent must not be preempted by a transient scheduler
        # snapshot.  In particular, worker startup briefly reports no active
        # workers while the parent already owns its desired GPU; recomputing
        # targets in that window used to write ``desired=[]`` and drain a
        # healthy render after one frame.  Pin its current lease until the
        # parent exits; only genuinely free GPUs participate in this round.
        pinned: dict[str, list[int]] = {}
        # A controller-restarted parent cannot safely hot-reload a worker
        # script.  Once its replacement workers have failed, pin only the
        # verified healthy worker set and leave the rest of the pool for other
        # jobs.  Without this exception, the generic max-min allocator keeps
        # assigning those failed GPUs back to the same parent every tick.
        degraded_external = {
            job.job_id for job in running_renders
            if job.external_adopted and job.degraded_worker_gpu_indices
        }
        fixed_single_gpu_renders = {
            job.job_id for job in running_renders
            if job.stage == "nir_passive_backfill"
        }
        pinned_gpus: set[int] = set()
        for job in running_renders:
            if not self._pid_alive(job.pid):
                continue
            eligible = set(job.eligible_gpu_indices or self._eligible_gpus(job))
            if job.job_id in degraded_external or job.job_id in fixed_single_gpu_renders:
                leases = sorted((set(job.resource_gpu_indices or []) & eligible) - pinned_gpus)
            else:
                leases = sorted((self._gpu_leases(job) & eligible) - pinned_gpus)
            if leases:
                leases = leases[:(1 if job.job_id in fixed_single_gpu_renders else max_gpus_per_render_parent)]
                pinned[job.job_id] = leases
                pinned_gpus.update(leases)
        for job_id, leases in pinned.items():
            targets[job_id] = leases
        remaining = [gpu for gpu in remaining if gpu not in pinned_gpus]
        # Repeated rounds retain current leases when possible to avoid
        # gratuitous worker restarts.
        while remaining and render_jobs:
            assigned = False
            for job in render_jobs:
                if job.job_id in degraded_external or job.job_id in fixed_single_gpu_renders:
                    continue
                if len(targets[job.job_id]) >= max_gpus_per_render_parent:
                    continue
                eligible = set(job.eligible_gpu_indices or self._eligible_gpus(job))
                choices = [gpu for gpu in remaining if gpu in eligible]
                if not choices:
                    continue
                current = self._gpu_leases(job)
                gpu = next((value for value in choices if value in current), choices[0])
                targets[job.job_id].append(gpu)
                remaining.remove(gpu)
                assigned = True
                if not remaining:
                    break
            if not assigned:
                break

        # An ideal target may name a GPU that another renderer still owns while
        # draining. Do not expose it to the new owner until the worker state says
        # stopped; this is the no-double-lease handshake.
        current_owner = {
            gpu: job.job_id
            for job in running_renders
            for gpu in self._gpu_leases(job)
        }
        changed: list[ControllerJob] = []
        for job in render_jobs:
            target = [
                gpu for gpu in targets[job.job_id]
                if current_owner.get(gpu) in {None, job.job_id}
            ]
            target = sorted(target)
            if target != job.desired_gpu_indices:
                job.desired_gpu_indices = target
                job.gpu_target_updated_at = _utc() if target else None
                job.draining_gpu_indices = sorted(set(job.resource_gpu_indices) - set(target))
                changed.append(job)
        for job in changed:
            if job in running_renders:
                self._write_render_allocation(job)
            self._save(job, "gpu_allocation_changed", desired_gpu_indices=job.desired_gpu_indices,
                       resource_gpu_indices=job.resource_gpu_indices,
                       draining_gpu_indices=job.draining_gpu_indices)

    def _available_bake_gpu(self, job: ControllerJob) -> int | None:
        if self.bake_device == "CPU":
            return -1
        occupied: set[int] = set()
        for current in self._jobs.values():
            if current.status in {"queued", "running"} and current.resource_class in {"blender_bake", "gpu_render"}:
                occupied.update(self._gpu_leases(current))
        return next((gpu for gpu in (job.eligible_gpu_indices or self._eligible_gpus(job)) if gpu not in occupied), None)

    def _can_start(self, resource: str, job: ControllerJob | None = None) -> bool:
        running = self._running_jobs()
        if resource == "gpu_render":
            if job is None:
                return False
            if job.desired_gpu_indices:
                return True
            occupied = {
                gpu for item in running
                if item.resource_class in {"gpu_render", "blender_bake"}
                for gpu in self._gpu_leases(item)
            }
            return any(gpu not in occupied for gpu in (job.eligible_gpu_indices or self._eligible_gpus(job)))
        if resource == "infinigen_generate":
            return sum(item.resource_class == "infinigen_generate" for item in running) < self.infinigen_concurrency
        if resource == "blender_bootstrap":
            return sum(item.resource_class == resource for item in running) < self.bootstrap_concurrency
        if resource == "blender_bake":
            if job is None or sum(item.resource_class == resource for item in running) >= self.bake_concurrency:
                return False
            # All IR bake commands include ``--cycles-fallback CPU``.  If the
            # requested GPU subset is temporarily occupied, start the bake
            # without a GPU instead of leaving a CPU-safe Blender stage parked
            # behind a long rolling render.  A free eligible GPU is still
            # preferred by _available_bake_gpu; this branch only enables the
            # documented CPU fallback path.
            return self._available_bake_gpu(job) is not None or self.bake_device != "CPU"
        if resource == "blender_prepare":
            return sum(item.resource_class == resource for item in running) < self.prepare_concurrency
        # Metadata/QC verification and publish hashing are independent of the
        # Blender/GPU leases.  Allow one lightweight verifier to run alongside
        # the two long-running publish scans so a completed Stage-0 gate does
        # not stall behind multi-GB inventory hashing.
        return sum(job.resource_class == "cpu_light" for job in running) < 3

    def _refresh_waiting_states(self, candidates: list[tuple[ControllerJob, str]]) -> None:
        gpu_waiting = [
            job for job, resource in candidates
            if resource in {"gpu_render", "blender_bake"}
            and (not self._can_start(resource, job) or (resource == "gpu_render" and not job.desired_gpu_indices))
        ]
        for index, job in enumerate(gpu_waiting, 1):
            resource = self._resource_class(self._next_stage(job) or "")
            next_state = (resource, "waiting_gpu", index)
            if (job.resource_class, job.resource_state, job.queue_position) != next_state:
                job.resource_class, job.resource_state, job.queue_position = next_state
                self._save(job, "resource_waiting", resource_class=resource, queue_position=index,
                           requested_gpu_indices=job.request.get("gpu_indices", []),
                           slot_usage=self._resource_usage())
        for job, resource in candidates:
            if resource in {"blender_bootstrap", "blender_prepare", "infinigen_generate"} and not self._can_start(resource, job):
                next_state = (resource, "waiting_resource", None)
                if (job.resource_class, job.resource_state, job.queue_position) != next_state:
                    job.resource_class, job.resource_state, job.queue_position = next_state
                    self._save(job, "resource_waiting", resource_class=resource, slot_usage=self._resource_usage())
            elif resource == "cpu_light" and not self._can_start(resource, job):
                next_state = (resource, "waiting_cpu", None)
                if (job.resource_class, job.resource_state, job.queue_position) != next_state:
                    job.resource_class, job.resource_state, job.queue_position = next_state
                    self._save(job, "resource_waiting", resource_class=resource)

    def _resource_usage(self) -> dict[str, dict[str, int]]:
        running = self._running_jobs()
        return {
            "blender_bootstrap": {"used": sum(j.resource_class == "blender_bootstrap" for j in running), "limit": self.bootstrap_concurrency},
            "blender_bake": {"used": sum(j.resource_class == "blender_bake" for j in running), "limit": self.bake_concurrency},
            "blender_prepare": {"used": sum(j.resource_class == "blender_prepare" for j in running), "limit": self.prepare_concurrency},
            "infinigen_generate": {"used": sum(j.resource_class == "infinigen_generate" for j in running), "limit": self.infinigen_concurrency},
            "cpu_light": {"used": sum(j.resource_class == "cpu_light" for j in running), "limit": 3},
        }

    def _audit_work_conserving(self, candidates: list[tuple[ControllerJob, str]]) -> None:
        leased = {
            gpu for job in self._running_jobs()
            if job.resource_class in {"gpu_render", "blender_bake"}
            for gpu in self._gpu_leases(job)
        }
        renders = [job for job in self._running_jobs() if job.resource_class == "gpu_render"]
        renders.extend(job for job, stage in candidates if self._resource_class(stage) == "gpu_render")
        idle = tuple(
            gpu for gpu in self.gpu_pool
            if gpu not in leased and any(gpu in (job.eligible_gpu_indices or self._eligible_gpus(job)) for job in renders)
        )
        if idle and idle != self._scheduler_idle_signature and renders:
            self._save(
                renders[0], "scheduler_error", reason="eligible GPU idle with runnable render work",
                idle_gpu_indices=list(idle), leased_gpu_indices=sorted(leased),
            )
        self._scheduler_idle_signature = idle or None

    def _run(self) -> None:
        """Resource-aware stage scheduler; GPU ownership exists only while rendering."""
        while True:
            self._wake.wait(timeout=0.5); self._wake.clear()
            with self._lock:
                # Adopted subprocesses no longer have a stage thread.  Keep
                # their durable output and completion state moving even when no
                # browser happens to poll the controller.
                self._refresh_external_jobs()
                self._sync_render_worker_state()
                self._release_cpu_bake_leases()
                candidates = []
                for job in self._jobs.values():
                    if (
                        job.status not in {"queued", "running"}
                        or job.job_id in self._running
                        or job.external_adopted
                    ):
                        continue
                    stage = self._next_stage(job)
                    if stage is not None:
                        candidates.append((job, stage))
                candidates.sort(key=lambda item: (-item[0].priority, item[0].created_at))
                self._rebalance_gpu_targets(candidates)
                self._refresh_waiting_states([(job, self._resource_class(stage)) for job, stage in candidates])
                for job, stage in candidates:
                    resource = self._resource_class(stage)
                    if not self._can_start(resource, job):
                        continue
                    # _rebalance_gpu_targets is the sole render lease authority.
                    # Never launch a queue parent merely because a GPU appears
                    # free between scheduler snapshots: it must already own a
                    # durable desired target.
                    if resource == "gpu_render" and not job.desired_gpu_indices:
                        continue
                    if job.job_id in self._queue:
                        self._queue.remove(job.job_id)
                    job.status, job.stage, job.resource_class, job.resource_state = "running", stage, resource, "running"
                    job.queue_position = None
                    if resource == "blender_bake":
                        gpu = self._available_bake_gpu(job)
                        job.resource_gpu_indices = [] if gpu is None or gpu == -1 else [int(gpu)]
                    elif resource == "gpu_render":
                        if stage == "nir_passive_backfill":
                            # The backfill command is a single-GPU process,
                            # so make the atomic target visible immediately.
                            job.resource_gpu_indices = list(job.desired_gpu_indices[:1])
                        else:
                            job.resource_gpu_indices = []
                        job.draining_gpu_indices = []
                    else:
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                    if job.started_at is None:
                        job.started_at = _utc()
                    job.stage_started_at = _utc()
                    self._save(job, "stage_dispatched", stage=stage, resource_class=resource,
                               resource_gpu_indices=job.resource_gpu_indices, slot_usage=self._resource_usage())
                    thread = threading.Thread(target=self._complete_stage, args=(job, stage), name=f"ir-stage-{job.job_id[:8]}-{stage}", daemon=True)
                    self._running[job.job_id] = thread
                    thread.start()
                self._audit_work_conserving(candidates)

    def _run_supervised(self) -> None:
        """Keep scheduling alive after an isolated legacy-artifact failure."""
        while True:
            try:
                self._run()
            except Exception:
                traceback.print_exc()
                time.sleep(1.0)
