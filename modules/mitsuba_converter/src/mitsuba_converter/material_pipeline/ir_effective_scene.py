"""Build immutable, inverse-rendering scene domains.
The OpticalNav source scene remains the authority for authoring and navigation.
This module derives a small, self-contained *effective scene* for a particular
inverse-rendering policy.  The current policy, ``opaque_pbr``, removes only
shape parts whose reachable surface closure contains a dielectric.  It never
rewrites a glass material into an opaque approximation.

Both Mitsuba renderers and the Blender AOV exporter consume the resulting
``ir_scene_domain.json``.  Keeping the exclusion list, retained special-surface
regions, and sidecars together is what prevents RGB/NIR, geometry GT, and
Blender PBR GT from silently observing different geometry.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping

from .bsdf_contract import force_analytic as _force_analytic


IR_SCENE_DOMAIN_SCHEMA = "robomituba.ir_scene_domain.v1"
_MATERIALIZER_VERSION = "ir-effective-scene-v7"
OPAQUE_PBR_DOMAIN = "opaque_pbr"
ALL_SURFACES_DOMAIN = "all"
SPECULAR_MASKED_PBR_DOMAIN = "specular_masked_pbr"
STRUCTURAL_SPECULAR_PBR_DOMAIN = "structural_specular_pbr"
SUPPORTED_SURFACE_DOMAINS = frozenset({
    OPAQUE_PBR_DOMAIN,
    ALL_SURFACES_DOMAIN,
    SPECULAR_MASKED_PBR_DOMAIN,
    STRUCTURAL_SPECULAR_PBR_DOMAIN,
})
_DIELECTRIC_TYPES = frozenset({"dielectric", "roughdielectric", "thindielectric"})
_SPECULAR_SEMANTIC_SCHEMA = "robomituba.specular_semantic_regions.v1"
_SPECULAR_OVERRIDE_SCHEMA = "robomituba.specular_semantic_overrides.v1"
_SPECULAR_OVERRIDE_FILENAME = "specular_semantic_overrides.json"
_SPECULAR_CLASSES = frozenset({"window_glass", "object_glass", "mirror", "none"})
_SIDECARS = (
    "viewpoint_graph.json",
    "nav_graph.json",
    "scene_annotation.json",
    "render_readiness.json",
    "authoring_map.json",
)


def uses_specular_semantic_masks(surface_domain: str) -> bool:
    """Whether a domain publishes first-hit window/glass/mirror masks.

    ``structural_specular_pbr`` removes portable object glass before rendering,
    but keeps the same four-mask artifact contract as the full specular domain.
    In that domain the object-glass mask is intentionally all zero.
    """
    return surface_domain in {
        SPECULAR_MASKED_PBR_DOMAIN,
        STRUCTURAL_SPECULAR_PBR_DOMAIN,
    }


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_digest(paths: Iterable[Path], *, root: Path) -> str:
    digest = hashlib.sha256()
    unique = sorted({path.resolve() for path in paths if path.is_file()}, key=str)
    for path in unique:
        try:
            label = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            label = path.as_posix()
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _candidate_path(value: object, *, base: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    try:
        return path.resolve() if path.is_file() else None
    except OSError:
        return None


def _json_path_values(value: object, *, base: Path) -> Iterable[Path]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"path", "filename", "mesh_path", "source_ref", "glb_ref", "ref"}:
                candidate = _candidate_path(item, base=base)
                if candidate is not None:
                    yield candidate
            yield from _json_path_values(item, base=base)
    elif isinstance(value, list):
        for item in value:
            yield from _json_path_values(item, base=base)


def source_scene_digest(source_scene_dir: Path) -> str:
    """Digest the authoritative scene sidecars and their referenced assets."""
    source_scene_dir = Path(source_scene_dir).resolve()
    names = (
        "render_scene.xml", "xml_scene_index.json", "render_scene_material_policy.json",
        "material_canonical.json", "authoring_map.json", "viewpoint_graph.json",
        _SPECULAR_OVERRIDE_FILENAME,
    )
    required = names[:4]
    missing = [name for name in required if not (source_scene_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"IR effective scene requires source sidecars in {source_scene_dir}: {', '.join(missing)}"
        )
    inputs: list[Path] = [source_scene_dir / name for name in names if (source_scene_dir / name).is_file()]
    root = ET.parse(source_scene_dir / "render_scene.xml").getroot()
    for node in root.findall(".//string[@name='filename']"):
        candidate = _candidate_path(node.get("value"), base=source_scene_dir)
        if candidate is not None:
            inputs.append(candidate)
    for name in ("xml_scene_index.json", "render_scene_material_policy.json", "material_canonical.json"):
        inputs.extend(_json_path_values(_json(source_scene_dir / name), base=source_scene_dir))
    return _stable_digest(inputs, root=source_scene_dir)


def _top_bsdfs(root: ET.Element) -> dict[str, ET.Element]:
    return {
        str(node.get("id")): node
        for node in root.findall("./bsdf")
        if node.get("id")
    }


def _contains_bsdf_type(
    node: ET.Element,
    top_bsdfs: Mapping[str, ET.Element],
    types: frozenset[str],
    seen: set[str] | None = None,
) -> bool:
    seen = set() if seen is None else seen
    if node.tag == "bsdf" and node.get("type") in types:
        return True
    for child in node:
        if child.tag == "bsdf" and _contains_bsdf_type(child, top_bsdfs, types, seen):
            return True
        if child.tag == "ref":
            ref_id = str(child.get("id") or "")
            target = top_bsdfs.get(ref_id)
            if target is not None and ref_id not in seen:
                seen.add(ref_id)
                if _contains_bsdf_type(target, top_bsdfs, types, seen):
                    return True
    return False


def _contains_dielectric(node: ET.Element, top_bsdfs: Mapping[str, ET.Element], seen: set[str] | None = None) -> bool:
    return _contains_bsdf_type(node, top_bsdfs, _DIELECTRIC_TYPES, seen)


def _shape_bsdf_ref(shape: ET.Element, top_bsdfs: Mapping[str, ET.Element]) -> str | None:
    for ref in shape.findall(".//ref"):
        ref_id = str(ref.get("id") or "")
        if ref_id in top_bsdfs:
            return ref_id
    return None


def _shape_mesh_bindings(root: ET.Element) -> dict[str, tuple[str, ...]]:
    """Return exact render-mesh filename bindings by shape id.

    The effective-scene materializer may remove an entire dielectric *shape*,
    but it must never rewrite, simplify, or redirect the mesh of a retained
    shape.  Capturing these bindings makes that invariant auditable without
    parsing any mesh format.
    """
    bindings: dict[str, tuple[str, ...]] = {}
    for shape in root.findall("./shape"):
        shape_id = str(shape.get("id") or "")
        if not shape_id:
            continue
        filenames = tuple(
            str(node.get("value"))
            for node in shape.findall(".//string")
            if node.get("name") == "filename" and node.get("value")
        )
        bindings[shape_id] = filenames
    return bindings


def _binding_digest(bindings: Mapping[str, tuple[str, ...]]) -> str:
    encoded = json.dumps(dict(sorted(bindings.items())), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonicalize_measured_for_ir(
    root: ET.Element,
    *,
    index_by_shape: Mapping[str, Mapping[str, Any]],
    policy_by_shape: Mapping[str, Mapping[str, Any]],
    canonical: Mapping[str, Any],
) -> list[str]:
    """Replace measured leaves with the existing canonical opaque-PBR fallback.

    Measured pBRDF files are optional calibration assets, not IR render
    authority.  In particular, a source scene may point at a wavelength file
    that was not installed locally.  The effective opaque-PBR scene must be
    independently loadable, so it uses the material policy's canonical
    ``pplastic``/``roughconductor`` representation while retaining every GLB
    texture already connected to those analytic materials.
    """
    canonical_by_id = {
        str(row.get("material_id")): row
        for row in canonical.get("materials") or []
        if isinstance(row, Mapping) and row.get("material_id")
    }
    top_bsdfs = _top_bsdfs(root)
    material_ids_by_bsdf: dict[str, set[str]] = {}
    for shape_id, index_row in index_by_shape.items():
        bsdf_id = str(index_row.get("bsdf_ref") or "")
        material_id = str((policy_by_shape.get(shape_id) or {}).get("material_id") or "")
        if bsdf_id and material_id:
            material_ids_by_bsdf.setdefault(bsdf_id, set()).add(material_id)
    converted: list[str] = []
    measured_types = {"measured", "measured_polarized", "measured_polarized_rgb"}
    for bsdf_id, node in top_bsdfs.items():
        if not any(child.get("type") in measured_types for child in node.iter("bsdf")):
            continue
        material_ids = material_ids_by_bsdf.get(bsdf_id) or set()
        if len(material_ids) != 1:
            raise ValueError(
                f"cannot canonicalize measured IR BSDF {bsdf_id}: expected exactly one material policy, "
                f"got {sorted(material_ids)}"
            )
        material_id = next(iter(material_ids))
        canonical_row = canonical_by_id.get(material_id)
        if canonical_row is None:
            raise ValueError(
                f"cannot canonicalize measured IR BSDF {bsdf_id}: canonical material {material_id!r} is missing"
            )
        if node.get("type") in measured_types:
            # force_analytic replaces a child BSDF. A direct top-level measured
            # node has no BSDF parent, so temporarily give it one and then put
            # the canonical child back into the scene at the original position.
            wrapper = ET.Element("bsdf", {"type": "twosided"})
            wrapper.append(ET.fromstring(ET.tostring(node, encoding="unicode")))
            if _force_analytic(wrapper, canonical_row) < 1:
                raise RuntimeError(f"measured IR BSDF {bsdf_id} was not converted to canonical analytic PBR")
            replacement = next((child for child in wrapper if child.tag == "bsdf"), None)
            if replacement is None:
                raise RuntimeError(f"measured IR BSDF {bsdf_id} produced no canonical replacement")
            replacement.set("id", bsdf_id)
            position = list(root).index(node)
            root.remove(node)
            root.insert(position, replacement)
        elif _force_analytic(node, canonical_row) < 1:
            raise RuntimeError(f"measured IR BSDF {bsdf_id} was not converted to canonical analytic PBR")
        converted.append(bsdf_id)
    return sorted(converted)


def _reachable_bsdfs(root: ET.Element, top_bsdfs: Mapping[str, ET.Element]) -> set[str]:
    retained: set[str] = set()
    pending = [
        str(ref.get("id"))
        for shape in root.findall("./shape")
        for ref in shape.findall(".//ref")
        if ref.get("id") in top_bsdfs
    ]
    while pending:
        bsdf_id = pending.pop()
        if bsdf_id in retained:
            continue
        retained.add(bsdf_id)
        node = top_bsdfs.get(bsdf_id)
        if node is None:
            continue
        pending.extend(
            str(ref.get("id"))
            for ref in node.findall(".//ref")
            if ref.get("id") in top_bsdfs and ref.get("id") not in retained
        )
    return retained


def _authoring_objects(authoring: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("id")): row
        for row in authoring.get("objects") or []
        if isinstance(row, Mapping) and row.get("id")
    }


def _validated_semantic_class(value: object, *, label: str) -> str:
    semantic_class = str(value or "").strip()
    if semantic_class not in _SPECULAR_CLASSES:
        raise ValueError(
            f"{label} must be one of {sorted(_SPECULAR_CLASSES)}, got {semantic_class!r}"
        )
    return semantic_class


def _semantic_overrides(source: Path) -> tuple[dict[str, str], dict[str, str], Path | None]:
    """Load optional shape/material-part overrides without silently ignoring typos."""
    path = source / _SPECULAR_OVERRIDE_FILENAME
    if not path.is_file():
        return {}, {}, None
    payload = _json(path)
    schema = payload.get("schema")
    if schema not in {None, _SPECULAR_OVERRIDE_SCHEMA}:
        raise ValueError(f"unsupported specular semantic override schema: {schema!r}")

    def mapping(key: str) -> dict[str, str]:
        value = payload.get(key, {})
        if not isinstance(value, Mapping):
            raise ValueError(f"{path}: {key} must be an object mapping IDs to semantic classes")
        return {
            str(identifier): _validated_semantic_class(semantic_class, label=f"{path}:{key}:{identifier}")
            for identifier, semantic_class in value.items()
        }

    return mapping("shape_classes"), mapping("material_classes"), path


def _semantic_context(
    *, shape_id: str, index_row: Mapping[str, Any], policy_row: Mapping[str, Any], canonical_row: Mapping[str, Any],
) -> str:
    """Stable, auditable names used only for explicit window/mirror signals."""
    values: list[str] = [shape_id]
    for row in (index_row, policy_row, canonical_row):
        for key in (
            "shape_id", "object_id", "material_id", "bsdf_ref", "optical_class", "preset",
            "name", "material_name", "source_material_name", "blender_material", "blender_name",
        ):
            value = row.get(key)
            if isinstance(value, str):
                values.append(value)
    return " ".join(values).casefold()


def _resolve_specular_semantic_regions(
    *,
    source: Path,
    root: ET.Element,
    top_bsdfs: Mapping[str, ET.Element],
    index_by_shape: Mapping[str, Mapping[str, Any]],
    policy_by_shape: Mapping[str, Mapping[str, Any]],
    canonical: Mapping[str, Any],
) -> tuple[dict[str, Any], Path | None]:
    """Resolve retained dielectric/mirror regions at XML shape/material-part granularity.

    A manual override is authoritative.  Automatic window classification only applies
    to dielectric closures; all other dielectric shapes deliberately become
    ``object_glass`` so datasets never have an unlabelled glass surface.
    """
    shape_overrides, material_overrides, override_path = _semantic_overrides(source)
    canonical_by_id = {
        str(row.get("material_id")): row
        for row in canonical.get("materials") or []
        if isinstance(row, Mapping) and row.get("material_id")
    }
    shape_ids = {
        str(shape.get("id")) for shape in root.findall("./shape") if shape.get("id")
    }
    material_ids = {
        str(row.get("material_id"))
        for row in list(index_by_shape.values()) + list(policy_by_shape.values())
        if row.get("material_id")
    } | set(canonical_by_id)
    unknown_shapes = sorted(set(shape_overrides) - shape_ids)
    unknown_materials = sorted(set(material_overrides) - material_ids)
    if unknown_shapes or unknown_materials:
        raise ValueError(
            "specular semantic override references unknown IDs: "
            f"shapes={unknown_shapes[:12]} materials={unknown_materials[:12]}"
        )

    class_shape_ids = {name: [] for name in sorted(_SPECULAR_CLASSES)}
    records: list[dict[str, Any]] = []
    conductor_types = frozenset({"conductor"})
    window_tokens = ("window", "glazing", "glaze")
    for shape in root.findall("./shape"):
        shape_id = str(shape.get("id") or "")
        if not shape_id:
            raise ValueError("render scene contains a shape without an id")
        index_row = index_by_shape.get(shape_id)
        if index_row is None:
            raise ValueError(f"cannot classify special surface {shape_id}: missing xml_scene_index entry")
        policy_row = policy_by_shape.get(shape_id) or {}
        material_id = str(policy_row.get("material_id") or index_row.get("material_id") or "")
        canonical_row = canonical_by_id.get(material_id, {})
        context = _semantic_context(
            shape_id=shape_id, index_row=index_row, policy_row=policy_row, canonical_row=canonical_row,
        )
        glass_candidate = _contains_dielectric(shape, top_bsdfs)
        smooth_conductor_candidate = (
            _contains_bsdf_type(shape, top_bsdfs, conductor_types)
            or str(canonical_row.get("canonical_bsdf") or "") == "conductor"
        )
        mirror_name_candidate = "mirror" in context
        auto_candidates: set[str] = set()
        auto_source = "none"
        if glass_candidate:
            auto_candidates.add("window_glass" if any(token in context for token in window_tokens) else "object_glass")
            auto_source = "auto_dielectric_window_signal" if "window_glass" in auto_candidates else "auto_dielectric_fallback"
        if smooth_conductor_candidate or mirror_name_candidate:
            auto_candidates.add("mirror")
            if not glass_candidate:
                auto_source = "auto_smooth_conductor" if smooth_conductor_candidate else "auto_mirror_name"
        shape_override = shape_overrides.get(shape_id)
        material_override = material_overrides.get(material_id)
        if shape_override is not None and material_override is not None and shape_override != material_override:
            raise ValueError(
                f"conflicting specular semantic overrides for {shape_id}: "
                f"shape={shape_override!r} material={material_override!r}"
            )
        override = shape_override if shape_override is not None else material_override
        if override is not None:
            semantic_class = override
            source_label = "shape_override" if shape_override is not None else "material_override"
        else:
            if len(auto_candidates) > 1:
                raise ValueError(
                    f"ambiguous special-surface classification for {shape_id}: "
                    f"{sorted(auto_candidates)}; add {_SPECULAR_OVERRIDE_FILENAME}"
                )
            semantic_class = next(iter(auto_candidates), "none")
            source_label = auto_source
        class_shape_ids[semantic_class].append(shape_id)
        records.append({
            "shape_id": shape_id,
            "object_id": index_row.get("object_id"),
            "material_id": material_id,
            "bsdf_ref": _shape_bsdf_ref(shape, top_bsdfs),
            "semantic_class": semantic_class,
            "classification_source": source_label,
            "override_applied": override is not None,
            "material_policy_resolved": shape_id in policy_by_shape,
            "candidates": {
                "dielectric": glass_candidate,
                "smooth_conductor": smooth_conductor_candidate,
                "mirror_name": mirror_name_candidate,
                "window_signal": glass_candidate and any(token in context for token in window_tokens),
            },
        })
    for values in class_shape_ids.values():
        values.sort()
    records.sort(key=lambda row: str(row["shape_id"]))
    return {
        "schema": _SPECULAR_SEMANTIC_SCHEMA,
        "mask_semantics": "primary_ray_first_geometric_hit_v1",
        "classes": ["window_glass", "object_glass", "mirror", "glass"],
        "shape_classes": class_shape_ids,
        "glass_shape_ids": sorted(class_shape_ids["window_glass"] + class_shape_ids["object_glass"]),
        "records": records,
        "counts": {name: len(values) for name, values in class_shape_ids.items()},
        "unresolved_shape_count": 0,
        "conflict_shape_count": 0,
        "override_source": _SPECULAR_OVERRIDE_FILENAME if override_path is not None else None,
    }, override_path


def _retain_specular_semantic_regions(
    regions: Mapping[str, Any], retained_shape_ids: set[str], removed_object_glass_shape_ids: set[str],
) -> dict[str, Any]:
    """Filter a source semantic audit to the geometry that remains renderable."""
    source_classes = {
        name: list(values) for name, values in dict(regions["shape_classes"]).items()
    }
    source_counts = {name: len(values) for name, values in source_classes.items()}
    class_map = {
        name: [
            str(shape_id)
            for shape_id in values
            if str(shape_id) in retained_shape_ids
        ]
        for name, values in source_classes.items()
    }
    records = [
        dict(record)
        for record in regions["records"]
        if str(record.get("shape_id")) in retained_shape_ids
    ]
    records.sort(key=lambda row: str(row["shape_id"]))
    result = dict(regions)
    result.update({
        "shape_classes": class_map,
        "records": records,
        "counts": {name: len(values) for name, values in class_map.items()},
        "glass_shape_ids": sorted(class_map["window_glass"] + class_map["object_glass"]),
        "source_shape_classes": source_classes,
        "source_counts": source_counts,
        "removed_object_glass_shape_ids": sorted(removed_object_glass_shape_ids),
    })
    return result

def _copy_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _selector(
    *, shape_id: str, index_row: Mapping[str, Any], policy_row: Mapping[str, Any], authoring: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    object_id = str(index_row.get("object_id") or shape_id)
    authored = authoring.get(object_id) or authoring.get(shape_id)
    metadata = authored.get("metadata") if isinstance(authored, Mapping) else {}
    blender_object = str((metadata or {}).get("blender_name") or "")
    material_id = str(policy_row.get("material_id") or index_row.get("material_id") or "")
    if not isinstance(authored, Mapping) or not blender_object or not material_id:
        raise ValueError(
            f"cannot map excluded shape {shape_id} to Blender face selector "
            f"(object={blender_object!r}, material={material_id!r})"
        )
    return {
        "blender_object": blender_object,
        "blender_material": material_id,
        # A few Infinigen structural objects have no Blender material slots even
        # though Stage 2 classifies their whole GLB part as glass.  Blender can
        # only remove those safely as an explicitly recorded whole-object case.
        "fallback": "whole_object_if_no_material_slots",
    }


def _filtered_canonical(
    canonical: Mapping[str, Any], kept_shape_ids: set[str], *, drop_dielectrics: bool,
) -> dict[str, Any]:
    result = dict(canonical)
    materials: list[dict[str, Any]] = []
    for row in canonical.get("materials") or []:
        if not isinstance(row, Mapping):
            continue
        kept = [str(shape_id) for shape_id in row.get("shape_ids") or [] if str(shape_id) in kept_shape_ids]
        if not kept:
            continue
        copied = dict(row)
        copied["shape_ids"] = kept
        if drop_dielectrics and copied.get("canonical_bsdf") in _DIELECTRIC_TYPES:
            # Emitter geometry may remain in the XML to preserve illumination,
            # but it is never a retained inverse-rendering material surface.
            continue
        materials.append(copied)
    result["materials"] = materials
    return result


def _copy_supporting_sidecars(source: Path, destination: Path) -> None:
    for name in _SIDECARS:
        candidate = source / name
        if candidate.is_file():
            shutil.copy2(candidate, destination / name)


def _atomic_publish(staging: Path, output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    backup = output_dir.parent / f".{output_dir.name}.superseded-{uuid.uuid4().hex}"
    if output_dir.exists():
        os.replace(output_dir, backup)
    try:
        os.replace(staging, output_dir)
    except Exception:
        if backup.exists() and not output_dir.exists():
            os.replace(backup, output_dir)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _existing_matches(
    output_dir: Path, *, source_digest: str, surface_domain: str, geometry_profile: Mapping[str, Any],
) -> dict[str, Any] | None:
    contract_path = output_dir / "ir_scene_domain.json"
    if not contract_path.is_file():
        return None
    try:
        contract = _json(contract_path)
    except Exception:
        return None
    expected_profile = str(geometry_profile.get("profile") or "full")
    expected_geometry_digest = geometry_profile.get("geometry_digest")
    existing_geometry = dict(contract.get("geometry") or {})
    if (contract.get("schema") == IR_SCENE_DOMAIN_SCHEMA
            and contract.get("source_scene_digest") == source_digest
            and contract.get("surface_domain") == surface_domain
            and contract.get("materializer_version") == _MATERIALIZER_VERSION
            and existing_geometry.get("geometry_profile") == expected_profile
            and existing_geometry.get("derived_geometry_digest") == expected_geometry_digest):
        return contract
    return None


def materialize_ir_effective_scene(
    source_scene_dir: Path,
    output_dir: Path,
    *,
    surface_domain: str = STRUCTURAL_SPECULAR_PBR_DOMAIN,
    geometry_profile: Mapping[str, Any] | None = None,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    """Materialize and validate an immutable scene domain.

    ``output_dir`` is generated data, never the source OpticalNav scene.  If an
    existing output has the same source digest and domain it is reused; changed
    scene assets instead produce a replacement directory through staging.
    """
    source = Path(source_scene_dir).resolve()
    output = Path(output_dir).resolve()
    if surface_domain not in SUPPORTED_SURFACE_DOMAINS:
        raise ValueError(f"unsupported IR surface domain: {surface_domain}")
    source_digest = source_scene_digest(source)
    geometry_profile_data = dict(geometry_profile or {})
    if reuse_existing:
        existing = _existing_matches(
            output, source_digest=source_digest, surface_domain=surface_domain, geometry_profile=geometry_profile_data,
        )
        if existing is not None:
            validate_ir_effective_scene(output)
            return existing

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        xml_path = source / "render_scene.xml"
        index = _json(source / "xml_scene_index.json")
        policy = _json(source / "render_scene_material_policy.json")
        canonical = _json(source / "material_canonical.json")
        authoring_path = source / "authoring_map.json"
        authoring = _json(authoring_path) if authoring_path.is_file() else {"objects": []}
        tree = ET.parse(xml_path)
        root = tree.getroot()
        top_bsdfs = _top_bsdfs(root)
        source_mesh_bindings = _shape_mesh_bindings(root)
        index_by_shape = {
            str(row.get("shape_id")): row
            for row in index.get("shapes") or []
            if isinstance(row, Mapping) and row.get("shape_id")
        }
        policy_by_shape = {
            str(row.get("shape_id")): row
            for row in policy.get("shape_policies") or []
            if isinstance(row, Mapping) and row.get("shape_id")
        }
        authored = _authoring_objects(authoring)
        # The IR scene is executable without optional measured-pBRDF files.
        # This happens before dielectric filtering so any shared top-level BSDF
        # remains correctly discoverable by the closure walk below.
        canonicalized_measured_bsdf_ids = (
            _canonicalize_measured_for_ir(
                root, index_by_shape=index_by_shape, policy_by_shape=policy_by_shape, canonical=canonical,
            ) if surface_domain in {OPAQUE_PBR_DOMAIN, SPECULAR_MASKED_PBR_DOMAIN, STRUCTURAL_SPECULAR_PBR_DOMAIN} else []
        )
        top_bsdfs = _top_bsdfs(root)
        excluded: list[dict[str, Any]] = []
        selectors: dict[tuple[str, str], dict[str, str]] = {}
        emitter_preserved = 0

        if surface_domain == OPAQUE_PBR_DOMAIN:
            for shape in list(root.findall("./shape")):
                shape_id = str(shape.get("id") or "")
                if not shape_id:
                    raise ValueError("render scene contains a shape without an id")
                if not _contains_dielectric(shape, top_bsdfs):
                    continue
                if shape.find("emitter") is not None:
                    emitter_preserved += 1
                    continue
                index_row = index_by_shape.get(shape_id)
                policy_row = policy_by_shape.get(shape_id)
                if index_row is None or policy_row is None:
                    raise ValueError(
                        f"cannot exclude dielectric shape {shape_id}: missing "
                        f"{'xml_scene_index' if index_row is None else 'render_scene_material_policy'} entry"
                    )
                selector = _selector(
                    shape_id=shape_id, index_row=index_row, policy_row=policy_row, authoring=authored,
                )
                selectors[(selector["blender_object"], selector["blender_material"])] = selector
                excluded.append({
                    "shape_id": shape_id,
                    "object_id": index_row.get("object_id"),
                    "material_id": policy_row.get("material_id"),
                    "bsdf_ref": _shape_bsdf_ref(shape, top_bsdfs),
                    "blender_face_selector": selector,
                })
                root.remove(shape)

        semantic_regions: dict[str, Any] | None = None
        source_semantic_regions: dict[str, Any] | None = None
        semantic_override_path: Path | None = None
        removed_object_glass_shape_ids: set[str] = set()
        if surface_domain == STRUCTURAL_SPECULAR_PBR_DOMAIN:
            source_semantic_regions, semantic_override_path = _resolve_specular_semantic_regions(
                source=source,
                root=root,
                top_bsdfs=top_bsdfs,
                index_by_shape=index_by_shape,
                policy_by_shape=policy_by_shape,
                canonical=canonical,
            )
            object_glass_ids = set(source_semantic_regions["shape_classes"]["object_glass"])
            for shape in list(root.findall("./shape")):
                shape_id = str(shape.get("id") or "")
                if shape_id not in object_glass_ids:
                    continue
                index_row = index_by_shape.get(shape_id)
                policy_row = policy_by_shape.get(shape_id)
                if index_row is None or policy_row is None:
                    raise ValueError(
                        f"cannot exclude object-glass shape {shape_id}: missing "
                        f"{'xml_scene_index' if index_row is None else 'render_scene_material_policy'} entry"
                    )
                selector = _selector(
                    shape_id=shape_id, index_row=index_row, policy_row=policy_row, authoring=authored,
                )
                selectors[(selector["blender_object"], selector["blender_material"])] = selector
                excluded.append({
                    "shape_id": shape_id,
                    "object_id": index_row.get("object_id"),
                    "material_id": policy_row.get("material_id"),
                    "bsdf_ref": _shape_bsdf_ref(shape, top_bsdfs),
                    "semantic_class": "object_glass",
                    "classification_source": next(
                        (record.get("classification_source") for record in source_semantic_regions["records"]
                         if record.get("shape_id") == shape_id),
                        "unknown",
                    ),
                    "blender_face_selector": selector,
                })
                removed_object_glass_shape_ids.add(shape_id)
                root.remove(shape)
        if surface_domain == SPECULAR_MASKED_PBR_DOMAIN:
            semantic_regions, semantic_override_path = _resolve_specular_semantic_regions(
                source=source,
                root=root,
                top_bsdfs=top_bsdfs,
                index_by_shape=index_by_shape,
                policy_by_shape=policy_by_shape,
                canonical=canonical,
            )

        retained_ids = {str(shape.get("id")) for shape in root.findall("./shape") if shape.get("id")}
        if source_semantic_regions is not None:
            semantic_regions = _retain_specular_semantic_regions(
                source_semantic_regions, retained_ids, removed_object_glass_shape_ids,
            )
        effective_mesh_bindings = _shape_mesh_bindings(root)
        bindings_preserved = all(
            source_mesh_bindings.get(shape_id) == binding
            for shape_id, binding in effective_mesh_bindings.items()
        )
        if not bindings_preserved:
            raise RuntimeError("IR effective scene attempted to change a retained mesh binding")
        reachable = _reachable_bsdfs(root, top_bsdfs)
        pruned_bsdfs: list[str] = []
        for bsdf_id, node in top_bsdfs.items():
            if bsdf_id not in reachable:
                root.remove(node)
                pruned_bsdfs.append(bsdf_id)
        kept_index = [row for row in index.get("shapes") or [] if str(row.get("shape_id")) in retained_ids]
        kept_policy = [row for row in policy.get("shape_policies") or [] if str(row.get("shape_id")) in retained_ids]
        index_out = dict(index)
        index_out["shapes"] = kept_index
        # Keep the content digest independent of the run/output directory.
        # Consumers resolve the XML by the sibling render_scene.xml contract.
        index_out["xml_path"] = "render_scene.xml"
        policy_out = dict(policy)
        policy_out["shape_policies"] = kept_policy
        canonical_out = (
            _filtered_canonical(
                canonical, retained_ids, drop_dielectrics=surface_domain == OPAQUE_PBR_DOMAIN,
            ) if surface_domain in {OPAQUE_PBR_DOMAIN, STRUCTURAL_SPECULAR_PBR_DOMAIN} else dict(canonical)
        )
        canonical_out["ir_surface_domain"] = surface_domain

        ET.indent(tree, space="  ")
        tree.write(staging / "render_scene.xml", encoding="utf-8", xml_declaration=True)
        _copy_json(staging / "xml_scene_index.json", index_out)
        _copy_json(staging / "render_scene_material_policy.json", policy_out)
        _copy_json(staging / "material_canonical.json", canonical_out)
        if semantic_regions is not None:
            _copy_json(staging / "specular_semantic_regions.json", semantic_regions)
        if geometry_profile_data:
            _copy_json(staging / "ir_geometry_profile.json", geometry_profile_data)
        _copy_supporting_sidecars(source, staging)
        if semantic_override_path is not None:
            shutil.copy2(semantic_override_path, staging / _SPECULAR_OVERRIDE_FILENAME)
        for name in ("material_slots.json",):
            candidate = source / name
            if candidate.is_file():
                shutil.copy2(candidate, staging / name)

        digest_inputs = [
            staging / name for name in (
                "render_scene.xml", "xml_scene_index.json", "render_scene_material_policy.json", "material_canonical.json",
            )
        ]
        if semantic_regions is not None:
            digest_inputs.append(staging / "specular_semantic_regions.json")
        if geometry_profile_data:
            digest_inputs.append(staging / "ir_geometry_profile.json")
        if semantic_override_path is not None:
            digest_inputs.append(staging / _SPECULAR_OVERRIDE_FILENAME)
        effective_digest = _stable_digest(digest_inputs, root=staging)

        contract: dict[str, Any] = {
            "schema": IR_SCENE_DOMAIN_SCHEMA,
            "materializer_version": _MATERIALIZER_VERSION,
            "created_at": _utc_now(),
            "surface_domain": surface_domain,
            "source_scene_dir": str(source),
            "source_scene_digest": source_digest,
            "effective_scene_digest": effective_digest,
            "source_render_scene_ref": str(xml_path),
            "render_scene_ref": "render_scene.xml",
            "sidecars": {
                "xml_scene_index_ref": "xml_scene_index.json",
                "geometry_profile_ref": "ir_geometry_profile.json" if geometry_profile_data else None,
                "material_policy_ref": "render_scene_material_policy.json",
                "material_canonical_ref": "material_canonical.json",
            },
            "geometry": {
                "ir_materializer_decimation": (
                    geometry_profile_data.get("profile") if geometry_profile_data.get("profile") == "ir_semantic_lod_v1" else "none"
                ),
                "geometry_profile": geometry_profile_data.get("profile", "full"),
                "derived_geometry_digest": geometry_profile_data.get("geometry_digest"),
                "source_triangles_before_structural_removal": geometry_profile_data.get("geometry", {}).get("source_triangles_before_structural_removal"),
                "triangles_after_lod": geometry_profile_data.get("geometry", {}).get("triangles_after_lod"),
                "removed_object_glass_triangles": geometry_profile_data.get("stage1", {}).get("removed_object_glass_triangles"),
                "common_geometry": bool(geometry_profile_data.get("geometry", {}).get("common_geometry", False)),
                "source_lod_scene_selected": bool(geometry_profile_data),
                "source_lod_scene_available": (source / "render_scene_lod.xml").is_file(),
                "source_render_mesh_binding_digest": _binding_digest(source_mesh_bindings),
                "effective_render_mesh_binding_digest": _binding_digest(effective_mesh_bindings),
                "retained_shape_mesh_binding_count": len(effective_mesh_bindings),
                "all_retained_mesh_bindings_preserved": bindings_preserved,
            },
            "exclusion": {
                "policy": (
                    "remove_shape_part_with_reachable_dielectric" if surface_domain == OPAQUE_PBR_DOMAIN
                    else "retain_all_shape_parts_with_semantic_masks" if surface_domain == SPECULAR_MASKED_PBR_DOMAIN
                    else "remove_object_glass_shape_part_keep_window_and_mirror" if surface_domain == STRUCTURAL_SPECULAR_PBR_DOMAIN
                    else "retain_all_shape_parts"
                ),
                "dielectric_types": sorted(_DIELECTRIC_TYPES),
                "excluded_shape_count": len(excluded),
                "retained_shape_count": len(retained_ids),
                "emitter_shape_preserved_count": emitter_preserved,
                "excluded_shapes": excluded,
                "removed_object_glass_shape_ids": sorted(removed_object_glass_shape_ids),
                "blender_face_selectors": sorted(selectors.values(), key=lambda item: (item["blender_object"], item["blender_material"])),
                "pruned_bsdf_ids": sorted(pruned_bsdfs),
                "canonicalized_measured_bsdf_ids": canonicalized_measured_bsdf_ids,
            },
        }
        if semantic_regions is not None:
            contract["specular_semantics"] = {
                "ref": "specular_semantic_regions.json",
                "mask_semantics": semantic_regions["mask_semantics"],
                "counts": semantic_regions["counts"],
                "source_counts": semantic_regions.get("source_counts", semantic_regions["counts"]),
                "glass_shape_ids": semantic_regions["glass_shape_ids"],
                "removed_object_glass_shape_ids": semantic_regions.get("removed_object_glass_shape_ids", []),
                "override_ref": _SPECULAR_OVERRIDE_FILENAME if semantic_override_path is not None else None,
            }
        _copy_json(staging / "ir_scene_domain.json", contract)
        validate_ir_effective_scene(staging)
        _atomic_publish(staging, output)
        return _json(output / "ir_scene_domain.json")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _validate_specular_semantic_regions(scene_dir: Path, contract: Mapping[str, Any], root: ET.Element) -> None:
    semantic_contract = contract.get("specular_semantics")
    if not isinstance(semantic_contract, Mapping):
        raise ValueError("specular-masked IR scene has no semantic-region contract")
    reference = str(semantic_contract.get("ref") or "")
    if reference != "specular_semantic_regions.json":
        raise ValueError("specular-masked IR scene has an invalid semantic-region reference")
    payload = _json(scene_dir / reference)
    if payload.get("schema") != _SPECULAR_SEMANTIC_SCHEMA:
        raise ValueError("invalid specular semantic-region sidecar schema")
    if payload.get("mask_semantics") != "primary_ray_first_geometric_hit_v1":
        raise ValueError("unsupported specular semantic mask semantics")
    class_map = payload.get("shape_classes")
    records = payload.get("records")
    if not isinstance(class_map, Mapping) or not isinstance(records, list):
        raise ValueError("specular semantic-region sidecar is missing shape classes or records")
    expected_classes = set(_SPECULAR_CLASSES)
    if set(class_map) != expected_classes:
        raise ValueError(f"specular semantic classes differ from contract: {sorted(class_map)}")
    shape_ids = {str(shape.get("id")) for shape in root.findall("./shape") if shape.get("id")}
    assigned: dict[str, str] = {}
    for semantic_class, values in class_map.items():
        if semantic_class not in expected_classes or not isinstance(values, list):
            raise ValueError(f"invalid specular semantic class row: {semantic_class!r}")
        for shape_id in values:
            shape_id = str(shape_id)
            if shape_id not in shape_ids or shape_id in assigned:
                raise ValueError(f"invalid or duplicated semantic shape ID: {shape_id!r}")
            assigned[shape_id] = semantic_class
    if set(assigned) != shape_ids:
        raise ValueError("specular semantic sidecar does not classify every retained shape")
    by_record = {str(row.get("shape_id")): row for row in records if isinstance(row, Mapping) and row.get("shape_id")}
    if set(by_record) != shape_ids:
        raise ValueError("specular semantic records do not cover every retained shape exactly once")
    for shape_id, semantic_class in assigned.items():
        if by_record[shape_id].get("semantic_class") != semantic_class:
            raise ValueError(f"semantic record/class mismatch for {shape_id}")
    glass_ids = sorted(class_map["window_glass"] + class_map["object_glass"])
    if sorted(str(value) for value in payload.get("glass_shape_ids") or []) != glass_ids:
        raise ValueError("glass semantic union differs from window/object glass classes")
    if semantic_contract.get("glass_shape_ids") != glass_ids:
        raise ValueError("IR scene-domain glass semantic summary differs from sidecar")
    counts = {name: len(values) for name, values in class_map.items()}
    if payload.get("counts") != counts or semantic_contract.get("counts") != counts:
        raise ValueError("specular semantic counts differ from shape-class membership")
    if contract.get("surface_domain") == STRUCTURAL_SPECULAR_PBR_DOMAIN:
        source_classes = payload.get("source_shape_classes") or {}
        source_object_glass = {str(value) for value in source_classes.get("object_glass") or []}
        removed = {str(value) for value in payload.get("removed_object_glass_shape_ids") or []}
        retained_object_glass = set(class_map["object_glass"])
        if not removed <= source_object_glass or source_object_glass != removed | retained_object_glass:
            raise ValueError("structural specular object-glass provenance is inconsistent")
        if semantic_contract.get("removed_object_glass_shape_ids") != sorted(removed):
            raise ValueError("IR scene-domain object-glass removal summary differs from sidecar")
        excluded_ids = {str(row.get("shape_id")) for row in (contract.get("exclusion") or {}).get("excluded_shapes") or []}
        if retained_object_glass:
            raise ValueError("structural specular effective scene retained object-glass geometry")
        if not removed <= excluded_ids:
            raise ValueError("structural specular semantic removals lack exclusion records")
    if int(payload.get("unresolved_shape_count", -1)) != 0 or int(payload.get("conflict_shape_count", -1)) != 0:
        raise ValueError("specular semantic sidecar reports unresolved/conflicting shapes")
    override_ref = semantic_contract.get("override_ref")
    if override_ref is not None and not (scene_dir / str(override_ref)).is_file():
        raise ValueError("specular semantic override provenance is missing from effective scene")


def validate_ir_effective_scene(scene_dir: Path) -> dict[str, Any]:
    """Validate structural consistency without importing Mitsuba."""
    scene_dir = Path(scene_dir).resolve()
    contract = _json(scene_dir / "ir_scene_domain.json")
    if contract.get("schema") != IR_SCENE_DOMAIN_SCHEMA:
        raise ValueError(f"unsupported IR effective-scene contract: {scene_dir}")
    surface_domain = str(contract.get("surface_domain") or "")
    if surface_domain not in SUPPORTED_SURFACE_DOMAINS:
        raise ValueError(f"invalid surface domain in {scene_dir}: {surface_domain!r}")
    root = ET.parse(scene_dir / "render_scene.xml").getroot()
    top_bsdfs = _top_bsdfs(root)
    shape_ids = {str(shape.get("id")) for shape in root.findall("./shape") if shape.get("id")}
    index = _json(scene_dir / "xml_scene_index.json")
    policy = _json(scene_dir / "render_scene_material_policy.json")
    index_ids = {str(row.get("shape_id")) for row in index.get("shapes") or [] if row.get("shape_id")}
    policy_ids = {str(row.get("shape_id")) for row in policy.get("shape_policies") or [] if row.get("shape_id")}
    if index_ids != shape_ids or not policy_ids <= shape_ids:
        raise ValueError(
            "effective scene sidecars disagree with XML shapes: "
            f"xml={len(shape_ids)} index={len(index_ids)} policy={len(policy_ids)}"
        )
    dangling_refs = [
        (str(shape.get("id")), str(ref.get("id")))
        for shape in root.findall("./shape")
        for ref in shape.findall("./ref")
        if ref.get("id") not in top_bsdfs
    ]
    if dangling_refs:
        raise ValueError(f"effective scene has dangling shape BSDF refs: {dangling_refs[:12]}")
    geometry = contract.get("geometry") or {}
    decimation = str(geometry.get("ir_materializer_decimation") or "none")
    if decimation not in {"none", "ir_semantic_lod_v1"}:
        raise ValueError(f"unsupported effective-scene geometry profile: {decimation}")
    if decimation != "none":
        if not geometry.get("common_geometry") or not geometry.get("derived_geometry_digest"):
            raise ValueError("IR LOD effective scene lacks common-geometry provenance")
        if geometry.get("source_triangles_before_structural_removal") is None or geometry.get("triangles_after_lod") is None:
            raise ValueError("IR LOD effective scene lacks structural/LOD triangle accounting")
    if not geometry.get("all_retained_mesh_bindings_preserved"):
        raise ValueError("IR effective scene did not preserve retained mesh bindings")
    effective_bindings = _shape_mesh_bindings(root)
    if geometry.get("effective_render_mesh_binding_digest") != _binding_digest(effective_bindings):
        raise ValueError("effective scene mesh bindings differ from the recorded contract")
    if uses_specular_semantic_masks(surface_domain):
        _validate_specular_semantic_regions(scene_dir, contract, root)
    if surface_domain == OPAQUE_PBR_DOMAIN:
        dielectric = [
            str(shape.get("id")) for shape in root.findall("./shape")
            if shape.find("emitter") is None and _contains_dielectric(shape, top_bsdfs)
        ]
        if dielectric:
            raise ValueError(f"opaque PBR effective scene retained dielectric shapes: {dielectric[:12]}")
        canonical = _json(scene_dir / "material_canonical.json")
        bad_materials = [
            str(row.get("material_id")) for row in canonical.get("materials") or []
            if row.get("canonical_bsdf") in _DIELECTRIC_TYPES
        ]
        if bad_materials:
            raise ValueError(f"opaque PBR canonical sidecar retained dielectric materials: {bad_materials[:12]}")
    if surface_domain in {OPAQUE_PBR_DOMAIN, SPECULAR_MASKED_PBR_DOMAIN, STRUCTURAL_SPECULAR_PBR_DOMAIN}:
        measured_leaves = [
            str(node.get("id") or node.get("type")) for node in root.iter("bsdf")
            if node.get("type") in {"measured", "measured_polarized", "measured_polarized_rgb"}
        ]
        if measured_leaves:
            raise ValueError(f"IR effective scene retained measured BSDF leaves: {measured_leaves[:12]}")
    return contract
