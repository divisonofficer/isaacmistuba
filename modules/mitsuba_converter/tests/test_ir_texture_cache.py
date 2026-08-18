import json
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from mitsuba_converter.multimodal import cap_scene_texture_resolution


def test_ir_texture_cap_rewrites_only_derived_xml_to_host_cache(tmp_path):
    """A render cap must preserve the source atlas and make a bounded copy."""
    source = tmp_path / "source_atlas.png"
    Image.new("RGB", (32, 16), color=(17, 34, 51)).save(source)
    scene = tmp_path / "scene.xml"
    scene.write_text(
        "<scene version='3.0.0'><texture type='bitmap' id='atlas'>"
        f"<string name='filename' value='{source}'/>"
        "</texture></scene>",
        encoding="utf-8",
    )
    cache = tmp_path / "host_local_cache"

    audit = cap_scene_texture_resolution(
        scene, max_resolution=8, cache_dir=cache, fail_on_unbounded=True,
    )

    rewritten = Path(ET.parse(scene).getroot().find("texture/string").attrib["value"])
    assert source.is_file()
    assert rewritten.is_file()
    assert rewritten.is_relative_to(cache)
    assert Image.open(rewritten).size == (8, 4)
    assert audit["texture_profile"] == 8
    assert audit["rewritten"] == 1
    assert audit["original_gt_profile_refs"] == 0
    assert audit["audit_ok"] is True
    persisted = json.loads(scene.with_suffix(".texture_audit.json").read_text(encoding="utf-8"))
    assert persisted["downsampled_refs"] == 1


def test_texture_cap_resolves_repo_relative_policy_texture(tmp_path, monkeypatch):
    source = tmp_path / "out" / "scene" / "policy_atlas.png"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (64, 32), color=(1, 2, 3)).save(source)
    staged = tmp_path / "staged" / "scene.xml"
    staged.parent.mkdir()
    staged.write_text(
        "<scene version='3.0.0'><shape type='obj'><bsdf type='diffuse'>"
        "<texture name='reflectance' type='bitmap'>"
        "<string name='filename' value='out/scene/policy_atlas.png'/>"
        "</texture></bsdf></shape></scene>",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    audit = cap_scene_texture_resolution(
        staged, max_resolution=16, cache_dir=tmp_path / "cache", fail_on_unbounded=True,
    )
    rewritten = Path(ET.parse(staged).find(".//string[@name='filename']").get("value"))
    assert rewritten.is_absolute()
    assert Image.open(rewritten).size == (16, 8)
    assert audit["rewritten"] == 1
    assert audit["skipped"] == 0
