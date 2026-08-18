from __future__ import annotations

import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location("export_ir_dataset", REPO_ROOT / "apps" / "export_ir_dataset.py")
assert _SPEC is not None and _SPEC.loader is not None
_EXPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORT)


def test_effective_scene_assets_are_copied_and_rewritten_bundle_relative(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "mesh.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    (source / "texture.png").write_bytes(b"not-a-real-png-but-an-asset")
    effective = tmp_path / "effective"
    effective.mkdir()
    (effective / "render_scene.xml").write_text(
        '<scene><bsdf type="diffuse" id="m"><texture type="bitmap" name="reflectance">'
        '<string name="filename" value="texture.png"/></texture></bsdf>'
        '<shape type="obj" id="s"><string name="filename" value="mesh.obj"/><ref id="m"/></shape></scene>',
        encoding="utf-8",
    )
    (effective / "ir_scene_domain.json").write_text(
        json.dumps({"source_scene_dir": str(source)}), encoding="utf-8"
    )
    (effective / "xml_scene_index.json").write_text(
        json.dumps({"shapes": [{"mesh_path": "mesh.obj"}]}), encoding="utf-8"
    )
    (effective / "render_scene_material_policy.json").write_text("{}", encoding="utf-8")
    (effective / "material_canonical.json").write_text(
        json.dumps({"materials": [{"parameters": {"base_color": {"path": "texture.png"}}}]}),
        encoding="utf-8",
    )
    target = tmp_path / "bundle_scene"

    report = _EXPORT._copy_effective_scene(effective, target)

    assert report["copied_asset_count"] == 2
    root = ET.parse(target / "render_scene.xml").getroot()
    refs = [node.get("value") for node in root.findall('.//string[@name="filename"]')]
    assert all(ref and not Path(ref).is_absolute() and (target / ref).is_file() for ref in refs)
    index = json.loads((target / "xml_scene_index.json").read_text(encoding="utf-8"))
    assert (target / index["shapes"][0]["mesh_path"]).is_file()
