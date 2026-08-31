#!/usr/bin/env python3
"""Create an immutable lighting/material/orphan-policy A/B child scene."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for path in (ROOT / "modules" / "robomituba_bridge" / "src", ROOT / "modules" / "navigation_dataset" / "src", ROOT / "modules" / "mitsuba_converter" / "src"):
    sys.path.insert(0, str(path))

from navigation_dataset.apartment_quality import (  # noqa: E402
    LIGHTING_PROFILES, ORPHAN_POLICIES, apply_blocker_and_orphan_policy, apply_lighting_profile,
    canonical_digest, traversable_regions,
)
from mitsuba_converter.ir_structural_pbr import build_manifest, load_registry, validate_registry_files  # noqa: E402


def _scene_dir(project: str, scene_id: str) -> Path:
    path = ROOT / "out" / "opticalnav" / project / "scenes" / scene_id
    if not (path / "authoring_map.json").is_file():
        raise SystemExit(f"scene not found: {path}")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_scene_id(value, parent: str, child: str):
    if isinstance(value, str):
        return value.replace(parent, child)
    if isinstance(value, list):
        return [_replace_scene_id(item, parent, child) for item in value]
    if isinstance(value, dict):
        return {key: _replace_scene_id(item, parent, child) for key, item in value.items()}
    return value


def _copy_child(parent_dir: Path, child_dir: Path, parent_id: str, child_id: str) -> None:
    if child_dir.exists():
        raise SystemExit(f"child scene already exists (refusing overwrite): {child_dir}")
    # Parent scene directories may contain multi-GB staged render caches.  A
    # quality child only needs the top-level authoring/annotation sidecars;
    # meshes stay referenced through the immutable import root.  Never clone
    # rendered observations, staging caches, or compiled XML from the parent.
    child_dir.mkdir(parents=True)
    excluded = {"scene_variant.json", "render_scene.xml", "render_scene_perturbed.xml"}
    for source in parent_dir.iterdir():
        if source.is_file() and source.name not in excluded:
            shutil.copy2(source, child_dir / source.name)
    for path in child_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        path.write_text(json.dumps(_replace_scene_id(payload, parent_id, child_id), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-scene-id", required=True)
    parser.add_argument("--child-scene-id", required=True)
    parser.add_argument("--project", default="opticalnav-v0.2")
    parser.add_argument("--lighting-profile", choices=sorted(LIGHTING_PROFILES), default="softbox_hdr")
    parser.add_argument("--texturecan-registry", type=Path, required=True)
    parser.add_argument("--texturecan-root", type=Path, required=True)
    parser.add_argument("--material-seed", type=int, default=0)
    parser.add_argument("--orphan-policy", choices=sorted(ORPHAN_POLICIES), default="support_validate_remove")
    parser.add_argument("--remove-blocker-id", action="append", default=[])
    parser.add_argument("--recompile", action="store_true", help="sync the child authoring map into render_scene.xml")
    args = parser.parse_args()

    parent_dir = _scene_dir(args.project, args.parent_scene_id)
    child_dir = parent_dir.parent / args.child_scene_id
    _copy_child(parent_dir, child_dir, args.parent_scene_id, args.child_scene_id)
    map_path = child_dir / "authoring_map.json"
    authoring_map = json.loads(map_path.read_text(encoding="utf-8"))
    parent_fingerprint = _sha256(parent_dir / "authoring_map.json")
    authoring_map["scene_id"] = args.child_scene_id
    lighting = apply_lighting_profile(authoring_map, args.lighting_profile)
    orphan_audit = apply_blocker_and_orphan_policy(authoring_map, remove_blocker_ids=args.remove_blocker_id,
                                                    orphan_policy=args.orphan_policy)
    authoring_map.setdefault("metadata", {})["apartment_quality_variant"] = {
        "parent_scene_id": args.parent_scene_id, "parent_authoring_map_sha256": parent_fingerprint,
        "lighting_profile": args.lighting_profile, "orphan_policy": args.orphan_policy,
    }
    map_path.write_text(json.dumps(authoring_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    registry_path, registry_root = args.texturecan_registry.resolve(), args.texturecan_root.resolve()
    registry = load_registry(registry_path)
    validate_registry_files(registry, registry_root)
    import_root = ROOT / str((authoring_map.get("metadata") or {}).get("import_root") or "")
    stage1 = import_root / "scene_manifest.json"
    if not stage1.is_file():
        raise SystemExit(f"cannot infer Stage-1 manifest from import_root: {stage1}")
    material = build_manifest(stage1_manifest=json.loads(stage1.read_text()), stage1_path=stage1, registry=registry,
                              registry_path=registry_path, child_scene_id=args.child_scene_id,
                              parent_scene_id=args.parent_scene_id, parent_dataset_fingerprint=parent_fingerprint,
                              material_variant_id="texturecan_structural_extended_v2", material_seed=args.material_seed)
    for binding in material["bindings"]:
        binding["resolved_maps"] = {key: str((registry_root / value).resolve()) for key, value in binding["maps"].items()}
    material_path = child_dir / "structural_rematerialization.json"
    material_path.write_text(json.dumps(material, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cohort = [{"kind": "existing_probe", "observation_id": "probe_1788073605939", "heading": "h0"}]
    cohort += [{"kind": "room_representative", "region_id": room["id"], "bounds": room["bounds"]} for room in traversable_regions(authoring_map)]
    manifest = {"schema": "robomituba.apartment_quality_ab_variant.v1", "scene_id": args.child_scene_id,
                "parent_scene_id": args.parent_scene_id, "source_fingerprint": parent_fingerprint,
                "lighting": lighting, "material": {"manifest_ref": material_path.name, "seed": args.material_seed,
                                                     "registry_digest": material["registry_digest"]},
                "placement_policy": "collision_aware_clutter_v1", "orphan_audit": orphan_audit,
                "probe_cohort": cohort,
                "render_settings": {"seed": 0, "spp": None, "comparison_policy": "fixed_camera_seed_spp"},
                "metrics": {"luminance": None, "clipping": None, "noise": None, "status": "pending_render"}}
    manifest["digest"] = canonical_digest(manifest)
    (child_dir / "apartment_quality_ab_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (child_dir / "scene_variant.json").write_text(json.dumps({"version": "opticalnav-scene-variant-v0.3", "scene_id": args.child_scene_id,
        "parent_scene_id": args.parent_scene_id, "render_sync_mode": "editor_generated_xml",
        "authoring_map_ref": "authoring_map.json", "quality_manifest_ref": "apartment_quality_ab_manifest.json"}, indent=2) + "\n")
    if args.recompile:
        from apps.migrations.patch_scene_ceiling_lights import _recompile  # noqa: E402
        _recompile(child_dir)
    print(f"[quality-variant] child={args.child_scene_id} softboxes={lighting['softbox_count']} "
          f"structural_bindings={len(material['bindings'])} removed_orphans={len(orphan_audit['removed_orphans'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
