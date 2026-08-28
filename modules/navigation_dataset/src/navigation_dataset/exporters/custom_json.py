from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from typing import Callable, Iterable
import zipfile

from ..episode_schema import DatasetProject, EpisodeManifest, read_episode, read_project, write_project
from ..scene_dataset import PROJECT_CATALOG_VERSION, SceneDatasetPaths


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def find_episode_files(dataset_root: str | Path, *, scene_id: str | None = None) -> list[Path]:
    """Return episode JSON files, optionally through one scene workspace only.

    ``scene_id`` is not a post-filter: it selects the v3 scene-local resolver
    before any directory enumeration, so another scene's malformed or huge
    episode tree cannot affect the caller.
    """
    root = Path(dataset_root)
    if scene_id is not None:
        return SceneDatasetPaths.from_project(root, str(scene_id)).episode_paths()
    return sorted((root / "episodes").glob("*/*.json"))


def _scene_id_from_path(path: Path, split: str) -> str:
    """Derive scene_id from the episode path without opening the file.

    Episode ids are constructed as ``f"{scene_id}_{split}_…"`` (see ``rollout`` and
    ``graph_episode_sampler``) and stored under ``episodes/<split>/``. The scene_id
    is therefore the filename stem up to the ``_<split>_`` marker. Returns "" if the
    marker isn't found (caller falls back to a real read).
    """
    stem = path.stem
    idx = stem.find(f"_{split}_")
    return stem[:idx] if idx > 0 else ""


_OBS_FILE_SUFFIXES = (".png", ".exr", ".jpg", ".jpeg", ".npy")


def _active_observation_dir(
    dataset_root: Path,
    *,
    scene_id: str,
    variant: str,
    node_id: str,
    heading_id: str,
) -> Path | None:
    """Resolve a versioned ``current.json`` observation pointer.

    Scene-bundle export must follow the active pointer but retain the stable
    observation path inside the ZIP.  Keep this resolver local to the pure
    navigation exporter to avoid importing the Mitsuba daemon package.
    """
    root = Path(dataset_root).resolve()
    observation_name = {
        "perturbed": "observations_perturbed",
        "perturbed_active_polar": "observations_perturbed_active_polar",
    }.get(variant, "observations")
    stable = root / "scenes" / str(scene_id) / observation_name / str(node_id) / str(heading_id)
    pointer = stable / "current.json"
    if pointer.is_file():
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            ref = payload.get("bundle_ref")
            if isinstance(ref, str) and ref:
                candidate = (root / ref).resolve()
                # Never allow a malformed pointer to escape the project tree.
                candidate.relative_to(root)
                if candidate.is_dir():
                    return candidate
        except (OSError, ValueError, TypeError):
            pass
    return stable if stable.is_dir() else None


def _completed_sensor_bundle_index(
    dataset_root: Path,
    scene_ids: Iterable[str],
) -> dict[tuple[str, str, str, str, str], Path]:
    """Resolve the newest durable source directory for every rendered sensor.

    A graph sweep version is intentionally immutable, and modality-only sweeps
    therefore store different cameras in different version directories.  A
    single heading-level ``current.json`` cannot represent that union: promoting
    a later polar run would otherwise hide an earlier RGB camera at export time.
    Build one small ledger index up front so collection can compose the cameras
    without querying SQLite once per heading.
    """
    root = Path(dataset_root).resolve()
    scenes = sorted({str(scene_id) for scene_id in scene_ids if str(scene_id)})
    if not scenes:
        return {}
    result: dict[tuple[str, str, str, str, str], Path] = {}
    # v3 has one ledger per scene.  Retain the shared-ledger fallback only for
    # an unmigrated legacy project or an explicit multi-scene bulk operation.
    ledger_sources: list[tuple[Path, list[str]]] = []
    for scene_id in scenes:
        local = SceneDatasetPaths.from_project(root, scene_id).ledger_path
        if local.is_file():
            ledger_sources.append((local, [scene_id]))
        elif (root / "render_ledger.sqlite3").is_file():
            ledger_sources.append((root / "render_ledger.sqlite3", [scene_id]))
    if not ledger_sources:
        return result
    for ledger_path, scoped_scenes in ledger_sources:
        placeholders = ",".join("?" for _ in scoped_scenes)
        try:
            connection = sqlite3.connect(f"file:{ledger_path.as_posix()}?mode=ro", uri=True, timeout=5.0)
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(
                    f"""SELECT r.scene_id, r.created_at, t.variant, t.node_id,
                           t.heading_id, t.render_version_id, t.metadata_json
                    FROM sweep_tasks t
                    JOIN sweep_runs r ON r.run_id = t.run_id
                    LEFT JOIN render_versions v
                      ON v.render_version_id = t.render_version_id
                    WHERE r.scene_id IN ({placeholders})
                      AND (
                        t.state = 'succeeded'
                        OR (t.state = 'skipped' AND json_extract(t.metadata_json, '$.source_bundle_ref') IS NOT NULL)
                      )
                      AND COALESCE(v.status, '') <> 'pruned'
                    ORDER BY r.created_at, t.ordinal""",
                    scoped_scenes,
                ).fetchall()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            continue
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            sensor_ids = [str(value) for value in metadata.get("sensor_ids") or [] if str(value)]
            if not sensor_ids:
                continue
            source_ref = str(metadata.get("source_bundle_ref") or "")
            if source_ref:
                # ``source_bundle_ref`` is an internal, bundle-relative ledger
                # reference. Calling ``Path.resolve()`` here turns one export
                # preflight into thousands of NAS realpath requests (one per
                # completed task), which can take minutes even though no file
                # content needs to be read. Reject lexical escapes and retain
                # the relative path instead; subsequent ``is_dir()`` is the
                # authoritative existence check.
                ref_path = Path(source_ref)
                if ref_path.is_absolute() or ".." in ref_path.parts:
                    continue
                bundle = root / ref_path
            else:
                bundle = (
                    root / "scenes" / str(row["scene_id"]) / "observations" / "versions"
                    / str(row["render_version_id"]) / str(row["variant"] or "base")
                    / str(row["node_id"]) / str(row["heading_id"])
                )
            for sensor_id in sensor_ids:
                sensor_root = next(
                    (candidate for candidate in (bundle / "sensors" / sensor_id, bundle / "cameras" / sensor_id)
                     if candidate.is_dir()),
                    None,
                )
                if sensor_root is not None:
                    result[(
                        str(row["scene_id"]), str(row["variant"] or "base"),
                        str(row["node_id"]), str(row["heading_id"]), sensor_id,
                    )] = sensor_root
    return result


