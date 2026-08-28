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


def test_google_drive_upload_request_rejects_raw_remote_and_path_escape(monkeypatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_EXPORT_GDRIVE_REMOTE", "gdrive:")
    assert RenderDaemon._normalize_export_upload({
        "enabled": True,
        "target": "google_drive",
        "destination_subpath": "dataset/opticalnav",
    }) == {
        "enabled": True,
        "target": "google_drive",
        "remote_alias": "gdrive:",
        "destination_subpath": "dataset/opticalnav",
    }
    for invalid in ("../escape", "/absolute", "a//b"):
        try:
            RenderDaemon._normalize_export_upload({
                "enabled": True,
                "target": "google_drive",
                "destination_subpath": invalid,
            })
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected path rejection for {invalid!r}")
    try:
        RenderDaemon._normalize_export_upload({"enabled": True, "target": "gdrive:arbitrary"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected target rejection")


def test_rclone_progress_parser_keeps_rate_and_eta() -> None:
    parsed = RenderDaemon._parse_rclone_progress(
        "Transferred:    1.250 GiB / 5.000 GiB, 25%, 64.000 MiB/s, ETA 1m0s"
    )
    assert parsed["transferred"] == "1.250 GiB"
    assert parsed["total"] == "5.000 GiB"
    assert parsed["rate"] == "64.000 MiB/s"
    assert parsed["eta"] == "1m0s"


def test_upload_checkpoint_resumes_verified_files_without_recopy(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    project = repo / "out" / "opticalnav" / "opticalnav-v0.2"
    exports = project / "exports" / "export-scene-a"
    exports.mkdir(parents=True)
    archive = exports / "scene_core.zip"
    archive.write_bytes(b"archive-bytes")
    archive_ref = archive.relative_to(repo).as_posix()
    report = {
        "scene_id": "scene-a",
        "export_profile": "compact_with_polar_extension",
        "archives": [{"kind": "dataset_core", "zip_ref": archive_ref, "bytes": archive.stat().st_size}],
    }
    (exports / "export_report.json").write_text(json.dumps(report))
    (exports / "export_file_manifest.json").write_text(json.dumps({"archives": report["archives"]}))
    daemon = RenderDaemon(repo_root=repo)
    remote_sizes: dict[str, int] = {}
    calls: list[str] = []

    monkeypatch.setattr(daemon, "_rclone_remote_file_size", lambda remote: remote_sizes.get(remote))

    def fake_copy(local: Path, remote: str, *, check_cancel, on_progress) -> str:
        calls.append(local.name)
        on_progress({"raw": "Transferred: 1 B / 1 B, 100%, 1 B/s, ETA 0s", "rate": "1 B/s", "eta": "0s"})
        remote_sizes[remote] = local.stat().st_size
        return "ok"

    monkeypatch.setattr(daemon, "_rclone_copy_file", fake_copy)
    progress: list[dict] = []
    upload = {"enabled": True, "target": "google_drive", "remote_alias": "gdrive:", "destination_subpath": "dataset/opticalnav"}
    first = daemon._run_export_upload(
        job_id="export-scene-a", project_dir=project, scene_id="scene-a", exports_root=exports,
        upload=upload, report=report, archives=[archive], check_cancel=lambda: None,
        publish=lambda **payload: progress.append(payload),
    )

    assert first["remote_dir"] == "gdrive:dataset/opticalnav/scene-a/export-scene-a/"
    assert set(calls) == {"scene_core.zip", "export_report.json", "export_file_manifest.json", "_SUCCESS.json"}
    assert all(item["verified"] for item in first["files"].values())
    calls.clear()
    second = daemon._run_export_upload(
        job_id="export-scene-a", project_dir=project, scene_id="scene-a", exports_root=exports,
        upload=upload, report=report, archives=[archive], check_cancel=lambda: None,
        publish=lambda **payload: progress.append(payload),
    )
    assert calls == []
    assert second["files"]["scene_core.zip"]["sha256"] == first["files"]["scene_core.zip"]["sha256"]
    assert any(item.get("stage") == "verify_remote" for item in progress)


def test_upload_rejects_remote_size_mismatch(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "out" / "opticalnav" / "opticalnav-v0.2"
    exports = project / "exports" / "export-scene-a"
    exports.mkdir(parents=True)
    archive = exports / "scene_core.zip"
    archive.write_bytes(b"archive-bytes")
    report = {
        "scene_id": "scene-a",
        "export_profile": "compact_with_polar_extension",
        "archives": [{"kind": "dataset_core", "zip_ref": archive.relative_to(tmp_path).as_posix(), "bytes": archive.stat().st_size}],
    }
    (exports / "export_report.json").write_text(json.dumps(report))
    (exports / "export_file_manifest.json").write_text("{}")
    daemon = RenderDaemon(repo_root=tmp_path)
    monkeypatch.setattr(daemon, "_rclone_remote_file_size", lambda _remote: 0)
    monkeypatch.setattr(daemon, "_rclone_copy_file", lambda *_args, **_kwargs: "copy returned")

    try:
        daemon._run_export_upload(
            job_id="export-scene-a", project_dir=project, scene_id="scene-a", exports_root=exports,
            upload={"enabled": True, "target": "google_drive", "remote_alias": "gdrive:", "destination_subpath": "dataset/opticalnav"},
            report=report, archives=[archive], check_cancel=lambda: None, publish=lambda **_payload: None,
        )
    except RuntimeError as exc:
        assert "size verification failed" in str(exc)
    else:
        raise AssertionError("expected remote-size mismatch rejection")


def test_eval_perturbation_requires_pair_complete() -> None:
    RenderDaemon._assert_complete_perturbation_pairs(
        {"perturbation_pairs": {"pair_count": 1, "unpaired_base": [], "unpaired_perturbed": []}}, enabled=True,
    )
    try:
        RenderDaemon._assert_complete_perturbation_pairs(
            {"perturbation_pairs": {"pair_count": 0, "unpaired_base": [], "unpaired_perturbed": []}}, enabled=True,
        )
    except ValueError as exc:
        assert "no matched" in str(exc)
    else:
        raise AssertionError("expected empty pair rejection")
    try:
        RenderDaemon._assert_complete_perturbation_pairs(
            {"perturbation_pairs": {"pair_count": 1, "unpaired_base": ["base"], "unpaired_perturbed": []}}, enabled=True,
        )
    except ValueError as exc:
        assert "complete base" in str(exc)
    else:
        raise AssertionError("expected incomplete pair rejection")
