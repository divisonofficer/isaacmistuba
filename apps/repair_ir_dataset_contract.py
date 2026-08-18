#!/usr/bin/env python3
"""Canonicalize repairable IR artifacts without rerendering valid frames."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "navigation_dataset", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from render_ir_principled_dataset_queue import (  # noqa: E402
    _atomic_json, _canonicalize_binary_masks, _derive_camera_depth, _qc_summary,
    _refresh_index, _row_complete,
)


def repair_dataset(dataset: Path) -> dict:
    dataset = dataset.resolve()
    config = json.loads((dataset / "dataset_config.json").read_text(encoding="utf-8"))
    fingerprint = str(config.get("dataset_fingerprint") or "")
    state_path = dataset / "rolling_queue_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else None
    rows = _refresh_index(dataset)
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
            if _row_complete(dataset, frame_id, fingerprint):
                finalized_frames.append(frame_id)
                continue
            try:
                _derive_camera_depth(dataset, row)
            except Exception as exc:
                print(f"[ir-contract-repair] cannot finalize {frame_id}: {exc}", flush=True)
                continue
            if _row_complete(dataset, frame_id, fingerprint):
                finalized_frames.append(frame_id)

        rows = _refresh_index(dataset)
        completed = {
            str(row["frame_id"]) for row in rows
            if _row_complete(dataset, str(row["frame_id"]), fingerprint)
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
