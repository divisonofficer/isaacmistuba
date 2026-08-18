from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mitsuba_converter import render_daemon as rd
from mitsuba_converter.render_daemon import RenderDaemon
from navigation_dataset.authoring_compile import compile_authoring_map
from navigation_dataset.authoring_map import save_authoring_map
from navigation_dataset.scene_annotations import write_scene_annotation
from navigation_dataset.scene_sync import compute_authoring_source_hash


def _authoring_map(scene_id: str = "gate_test") -> dict:
    return {
        "version": "opticalnav-authoring-map-v0.2",
        "scene_id": scene_id,
        "unit": "meter",
        "floorplan_ref": f"/api/scenes/{scene_id}/floorplan",
        "objects": [{
            "id": "wall_001", "type": "glass_wall", "label": "base wall", "placement": "line",
            "geometry": {
                "type": "line", "start": [0.0, 0.0], "end": [2.0, 0.0],
                "height_m": 2.0, "thickness_m": 0.1,
            },
            "material": "clear_glass", "navigation": {"blocks_navigation": True},
        }],
        "regions": [
            {
                "id": "floor", "type": "traversable", "label": "floor", "placement": "rectangle",
                "geometry": {"type": "rectangle", "bounds": [0.0, 0.0, 3.0, 3.0]},
                "navigation": {"blocks_navigation": False},
            },
            {
                "id": "goal", "type": "goal", "label": "goal", "placement": "rectangle",
                "geometry": {"type": "rectangle", "bounds": [2.0, 2.0, 2.5, 2.5]},
                "navigation": {"goal_candidate": True},
            },
        ],
        "materials": [], "settings": {}, "metadata": {},
    }


def _scene_daemon(tmp_path: Path) -> tuple[RenderDaemon, Path, Path]:
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "project"
    scene_dir = project_dir / "scenes" / "gate_test"
    scene_dir.mkdir(parents=True)
    payload = _authoring_map()
    save_authoring_map(scene_dir / "authoring_map.json", payload)
    write_scene_annotation(scene_dir / "scene_annotation.json", compile_authoring_map(payload).annotation)
    daemon = RenderDaemon(repo_root=repo_root)
    # Project summary is outside this focused scene-sync contract and would
    # otherwise require a complete OpticalNav project layout in every fixture.
    daemon._opticalnav_project_summary = lambda _project: {}  # type: ignore[method-assign]
    return daemon, project_dir, scene_dir


def _sync(daemon: RenderDaemon, project_dir: Path):
    return daemon._sync_opticalnav_render_scene(
        project_dir, "gate_test", {}, sync_job_id=None, progress_cb=None,
    )


def test_authoring_source_hash_is_stable_across_key_order() -> None:
    assert compute_authoring_source_hash({"b": [2, {"a": 1}], "a": "x"}) == compute_authoring_source_hash(
        {"a": "x", "b": [2, {"a": 1}]},
    )


def test_scene_texture_profile_overrides_daemon_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "1024")
    assert rd._render_scene_texture_gate_config()["max_resolution"] == 1024
    config = rd._render_scene_texture_gate_config({
        "settings": {"render_texture_max_resolution": 512},
    })
    assert config["max_resolution"] == 512
    assert config["source"] == "scene"


def test_obj_stage_records_cache_and_normalization_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source.obj"
    source.write_text("v 10 0 5\nv 11 0 5\nv 10 1 5\nvn 0 0 0\nf 1//1 2//1 3//1\n", encoding="utf-8")
    xml = tmp_path / "render_scene.xml"
    xml.write_text(
        f'<scene version="3.0.0"><shape type="obj"><string name="filename" value="{source}"/></shape></scene>',
        encoding="utf-8",
    )

    stats = rd._stage_xml_obj_filenames_to_scene_mesh_cache(
        xml, scene_mesh_cache_dir=tmp_path / "mesh_cache", repo_root=tmp_path,
    )
    assert stats["staged"] == 1
    assert stats["source_bytes"] == source.stat().st_size
    assert stats["cache_bytes"] > 0
    assert stats["offset_nonzero"] == 1
    assert stats["normal_repaired"] == 1
    assert stats["elapsed_ms"] >= 0


