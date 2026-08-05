#!/usr/bin/env python3
"""Index legacy ``out/bridge_jobs`` attempts into the versioned render ledger.

The command is intentionally read-only by default. It never rewrites an old
job directory; after indexing, ``archive_completed_bridge_jobs.py`` can move
only entries that are no longer referenced by active pointers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
from mitsuba_converter.versioned_artifacts import RenderLedger  # noqa: E402


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _legacy_id(prefix: str, value: str) -> str:
    return f"{prefix}_legacy_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def index_job(job_dir: Path, *, repo_root: Path = REPO_ROOT, apply: bool = False) -> dict | None:
    request_path = next(iter(sorted((job_dir / "requests").glob("*.json"))), None)
    if request_path is None:
        return None
    request = _read(request_path)
    extras = dict(request.get("extras") or {})
    manifest_path = next(iter(sorted((job_dir / "observations").glob("*/manifest.json"))), None)
    manifest = _read(manifest_path) if manifest_path else {}
    mextras = dict(manifest.get("extras") or {})
    project_id = str(extras.get("opticalnav_project_id") or mextras.get("opticalnav_project_id") or "")
    scene_id = str(extras.get("opticalnav_scene_id") or mextras.get("scene_id") or request.get("scene_state", {}).get("scene_id") or "legacy")
    if not project_id:
        return {"job_id": job_dir.name, "status": "unscoped", "reason": "missing opticalnav_project_id"}
    project_dir = repo_root / "out" / "opticalnav" / project_id
    scene_ref = str(request.get("scene_state", {}).get("mitsuba_scene_ref") or "legacy")
    scene_version = _legacy_id("sv", scene_ref)
    scene_digest = hashlib.sha256(scene_ref.encode()).hexdigest()
    render_version = _legacy_id("rv", job_dir.name)
    run_id = f"legacy-{job_dir.name}"
    task_key = _legacy_id("tk", f"{job_dir.name}:{request.get('frame_id', request_path.stem)}")
    status = str(_read(job_dir / "job_status.json").get("status") or ("succeeded" if manifest_path else "unknown"))
    mapped = "succeeded" if status in {"succeeded", "completed", "success"} else "failed" if status in {"failed", "error"} else "planned"
    summary = {"job_id": job_dir.name, "project_id": project_id, "scene_id": scene_id, "status": mapped, "indexed": apply}
    if not apply:
        return summary
    ledger = RenderLedger(project_dir)
    ledger.create_scene_version(project_id=project_id, scene_id=scene_id, scene_version_id_value=scene_version, scene_digest=scene_digest, metadata={"legacy_bridge_job": job_dir.name, "scene_ref": scene_ref})
    ledger.create_render_run(run_id=run_id, project_id=project_id, scene_id=scene_id, scene_version_id_value=scene_version, render_version_id=render_version, metadata={"legacy_bridge_job": job_dir.name})
    blob = ledger.put_request_blob(request)
    ledger.put_task(task_key_value=task_key, logical_task_key=task_key, run_id=run_id, render_version_id=render_version, variant="perturbed" if "perturbed" in job_dir.name else "base", phase=str(extras.get("phase") or "legacy"), phase_index=int(extras.get("phase_index") or 0), ordinal=0, node_id=str(extras.get("opticalnav_vp_id") or "legacy"), heading_id=str(extras.get("opticalnav_heading_id") or "legacy"), metadata={"legacy_bridge_job": job_dir.name, "manifest_ref": str(manifest_path) if manifest_path else None}, request_blob_digest=blob)
    ledger.update_task(task_key, state=mapped)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-dir", type=Path, default=REPO_ROOT / "out" / "bridge_jobs")
    parser.add_argument("--apply", action="store_true", help="write ledger rows; default is a dry-run")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    rows = []
    for index, job_dir in enumerate(sorted(p for p in args.bridge_dir.iterdir() if p.is_dir())):
        if args.limit and index >= args.limit:
            break
        row = index_job(job_dir, repo_root=REPO_ROOT, apply=args.apply)
        if row:
            rows.append(row)
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"scanned": len(rows), "counts": counts, "apply": args.apply}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
