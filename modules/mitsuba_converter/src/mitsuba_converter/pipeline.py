from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from robomituba_bridge import load_job_bundle, repo_root_from, resolve_repo_path

from .usd_loader import UsdSceneLoader
from .mitsuba_builder import MitsubaSceneBuilder


def convert_usd_to_mitsuba_dict(usd_path: str, *, width: int = 768, height: int = 768, spp: int = 64) -> Dict[str, Any]:
    ir = UsdSceneLoader(usd_path=usd_path).load()
    scene = MitsubaSceneBuilder(width=width, height=height, spp=spp).build(ir)
    return scene


def build_scene_dict_from_job(
    manifest_path: str,
    *,
    repo_root: str | Path | None = None,
    width: int = 768,
    height: int = 768,
    spp: int = 64,
    render_mode: str = "rgb",
) -> Dict[str, Any]:
    root = Path(repo_root) if repo_root else repo_root_from(manifest_path)
    _, snapshot = load_job_bundle(manifest_path, repo_root=root)

    fallback_ir = None
    needs_fallback_geometry = any(not mesh.geometry_path for mesh in snapshot.meshes) or not snapshot.meshes
    if needs_fallback_geometry and snapshot.usd_stage_path:
        fallback_usd = resolve_repo_path(root, snapshot.usd_stage_path)
        if fallback_usd.exists():
            fallback_ir = UsdSceneLoader(usd_path=str(fallback_usd)).load()

    return MitsubaSceneBuilder(width=width, height=height, spp=spp).build_snapshot(
        snapshot,
        repo_root=root,
        fallback_ir=fallback_ir,
        render_mode=render_mode,
    )
