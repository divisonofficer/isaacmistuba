from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("export_opticalnav_wizard", REPO_ROOT / "apps" / "export_opticalnav_wizard.py")
assert _SPEC and _SPEC.loader
wizard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wizard)


def _scene(project: Path, scene_id: str, sensor: str = "cam") -> Path:
    scene = project / "scenes" / scene_id
    pointer = scene / "observations" / "vp_000001" / "h_000" / "current.json"
    bundle = project / "render_versions" / scene_id / "observation"
    (bundle / "sensors" / sensor).mkdir(parents=True)
    (bundle / "sensors" / sensor / "rgb.png").write_bytes(b"rgb")
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"bundle_ref": bundle.relative_to(project).as_posix()}))
    (scene / "render_scene.xml").write_text("<scene/>")
    return scene


def test_discover_scenes_sorts_newest_and_counts_active_sensors(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    old = _scene(project, "old", "rear")
    new = _scene(project, "new", "polar")
    import os
    for path in old.rglob("*"):
        if path.is_file():
            os.utime(path, (100, 100))
    for path in new.rglob("*"):
        if path.is_file():
            os.utime(path, (200, 200))

    scenes = wizard.discover_scenes(project)

    assert [row["scene_id"] for row in scenes] == ["new", "old"]
    assert scenes[0]["base"] == {"polar": 1}
    assert scenes[0]["perturbed_active_polar"] == {}
    assert scenes[0]["exportable"] is True


def test_selected_scene_discovery_does_not_touch_sibling_workspaces(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    _scene(project, "scene_a", "rear")
    _scene(project, "scene_b", "polar")
    touched: list[str] = []
    original = wizard._sensor_counts

    def tracked_counts(project_dir, scene_id, variant_dir):
        touched.append(scene_id)
        return original(project_dir, scene_id, variant_dir)

    monkeypatch.setattr(wizard, "_sensor_counts", tracked_counts)
    scenes = wizard.discover_scenes(project, scene_ids=["scene_a"])

    assert [row["scene_id"] for row in scenes] == ["scene_a"]
    assert set(touched) == {"scene_a"}


def test_format_scene_shows_active_polar_bucket() -> None:
    text = wizard._format_scene({
        "scene_id": "scene", "modified_at": 0.0,
        "base": {"rgb": 1}, "perturbed": {"polar_cam": 2},
        "perturbed_active_polar": {"polar_cam": 3}, "exportable": True,
    }, 1)
    assert "active-polar(polar_cam:3)" in text


def test_upload_skips_remote_file_with_matching_size(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "archive.zip"
    local.write_bytes(b"complete")
    called = False

    def fake_rclone(_args):
        nonlocal called
        called = True
        raise AssertionError("matching remote must not be uploaded again")

    monkeypatch.setattr(wizard, "_remote_file_size", lambda _remote: local.stat().st_size)
    monkeypatch.setattr(wizard, "_rclone", fake_rclone)
    wizard._upload_file(local, "gdrive:dataset/archive.zip")
    assert called is False


def test_upload_requests_five_second_live_rclone_stats(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "archive.zip"
    local.write_bytes(b"complete")
    sizes = iter((None, local.stat().st_size))
    calls = []

    monkeypatch.setattr(wizard, "_remote_file_size", lambda _remote: next(sizes))

    def fake_rclone(args, *, stream=False):
        calls.append((args, stream))
        return __import__("subprocess").CompletedProcess(["rclone", *args], 0, "Transferred: 1 / 1")

    monkeypatch.setattr(wizard, "_rclone", fake_rclone)
    wizard._upload_file(local, "gdrive:dataset/archive.zip")

    assert calls[0][1] is True
    stats_index = calls[0][0].index("--stats")
    assert ["--stats", "5s"] == calls[0][0][stats_index:stats_index + 2]
    assert "--stats-one-line" in calls[0][0]

def test_default_payload_uses_png_stokes_core_and_png_only() -> None:
    args = type("Args", (), {
        "cameras": None,
        "modalities": None,
        "no_polar": False,
        "no_perturbed": False,
        "thumbnails": False,
        "no_birdseye": False,
        "include_incomplete": False,
        "raw": False,
        "profile": "png_stokes_core",
        "coverage_levels": None,
    })()
    payload = wizard._choose_payload(
        {"scene_id": "scene", "camera_ids": ["rgb", "polar"]},
        non_interactive=True,
        args=args,
    )
    assert payload["export_profile"] == "png_stokes_core"
    assert payload["png_only"] is True
    assert payload["include_polarization_raw"] is True
    assert payload["include_active_polar"] is True


def test_raw_payload_requests_legacy_full_with_exr() -> None:
    args = type("Args", (), {
        "cameras": None,
        "modalities": None,
        "no_polar": False,
        "no_perturbed": False,
        "thumbnails": False,
        "no_birdseye": False,
        "include_incomplete": False,
        "raw": True,
        "profile": "png_stokes_core",
        "coverage_levels": None,
    })()
    payload = wizard._choose_payload(
        {"scene_id": "scene", "camera_ids": ["rgb", "polar"]},
        non_interactive=True,
        args=args,
    )
    assert payload["export_profile"] == "legacy_full"
    assert payload["png_only"] is False


def test_local_command_never_references_daemon_and_filters_selected_camera(tmp_path: Path) -> None:
    run_path = tmp_path / "run" / "run.json"
    run = {
        "project": "opticalnav-v0.2", "scene_id": "scene",
        "export_payload": {
            "camera_ids": ["polar_cam"], "include_polarization_raw": True,
            "eval_perturbation": True,
        },
    }
    command, bundle, archive = wizard._local_export_command(run, run_path)
    assert "8765" not in " ".join(command)
    assert command[0] == __import__("sys").executable
    assert ["--camera-ids", "polar_cam"] == command[command.index("--camera-ids"):command.index("--camera-ids") + 2]
    assert bundle == run_path.parent / "bundle"
    assert archive == run_path.parent / "bundle.zip"


def test_v4_export_universe_uses_archived_support_l0_plus_l3_not_legacy_graph(tmp_path: Path) -> None:
    scene = tmp_path / "scene"
    archive = scene / "navigation_support_archives" / "digest"
    archive.mkdir(parents=True)
    (scene / "viewpoint_graph.json").write_text(json.dumps({
        "nodes": [{"node_id": "vp_legacy", "headings": [{"heading_id": "h_000"}]}],
    }))
    common = {"profile_id": "adaptive_navigation_support_v4"}
    (archive / "support_observation_plan.json").write_text(json.dumps({
        **common,
        "render_entries": [
            {"motion_node_id": "support_pose_1", "heading_id": "h_000"},
            {"motion_node_id": "support_pose_1", "heading_id": "h_015"},
        ],
    }))
    (archive / "support_observation_expansion_l3_context_45.json").write_text(json.dumps({
        **common, "plan_kind": "observation_expansion",
        "render_entries": [{"motion_node_id": "support_pose_2", "heading_id": "h_030"}],
    }))
    (scene / "support_l3_submission_example.json").write_text(json.dumps({"plan_dir": "navigation_support_archives/digest"}))

    keys, universe = wizard._current_export_view_universe(scene)

    assert keys == {("support_pose_1", "h_000"), ("support_pose_1", "h_015"), ("support_pose_2", "h_030")}
    assert universe["kind"] == "adaptive_navigation_support_v4"
    assert "submission" in universe["source"]


def test_v4_stokes_batch_expands_representative_task_to_heading_bundles(tmp_path: Path) -> None:
    project = tmp_path / "project"
    root = project / "scenes" / "scene" / "observations" / "versions" / "rv" / "base" / "support_pose_1"
    for heading in ("h_000", "h_015", "h_030", "h_045"):
        path = root / heading
        path.mkdir(parents=True)
        (path / "manifest.json").write_text("{}")
    expected = {("support_pose_1", heading) for heading in ("h_000", "h_015", "h_030", "h_045")}
    result = wizard._v4_heading_batch_bundles(
        project, root / "h_000", {
            "stokes_heading_batch_view_keys": [
                {"node_id": "support_pose_1", "heading_id": heading}
                for heading in ("h_000", "h_015", "h_030", "h_045")
            ],
        }, default_key=("support_pose_1", "h_000"), expected=expected,
    )
    assert {key for key, _ in result} == expected


def test_coverage_levels_override_the_l0_plan_universe(tmp_path: Path) -> None:
    scene = tmp_path / "scene"
    scene.mkdir(parents=True)
    common = {"profile_id": "adaptive_navigation_support_v4"}
    (scene / "support_observation_plan.json").write_text(json.dumps({
        **common,
        "render_entries": [
            {"motion_node_id": f"support_pose_{index}", "heading_id": "h_000"}
            for index in range(1, 5)
        ],
    }))
    (scene / "support_sweep_coverage_sv1_episode_headings.json").write_text(json.dumps({
        **common, "level_id": "sv1_episode_headings",
        "render_entries": [{"motion_node_id": "support_pose_1", "heading_id": "h_000"}],
    }))
    (scene / "support_sweep_coverage_sv2_base_panorama_12.json").write_text(json.dumps({
        **common, "level_id": "sv2_base_panorama_12",
        "render_entries": [
            {"motion_node_id": "support_pose_1", "heading_id": "h_000"},
            {"motion_node_id": "support_pose_2", "heading_id": "h_000"},
        ],
    }))

    l0_keys, l0_universe = wizard._current_export_view_universe(scene)
    assert len(l0_keys) == 4
    assert "coverage_levels" not in l0_universe

    keys, universe = wizard._current_export_view_universe(
        scene, coverage_levels=["sv1_episode_headings", "sv2_base_panorama_12"],
    )

    # sv1 is a subset of sv2: the union is the campaign, not the sum.
    assert keys == {("support_pose_1", "h_000"), ("support_pose_2", "h_000")}
    assert universe["kind"] == "adaptive_navigation_support_v4"
    assert universe["coverage_levels"] == ["sv1_episode_headings", "sv2_base_panorama_12"]


def test_unknown_coverage_level_is_rejected(tmp_path: Path) -> None:
    scene = tmp_path / "scene"
    scene.mkdir(parents=True)
    for level in ("sv9_missing", "../escape"):
        try:
            wizard._current_export_view_universe(scene, coverage_levels=[level])
        except RuntimeError:
            continue
        raise AssertionError(f"{level} should be rejected")


def test_orphan_bundles_are_adopted_newest_version_first(tmp_path: Path) -> None:
    project = tmp_path / "project"
    versions = project / "scenes" / "scene" / "observations" / "versions"
    for version in ("rv_20260101T000000_a", "rv_20260202T000000_b"):
        path = versions / version / "perturbed" / "support_pose_1" / "h_000"
        path.mkdir(parents=True)
        (path / "manifest.json").write_text(json.dumps({
            "artifacts": [{"camera_id": "polar_cam", "modality": "dop"}],
        }))
    # A view with no bundle anywhere must stay missing rather than be invented.
    expected = {("support_pose_1", "h_000"), ("support_pose_2", "h_000")}
    chosen: dict = {}

    adopted = wizard._adopt_orphan_bundles(
        project, scene_id="scene", variant="perturbed", expected=expected, chosen=chosen,
    )

    assert adopted == 1
    assert set(chosen) == {("support_pose_1", "h_000")}
    bundle_ref, render_version_id, _, sensors = chosen[("support_pose_1", "h_000")]
    assert render_version_id == "rv_20260202T000000_b"
    assert bundle_ref.endswith("rv_20260202T000000_b/perturbed/support_pose_1/h_000")
    assert sensors == ("polar_cam",)


def test_local_export_command_forwards_selected_modalities(tmp_path: Path) -> None:
    run_path = tmp_path / "run" / "run.json"
    run_path.parent.mkdir(parents=True)
    run = {
        "run_id": "r", "project": "opticalnav-v0.2", "scene_id": "scene",
        "export_payload": {"camera_ids": ["polar_cam"], "modalities": ["s0"]},
    }
    command, _, _ = wizard._local_export_command(run, run_path)
    index = command.index("--modalities")
    assert command[index:index + 2] == ["--modalities", "s0"]
    assert "--polarization-raw-format" in command
    assert command[command.index("--polarization-raw-format") + 1] == "minimal-f16"
