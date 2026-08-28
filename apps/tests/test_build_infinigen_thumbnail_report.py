from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("thumbnail_report", REPO_ROOT / "apps" / "build_infinigen_thumbnail_report.py")
assert SPEC and SPEC.loader
report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report
SPEC.loader.exec_module(report)


def _image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)


def _observation(scene: Path, variant: str, vp: str, heading: str, color: tuple[int, int, int], *, polar: bool = True) -> None:
    root = scene / ("observations_perturbed" if variant == "perturbed" else "observations") / vp / heading
    (root / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text("{}")
    _image(root / "sensors" / report.RGB_CAMERA / "rgb.png", color)
    _image(root / "sensors" / report.SECONDARY_RGB_CAMERA / "rgb.png", color)
    if polar:
        for index, (name, _) in enumerate(report.POLAR_TILES):
            _image(root / "sensors" / report.POLAR_CAMERA / name, (index * 30, 10, 90))


def _scene(project: Path) -> Path:
    scene = project / "scenes" / "demo"
    scene.mkdir(parents=True)
    (scene / "authoring_map.json").write_text(json.dumps({"regions": [
        {"label": "Room A", "geometry": {"bounds": [0, 0, 2, 2]}},
        {"label": "Room B", "geometry": {"bounds": [3, 0, 5, 2]}},
    ]}))
    (scene / "viewpoint_graph.json").write_text(json.dumps({"nodes": [
        {"node_id": "vp_000001", "position": [1, 1, 0], "headings": [{"heading_id": "h_000"}]},
        {"node_id": "vp_000002", "position": [4, 1, 0], "headings": [{"heading_id": "h_000"}, {"heading_id": "h_030"}]},
    ]}))
    return scene


def test_collect_candidates_requires_complete_rgb_polar_pairs_and_selects_rooms(tmp_path: Path) -> None:
    scene = _scene(tmp_path)
    _observation(scene, "base", "vp_000001", "h_000", (0, 0, 0))
    _observation(scene, "perturbed", "vp_000001", "h_000", (255, 255, 255))
    _observation(scene, "base", "vp_000002", "h_000", (0, 0, 0))
    _observation(scene, "perturbed", "vp_000002", "h_000", (30, 0, 0))
    _observation(scene, "base", "vp_000002", "h_030", (0, 0, 0), polar=False)
    _observation(scene, "perturbed", "vp_000002", "h_030", (50, 0, 0), polar=False)

    candidates, stats = report.collect_candidates("demo", scene)

    assert stats["paired"] == 3
    assert stats["renderable_pairs"] == 2
    selected = report.select_candidates(candidates, 6)
    assert [(item.region, item.vp_id) for item in selected] == [("Room A", "vp_000001"), ("Room B", "vp_000002")]
    assert [(item.region, item.vp_id) for item in report.exclude_candidates(candidates, {("demo", "vp_000001", "h_000")}, set())] == [("Room B", "vp_000002")]


def test_parse_exclusions_rejects_invalid_input() -> None:
    assert report.parse_exclusions(["demo:vp_000001:h_000"]) == {("demo", "vp_000001", "h_000")}
    assert report.parse_excluded_viewpoints(["demo:vp_000001"]) == {("demo", "vp_000001")}
    try:
        report.parse_exclusions(["demo:vp_000001"])
    except ValueError as error:
        assert "expected" in str(error)
    else:
        raise AssertionError("invalid exclusion must fail")


def test_build_report_materializes_local_assets_and_marks_export_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scene = _scene(project)
    _observation(scene, "base", "vp_000001", "h_000", (0, 0, 0))
    _observation(scene, "perturbed", "vp_000001", "h_000", (100, 20, 0))
    export = project / "exports" / "export-demo-20260818"
    export.mkdir(parents=True)
    (export / "export_status.json").write_text(json.dumps({"status": "running", "created_at": "2026-08-18T00:00:00Z"}))
    output, assets, manifest = tmp_path / "report.html", tmp_path / "assets", tmp_path / "selection.json"

    result = report.build_report(project, ["demo"], output, assets, manifest, 6)

    assert output.is_file() and manifest.is_file()
    assert result["scenes"][0]["export_status"]["status"] == "running"
    assert len(result["scenes"][0]["selected"]) == 1
    for asset in result["scenes"][0]["selected"][0]["assets"].values():
        assert (assets.parent / asset).is_file()
