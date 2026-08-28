#!/usr/bin/env python3
"""Build the opaque spatial-PBR kitchen scene from Stage A atlases."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    src = REPO_ROOT / "modules" / module / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

from mitsuba_converter.opaque_scene import assemble_opaque_scene, load_spatial_records  # noqa: E402
from mitsuba_converter.spatial_pbr import convert_spatial_pbr_textures  # noqa: E402


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _channel_path(root: Path, unit: dict[str, Any], name: str) -> Path | None:
    channel = dict((((unit.get("pbr") or {}).get("channels") or {}).get(name) or {}))
    if channel.get("mode") == "texture":
        return _resolve(root, channel.get("ref"))
    return None


def _flatten(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        return [item for nested in value for item in _flatten(nested)]
    try:
        return [float(value)]
    except (TypeError, ValueError):
        return []


def _constant(unit: dict[str, Any], name: str, default: float) -> float:
    channel = dict((((unit.get("pbr") or {}).get("channels") or {}).get(name) or {}))
    values = _flatten(channel.get("value"))
    return float(sum(values) / len(values)) if values else float(default)


def _base_color_input(
    *, manifest_root: Path, maps_dir: Path, unit: dict[str, Any], object_id: str
) -> Path:
    texture = _channel_path(manifest_root, unit, "base_color")
    if texture is not None and texture.is_file():
        return texture

    # Preserve spatial roughness/metallic/normal resolution when base color is
    # authoritative but constant. The converter takes base-color dimensions as
    # its output-map dimensions.
    # Mitsuba rejects or warns on one-pixel bitmap distributions. A 2x2
    # constant preserves the value without renderer-side implicit upsampling.
    size = (2, 2)
    for name in ("roughness", "metallic", "normal"):
        candidate = _channel_path(manifest_root, unit, name)
        if candidate is not None and candidate.is_file():
            with Image.open(candidate) as image:
                size = image.size
            break
    channel = dict((((unit.get("pbr") or {}).get("channels") or {}).get("base_color") or {}))
    values = _flatten(channel.get("value"))
    rgb = values[:3] if len(values) >= 3 else [0.6, 0.6, 0.6]
    encoded = tuple(round(max(0.0, min(1.0, value)) * 255) for value in rgb)
    path = maps_dir / object_id / f"{object_id}_constant_basecolor.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, encoded).save(path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-scene-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--ior-dir",
        type=Path,
        default=REPO_ROOT / "modules/mitsuba3-optix7/resources/data/ior",
    )
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument(
        "--scope", choices=("all", "substitutions"), default="all",
        help="all replaces every indexed manifest unit; substitutions replaces only Stage A targets",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest_root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    applied_path = manifest_root / str(
        manifest.get("opaque_substitutions_ref") or "opaque_substitutions_applied.json"
    )
    applied = json.loads(applied_path.read_text(encoding="utf-8"))
    active_units = sorted(
        {str(row["unit_id"]) for row in applied.get("substitutions") or [] if row.get("applied")}
    )
    units = {str(row.get("id")): row for row in manifest.get("units") or []}
    scene_index = json.loads((args.source_scene_dir / "xml_scene_index.json").read_text(encoding="utf-8"))
    indexed_units = {str(row.get("object_id")) for row in scene_index.get("shapes") or [] if row.get("object_id")}
    selected_units = (
        sorted(set(units) & indexed_units) if args.scope == "all" else active_units
    )
    maps_dir = args.output_dir / "spatial_pbr"

    for progress_index, object_id in enumerate(selected_units, 1):
        record_path = maps_dir / object_id / f"{object_id}_spatial_pbr.json"
        if args.reuse_existing and record_path.is_file():
            existing = json.loads(record_path.read_text(encoding="utf-8"))
            if existing.get("size") != [1, 1]:
                print(f"[{progress_index}/{len(selected_units)}] reuse {object_id}")
                continue
        unit = units[object_id]
        base = _base_color_input(
            manifest_root=manifest_root, maps_dir=maps_dir, unit=unit, object_id=object_id
        )
        record = convert_spatial_pbr_textures(
            object_id=object_id,
            output_dir=maps_dir / object_id,
            base_color_path=base,
            roughness_path=_channel_path(manifest_root, unit, "roughness"),
            metallic_path=_channel_path(manifest_root, unit, "metallic"),
            normal_path=_channel_path(manifest_root, unit, "normal"),
            roughness_constant=_constant(unit, "roughness", 0.5),
            metallic_constant=_constant(unit, "metallic", 0.0),
            ior_dir=args.ior_dir,
            write_exr=True,
            provenance={
                "manifest": str(manifest_path),
                "scene_id": manifest.get("scene_id") or manifest_root.name,
                "factory": unit.get("factory"),
                "opaque_replacement_active": True,
            },
        )
        print(
            f"[{progress_index}/{len(selected_units)}] {object_id}: "
            f"metallic={record['stats']['metallic_min']:.3f}..{record['stats']['metallic_max']:.3f}"
        )

    records = load_spatial_records(maps_dir)
    output_xml = args.output_dir / "render_scene.xml"
    report = assemble_opaque_scene(
        source_xml=args.source_scene_dir / "render_scene.xml",
        xml_scene_index=args.source_scene_dir / "xml_scene_index.json",
        applied_substitutions=applied_path,
        spatial_records=records,
        output_xml=output_xml,
        object_ids=selected_units,
    )
    report.update({"manifest": str(manifest_path), "spatial_pbr_dir": str(maps_dir.resolve())})
    report_path = args.output_dir / "opaque_scene_assembly.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Material-pipeline consumers resolve these sidecars relative to the XML.
    # Preserve source metadata while updating each redirected shape's BSDF ref.
    opaque_refs = {
        shape["shape_id"]: row["bsdf_id"]
        for row in report["replacements"]
        for shape in row["shapes"]
    }
    opaque_index = dict(scene_index)
    opaque_index["xml_path"] = str(output_xml.resolve())
    opaque_index["shapes"] = [
        {**row, "bsdf_ref": opaque_refs.get(str(row.get("shape_id")), row.get("bsdf_ref"))}
        for row in scene_index.get("shapes") or []
    ]
    (args.output_dir / "xml_scene_index.json").write_text(
        json.dumps(opaque_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for name in (
        "render_scene_material_policy.json", "material_canonical.json",
        "viewpoint_graph.json", "nav_graph.json", "scene_annotation.json",
    ):
        source = args.source_scene_dir / name
        if source.is_file():
            shutil.copyfile(source, args.output_dir / name)
    shutil.copyfile(applied_path, args.output_dir / "opaque_substitutions_applied.json")
    print(
        f"assembled units={report['assembled_unit_count']} shapes={report['replaced_shape_count']} "
        f"xml={output_xml}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
