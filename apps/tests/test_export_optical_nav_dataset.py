from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("export_optical_nav_dataset", REPO_ROOT / "apps" / "export_optical_nav_dataset.py")
assert _SPEC and _SPEC.loader
exporter = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = exporter
_SPEC.loader.exec_module(exporter)


def _write_variant(root: Path, variant_root: str, variant: str, image: Path, stokes: Path | None = None) -> None:
    bundle = root / "project" / "render_versions" / f"bundle-{variant}"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "frame_id": "vp_000001-h_000",
        "scene_id": "scene",
        "artifacts": [{
            "camera_id": "polar_cam", "modality": "rgb",
            "artifact_paths": {"png": str(image), **({"stokes_npz": str(stokes)} if stokes else {})},
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


def test_versioned_export_repackages_legacy_stokes_as_minimal_f16(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(image)
    stokes = tmp_path / "legacy_stokes.npz"
    np.savez_compressed(
        stokes,
        rgb=np.ones((2, 2, 3), dtype=np.float32),
        s0=np.ones((2, 2, 3), dtype=np.float32),
        s1=np.full((2, 2, 3), 0.1, dtype=np.float32),
        s2=np.full((2, 2, 3), -0.2, dtype=np.float32),
        s3=np.zeros((2, 2, 3), dtype=np.float32),
        dop=np.ones((2, 2), dtype=np.float32),
    )
    _write_variant(tmp_path, "observations", "base", image, stokes)
    out = tmp_path / "bundle"
    monkeypatch.setattr(sys, "argv", [
        "export_optical_nav_dataset.py", "--scene", "scene", "--exact-scene",
        "--versioned-root", str(tmp_path), "--out", str(out), "--no-legacy-bridge-jobs",
        "--no-graph", "--no-from-exr", "--workers", "1",
    ])

    assert exporter.main() == 0
    converted = out / "polarization_raw" / "base" / "vp_000001-h_000__polar_cam__stokes.npz"
    with np.load(converted, allow_pickle=False) as data:
        assert set(data.files) == {"s0", "s1", "s2", "s3"}
        assert all(data[name].dtype == np.float16 for name in data.files)
    manifest = json.loads((out / "polarization_raw_manifest.json").read_text())
    assert manifest["schema"] == "minimal_rgb_stokes_f16_v2"
    assert manifest["files"][0]["source_sha256"]


def _polar_bundle(tmp_path: Path, monkeypatch) -> Path:
    """One polar observation: declared derived products plus an s0 sibling."""
    monkeypatch.setattr(exporter, "REPO_ROOT", tmp_path)
    camera = tmp_path / "cameras" / "polar_cam"
    camera.mkdir(parents=True)
    for name in ("polar_rgb_preview.png", "dop_red_black_colorbar.png", "s0_rgb_preview.png"):
        Image.new("RGB", (2, 2)).save(camera / name)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({
        "frame_id": "support_pose_1-h_000",
        "scene_id": "scene",
        "artifacts": [
            {
                "camera_id": "polar_cam", "modality": modality,
                "artifact_paths": {
                    "png": (camera / filename).relative_to(tmp_path).as_posix(),
                    "stokes_npz": "cameras/polar_cam/stokes_data.npz",
                },
            }
            for modality, filename in (
                ("polar_rgb_preview", "polar_rgb_preview.png"),
                ("dop", "dop_red_black_colorbar.png"),
            )
        ],
        "camera_specs": [{"camera_id": "polar_cam", "resolution": [2, 2]}],
    }))
    return bundle


def test_modality_filter_keeps_only_requested_products(tmp_path: Path, monkeypatch) -> None:
    bundle = _polar_bundle(tmp_path, monkeypatch)

    everything = exporter._build_records(bundle, False, "scene", "base", None, None)
    assert {record.modality for record in everything} == {"polar_rgb_preview", "dop"}

    filtered = exporter._build_records(bundle, False, "scene", "base", None, {"dop"})
    assert [record.modality for record in filtered] == ["dop"]


def test_s0_modality_admits_the_undeclared_stokes_preview(tmp_path: Path, monkeypatch) -> None:
    bundle = _polar_bundle(tmp_path, monkeypatch)

    records = exporter._build_records(bundle, False, "scene", "base", None, {"s0"})

    assert [record.modality for record in records] == ["s0"]
    record = records[0]
    assert record.src_png.name == "s0_rgb_preview.png"
    # The Stokes payload must survive the substitution: it is the lossless core.
    assert record.record["image"].endswith("__polar_cam__s0.{ext}")


def test_requesting_an_absent_preview_yields_no_record(tmp_path: Path, monkeypatch) -> None:
    bundle = _polar_bundle(tmp_path, monkeypatch)
    (tmp_path / "cameras" / "polar_cam" / "s3_rgb_preview.png").unlink(missing_ok=True)

    assert exporter._build_records(bundle, False, "scene", "base", None, {"s3"}) == []
