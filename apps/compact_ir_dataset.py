#!/usr/bin/env python3
"""Create an immutable compact child of a published Principled IR dataset.

The source is never modified.  The child keeps the exact frame topology,
camera/PBR/mask artifacts and scene-linear observations, rewrites EXR payloads
as ZIP-compressed HALF, and drops the auxiliary diffuse decomposition family.
It stages beside the requested output and becomes visible only after the normal
publish validator accepts the complete child.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.ir_dataset_contract import (  # noqa: E402
    HDR_MODALITIES,
    STORAGE_PROFILE_CORE_HALF_EXR_V1,
    storage_profile_spec,
)
from mitsuba_converter.ir_dataset_publish import publish_dataset, validate_publish_source  # noqa: E402


DIFFUSE_PREFIXES = (
    "diffuse_component_", "diffuse_transport_", "diffuse_reflectance_",
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _is_diffuse(modality: str) -> bool:
    return modality.startswith(DIFFUSE_PREFIXES)


def _write_half_exr(destination: Path, value: np.ndarray) -> None:
    if value is None or not np.issubdtype(value.dtype, np.floating):
        raise ValueError(f"cannot compact non-floating EXR: {destination}")
    if not np.isfinite(value).all():
        raise ValueError(f"cannot compact non-finite EXR: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.partial{destination.suffix}")
    options = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF]
    if hasattr(cv2, "IMWRITE_EXR_COMPRESSION_ZIP"):
        options += [cv2.IMWRITE_EXR_COMPRESSION, cv2.IMWRITE_EXR_COMPRESSION_ZIP]
    if not cv2.imwrite(str(temporary), value.astype(np.float32, copy=False), options):
        raise RuntimeError(f"failed to write half EXR: {temporary}")
    os.replace(temporary, destination)


def _copy_or_convert(source: Path, destination: Path, modality: str) -> None:
    if destination.is_file():
        return
    if modality in HDR_MODALITIES:
        value = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
        if value is None:
            raise ValueError(f"cannot decode source EXR: {source}")
        _write_half_exr(destination, value)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.partial")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)


def _compact(source: Path, stage: Path) -> dict[str, Any]:
    validate_publish_source(source)
    config, contract = _json(source / "dataset_config.json"), _json(source / "artifact_contract.json")
    rows = [json.loads(line) for line in (source / "index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    parent_fingerprint = str(config["dataset_fingerprint"])
    dropped_modalities = sorted({
        str(name) for row in rows for name in (row.get("paths") or {}) if _is_diffuse(str(name))
    })
    child_fingerprint = _digest({
        "schema": "robomituba.ir_principled_compact_child.v1",
        "parent_fingerprint": parent_fingerprint,
        "storage_profile": STORAGE_PROFILE_CORE_HALF_EXR_V1,
        "frame_ids": [str(row.get("frame_id")) for row in rows],
    })

    for row in rows:
        paths = dict(row.get("paths") or {})
        retained = {name: relative for name, relative in paths.items() if not _is_diffuse(str(name))}
        for modality, relative in retained.items():
            src = source / str(relative)
            dst = stage / str(relative)
            _copy_or_convert(src, dst, str(modality))
        row["paths"] = retained
        row["dataset_fingerprint"] = child_fingerprint
        _atomic_json(stage / "frames" / f"{row['frame_id']}.json", row)

    storage = storage_profile_spec(STORAGE_PROFILE_CORE_HALF_EXR_V1)
    config["dataset_fingerprint"] = child_fingerprint
    config["storage_profile"] = STORAGE_PROFILE_CORE_HALF_EXR_V1
    config["compaction"] = {
        "schema": "robomituba.ir_principled_compaction.v1",
        "parent_dataset_fingerprint": parent_fingerprint,
        "profile": STORAGE_PROFILE_CORE_HALF_EXR_V1,
        "dropped_modalities": dropped_modalities,
    }
    contract["dataset_fingerprint"] = child_fingerprint
    contract["storage_profile"] = storage
    for name in list((contract.get("ground_truth") or {})):
        if _is_diffuse(str(name)):
            contract["ground_truth"].pop(name, None)
    for name in list((contract.get("masks") or {})):
        if _is_diffuse(str(name)):
            contract["masks"].pop(name, None)
    contract["diffuse_decomposition"] = {
        **(contract.get("diffuse_decomposition") or {}),
        "stored": False,
        "availability": "diagnostic_parent_only",
    }
    for name, spec in (contract.get("observations") or {}).items():
        if name in HDR_MODALITIES and isinstance(spec, dict):
            spec["encoding"] = str(spec.get("encoding") or "").replace("float32", "float16")
    contract["compaction"] = dict(config["compaction"])

    queue_state = _json(source / "rolling_queue_state.json")
    queue_state["dataset_fingerprint"] = child_fingerprint
    qc = _json(source / "qc_summary.json")
    qc["storage_profile"] = STORAGE_PROFILE_CORE_HALF_EXR_V1

    overview_path = source / "scene_overview.json"
    if overview_path.is_file():
        overview = _json(overview_path)
        overview["dataset_fingerprint"] = child_fingerprint
        _atomic_json(stage / "scene_overview.json", overview)
    for name in ("scene_overview", "qc", "material_visibility_qc.json", "dataset_utility_audit.json"):
        source_path = source / name
        target_path = stage / name
        if source_path.is_dir() and not target_path.exists():
            shutil.copytree(source_path, target_path, symlinks=False)
        elif source_path.is_file() and not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)

    _atomic_json(stage / "dataset_config.json", config)
    _atomic_json(stage / "artifact_contract.json", contract)
    _atomic_json(stage / "rolling_queue_state.json", queue_state)
    _atomic_json(stage / "qc_summary.json", qc)
    (stage / "index.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"parent_fingerprint": parent_fingerprint, "dataset_fingerprint": child_fingerprint, "frames": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new compact child under /bean/ir_dataset_work")
    parser.add_argument("--publish", action="store_true", help="publish the verified child after compaction")
    parser.add_argument("--publish-name", help="required when --publish; must not collide with the parent")
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    if not source.is_dir() or source.is_symlink():
        parser.error("--source must be a real dataset directory")
    if out.exists():
        parser.error("--out already exists; compact children are immutable")
    stage = out.with_name(f".{out.name}.compacting")
    if stage.exists():
        parser.error(f"staging exists: {stage}; inspect or remove it before starting again")
    stage.mkdir(parents=True)
    try:
        result = _compact(source, stage)
        validate_publish_source(stage)
        os.replace(stage, out)
        result.update({"out": str(out), "mode": "compacted"})
        if args.publish:
            if not args.publish_name:
                parser.error("--publish-name is required with --publish")
            result["publish"] = publish_dataset(out, Path("/bean/ir_dataset"), name=args.publish_name)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception:
        # Preserve staging evidence; it is safer to inspect than to destroy a
        # partial conversion on a network filesystem.
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
