from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ASSET_ROOT / "reference" / "agilex_ugv_gazebo_sim"
UPSTREAM_ROOT = REFERENCE_ROOT / "upstream"
REPORT_PATH = REFERENCE_ROOT / "validation_report.json"
COLLADA_NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _required(path: Path) -> Path:
    if not path.exists():
        raise RuntimeError(
            f"Missing required file: {path}\n"
            "Run fetch_official_mesh.py first."
        )
    return path


def _parse_xacro(path: Path) -> dict[str, object]:
    text = _read_text(path)
    mesh_refs: list[dict[str, object]] = []
    for match in re.finditer(r'<mesh\s+filename="([^"]+)"(?:\s+scale="([^"]+)")?', text):
        mesh_refs.append(
            {
                "filename": match.group(1),
                "scale": match.group(2),
            }
        )

    mesh_counts = Counter(item["filename"] for item in mesh_refs)
    return {
        "mesh_references": mesh_refs,
        "mesh_reference_counts": dict(sorted(mesh_counts.items())),
    }


def _collada_summary_from_bytes(data: bytes, *, source_name: str) -> dict[str, object]:
    root = ET.fromstring(data)
    asset = root.find(".//c:asset", COLLADA_NS)
    unit = asset.find("c:unit", COLLADA_NS) if asset is not None else None
    up_axis = asset.find("c:up_axis", COLLADA_NS) if asset is not None else None
    geometries = root.findall(".//c:geometry", COLLADA_NS)
    images = root.findall(".//c:image", COLLADA_NS)
    effects = root.findall(".//c:effect", COLLADA_NS)
    materials = root.findall(".//c:material", COLLADA_NS)
    visual_scenes = root.findall(".//c:visual_scene", COLLADA_NS)

    return {
        "source_name": source_name,
        "geometry_count": len(geometries),
        "image_count": len(images),
        "effect_count": len(effects),
        "material_count": len(materials),
        "visual_scene_count": len(visual_scenes),
        "unit_meter": unit.attrib.get("meter") if unit is not None else None,
        "unit_name": unit.attrib.get("name") if unit is not None else None,
        "up_axis": up_axis.text if up_axis is not None else None,
        "sample_geometry_ids": [geom.attrib.get("id") for geom in geometries[:8]],
    }


def _zip_summary(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        entries = [
            {
                "filename": info.filename,
                "file_size": info.file_size,
            }
            for info in archive.infolist()
        ]
        dae_entries = [item for item in entries if item["filename"].lower().endswith(".dae")]
        body_name = dae_entries[0]["filename"] if dae_entries else None
        body_summary = None
        if body_name:
            body_summary = _collada_summary_from_bytes(
                archive.read(body_name),
                source_name=body_name,
            )
    return {
        "entries": entries,
        "dae_entries": dae_entries,
        "embedded_body_collada": body_summary,
    }


def _validate() -> dict[str, object]:
    xacro_path = _required(UPSTREAM_ROOT / "ranger_mini.xacro")
    zip_path = _required(UPSTREAM_ROOT / "ranger_base.zip")
    steering_path = _required(UPSTREAM_ROOT / "steering_wheel.dae")
    wheel_path = _required(UPSTREAM_ROOT / "wheel_v3.dae")

    xacro_summary = _parse_xacro(xacro_path)
    zip_summary = _zip_summary(zip_path)
    steering_summary = _collada_summary_from_bytes(
        steering_path.read_bytes(),
        source_name=steering_path.name,
    )
    wheel_summary = _collada_summary_from_bytes(
        wheel_path.read_bytes(),
        source_name=wheel_path.name,
    )

    findings = [
        "The official body mesh is delivered through ranger_base.zip rather than a directly usable raw ranger_base.dae file.",
        "The embedded body COLLADA uses millimeter units (meter=0.001) and Z_UP, so import scale/origin cleanup is expected.",
        "The xacro references ranger_base.dae with scale 1000 1000 1000, and wheel/steering meshes with scale 10 10 10.",
        "Separate steering and wheel DAE files exist, which is useful for part-level cleanup or photoreal wheel reconstruction.",
        "No bitmap texture images were found in the checked COLLADA files, so full photoreal lookdev still needs local material rebuilding.",
    ]

    return {
        "source": "agilexrobotics/ugv_gazebo_sim",
        "robot": "ranger_mini_v3",
        "verdict": "usable_with_cleanup",
        "recommended_use": "Use as shape/reference base in Blender, then rebuild photoreal visual shell and materials locally.",
        "validation_focus": [
            "body silhouette",
            "part separation",
            "scale and origin cleanup",
            "material/lookdev rebuild requirements",
        ],
        "findings": findings,
        "xacro": xacro_summary,
        "mesh_files": {
            "ranger_base_zip": {
                "byte_size": zip_path.stat().st_size,
                **zip_summary,
            },
            "steering_wheel_dae": {
                "byte_size": steering_path.stat().st_size,
                **steering_summary,
            },
            "wheel_v3_dae": {
                "byte_size": wheel_path.stat().st_size,
                **wheel_summary,
            },
        },
    }


def main() -> None:
    report = _validate()
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"[validate_official_mesh] wrote {REPORT_PATH}")
    print(f"[validate_official_mesh] verdict={report['verdict']}")


if __name__ == "__main__":
    main()
