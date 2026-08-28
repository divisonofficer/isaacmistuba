#!/usr/bin/env python3
"""Canonicalize repairable IR artifacts without rerendering valid frames."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "navigation_dataset", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from render_ir_principled_dataset_queue import (  # noqa: E402
    _atomic_json, _canonicalize_binary_masks, _derive_camera_depth, _qc_summary,
    _refresh_index, _row_complete,
)
from mitsuba_converter.ir_dataset_contract import LEGACY_DATASET_SCHEMA, _safe_artifact_path  # noqa: E402


def _row_complete_for_repair(dataset: Path, frame_id: str, fingerprint: str, *, legacy_v2: bool) -> bool:
    """Check completeness without applying the current renderer's v3 schema to v2.

    A v2 dataset is immutable and legitimately lacks later v3 modalities such
    as metal-family and diffuse-transport maps.  Contract repair is invoked
    immediately before publish, so applying ``_row_complete`` unconditionally
    reset an otherwise finished v2 rolling state to zero completed frames.
    The publisher still decodes and validates every indexed artifact below.
    """
    if not legacy_v2:
        return _row_complete(dataset, frame_id, fingerprint)
    path = dataset / "frames" / f"{frame_id}.json"
    if not path.is_file():
        return False
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        paths = row.get("paths") or {}
        if row.get("dataset_fingerprint") != fingerprint or not isinstance(paths, dict) or not paths:
            return False
        return all(_safe_artifact_path(dataset, str(relative)).is_file() for relative in paths.values())
    except Exception:
        return False


def repair_dataset(dataset: Path) -> dict:
    dataset = dataset.resolve()
    config = json.loads((dataset / "dataset_config.json").read_text(encoding="utf-8"))
    fingerprint = str(config.get("dataset_fingerprint") or "")
    legacy_v2 = config.get("schema") == LEGACY_DATASET_SCHEMA
    state_path = dataset / "rolling_queue_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
    # A compatible-plan resume deliberately leaves old frame metadata and
    # pixels in place for provenance.  Contract repair must never reintroduce
    # those legacy rows into the authoritative index.
    rows = _refresh_index(dataset, fingerprint=fingerprint)

    # v3 prepared scenes predate the optional remediation/provenance AOVs.  A
    # completed render from those scenes is still valid: materialize the
    # documented neutral values and add the paths to each frame record so the
    # v2 completeness contract can be checked without an expensive rerender.
    # ``train_pbr_valid_mask`` is the conservative source-valid mask for a
    # legacy frame; the other two channels are zero/unknown.
    legacy_upgrades = 0
    for row in rows:
        frame_id = str(row.get("frame_id") or "")
        row_path = dataset / "frames" / f"{frame_id}.json"
        if not frame_id or not row_path.is_file():
            continue
        paths = dict(row.get("paths") or {})
        source_rel = paths.get("source_valid_mask")
        source_path = dataset / source_rel if source_rel else None
        if source_path is None or not source_path.is_file():
            continue
        source = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
        if source is None or source.dtype != np.uint8 or source.ndim != 2:
            continue
        changed = False
        for modality, value in (
            ("remediated_pbr_mask", np.zeros_like(source, dtype=np.uint8)),
            ("pbr_provenance_class", np.zeros_like(source, dtype=np.uint8)),
            ("train_pbr_valid_mask", np.where(source >= 128, 255, 0).astype(np.uint8)),
        ):
            rel = paths.get(modality) or f"{modality}/{frame_id}.png"
            target = dataset / rel
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(f".{target.name}.{id(row)}.tmp.png")
                if not cv2.imwrite(str(temp), value, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                    raise RuntimeError(f"failed to materialize legacy contract artifact: {target}")
                temp.replace(target)
            if paths.get(modality) != rel:
                paths[modality] = rel
                changed = True
        if changed:
            row["paths"] = paths
            temp_row = row_path.with_name(f".{row_path.name}.{id(row)}.tmp")
            temp_row.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            temp_row.replace(row_path)
            legacy_upgrades += 1
    if legacy_upgrades:
        rows = _refresh_index(dataset, fingerprint=fingerprint)
        print(f"[ir-contract-repair] upgraded legacy frame metadata rows={legacy_upgrades}", flush=True)
    report_path = dataset / "contract_repair.json"
    if report_path.is_file():
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if (
            previous.get("status") == "succeeded"
            and previous.get("dataset_fingerprint") == fingerprint
            and int(previous.get("frame_count") or -1) == len(rows)
            and not ((state or {}).get("pending") or (state or {}).get("failed"))
        ):
            print(f"[ir-contract-repair] reused {report_path}", flush=True)
            return previous

    repaired = Counter()
    finalized_frames: list[str] = []
    if state is not None:
        incomplete = set(state.get("pending") or []) | set((state.get("failed") or {}).keys())
        for frame_id in sorted(incomplete):
            row_path = dataset / "frames" / f"{frame_id}.json"
            if not row_path.is_file():
                continue
            row = json.loads(row_path.read_text(encoding="utf-8"))
            if _row_complete_for_repair(dataset, frame_id, fingerprint, legacy_v2=legacy_v2):
                finalized_frames.append(frame_id)
                continue
            try:
                _derive_camera_depth(dataset, row)
            except Exception as exc:
                print(f"[ir-contract-repair] cannot finalize {frame_id}: {exc}", flush=True)
                continue
            if _row_complete_for_repair(dataset, frame_id, fingerprint, legacy_v2=legacy_v2):
                finalized_frames.append(frame_id)

        rows = _refresh_index(dataset, fingerprint=fingerprint)
        completed = {
            str(row["frame_id"]) for row in rows
            if _row_complete_for_repair(dataset, str(row["frame_id"]), fingerprint, legacy_v2=legacy_v2)
        }
        unresolved = sorted(incomplete - completed)
        old_failed = state.get("failed") or {}
        state["completed"] = sorted(completed)
        state["pending"] = unresolved
        state["failed"] = {frame_id: old_failed.get(frame_id, "artifact repair incomplete") for frame_id in unresolved}
        groups: dict[str, dict] = {}
        for row in rows:
            lighting = row.get("lighting") or {}
            ident = str(lighting.get("id") or "legacy")
            group = groups.setdefault(ident, {
                "total": 0, "completed": 0,
                "capture_group_id": lighting.get("capture_group_id"),
            })
            group["total"] += 1
            if str(row.get("frame_id")) in completed:
                group["completed"] += 1
        for group in groups.values():
            group["percent"] = 100.0 * group["completed"] / max(group["total"], 1)
        state["lighting_groups"] = groups
        _atomic_json(state_path, state)
        expected = int(state.get("frame_count") or len(rows))
        if len(completed) != expected:
            raise RuntimeError(
                f"dataset remains incomplete after repair: {len(completed)}/{expected}; "
                f"unresolved={unresolved}"
            )
    repaired_frames = 0
    for row in rows:
        changes = _canonicalize_binary_masks(dataset, row)
        if changes:
            repaired_frames += 1
            repaired.update(changes)
    qc = _qc_summary(dataset, rows) if rows else {}
    report = {
        "schema": "robomituba.ir_dataset_contract_repair.v1",
        "status": "succeeded",
        "dataset_fingerprint": fingerprint,
        "frame_count": len(rows),
        "repaired_frame_count": repaired_frames,
        "repaired_pixel_counts": dict(sorted(repaired.items())),
        "finalized_frame_count": len(finalized_frames),
        "finalized_frames": finalized_frames,
        "binary_threshold": 0.5,
        "primary_eval_valid": "source_valid AND NOT replacement",
        "qc_frame_count": qc.get("frame_count"),
    }
    _atomic_json(report_path, report)
    print(
        f"[ir-contract-repair] frames={len(rows)} repaired_frames={repaired_frames} "
        f"pixels={sum(repaired.values())}", flush=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    repair_dataset(args.dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
