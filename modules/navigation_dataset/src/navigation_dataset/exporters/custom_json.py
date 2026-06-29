from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Callable, Iterable
import zipfile

from ..episode_schema import DatasetProject, EpisodeManifest, read_episode, read_project, write_project


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def find_episode_files(dataset_root: str | Path) -> list[Path]:
    root = Path(dataset_root)
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


def is_episode_complete(episode: EpisodeManifest, dataset_root: Path) -> bool:
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

    Disk presence in ``scenes/<scene>/observations/<vp_id>/<heading_id>/`` is
    the source of truth — that's where ``_opticalnav_copy_observation_rgb``
    consolidates rendered modalities for every job.
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
        obs_root = project_dir / "scenes" / str(episode.scene_id) / "observations"
        if not obs_root.exists():
            return False
        for node_id, heading_id in zip(episode.path_nodes, episode.path_headings):
            heading_dir = obs_root / str(node_id) / str(heading_id)
            if not heading_dir.is_dir():
                return False
            # At least one rendered modality file present (rgb.png etc.).
            has_modality = any(
                p.is_file() and p.suffix.lower() in _OBS_FILE_SUFFIXES
                for p in heading_dir.iterdir()
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
    paths = find_episode_files(dataset_root)
    if episode_ids is None and not only_completed and scene_ids is None:
        return paths
    allow_episode = set(str(eid) for eid in episode_ids) if episode_ids is not None else None
    allow_scene = set(str(sid) for sid in scene_ids) if scene_ids is not None else None
    kept: list[Path] = []
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
            if not is_episode_complete(episode, dataset_root):
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
    project = read_project(project_path) if project_path.exists() else DatasetProject(project_name=root.name)
    scene_filter = set(str(sid) for sid in scene_ids) if scene_ids is not None else None
    episodes_by_split: dict[str, list[str]] = {"train": [], "val_seen": [], "val_unseen": [], "test": []}
    discovered_scene_ids: set[str] = set()
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
    for scene_dir in sorted((root / "scenes").glob("*")):
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
    path = root / "dataset.json"
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
    output_dir = root / "splits"
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
) -> Iterable[tuple[Path, str]]:
    """Yield (src_path, dst_relative_posix_path) pairs for the scene bundle.

    The destination layout mirrors the project tree under
    `scenes/<scene_id>/` so external readers that already understand the
    project layout work unchanged.

    `panorama_observations`:
        * True (default) — include **every heading** at each viewpoint along
          the episode path. Lets external readers consume full surround
          context per waypoint.
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

    def _emit(src: Path, dst_rel: str):
        if dst_rel in yielded_dst:
            return None
        yielded_dst.add(dst_rel)
        return (src, dst_rel)

    def _emit_observation_dir(obs_dir: Path) -> Iterable[tuple[Path, str]]:
        """Yield de-duplicated (src, dst) pairs for one consolidated <vp>/<h>/ dir.

        The daemon mirrors a "primary" view's rasters at the heading root
        (e.g. <vp>/<h>/rgb.png) *and* under `sensors/<camera>/`. The root copies
        are byte-identical to a sensors/ file, so the bundle would carry every
        primary modality twice and present an asymmetric tree (root = one camera
        only, sub-folders = all cameras). Ship per-camera modalities under
        `sensors/<camera>/` only; drop the root-level duplicates.
        """
        if not obs_dir.is_dir():
            return
        sensors_root = obs_dir / "sensors"
        sensor_file_names: set[str] = set()
        if sensors_root.is_dir():
            sensor_file_names = {p.name for p in sensors_root.rglob("*") if p.is_file()}
        for src in sorted(obs_dir.rglob("*")):
            if not src.is_file():
                continue
            # Skip a root-level observation file (directly under <vp>/<h>/)
            # when the same modality is already carried under sensors/.
            if src.parent == obs_dir and src.name in sensor_file_names:
                continue
            # PNG-only mode: drop heavy HDR/raw rasters, keep PNG + metadata.
            # Exception: keep the polarization Stokes raw (stokes_data.npz) so
            # downstream code can recompute any Stokes representation, even when
            # other .npz/.exr are dropped. Representation PNGs (s1_over_s0_*.png,
            # dop/aolp colorbars) are .png and kept regardless.
            if not include_exr and src.suffix.lower() in {".exr", ".hdr", ".npz"}:
                if not (include_polarization_raw and src.name == "stokes_data.npz"):
                    continue
            rel = src.relative_to(pdir).as_posix()
            pair = _emit(src, rel)
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
    for ep in kept_list:
        ep_path = pdir / "episodes" / ep.split / f"{ep.episode_id}.json"
        if ep_path.is_file():
            pair = _emit(ep_path, f"episodes/{ep.split}/{ep.episode_id}.json")
            if pair is not None:
                yield pair
    # 3. Observation files for every viewpoint along the episode path —
    # **all panorama headings** at that node (not just the heading the episode
    # visits), so external readers have the full surround context for each
    # waypoint. Path-specific heading order is preserved separately in
    # `thumbnails/<episode_id>/` (see worker's `generate_thumbnails` stage).
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
            vp_dir = pdir / "scenes" / str(ep.scene_id) / "observations" / str(vp_id)
            heading_ids: list[str] = []
            if vp_dir.is_dir():
                disk_headings = sorted(p.name for p in vp_dir.iterdir() if p.is_dir())
                if panorama_observations:
                    heading_ids = disk_headings
                else:
                    # GT-only: just the heading this episode visits at vp_idx.
                    if vp_idx < len(path_pairs):
                        gt_h = path_pairs[vp_idx][1]
                        if gt_h in disk_headings:
                            heading_ids = [gt_h]
            # 3a. Consolidated observation files for every heading at this vp.
            for h_id in heading_ids:
                yield from _emit_observation_dir(vp_dir / h_id)
            # 3c. Paired perturbation variant (eval split): the same viewpoints
            # rendered with the optical-perturbation overlay (mirrors/glass) live
            # under `observations_perturbed/`. Ship them alongside the base tree
            # so downstream can join base↔perturbed on identical (vp, heading).
            if include_perturbed:
                pvp_dir = pdir / "scenes" / str(ep.scene_id) / "observations_perturbed" / str(vp_id)
                if pvp_dir.is_dir():
                    p_disk = sorted(p.name for p in pvp_dir.iterdir() if p.is_dir())
                    p_headings = p_disk if panorama_observations else [h for h in heading_ids if h in p_disk]
                    for h_id in p_headings:
                        yield from _emit_observation_dir(pvp_dir / h_id)
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
            bridge_heading_pool: list[str] = list(heading_ids)
            if not bridge_heading_pool:
                if panorama_observations:
                    bridge_root = repo_root / "out" / "bridge_jobs"
                    if bridge_root.exists():
                        for job_dir in bridge_root.glob(f"opticalnav-{ep.scene_id}-template-{vp_id}-*"):
                            suffix = job_dir.name[len(f"opticalnav-{ep.scene_id}-template-{vp_id}-"):]
                            parts = suffix.split("-")
                            if parts:
                                bridge_heading_pool.append(parts[0])
                else:
                    # GT-only fallback when consolidated dir is empty.
                    if vp_idx < len(path_pairs):
                        bridge_heading_pool.append(path_pairs[vp_idx][1])
                bridge_heading_pool = sorted(set(bridge_heading_pool))
            for h_id in bridge_heading_pool:
                for bridge_obs in _bridge_job_observation_dirs(repo_root, str(ep.scene_id), str(vp_id), str(h_id)):
                    for src in sorted(bridge_obs.rglob("*")):
                        if not src.is_file() or src.suffix.lower() != ".exr":
                            continue
                        parts = src.parts
                        try:
                            cam_idx = parts.index("cameras")
                            camera_id = parts[cam_idx + 1]
                        except (ValueError, IndexError):
                            continue
                        dst_rel = (
                            f"scenes/{ep.scene_id}/observations/{vp_id}/{h_id}/"
                            f"sensors/{camera_id}/{src.name}"
                        )
                        pair = _emit(src, dst_rel)
                        if pair is not None:
                            yield pair