def _completed_observation_keys(
    dataset_root: Path,
    scene_ids: Iterable[str],
) -> set[tuple[str, str, str, str]]:
    """Return durable versioned observation keys without walking every raster.

    Graph sweeps publish immutable bundles in ``observations/versions``.  A
    legacy consolidated directory may not exist at all, so disk-only episode
    completion would incorrectly hide fully rendered daemon sweeps from an
    ``only_completed`` export.  The ledger already has the authoritative
    completed sensor bundles; collapse that index to heading-level keys.
    """
    return {
        (scene_id, variant, node_id, heading_id)
        for scene_id, variant, node_id, heading_id, _sensor_id in _completed_sensor_bundle_index(
            dataset_root, scene_ids,
        )
    }


def is_episode_complete(
    episode: EpisodeManifest,
    dataset_root: Path,
    *,
    versioned_observation_keys: set[tuple[str, str, str, str]] | None = None,
) -> bool:
    """Return True when every step in the episode path has rendered observations
    on disk.

    Two data sources both turn out to be unreliable on the current pipeline so
    we ignore them and look at the disk directly:

    * ``episode.timesteps[i].observation_bundle_ref`` is filled at episode
      *creation* time from ``graph.sensor_observations``. If the user creates
      an episode first and renders later, the field stays empty in the saved
      episode JSON.
    * ``viewpoint_graph.json`` 's ``sensor_observations`` is only kept fresh by
      the in-process ``render_viewpoint_sweep_direct`` path. The daemon-based
      batch path (graph_sweep / episode_nodes) writes files to
      ``scenes/<scene>/observations/<vp>/<h>/`` but never calls back to update
      the graph.

    A versioned-render ledger is the source of truth for daemon sweeps; the
    legacy consolidated directory remains a compatibility fallback.
    """
    project_dir = Path(dataset_root).resolve()

    # Graph-mode episodes — check each (node, heading) along the path against
    # the consolidated observations directory.
    if (
        episode.path_nodes
        and episode.path_headings
        and len(episode.path_nodes) == len(episode.path_headings)
        and episode.scene_id
    ):
        scene_id = str(episode.scene_id)
        completed_keys = versioned_observation_keys
        if completed_keys is None:
            completed_keys = _completed_observation_keys(project_dir, [scene_id])
        for node_id, heading_id in zip(episode.path_nodes, episode.path_headings):
            key = (scene_id, "base", str(node_id), str(heading_id))
            if key in completed_keys:
                continue
            heading_dir = _active_observation_dir(
                project_dir, scene_id=scene_id, variant="base",
                node_id=str(node_id), heading_id=str(heading_id),
            )
            if heading_dir is None:
                return False
            # At least one rendered modality file present (including files under
            # versioned bundle cameras/ or sensors/ subdirectories).
            has_modality = any(
                p.is_file() and p.suffix.lower() in _OBS_FILE_SUFFIXES
                for p in heading_dir.rglob("*")
            )
            if not has_modality:
                return False
        return True

    # Trajectory mode — fall back to the timestep ref check.
    timesteps = episode.timesteps or []
    if not timesteps:
        return False
    repo_root = project_dir.parent.parent
    for step in timesteps:
        ref = (step.observation_bundle_ref or "").strip()
        if not ref:
            return False
        ref_path = Path(ref)
        if ref_path.is_absolute():
            candidates = [ref_path]
        else:
            candidates = [project_dir / ref_path, repo_root / ref_path]
        if not any(p.exists() for p in candidates):
            return False
    return True


