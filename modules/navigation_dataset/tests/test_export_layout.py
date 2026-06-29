"""Export-bundle layout regression tests for `exporters.custom_json.iter_export_files`.

Covers two behaviours added for the trainable-bundle cleanup:

* root-level observation files that duplicate a `sensors/<camera>/` file are
  dropped (the daemon writes the "primary" view both at the heading root and
  under sensors/ — the bundle should carry each modality once, per-camera);
* `include_perturbed=True` also ships the paired `observations_perturbed/` tree.
"""
from __future__ import annotations

from pathlib import Path

from navigation_dataset.episode_schema import EpisodeManifest
from navigation_dataset.exporters.custom_json import iter_export_files


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
