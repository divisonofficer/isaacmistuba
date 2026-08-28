from __future__ import annotations

import json
import os
import hashlib
import shutil
import struct
from pathlib import Path

import cv2
import numpy as np
import pytest

from apps.ir_dataset_viewer.backend.catalog import (
    DatasetCatalog,
    DatasetOrigin,
    PreviewService,
    decode_artifact,
    load_dataset_origin,
)
from apps.ir_dataset_viewer.backend.preview_queue import PreviewWorkScheduler
from mitsuba_converter.ir_scene_statistics import build_scene_statistics

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path, name: str = "tiny", fingerprint: str = "f" * 64, version: int = 2) -> Path:
    dataset = root / name
    dataset.mkdir(parents=True)
    frame_id = "vp_000001__h_000"
    rgb = np.array([[[0.25, 0.5, 1.0], [2.0, 0.0, 0.5]], [[0.0, 0.1, 0.2], [1.0, 1.0, 1.0]]], np.float32)
    roughness = np.array([[0, 32768], [65535, 16384]], np.uint16)
    normal_rgb = np.array([[[65535, 32768, 32768]] * 2] * 2, np.uint16)
    object_id = np.array([[0, 2], [10, 65535]], np.uint16)
    mask = np.array([[0, 255], [255, 0]], np.uint8)
    artifacts = {
        "rgb": (rgb[..., ::-1], ".exr"),
        "roughness": (roughness, ".png"),
        "normal_geometry_world": (normal_rgb[..., ::-1], ".png"),
        "object_id": (object_id, ".png"),
        "replacement_mask": (mask, ".png"),
    }
    paths = {}
    for modality, (array, suffix) in artifacts.items():
        path = dataset / modality / f"{frame_id}{suffix}"
        path.parent.mkdir(parents=True)
        assert cv2.imwrite(str(path), array)
        paths[modality] = path.relative_to(dataset).as_posix()
    config = {
        "schema": f"robomituba.ir_principled_dataset.v{version}", "dataset_fingerprint": fingerprint,
        "width": 2, "height": 2, "exposure_ev": {"rgb": 0.0, "nir_active": 0.0},
    }
    contract = {
        "schema": f"robomituba.ir_principled_artifact_contract.v{version}",
        "dataset_schema": config["schema"], "dataset_fingerprint": fingerprint,
        "exposure_ev": config["exposure_ev"], "observations": {"rgb": {"path": "rgb/{frame_id}.exr"}},
        "ground_truth": {"roughness": "perceptual_roughness_unorm16", "normal_geometry_world": "xyz_signed_to_unorm16", "object_id": "uint16"},
        "masks": {"replacement_mask": "binary_u8"},
    }
    row = {
        "schema": "robomituba.ir_principled_frame.v2", "frame_id": frame_id,
        "viewpoint_id": "vp_000001", "heading_deg": 0.0, "dataset_fingerprint": fingerprint,
        "width": 2, "height": 2, "paths": paths, "camera": {}, "intrinsics": {},
    }
    _write_json(dataset / "dataset_config.json", config)
    _write_json(dataset / "artifact_contract.json", contract)
    (dataset / "index.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    _write_json(dataset / "rolling_queue_state.json", {
        "schema": "robomituba.ir_principled_rolling_queue.v1", "dataset_fingerprint": fingerprint,
        "frame_count": 1, "completed": [frame_id], "pending": [], "failed": {},
    })
    _write_json(dataset / "qc_summary.json", {
        "schema": "robomituba.ir_principled_qc_summary.v1", "frame_count": 1,
        "fallback_threshold_passed": True, "fallback_pixel_ratio": 0.0,
    })
    return dataset


def test_catalog_deduplicates_by_fingerprint_and_prefers_bean(tmp_path: Path) -> None:
    out_root = tmp_path / "out"; bean_root = tmp_path / "bean"
    source = _fixture(out_root, "source")
    shutil.copytree(source, bean_root / "published")
    catalog = DatasetCatalog([("bean", bean_root), ("out", out_root)], ttl_s=0)
    payload = catalog.list_payload(force=True)
    assert len(payload["datasets"]) == 1
    row = payload["datasets"][0]
    assert row["primary_origin"] == "bean"
    assert row["published"] is True
    # Compact catalog scans must keep the inexpensive QC frame count.  If this
    # regresses, the scene list says “0 VP · 0 frames” even though opening the
    # same dataset hydrates a valid index.
    assert row["frame_count"] == 1
    assert {origin["kind"] for origin in row["origins"]} == {"bean", "out"}
    viewpoints = catalog.viewpoints_payload(row["dataset_id"])["viewpoints"]
    assert viewpoints[0]["frames"][0]["frame_id"] == "vp_000001__h_000"


