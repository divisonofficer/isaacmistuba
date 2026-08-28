from __future__ import annotations

import json
import io

import pytest

from mitsuba_converter.render_daemon import RenderDaemon


def _write_scene(tmp_path):
    project = tmp_path / "out" / "opticalnav" / "project"
    scene = project / "scenes" / "scene"
    mesh_cache = scene / "mesh_cache"
    textures = tmp_path / "assets"
    mesh_cache.mkdir(parents=True)
    textures.mkdir()
    mesh = mesh_cache / "source.obj"
    mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    texture = textures / "albedo.png"
    texture.write_bytes(b"png")
    (scene / "authoring_map.json").write_text(json.dumps({
        "materials": [{
            "material_id": "wood",
            "params": {"pbr": {"base_color": [0.2, 0.3, 0.4], "roughness": 0.4}},
            "render_binding": {"bsdf_strategy": "roughplastic"},
        }],
    }), encoding="utf-8")
    (scene / "render_scene_materialization.json").write_text(json.dumps({"objects": []}), encoding="utf-8")
    (scene / "render_scene.xml").write_text(
        f"""<scene version='3.0.0'><bsdf id='mat' type='roughplastic'>
        <texture name='diffuse_reflectance' type='bitmap'><string name='filename' value='{texture}'/></texture>
        </bsdf></scene>""", encoding="utf-8",
    )
    # Deliberately omit mesh_ref: old synced sidecars only recorded mesh_path.
    (scene / "xml_scene_index.json").write_text(json.dumps({"shapes": [{
        "shape_id": "shape", "shape_type": "obj", "mesh_path": str(mesh),
        "bsdf_ref": "mat", "material_id": "wood", "transform": {"translate": [1, 2, 3]},
    }]}), encoding="utf-8")
    return project, texture


def test_raster_manifest_uses_full_mesh_and_xml_texture(tmp_path) -> None:
    project, texture = _write_scene(tmp_path)
    daemon = RenderDaemon(repo_root=tmp_path)
    manifest = daemon._opticalnav_raster_scene_manifest(project, "scene")
    assert manifest["diagnostics"]["source_meshes"] == 1
    assert manifest["shapes"][0]["mesh_ref"] == "source.obj"
    material = manifest["materials"]["wood"]
    assert material["bsdf_strategy"] == "pplastic"
    assert material["textures"]["base_color"] == texture.relative_to(tmp_path).as_posix()
    assert daemon._opticalnav_raster_asset_target(material["textures"]["base_color"]) == texture


def test_raster_asset_rejects_path_escape(tmp_path) -> None:
    daemon = RenderDaemon(repo_root=tmp_path)
    with pytest.raises(ValueError):
        daemon._opticalnav_raster_asset_target("../secret.png")


def test_raster_asset_http_endpoint_sends_the_texture_bytes(tmp_path) -> None:
    class Handler:
        def __init__(self) -> None:
            self.status: int | None = None
            self.headers: dict[str, str] = {}
            self.wfile = io.BytesIO()

        def send_response(self, status: int) -> None:
            self.status = status

        def send_header(self, name: str, value: str) -> None:
            self.headers[name] = value

        def end_headers(self) -> None:
            pass

    project, texture = _write_scene(tmp_path)
    daemon = RenderDaemon(repo_root=tmp_path)
    handler = Handler()
    handled = daemon._handle_opticalnav_get(
        handler,
        "/api/opticalnav/projects/project/scenes/scene/raster-asset",
        {"ref": [texture.relative_to(tmp_path).as_posix()]},
    )
    assert handled is True
    assert handler.status == 200
    assert handler.headers["Content-Type"] == "image/png"
    assert handler.wfile.getvalue() == b"png"
