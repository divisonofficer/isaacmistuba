from __future__ import annotations

import json
from pathlib import Path

from mitsuba_converter.render_daemon import RenderDaemon


def test_export_source_fingerprint_tracks_current_pointer(tmp_path: Path) -> None:
    project = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    pointer = project / "scenes" / "scene_a" / "observations" / "vp" / "h" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"bundle_ref": "render_versions/a"}))
    daemon = RenderDaemon(repo_root=tmp_path)

    before = daemon._export_source_fingerprint(project, "scene_a")
    pointer.write_text(json.dumps({"bundle_ref": "render_versions/b"}))
    after = daemon._export_source_fingerprint(project, "scene_a")

    assert before != after


def test_startup_marks_orphaned_export_interrupted(tmp_path: Path) -> None:
    project = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    status_path = project / "exports" / "export-scene-a" / "export_status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text(json.dumps({"job_id": "export-scene-a", "status": "running"}))
    daemon = RenderDaemon(repo_root=tmp_path)

    daemon._mark_stale_export_jobs_at_startup()

    status = json.loads(status_path.read_text())
    assert status["status"] == "interrupted"
    assert status["resume_available"] is True
