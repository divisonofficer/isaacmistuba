"""Durable, localhost-only orchestration for the Blender Principled IR pipeline.

The controller deliberately owns no renderer code.  It validates a compact job
request and invokes the repository CLIs with an explicit argv list, one pipeline
at a time.  This keeps it independent from the OpticalNav render daemon.
"""
from __future__ import annotations

import json
import hashlib
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mitsuba_converter.ir_dataset_publish import publish_dataset
from mitsuba_converter.ir_render_plan import write_render_plan
from mitsuba_converter.ir_illumination import load_bank
from mitsuba_converter.ir_material_mix import PROFILE as METAL_PROFILE

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
ARCHETYPES = {"apartment", "office", "single_room"}
ROOM_TYPES = {
    "living-room", "bedroom", "kitchen", "bathroom", "dining-room", "closet",
    "hallway", "garage", "balcony", "utility", "staircase-room", "warehouse",
    "office", "meeting-room", "open-office", "break-room", "restroom",
    "factory-office",
}
DENSITIES = {"model_house", "normal_lived_in", "family_home", "storage_heavy"}
IR_GRAPH_DEFAULTS = {
    "graph_max_nodes": 70,
    "graph_heading_count": 24,
    "graph_min_node_spacing": 0.25,
    "graph_robot_radius": 0.30,
}
STAGES = ("generate", "import", "scene_content_audit", "navigation_compile", "view_probe", "material_extract", "material_canonicalize", "lighting_asset_audit", "view_plan", "scene_quality_gate", "geometry", "structural_rematerialize", "overview_proxy", "principled_prepare", "material_mix_audit", "qc_render", "qc_verify", "full_render", "full_verify", "dataset_utility_audit", "publish")
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
GPU_STAGES = frozenset({"qc_render", "full_render"})
INFINIGEN_GENERATE_STAGES = frozenset({"generate"})
BLENDER_BOOTSTRAP_STAGES = frozenset({"import"})
BLENDER_BAKE_STAGES = frozenset({"geometry"})
BLENDER_PREPARE_STAGES = frozenset({"overview_proxy", "principled_prepare"})
CPU_LIGHT_STAGES = frozenset(
    set(STAGES) - GPU_STAGES - INFINIGEN_GENERATE_STAGES
    - BLENDER_BOOTSTRAP_STAGES - BLENDER_BAKE_STAGES - BLENDER_PREPARE_STAGES
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


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _gpu_pool_env(name: str = "ROBOMITUBA_IR_GPU_INDICES", default: str = "0,1,2,3") -> list[int]:
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
    finished_at: str | None = None
    error: str | None = None
    pid: int | None = None
    current_command: list[str] | None = None
    stage_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    external_adopted: bool = False
    resource_class: str | None = None
    resource_state: str = "pending"
    queue_position: int | None = None
    resource_gpu_indices: list[int] = field(default_factory=list)
    desired_gpu_indices: list[int] = field(default_factory=list)
    draining_gpu_indices: list[int] = field(default_factory=list)
    eligible_gpu_indices: list[int] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def payload(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "request": self.request, "status": self.status, "stage": self.stage,
            "priority": self.priority, "created_at": self.created_at, "updated_at": self.updated_at,
            "started_at": self.started_at, "finished_at": self.finished_at, "error": self.error,
            "pid": self.pid, "current_command": self.current_command, "stage_results": self.stage_results,
            "resource_class": self.resource_class, "resource_state": self.resource_state,
            "queue_position": self.queue_position, "resource_gpu_indices": list(self.resource_gpu_indices or []),
            "desired_gpu_indices": list(self.desired_gpu_indices or []),
            "draining_gpu_indices": list(self.draining_gpu_indices or []),
            "eligible_gpu_indices": list(self.eligible_gpu_indices or []),
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
        self.bake_device = str(os.environ.get("ROBOMITUBA_BLENDER_BAKE_DEVICE", "OPTIX")).upper()
        if self.bake_device not in {"CPU", "CUDA", "OPTIX"}:
            raise ValueError("ROBOMITUBA_BLENDER_BAKE_DEVICE must be CPU, CUDA, or OPTIX")
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._restore()
        self._thread = threading.Thread(target=self._run, name="ir-dataset-controller", daemon=True)
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
                job.eligible_gpu_indices = list(job.eligible_gpu_indices or [])
                self._upgrade_request(job.request)
                job.eligible_gpu_indices = self._eligible_gpus(job)
                # stdout cannot be reattached after a server restart, but a
                # surviving importer can still be adopted for lifecycle and
                # resumable-artifact monitoring rather than being hidden as a
                # misleading terminal job.
                if job.status == "running":
                    live = self._external_pids(job)
                    if live:
                        job.status, job.pid = "running", live[0]
                        job.external_adopted, job.error = True, None
                        job.resource_class = self._resource_class(job.stage)
                        job.resource_state, job.queue_position = "running", None
                        self._save(job, "external_process_adopted", stage=job.stage, pids=live)
                    else:
                        job.status, job.stage, job.error = "interrupted", "interrupted", "controller restarted while subprocess was active"
                        job.finished_at = _utc()
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                        self._save(job, "interrupted")
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
        request.setdefault("paired_fraction", 0.25)
        request.setdefault("pipeline_revision", "legacy-strict-import-v1")
        request.setdefault("import_profile", "strict-pbr-v1")
        original = sorted({int(value) for value in request.get("gpu_indices") or []})
        if request.get("pipeline_revision") in {"ir-bootstrap-gpu-v1", "ir-content-aware-v2"}:
            request.setdefault("requested_gpu_indices", original)
            request["gpu_indices"] = list(self.gpu_pool)
        elif any(value not in self.gpu_pool for value in original):
            request.setdefault("requested_gpu_indices", original)
            request["gpu_indices"] = [value for value in original if value in self.gpu_pool]
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
            paths.setdefault("structural_rematerialization", str(Path(pipeline) / "structural_rematerialization.json"))

    @staticmethod
    def _resource_class(stage: str) -> str:
        if stage in GPU_STAGES:
            return "gpu_render"
        if stage in INFINIGEN_GENERATE_STAGES:
            return "infinigen_generate"
        if stage in BLENDER_BOOTSTRAP_STAGES:
            return "blender_bootstrap"
        if stage in BLENDER_BAKE_STAGES:
            return "blender_bake"
        if stage in BLENDER_PREPARE_STAGES:
            return "blender_prepare"
        return "cpu_light"

    @staticmethod
    def _pipeline(job: ControllerJob) -> list[str]:
        if job.request.get("source_mode") == "augmentation":
            return ["lighting_asset_audit", "view_plan", "overview_proxy", "principled_prepare", "qc_render", "qc_verify", "full_render", "full_verify", "publish"]
        stages = list(STAGES[1:])
        if not job.request.get("structural_rematerialize"):
            stages = [stage for stage in stages if stage != "structural_rematerialize"]
        if not job.request.get("illumination_diversity"):
            stages = [stage for stage in stages if stage != "lighting_asset_audit"]
        if job.request.get("pipeline_revision") != "ir-content-aware-v2":
            stages = [stage for stage in stages if stage not in {"scene_content_audit", "view_probe", "scene_quality_gate", "material_mix_audit", "dataset_utility_audit"}]
        if job.request.get("content_profile") != "research_balanced" or job.request.get("source_mode") != "generate":
            stages = [stage for stage in stages if stage not in {"scene_quality_gate", "material_mix_audit"}]
        return (["generate"] if job.request.get("source_mode") == "generate" else []) + stages

    def _active_import_pids(self, job: ControllerJob) -> list[int]:
        """Find an orphan importer still writing this exact source scene."""
        raw_source = job.request.get("existing_output")
        if not raw_source:
            return []
        source = str(Path(str(raw_source)).resolve())
        matches: list[int] = []
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                pid = int(proc.name)
                command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
            except (OSError, ValueError):
                continue
            if "apps/run_infinigen_import.sh" in command and source in command:
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
        return [job.pid] if self._pid_alive(job.pid) else []

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
        return False

    def _resolve_existing(self, value: Any) -> Path:
        candidate = (self.data_root / str(value or "")).resolve()
        if not _inside(self.data_root, candidate) or not candidate.is_dir() or not (candidate / "scene.blend").is_file():
            raise ValueError("existing_output must name a generated output with scene.blend")
        return candidate

    def _eligible_gpus(self, job: ControllerJob) -> list[int]:
        requested = {int(value) for value in job.request.get("gpu_indices") or []}
        return [gpu for gpu in self.gpu_pool if gpu in requested]

    def _import_dir(self, request: dict[str, Any]) -> Path:
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
        if mode not in {"generate", "existing", "augmentation"}:
            raise ValueError("source_mode must be generate, existing, or augmentation")
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
        request: dict[str, Any] = {
            "source_mode": mode, "dataset_name": dataset_name,
            "gpu_indices": list(self.gpu_pool), "requested_gpu_indices": gpu_indices,
            "pipeline_revision": "ir-content-aware-v2", "import_profile": "ir-bootstrap-v1",
            "width": int(raw.get("width", 684)), "height": int(raw.get("height", 512)),
            "fov": float(raw.get("fov", 60.0)), "rgb_spp": int(raw.get("rgb_spp", 4000)),
            "nir_spp": int(raw.get("nir_spp", 2000)), "flash_energy_scale": float(raw.get("flash_energy_scale", 1.0)),
            "ambient_fill_energy_scale": float(raw.get("ambient_fill_energy_scale", 1.0)),
            "illumination_diversity": bool(raw.get("illumination_diversity", False)),
            "paired_fraction": float(raw.get("paired_fraction", 0.25)),
            "pose_budget": int(raw.get("pose_budget", 400)),
            "camera_policy": str(raw.get("camera_policy") or "content_aware_v2"),
            "content_profile": str(raw.get("content_profile") or "balanced"),
            "material_mix_profile": str(raw.get("material_mix_profile") or METAL_PROFILE),
            "max_quality_variations": int(raw.get("max_quality_variations", 4)),
            "adaptive_pose_budget": bool(raw.get("adaptive_pose_budget", True)),
            "sparse_negative_fraction": float(raw.get("sparse_negative_fraction", 0.15)),
            "max_headings_per_node": int(raw.get("max_headings_per_node", 6)),
            "graph_max_nodes": int(raw.get("graph_max_nodes", IR_GRAPH_DEFAULTS["graph_max_nodes"])),
            "graph_heading_count": int(raw.get("graph_heading_count", IR_GRAPH_DEFAULTS["graph_heading_count"])),
            "graph_min_node_spacing": float(raw.get("graph_min_node_spacing", IR_GRAPH_DEFAULTS["graph_min_node_spacing"])),
            "graph_robot_radius": float(raw.get("graph_robot_radius", IR_GRAPH_DEFAULTS["graph_robot_radius"])),
            "structural_rematerialize": bool(raw.get("structural_rematerialize", False)),
        }
        if request["width"] < 1 or request["height"] < 1 or request["rgb_spp"] < 1 or request["nir_spp"] < 1 or not 1 <= request["fov"] < 179 or not 100 <= request["pose_budget"] <= 2000:
            raise ValueError("invalid render dimensions, samples, or horizontal FOV")
        if not 0.05 <= request["paired_fraction"] <= 1.0:
            raise ValueError("paired fraction must be in [0.05, 1.0]")
        if request["camera_policy"] not in {"content_aware_v2", "coverage_v1"} or request["content_profile"] not in {"balanced", "anchor_rich", "structural", "research_balanced"}:
            raise ValueError("invalid camera or content policy")
        if request["material_mix_profile"] != METAL_PROFILE or not 1 <= request["max_quality_variations"] <= 4:
            raise ValueError("invalid material-mix profile or quality variation limit")
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
            generated_source = self.data_root / f"kr_{effective_seed}_{archetype}{suffix}" / stage
            generated_scene_id = f"infinigen_{archetype}{suffix}_{seed}_v{variation_id:02d}"
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
            request["scene_id_base"] = request["scene_id"]
        elif mode == "existing":
            source = self._resolve_existing(raw.get("existing_output"))
            existing_room_type = str(raw.get("room_type") or "generic").replace("_", "-")
            if existing_room_type != "generic" and existing_room_type not in ROOM_TYPES:
                raise ValueError("invalid existing scene room type")
            request.update({"existing_output": str(source), "room_type": existing_room_type,
                            "scene_id": self._safe_name(raw.get("scene_id") or f"infinigen_{dataset_name}", "scene_id")})
        else:
            legacy_name = self._safe_name(raw.get("legacy_dataset_name"), "legacy_dataset_name")
            candidates = [self.bean_root / legacy_name, self.work_root / legacy_name, self.repo_root / "out" / "ir_dataset" / legacy_name]
            legacy = next((item.resolve() for item in candidates if (item / "ir_geometry" / "ir_geometry_profile.json").is_file()), None)
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
            "content_audit": str(attempt_root / "scene_content_audit.json"),
            "illumination_audit": str(attempt_root / "illumination_asset_audit.json"),
            "scene_quality": str(attempt_root / "scene_content_quality.json"),
            "material_mix": str(attempt_root / "material_mix_quality.json"),
            "structural_rematerialization": str(attempt_root / "structural_rematerialization.json"),
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

    def list_jobs(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_external_jobs()
            jobs = [self._payload(job) for job in self._jobs.values()]
            jobs.sort(key=lambda item: (item["status"] != "running", -item["priority"], item["created_at"]))
            active = next(iter(self._running), None)
            gpu_queue = [job.job_id for job in self._jobs.values() if job.resource_state == "waiting_gpu"]
            return {"jobs": jobs, "queue": list(self._queue), "gpu_queue": gpu_queue, "active_job_id": active}

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

        fingerprint = tuple(stat_token(path) for path in (log_path, state_root, plan_path, *rolling_states))
        cached = self._stage_progress_cache.get(job.job_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        completed = len(list(state_root.glob("*.json"))) if state_root.is_dir() else 0
        total = 0
        log_messages: list[str] = []
        if log_path.is_file():
            # blender_export_scene emits this once before any unit starts.
            pattern = re.compile(r"\[export\] exporting\s+(\d+)\s+units")
            try:
                for serialized in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        message = json.loads(serialized).get("line")
                    except (ValueError, TypeError):
                        continue
                    message = str(message or "")
                    log_messages.append(message)
                    match = pattern.search(message)
                    if match:
                        total = int(match.group(1))
            except OSError:
                pass
        progress: dict[str, dict[str, Any]] = {}
        if job.request.get("source_mode") == "generate" and log_messages:
            phase_pattern = re.compile(r"\[logging\] \[INFO\] \| \[([^]]+)\]( finished in .*)?$")
            annealing_pattern = re.compile(r"\[annealing\].*?\bit=(\d+)/(\d+).*?\bn=(\d+)")
            completed_phases: set[str] = set()
            current_phase: str | None = None
            local: tuple[int, int, int] | None = None
            for message in log_messages:
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
            estimated = min(100.0, sum(INFINIGEN_PHASE_WEIGHTS[name] for name in completed_phases))
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
            pids = self._external_pids(job)
            if pids:
                if job.pid != pids[0]:
                    job.pid = pids[0]
                    self._save(job, "external_process_heartbeat", stage=job.stage, pids=pids)
                continue
            if self._external_stage_completed(job):
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
            job.error = "adopted external process exited; Resume safely validates and continues from committed artifacts"
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
            self._apply_recovery(job, rerun_from=rerun_from if mode == "custom" else None,
                                 insert_stages=list(insert_stages or []))
            return self._payload(job)

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
            if job.status != "queued": raise ValueError("only queued jobs can change priority")
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

    def status(self) -> dict[str, Any]:
        return {"service": "ir-dataset-controller", "serial_pipeline": False, "work_root": str(self.work_root),
                "gpu_pool": list(self.gpu_pool),
                "resource_config": {
                    "blender_bootstrap": {"concurrency": self.bootstrap_concurrency},
                    "blender_bake": {"concurrency": self.bake_concurrency, "device": self.bake_device},
                    "blender_prepare": {"concurrency": self.prepare_concurrency},
                    "usage": self._resource_usage(),
                },
                "gpu_inventory": self.gpu_inventory(), **self.list_jobs()}

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
        scene = self.scene_root / str(r.get("scene_id") or "")
        if stage == "generate":
            return "verified" if Path(str(r.get("existing_output") or ""), "scene.blend").is_file() else "missing"
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
                if r.get("pipeline_revision") == "ir-content-aware-v2" and r.get("source_mode") != "augmentation":
                    probe = _read_json(Path(p["candidate_visibility"]))
                    valid = valid and plan.get("source_visibility_digest") == probe.get("probe_digest")
                return "verified" if valid else "stale"
            except (KeyError, OSError, ValueError, json.JSONDecodeError): return "missing"
        if stage == "scene_quality_gate":
            try:
                quality = _read_json(Path(p["scene_quality"]))
                return "verified" if quality.get("status") == "passed" else "stale"
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
                    contract.get("schema") == "robomituba.ir_principled_material_contract.v2"
                    and contract.get("contract_version") == "blender42-principled-metallic-roughness-v2"
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
        job.eligible_gpu_indices = self._eligible_gpus(job)
        job.cancel = threading.Event()
        if job.job_id not in self._queue: self._queue.append(job.job_id)
        self._save(job, "recovery_queued", rerun_from=start, insert_stages=insert_stages)
        self._wake.set()

    def _build_view_plan(self, job: ControllerJob) -> None:
        path = Path(job.request["paths"]["render_plan"])
        graph = self.scene_root / job.request["scene_id"] / "viewpoint_graph.json"
        plan = write_render_plan(path, graph, requested_pose_count=int(job.request["pose_budget"]),
                                 seed=int(job.request.get("effective_scene_seed") or job.request.get("seed") or 20260812),
                                 scene_id=str(job.request["scene_id"]),
                                 visibility_path=Path(job.request["paths"]["candidate_visibility"])
                                 if job.request.get("camera_policy") == "content_aware_v2" else None,
                                 adaptive_budget=bool(job.request.get("adaptive_pose_budget")),
                                 max_headings_per_node=int(job.request.get("max_headings_per_node", 6)),
                                 sparse_fraction=float(job.request.get("sparse_negative_fraction", 0.15)),
                                 illumination=(load_bank(self.repo_root) if job.request.get("illumination_diversity") else None),
                                 paired_fraction=float(job.request.get("paired_fraction", 0.25)))
        qc_groups = []
        for group in plan["groups"]:
            qc_groups.append({**group, "poses": list(group["poses"])[:2]})
        qc_core = {key: value for key, value in plan.items() if key not in {"groups", "render_plan_id", "render_plan_digest"}}
        qc_core["groups"] = qc_groups
        from mitsuba_converter.ir_render_plan import stable_digest
        qc_digest = stable_digest(qc_core)
        qc_plan = {**qc_core, "render_plan_id": qc_digest[:16], "render_plan_digest": qc_digest,
                   "parent_render_plan_digest": plan["render_plan_digest"], "stage": "qc"}
        _atomic_json(Path(job.request["paths"]["qc_render_plan"]), qc_plan)
        job.stage_results["view_plan"] = {
            "status": "succeeded", "completed_at": _utc(), "requested_pose_count": plan["requested_pose_count"],
            "actual_pose_count": plan["actual_pose_count"], "candidate_pose_count": plan["candidate_pose_count"],
            "clamped": plan["clamped"], "lighting_group_count": plan["lighting_group_count"],
            "render_plan_digest": plan["render_plan_digest"],
        }
        if plan.get("illumination"):
            job.stage_results["view_plan"]["illumination"] = dict(plan["illumination"])
        self._save(job, "view_plan_succeeded", **job.stage_results["view_plan"])

    def _scene_quality_gate(self, job: ControllerJob) -> None:
        """Gate density and viewpoint richness before the expensive Stage-1 bake."""
        p = job.request["paths"]
        content, plan = _read_json(Path(p["content_audit"])), _read_json(Path(p["render_plan"]))
        poses = [pose for group in plan.get("groups") or [] for pose in group.get("poses") or []]
        utilities = [pose.get("utility") or {} for pose in poses]
        visible = sorted(float(item.get("visible_object_count") or 0) for item in utilities)
        median = visible[len(visible) // 2] if visible else 0.0
        sparse = sum(item.get("utility_class") == "sparse_negative" for item in utilities) / max(1, len(utilities))
        footprint = content.get("room_footprint") or {}
        area = float(footprint.get("area_m2") or 0.0)
        nonstructural = int(content.get("nonstructural_object_count") or 0)
        per_m2 = nonstructural / area if area > 0 else 0.0
        failures = []
        if content.get("status") != "passed": failures.append("scene_content_contract")
        if per_m2 < 3.0: failures.append("nonstructural_density_below_3_per_m2")
        if median < 2.0: failures.append("visible_object_median_below_2")
        if sparse > 0.150001: failures.append("sparse_pose_fraction_above_15pct")
        report = {"schema": "robomituba.ir_scene_content_quality.v1", "profile": "research_balanced",
                  "status": "failed" if failures else "passed", "attempt": int(job.request.get("variation_id") or 0),
                  "logical_seed": job.request.get("logical_seed"), "effective_seed": job.request.get("effective_scene_seed"),
                  "room_area_m2": area or None, "nonstructural_object_count": nonstructural,
                  "nonstructural_objects_per_m2": round(per_m2, 6) if area else None,
                  "selected_pose_count": len(poses), "selected_visible_object_median": median,
                  "selected_sparse_pose_fraction": round(sparse, 6), "failures": failures}
        report["quality_digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic_json(Path(p["scene_quality"]), report)
        job.stage_results["scene_quality_gate"] = {"status": "succeeded" if not failures else "failed", **report}
        self._save(job, "scene_quality_checked", **report)
        if failures:
            raise QualityGateError("scene quality gate failed: " + ", ".join(failures))

    def _next_quality_variation(self, job: ControllerJob, *, failed_stage: str, error: str) -> bool:
        """Move a generated Research-balanced job to its next isolated attempt."""
        r = job.request
        if r.get("source_mode") != "generate" or r.get("content_profile") != "research_balanced":
            return False
        attempt_index = int(r.get("quality_attempt_index") or 0)
        limit = int(r.get("max_quality_variations") or 4)
        history = list(r.get("quality_attempts") or [])
        history.append({"attempt_index": attempt_index, "variation_id": r.get("variation_id"),
                        "scene_id": r.get("scene_id"), "failed_stage": failed_stage, "error": error,
                        "at": _utc(), "paths": dict(r.get("paths") or {})})
        if attempt_index + 1 >= limit:
            r["quality_attempts"] = history
            return False
        variation = int(r.get("variation_id") or 0) + 1
        r["quality_attempt_index"] = attempt_index + 1
        r["quality_attempts"] = history
        r["variation_id"] = variation
        r["effective_scene_seed"] = _effective_scene_seed(str(r["logical_seed"]), str(r["room_type"]), variation)
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
            "illumination_audit": str(attempt / "illumination_asset_audit.json"), "scene_quality": str(attempt / "scene_content_quality.json"),
            "material_mix": str(attempt / "material_mix_quality.json"), "overview_proxy": str(attempt / "overview_proxy"),
            "dataset": dataset, "published": published,
        }
        job.stage_results = {}
        job.error = None
        self._save(job, "quality_variation_queued", variation_id=variation, attempt_index=attempt_index + 1,
                   failed_stage=failed_stage, error=error)
        return True

    def _command(self, job: ControllerJob, stage: str) -> list[str]:
        r, p = job.request, job.request["paths"]
        source = Path(r.get("existing_output") or "")
        if stage == "generate":
            cmd = ["python3", "scripts/infinigen_wizard.py", "--archetype", r["archetype"], "--density", r["density"], "--stage", r["generation_stage"],
                   "--seed", str(r.get("effective_scene_seed") or r["seed"]), "--logical-seed", str(r.get("logical_seed") or r["seed"]),
                   "--variation-id", str(r.get("variation_id", 0)), "--anchor-richness", str(r.get("anchor_richness") or "balanced"),
                   "--surface-clutter", str(r.get("surface_clutter") or "balanced"), "--scene-id", r["scene_id"], "--no-import", "--yes"]
            if r["archetype"] == "single_room": cmd += ["--room-type", r["room_type"]]
            return cmd
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
                    "--source-blend", str(source / "scene.blend"), "--registry-root", str(self.pipeline_root),
                    "--registry-root", str(self.bean_root)]
        if stage == "view_probe":
            return ["python3", "apps/probe_ir_candidate_visibility.py", "--graph",
                    str(self.scene_root / r["scene_id"] / "viewpoint_graph.json"), "--authoring-map",
                    str(self.scene_root / r["scene_id"] / "authoring_map.json"), "--out", p["candidate_visibility"],
                    "--fov", str(r["fov"])]
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
        blend = source / "scene.blend"
        if stage == "geometry":
            cmd = ["python3", "apps/build_ir_geometry_profile.py", "--source-scene-dir", str(scene),
                   "--source-blend", str(blend), "--out", p["geometry"], "--profile", "ir_semantic_lod_v1",
                   "--cycles-device", self.bake_device, "--cycles-fallback", "CPU"]
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
            if r.get("illumination_diversity"):
                cmd += ["--illumination-manifest", str(self.repo_root / "configs" / "ir_lighting" / "illumination_diversity_v1.json")]
            if r.get("structural_rematerialize"):
                cmd += ["--structural-material-manifest", p["structural_rematerialization"]]
            return cmd
        eligible = self._eligible_gpus(job)
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
        if stage == "qc_render":
            return common + ["--out", p["qc"], "--frame-plan", p["qc_render_plan"], "--width", "342", "--height", "256", "--rgb-spp", "64", "--nir-spp", "64"]
        if stage == "full_render":
            return common + ["--out", p["dataset"], "--frame-plan", p["render_plan"], "--width", str(r["width"]), "--height", str(r["height"]), "--rgb-spp", str(r["rgb_spp"]), "--nir-spp", str(r["nir_spp"])]
        raise ValueError(f"no command for stage {stage}")

    def _run_command(self, job: ControllerJob, stage: str, command: list[str]) -> None:
        job.stage, job.current_command = stage, command; self._save(job, "stage_started", command=command)
        if stage in GPU_STAGES:
            self._write_render_allocation(job, stage)
        environment = os.environ.copy()
        # Controller subprocesses must work whether or not the developer shell
        # has editable modules installed.  Keep existing PYTHONPATH entries but
        # put this checkout's source packages first.
        source_paths = [str(self.repo_root / "modules" / name / "src") for name in
                        ("mitsuba_converter", "robomituba_bridge", "navigation_dataset")]
        environment["PYTHONPATH"] = os.pathsep.join(source_paths + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else []))
        if stage in BLENDER_BOOTSTRAP_STAGES or stage in BLENDER_PREPARE_STAGES or stage in INFINIGEN_GENERATE_STAGES:
            environment["CUDA_VISIBLE_DEVICES"] = ""
            if stage in BLENDER_BOOTSTRAP_STAGES:
                environment["ROBOMITUBA_MATERIALIZE_PROGRESS"] = "1"
        elif stage in BLENDER_BAKE_STAGES and job.resource_gpu_indices:
            assigned = job.resource_gpu_indices[0]
            environment["CUDA_VISIBLE_DEVICES"] = str(assigned)
            environment["ROBOMITUBA_ASSIGNED_BAKE_GPU"] = str(assigned)
        process = self._runner(command, cwd=self.repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1, start_new_session=True, env=environment)
        job.pid = process.pid; self._save(job, "process_started", pid=process.pid)
        assert process.stdout is not None
        # A renderer can be silent for minutes.  Read stdout in a helper so a
        # cancellation request is still honoured while no log line is emitted.
        output: queue.Queue[str | None] = queue.Queue()
        def drain() -> None:
            try:
                for line in process.stdout:
                    output.put(line)
            finally:
                output.put(None)
        threading.Thread(target=drain, name=f"ir-job-log-{job.job_id[:8]}", daemon=True).start()
        while True:
            if job.cancel.is_set():
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                raise RuntimeError("cancelled")
            try: line = output.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None: break
                continue
            if line is None: break
            self._save(job, "output", stage=stage, line=line.rstrip())
        code = process.wait(); job.pid = None
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
            if not pairs or any(len(group) != 6 for group in pairs.values()):
                raise RuntimeError("QC gate failed: incomplete six-condition illumination pair")
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
            visibility = self._material_visibility_qc(root, rows)
            if visibility["status"] != "passed":
                raise QualityGateError("material visibility QC failed: " + ", ".join(visibility["failures"]))
            _atomic_json(Path(job.request["paths"]["pipeline"]) / "winner.json", {
                "schema": "robomituba.ir_quality_attempt_winner.v1", "selected_at": _utc(),
                "variation_id": job.request.get("variation_id"), "attempt_index": job.request.get("quality_attempt_index"),
                "scene_id": job.request.get("scene_id"), "attempt_root": job.request["paths"].get("attempt_root"),
                "scene_quality": job.request["paths"].get("scene_quality"),
                "material_mix": job.request["paths"].get("material_mix"),
                "material_visibility_qc": str(root / "material_visibility_qc.json"),
            })
        job.stage_results[stage_name] = {"status": "succeeded", "completed_at": _utc()}; self._save(job, "verified", qc=qc)

    def _material_visibility_qc(self, root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Evaluate metal coverage from exact Stage-0 GT, never RGB appearance."""
        import cv2
        import numpy as np
        threshold = 0.7
        frame_rows, group_rows, histogram = [], {}, [0] * 10
        total_valid = total_high = 0
        material_counts: dict[int, int] = {}
        for row in rows:
            paths = row["paths"]
            metallic = cv2.imread(str(root / paths["metallic"]), cv2.IMREAD_UNCHANGED)
            defined = cv2.imread(str(root / paths["gt_defined_mask"]), cv2.IMREAD_UNCHANGED)
            replacement = cv2.imread(str(root / paths["replacement_mask"]), cv2.IMREAD_UNCHANGED)
            fallback = cv2.imread(str(root / paths["fallback_mask"]), cv2.IMREAD_UNCHANGED)
            material_id = cv2.imread(str(root / paths["material_id"]), cv2.IMREAD_UNCHANGED)
            if any(image is None for image in (metallic, defined, replacement, fallback, material_id)):
                raise RuntimeError("material visibility QC requires metallic/ID/validity masks")
            scale = float(np.iinfo(metallic.dtype).max) if np.issubdtype(metallic.dtype, np.integer) else 1.0
            value = metallic.astype(np.float32) / scale
            valid = (defined > 0) & ~(replacement > 0) & ~(fallback > 0)
            high = valid & (value >= threshold)
            valid_count, high_count = int(valid.sum()), int(high.sum())
            total_valid += valid_count; total_high += high_count
            if valid_count:
                bins = np.minimum((value[valid] * 10).astype(np.int32), 9)
                for index, count in enumerate(np.bincount(bins, minlength=10)):
                    histogram[index] += int(count)
            for encoded, count in zip(*np.unique(material_id[high], return_counts=True)):
                material_counts[int(encoded)] = material_counts.get(int(encoded), 0) + int(count)
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
        if visible_fraction < .5: failures.append("high_metallic_visible_in_less_than_half_qc_frames")
        if coverage < .03: failures.append("high_metallic_coverage_below_3pct")
        if coverage > .12: failures.append("high_metallic_coverage_above_12pct")
        if dominant_ratio > .60: failures.append("single_material_dominates_high_metallic_pixels")
        report = {"schema": "robomituba.ir_material_visibility_qc.v1", "profile": METAL_PROFILE,
                  "high_metallic_threshold": threshold, "status": "failed" if failures else "passed",
                  "valid_pixel_count": total_valid, "high_metallic_pixel_count": total_high,
                  "high_metallic_fraction": coverage, "visible_frame_fraction": visible_fraction,
                  "dominant_material_id": dominant_id, "dominant_material_ratio": dominant_ratio,
                  "histogram_10_bins": histogram, "lighting_groups": group_rows, "frames": frame_rows,
                  "top_material_ids": [{"material_id": key, "high_metallic_pixels": value,
                                        "fraction": value / total_high} for key, value in sorted(material_counts.items(), key=lambda item: -item[1])[:10]],
                  "failures": failures}
        report["qc_digest"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        _atomic_json(root / "material_visibility_qc.json", report)
        return report

    def _assert_prepared_v2(self, job: ControllerJob) -> None:
        contract_path = Path(job.request["paths"]["prepared"]) / "principled_material_contract.json"
        contract = _read_json(contract_path)
        if contract.get("schema") != "robomituba.ir_principled_material_contract.v2":
            raise RuntimeError("prepared scene is not the required Principled material-contract v2")
        if contract.get("contract_version") != "blender42-principled-metallic-roughness-v2":
            raise RuntimeError("prepared scene does not use texture-accurate Principled v2")
        required = {"base_color_rgb", "base_color_nir", "roughness", "metallic", "normal_geometry_world", "normal_shading_world"}
        records = contract.get("materials") or []
        if not records or any(set((record.get("effective_inputs") or {})) != required for record in records):
            raise RuntimeError("prepared scene lacks the required effective-input audit")

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
            if (
                job.stage_results.get(stage, {}).get("status") != "succeeded"
                or self._stage_artifact_state(job, stage) != "verified"
            ):
                return stage
        return None

    def _run_stage(self, job: ControllerJob, stage: str) -> None:
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        if stage in {"view_probe", "view_plan", "scene_quality_gate", "geometry", "overview_proxy", "principled_prepare", "material_mix_audit", "qc_render", "qc_verify",
                     "full_render", "full_verify", "dataset_utility_audit", "publish"}:
            self._assert_pipeline_owner(job)
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
            job.stage_results[stage] = publish_dataset(Path(job.request["paths"]["dataset"]), self.bean_root,
                                                       name=job.request["dataset_name"])
            self._save(job, "stage_succeeded"); return
        if stage == "qc_render":
            self._assert_prepared_v2(job)
        self._run_command(job, stage, self._command(job, stage))
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

    def _complete_stage(self, job: ControllerJob, stage: str) -> None:
        try:
            self._run_stage(job, stage)
            with self._lock:
                job.pid = None; job.resource_state = "pending"; job.resource_class = None
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
                job.pid, job.finished_at, job.error = None, _utc(), str(exc)
                job.resource_state = "cancelled" if job.cancel.is_set() else "failed"
                job.resource_gpu_indices = []
                job.desired_gpu_indices = []
                job.draining_gpu_indices = []
                job.status = "cancelled" if job.cancel.is_set() else "failed"
                job.stage_results[stage] = {"status": "failed", "failed_at": _utc(), "error": str(exc)}
                self._save(job, job.status, stage=stage, error=job.error)
                self._wake.set()

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
            try:
                payload = _read_json(self._render_root(job) / "gpu_worker_state.json")
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                continue
            workers = payload.get("workers") if isinstance(payload.get("workers"), dict) else {}
            actual = sorted(
                int(gpu) for gpu, record in workers.items()
                if isinstance(record, dict) and record.get("status") in {"starting", "ready", "busy", "draining"}
            )
            draining = sorted(
                int(gpu) for gpu, record in workers.items()
                if isinstance(record, dict) and record.get("status") == "draining"
            )
            resource_state = "waiting_gpu" if not actual and not job.desired_gpu_indices else "running"
            if (
                actual != job.resource_gpu_indices
                or draining != job.draining_gpu_indices
                or resource_state != job.resource_state
            ):
                job.resource_gpu_indices = actual
                job.draining_gpu_indices = draining
                job.resource_state = resource_state
                self._save(job, "gpu_worker_state", resource_gpu_indices=actual,
                           desired_gpu_indices=job.desired_gpu_indices, draining_gpu_indices=draining)

    def _rebalance_gpu_targets(self, candidates: list[tuple[ControllerJob, str]]) -> None:
        """Compute a work-conserving max-min target over the configured GPU pool."""
        running_bakes = [job for job in self._running_jobs() if job.resource_class == "blender_bake"]
        bake_gpus = {gpu for job in running_bakes for gpu in job.resource_gpu_indices}
        ready_bakes = [job for job, stage in candidates if self._resource_class(stage) == "blender_bake"]
        reserve_count = min(
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
        render_jobs.sort(key=lambda item: (-item.priority, item.created_at, item.job_id))
        targets: dict[str, list[int]] = {job.job_id: [] for job in render_jobs}
        remaining = list(render_pool)
        # Repeated rounds implement max-min fair share. Within each round retain
        # current leases when possible to avoid gratuitous worker restarts.
        while remaining and render_jobs:
            assigned = False
            for job in render_jobs:
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
            return sum(job.resource_class == "infinigen_generate" for job in running) < 2
        if resource == "blender_bootstrap":
            return sum(item.resource_class == resource for item in running) < self.bootstrap_concurrency
        if resource == "blender_bake":
            return (
                job is not None
                and sum(item.resource_class == resource for item in running) < self.bake_concurrency
                and self._available_bake_gpu(job) is not None
            )
        if resource == "blender_prepare":
            return sum(item.resource_class == resource for item in running) < self.prepare_concurrency
        return sum(job.resource_class == "cpu_light" for job in running) < 2

    def _refresh_waiting_states(self, candidates: list[tuple[ControllerJob, str]]) -> None:
        gpu_waiting = [job for job, resource in candidates if resource in {"gpu_render", "blender_bake"} and not self._can_start(resource, job)]
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
                self._sync_render_worker_state()
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
                    if job.job_id in self._queue:
                        self._queue.remove(job.job_id)
                    job.status, job.stage, job.resource_class, job.resource_state = "running", stage, resource, "running"
                    job.queue_position = None
                    if resource == "blender_bake":
                        gpu = self._available_bake_gpu(job)
                        job.resource_gpu_indices = [] if gpu == -1 else [int(gpu)]
                    elif resource == "gpu_render":
                        job.resource_gpu_indices = []
                        job.draining_gpu_indices = []
                    else:
                        job.resource_gpu_indices = []
                        job.desired_gpu_indices = []
                        job.draining_gpu_indices = []
                    if job.started_at is None: job.started_at = _utc()
                    self._save(job, "stage_dispatched", stage=stage, resource_class=resource,
                               resource_gpu_indices=job.resource_gpu_indices, slot_usage=self._resource_usage())
                    thread = threading.Thread(target=self._complete_stage, args=(job, stage), name=f"ir-stage-{job.job_id[:8]}-{stage}", daemon=True)
                    self._running[job.job_id] = thread
                    thread.start()
                self._audit_work_conserving(candidates)
