"""Shared OpticalNav render-scene materialization boundary.

IR dataset preparation and the HTTP render daemon are separate execution
pipelines.  They intentionally share this deterministic scene compiler so
that XML, mesh-cache and audit contracts cannot drift between them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SCENE_MATERIALIZER_CONTRACT_VERSION = "opticalnav-scene-materializer-v2"


def materialize_render_scene(
    *,
    repo_root: Path,
    project_dir: Path,
    scene_dir: Path,
    scene_id: str,
    authoring_map: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    """Compile and publish one deterministic render scene.

    The implementation helpers currently live beside the daemon server for
    backwards compatibility, but consumers depend only on this public,
    daemon-state-free API.  No daemon, worker, queue or HTTP service is
    created by this function.
    """
    from .render_daemon import (
        _build_materialization_audit,
        _build_opticalnav_render_readiness,
        _build_render_scene_material_policy,
        _build_xml_scene_index,
        _generate_opticalnav_render_scene_xml,
        _stage_xml_obj_filenames_to_scene_mesh_cache,
    )

    render_scene_path = scene_dir / "render_scene.xml"
    mesh_stats: dict[str, Any] = {}
    materialization_records: list[dict[str, Any]] = []
    material_policy_records: list[dict[str, Any]] = []
    progress_enabled = os.environ.get("ROBOMITUBA_MATERIALIZE_PROGRESS", "") == "1"

    def shape_progress(done: int, total: int) -> None:
        if progress_enabled and (done == total or done % max(1, total // 20) == 0):
            print(f"[materialize] overlay objects {done}/{total}", flush=True)

    def cache_progress(done: int, total: int, detail: str, stage: str) -> None:
        if progress_enabled:
            print(f"[materialize] {stage} {done}/{total} {detail}", flush=True)

    shape_count = _generate_opticalnav_render_scene_xml(
        authoring_map,
        overlay,
        render_scene_path,
        editor_geometry=None,
        repo_root=repo_root,
        mesh_resolver=None,
        mesh_stats=mesh_stats,
        materialization_records=materialization_records,
        material_policy_records=material_policy_records,
        shape_progress_cb=shape_progress if progress_enabled else None,
    )
    material_policy = _build_render_scene_material_policy(
        scene_id=scene_id, material_policy_records=material_policy_records,
    )
    (scene_dir / "render_scene_material_policy.json").write_text(
        json.dumps(material_policy, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    try:
        render_scene_ref = render_scene_path.relative_to(repo_root).as_posix()
    except ValueError:
        # Integration tests deliberately publish into an isolated temporary
        # directory so production scene artifacts remain read-only.
        render_scene_ref = str(render_scene_path.resolve())
    mesh_stats["scene_mesh_cache"] = _stage_xml_obj_filenames_to_scene_mesh_cache(
        render_scene_path,
        scene_mesh_cache_dir=scene_dir / "mesh_cache",
        repo_root=repo_root,
        progress_cb=cache_progress if progress_enabled else None,
        materialization_records=materialization_records,
    )
    audit = _build_materialization_audit(
        scene_id=scene_id,
        overlay_objects=list(overlay.get("objects") or []),
        materialization_records=materialization_records,
        mesh_stats=mesh_stats,
    )
    audit["scene_materializer_contract"] = SCENE_MATERIALIZER_CONTRACT_VERSION
    (scene_dir / "render_scene_materialization.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    xml_index = _build_xml_scene_index(
        render_scene_path, scene_id=scene_id,
        materialization_records=materialization_records,
    )
    if xml_index is not None:
        (scene_dir / "xml_scene_index.json").write_text(
            json.dumps(xml_index, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    readiness = _build_opticalnav_render_readiness(
        authoring_map,
        repo_root=repo_root,
        render_scene_path=render_scene_path,
        render_scene_ref=render_scene_ref,
        overlay_shape_count=shape_count,
        materialization_records=materialization_records,
    )
    readiness["scene_materializer_contract"] = SCENE_MATERIALIZER_CONTRACT_VERSION
    (scene_dir / "render_readiness.json").write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return {
        "render_scene_path": render_scene_path,
        "render_scene_ref": render_scene_ref,
        "shape_count": shape_count,
        "mesh_stats": mesh_stats,
        "materialization_records": materialization_records,
        "readiness": readiness,
    }


__all__ = ["SCENE_MATERIALIZER_CONTRACT_VERSION", "materialize_render_scene"]