def _filter_episode_files(
    dataset_root: Path,
    *,
    episode_ids: Iterable[str] | None,
    only_completed: bool,
    scene_ids: Iterable[str] | None = None,
) -> list[Path]:
    scene_scope = [str(item) for item in scene_ids] if scene_ids is not None else []
    paths = (
        find_episode_files(dataset_root, scene_id=scene_scope[0])
        if len(scene_scope) == 1 else find_episode_files(dataset_root)
    )
    if episode_ids is None and not only_completed and scene_ids is None:
        return paths
    allow_episode = set(str(eid) for eid in episode_ids) if episode_ids is not None else None
    allow_scene = set(str(sid) for sid in scene_ids) if scene_ids is not None else None
    kept: list[Path] = []
    completed_by_scene: dict[str, set[tuple[str, str, str, str]]] = {}
    for path in paths:
        # episode_id == filename stem, split == parent dir, scene_id derivable from
        # both — so the episode_id / scene_id filters never need to open the file
        # (~26 ms each on this filesystem). Only ``only_completed`` requires a read.
        if allow_episode is not None and path.stem not in allow_episode:
            continue
        if allow_scene is not None:
            scene_id = _scene_id_from_path(path, path.parent.name)
            if not scene_id:
                try:
                    scene_id = read_episode(path).scene_id
                except Exception:
                    continue
            if scene_id not in allow_scene:
                continue
        if only_completed:
            try:
                episode = read_episode(path)
            except Exception:
                continue
            scene_id = str(episode.scene_id or "")
            if scene_id not in completed_by_scene:
                completed_by_scene[scene_id] = (
                    _completed_observation_keys(dataset_root, [scene_id]) if scene_id else set()
                )
            completed_keys = completed_by_scene[scene_id]
            if not is_episode_complete(
                episode,
                dataset_root,
                versioned_observation_keys=completed_keys,
            ):
                continue
        kept.append(path)
    return kept


