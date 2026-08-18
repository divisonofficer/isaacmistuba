from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from mitsuba_converter.ir_dataset_publish import publish_dataset


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(root: Path, *, fingerprint: str = "f" * 64) -> Path:
    dataset = root / "tiny"
    dataset.mkdir(parents=True)
    frame_id = "vp_000001__h_000"
    rgb_path = dataset / "rgb" / f"{frame_id}.exr"
    roughness_path = dataset / "roughness" / f"{frame_id}.png"
    rgb_path.parent.mkdir(); roughness_path.parent.mkdir()
    assert cv2.imwrite(str(rgb_path), np.full((2, 2, 3), 0.5, np.float32))
    assert cv2.imwrite(str(roughness_path), np.full((2, 2), 32768, np.uint16))
    row = {"frame_id": frame_id, "dataset_fingerprint": fingerprint, "width": 2, "height": 2,
           "paths": {"rgb": rgb_path.relative_to(dataset).as_posix(),
                                               "roughness": roughness_path.relative_to(dataset).as_posix()}}
    _write_json(dataset / "dataset_config.json", {"schema": "robomituba.ir_principled_dataset.v2", "dataset_fingerprint": fingerprint,
                                                    "width": 2, "height": 2})
    _write_json(dataset / "artifact_contract.json", {"schema": "robomituba.ir_principled_artifact_contract.v2", "dataset_fingerprint": fingerprint})
    (dataset / "index.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    _write_json(dataset / "rolling_queue_state.json", {"schema": "robomituba.ir_principled_rolling_queue.v1",
                                                         "dataset_fingerprint": fingerprint, "frame_count": 1,
                                                         "completed": [frame_id], "pending": [], "failed": {}})
    _write_json(dataset / "qc_summary.json", {"schema": "robomituba.ir_principled_qc_summary.v1",
                                                "frame_count": 1, "fallback_threshold_passed": True,
                                                "fallback_pixel_ratio": 0.0})
    return dataset


def test_publish_is_atomic_and_idempotent_without_viewer_app(tmp_path: Path) -> None:
    source = _fixture(tmp_path / "out")
    destination = tmp_path / "bean"
    result = publish_dataset(source, destination)
    assert result["mode"] == "published"
    assert (destination / "tiny" / "publish_manifest.json").is_file()
    assert publish_dataset(source, destination)["mode"] == "adopted_existing"


def test_publish_rejects_corrupt_indexed_artifact(tmp_path: Path) -> None:
    source = _fixture(tmp_path / "out")
    (source / "rgb" / "vp_000001__h_000.exr").write_bytes(b"not an exr")
    with pytest.raises(ValueError, match="cannot decode rgb"):
        publish_dataset(source, tmp_path / "bean")
