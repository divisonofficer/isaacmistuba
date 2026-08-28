from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("export_optical_nav_dataset", REPO_ROOT / "apps" / "export_optical_nav_dataset.py")
assert _SPEC and _SPEC.loader
exporter = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = exporter
_SPEC.loader.exec_module(exporter)


def _write_variant(root: Path, variant_root: str, variant: str, image: Path) -> None:
    bundle = root / "project" / "render_versions" / f"bundle-{variant}"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "frame_id": "vp_000001-h_000",
        "scene_id": "scene",
        "artifacts": [{
            "camera_id": "polar_cam", "modality": "rgb",
            "artifact_paths": {"png": str(image)},
        }],
        "camera_specs": [{"camera_id": "polar_cam", "resolution": [2, 2]}],
        "extras": {"opticalnav_vp_id": "vp_000001", "opticalnav_heading_id": "h_000"},
    }))
    pointer = root / "project" / "scenes" / "scene" / variant_root / "vp_000001" / "h_000" / "current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"bundle_ref": bundle.relative_to(root / "project").as_posix()}))


def test_versioned_export_keeps_same_frame_from_each_variant(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(image)
    _write_variant(tmp_path, "observations", "base", image)
    _write_variant(tmp_path, "observations_perturbed_active_polar", "perturbed_active_polar", image)
    out = tmp_path / "bundle"
    monkeypatch.setattr(sys, "argv", [
        "export_optical_nav_dataset.py", "--scene", "scene", "--exact-scene",
        "--versioned-root", str(tmp_path), "--out", str(out), "--no-legacy-bridge-jobs",
        "--no-graph", "--no-from-exr", "--workers", "1",
    ])

    assert exporter.main() == 0
    rows = [json.loads(line) for line in (out / "index.jsonl").read_text().splitlines()]
    assert {row["variant"] for row in rows} == {"base", "perturbed_active_polar"}
    assert (out / "images" / "base" / "vp_000001-h_000__polar_cam.jpg").is_file()
    assert (out / "images" / "perturbed_active_polar" / "vp_000001-h_000__polar_cam.jpg").is_file()
