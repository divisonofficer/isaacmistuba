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
    assert scenes[0]["exportable"] is True


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