def test_glb_parts_preserve_assembly_relative_positions(tmp_path: Path) -> None:
    low = tmp_path / "low.obj"
    high = tmp_path / "high.obj"
    low.write_text(
        "v -1 0 -1\nv 1 0 -1\nv 0 0.5 1\nvn 0 0 0\nf 1//1 2//1 3//1\n",
        encoding="utf-8",
    )
    high.write_text(
        "v -1 2 -1\nv 1 2 -1\nv 0 2.5 1\nvn 0 1 0\nf 1//1 2//1 3//1\n",
        encoding="utf-8",
    )
    xml = tmp_path / "render_scene.xml"
    xml.write_text(
        '<scene version="3.0.0">'
        f'<shape type="obj" id="cabinet__part_low"><string name="filename" value="{low}"/></shape>'
        f'<shape type="obj" id="cabinet__part_high"><string name="filename" value="{high}"/></shape>'
        '</scene>',
        encoding="utf-8",
    )
    records = [
        {"shape_id": "cabinet__part_low", "source_type": "glb_part"},
        {"shape_id": "cabinet__part_high", "source_type": "glb_part"},
    ]

    stats = rd._stage_xml_obj_filenames_to_scene_mesh_cache(
        xml, scene_mesh_cache_dir=tmp_path / "mesh_cache", repo_root=tmp_path,
        materialization_records=records,
    )

    tree = ET.parse(xml)
    staged = [Path(node.get("value")) for node in tree.findall(".//string[@name='filename']")]
    ys = []
    for path in staged:
        ys.extend(
            float(line.split()[2]) for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("v ")
        )
    assert min(ys) == pytest.approx(0.0)
    assert max(ys) == pytest.approx(2.5)
    assert stats["preserved_positions"] == 2
    assert stats["offset_nonzero"] == 0
    assert stats["normal_repaired"] == 1


def test_safe_glb_part_is_reused_without_staging_copy(tmp_path: Path) -> None:
    source = tmp_path / "canonical.obj"
    source.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3//1\n", encoding="utf-8")
    xml = tmp_path / "render_scene.xml"
    xml.write_text(
        '<scene version="3.0.0"><shape type="obj" id="safe">'
        f'<string name="filename" value="{source}"/></shape></scene>',
        encoding="utf-8",
    )
    stats = rd._stage_xml_obj_filenames_to_scene_mesh_cache(
        xml, scene_mesh_cache_dir=tmp_path / "mesh_cache", repo_root=tmp_path,
        materialization_records=[{"shape_id": "safe", "source_type": "glb_part_safe"}],
    )
    filename = Path(ET.parse(xml).find(".//string[@name='filename']").get("value"))
    assert filename == source.resolve()
    assert stats["staged"] == 0
    assert stats["canonical_safe_reused"] == 1
    assert not list((tmp_path / "mesh_cache").glob("*.obj"))


def test_preview_heavy_part_uses_metadata_without_scanning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "heavy.obj"
    source.write_text("v 0 0 0\n", encoding="utf-8")
    xml = tmp_path / "render_scene.xml"
    xml.write_text(
        '<scene version="3.0.0"><shape type="obj" id="heavy">'
        f'<string name="filename" value="{source}"/></shape></scene>',
        encoding="utf-8",
    )
    monkeypatch.setattr(rd, "_scan_obj_bounds_and_faces", lambda _path: pytest.fail("heavy OBJ was scanned"))
    manifest = rd._build_editor_preview_mesh_manifest(
        xml, scene_mesh_cache_dir=tmp_path / "mesh_cache", repo_root=tmp_path,
        materialization_records=[{
            "shape_id": "heavy", "source_type": "glb_part_safe", "material_id": "wood",
            "extras": {"triangle_count": 500_000, "bounds": {"min": [0, 0, 0], "max": [1, 2, 3]}},
        }],
    )
    assert manifest["shapes"]["heavy"]["preview_mesh_status"] == "skipped_heavy_source"
    assert manifest["stats"]["heavy_skipped_from_metadata"] == 1


