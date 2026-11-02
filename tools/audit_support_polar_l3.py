#!/usr/bin/env python3
"""Audit the L0 + L3 native-polar contract for one Navigation Support V4 scene.

The renderer queues K=4 leader tasks, but completion is defined in logical
``motion_node_id × heading_id`` views.  This tool expands the immutable L0 and
L3 plans, maps each supplied ledger run to its immutable render version, and
checks all three scene variants against their actual observation bundles.

Use ``--require-complete`` only when the render chain should be terminal.  The
default report is deliberately useful while rendering is still underway.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "opticalnav-v0.2"
SCENE_ID = "infinigen_apartment_20260811"
LEVELS = {
    "l0": "support_observation_plan.json",
    "l3": "support_observation_expansion_l3_context_45.json",
}
VARIANTS = ("base", "perturbed", "perturbed_active_polar")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _expected_keys(plan_path: Path) -> set[tuple[str, str]]:
    plan = _read_json(plan_path)
    entries = plan.get("render_entries")
    if not isinstance(entries, list):
        raise ValueError(f"render_entries missing: {plan_path}")
    keys: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError(f"non-object render entry: {plan_path}")
        node = str(entry.get("motion_node_id") or "")
        heading = str(entry.get("heading_id") or "")
        if not node or not heading:
            raise ValueError(f"malformed render entry: {plan_path}")
        keys.add((node, heading))
    if len(keys) != len(entries):
        raise ValueError(f"duplicate logical views in {plan_path}")
    return keys


def _run_version(connection: sqlite3.Connection, run_id: str) -> tuple[str | None, str | None]:
    row = connection.execute(
        "SELECT status, render_version_id FROM sweep_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None, None
    return str(row[0]), str(row[1])


def _task_states(connection: sqlite3.Connection, run_id: str) -> dict[str, int]:
    return {
        str(state): int(count)
        for state, count in connection.execute(
            "SELECT state, COUNT(*) FROM sweep_tasks WHERE run_id = ? GROUP BY state", (run_id,)
        )
    }


def _task_view_roots(
    connection: sqlite3.Connection,
    *,
    project_dir: Path,
    scene_dir: Path,
    run_id: str,
    default_version_id: str,
    variant: str,
) -> tuple[dict[tuple[str, str], Path], list[str]]:
    """Map every logical child view in a leader task to its physical root.

    Resume runs intentionally retain source-complete K=4 leaders as ``skipped``
    rows.  Their observation bundles remain in the immutable source render
    version, not the resumed run's version.  Audit by child view key so a
    source-reused K=4 strip is credited exactly once while newly rendered
    strips must exist in the current render version.
    """
    rows = connection.execute(
        """
        SELECT node_id, heading_id, render_version_id, metadata_json
        FROM sweep_tasks
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall()
    project_root = project_dir.resolve()
    observations_root = (scene_dir / "observations" / "versions").resolve()
    roots: dict[tuple[str, str], Path] = {}
    errors: list[str] = []
    for leader_node, leader_heading, row_version_id, metadata_raw in rows:
        try:
            metadata = json.loads(str(metadata_raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{leader_node}/{leader_heading}:metadata={exc}")
            continue
        if not isinstance(metadata, Mapping):
            errors.append(f"{leader_node}/{leader_heading}:metadata_not_object")
            continue
        source_ref = metadata.get("source_bundle_ref")
        if source_ref:
            try:
                source_bundle = (project_dir / str(source_ref)).resolve()
                source_bundle.relative_to(project_root)
                # The durable reference names a leaf
                # ``.../<variant>/<node>/<heading>``.  Children of that K=4
                # strip share the same immutable variant root.
                root = source_bundle.parent.parent
                root.relative_to(observations_root)
            except (OSError, ValueError) as exc:
                errors.append(f"{leader_node}/{leader_heading}:invalid_source_bundle_ref={exc}")
                continue
        else:
            version_id = str(row_version_id or default_version_id or "")
            if not version_id:
                errors.append(f"{leader_node}/{leader_heading}:missing_render_version_id")
                continue
            root = observations_root / version_id / variant

        raw_views = metadata.get("stokes_heading_batch_view_keys")
        views = raw_views if isinstance(raw_views, list) and raw_views else [
            {"node_id": leader_node, "heading_id": leader_heading}
        ]
        for raw_view in views:
            if not isinstance(raw_view, Mapping):
                errors.append(f"{leader_node}/{leader_heading}:malformed_batch_view")
                continue
            node, heading = str(raw_view.get("node_id") or ""), str(raw_view.get("heading_id") or "")
            if not node or not heading:
                errors.append(f"{leader_node}/{leader_heading}:malformed_batch_view")
                continue
            key = (node, heading)
            previous = roots.get(key)
            if previous is not None and previous != root:
                errors.append(f"{node}/{heading}:multiple_bundle_roots")
                continue
            roots[key] = root
    return roots, errors


def _view_record(version_root: Path, node: str, heading: str) -> dict[str, Any]:
    frame = version_root / node / heading
    manifest_path = frame / "manifest.json"
    timing_path = frame / "logs" / "render_timing.json"
    stokes_path = frame / "cameras" / "polar_cam" / "stokes_data.npz"
    record: dict[str, Any] = {
        "manifest": manifest_path.exists(),
        "timing": timing_path.exists(),
        "stokes_npz": stokes_path.exists(),
    }
    if not timing_path.exists():
        return record
    try:
        timing = _read_json(timing_path)
        polar = (
            timing.get("cameras", {})
            .get("polar_cam", {})
            .get("polarization", {})
        )
        if isinstance(polar, Mapping):
            record.update({
                "batch_size": polar.get("batch_size"),
                "stokes_basis": polar.get("stokes_basis"),
                "stokes_reference_axis": polar.get("stokes_reference_axis"),
                "scene_cache_hit": polar.get("scene_cache_hit"),
            })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        record["timing_error"] = str(exc)
    return record


def _sample(items: Iterable[str], limit: int = 12) -> list[str]:
    return list(sorted(items))[:limit]


def _audit_run(
    connection: sqlite3.Connection,
    *,
    scene_dir: Path,
    level: str,
    variant: str,
    run_id: str,
    expected: set[tuple[str, str]],
) -> dict[str, Any]:
    run_status, version_id = _run_version(connection, run_id)
    report: dict[str, Any] = {
        "run_id": run_id,
        "run_status": run_status,
        "render_version_id": version_id,
        "leader_task_states": _task_states(connection, run_id),
        "expected_logical_views": len(expected),
    }
    if not version_id:
        report["error"] = "run_not_found"
        return report
    project_dir = scene_dir.parents[1]
    root = scene_dir / "observations" / "versions" / version_id / variant
    view_roots, mapping_errors = _task_view_roots(
        connection,
        project_dir=project_dir,
        scene_dir=scene_dir,
        run_id=run_id,
        default_version_id=version_id,
        variant=variant,
    )
    complete: set[tuple[str, str]] = set()
    missing: list[str] = []
    corrupt: list[str] = list(mapping_errors)
    batches: Counter[str] = Counter()
    bases: Counter[str] = Counter()
    axes: Counter[str] = Counter()
    bundle_roots: Counter[str] = Counter()
    cache_hits = 0
    for node, heading in sorted(expected):
        key = f"{node}/{heading}"
        view_root = view_roots.get((node, heading))
        if view_root is None:
            missing.append(key)
            continue
        record = _view_record(view_root, node, heading)
        if not all(record.get(name) for name in ("manifest", "timing", "stokes_npz")):
            missing.append(key)
            continue
        complete.add((node, heading))
        bundle_roots[str(view_root)] += 1
        batches[str(record.get("batch_size"))] += 1
        bases[str(record.get("stokes_basis"))] += 1
        axes[json.dumps(record.get("stokes_reference_axis"), separators=(",", ":"))] += 1
        if record.get("scene_cache_hit") is True:
            cache_hits += 1
        if record.get("stokes_basis") != "world_gravity_y_v1":
            corrupt.append(f"{key}:stokes_basis={record.get('stokes_basis')!r}")
        if record.get("stokes_reference_axis") != [0.0, 1.0, 0.0]:
            corrupt.append(f"{key}:stokes_reference_axis={record.get('stokes_reference_axis')!r}")
    # Passive execution is K=4, except for the immutable plan's final short
    # strip (two or three logical headings).  ``batch_size=1`` would mean the
    # K=4 path silently fell back, so it is intentionally not accepted here.
    allowed_batches = {"1"} if variant == "perturbed_active_polar" else {"2", "3", "4"}
    expected_batch = "1" if variant == "perturbed_active_polar" else "K4 (tail K2/K3 allowed)"
    wrong_batch = sum(count for batch, count in batches.items() if batch not in allowed_batches)
    report.update({
        "complete_logical_views": len(complete),
        "missing_logical_views": len(missing),
        "missing_sample": _sample(missing),
        "metadata_error_count": len(corrupt),
        "metadata_error_sample": corrupt[:12],
        "batch_size_counts": dict(batches),
        "expected_batch_size": expected_batch,
        "wrong_batch_size_views": wrong_batch,
        "stokes_basis_counts": dict(bases),
        "stokes_reference_axis_counts": dict(axes),
        "scene_cache_hit_views": cache_hits,
        "version_root": str(root),
        "bundle_root_counts": dict(bundle_roots),
        "task_mapping_error_count": len(mapping_errors),
        "task_mapping_error_sample": mapping_errors[:12],
    })
    report["ok"] = (
        len(complete) == len(expected)
        and not corrupt
        and wrong_batch == 0
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=PROJECT_ID)
    parser.add_argument("--scene", default=SCENE_ID)
    parser.add_argument("--l0-base-run", required=True)
    parser.add_argument("--l0-perturbed-run", required=True)
    parser.add_argument("--l0-active-run", required=True)
    parser.add_argument("--l3-base-run", required=True)
    parser.add_argument("--l3-perturbed-run", required=True)
    parser.add_argument("--l3-active-run", required=True)
    parser.add_argument(
        "--plan-dir", default=".",
        help="scene-relative support-plan directory; accepts an immutable navigation_support_archives/<digest> recovery",
    )
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    scene_dir = (REPO_ROOT / "out" / "opticalnav" / args.project / "scenes" / args.scene).resolve()
    try:
        plan_dir = (scene_dir / args.plan_dir).resolve()
        plan_dir.relative_to(scene_dir)
    except (OSError, ValueError) as exc:
        parser.error(f"--plan-dir must stay inside the scene directory: {exc}")
    ledger = scene_dir / "operations" / "render_ledger.sqlite3"
    expected_by_level = {level: _expected_keys(plan_dir / ref) for level, ref in LEVELS.items()}
    union = expected_by_level["l0"] | expected_by_level["l3"]
    if len(expected_by_level["l0"]) != 2454 or len(expected_by_level["l3"]) != 1250 or len(union) != 3704:
        raise SystemExit(
            "unexpected logical coverage: "
            f"L0={len(expected_by_level['l0'])}, L3={len(expected_by_level['l3'])}, union={len(union)}"
        )
    run_ids = {
        "l0": {"base": args.l0_base_run, "perturbed": args.l0_perturbed_run, "perturbed_active_polar": args.l0_active_run},
        "l3": {"base": args.l3_base_run, "perturbed": args.l3_perturbed_run, "perturbed_active_polar": args.l3_active_run},
    }
    connection = sqlite3.connect(ledger)
    results = {
        level: {
            variant: _audit_run(
                connection,
                scene_dir=scene_dir,
                level=level,
                variant=variant,
                run_id=run_ids[level][variant],
                expected=expected_by_level[level],
            )
            for variant in VARIANTS
        }
        for level in ("l0", "l3")
    }
    all_ok = all(item.get("ok") is True for level in results.values() for item in level.values())
    report = {
        "scene_id": args.scene,
        "profile": "adaptive_navigation_support_v4",
        "plan_dir": plan_dir.relative_to(scene_dir).as_posix(),
        "expected_l0": len(expected_by_level["l0"]),
        "expected_l3_additional": len(expected_by_level["l3"]),
        "expected_total_per_variant": len(union),
        "all_ok": all_ok,
        "runs": results,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.require_complete and not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