def build_dataset_index(
    dataset_root: str | Path,
    *,
    episode_ids: Iterable[str] | None = None,
    only_completed: bool = False,
    scene_ids: Iterable[str] | None = None,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> dict:
    root = Path(dataset_root).resolve()
    project_path = root / "dataset.json"
    scene_filter = set(str(sid) for sid in scene_ids) if scene_ids is not None else None
    raw_project: dict = {}
    if project_path.exists():
        try:
            candidate = json.loads(project_path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict) and candidate.get("layout_version") != PROJECT_CATALOG_VERSION:
                raw_project = candidate
        except (OSError, ValueError):
            raw_project = {}
    project = DatasetProject(project_name=str(raw_project.get("project_name") or root.name))
    episodes_by_split: dict[str, list[str]] = {"train": [], "val_seen": [], "val_unseen": [], "test": []}
    discovered_scene_ids: set[str] = set()
    if scene_filter is not None and len(scene_filter) == 1:
        scoped_scene_id = next(iter(scene_filter))
        all_episode_paths = find_episode_files(root, scene_id=scoped_scene_id)
    else:
        all_episode_paths = find_episode_files(root)
    kept_paths = _filter_episode_files(
        root, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
    )
    # When a scene scope is active, "total on disk" should reflect that scope so
    # the UI can show "X of Y rendered for this scene".
    scoped_total = 0
    skipped_count = 0
    _index_total = len(all_episode_paths)
    # Fast path: the index only needs each episode's split + scene_id + rel path.
    # Both are encoded in the layout (``episodes/<split>/<scene_id>_<split>_…json``),
    # so we derive them from the path instead of opening the file. On this filesystem
    # a single read_episode is ~26 ms, so reading every episode (thousands) on each
    # rebuild cost 90 s+; deriving from the path makes the no-filter rebuild near-instant.
    no_filter = episode_ids is None and not only_completed and scene_ids is None
    kept_set = set() if no_filter else {p.resolve() for p in kept_paths}
    for _i, path in enumerate(all_episode_paths):
        if on_progress is not None:
            on_progress(_i + 1, _index_total)
        split = path.parent.name
        if scene_filter is not None:
            ep_scene = _scene_id_from_path(path, split)
            if not ep_scene:                       # unexpected naming → fall back to a real read
                try:
                    ep_scene = read_episode(path).scene_id
                except Exception:
                    ep_scene = ""
            if ep_scene not in scene_filter:
                continue
            discovered_scene_ids.add(ep_scene)
        scoped_total += 1
        if not no_filter and path.resolve() not in kept_set:
            skipped_count += 1
            continue
        episodes_by_split.setdefault(split, []).append(_rel(root, path))
    scene_artifacts: list[dict] = []
    scene_dirs = (
        [root / "scenes" / next(iter(scene_filter))]
        if scene_filter is not None and len(scene_filter) == 1 else sorted((root / "scenes").glob("*"))
    )
    for scene_dir in scene_dirs:
        if not scene_dir.is_dir():
            continue
        if scene_filter is not None and scene_dir.name not in scene_filter:
            continue
        entry = {"scene_id": scene_dir.name}
        for filename, field_name in (
            ("authoring_map.json", "authoring_map_ref"),
            ("scene_annotation.json", "annotation_ref"),
            ("scene_variant.json", "scene_variant_ref"),
            ("render_scene_overlays.json", "render_scene_overlay_ref"),
            ("traversable_grid.npy", "traversable_grid_ref"),
            ("nav_graph.json", "nav_graph_ref"),
            ("viewpoint_graph.json", "viewpoint_graph_ref"),
        ):
            path = scene_dir / filename
            if path.exists():
                entry[field_name] = _rel(root, path)
        scene_artifacts.append(entry)
        discovered_scene_ids.add(scene_dir.name)
    return {
        **asdict(project),
        "scenes": sorted(discovered_scene_ids),
        "scene_artifacts": scene_artifacts,
        "splits": episodes_by_split,
        "episode_count": sum(len(items) for items in episodes_by_split.values()),
        "total_episode_count_on_disk": scoped_total,
        "project_total_episode_count": len(all_episode_paths),
        "skipped_episode_count": skipped_count,
        "filter": {
            "episode_ids": list(episode_ids) if episode_ids is not None else None,
            "scene_ids": sorted(scene_filter) if scene_filter is not None else None,
            "only_completed": bool(only_completed),
        },
        "format": "custom_json",
    }


def write_dataset_index(
    dataset_root: str | Path,
    *,
    episode_ids: Iterable[str] | None = None,
    only_completed: bool = False,
    scene_ids: Iterable[str] | None = None,
    on_progress: "Callable[[int, int], None] | None" = None,
) -> Path:
    root = Path(dataset_root)
    index = build_dataset_index(
        root, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
        on_progress=on_progress,
    )
    scene_scope = [str(item) for item in scene_ids] if scene_ids is not None else []
    path = (
        SceneDatasetPaths.from_project(root, scene_scope[0]).dataset_path
        if len(scene_scope) == 1 else root / "dataset.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_split_files(
    dataset_root: str | Path,
    *,
    episode_ids: Iterable[str] | None = None,
    only_completed: bool = False,
    scene_ids: Iterable[str] | None = None,
) -> list[Path]:
    root = Path(dataset_root)
    index = build_dataset_index(
        root, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
    )
    scene_scope = [str(item) for item in scene_ids] if scene_ids is not None else []
    output_dir = (
        SceneDatasetPaths.from_project(root, scene_scope[0]).splits_dir
        if len(scene_scope) == 1 else root / "splits"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for split, episodes in index["splits"].items():
        path = output_dir / f"{split}.json"
        path.write_text(json.dumps({"split": split, "episodes": episodes}, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def export_dataset_zip(
    dataset_root: str | Path,
    output_zip: str | Path | None = None,
    *,
    episode_ids: Iterable[str] | None = None,
    only_completed: bool = False,
    scene_ids: Iterable[str] | None = None,
) -> Path:
    """Legacy project-wide zip. Kept for CLI / external scripts.

    The new scene-bundle export goes through `_run_export_job` on the daemon
    which uses `write_dataset_index_from`, `write_split_files_from`, and
    `iter_export_files` against a staging directory.
    """
    root = Path(dataset_root).resolve()
    write_dataset_index(
        root, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
    )
    write_split_files(
        root, episode_ids=episode_ids, only_completed=only_completed, scene_ids=scene_ids,
    )
    zip_path = Path(output_zip) if output_zip is not None else root.with_suffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            zf.write(path, _rel(root, path))
    return zip_path


# ---------------------------------------------------------------------------
# Scene-bundle export helpers — used by the daemon's export job worker.
# ---------------------------------------------------------------------------


def write_dataset_index_from(payload: dict, root: str | Path) -> Path:
    """Write a pre-built `build_dataset_index` payload as `dataset.json`.

    Lets the worker compute the index once and persist it in a staging
    directory without re-walking the project.
    """
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    path = root_path / "dataset.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_split_files_from(payload: dict, root: str | Path) -> list[Path]:
    """Write `splits/{split}.json` from a pre-built index payload."""
    root_path = Path(root)
    out_dir = root_path / "splits"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    splits = payload.get("splits") or {}
    for split, episodes in splits.items():
        path = out_dir / f"{split}.json"
        path.write_text(json.dumps({"split": split, "episodes": list(episodes)}, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


# Observation directories include both EXR (HDR) and PNG (LDR previews) plus
# `sensors/<camera>/...` subfolders. We copy everything verbatim so external
# readers (VLN evaluator) can pick whichever modality / format they need.

def _bridge_job_observation_dirs(
    repo_root: Path, scene_id: str, vp_id: str, h_id: str,
) -> Iterable[Path]:
    """Bridge-job observation dirs that match (scene, vp, heading).

    The render daemon writes EXR under
    `out/bridge_jobs/opticalnav-<scene>-template-<vp>-<h>-<mod>/observations/...`
    but `_opticalnav_copy_observation_rgb` only copies PNG into the
    consolidated `scenes/<scene>/observations/<vp>/<h>/` directory. The bundle
    needs EXR too, so we pull it from bridge_jobs directly at export time.
    """
    bridge_root = repo_root / "out" / "bridge_jobs"
    if not bridge_root.exists():
        return
    pattern = f"opticalnav-{scene_id}-template-{vp_id}-{h_id}-*"
    for job_dir in bridge_root.glob(pattern):
        obs_root = job_dir / "observations"
        if obs_root.is_dir():
            yield obs_root


def iter_export_files(
    project_dir: str | Path,
    index_payload: dict,
    kept_episodes: Iterable[EpisodeManifest],
    *,
    panorama_observations: bool = True,
    include_exr: bool = True,
    include_polarization_raw: bool = True,
    include_perturbed: bool = False,
    camera_ids: Iterable[str] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> Iterable[tuple[Path, str]]:
    """Yield (src_path, dst_relative_posix_path) pairs for the scene bundle.

    The destination layout mirrors the project tree under
    `scenes/<scene_id>/` so external readers that already understand the
    project layout work unchanged.

    `panorama_observations`:
        * True (default) — include **every rendered heading** at every
          rendered viewpoint in each selected scene. This is the full graph
          observation set, not merely the subset of viewpoints traversed by
          the exported episodes. Lets external readers consume full surround
          context and preserves base↔perturbed sweep completeness.
        * False — include only the (vp, heading) pairs the episode actually
          visits. Same data the GT thumbnails reference; produces a much
          slimmer bundle when only the rendered trajectory is needed.

    Excludes:
      * other scenes under `scenes/`
      * `control_plane_cache/`, `mesh_cache/`, `.staged_mitsuba/` (renderer caches)
      * `job_status.json`, `render_progress.log` (in-flight job artifacts)
      * the project's top-level `dataset.json` (replaced by the bundle's own)
    """
    pdir = Path(project_dir).resolve()
    repo_root = pdir.parents[2] if len(pdir.parents) >= 3 else None
    yielded_dst: set[str] = set()
    allowed_camera_ids = (
        {str(camera_id) for camera_id in camera_ids}
        if camera_ids is not None
        else None
    )
    resolved_heading_count = 0
    source_exr_keys: set[tuple[str, str, str]] = set()
    versioned_sensor_sources: dict[tuple[str, str, str, str], dict[str, Path]] = {}

    def _notify_resolved() -> None:
        nonlocal resolved_heading_count
        resolved_heading_count += 1
        if on_progress is not None:
            on_progress(resolved_heading_count, 0)

    def _emit(src: Path, dst_rel: str):
        if dst_rel in yielded_dst:
            return None
        yielded_dst.add(dst_rel)
        return (src, dst_rel)

    def _emit_observation_dir(
        obs_dir: Path,
        destination_root: Path | None = None,
        observation_key: tuple[str, str, str] | None = None,
    ) -> Iterable[tuple[Path, str]]:
        """Yield observation files, resolving versioned bundles to stable paths."""
        if not obs_dir.is_dir():
            return
        per_camera_roots = [root for root in (obs_dir / "sensors", obs_dir / "cameras") if root.is_dir()]
        # One filesystem walk per heading. The former implementation walked
        # each sensors tree once to find duplicate names and again to emit files;
        # on a large panorama sweep that doubled the NFS/stat cost at Collect.
        all_files = sorted(
            Path(root) / name
            for root, _dirs, names in os.walk(obs_dir)
            for name in names
        )
        if observation_key is not None and any(path.suffix.lower() == ".exr" for path in all_files):
            source_exr_keys.add(observation_key)
        per_camera_names: set[str] = set()
        for src in all_files:
            for camera_root in per_camera_roots:
                if camera_root in src.parents:
                    camera_rel = src.relative_to(camera_root)
                    if allowed_camera_ids is None or camera_rel.parts[0] in allowed_camera_ids:
                        per_camera_names.add(src.name)
                    break
        for src in all_files:
            # current.json is a resolver control plane pointer, not an
            # observation artifact; never package it as if it were a raster.
            if src.parent == obs_dir and src.name == "current.json":
                continue
            mapped_rel: Path | None = None
            for camera_root in per_camera_roots:
                if camera_root in src.parents:
                    camera_rel = src.relative_to(camera_root)
                    if allowed_camera_ids is not None and camera_rel.parts[0] not in allowed_camera_ids:
                        mapped_rel = None
                        break
                    # Consolidated exports historically expose every camera
                    # under sensors/, while versioned bundles may call the
                    # source directory cameras/.
                    mapped_rel = Path("sensors") / camera_rel
                    break
            if per_camera_roots and mapped_rel is None and any(root in src.parents for root in per_camera_roots):
                continue
            if mapped_rel is None:
                if allowed_camera_ids is not None and src.parent == obs_dir:
                    if src.name == "_sensor_index.json":
                        continue
                    if src.suffix.lower() in {".png", ".exr", ".hdr", ".jpg", ".jpeg", ".npy", ".npz"}:
                        continue
                # Drop root-level duplicates when the same modality exists in
                # a per-camera subtree.
                if src.parent == obs_dir and src.name in per_camera_names:
                    continue
                mapped_rel = Path(src.name)
            if not include_exr and src.suffix.lower() in {".exr", ".hdr", ".npz"}:
                if not (include_polarization_raw and src.name == "stokes_data.npz"):
                    continue
            if destination_root is None:
                rel = src.relative_to(pdir).as_posix()
            else:
                rel = (destination_root / mapped_rel).as_posix()
            pair = _emit(src, rel)
            if pair is not None:
                yield pair

    def _emit_versioned_sensors(
        *,
        scene_id: str,
        variant: str,
        node_id: str,
        heading_id: str,
        destination_root: Path,
    ) -> Iterable[tuple[Path, str]]:
        """Compose per-camera outputs that live in separate render versions."""
        prefix = (str(scene_id), str(variant), str(node_id), str(heading_id))
        entries = sorted(versioned_sensor_sources.get(prefix, {}).items())
        for sensor_id, sensor_root in entries:
            if allowed_camera_ids is not None and sensor_id not in allowed_camera_ids:
                continue
            for root_dir, _dirs, names in os.walk(sensor_root):
                for name in sorted(names):
                    src = Path(root_dir) / name
                    if not include_exr and src.suffix.lower() in {".exr", ".hdr", ".npz"}:
                        if not (include_polarization_raw and src.name == "stokes_data.npz"):
                            continue
                    rel = src.relative_to(sensor_root)
                    destination = (destination_root / "sensors" / sensor_id / rel).as_posix()
                    pair = _emit(src, destination)
                    if pair is not None:
                        yield pair

    # 1. Scene artifact files from index_payload.scene_artifacts.
    for artifact in index_payload.get("scene_artifacts") or []:
        for key, ref in artifact.items():
            if not isinstance(ref, str) or not ref.endswith((".json", ".npy", ".xml")):
                continue
            src = pdir / ref
            if src.is_file():
                pair = _emit(src, ref)
                if pair is not None:
                    yield pair
    # Pick up render_scene.xml (not in scene_artifacts).
    for artifact in index_payload.get("scene_artifacts") or []:
        scene_id = artifact.get("scene_id")
        if not scene_id:
            continue
        for fname in ("render_scene.xml",):
            src = pdir / "scenes" / scene_id / fname
            if src.is_file():
                pair = _emit(src, f"scenes/{scene_id}/{fname}")
                if pair is not None:
                    yield pair
    # 2. Episode JSON for each kept episode.
    kept_list = list(kept_episodes)
    flat_versioned_sources = _completed_sensor_bundle_index(
        pdir,
        (str(ep.scene_id) for ep in kept_list if ep.scene_id),
    )
    for key, source in flat_versioned_sources.items():
        versioned_sensor_sources.setdefault(key[:4], {})[key[4]] = source
    for ep in kept_list:
        ep_path = pdir / "episodes" / ep.split / f"{ep.episode_id}.json"
        if ep_path.is_file():
            pair = _emit(ep_path, f"episodes/{ep.split}/{ep.episode_id}.json")
            if pair is not None:
                yield pair
    # 3. Observation files. A panorama export is intentionally scene-wide:
    # previous code expanded headings only for episode-path viewpoints, which
    # silently omitted fully-rendered graph views that no sampled episode
    # happened to visit. Build the view scope once from durable ledger bundles
    # plus legacy/consolidated observation roots. Non-panorama exports retain
    # the old episode-path-only behaviour.
    selected_scenes = {str(ep.scene_id) for ep in kept_list if ep.scene_id}
    view_requests: list[tuple[str, str, str | None]] = []
    if panorama_observations:
        all_viewpoints: set[tuple[str, str]] = set()
        for scene_id, _variant, node_id, _heading_id in versioned_sensor_sources:
            if scene_id in selected_scenes:
                all_viewpoints.add((scene_id, node_id))
        for scene_id in selected_scenes:
            scene_root = pdir / "scenes" / scene_id
            for observation_name in ("observations", "observations_perturbed", "observations_perturbed_active_polar"):
                observation_root = scene_root / observation_name
                if not observation_root.is_dir():
                    continue
                for candidate in observation_root.iterdir():
                    # ``versions`` stores immutable render artifacts rather
                    # than a graph node; its descendants are already covered
                    # by the ledger index above.
                    if candidate.is_dir() and candidate.name != "versions":
                        all_viewpoints.add((scene_id, candidate.name))
        view_requests = [
            (scene_id, node_id, None)
            for scene_id, node_id in sorted(all_viewpoints)
        ]
    else:
        seen_viewpoints: set[tuple[str, str]] = set()
        for ep in kept_list:
            if not ep.scene_id or not ep.path_nodes:
                continue
            path_pairs: list[tuple[str, str]] = []
            if ep.path_headings and len(ep.path_headings) == len(ep.path_nodes):
                path_pairs = [(str(vp), str(h)) for vp, h in zip(ep.path_nodes, ep.path_headings)]
            for vp_idx, vp_id in enumerate(ep.path_nodes):
                vp_key = (str(ep.scene_id), str(vp_id))
                if vp_key in seen_viewpoints:
                    continue
                seen_viewpoints.add(vp_key)
                heading = path_pairs[vp_idx][1] if vp_idx < len(path_pairs) else None
                view_requests.append((str(ep.scene_id), str(vp_id), heading))

    for scene_id, vp_id, path_heading in view_requests:
        vp_dir = pdir / "scenes" / scene_id / "observations" / vp_id
        heading_ids: list[str] = []
        disk_headings = {p.name for p in vp_dir.iterdir() if p.is_dir()} if vp_dir.is_dir() else set()
        version_headings = {
            key[3] for key in versioned_sensor_sources
            if key[:3] == (scene_id, "base", vp_id)
        }
        available_headings = sorted(disk_headings | version_headings)
        if panorama_observations:
            heading_ids = available_headings
        elif path_heading is not None and path_heading in available_headings:
            heading_ids = [path_heading]

        # 3a. Consolidated observation files for every heading at this vp.
        versioned_heading_ids: set[str] = set()
        for h_id in heading_ids:
            source_dir = _active_observation_dir(
                pdir, scene_id=scene_id, variant="base",
                node_id=vp_id, heading_id=str(h_id),
            )
            destination = Path("scenes") / scene_id / "observations" / vp_id / str(h_id)
            _notify_resolved()
            if versioned_sensor_sources.get((scene_id, "base", vp_id, str(h_id))):
                versioned_heading_ids.add(str(h_id))
            yield from _emit_versioned_sensors(
                scene_id=scene_id, variant="base", node_id=vp_id,
                heading_id=str(h_id), destination_root=destination,
            )
            if source_dir is not None:
                if "versions" in source_dir.parts:
                    versioned_heading_ids.add(str(h_id))
                yield from _emit_observation_dir(
                    source_dir, destination,
                    observation_key=(scene_id, vp_id, str(h_id)),
                )

        # 3c. Perturbation variants share the mirror/glass overlay but must
        # retain distinct passive and active-polar output roots.  This makes a
        # three-way join unambiguous for the RGB-Stokes v2 pilot.
        if include_perturbed:
            for variant, observation_name in (
                ("perturbed", "observations_perturbed"),
                ("perturbed_active_polar", "observations_perturbed_active_polar"),
            ):
                pvp_dir = pdir / "scenes" / scene_id / observation_name / vp_id
                p_disk = {p.name for p in pvp_dir.iterdir() if p.is_dir()} if pvp_dir.is_dir() else set()
                p_version = {
                    key[3] for key in versioned_sensor_sources
                    if key[:3] == (scene_id, variant, vp_id)
                }
                p_available = sorted(p_disk | p_version)
                p_headings = p_available if panorama_observations else [h for h in heading_ids if h in p_available]
                for h_id in p_headings:
                    source_dir = _active_observation_dir(
                        pdir, scene_id=scene_id, variant=variant,
                        node_id=vp_id, heading_id=str(h_id),
                    )
                    destination = Path("scenes") / scene_id / observation_name / vp_id / str(h_id)
                    _notify_resolved()
                    yield from _emit_versioned_sensors(
                        scene_id=scene_id, variant=variant, node_id=vp_id,
                        heading_id=str(h_id), destination_root=destination,
                    )
                    if source_dir is not None:
                        yield from _emit_observation_dir(source_dir, destination)

        # 3b. EXR (HDR) pulled from bridge_jobs for every heading at this
        # vp. The daemon's PNG-only consolidation skipped these so we
        # mirror them under `sensors/<camera>/<modality>.exr`. This is the
        # heavy part — skipped entirely in PNG-only mode.
        if not include_exr:
            continue
        if repo_root is None:
            continue
        # bridge_jobs name pattern uses each heading individually, so we
        # iterate the heading ids discovered above. When the consolidated
        # dir is missing (no PNG was written yet), still fall back to a
        # glob for any heading matching the scene/vp.
        # A self-contained versioned bundle is authoritative; do not scan
        # the legacy bridge_jobs tree for those headings. Keep the fallback
        # for old consolidated observations that genuinely lack EXR files.
        bridge_heading_pool: list[str] = [
            h for h in heading_ids
            if str(h) not in versioned_heading_ids
            and (scene_id, vp_id, str(h)) not in source_exr_keys
        ]
        if not bridge_heading_pool and not versioned_heading_ids:
            if panorama_observations:
                bridge_root = repo_root / "out" / "bridge_jobs"
                if bridge_root.exists():
                    for job_dir in bridge_root.glob(f"opticalnav-{scene_id}-template-{vp_id}-*"):
                        suffix = job_dir.name[len(f"opticalnav-{scene_id}-template-{vp_id}-"):]
                        parts = suffix.split("-")
                        if parts:
                            bridge_heading_pool.append(parts[0])
            # GT-only fallback when consolidated dir is empty.
            elif path_heading is not None:
                bridge_heading_pool.append(path_heading)
            bridge_heading_pool = sorted(set(bridge_heading_pool))
        for h_id in bridge_heading_pool:
            for bridge_obs in _bridge_job_observation_dirs(repo_root, scene_id, vp_id, str(h_id)):
                for src in sorted(bridge_obs.rglob("*")):
                    if not src.is_file() or src.suffix.lower() != ".exr":
                        continue
                    parts = src.parts
                    try:
                        cam_idx = parts.index("cameras")
                        camera_id = parts[cam_idx + 1]
                    except (ValueError, IndexError):
                        continue
                    if allowed_camera_ids is not None and camera_id not in allowed_camera_ids:
                        continue
                    dst_rel = (
                        f"scenes/{scene_id}/observations/{vp_id}/{h_id}/"
                        f"sensors/{camera_id}/{src.name}"
                    )
                    pair = _emit(src, dst_rel)
                    if pair is not None:
                        yield pair

def write_filtered_sensor_indexes(export_root: str | Path) -> list[Path]:
    """Rebuild per-heading sensor indexes from a filtered staging tree.

    The source index cannot be copied verbatim when camera filtering is active,
    because it would still advertise excluded cameras and files. Building it
    from staging makes the sidecar describe exactly what the ZIP contains.
    """
    root = Path(export_root)
    written: list[Path] = []
    for scene_dir in sorted((root / "scenes").glob("*")):
        if not scene_dir.is_dir():
            continue
        for observation_name in ("observations", "observations_perturbed", "observations_perturbed_active_polar"):
            observation_root = scene_dir / observation_name
            if not observation_root.is_dir():
                continue
            for sensors_dir in sorted(observation_root.glob("*/*/sensors")):
                if not sensors_dir.is_dir():
                    continue
                sensors: dict[str, dict] = {}
                for sensor_dir in sorted(sensors_dir.iterdir()):
                    if not sensor_dir.is_dir():
                        continue
                    files = sorted(
                        path.relative_to(sensor_dir).as_posix()
                        for path in sensor_dir.rglob("*")
                        if path.is_file()
                    )
                    if files:
                        sensors[sensor_dir.name] = {
                            "camera_id": sensor_dir.name,
                            "files": files,
                        }
                if not sensors:
                    continue
                index_path = sensors_dir.parent / "_sensor_index.json"
                index_path.write_text(
                    json.dumps({"sensors": sensors}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                written.append(index_path)
    return written


def build_filtered_sensor_index_payloads(destinations: Iterable[str]) -> dict[str, dict]:
    """Build filtered per-heading sensor indexes from final archive paths.

    Direct archives never materialize a full observation tree. Deriving these
    sidecars from archive members keeps their camera inventory aligned with the
    packaged payload without re-walking copied files.
    """
    grouped: dict[str, dict[str, list[str]]] = {}
    for destination in destinations:
        parts = Path(destination).parts
        try:
            sensor_index = parts.index("sensors")
        except ValueError:
            continue
        if sensor_index < 5 or sensor_index + 2 >= len(parts):
            continue
        if parts[0] != "scenes" or parts[2] not in {"observations", "observations_perturbed", "observations_perturbed_active_polar"}:
            continue
        sensor_id = parts[sensor_index + 1]
        relative = Path(*parts[sensor_index + 2:]).as_posix()
        heading_root = Path(*parts[:sensor_index]).as_posix()
        grouped.setdefault(heading_root, {}).setdefault(sensor_id, []).append(relative)
    return {
        f"{heading_root}/_sensor_index.json": {
            "sensors": {
                sensor_id: {"camera_id": sensor_id, "files": sorted(files)}
                for sensor_id, files in sorted(sensors.items())
                if files
            }
        }
        for heading_root, sensors in sorted(grouped.items())
        if sensors
    }
