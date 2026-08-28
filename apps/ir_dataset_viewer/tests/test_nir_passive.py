from __future__ import annotations

import argparse
import json
import fcntl
from pathlib import Path

import cv2
import numpy as np
import pytest

from apps.backfill_ir_nir_passive import _discover_next, _task
from apps.render_ir_principled_dataset_queue import (
    BlenderWorker,
    PASSIVE_NIR_MODALITIES,
    REQUIRED_MODALITIES,
    _activate_nir_passive_contract,
    _derive_nir_difference,
    _row_complete,
)
from tools.infinigen.ir_worker_aov_contract import (
    LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES,
    required_aov_sources,
)


def test_legacy_passive_backfill_only_relaxes_metallic_auxiliary_aovs():
    sources = {
        "GT_BaseColorNIR", "GT_Roughness", "GT_Metallic",
        *LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES,
    }
    strict = required_aov_sources(sources)
    assert LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES <= strict

    legacy = required_aov_sources(sources, allow_legacy_passive_backfill=True)
    assert not (LEGACY_PASSIVE_BACKFILL_OPTIONAL_AOV_SOURCES & legacy)
    assert {"GT_BaseColorNIR", "GT_Roughness", "GT_Metallic"} <= legacy


def test_blender_worker_forwards_legacy_passive_backfill_flag(monkeypatch, tmp_path: Path):
    captured = {}

    class DummyProcess:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return DummyProcess()

    monkeypatch.setattr("apps.render_ir_principled_dataset_queue.subprocess.Popen", fake_popen)
    monkeypatch.setattr(BlenderWorker, "_read_event", lambda self, expected, timeout=None: {"type": expected})
    args = argparse.Namespace(
        out=tmp_path, width=4, height=3, fov=60.0, rgb_spp=1, nir_spp=1,
        max_bounces=1, render_seed=1, device="OPTIX", nir_formula="primary",
        flash_energy_scale=1.0, ambient_fill_energy_scale=1.0,
        qc_components=False, nir_passive=True, verbose_blender=False,
        allow_legacy_passive_backfill_aovs=True,
    )
    BlenderWorker(0, args, tmp_path / "legacy.blend", "fp").start()
    assert "--nir-passive" in captured["command"]
    assert "--allow-legacy-passive-backfill-aovs" in captured["command"]


def test_active_minus_passive_is_linear_and_atomic(tmp_path: Path):
    active = np.full((3, 4, 3), 2.0, dtype=np.float32)
    passive = np.full((3, 4, 3), 0.75, dtype=np.float32)
    for name, value in (("nir_active", active), ("nir_passive", passive)):
        path = tmp_path / name / "frame.exr"
        path.parent.mkdir(parents=True)
        assert cv2.imwrite(str(path), value)
    row = {"frame_id": "frame", "paths": {
        "nir_active": "nir_active/frame.exr", "nir_passive": "nir_passive/frame.exr",
    }}
    updated = _derive_nir_difference(tmp_path, row)
    result = cv2.imread(str(tmp_path / updated["paths"]["nir_active_minus_passive"]), cv2.IMREAD_UNCHANGED)
    assert result is not None
    np.testing.assert_allclose(result, 1.25, atol=1e-5)
    assert updated["nir_difference_qc"]["mean_abs"] == 1.25


def test_backfill_task_preserves_pose_and_marks_flash_off():
    row = {
        "frame_id": "vp_000001__h_090", "viewpoint_id": "vp_000001", "heading_deg": 90,
        "width": 4, "height": 3, "fov_deg": 60,
        "camera": {"camera_to_world_blender": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]},
        "lighting": {"id": "reference_neutral_v1", "recipe": {"id": "reference_neutral_v1"}},
    }
    task = _task(row, "fingerprint")
    assert task["render_mode"] == "nir_passive_only"
    assert task["nir_passive"] is True
    assert task["preserve_existing_row"] is True
    assert task["camera_to_world_blender"] == row["camera"]["camera_to_world_blender"]


