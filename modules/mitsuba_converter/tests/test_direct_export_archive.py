from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from mitsuba_converter.render_daemon import RenderDaemon
from navigation_dataset.exporters.compact_bundle import POLAR_STOKES_CORE_KEYS


def _write_stokes(path: Path) -> dict[str, np.ndarray]:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {
        "rgb": np.arange(18, dtype=np.float32).reshape(2, 3, 3),
        "s0": np.full((2, 3, 3), 2.0, dtype=np.float32),
        "s1": np.full((2, 3, 3), 0.4, dtype=np.float32),
        "s2": np.full((2, 3, 3), -0.2, dtype=np.float32),
        "s3": np.zeros((2, 3, 3), dtype=np.float32),
        "mask": np.array([[True, False, True], [True, True, False]], dtype=bool),
    }
    # The legacy file contains derived products too; the direct archive must not.
    np.savez_compressed(path, **arrays, dop=np.ones((2, 3), dtype=np.float32))
    return arrays


def _fixture(tmp_path: Path) -> tuple[RenderDaemon, Path, Path, dict[str, np.ndarray], SimpleNamespace]:
    repo = tmp_path
    project = repo / "out" / "opticalnav" / "opticalnav-v0.2"
    heading = project / "scenes" / "scene_a" / "observations" / "vp_1" / "h_000"
    rgb = heading / "sensors" / "rgb_cam" / "rgb.png"
    polar = heading / "sensors" / "polar_cam"
    rgb.parent.mkdir(parents=True, exist_ok=True)
    polar.mkdir(parents=True, exist_ok=True)
    rgb.write_bytes(b"exact-rgb-png-bytes")
    (heading / "sensors" / "rgb_cam" / "rgb.exr").write_bytes(b"exr")
    (heading / "sensors" / "rgb_cam" / "rgb_raw.npz").write_bytes(b"rgb-raw")
    preview = polar / "polar_rgb_preview.png"
    preview.write_bytes(b"exact-polar-preview-bytes")
    (polar / "dop_red_black_colorbar.png").write_bytes(b"exact-dop-bytes")
    stokes = polar / "stokes_data.npz"
    arrays = _write_stokes(stokes)
    manifest = heading / "manifest.json"
    manifest.write_text(json.dumps({"artifacts": [{"artifact_paths": {
        "png": stokes.relative_to(repo).with_name("polar_rgb_preview.png").as_posix(),
        "stokes_npz": stokes.relative_to(repo).as_posix(),
        "exr": (heading / "sensors" / "rgb_cam" / "rgb.exr").relative_to(repo).as_posix(),
    }}]}))
    episode_id = "scene_a_train_000"
    episode_path = project / "episodes" / "train" / f"{episode_id}.json"
    episode_path.parent.mkdir(parents=True, exist_ok=True)
    episode_path.write_text("{}")
    episode = SimpleNamespace(
        scene_id="scene_a", split="train", episode_id=episode_id,
        path_nodes=["vp_1"], path_headings=["h_000"],
    )
    (project / "dataset.json").write_text(json.dumps({"schema": "test"}))
    daemon = RenderDaemon(repo_root=repo, render_fn=lambda *_args, **_kwargs: None)
    return daemon, project, rgb, arrays, episode


def _run_direct(
    tmp_path: Path,
    check_cancel=lambda: None,
    *,
    profile: str = "png_stokes_core",
    png_only: bool = True,
) -> tuple[Path, Path, Path, dict[str, np.ndarray]]:
    daemon, project, rgb, arrays, episode = _fixture(tmp_path)
    exports_root = project / "exports" / "job-1"
    staging = exports_root / "staging"
    staging.mkdir(parents=True)
    (staging / "dataset.json").write_text((project / "dataset.json").read_text())
    daemon._run_direct_archive_materialization(
        job_id="job-1",
        project_id="opticalnav-v0.2",
        project_dir=project,
        scene_id="scene_a",
        exports_root=exports_root,
        staging=staging,
        timestamp="20260101T000000Z",
        export_profile=profile,
        index_payload={},
        kept_episodes=[episode],
        scene_paths=[project / "episodes" / "train" / "scene_a_train_000.json"],
        episodes_kept=1,
        episodes_skipped=0,
        only_completed=False,
        panorama_observations=True,
        png_only=png_only,
        include_birdseye=False,
        include_episode_birdseye=False,
        include_polarization_raw=True,
        eval_perturbation=False,
        camera_ids=["rgb_cam", "polar_cam"],
        check_cancel=check_cancel,
        publish=lambda **_kwargs: None,
    )
    return exports_root / "scene_a_20260101T000000Z.zip", exports_root, rgb, arrays


