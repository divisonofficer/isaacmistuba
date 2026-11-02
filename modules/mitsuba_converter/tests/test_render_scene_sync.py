from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from mitsuba_converter.render_scene_sync import RenderSceneSyncResult, sync_render_scene


def _scene(tmp_path: Path, project: str = "opticalnav-v0.2", scene: str = "scene_a") -> Path:
    scene_dir = tmp_path / "out" / "opticalnav" / project / "scenes" / scene
    scene_dir.mkdir(parents=True)
    (scene_dir / "render_scene.xml").write_text("<scene/>", encoding="utf-8")
    return scene_dir


class _FakeOutcome:
    def __init__(self, status_code: int, body: dict, overlay_shape_count: int = 0) -> None:
        self.status_code = status_code
        self.body = body
        self.overlay_shape_count = overlay_shape_count


def _install_fake_daemon(monkeypatch, outcome: _FakeOutcome, calls: list) -> None:
    """Stand in for render_daemon so the seam is tested without the renderer."""

    class _FakeDaemon:
        def __init__(self, *, repo_root):
            self.repo_root = Path(repo_root)
            calls.append(("init", self.repo_root))

        def _sync_opticalnav_render_scene(self, project_dir, scene_id, payload, *, sync_job_id, progress_cb):
            calls.append(("sync", project_dir, scene_id, dict(payload), sync_job_id))
            if progress_cb is not None:
                progress_cb(1, 2, "stage", "staging meshes")
            return outcome

    module = types.ModuleType("mitsuba_converter.render_daemon")
    module.RenderDaemon = _FakeDaemon
    monkeypatch.setitem(sys.modules, "mitsuba_converter.render_daemon", module)


def test_sync_runs_in_process_and_forwards_payload(tmp_path, monkeypatch) -> None:
    _scene(tmp_path)
    calls: list = []
    _install_fake_daemon(monkeypatch, _FakeOutcome(200, {"mesh_stats": {"glb_mesh_parts": 7}}, 12), calls)
    progress: list = []

    result = sync_render_scene(
        tmp_path, "opticalnav-v0.2", "scene_a", {"camera_rig": "rig_a"},
        sync_job_id="job-1", progress_cb=lambda *a: progress.append(a),
    )

    assert result.ok and result.status_code == 200
    assert result.mesh_stats == {"glb_mesh_parts": 7}
    assert result.overlay_shape_count == 12
    assert progress == [(1, 2, "stage", "staging meshes")]
    kind, project_dir, scene_id, payload, job = calls[1]
    assert (kind, scene_id, payload, job) == ("sync", "scene_a", {"camera_rig": "rig_a"}, "job-1")
    assert project_dir == (tmp_path / "out" / "opticalnav" / "opticalnav-v0.2").resolve()


def test_missing_scene_is_rejected_before_importing_the_renderer(tmp_path, monkeypatch) -> None:
    # No fake daemon installed: a missing scene must fail without importing it.
    monkeypatch.setitem(sys.modules, "mitsuba_converter.render_daemon", None)

    with pytest.raises(FileNotFoundError, match="scene workspace not found"):
        sync_render_scene(tmp_path, "opticalnav-v0.2", "absent")


def test_failure_surfaces_the_server_message(tmp_path, monkeypatch) -> None:
    _scene(tmp_path)
    _install_fake_daemon(monkeypatch, _FakeOutcome(409, {"error": "scene is locked"}), [])

    result = sync_render_scene(tmp_path, "opticalnav-v0.2", "scene_a")

    assert not result.ok
    assert result.error == "scene is locked"
    assert result.mesh_stats == {}


def test_failure_without_a_message_still_reports_the_status(tmp_path, monkeypatch) -> None:
    _scene(tmp_path)
    _install_fake_daemon(monkeypatch, _FakeOutcome(500, {}), [])

    assert sync_render_scene(tmp_path, "opticalnav-v0.2", "scene_a").error == "sync failed with status 500"


def test_result_is_a_plain_value(tmp_path) -> None:
    result = RenderSceneSyncResult(status_code=200, body={"mesh_stats": {"glb_missing": 3}})
    assert result.ok
    assert result.mesh_stats == {"glb_missing": 3}
    assert result.error is None


def test_concurrent_sync_of_one_scene_is_refused(tmp_path, monkeypatch) -> None:
    """The daemon's lock is process-local; this one has to cross processes."""
    import fcntl
    import os

    from mitsuba_converter.render_scene_sync import SYNC_LOCK_FILENAME, RenderSceneSyncBusy

    scene_dir = _scene(tmp_path)
    _install_fake_daemon(monkeypatch, _FakeOutcome(200, {}), [])

    held = os.open(scene_dir / SYNC_LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(RenderSceneSyncBusy, match="another process holds"):
            sync_render_scene(tmp_path, "opticalnav-v0.2", "scene_a")
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)

    # Released: the next caller gets through.
    assert sync_render_scene(tmp_path, "opticalnav-v0.2", "scene_a").ok


def test_lock_is_released_even_when_the_sync_raises(tmp_path, monkeypatch) -> None:
    from mitsuba_converter.render_scene_sync import SYNC_LOCK_FILENAME

    scene_dir = _scene(tmp_path)

    class _Boom:
        def __init__(self, *, repo_root):
            pass

        def _sync_opticalnav_render_scene(self, *a, **k):
            raise RuntimeError("stage failed")

    module = types.ModuleType("mitsuba_converter.render_daemon")
    module.RenderDaemon = _Boom
    monkeypatch.setitem(sys.modules, "mitsuba_converter.render_daemon", module)

    with pytest.raises(RuntimeError, match="stage failed"):
        sync_render_scene(tmp_path, "opticalnav-v0.2", "scene_a")

    import fcntl
    import os

    handle = os.open(scene_dir / SYNC_LOCK_FILENAME, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


def test_daemon_probe_reports_unreachable_without_a_server() -> None:
    from mitsuba_converter.render_scene_sync import daemon_is_reachable

    assert daemon_is_reachable("http://127.0.0.1:9", timeout=0.5) is False
