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
from mitsuba_converter.ir_scene_statistics import build_scene_statistics

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path, name: str = "tiny", fingerprint: str = "f" * 64) -> Path:
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
        "schema": "robomituba.ir_principled_dataset.v2", "dataset_fingerprint": fingerprint,
        "width": 2, "height": 2, "exposure_ev": {"rgb": 0.0, "nir_active": 0.0},
    }
    contract = {
        "schema": "robomituba.ir_principled_artifact_contract.v2",
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
    assert {origin["kind"] for origin in row["origins"]} == {"bean", "out"}
    viewpoints = catalog.viewpoints_payload(row["dataset_id"])["viewpoints"]
    assert viewpoints[0]["frames"][0]["frame_id"] == "vp_000001__h_000"


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
