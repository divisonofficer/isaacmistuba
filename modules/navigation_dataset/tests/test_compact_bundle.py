from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from navigation_dataset.exporters.compact_bundle import (
    POLAR_STOKES_CORE_KEYS,
    build_perturbation_pair_index,
    estimate_bundle_plan,
    plan_compact_bundle_files,
    resolve_export_profile,
    rewrite_observation_manifests,
    transcode_rgb_png_to_lossless_webp,
    write_polar_thumbnail,
    write_stokes_core,
)


def _write_stokes(path: Path) -> dict[str, np.ndarray]:
    path.parent.mkdir(parents=True, exist_ok=True)
    s0 = np.full((2, 3, 3), 0.5, dtype=np.float32)
    s1 = np.full((2, 3, 3), 0.1, dtype=np.float32)
    s2 = np.full((2, 3, 3), -0.2, dtype=np.float32)
    s3 = np.zeros((2, 3, 3), dtype=np.float32)
    mask = np.ones((2, 3), dtype=bool)
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    s0_l = np.tensordot(s0, weights, axes=([2], [0]))
    s1_l = np.tensordot(s1, weights, axes=([2], [0]))
    s2_l = np.tensordot(s2, weights, axes=([2], [0]))
    s1_n = s1_l / s0_l
    s2_n = s2_l / s0_l
    dop = np.sqrt(s1_l * s1_l + s2_l * s2_l) / s0_l
    aolp = np.mod(0.5 * np.arctan2(s2_l, s1_l), np.pi)
    arrays = {
        "rgb": s0.copy(), "s0": s0, "s1": s1, "s2": s2, "s3": s3,
        "s0_l": s0_l, "s1_l": s1_l, "s2_l": s2_l, "s3_l": np.zeros_like(s0_l),
        "s1_over_s0": s1_n, "s2_over_s0": s2_n, "dop": dop, "aolp": aolp, "mask": mask,
    }
    np.savez_compressed(path, **arrays)
    return arrays


def _png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)


def test_compact_plan_replaces_polar_visuals_and_keeps_stokes_core(tmp_path: Path) -> None:
    sensor = tmp_path / "sensors" / "polar_cam"
    stokes = sensor / "stokes_data.npz"
    _write_stokes(stokes)
    for name, color in (("polar_rgb_preview.png", (20, 30, 40)), ("dop_red_black_colorbar.png", (80, 30, 20))):
        _png(sensor / name, color)
    rgb = tmp_path / "sensors" / "rgb_cam" / "rgb.png"
    _png(rgb, (4, 5, 6))
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    plan = plan_compact_bundle_files([
        (stokes, "scenes/s/observations/vp/h/sensors/polar_cam/stokes_data.npz"),
        (sensor / "polar_rgb_preview.png", "scenes/s/observations/vp/h/sensors/polar_cam/polar_rgb_preview.png"),
        (sensor / "dop_red_black_colorbar.png", "scenes/s/observations/vp/h/sensors/polar_cam/dop_red_black_colorbar.png"),
        (rgb, "scenes/s/observations/vp/h/sensors/rgb_cam/rgb.png"),
        (manifest, "scenes/s/observations/vp/h/manifest.json"),
    ], resolve_export_profile(None))

    assert len(plan.polar_core) == 1
    assert plan.polar_core[0].dst.endswith("stokes_core_v1.npz")
    assert len(plan.polar_thumbnails) == 1
    assert plan.polar_thumbnails[0].dst.endswith("polar_thumbnail.webp")
    assert [item.dst for item in plan.webp_rgb] == ["scenes/s/observations/vp/h/sensors/rgb_cam/rgb.webp"]
    assert len(plan.omitted) == 2
    estimate = estimate_bundle_plan(plan)
    assert estimate["breakdown"]["by_variant"]["base"]["polar_extension_estimated_bytes"] > 0
    assert estimate["breakdown"]["by_sensor"]["polar_cam"]["core_estimated_bytes"] > 0


def test_lossless_core_webp_thumbnail_and_derived_values_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "stokes_data.npz"
    expected = _write_stokes(source)
    core = tmp_path / "stokes_core_v1.npz"
    metadata = write_stokes_core(source, core)
    assert metadata["source_sha256"]
    with np.load(core, allow_pickle=False) as restored:
        assert restored.files == list(POLAR_STOKES_CORE_KEYS)
        for key in POLAR_STOKES_CORE_KEYS:
            assert restored[key].tobytes(order="C") == expected[key].tobytes(order="C")
        weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        s0_l = np.tensordot(restored["s0"], weights, axes=([2], [0]))
        s1_l = np.tensordot(restored["s1"], weights, axes=([2], [0]))
        s2_l = np.tensordot(restored["s2"], weights, axes=([2], [0]))
        assert np.allclose(s1_l / s0_l, expected["s1_over_s0"], atol=1e-7)
        assert np.allclose(s2_l / s0_l, expected["s2_over_s0"], atol=1e-7)
        assert np.allclose(np.sqrt(s1_l * s1_l + s2_l * s2_l) / s0_l, expected["dop"], atol=1e-7)

    rgb = tmp_path / "rgb.png"
    _png(rgb, (17, 33, 91))
    webp = tmp_path / "rgb.webp"
    assert transcode_rgb_png_to_lossless_webp(rgb, webp) > 0

    polar_preview = source.parent / "polar_rgb_preview.png"
    _png(polar_preview, (17, 33, 91))
    thumbnail_plan = plan_compact_bundle_files([
        (source, "sensors/polar/stokes_data.npz"),
        (polar_preview, "sensors/polar/polar_rgb_preview.png"),
    ], resolve_export_profile("navigation_only")).polar_thumbnails[0]
    # The filename is deliberately enough for the compact thumbnail planner;
    # source image content is only descriptive, not canonical science data.
    assert write_polar_thumbnail(thumbnail_plan, tmp_path / "out") > 0
    assert (tmp_path / "out" / thumbnail_plan.dst).is_file()


def test_manifest_rewrite_and_pair_index_are_self_contained(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    manifest = root / "scenes" / "s" / "observations" / "vp" / "h" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"artifacts": [{"artifact_paths": {
        "png": "out/source/polar_rgb_preview.png",
        "stokes_npz": "out/source/stokes_data.npz",
        "exr": "out/source/rgb.exr",
    }}]}))
    count = rewrite_observation_manifests(
        root,
        profile=resolve_export_profile("compact_with_polar_extension"),
        source_to_exported={"out/source/polar_rgb_preview.png": "scenes/s/observations/vp/h/sensors/polar/polar_thumbnail.webp"},
        polar_extension={"archive": "s_polar.zip", "required": True},
    )
    assert count == 1
    rewritten = json.loads(manifest.read_text())
    artifact = rewritten["artifacts"][0]
    assert artifact["artifact_paths"] == {"polar_thumbnail": "scenes/s/observations/vp/h/sensors/polar/polar_thumbnail.webp"}
    assert artifact["polarization_extension"]["archive"] == "s_polar.zip"
    assert "exr" not in artifact["artifact_paths"]

    pairs = build_perturbation_pair_index([
        "scenes/s/observations/vp_a/h_000/sensors/a/rgb.webp",
        "scenes/s/observations_perturbed/vp_a/h_000/sensors/a/rgb.webp",
        "scenes/s/observations_perturbed/vp_b/h_090/sensors/a/rgb.webp",
    ])
    assert pairs["pair_count"] == 1
    assert pairs["unpaired_perturbed"] == [{"scene_id": "s", "vp_id": "vp_b", "heading_id": "h_090"}]