def test_catalog_accepts_v3_and_keeps_v2_legacy_semantics_visible(tmp_path: Path) -> None:
    v3 = _fixture(tmp_path, "v3", "3" * 64, version=3)
    v2 = _fixture(tmp_path, "v2", "2" * 64, version=2)
    catalog = DatasetCatalog([("out", tmp_path)], ttl_s=0)
    payload = catalog.list_payload(force=True)
    assert {item["schema"] for item in payload["datasets"]} == {
        "robomituba.ir_principled_dataset.v2", "robomituba.ir_principled_dataset.v3",
    }
    legacy = catalog.frame_payload("2" * 64, "vp_000001__h_000")
    assert legacy["legacy_diffuse_warning"]


def test_catalog_prefers_passive_nir_work_overlay_to_active_only_bean(tmp_path: Path) -> None:
    work_root = tmp_path / "work"; bean_root = tmp_path / "bean"
    work = _fixture(work_root, "scene")
    shutil.copytree(work, bean_root / "scene")
    row = json.loads((work / "index.jsonl").read_text())
    frame_id = row["frame_id"]
    for name in ("nir_active", "nir_passive"):
        path = work / name / f"{frame_id}.exr"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(path), np.ones((2, 2, 3), np.float32))
        row["paths"][name] = path.relative_to(work).as_posix()
    (work / "index.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    catalog = DatasetCatalog([("bean", bean_root), ("work", work_root)], ttl_s=0)
    summary = catalog.list_payload(force=True)["datasets"][0]
    assert summary["primary_origin"] == "work"
    assert summary["published"] is True
    assert "nir_passive" in summary["modalities"]
    assert "nir_active_minus_passive" in summary["modalities"]


def test_browse_bootstrap_reuses_one_hydrated_index_and_invalidates_work_signature(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "datasets"; _fixture(root)
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]

    import apps.ir_dataset_viewer.backend.catalog as catalog_module
    original = catalog_module.load_dataset_origin
    hydrated_calls = 0

    def counted(*args, **kwargs):
        nonlocal hydrated_calls
        if kwargs.get("load_rows", True):
            hydrated_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(catalog_module, "load_dataset_origin", counted)
    bootstrap = catalog.browse_payload(dataset_id, viewpoint_id="vp_000001", frame_id="vp_000001__h_000")
    assert bootstrap["selected_frame_id"] == "vp_000001__h_000"
    assert bootstrap["dataset"]["modalities"]
    assert hydrated_calls == 1 and catalog.index_cache_status() == "miss"
    assert catalog.viewpoints_payload(dataset_id)["viewpoints"]
    assert catalog.frame_payload(dataset_id, "vp_000001__h_000")["available"]["rgb"]
    assert hydrated_calls == 1 and catalog.index_cache_status() == "hit"

    # A mutable work/out index is a different cache key after its stat
    # signature changes; published bean indexes remain immutable by contract.
    index = root / "tiny" / "index.jsonl"
    index.write_text(index.read_text() + "\n", encoding="utf-8")
    catalog.list_payload(force=True)
    catalog.browse_payload(dataset_id)
    assert hydrated_calls == 2 and catalog.index_cache_status() == "miss"


def test_scene_statistics_and_catalog_filters(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; dataset = _fixture(root)
    content = {"schema": "robomituba.ir_scene_content_audit.v1", "status": "passed", "room_type": "kitchen",
               "object_count": 32, "nonstructural_object_count": 18, "room_footprint": {"area_m2": 6.0}, "audit_digest": "a" * 64}
    utility = {"utility_class": "informative", "visible_object_count": 6, "nonstructural_fraction": .5}
    plan = {"groups": [{"poses": [{"utility": utility}, {"utility": {**utility, "visible_object_count": 4}}]}], "render_plan_digest": "b" * 64}
    visibility = {"candidate_count": 4, "class_counts": {"informative": 3}, "probe_digest": "c" * 64}
    stats = build_scene_statistics(content_audit=content, visibility=visibility, render_plan=plan, requested_density="family_home")
    assert stats["density_class"] == "dense" and stats["nonstructural_objects_per_m2"] == pytest.approx(3.0)
    _write_json(dataset / "quality" / "scene_statistics.json", stats)
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    payload = catalog.scenes_payload({"density_class": "dense", "min_area_m2": "5", "sort": "objects"})
    assert payload["filtered"] == 1 and payload["scenes"][0]["scene_statistics"]["room_type"] == "kitchen"
    assert payload["medians"]["total_objects"] == 32
    assert payload["facets"]["room_types"] == ["kitchen"]
    assert catalog.scenes_payload({"min_total_objects": "33"})["filtered"] == 0
    assert catalog.scene_payload(payload["scenes"][0]["dataset_id"])["statistics"]["density_class"] == "dense"


def test_catalog_loads_fingerprint_bound_readiness_sidecar(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; dataset = _fixture(root)
    labels = tmp_path / "labels"
    sources = []
    for path in (dataset / "dataset_config.json", dataset / "artifact_contract.json", dataset / "index.jsonl"):
        sources.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    _write_json(labels / f"{'f' * 64}.json", {
        "schema": "robomituba.ir_inverse_rendering_readiness.v1",
        "dataset_fingerprint": "f" * 64,
        "profile": "scene_scale_specular_showcase_v1", "status": "below_target",
        "labels": ["scene_scale_specular_showcase_v1:below_target"],
        "findings": ["selected_visible_object_median_below_10"],
        "recommendation": "exclude_from_scene_scale_specular_headline_set", "label_digest": "a" * 64,
        "evidence": {"selected_visible_object_count": {"median": 2}},
        "binding": {"dataset_fingerprint": "f" * 64, "sources": sources},
    })
    catalog = DatasetCatalog([("out", root)], ttl_s=0, readiness_root=labels)
    row = catalog.list_payload(force=True)["datasets"][0]
    assert row["readiness_label"]["status"] == "below_target"
    (dataset / "index.jsonl").write_text((dataset / "index.jsonl").read_text() + "\n")
    assert catalog.list_payload(force=True)["datasets"][0]["readiness_label"]["status"] == "unlabeled"


def test_catalog_exposes_tier_d_until_explicitly_retired(tmp_path: Path) -> None:
    root = tmp_path / "datasets"
    dataset = _fixture(root, fingerprint="d" * 64)
    review_root = tmp_path / "reviews"
    sources = []
    for path in (dataset / "dataset_config.json", dataset / "artifact_contract.json", dataset / "index.jsonl"):
        sources.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    _write_json(review_root / ("d" * 64 + ".json"), {
        "schema": "robomituba.ir_scene_review.v1",
        "dataset_name": dataset.name,
        "dataset_fingerprint": "d" * 64,
        "review_tier": "D",
        "deprecation_candidate": True,
        "binding": {"dataset_fingerprint": "d" * 64, "sources": sources},
    })
    catalog = DatasetCatalog([("bean", root)], ttl_s=0, review_root=review_root)
    payload = catalog.list_payload(force=True)
    assert [row["dataset_id"] for row in payload["datasets"]] == ["d" * 64]
    assert payload["datasets"][0]["scene_review"]["review_tier"] == "D"
    assert payload["hidden_deprecated"] == 0
    assert catalog.get("d" * 64).fingerprint == "d" * 64

    (dataset / ".deprecated").write_text("retired\n", encoding="utf-8")
    payload = catalog.list_payload(force=True)
    assert payload["datasets"] == []
    assert payload["hidden_deprecated"] == 1
    with pytest.raises(KeyError):
        catalog.get("d" * 64)


def test_hydrated_detail_refreshes_review_sidecar_without_reparsing_index(tmp_path: Path) -> None:
    root = tmp_path / "datasets"
    dataset = _fixture(root, fingerprint="e" * 64)
    review_root = tmp_path / "reviews"
    sources = []
    for path in (dataset / "dataset_config.json", dataset / "artifact_contract.json", dataset / "index.jsonl"):
        sources.append({"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    review = {
        "schema": "robomituba.ir_scene_review.v1",
        "dataset_name": dataset.name,
        "dataset_fingerprint": "e" * 64,
        "review_tier": "D",
        "deprecation_candidate": True,
        "binding": {"dataset_fingerprint": "e" * 64, "sources": sources},
    }
    review_path = review_root / ("e" * 64 + ".json")
    _write_json(review_path, review)
    catalog = DatasetCatalog([("out", root)], ttl_s=0, review_root=review_root)
    assert catalog._with_rows(catalog.get("e" * 64)).scene_review["review_tier"] == "D"

    review["review_tier"] = "C"
    review["deprecation_candidate"] = False
    review["manual_override"] = {"automatic_tier": "D", "review_tier": "C"}
    _write_json(review_path, review)
    catalog.refresh(force=True)
    # The expensive index rows remain cached, but their independent review
    # overlay must match the freshly refreshed compact catalog record.
    assert catalog._with_rows(catalog.get("e" * 64)).scene_review["review_tier"] == "C"


def test_decode_preview_and_raw_pixels(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; dataset = _fixture(root)
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]
    service = PreviewService(catalog, tmp_path / "cache", disk_max_bytes=1024**2)
    preview, etag = service.preview(dataset_id, "vp_000001__h_000", "rgb")
    assert preview.startswith(b"\x89PNG") and len(etag) == 64
    pixels = service.pixels(dataset_id, "vp_000001__h_000", 1, 0,
                            ["rgb", "roughness", "normal_geometry_world", "object_id", "replacement_mask"])
    assert pixels["values"]["rgb"]["value"] == pytest.approx([2.0, 0.0, 0.5])
    assert pixels["values"]["roughness"]["value"] == pytest.approx(32768 / 65535)
    assert pixels["values"]["normal_geometry_world"]["value"] == pytest.approx([1.0, 0.0, 0.0], abs=3e-5)
    assert pixels["values"]["object_id"]["value"] == 2
    assert pixels["values"]["replacement_mask"]["value"] is True


def test_passive_nir_exposes_flash_only_derived_preview_and_pixels(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; dataset = _fixture(root)
    frame_id = "vp_000001__h_000"
    active = np.array([
        [[2.0, 1.0, 0.5], [1.0, 3.0, 0.25]],
        [[0.5, 0.75, 1.0], [4.0, 2.0, 1.0]],
    ], np.float32)
    passive = np.array([
        [[0.5, 1.5, 0.25], [0.25, 1.0, 0.5]],
        [[0.5, 0.25, 0.25], [1.0, 1.0, 1.5]],
    ], np.float32)
    for name, value in (("nir_active", active), ("nir_passive", passive)):
        path = dataset / name / f"{frame_id}.exr"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(path), value[..., ::-1])
    index_path = dataset / "index.jsonl"
    row = json.loads(index_path.read_text())
    row["paths"].update({
        "nir_active": f"nir_active/{frame_id}.exr",
        "nir_passive": f"nir_passive/{frame_id}.exr",
    })
    index_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]
    bootstrap = catalog.browse_payload(dataset_id)
    assert "nir_passive" in bootstrap["dataset"]["modalities"]
    assert "nir_active_minus_passive" in bootstrap["dataset"]["modalities"]
    compact = bootstrap["viewpoints"][0]["frames"][0]
    assert "nir_active_minus_passive" in compact["available"]
    assert catalog.frame_payload(dataset_id, frame_id)["available"]["nir_active_minus_passive"] is True

    service = PreviewService(catalog, tmp_path / "cache", disk_max_bytes=1024**2)
    preview, etag = service.preview(dataset_id, frame_id, "nir_active_minus_passive")
    assert preview.startswith(b"\x89PNG") and len(etag) == 64
    pixels = service.pixels(dataset_id, frame_id, 0, 0,
                            ["nir_active", "nir_passive", "nir_active_minus_passive"])
    assert pixels["values"]["nir_active_minus_passive"]["value"] == pytest.approx([1.5, 0.0, 0.25])
    assert pixels["values"]["nir_active_minus_passive"]["unit"] == "scene_linear_flash_only"


def test_encoded_preview_memory_cache_bypasses_raster_work(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "datasets"; _fixture(root)
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]
    service = PreviewService(catalog, tmp_path / "cache", disk_max_bytes=1024**2)
    first, _ = service.preview(dataset_id, "vp_000001__h_000", "rgb", image_format="webp")
    assert first.startswith(b"RIFF")
    import apps.ir_dataset_viewer.backend.catalog as catalog_module
    monkeypatch.setattr(catalog_module, "render_preview", lambda *args, **kwargs: pytest.fail("cache hit decoded again"))
    cached = service.cached_preview(dataset_id, "vp_000001__h_000", "rgb", image_format="webp")
    assert cached is not None and cached[0] == first and service.preview_cache_status() == "memory"


def test_preview_priority_scheduler_preserves_interactive_slots() -> None:
    scheduler = PreviewWorkScheduler(interactive_slots=2, background_slots=1)
    background = scheduler.acquire("prefetch")
    assert background is not None
    first = scheduler.acquire("interactive")
    second = scheduler.acquire("comparison")
    assert first is not None and second is not None
    # A cancelled background request must leave the queue before any decoding.
    assert scheduler.acquire("prefetch", cancelled=lambda: True) is None
    scheduler.release(second); scheduler.release(first); scheduler.release(background)


def test_webp_preview_and_pose_only_overview(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; _fixture(root)
    row = json.loads((root / "tiny" / "index.jsonl").read_text())
    row["camera"] = {"origin_mitsuba": [1.0, 1.2, 3.0], "target_mitsuba": [2.0, 1.1, 3.0], "up_mitsuba": [0.0, 1.0, 0.0]}
    (root / "tiny" / "index.jsonl").write_text(json.dumps(row) + "\n")
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]
    service = PreviewService(catalog, tmp_path / "cache")
    data, key = service.preview(dataset_id, "vp_000001__h_000", "rgb", image_format="webp", max_width=1)
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    etag, image_format, immutable = service.etag(dataset_id, "vp_000001__h_000", "rgb", image_format="webp", max_width=1)
    assert etag == key and image_format == "webp" and not immutable
    overview = catalog.overview_payload(dataset_id)
    assert overview["fallback"] and not overview["graph_available"]
    assert overview["poses"][0]["origin"] == [1.0, 1.2, 3.0]


def test_catalog_accepts_verified_proxy_overview(tmp_path: Path) -> None:
    root = tmp_path / "datasets"; dataset = _fixture(root)
    fingerprint = "f" * 64
    proxy = dataset / "scene_overview" / "scene_proxy.glb"; proxy.parent.mkdir()
    payload = b"glTF" + struct.pack("<I", 2) + struct.pack("<I", 12)
    proxy.write_bytes(payload)
    overview = {
        "schema": "robomituba.ir_scene_overview.v1", "dataset_fingerprint": fingerprint,
        "coordinate_system": "mitsuba_y_up", "graph_available": False, "traversability_available": False,
        "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}, "nodes": [], "edges": [], "poses": [], "lighting_ids": [],
        "proxy_mesh": {"path": "scene_overview/scene_proxy.glb", "sha256": hashlib.sha256(payload).hexdigest(),
                       "triangles": 12, "byte_count": len(payload), "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]},
                       "coordinate_system": "mitsuba_y_up", "compiler_version": "ir-scene-overview-proxy-v1", "semantic_groups": ["structural", "large_furniture"]},
    }
    _write_json(dataset / "scene_overview.json", overview)
    contract = json.loads((dataset / "artifact_contract.json").read_text())
    contract["overview"] = {"schema": overview["schema"], "path": "scene_overview.json", "proxy_mesh_path": "scene_overview/scene_proxy.glb", "proxy_mesh_sha256": overview["proxy_mesh"]["sha256"]}
    _write_json(dataset / "artifact_contract.json", contract)
    catalog = DatasetCatalog([("out", root)], ttl_s=0)
    dataset_id = catalog.list_payload(force=True)["datasets"][0]["dataset_id"]
    assert catalog.overview_payload(dataset_id)["proxy_mesh"]["triangles"] == 12


def test_catalog_rejects_duplicate_and_unsafe_paths(tmp_path: Path) -> None:
    dataset = _fixture(tmp_path)
    line = (dataset / "index.jsonl").read_text()
    (dataset / "index.jsonl").write_text(line + line)
    with pytest.raises(ValueError, match="duplicate frame_id"):
        load_dataset_origin(DatasetOrigin("out", tmp_path, dataset))

    dataset = _fixture(tmp_path, "unsafe", "e" * 64)
    row = json.loads((dataset / "index.jsonl").read_text())
    row["paths"]["rgb"] = "../escape.exr"
    (dataset / "index.jsonl").write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="unsafe dataset artifact path"):
        load_dataset_origin(DatasetOrigin("out", tmp_path, dataset))
