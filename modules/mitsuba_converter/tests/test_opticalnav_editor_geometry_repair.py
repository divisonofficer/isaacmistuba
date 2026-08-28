from __future__ import annotations

import http.client
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from mitsuba_converter.editor_geometry_fallback import build_non_usd_editor_geometry
from mitsuba_converter.render_daemon import (
    RenderDaemon,
    _build_editor_preview_mesh_manifest,
    _build_xml_scene_index,
)


MIGRATION_PATH = Path(__file__).resolve().parents[3] / "apps/migrations/repair_opticalnav_editor_geometry.py"
MIGRATION_SPEC = importlib.util.spec_from_file_location("repair_opticalnav_editor_geometry", MIGRATION_PATH)
assert MIGRATION_SPEC and MIGRATION_SPEC.loader
repair = importlib.util.module_from_spec(MIGRATION_SPEC)
MIGRATION_SPEC.loader.exec_module(repair)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _authoring_map() -> dict:
    return {
        "scene_id": "scene",
        "objects": [{
            "id": "desk", "geometry": {"center": [5.0, 4.0], "size_m": [2.0, 1.0, 3.0]},
        }],
        "regions": [{"id": "floor", "geometry": {"bounds": [0.0, 0.0, 12.0, 9.0]}}],
    }


def test_non_usd_geometry_prefers_xml_native_and_avoids_proxy_objects(tmp_path: Path) -> None:
    scene_dir = tmp_path / "scene"
    _write_json(scene_dir / "authoring_map.json", _authoring_map())
    _write_json(scene_dir / "xml_scene_index.json", {"shapes": []})

    payload = build_non_usd_editor_geometry(scene_dir, "scene", usd_ref="scenes/scene/scene.usd")

    assert payload["status"] == "ready"
    assert payload["source"] == "xml_native"
    assert payload["objects"] == []
    assert payload["bounds"]["max"][0] >= 12.0


def test_repair_dry_run_and_apply_only_change_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    project_dir = repo / "out" / "opticalnav" / "project"
    scene_dir = project_dir / "scenes" / "scene"
    _write_json(project_dir / "dataset.json", {"scenes": [{"scene_id": "scene", "usd_ref": "scenes/scene/scene.usd"}]})
    _write_json(scene_dir / "scene_annotation.json", {"scene_id": "scene", "usd_ref": "scenes/scene/scene.usd"})
    _write_json(scene_dir / "authoring_map.json", _authoring_map())
    _write_json(scene_dir / "xml_scene_index.json", {"shapes": []})
    render_scene = scene_dir / "render_scene.xml"
    render_scene.write_text("<scene/>", encoding="utf-8")
    before = render_scene.read_bytes()
    monkeypatch.setattr(repair, "REPO_ROOT", repo)

    dry = repair.repair_project("project", apply=False)
    assert dry["summary"]["repaired"] == 1
    assert json.loads((scene_dir / "scene_annotation.json").read_text())["usd_ref"]
    assert not (scene_dir / "editor_geometry.json").exists()

    applied = repair.repair_project("project", apply=True)
    assert applied["summary"]["repaired"] == 1
    assert json.loads((scene_dir / "scene_annotation.json").read_text())["usd_ref"] is None
    assert json.loads((project_dir / "dataset.json").read_text())["scenes"][0]["usd_ref"] is None
    assert json.loads((scene_dir / "editor_geometry.json").read_text())["source"] == "xml_native"
    assert render_scene.read_bytes() == before
    assert (project_dir / "reports" / "editor_geometry_usd_ref_repair.json").is_file()


def test_xml_index_and_preview_manifest_publish_nested_cache_refs(tmp_path: Path) -> None:
    scene_dir = tmp_path / "scenes" / "scene"
    mesh = scene_dir / "mesh_cache" / "nested" / "part.obj"
    mesh.parent.mkdir(parents=True)
    mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    xml = f"""<scene version=\"3.0.0\"><shape type=\"obj\" id=\"shape\"><string name=\"filename\" value=\"{mesh}\"/></shape></scene>"""
    xml_path = scene_dir / "render_scene.xml"
    xml_path.write_text(xml, encoding="utf-8")
    preview = _build_editor_preview_mesh_manifest(
        xml_path,
        scene_mesh_cache_dir=scene_dir / "mesh_cache",
        repo_root=tmp_path,
    )
    index = _build_xml_scene_index(
        xml_path,
        scene_id="scene",
        preview_mesh_manifest=preview["shapes"],
        repo_root=tmp_path,
    )

    shape = index["shapes"][0]
    assert shape["mesh_ref"] == "nested/part.obj"
    assert shape["mesh_bytes"] == mesh.stat().st_size
    assert shape["preview_mesh_ref"] == "nested/part.obj"
    assert shape["preview_mesh_bytes"] == mesh.stat().st_size


def test_mesh_cache_http_handles_nested_refs_and_keeps_content_length(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    obj = repo / "out" / "opticalnav" / "project" / "scenes" / "scene" / "mesh_cache" / "nested" / "part.obj"
    obj.parent.mkdir(parents=True)
    payload = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    obj.write_bytes(payload)
    legacy = obj.parents[1] / "legacy.obj"
    legacy.write_bytes(payload)

    daemon = RenderDaemon(repo_root=repo, host="127.0.0.1", port=0)
    daemon.start()
    connection = http.client.HTTPConnection("127.0.0.1", daemon.port, timeout=5)
    base = "/api/opticalnav/projects/project/scenes/scene/mesh-cache/"
    try:
        connection.request("GET", base + quote("nested/part.obj", safe=""))
        response = connection.getresponse()
        assert response.version == 11
        assert response.status == 200
        assert int(response.getheader("Content-Length")) == len(payload)
        assert response.read() == payload

        # Same connection remains usable, and a legacy root-level reference works.
        connection.request("HEAD", base + "legacy.obj")
        response = connection.getresponse()
        assert response.status == 200
        assert int(response.getheader("Content-Length")) == len(payload)
        assert response.read() == b""

        connection.request("GET", base + quote("../outside.obj", safe=""))
        response = connection.getresponse()
        assert response.status == 400
        response.read()
    finally:
        connection.close()
        daemon.shutdown()
