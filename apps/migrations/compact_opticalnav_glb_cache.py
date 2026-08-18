#!/usr/bin/env python3
"""Promote validated staged GLB OBJs and remove legacy duplicate caches.

This migration is intentionally conservative: ``--apply`` requires both local
render daemons to be stopped, an exact authoring/audit source match, a complete
legacy part -> staged OBJ mapping, and a successful prior assembly-bounds audit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


ADAPTER_VERSION = 7
SAFE_CONTRACT = "mitsuba_safe_glb_part_v1"
STAGE_OBJ_VERSION = 5


def _debug(label: str, started: float) -> None:
    if os.environ.get("ROBOMITUBA_COMPACTION_DEBUG"):
        print(f"[compact-cache] {label}: {time.perf_counter() - started:.3f}s", file=sys.stderr, flush=True)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return raw


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _repo_ref(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _staged_path(part_path: Path, mesh_cache: Path) -> Path:
    stat = part_path.stat()
    digest = hashlib.sha1(
        (
            f"{part_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|"
            f"preserve_assembly_local|stage_obj_v{STAGE_OBJ_VERSION}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    return mesh_cache / f"{digest}.obj"


def _daemon_ports_alive() -> list[int]:
    alive: list[int] = []
    for port in (8765, 8766):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5):
                alive.append(port)
        except Exception:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    alive.append(port)
            except OSError:
                pass
    return alive


def _open_cache_fds(mesh_cache: Path) -> list[str]:
    prefix = str(mesh_cache.resolve()) + os.sep
    matches: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return matches
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        fd_dir = pid_dir / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith(prefix):
                matches.append(f"pid={pid_dir.name} fd={fd.name} {target}")
                if len(matches) >= 20:
                    return matches
    return matches


def _collect(repo_root: Path, project: str, scene: str) -> dict[str, Any]:
    started = time.perf_counter()
    project_dir = repo_root / "out" / "opticalnav" / project
    scene_dir = project_dir / "scenes" / scene
    mesh_cache = scene_dir / "mesh_cache"
    authoring_path = scene_dir / "authoring_map.json"
    audit_path = scene_dir / "render_scene_materialization.json"
    xml_path = scene_dir / "render_scene.xml"
    annotation_path = scene_dir / "scene_annotation.json"
    for path in (scene_dir, mesh_cache, authoring_path, xml_path, annotation_path):
        if not path.exists():
            raise FileNotFoundError(path)

    authoring = _read_json(authoring_path)
    current_refs = {
        (str(row.get("id") or ""), str(row.get("source_ref") or ""))
        for row in authoring.get("objects") or [] if row.get("source_ref")
    }
    prior_manifest_path = scene_dir / "cache_compaction_manifest.json"
    if audit_path.is_file():
        audit = _read_json(audit_path)
        audit_refs = {
            (str(row.get("object_id") or ""), str(row.get("source_ref") or ""))
            for row in audit.get("objects") or [] if row.get("source_ref")
        }
        if current_refs != audit_refs:
            raise ValueError(
                f"authoring/audit GLB refs differ: current={len(current_refs)} audit={len(audit_refs)} "
                f"missing={len(current_refs - audit_refs)} stale={len(audit_refs - current_refs)}"
            )
        stage_stats = dict((audit.get("mesh_stats") or {}).get("scene_mesh_cache") or {})
        preserved = int(stage_stats.get("preserved_positions") or 0)
        tolerance = float(stage_stats.get("preserved_bounds_tolerance_m") or 0.0)
        raw_delta = stage_stats.get("preserved_bounds_max_abs_delta_m")
        delta = float(raw_delta) if raw_delta is not None else float("inf")
    elif prior_manifest_path.is_file():
        prior = _read_json(prior_manifest_path)
        if prior.get("status") != "complete" or int(prior.get("source_ref_count") or 0) != len(current_refs):
            raise ValueError("compaction evidence does not match the current authoring map")
        preserved = int(prior.get("canonical_part_count") or 0)
        tolerance = float(prior.get("bounds_tolerance_m") or 0.0)
        raw_delta = prior.get("bounds_delta_m")
        delta = float(raw_delta) if raw_delta is not None else float("inf")
    else:
        raise FileNotFoundError(audit_path)
    if preserved <= 0 or tolerance <= 0 or delta > tolerance:
        raise ValueError(
            f"prior bounds audit is not reusable: preserved={preserved} delta={delta} tolerance={tolerance}"
        )
    _debug("authoring and audit", started)

    meta_paths = sorted(mesh_cache.glob("glb_*.meta.json"))
    if not meta_paths:
        raise ValueError("no GLB adapter metadata found")
    rewritten_meta: dict[Path, dict[str, Any]] = {}
    meta_sources: dict[Path, Path] = {}
    old_to_canonical: dict[str, Path] = {}
    canonical_paths: set[Path] = set()
    legacy_part_count = 0
    for meta_path in meta_paths:
        meta = _read_json(meta_path)
        parts = list(meta.get("mesh_parts") or [])
        if not parts:
            raise ValueError(f"metadata has no parts: {meta_path}")
        migrated_parts: list[dict[str, Any]] = []
        already_safe = (
            int(meta.get("adapter_version") or 0) >= ADAPTER_VERSION
            and meta.get("obj_contract") == SAFE_CONTRACT
        )
        for raw_part in parts:
            part = dict(raw_part)
            old_path = _repo_path(repo_root, str(part.get("obj_path") or part.get("obj_ref") or ""))
            if already_safe and part.get("obj_contract") == SAFE_CONTRACT:
                canonical = old_path
            else:
                if not old_path.is_file() or old_path.stat().st_size <= 0:
                    raise ValueError(f"legacy GLB part missing: {old_path}")
                canonical = _staged_path(old_path, mesh_cache)
                old_to_canonical[str(old_path.resolve())] = canonical.resolve()
                legacy_part_count += 1
            if not canonical.is_file() or canonical.stat().st_size <= 0:
                raise ValueError(f"canonical staged OBJ missing: {canonical}")
            canonical = canonical.resolve()
            canonical_paths.add(canonical)
            ref = _repo_ref(repo_root, canonical)
            part.update({
                "obj_path": ref,
                "obj_ref": ref,
                "obj_contract": SAFE_CONTRACT,
            })
            migrated_parts.append(part)
        source_path = Path(str(meta.get("source_path") or ""))
        if not source_path.is_absolute():
            source_path = repo_root / source_path
        source_stat = source_path.stat() if source_path.is_file() else None
        if source_stat is None:
            raise ValueError(f"GLB source missing: {source_path}")
        v7_digest = hashlib.sha1(
            (
                f"{source_path.resolve()}|{source_stat.st_mtime_ns}|{source_stat.st_size}|"
                f"glb_adapter_v{ADAPTER_VERSION}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        target_meta_path = mesh_cache / f"glb_{v7_digest}.meta.json"
        previous_source = meta_sources.get(target_meta_path)
        if previous_source is not None and previous_source != meta_path:
            raise ValueError(
                f"multiple adapter metadata files map to {target_meta_path.name}: "
                f"{previous_source.name}, {meta_path.name}"
            )
        meta.update({
            "digest": v7_digest,
            "adapter_version": ADAPTER_VERSION,
            "obj_contract": SAFE_CONTRACT,
            "combined_obj_path": None,
            "combined_obj_ref": None,
            "mesh_parts": migrated_parts,
            "source_mtime_ns": int(source_stat.st_mtime_ns) if source_stat else int(meta.get("source_mtime_ns") or 0),
            "source_size": int(source_stat.st_size) if source_stat else int(meta.get("source_size") or 0),
            "cache_compacted_at": _utc_now_iso(),
        })
        rewritten_meta[target_meta_path] = meta
        meta_sources[target_meta_path] = meta_path
    _debug("metadata and canonical mapping", started)

    if len(canonical_paths) != preserved:
        raise ValueError(
            f"canonical/audit count mismatch: canonical={len(canonical_paths)} preserved={preserved}"
        )

    combined = sorted(mesh_cache.glob("glb_*.obj"))
    part_dirs = sorted(path for path in mesh_cache.glob("glb_*_parts") if path.is_dir())
    top_ancillary = sorted(
        path for path in mesh_cache.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".mtl"}
    )
    deletion_targets = [*combined, *part_dirs, *top_ancillary]
    retained_meta_text = json.dumps(list(rewritten_meta.values()), ensure_ascii=False)
    for ancillary in top_ancillary:
        if str(ancillary.resolve()) in retained_meta_text or _repo_ref(repo_root, ancillary) in retained_meta_text:
            raise ValueError(f"top-level ancillary is still referenced by canonical metadata: {ancillary}")
    _debug("ancillary references", started)

    xml_tree = ET.parse(xml_path)
    unmapped_deleted_refs: list[str] = []
    combined_resolved = {path.resolve() for path in combined}
    part_dirs_resolved = {path.resolve() for path in part_dirs}
    for node in xml_tree.findall(".//string[@name='filename']"):
        raw = str(node.get("value") or "")
        resolved = _repo_path(repo_root, raw).resolve()
        if str(resolved) in old_to_canonical or resolved in canonical_paths:
            continue
        if resolved in combined_resolved or any(parent in part_dirs_resolved for parent in resolved.parents):
            unmapped_deleted_refs.append(str(resolved))
    if unmapped_deleted_refs:
        raise ValueError(f"XML has {len(unmapped_deleted_refs)} references into deletion targets")
    _debug("XML references", started)

    deletion_bytes = 0
    deletion_files = 0
    for target in deletion_targets:
        if target.is_dir():
            for path in target.rglob("*"):
                if path.is_file():
                    deletion_files += 1
                    deletion_bytes += path.stat().st_size
        elif target.is_file():
            deletion_files += 1
            deletion_bytes += target.stat().st_size
    _debug("deletion inventory", started)

    return {
        "repo_root": repo_root,
        "project_dir": project_dir,
        "scene_dir": scene_dir,
        "mesh_cache": mesh_cache,
        "xml_path": xml_path,
        "annotation_path": annotation_path,
        "meta": rewritten_meta,
        "meta_sources": meta_sources,
        "mapping": old_to_canonical,
        "canonical_paths": canonical_paths,
        "deletion_targets": deletion_targets,
        "deletion_files": deletion_files,
        "deletion_bytes": deletion_bytes,
        "source_ref_count": len(current_refs),
        "part_count": len(canonical_paths),
        "legacy_part_count": legacy_part_count,
        "bounds_delta": delta,
        "bounds_tolerance": tolerance,
        "already_compacted": (
            legacy_part_count == 0
            and not deletion_targets
            and all(target == source for target, source in meta_sources.items())
        ),
    }


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": state["project_dir"].name,
        "scene": state["scene_dir"].name,
        "source_ref_count": state["source_ref_count"],
        "canonical_part_count": state["part_count"],
        "legacy_parts_to_promote": state["legacy_part_count"],
        "metadata_count": len(state["meta"]),
        "delete_file_count": state["deletion_files"],
        "delete_bytes": state["deletion_bytes"],
        "delete_gib": round(state["deletion_bytes"] / (1024 ** 3), 3),
        "bounds_delta_m": state["bounds_delta"],
        "bounds_tolerance_m": state["bounds_tolerance"],
    }


def _apply(state: dict[str, Any]) -> dict[str, Any]:
    alive = _daemon_ports_alive()
    if alive:
        raise RuntimeError(f"stop local daemons before --apply; active ports: {alive}")
    open_fds = _open_cache_fds(state["mesh_cache"])
    if open_fds:
        raise RuntimeError("scene cache is open by another process: " + "; ".join(open_fds))
    if state.get("already_compacted"):
        prior = _read_json(state["scene_dir"] / "cache_compaction_manifest.json")
        return {**prior, "idempotent": True}

    scene_dir: Path = state["scene_dir"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = scene_dir / "cache_compaction_backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_names = (
        "scene_annotation.json", "render_scene.xml", "scene_variant.json",
        "render_readiness.json", "render_scene_materialization.json",
        "render_scene_material_policy.json", "xml_scene_index.json",
        "render_scene_sync_gate.json", "editor_preview_mesh_manifest.json",
    )
    for name in backup_names:
        source = scene_dir / name
        if source.is_file():
            shutil.copy2(source, backup_dir / name)
    meta_backup = backup_dir / "glb_meta"
    meta_backup.mkdir()
    for source_meta_path in state["meta_sources"].values():
        shutil.copy2(source_meta_path, meta_backup / source_meta_path.name)

    for meta_path, payload in state["meta"].items():
        _atomic_json(meta_path, payload)
    for target_meta_path, source_meta_path in state["meta_sources"].items():
        if source_meta_path != target_meta_path:
            source_meta_path.unlink()

    tree = ET.parse(state["xml_path"])
    rewritten = 0
    for node in tree.findall(".//string[@name='filename']"):
        raw = str(node.get("value") or "")
        try:
            resolved = str(_repo_path(state["repo_root"], raw).resolve())
        except Exception:
            continue
        canonical = state["mapping"].get(resolved)
        if canonical is not None:
            node.set("value", str(canonical))
            rewritten += 1
    xml_tmp = state["xml_path"].with_name(f"render_scene.xml.tmp.{os.getpid()}")
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    tree.write(xml_tmp, encoding="utf-8", xml_declaration=True)
    xml_tmp.replace(state["xml_path"])

    annotation = _read_json(state["annotation_path"])
    sync = dict(annotation.get("metadata", {}).get("sync", {}))
    sync.update({
        "render_scene": "pending",
        "render_scene_status": "cache_compacted",
        "render_readiness_status": "pending",
        "message": "GLB cache compacted; run render-scene sync once to rebuild derived sidecars.",
        "cache_compacted_at": _utc_now_iso(),
    })
    annotation.setdefault("metadata", {})["sync"] = sync
    _atomic_json(state["annotation_path"], annotation)

    for name in (
        "render_readiness.json", "render_scene_materialization.json",
        "render_scene_material_policy.json", "xml_scene_index.json",
        "render_scene_sync_gate.json", "editor_preview_mesh_manifest.json",
    ):
        (scene_dir / name).unlink(missing_ok=True)

    removed_files = 0
    removed_bytes = 0
    for target in state["deletion_targets"]:
        if target.is_dir():
            for path in target.rglob("*"):
                if path.is_file():
                    removed_files += 1
                    removed_bytes += path.stat().st_size
            shutil.rmtree(target)
        elif target.is_file():
            removed_files += 1
            removed_bytes += target.stat().st_size
            target.unlink()

    prior_manifest_path = scene_dir / "cache_compaction_manifest.json"
    prior_manifest = _read_json(prior_manifest_path) if prior_manifest_path.is_file() else {}
    manifest = {
        "version": 1,
        "status": "complete",
        "completed_at": _utc_now_iso(),
        **_summary(state),
        "xml_refs_rewritten": rewritten,
        "removed_files": removed_files + int(prior_manifest.get("removed_files") or 0),
        "removed_bytes": removed_bytes + int(prior_manifest.get("removed_bytes") or 0),
        "last_apply_removed_files": removed_files,
        "last_apply_removed_bytes": removed_bytes,
        "backup_ref": _repo_ref(state["repo_root"], backup_dir),
        "canonical_contract": SAFE_CONTRACT,
    }
    _atomic_json(scene_dir / "cache_compaction_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--project", required=True)
    parser.add_argument("--scene", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        state = _collect(args.repo_root.resolve(), args.project, args.scene)
        result = _apply(state) if args.apply else {"status": "dry_run", **_summary(state)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