def test_render_scene_sync_requests_are_deduplicated_and_latest_wins(tmp_path: Path) -> None:
    daemon, project_dir, scene_dir = _scene_daemon(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_sync(_project, _scene, _payload, *, sync_job_id, progress_cb):
        calls.append(daemon._render_scene_sync_fingerprint(project_dir, "gate_test", _payload))
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return int(200), {"ok": True, "sync_job_id": sync_job_id}

    daemon._run_render_scene_sync_inner = fake_sync  # type: ignore[method-assign]
    first = daemon._accept_render_scene_sync(project_dir, "gate_test", {})
    assert started.wait(5)
    duplicate = daemon._accept_render_scene_sync(project_dir, "gate_test", {})
    assert duplicate["sync_job_id"] == first["sync_job_id"]
    assert duplicate["deduplicated"] is True

    payload = json.loads((scene_dir / "authoring_map.json").read_text(encoding="utf-8"))
    payload["settings"] = {"revision": 2}
    (scene_dir / "authoring_map.json").write_text(json.dumps(payload), encoding="utf-8")
    latest = daemon._accept_render_scene_sync(project_dir, "gate_test", {})
    assert latest["sync_job_id"] == first["sync_job_id"]
    assert latest["coalesced"] is True
    assert latest["revision"] == 2
    release.set()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = daemon._opticalnav_sync_progress.get(first["sync_job_id"], {})
        if state.get("status") == "done":
            break
        time.sleep(0.01)
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert daemon._opticalnav_sync_progress[first["sync_job_id"]]["revision"] == 2


def test_sync_gate_reuses_base_and_adds_proxy_perturbation_without_restaging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon, project_dir, scene_dir = _scene_daemon(tmp_path)
    calls = {"base_emit": 0, "stage": 0, "preview": 0}
    original_emit = rd._generate_opticalnav_render_scene_xml
    original_stage = rd._stage_xml_obj_filenames_to_scene_mesh_cache
    original_preview = rd._build_editor_preview_mesh_manifest

    def emit(*args, **kwargs):
        if Path(args[2]).name == "render_scene.xml":
            calls["base_emit"] += 1
        return original_emit(*args, **kwargs)

    def stage(*args, **kwargs):
        calls["stage"] += 1
        return original_stage(*args, **kwargs)

    def preview(*args, **kwargs):
        calls["preview"] += 1
        return original_preview(*args, **kwargs)

    monkeypatch.setattr(rd, "_generate_opticalnav_render_scene_xml", emit)
    monkeypatch.setattr(rd, "_stage_xml_obj_filenames_to_scene_mesh_cache", stage)
    monkeypatch.setattr(rd, "_build_editor_preview_mesh_manifest", preview)

    first = _sync(daemon, project_dir)
    assert first.body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"
    base_xml = (scene_dir / "render_scene.xml").read_text(encoding="utf-8")
    assert "opticalnav-obj:" in base_xml
    baseline = dict(calls)

    second = _sync(daemon, project_dir)
    assert second.body["mesh_extraction_stats"]["sync_mode"] == "reuse_all"
    assert calls == baseline

    # The additive path starts from this base document, so it must retain
    # pre-existing OBJ filenames rather than recreate a base mesh cache.
    base_tree = ET.parse(scene_dir / "render_scene.xml")
    base_root = base_tree.getroot()
    base_obj = ET.SubElement(base_root, "shape", {"type": "obj", "id": "base_obj"})
    ET.SubElement(base_obj, "string", {"name": "filename", "value": "/tmp/keep-base.obj"})
    base_tree.write(scene_dir / "render_scene.xml", encoding="utf-8", xml_declaration=True)
    base_xml = (scene_dir / "render_scene.xml").read_text(encoding="utf-8")

    (scene_dir / "optical_perturbation.json").write_text(json.dumps({
        "enabled": True,
        "objects": [{
            "id": "mirror_delta", "type": "mirror_wall", "placement": "line",
            "geometry": {
                "type": "line", "start": [0.5, 0.5], "end": [1.5, 0.5],
                "height_m": 2.0, "thickness_m": 0.1,
            },
            "material": "mirror",
        }],
    }), encoding="utf-8")
    third = _sync(daemon, project_dir)
    assert third.body["mesh_extraction_stats"]["sync_mode"] == "perturbation_only_rebuild"
    assert third.body["mesh_extraction_stats"]["perturbed_scene"]["mode"] == "additive"
    assert calls["base_emit"] == baseline["base_emit"]
    assert calls["stage"] == baseline["stage"]
    assert calls["preview"] == baseline["preview"]

    base_root = ET.fromstring(base_xml)
    perturbed_root = ET.parse(scene_dir / "render_scene_perturbed.xml").getroot()
    base_shape_ids = {shape.get("id") for shape in base_root.findall("./shape")}
    perturbed_shape_ids = {shape.get("id") for shape in perturbed_root.findall("./shape")}
    assert base_shape_ids <= perturbed_shape_ids
    assert any("mirror_delta" in str(shape_id) for shape_id in perturbed_shape_ids - base_shape_ids)
    assert perturbed_root.find("./shape[@id='base_obj']/string[@name='filename']").get("value") == "/tmp/keep-base.obj"
    bsdf_ids = [node.get("id") for node in perturbed_root.findall("./bsdf") if node.get("id")]
    assert len(bsdf_ids) == len(set(bsdf_ids))


def test_gate_invalidates_missing_sidecar_and_texture_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    daemon, project_dir, scene_dir = _scene_daemon(tmp_path)
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "reuse_all"

    (scene_dir / "render_scene_sync_gate.json").unlink()
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "reuse_all"

    (scene_dir / "material_canonical.json").unlink()
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"
    assert (scene_dir / "render_scene_sync_gate.json").is_file()

    monkeypatch.setenv("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "777")
    assert _sync(daemon, project_dir).body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"


def test_source_backed_perturbation_uses_compatibility_fallback(tmp_path: Path) -> None:
    daemon, project_dir, scene_dir = _scene_daemon(tmp_path)
    _sync(daemon, project_dir)
    (scene_dir / "optical_perturbation.json").write_text(json.dumps({
        "enabled": True,
        "objects": [{
            "id": "unsupported_delta", "type": "prop", "placement": "point",
            "geometry": {"type": "point", "center": [1.0, 1.0]},
            "source_ref": "assets/does-not-exist.obj",
        }],
    }), encoding="utf-8")
    outcome = _sync(daemon, project_dir)
    assert outcome.body["mesh_extraction_stats"]["sync_mode"] == "perturbation_only_rebuild"
    assert outcome.body["mesh_extraction_stats"]["perturbed_scene"]["mode"] == "full_fallback"


def test_canonicalization_failure_blocks_and_never_publishes_a_reuse_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon, project_dir, scene_dir = _scene_daemon(tmp_path)
    original = rd.canonicalize_materials
    monkeypatch.setattr(rd, "canonicalize_materials", lambda _slots: (_ for _ in ()).throw(RuntimeError("canonical boom")))
    blocked = _sync(daemon, project_dir)
    assert blocked.body["render_readiness"]["status"] == "blocked"
    assert not (scene_dir / "render_scene_sync_gate.json").exists()

    monkeypatch.setattr(rd, "canonicalize_materials", original)
    retry = _sync(daemon, project_dir)
    assert retry.body["mesh_extraction_stats"]["sync_mode"] == "full_rebuild"
    assert (scene_dir / "render_scene_sync_gate.json").is_file()


def test_top_level_post_500_prints_traceback_and_records_debug_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    class Handler:
        path = "/api/opticalnav/test-boom"

    daemon = RenderDaemon(repo_root=tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(daemon, "_proxy_to_render_queue", lambda *_args: False)
    monkeypatch.setattr(daemon, "_read_request_body", lambda _handler: {})
    monkeypatch.setattr(daemon, "_handle_opticalnav_post", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(daemon, "_send_json", lambda _handler, status, body: captured.update(status=int(status), body=body))

    daemon._handle_post(Handler())

    stderr = capsys.readouterr().err
    assert "[http] unhandled POST /api/opticalnav/test-boom: RuntimeError: boom" in stderr
    assert "RuntimeError: boom" in stderr
    assert captured == {"status": 500, "body": {"error": "boom"}}
    assert any(event["kind"] == "error" and "unhandled POST" in event["message"] for event in daemon._debug_events)