def test_png_stokes_core_direct_archive_is_lossless_and_self_contained(tmp_path: Path) -> None:
    archive_path, exports_root, rgb, expected = _run_direct(tmp_path)

    assert archive_path.is_file()
    assert not (exports_root / "staging").exists()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        base = "scenes/scene_a/observations/vp_1/h_000"
        rgb_name = f"{base}/sensors/rgb_cam/rgb.png"
        preview_name = f"{base}/sensors/polar_cam/polar_rgb_preview.png"
        core_name = f"{base}/sensors/polar_cam/stokes_core_v1.npz"
        manifest_name = f"{base}/manifest.json"
        assert {rgb_name, preview_name, core_name, manifest_name} <= names
        assert f"{base}/sensors/rgb_cam/rgb.exr" not in names
        assert f"{base}/sensors/rgb_cam/rgb_raw.npz" not in names
        assert f"{base}/sensors/polar_cam/stokes_data.npz" not in names
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        assert archive.read(rgb_name) == rgb.read_bytes()
        with np.load(BytesIO(archive.read(core_name)), allow_pickle=False) as core:
            assert core.files == list(POLAR_STOKES_CORE_KEYS)
            for key in POLAR_STOKES_CORE_KEYS:
                assert core[key].dtype == expected[key].dtype
                assert core[key].shape == expected[key].shape
                assert core[key].tobytes(order="C") == expected[key].tobytes(order="C")
            s0_l = np.tensordot(core["s0"], np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0]))
            s1_l = np.tensordot(core["s1"], np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0]))
            assert np.allclose(s1_l / s0_l, 0.2)
        manifest = json.loads(archive.read(manifest_name))
        paths = manifest["artifacts"][0]["artifact_paths"]
        assert paths["stokes_core_v1"] == core_name
        assert "stokes_npz" not in paths
        assert "exr" not in paths
        sensor_index = json.loads(archive.read(f"{base}/_sensor_index.json"))
        assert sensor_index == {"sensors": {
            "polar_cam": {"camera_id": "polar_cam", "files": [
                "dop_red_black_colorbar.png", "polar_rgb_preview.png", "stokes_core_v1.npz",
            ]},
            "rgb_cam": {"camera_id": "rgb_cam", "files": ["rgb.png"]},
        }}


def test_legacy_full_direct_archive_preserves_raw_members(tmp_path: Path) -> None:
    archive_path, _exports_root, _rgb, _expected = _run_direct(
        tmp_path,
        profile="legacy_full",
        png_only=False,
    )
    base = "scenes/scene_a/observations/vp_1/h_000"
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert f"{base}/sensors/rgb_cam/rgb.exr" in names
        assert f"{base}/sensors/rgb_cam/rgb_raw.npz" in names
        assert f"{base}/sensors/polar_cam/stokes_data.npz" in names
        assert f"{base}/sensors/polar_cam/stokes_core_v1.npz" not in names
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())


def test_direct_archive_removes_partial_on_cancellation(tmp_path: Path) -> None:
    checks = 0

    def cancel_during_archive() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise RuntimeError("cancel test")

    with pytest.raises(RuntimeError, match="cancel test"):
        _run_direct(tmp_path, check_cancel=cancel_during_archive)
    exports_root = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2" / "exports" / "job-1"
    assert not (exports_root / "scene_a_20260101T000000Z.zip").exists()
    assert not (exports_root / "scene_a_20260101T000000Z.zip.partial").exists()
