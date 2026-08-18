#!/usr/bin/env python3
"""Export a validated inverse-rendering run as a portable Core/OOD bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _copy_optional(source: Path, target: Path) -> str | None:
    if not source.is_file():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_effective_scene(source: Path, target: Path) -> dict:
    """Copy a runnable effective scene and make mesh/texture paths bundle-relative.

    Source references retained in provenance (for example ``source_ref`` GLBs)
    deliberately remain provenance only.  Every filename/path actually consumed
    by the effective XML and its PBR sidecars is copied to ``assets/`` and
    rewritten relative to the effective-scene root.
    """
    shutil.copytree(source, target)
    # Effective XML commonly inherits relative paths from its immutable source
    # scene.  Resolve those against both locations before copying them into the
    # portable bundle.
    domain = json.loads((source / "ir_scene_domain.json").read_text(encoding="utf-8"))
    source_roots = [source]
    source_scene_dir = domain.get("source_scene_dir")
    if isinstance(source_scene_dir, str) and source_scene_dir:
        source_roots.append(Path(source_scene_dir))
    assets = target / "assets"
    cached: dict[Path, str] = {}
    copied_count = 0

    def rewrite(value: object) -> object:
        nonlocal copied_count
        if not isinstance(value, str) or not value:
            return value
        original = Path(value)
        candidates = [original] if original.is_absolute() else [root / original for root in source_roots]
        resolved = next((candidate for candidate in candidates if candidate.is_file()), None)
        if resolved is None:
            return value
        try:
            resolved = resolved.resolve()
        except OSError:
            return value
        if resolved not in cached:
            digest = _sha256(resolved)[:20]
            destination = assets / f"{digest}_{resolved.name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copy2(resolved, destination)
            cached[resolved] = destination.relative_to(target).as_posix()
            copied_count += 1
        return cached[resolved]

    xml_path = target / "render_scene.xml"
    tree = ET.parse(xml_path)
    for string in tree.getroot().findall(".//string"):
        if string.get("name") == "filename":
            string.set("value", str(rewrite(string.get("value"))))
    ET.indent(tree, space="  ")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    # These sidecars can be used independently of the XML to recover meshes or
    # PBR maps. Rewrite only actual render-asset keys, never provenance keys
    # such as source_ref/glb_ref that would balloon a compact training bundle.
    asset_keys = {"path", "mesh_path", "filename"}
    def rewrite_json(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: (rewrite(item) if key in asset_keys else rewrite_json(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [rewrite_json(item) for item in value]
        return value

    for name in ("xml_scene_index.json", "render_scene_material_policy.json", "material_canonical.json", "material_slots.json"):
        path = target / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            _atomic_json(path, rewrite_json(payload))
    return {
        "asset_directory": "assets",
        "copied_asset_count": copied_count,
        "rewritten_render_asset_refs": len(cached),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--scene-dir", type=Path, required=True,
                        help="validated IR effective-scene directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    validation = json.loads((args.dataset / "validation.json").read_text())
    if not validation.get("passed"):
        parser.error("dataset validation did not pass")

    rows = [json.loads(line) for line in (args.dataset / "index.jsonl").read_text().splitlines() if line.strip()]
    frames_dir = args.out / "frames"
    materials_dir = args.out / "materials"
    splits_dir = args.out / "splits"
    for directory in (frames_dir, materials_dir, splits_dir):
        directory.mkdir(parents=True, exist_ok=True)

    effective_source = args.scene_dir.resolve()
    domain_path = effective_source / "ir_scene_domain.json"
    if not domain_path.is_file():
        parser.error("--scene-dir must be an IR effective scene containing ir_scene_domain.json")
    domain = json.loads(domain_path.read_text(encoding="utf-8"))
    effective_target = materials_dir / "ir_effective_scene"
    if effective_target.exists():
        parser.error(f"export target already contains {effective_target}; choose a new --out")
    effective_scene_bundle = _copy_effective_scene(effective_source, effective_target)

    exported = []
    for row in rows:
        frame_id = row["frame_id"]
        target = frames_dir / frame_id
        target.mkdir(parents=True, exist_ok=True)
        copied: dict[Path, Path] = {}
        for group in ("observation_paths", "gt_paths", "mask_paths"):
            rewritten = {}
            for name, value in row[group].items():
                source = Path(value).resolve()
                destination = copied.get(source)
                if destination is None:
                    destination = target / group / name / source.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    copied[source] = destination
                rewritten[name] = str(destination.relative_to(args.out))
            row[group] = rewritten
        legends = Path(row["id_legends_ref"]).resolve()
        legend_target = target / "metadata" / legends.name
        legend_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legends, legend_target)
        row["id_legends_ref"] = str(legend_target.relative_to(args.out))
        row["surface_domain"] = domain["surface_domain"]
        row["effective_scene_digest"] = domain["effective_scene_digest"]
        row["ir_scene_domain_ref"] = str((effective_target / "ir_scene_domain.json").relative_to(args.out))
        row["split"] = "core"
        exported.append(row)

    material_refs = {
        "material_canonical_ref": "material_canonical.json",
        "xml_scene_index_ref": "xml_scene_index.json",
        "render_scene_material_policy_ref": "render_scene_material_policy.json",
    }
    for row in exported:
        for field, filename in material_refs.items():
            row[field] = str((effective_target / filename).relative_to(args.out))
    for row in exported:
        (frames_dir / row["frame_id"] / "frame.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for filename in ("opaque_scene_assembly.json", "viewpoint_graph.json"):
        source = effective_source / filename
        if source.is_file():
            shutil.copy2(source, materials_dir / filename)
    shutil.copy2(args.dataset / "validation.json", args.out / "validation.json")
    contract_refs = {}
    for name, source in (
        ("mitsuba_property", args.dataset / "gt_artifact_contract.json"),
        ("blender_aov", args.dataset / "blender_gt" / "gt_artifact_contract.json"),
    ):
        target = args.out / "contracts" / f"gt_artifact_contract_{name}.json"
        copied = _copy_optional(source, target)
        if copied is not None:
            contract_refs[name] = str(target.relative_to(args.out))
    render_input_audit_ref = None
    input_audit = args.dataset / "render_input_audit.json"
    if input_audit.is_file():
        audit_payload = json.loads(input_audit.read_text(encoding="utf-8"))
        audit_payload["render_scene_ref"] = "materials/ir_effective_scene/render_scene.xml"
        audit_target = args.out / "contracts" / "render_input_audit.json"
        _atomic_json(audit_target, audit_payload)
        render_input_audit_ref = str(audit_target.relative_to(args.out))
    assembly = args.dataset / "ir_dataset_assembly.json"
    if assembly.is_file():
        # The run-local assembly carries absolute producer paths. Rewrite it so
        # the export remains usable after staging/temporary directories vanish.
        assembly_payload = json.loads(assembly.read_text(encoding="utf-8"))
        assembly_payload["effective_scene_ref"] = "materials/ir_effective_scene/ir_scene_domain.json"
        assembly_payload["blender_gt_ref"] = "frames"
        _atomic_json(args.out / "ir_dataset_assembly.json", assembly_payload)

    with (args.out / "index.jsonl").open("w", encoding="utf-8") as handle:
        for row in exported:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    core_ids = [row["frame_id"] for row in exported]
    (splits_dir / "core.json").write_text(json.dumps(core_ids, indent=2), encoding="utf-8")
    (splits_dir / "ood.json").write_text("[]\n", encoding="utf-8")
    manifest = {
        "schema": "robomituba.ir_dataset_bundle.v2", "frame_count": len(exported),
        "surface_domain": domain["surface_domain"],
        "effective_scene_digest": domain["effective_scene_digest"],
        "effective_scene_ref": "materials/ir_effective_scene/ir_scene_domain.json",
        "effective_scene_bundle": effective_scene_bundle,
        "splits": {"core": len(core_ids), "ood": 0},
        "modalities": {"observations": sorted(exported[0]["observation_paths"]) if exported else [],
                       "gt": sorted(exported[0]["gt_paths"]) if exported else [],
                       "masks": sorted(exported[0]["mask_paths"]) if exported else []},
        "validation_ref": "validation.json",
        "gt_artifact_contracts": contract_refs,
        "render_input_audit_ref": render_input_audit_ref,
    }
    (args.out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"exported frames={len(exported)} core={len(core_ids)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
