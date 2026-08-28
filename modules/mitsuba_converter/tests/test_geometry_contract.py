from __future__ import annotations

from pathlib import Path

from mitsuba_converter.geometry_contract import audit_scene_geometry_contract
from mitsuba_converter.render_daemon import _apply_scene_geometry_overrides


def _scene_dir(tmp_path: Path) -> Path:
    scene = tmp_path / "out" / "opticalnav" / "v0" / "scenes" / "scene"
    scene.mkdir(parents=True)
    return scene


def test_geometry_contract_reports_missing_obj_uv(tmp_path: Path) -> None:
    scene = _scene_dir(tmp_path)
    mesh = scene / "bad.obj"
    mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    (scene / "render_scene.xml").write_text(
        '<scene><!--opticalnav-obj:{"id":"kitchen"}--><shape type="obj"><string name="filename" value="%s" /></shape></scene>' % mesh,
        encoding="utf-8",
    )

    report = audit_scene_geometry_contract(scene, {"objects": [{"id": "kitchen", "source_ref": str(mesh)}]})

    record = report["objects"][0]
    assert record["status"] == "needs_override"
    assert record["obj_parts"][0]["faces_without_uv"] == 1


def test_geometry_override_promotes_only_requested_object(tmp_path: Path) -> None:
    scene = _scene_dir(tmp_path)
    (scene / "geometry_overrides.json").write_text(
        '{"overrides":[{"object_id":"kitchen","source_ref":"out/full.glb","reason":"uv"}]}', encoding="utf-8"
    )
    payload = {"objects": [{"id": "kitchen", "source_ref": "out/lod.glb"}, {"id": "other", "source_ref": "out/other.glb"}]}

    applied, report = _apply_scene_geometry_overrides(payload, scene)

    assert applied["objects"][0]["source_ref"] == "out/full.glb"
    assert applied["objects"][1]["source_ref"] == "out/other.glb"
    assert report["applied"][0]["object_id"] == "kitchen"
