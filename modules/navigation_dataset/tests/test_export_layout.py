"""Export-bundle layout regression tests for `exporters.custom_json.iter_export_files`.

Covers two behaviours added for the trainable-bundle cleanup:

* root-level observation files that duplicate a `sensors/<camera>/` file are
  dropped (the daemon writes the "primary" view both at the heading root and
  under sensors/ — the bundle should carry each modality once, per-camera);
* `include_perturbed=True` also ships the paired `observations_perturbed/` tree.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from navigation_dataset.episode_schema import EpisodeManifest
from navigation_dataset.exporters.custom_json import (
    is_episode_complete,
    iter_export_files,
    write_filtered_sensor_indexes,
)


def _episode(scene_id: str, vp: str, heading: str) -> EpisodeManifest:
    return EpisodeManifest(
        episode_id=f"{scene_id}_train_000001",
        scene_id=scene_id,
        split="train",
        start_pose=[0.0, 0.0, 0.0],
        goal_pose=[1.0, 0.0, 0.0],
        goal_region="r0",
        natural_language_instruction="go",
        trajectory=[[0.0, 0.0, 0.0]],
        actions=["stop"],
        path_nodes=[vp],
        path_headings=[heading],
    )


def _write_obs(obs_root: Path, vp: str, heading: str) -> None:
    """One viewpoint/heading with a root duplicate + two sensors."""
    hd = obs_root / vp / heading
    (hd / "sensors" / "cam_front").mkdir(parents=True, exist_ok=True)
    (hd / "sensors" / "cam_rear").mkdir(parents=True, exist_ok=True)
    # Per-camera modalities.
    (hd / "sensors" / "cam_front" / "rgb.png").write_bytes(b"front")
    (hd / "sensors" / "cam_rear" / "rgb.png").write_bytes(b"rear")
    # Root-level duplicate of the primary (cam_front) view + scene metadata.
    (hd / "rgb.png").write_bytes(b"front")
    (hd / "_sensor_index.json").write_text("{}")


def _build_project(tmp_path: Path, scene_id: str, vp: str, heading: str, *, perturbed: bool) -> Path:
    # iter_export_files derives repo_root as project_dir.parents[2]; nest accordingly.
    project_dir = tmp_path / "out" / "opticalnav" / "v0"
    scene_dir = project_dir / "scenes" / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    _write_obs(scene_dir / "observations", vp, heading)
    if perturbed:
        _write_obs(scene_dir / "observations_perturbed", vp, heading)
    return project_dir


def test_root_level_observation_duplicates_are_dropped(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_a", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=False)
    index_payload = {"scene_artifacts": [{"scene_id": scene_id}]}
    dsts = {dst for _src, dst in iter_export_files(project_dir, index_payload, [_episode(scene_id, vp, heading)])}

    base = f"scenes/{scene_id}/observations/{vp}/{heading}"
    # Per-camera modalities are kept...
    assert f"{base}/sensors/cam_front/rgb.png" in dsts
    assert f"{base}/sensors/cam_rear/rgb.png" in dsts
    # ...the root duplicate is dropped, the metadata sidecar stays.
    assert f"{base}/rgb.png" not in dsts
    assert f"{base}/_sensor_index.json" in dsts


def test_include_perturbed_ships_paired_tree(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_b", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=True)
    index_payload = {"scene_artifacts": [{"scene_id": scene_id}]}
    ep = [_episode(scene_id, vp, heading)]

    base_only = {dst for _s, dst in iter_export_files(project_dir, index_payload, ep)}
    assert not any("observations_perturbed" in d for d in base_only)

    paired = {dst for _s, dst in iter_export_files(project_dir, index_payload, ep, include_perturbed=True)}
    pbase = f"scenes/{scene_id}/observations_perturbed/{vp}/{heading}"
    assert f"{pbase}/sensors/cam_front/rgb.png" in paired
    assert f"{pbase}/rgb.png" not in paired  # same dedup applies to the perturbed tree


def test_panorama_includes_rendered_viewpoints_outside_episode_paths(tmp_path: Path) -> None:
    """Full-panorama exports are scene-wide, not episode-path scoped."""
    scene_id, vp, heading = "scene_full_graph", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=True)
    extra_vp, extra_heading = "vp_000099", "h_030"
    scene_dir = project_dir / "scenes" / scene_id
    _write_obs(scene_dir / "observations", extra_vp, extra_heading)
    _write_obs(scene_dir / "observations_perturbed", extra_vp, extra_heading)
    index_payload = {"scene_artifacts": [{"scene_id": scene_id}]}
    ep = [_episode(scene_id, vp, heading)]

    full_destinations = {
        dst for _src, dst in iter_export_files(
            project_dir,
            index_payload,
            ep,
            panorama_observations=True,
            include_perturbed=True,
        )
    }
    extra_base = f"scenes/{scene_id}/observations/{extra_vp}/{extra_heading}/sensors/cam_front/rgb.png"
    extra_perturbed = f"scenes/{scene_id}/observations_perturbed/{extra_vp}/{extra_heading}/sensors/cam_front/rgb.png"
    assert extra_base in full_destinations
    assert extra_perturbed in full_destinations

    trajectory_destinations = {
        dst for _src, dst in iter_export_files(
            project_dir,
            index_payload,
            ep,
            panorama_observations=False,
            include_perturbed=True,
        )
    }
    assert extra_base not in trajectory_destinations
    assert extra_perturbed not in trajectory_destinations


def test_camera_filter_applies_to_base_and_perturbed(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_c", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=True)
    index_payload = {"scene_artifacts": [{"scene_id": scene_id}]}
    ep = [_episode(scene_id, vp, heading)]

    filtered = {
        dst
        for _src, dst in iter_export_files(
            project_dir,
            index_payload,
            ep,
            include_perturbed=True,
            camera_ids=["cam_rear"],
        )
    }

    assert any("/sensors/cam_rear/" in dst for dst in filtered)
    assert not any("/sensors/cam_front/" in dst for dst in filtered)
    assert not any(dst.endswith("/rgb.png") and "/sensors/" not in dst for dst in filtered)
    assert not any(dst.endswith("/_sensor_index.json") for dst in filtered)


def test_filtered_sensor_index_matches_staging_tree(tmp_path: Path) -> None:
    heading_dir = tmp_path / "staging" / "scenes" / "scene_d" / "observations" / "vp_1" / "h_000"
    selected = heading_dir / "sensors" / "cam_rear"
    selected.mkdir(parents=True)
    (selected / "rgb.png").write_bytes(b"rear")

    written = write_filtered_sensor_indexes(tmp_path / "staging")

    assert written == [heading_dir / "_sensor_index.json"]
    payload = json.loads(written[0].read_text())
    assert payload == {
        "sensors": {
            "cam_rear": {
                "camera_id": "cam_rear",
                "files": ["rgb.png"],
            }
        }
    }


def test_camera_filter_applies_to_bridge_job_exr(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_e", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=False)
    bridge_obs = (
        tmp_path
        / "out"
        / "bridge_jobs"
        / f"opticalnav-{scene_id}-template-{vp}-{heading}-rgb"
        / "observations"
        / "frame_000001"
        / "cameras"
    )
    for camera_id in ("cam_front", "cam_rear"):
        camera_dir = bridge_obs / camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        (camera_dir / "rgb.exr").write_bytes(camera_id.encode())

    index_payload = {"scene_artifacts": [{"scene_id": scene_id}]}
    filtered = {
        dst
        for _src, dst in iter_export_files(
            project_dir,
            index_payload,
            [_episode(scene_id, vp, heading)],
            include_exr=True,
            camera_ids=["cam_rear"],
        )
    }

    assert any(dst.endswith("/sensors/cam_rear/rgb.exr") for dst in filtered)
    assert not any(dst.endswith("/sensors/cam_front/rgb.exr") for dst in filtered)


def test_versioned_current_pointer_is_collected_into_stable_layout(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_versioned", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=False)
    stable = project_dir / "scenes" / scene_id / "observations" / vp / heading
    # Replace the stable raster directory with a pointer-only observation.
    for child in list(stable.iterdir()):
        if child.is_dir():
            import shutil
            shutil.rmtree(child)
        else:
            child.unlink()
    render_bundle = project_dir / "scenes" / scene_id / "observations" / "versions" / "rv_test" / "base" / vp / heading
    camera_dir = render_bundle / "cameras" / "cam_front"
    camera_dir.mkdir(parents=True)
    (camera_dir / "rgb.png").write_bytes(b"versioned-rgb")
    (render_bundle / "manifest.json").write_text("{}")
    (stable / "current.json").write_text(json.dumps({
        "bundle_ref": render_bundle.relative_to(project_dir).as_posix(),
        "render_version_id": "rv_test",
    }))

    ep = _episode(scene_id, vp, heading)
    pairs = list(iter_export_files(project_dir, {"scene_artifacts": [{"scene_id": scene_id}]}, [ep]))
    destinations = {dst for _src, dst in pairs}
    base = f"scenes/{scene_id}/observations/{vp}/{heading}"
    assert f"{base}/sensors/cam_front/rgb.png" in destinations
    assert not any(dst.endswith("current.json") for dst in destinations)
    assert is_episode_complete(ep, project_dir)


def test_episode_completion_accepts_ledger_version_without_current_pointer(tmp_path: Path) -> None:
    """Daemon sweeps may have immutable bundles before a base pointer exists."""
    scene_id, vp, heading = "scene_ledger_only", "vp_000001", "h_000"
    project_dir = tmp_path / "out" / "opticalnav" / "v0"
    bundle = project_dir / "scenes" / scene_id / "observations" / "versions" / "rv_base" / "base" / vp / heading
    (bundle / "cameras" / "polar_cam").mkdir(parents=True)
    (bundle / "cameras" / "polar_cam" / "rgb.png").write_bytes(b"rendered")
    (bundle / "manifest.json").write_text("{}")

    ledger = sqlite3.connect(project_dir / "render_ledger.sqlite3")
    ledger.executescript("""
        CREATE TABLE sweep_runs (run_id TEXT PRIMARY KEY, scene_id TEXT, created_at TEXT);
        CREATE TABLE render_versions (render_version_id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE sweep_tasks (
            task_key TEXT PRIMARY KEY, run_id TEXT, render_version_id TEXT,
            variant TEXT, node_id TEXT, heading_id TEXT, state TEXT,
            ordinal INTEGER, metadata_json TEXT
        );
    """)
    ledger.execute("INSERT INTO sweep_runs VALUES ('run', ?, '2026-01-01T00:00:00Z')", (scene_id,))
    ledger.execute("INSERT INTO render_versions VALUES ('rv_base', 'ready')")
    ledger.execute(
        "INSERT INTO sweep_tasks VALUES ('task', 'run', 'rv_base', 'base', ?, ?, 'succeeded', 0, ?)",
        (vp, heading, json.dumps({"sensor_ids": ["polar_cam"]})),
    )
    ledger.commit()
    ledger.close()

    assert is_episode_complete(_episode(scene_id, vp, heading), project_dir)


def test_export_composes_sensors_from_separate_completed_versions(tmp_path: Path) -> None:
    scene_id, vp, heading = "scene_composed", "vp_000001", "h_000"
    project_dir = _build_project(tmp_path, scene_id, vp, heading, perturbed=True)
    stable = project_dir / "scenes" / scene_id / "observations" / vp / heading
    # Legacy consolidation contains cam_front, while later immutable sweeps
    # independently produced cam_rear and polar_cam.
    rear_bundle = project_dir / "scenes" / scene_id / "observations" / "versions" / "rv_rear" / "base" / vp / heading
    polar_bundle = project_dir / "scenes" / scene_id / "observations" / "versions" / "rv_polar" / "base" / vp / heading
    (rear_bundle / "cameras" / "cam_rear").mkdir(parents=True)
    (polar_bundle / "cameras" / "polar_cam").mkdir(parents=True)
    (rear_bundle / "cameras" / "cam_rear" / "rgb.png").write_bytes(b"rear-version")
    (polar_bundle / "cameras" / "polar_cam" / "stokes_data.npz").write_bytes(b"polar-version")
    (rear_bundle / "manifest.json").write_text("{}")
    (polar_bundle / "manifest.json").write_text("{}")

    ledger = sqlite3.connect(project_dir / "render_ledger.sqlite3")
    ledger.executescript("""
        CREATE TABLE sweep_runs (
            run_id TEXT PRIMARY KEY, scene_id TEXT, created_at TEXT
        );
        CREATE TABLE render_versions (
            render_version_id TEXT PRIMARY KEY, status TEXT
        );
        CREATE TABLE sweep_tasks (
            task_key TEXT PRIMARY KEY, run_id TEXT, render_version_id TEXT,
            variant TEXT, node_id TEXT, heading_id TEXT, state TEXT,
            ordinal INTEGER, metadata_json TEXT
        );
    """)
    for ordinal, (render_version, sensor_id) in enumerate((("rv_rear", "cam_rear"), ("rv_polar", "polar_cam"))):
        run_id = f"run_{ordinal}"
        ledger.execute("INSERT INTO sweep_runs VALUES (?, ?, ?)", (run_id, scene_id, f"2026-01-01T00:00:0{ordinal}Z"))
        ledger.execute("INSERT INTO render_versions VALUES (?, 'ready')", (render_version,))
        ledger.execute(
            "INSERT INTO sweep_tasks VALUES (?, ?, ?, 'base', ?, ?, 'succeeded', ?, ?)",
            (f"task_{ordinal}", run_id, render_version, vp, heading, ordinal, json.dumps({"sensor_ids": [sensor_id]})),
        )
    ledger.commit()
    ledger.close()

    pairs = list(iter_export_files(
        project_dir,
        {"scene_artifacts": [{"scene_id": scene_id}]},
        [_episode(scene_id, vp, heading)],
        include_exr=False,
        include_polarization_raw=True,
        camera_ids=["cam_front", "cam_rear", "polar_cam"],
    ))
    sources = {dst: src for src, dst in pairs}
    base = f"scenes/{scene_id}/observations/{vp}/{heading}/sensors"
    assert sources[f"{base}/cam_front/rgb.png"] == stable / "sensors" / "cam_front" / "rgb.png"
    assert sources[f"{base}/cam_rear/rgb.png"] == rear_bundle / "cameras" / "cam_rear" / "rgb.png"
    assert sources[f"{base}/polar_cam/stokes_data.npz"] == polar_bundle / "cameras" / "polar_cam" / "stokes_data.npz"
