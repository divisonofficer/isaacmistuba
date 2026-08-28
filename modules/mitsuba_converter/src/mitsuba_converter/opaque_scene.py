"""Assemble an opaque spatial-PBR scene from a compiled OpticalNav XML.

The compiled scene contains BSDFs extracted from each source GLB.  Re-baking an
Infinigen unit therefore is not sufficient by itself: the shape references in
``render_scene.xml`` must be redirected to the authoritative baked atlas.  This
module performs that redirect without changing geometry, transforms, cameras,
or emitters.
"""
from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


def _bitmap(parent: ET.Element, name: str, path: str | Path, *, raw: bool) -> None:
    texture = ET.SubElement(parent, "texture", {"type": "bitmap", "name": name})
    ET.SubElement(
        texture,
        "string",
        {"name": "filename", "value": str(Path(path).resolve())},
    )
    if raw:
        ET.SubElement(texture, "boolean", {"name": "raw", "value": "true"})


def _opaque_spatial_bsdf(
    *, object_id: str, outputs: Mapping[str, Any]
) -> tuple[ET.Element, str]:
    """Build a top-level opaque normal-mapped dielectric/conductor blend."""
    required = ("base_color", "alpha", "bsdf_weight", "eta_exr", "k_exr")
    missing = [name for name in required if not outputs.get(name)]
    if missing:
        raise ValueError(f"{object_id}: spatial-PBR outputs missing {', '.join(missing)}")

    digest = hashlib.sha256(object_id.encode("utf-8")).hexdigest()[:12]
    bsdf_id = f"opaque_spatial_{digest}"
    outer = ET.Element("bsdf", {"type": "twosided", "id": bsdf_id})
    parent = outer
    if outputs.get("normal"):
        normal = ET.SubElement(parent, "bsdf", {"type": "normalmap"})
        _bitmap(normal, "normalmap", outputs["normal"], raw=True)
        parent = normal

    blend = ET.SubElement(parent, "bsdf", {"type": "blendbsdf"})
    _bitmap(blend, "weight", outputs["bsdf_weight"], raw=True)

    plastic = ET.SubElement(blend, "bsdf", {"type": "pplastic"})
    ET.SubElement(plastic, "float", {"name": "int_ior", "value": "1.5"})
    _bitmap(plastic, "diffuse_reflectance", outputs["base_color"], raw=False)
    _bitmap(plastic, "alpha", outputs["alpha"], raw=True)

    conductor = ET.SubElement(blend, "bsdf", {"type": "roughconductor"})
    # EXR is linear. Omitting raw here permits RGB-to-spectrum upsampling in
    # the polarized spectral variants used by the dataset renderer.
    _bitmap(conductor, "eta", outputs["eta_exr"], raw=False)
    _bitmap(conductor, "k", outputs["k_exr"], raw=False)
    _bitmap(conductor, "alpha", outputs["alpha"], raw=True)
    return outer, bsdf_id


