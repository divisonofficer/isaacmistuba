"""Deterministic CC0 structural-PBR registry and rematerialization manifests.

This module deliberately does not alter Stage-1 assets.  A manifest is a
read-only overlay consumed by the v3 Principled compiler, which means each
rematerialized child has its own provenance/fingerprint while retaining exactly
the approved parent geometry and camera graph.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

REGISTRY_SCHEMA = "robomituba.ir_external_structural_pbr_registry.v1"
MANIFEST_SCHEMA = "robomituba.ir_structural_rematerialization.v1"
INTERIOR_SUBTYPES = frozenset({"wall", "floor", "ceiling", "column", "panel"})
EXCLUDED_TOKENS = frozenset({"exterior", "outside", "door", "window", "glass", "mirror"})

ROLE_TOKENS = {
    "wall": ("wall", "plaster", "stucco", "brick", "concrete"),
    "floor": ("floor", "tile", "granite", "stone", "concrete", "plank", "bamboo"),
    "ceiling": ("plaster", "stucco", "concrete", "wall"),
    "panel": ("plaster", "stucco", "concrete", "wall"),
    "column": ("plaster", "stucco", "concrete", "stone", "brick"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"unsupported external PBR registry: {payload.get('schema')!r}")
    records = payload.get("materials")
    if not isinstance(records, list) or not records:
        raise ValueError("external PBR registry has no materials")
    explicit_roles = payload.get("role_policy") == "explicit_approved_roles_v1"
    for record in records:
        if record.get("license") != "CC0-1.0":
            raise ValueError(f"{record.get('id')}: registry materials must be CC0-1.0")
        maps = record.get("maps") or {}
        if not all(maps.get(key) for key in ("base_color", "roughness", "normal_gl")):
            raise ValueError(f"{record.get('id')}: requires base_color, roughness and OpenGL normal")
        if float((record.get("physical_size_m") or {}).get("width") or 0) <= 0:
            raise ValueError(f"{record.get('id')}: missing physical material size")
        if explicit_roles:
            roles = record.get("approved_roles")
            if not isinstance(roles, list) or not roles or not set(roles) <= INTERIOR_SUBTYPES:
                raise ValueError(f"{record.get('id')}: requires explicit approved structural roles")
            if record.get("normal_convention") != "OpenGL":
                raise ValueError(f"{record.get('id')}: requires OpenGL normal provenance")
            metallic = record.get("metallic") or {}
            mode = metallic.get("mode")
            if mode == "texture":
                key = str(metallic.get("map") or "metallic")
                if not maps.get(key):
                    raise ValueError(f"{record.get('id')}: metallic texture route has no map")
            elif mode == "constant":
                value = metallic.get("value")
                if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
                    raise ValueError(f"{record.get('id')}: invalid metallic constant")
            else:
                raise ValueError(f"{record.get('id')}: requires a metallic texture or constant route")
    return payload


def validate_registry_files(registry: dict[str, Any], root: Path) -> None:
    for record in registry["materials"]:
        for kind, rel in record["maps"].items():
            path = (root / str(rel)).resolve()
            if not path.is_file() or root.resolve() not in path.parents:
                raise FileNotFoundError(f"{record['id']} {kind}: {path}")
            expected = (record.get("sha256") or {}).get(kind)
            if expected and sha256(path) != expected:
                raise ValueError(f"{record['id']} {kind}: SHA-256 mismatch")


def structural_eligibility(unit: dict[str, Any]) -> dict[str, Any]:
    """Conservative, metadata-first policy for interior building skeleton only.

    Material names are deliberately ignored: Infinigen uses e.g. plaster on a
    book spine, and an object-name-only matcher would incorrectly overwrite it.
    A unit must be exporter-classified ``structure``, have an approved interior
    subtype, and belong to a room structural collection. Unknowns are excluded.
    """
    kind = str(unit.get("kind") or "").lower()
    semantic = str(unit.get("semantic_type") or "").lower()
    subtype = str(unit.get("subtype") or "").lower()
    collections = [str(value).lower() for value in (unit.get("collections") or [])]
    text = " ".join((semantic, subtype, *collections))
    if kind != "structure":
        return {"eligible": False, "reason": "not_exporter_structure", "kind": kind}
    if any(token in text for token in EXCLUDED_TOKENS):
        return {"eligible": False, "reason": "excluded_structural_or_opening", "kind": kind}
    if subtype not in INTERIOR_SUBTYPES:
        return {"eligible": False, "reason": "unknown_structural_subtype", "kind": kind}
    room_collection = next((name for name in collections if "room_" in name), None)
    if room_collection is None:
        return {"eligible": False, "reason": "missing_room_structural_membership", "kind": kind}
    expected = f"room_{subtype}"
    if expected not in room_collection and subtype not in {"column", "panel"}:
        return {"eligible": False, "reason": "room_membership_subtype_mismatch", "kind": kind}
    return {"eligible": True, "reason": "interior_structural_slot", "kind": kind,
            "semantic_type": semantic, "subtype": subtype, "room_collection": room_collection}


def is_structural(unit: dict[str, Any]) -> bool:
    """Compatibility boolean for callers; use ``structural_eligibility`` for audit."""
    return bool(structural_eligibility(unit)["eligible"])


def compatible(record: dict[str, Any], unit: dict[str, Any]) -> bool:
    text = " ".join(str(unit.get(key) or "").lower() for key in ("id", "blender_name", "semantic_type", "subtype"))
    classes = set(record.get("semantic_compatibility") or [])
    return not classes or any(token in text for token in classes)


def curated_for_role(record: dict[str, Any], role: str) -> bool:
    """Select explicit human-reviewed roles, preserving legacy registry fallback."""
    approved = record.get("approved_roles")
    if approved is not None:
        return role in {str(value) for value in approved}
    # Existing locked v1 registries did not carry per-record roles.  Retain
    # their deterministic compatibility path; all new TextureCan registries
    # must use the explicit branch above.
    identifier = str(record.get("id") or record.get("asset_id") or "").lower()
    return any(token in identifier for token in ROLE_TOKENS.get(role, ()))


def bindings_for_scene(stage1_manifest: dict[str, Any], registry: dict[str, Any], *, seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(int(seed))
    records = list(registry["materials"])
    bindings, excluded = [], []
    for unit in stage1_manifest.get("units") or []:
        eligibility = structural_eligibility(unit)
        if not eligibility["eligible"]:
            excluded.append({"unit_id": str(unit.get("id") or ""), "blender_name": unit.get("blender_name"),
                             **eligibility})
            continue
        role = str(eligibility["subtype"])
        choices = [record for record in records if compatible(record, unit) and curated_for_role(record, role)]
        if not choices:
            raise ValueError(f"structural registry has no approved material for {role}")
        for slot, _material in enumerate(unit.get("material_slots") or unit.get("materials") or [None]):
            record = choices[rng.randrange(len(choices))]
            metallic = record.get("metallic")
            if not isinstance(metallic, dict):
                metallic = {"mode": "constant", "value": 0.0}
            bindings.append({
                "unit_id": str(unit["id"]), "slot_index": slot, "material_id": record["id"],
                "maps": record["maps"], "map_sha256": record.get("sha256") or {},
                "physical_size_m": record["physical_size_m"],
                "role": role, "projection": str(record.get("projection") or "object_meter_repeat_v2"),
                "metallic": dict(metallic), "approved_roles": list(record.get("approved_roles") or []),
                "source_url": record.get("source_url"), "license": "CC0-1.0",
                "eligibility": eligibility,
            })
    if not bindings:
        raise ValueError("no structural slots matched the Stage-1 scene")
    return bindings, excluded


def build_manifest(*, stage1_manifest: dict[str, Any], stage1_path: Path, registry: dict[str, Any],
                   registry_path: Path, child_scene_id: str, parent_scene_id: str, parent_dataset_fingerprint: str | None,
                   material_variant_id: str, material_seed: int) -> dict[str, Any]:
    bindings, excluded = bindings_for_scene(stage1_manifest, registry, seed=material_seed)
    geometry_digest = sha256(stage1_path)
    payload = {
        "schema": MANIFEST_SCHEMA, "compiler_version": "structural-rematerialize-v3-explicit-role-aware",
        "child_scene_id": child_scene_id, "parent_scene_id": parent_scene_id,
        "parent_dataset_fingerprint": parent_dataset_fingerprint,
        "geometry_digest": geometry_digest, "material_variant_id": material_variant_id,
        "material_seed": int(material_seed), "registry_digest": canonical_digest(registry),
        "registry_path": str(registry_path), "bindings": bindings,
        "selection": {
            "policy": ("interior_structure_only_v3_explicit_roles"
                       if registry.get("role_policy") == "explicit_approved_roles_v1"
                       else "interior_structure_only_v2_role_curated"),
            "eligible_unit_count": len({row["unit_id"] for row in bindings}),
            "eligible_slot_count": len(bindings),
            "excluded_unit_count": len(excluded),
            "excluded_units": excluded,
        },
    }
    payload["digest"] = canonical_digest(payload)
    return payload
