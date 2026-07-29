#!/usr/bin/env python3
"""Convert Infinigen PBR atlases into Robomituba spatial analytic-BSDF maps."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for MODULE_SRC in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(MODULE_SRC) not in sys.path:
        sys.path.insert(0, str(MODULE_SRC))

from mitsuba_converter.spatial_pbr import (  # noqa: E402
    convert_spatial_pbr_textures,
    summarize_records,
)


def _flatten_constants(value: Any) -> list[float]:
    out: list[float] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_flatten_constants(item))
    else:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            pass
    return out


def _constant(channel: dict[str, Any], default: float) -> float:
    values = _flatten_constants(channel.get("value"))
    return float(sum(values) / len(values)) if values else float(default)


def _resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def _unit_inputs(root: Path, unit: dict[str, Any]) -> dict[str, Any]:
    channels = dict(((unit.get("pbr") or {}).get("channels") or {}))

    def texture(name: str, legacy_key: str) -> Path | None:
        channel = dict(channels.get(name) or {})
        if channel.get("mode") == "texture" and channel.get("ref"):
            return _resolve(root, channel["ref"])
        return _resolve(root, unit.get(legacy_key))

    base = texture("base_color", "baked_albedo")
    if base is None or not base.is_file():
        raise FileNotFoundError(f"{unit.get('id')}: no baked base-color atlas")
    rough_channel = dict(channels.get("roughness") or {})
    metal_channel = dict(channels.get("metallic") or {})
    return {
        "base_color_path": base,
        "roughness_path": texture("roughness", "baked_roughness"),
        "metallic_path": texture("metallic", "baked_metallic"),
        "normal_path": texture("normal", "baked_normal"),
        # Blender-baked standalone atlases already contain evaluated values.
        "roughness_factor": 1.0,
        "metallic_factor": 1.0,
        "roughness_constant": _constant(rough_channel, 0.5),
        "metallic_constant": _constant(metal_channel, 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--object-id", action="append", default=[], help="repeatable; defaults to every unit with base color")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ior-dir", type=Path, default=REPO_ROOT / "modules/mitsuba3-optix7/resources/data/ior")
    parser.add_argument("--conductor-threshold", type=float, default=0.5)
    parser.add_argument("--no-exr", action="store_true")
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    units = {str(unit.get("id")): unit for unit in manifest.get("units") or []}
    selected = args.object_id or list(units)
    missing = [object_id for object_id in selected if object_id not in units]
    if missing:
        parser.error(f"object id(s) not found: {', '.join(missing)}")

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for object_id in selected:
        unit = units[object_id]
        try:
            inputs = _unit_inputs(root, unit)
            record = convert_spatial_pbr_textures(
                object_id=object_id,
                output_dir=args.output_dir / object_id,
                ior_dir=args.ior_dir,
                conductor_threshold=args.conductor_threshold,
                write_exr=not args.no_exr,
                provenance={
                    "manifest": str(manifest_path),
                    "scene_id": manifest.get("scene_id") or root.name,
                    "factory": unit.get("factory"),
                    "optical_class": unit.get("optical_class"),
                    "material_slots": unit.get("material_slots"),
                },
                **inputs,
            )
            records.append(record)
            stats = record["stats"]
            print(
                f"{object_id}: metallic={stats['metallic_min']:.3f}..{stats['metallic_max']:.3f} "
                f"conductor={stats['conductor_fraction']:.1%}"
            )
        except Exception as exc:  # noqa: BLE001 - batch converter records per-object failure
            failures.append({"object_id": object_id, "error": str(exc)})
            print(f"FAIL {object_id}: {exc}", file=sys.stderr)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema": "robomituba.spatial_pbr.batch.v1",
        "manifest": str(manifest_path),
        "summary": summarize_records(records),
        "records": [record["record_path"] for record in records],
        "failures": failures,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"converted={len(records)} failed={len(failures)} output={args.output_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
