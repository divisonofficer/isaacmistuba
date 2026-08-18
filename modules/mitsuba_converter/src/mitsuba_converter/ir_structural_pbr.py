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
STRUCTURAL_TOKENS = ("wall", "floor", "ceiling", "column", "panel")


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
    for record in records:
        if record.get("license") != "CC0-1.0":
            raise ValueError(f"{record.get('id')}: registry materials must be CC0-1.0")
        maps = record.get("maps") or {}
        if not all(maps.get(key) for key in ("base_color", "roughness", "normal_gl")):
            raise ValueError(f"{record.get('id')}: requires base_color, roughness and OpenGL normal")
        if float((record.get("physical_size_m") or {}).get("width") or 0) <= 0:
            raise ValueError(f"{record.get('id')}: missing physical material size")
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


def is_structural(unit: dict[str, Any]) -> bool:
    text = " ".join(str(unit.get(key) or "").lower() for key in ("id", "blender_name", "semantic_type", "subtype"))
    return any(token in text for token in STRUCTURAL_TOKENS)


def compatible(record: dict[str, Any], unit: dict[str, Any]) -> bool:
    text = " ".join(str(unit.get(key) or "").lower() for key in ("id", "blender_name", "semantic_type", "subtype"))
    classes = set(record.get("semantic_compatibility") or [])
    return not classes or any(token in text for token in classes)


def bindings_for_scene(stage1_manifest: dict[str, Any], registry: dict[str, Any], *, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(int(seed))
    records = list(registry["materials"])
    bindings = []
    for unit in stage1_manifest.get("units") or []:
        if not is_structural(unit):
            continue
        choices = [record for record in records if compatible(record, unit)] or records
        for slot, _material in enumerate(unit.get("material_slots") or unit.get("materials") or [None]):
            record = choices[rng.randrange(len(choices))]
            bindings.append({
                "unit_id": str(unit["id"]), "slot_index": slot, "material_id": record["id"],
                "maps": record["maps"], "map_sha256": record.get("sha256") or {},
                "physical_size_m": record["physical_size_m"],
                "projection": "generated_meter_repeat_v1", "metallic": 0.0,
                "source_url": record.get("source_url"), "license": "CC0-1.0",
            })
    if not bindings:
        raise ValueError("no structural slots matched the Stage-1 scene")
    return bindings


def build_manifest(*, stage1_manifest: dict[str, Any], stage1_path: Path, registry: dict[str, Any],
                   registry_path: Path, child_scene_id: str, parent_scene_id: str, parent_dataset_fingerprint: str | None,
                   material_variant_id: str, material_seed: int) -> dict[str, Any]:
    bindings = bindings_for_scene(stage1_manifest, registry, seed=material_seed)
    geometry_digest = sha256(stage1_path)
    payload = {
        "schema": MANIFEST_SCHEMA, "compiler_version": "structural-rematerialize-v1",
        "child_scene_id": child_scene_id, "parent_scene_id": parent_scene_id,
        "parent_dataset_fingerprint": parent_dataset_fingerprint,
        "geometry_digest": geometry_digest, "material_variant_id": material_variant_id,
        "material_seed": int(material_seed), "registry_digest": canonical_digest(registry),
        "registry_path": str(registry_path), "bindings": bindings,
    }
    payload["digest"] = canonical_digest(payload)
    return payload
