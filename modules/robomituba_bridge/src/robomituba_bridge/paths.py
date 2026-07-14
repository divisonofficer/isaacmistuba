from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BRIDGE_JOBS_ROOT = Path("out/bridge_jobs")


@dataclass(frozen=True)
class JobLayout:
    job_dir: Path
    manifest: Path
    snapshot_dir: Path
    scene_snapshot: Path
    materials: Path
    cameras: Path
    lights: Path
    usd_dir: Path
    usd_stage: Path
    renders_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class ObservationLayout:
    job_dir: Path
    observations_dir: Path
    frame_dir: Path
    manifest: Path
    cameras_dir: Path
    sensors_dir: Path
    logs_dir: Path


def repo_root_from(start: str | Path | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    search_roots = [current, *current.parents]
    for candidate in search_roots:
        if (candidate / "project.md").exists() and (candidate / "modules").exists():
            return candidate
    raise RuntimeError("Could not locate repo root from the given path.")


def ensure_job_layout(repo_root: str | Path, job_id: str) -> JobLayout:
    root = Path(repo_root).resolve()
    job_dir = root / BRIDGE_JOBS_ROOT / job_id
    snapshot_dir = job_dir / "snapshot"
    usd_dir = job_dir / "usd"
    renders_dir = job_dir / "renders"
    logs_dir = job_dir / "logs"

    for path in [snapshot_dir, usd_dir, renders_dir / "rgb", renders_dir / "polarization", renders_dir / "nir", logs_dir]:
        path.mkdir(parents=True, exist_ok=True)

    return JobLayout(
        job_dir=job_dir,
        manifest=job_dir / "manifest.json",
        snapshot_dir=snapshot_dir,
        scene_snapshot=snapshot_dir / "scene_snapshot.json",
        materials=snapshot_dir / "materials.json",
        cameras=snapshot_dir / "cameras.json",
        lights=snapshot_dir / "lights.json",
        usd_dir=usd_dir,
        usd_stage=usd_dir / "stage.usda",
        renders_dir=renders_dir,
        logs_dir=logs_dir,
    )


def ensure_observation_layout(repo_root: str | Path, job_id: str, frame_id: str) -> ObservationLayout:
    root = Path(repo_root).resolve()
    job_dir = root / BRIDGE_JOBS_ROOT / job_id
    observations_dir = job_dir / "observations"
    frame_dir = observations_dir / frame_id
    cameras_dir = frame_dir / "cameras"
    sensors_dir = frame_dir / "sensors"
    logs_dir = frame_dir / "logs"

    for path in [observations_dir, frame_dir, cameras_dir, sensors_dir, logs_dir]:
        path.mkdir(parents=True, exist_ok=True)

    return ObservationLayout(
        job_dir=job_dir,
        observations_dir=observations_dir,
        frame_dir=frame_dir,
        manifest=frame_dir / "manifest.json",
        cameras_dir=cameras_dir,
        sensors_dir=sensors_dir,
        logs_dir=logs_dir,
    )


def to_repo_relative_posix(repo_root: str | Path, path: str | Path) -> str:
    root = Path(repo_root).resolve()
    candidate = Path(path).resolve()
    rel = candidate.relative_to(root)
    return PurePosixPath(rel.as_posix()).as_posix()


def resolve_repo_path(repo_root: str | Path, repo_relative_path: str) -> Path:
    root = Path(repo_root).resolve()
    return root / PurePosixPath(repo_relative_path)