def test_discover_next_skips_partial_rolling_dataset(tmp_path: Path):
    root = tmp_path / "work"
    root.mkdir()
    partial = root / "partial"
    partial.mkdir()
    (partial / "index.jsonl").write_text('{"frame_id":"a","paths":{}}\n', encoding="utf-8")
    (partial / "rolling_queue_state.json").write_text(json.dumps({
        "frame_count": 1, "completed": [], "pending": ["a"], "failed": {},
    }), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        _discover_next(root)


def test_passive_contract_is_activated_only_after_all_sidecars(tmp_path: Path):
    (tmp_path / "frames").mkdir()
    (tmp_path / "nir_passive").mkdir()
    (tmp_path / "nir_active_minus_passive").mkdir()
    frame = "frame"
    (tmp_path / "nir_passive" / f"{frame}.exr").write_bytes(b"passive")
    (tmp_path / "nir_active_minus_passive" / f"{frame}.exr").write_bytes(b"difference")
    (tmp_path / "frames" / f"{frame}.json").write_text(json.dumps({
        "frame_id": frame,
        "dataset_fingerprint": "fp",
        "paths": {
            "nir_passive": f"nir_passive/{frame}.exr",
            "nir_active_minus_passive": f"nir_active_minus_passive/{frame}.exr",
        },
    }), encoding="utf-8")
    (tmp_path / "dataset_config.json").write_text(json.dumps({
        "dataset_fingerprint": "fp", "nir_formula": "primary",
    }), encoding="utf-8")
    (tmp_path / "artifact_contract.json").write_text(json.dumps({
        "dataset_fingerprint": "fp", "observations": {"rgb": {"path": "rgb/{frame_id}.exr"}},
    }), encoding="utf-8")

    _activate_nir_passive_contract(tmp_path, fingerprint="fp", frame_ids={frame})
    config = json.loads((tmp_path / "dataset_config.json").read_text())
    contract = json.loads((tmp_path / "artifact_contract.json").read_text())
    assert config["nir_passive_enabled"] is True
    assert contract["nir_passive"]["ready"] is True
    assert "nir_active_minus_passive" in contract["observations"]


def test_discover_next_skips_dataset_owned_by_active_backfill(tmp_path: Path):
    root = tmp_path / "work"
    root.mkdir()
    jobs = root / ".control" / "jobs"
    jobs.mkdir(parents=True)
    candidates = []
    for name in ("a_active", "b_next"):
        dataset = root / name
        prepared = root / ".pipeline" / name / "principled_stage2"
        prepared.mkdir(parents=True)
        (prepared / "derived_ir_principled_v1.blend").write_bytes(b"blend")
        dataset.mkdir()
        (dataset / "index.jsonl").write_text(
            '{"frame_id":"frame","paths":{"nir_passive":"nir_passive/frame.exr",'
            '"nir_active_minus_passive":"nir_active_minus_passive/frame.exr"}}\n',
            encoding="utf-8",
        )
        (dataset / "rolling_queue_state.json").write_text(json.dumps({
            "frame_count": 1, "completed": ["frame"], "pending": [], "failed": {},
        }), encoding="utf-8")
        (jobs / f"{name}.json").write_text(json.dumps({"request": {
            "paths": {"dataset": str(dataset), "prepared": str(prepared)},
        }}), encoding="utf-8")
        candidates.append((dataset, prepared))

    lock_path = candidates[0][0] / ".nir_passive_backfill" / "lock"
    lock_path.parent.mkdir()
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected, prepared = _discover_next(root)
        assert selected == candidates[1][0]
        assert prepared == candidates[1][1]


def test_passive_queue_does_not_adopt_active_only_row(tmp_path: Path):
    frame = "frame"
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"ok")
    paths = {name: "artifact.bin" for name in REQUIRED_MODALITIES}
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / f"{frame}.json").write_text(json.dumps({
        "frame_id": frame, "dataset_fingerprint": "fp", "paths": paths,
    }), encoding="utf-8")

    assert _row_complete(tmp_path, frame, "fp")
    assert not _row_complete(tmp_path, frame, "fp", require_passive=True)

    paths.update({name: "artifact.bin" for name in PASSIVE_NIR_MODALITIES})
    (tmp_path / "frames" / f"{frame}.json").write_text(json.dumps({
        "frame_id": frame, "dataset_fingerprint": "fp", "paths": paths,
    }), encoding="utf-8")
    assert _row_complete(tmp_path, frame, "fp", require_passive=True)