def load_spatial_records(root: Path) -> dict[str, dict[str, Any]]:
    """Load object records produced by ``convert_spatial_pbr_textures``."""
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(root).glob("*/*_spatial_pbr.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        object_id = str(record.get("object_id") or "")
        if not object_id:
            raise ValueError(f"spatial-PBR record has no object_id: {path}")
        if object_id in records:
            raise ValueError(f"duplicate spatial-PBR record for {object_id}")
        record.setdefault("record_path", str(path.resolve()))
        records[object_id] = record
    return records


def assemble_opaque_scene(
    *,
    source_xml: Path,
    xml_scene_index: Path,
    applied_substitutions: Path,
    spatial_records: Mapping[str, Mapping[str, Any]],
    output_xml: Path,
    object_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Redirect selected units' shapes to opaque atlas BSDFs.

    With ``object_ids=None`` only active semantic substitutions are assembled.
    Passing the full manifest/index intersection produces a self-contained
    all-opaque scene with no dependency on GLB-extracted material BSDFs.
    """
    source_xml = Path(source_xml).resolve()
    index = json.loads(Path(xml_scene_index).read_text(encoding="utf-8"))
    applied = json.loads(Path(applied_substitutions).read_text(encoding="utf-8"))
    substitution_units = sorted(
        {
            str(row["unit_id"])
            for row in applied.get("substitutions") or []
            if row.get("applied")
        }
    )
    if not substitution_units:
        raise ValueError("no active opaque substitutions")
    selected_units = sorted(set(object_ids if object_ids is not None else substitution_units))
    if not selected_units:
        raise ValueError("no units selected for opaque assembly")

    indexed_shapes: dict[str, list[dict[str, Any]]] = {}
    for row in index.get("shapes") or []:
        object_id = str(row.get("object_id") or "")
        if object_id:
            indexed_shapes.setdefault(object_id, []).append(row)

    tree = ET.parse(source_xml)
    root = tree.getroot()
    xml_shapes = {str(shape.get("id")): shape for shape in root.findall("./shape")}
    missing_records = [unit for unit in selected_units if unit not in spatial_records]
    missing_index = [unit for unit in selected_units if not indexed_shapes.get(unit)]
    if missing_records or missing_index:
        raise ValueError(
            "opaque scene inputs incomplete: "
            f"missing_records={missing_records}, missing_index={missing_index}"
        )

    replacements: list[dict[str, Any]] = []
    new_bsdfs: list[ET.Element] = []
    for object_id in selected_units:
        record = spatial_records[object_id]
        bsdf, bsdf_id = _opaque_spatial_bsdf(
            object_id=object_id, outputs=dict(record.get("outputs") or {})
        )
        new_bsdfs.append(bsdf)
        changed: list[dict[str, Any]] = []
        for indexed in indexed_shapes[object_id]:
            shape_id = str(indexed.get("shape_id") or "")
            shape = xml_shapes.get(shape_id)
            if shape is None:
                raise ValueError(f"indexed shape absent from XML: {shape_id}")
            refs = shape.findall("./ref")
            old_refs = [str(ref.get("id") or "") for ref in refs]
            for child in list(shape):
                if child.tag in {"ref", "bsdf"}:
                    shape.remove(child)
            ET.SubElement(shape, "ref", {"id": bsdf_id})
            changed.append({"shape_id": shape_id, "old_bsdf_refs": old_refs})
        replacements.append(
            {
                "object_id": object_id,
                "bsdf_id": bsdf_id,
                "shape_count": len(changed),
                "shapes": changed,
                "spatial_record": str(record.get("record_path") or ""),
            }
        )

    # Top-level BSDF order is immaterial, but placing generated nodes before
    # shapes keeps the resulting XML easy to inspect and diff.
    insertion = next(
        (idx for idx, child in enumerate(list(root)) if child.tag == "shape"),
        len(root),
    )
    for offset, bsdf in enumerate(new_bsdfs):
        root.insert(insertion + offset, bsdf)

    # Mitsuba instantiates top-level plugins even when no shape references them.
    # Remove superseded GLB/measured/glass BSDFs so unavailable source datasets
    # cannot break loading of the otherwise self-contained opaque scene. Follow
    # nested refs transitively in case a retained top-level BSDF is composite.
    top_bsdfs = {str(node.get("id")): node for node in root.findall("./bsdf") if node.get("id")}
    retained = {
        str(ref.get("id"))
        for shape in root.findall("./shape")
        for ref in shape.findall(".//ref")
        if ref.get("id")
    }
    pending = list(retained)
    while pending:
        bsdf_id = pending.pop()
        node = top_bsdfs.get(bsdf_id)
        if node is None:
            continue
        for ref in node.findall(".//ref"):
            dependency = str(ref.get("id") or "")
            if dependency and dependency not in retained:
                retained.add(dependency)
                pending.append(dependency)
    pruned_bsdf_ids: list[str] = []
    for bsdf_id, node in top_bsdfs.items():
        if bsdf_id not in retained:
            root.remove(node)
            pruned_bsdf_ids.append(bsdf_id)

    output_xml = Path(output_xml)
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output_xml, encoding="utf-8", xml_declaration=True)

    report = {
        "schema": "robomituba.opaque_scene_assembly.v1",
        "source_xml": str(source_xml),
        "output_xml": str(output_xml.resolve()),
        "assembled_unit_count": len(selected_units),
        "active_substitution_unit_count": len(substitution_units),
        "replaced_shape_count": sum(row["shape_count"] for row in replacements),
        "pruned_superseded_bsdf_count": len(pruned_bsdf_ids),
        "retained_original_bsdf_count": sum(
            not bsdf_id.startswith("opaque_spatial_") for bsdf_id in retained
        ),
        "opaque_model": "twosided(normalmap(blendbsdf(pplastic,roughconductor)))",
        "metallic_weight": "continuous baked metallic atlas",
        "alpha": "baked roughness squared",
        "replacements": replacements,
    }
    return report
