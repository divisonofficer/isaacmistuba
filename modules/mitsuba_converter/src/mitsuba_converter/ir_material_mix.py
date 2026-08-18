"""Opaque Principled material-mix auditing for specular inverse-rendering data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.ir_material_mix_quality.v1"
PROFILE = "specular_inverse_balanced_v1"
HIGH_METALLIC = 0.7


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scalar(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and value:
        try:
            return float(sum(float(item) for item in value) / len(value))
        except (TypeError, ValueError):
            return None
    return None


def audit_material_mix(contract: dict[str, Any], *, profile: str = PROFILE) -> dict[str, Any]:
    """Audit final effective material routes without semantic name heuristics.

    Texture routes are retained as authored/eligible rather than guessed from an
    arbitrary texel sample.  Stage-0 visibility is the authoritative pixel gate.
    """
    materials = list(contract.get("materials") or [])
    high, texture, constant, excluded, routes = [], [], [], [], {}
    for record in materials:
        effective = (record.get("effective_inputs") or {}).get("metallic") or {}
        route = str(effective.get("route") or "missing")
        routes[route] = routes.get(route, 0) + 1
        fallback = "metallic" in set(record.get("fallback_channels") or [])
        replacement = bool(record.get("replacement"))
        surrogate = route.startswith("surrogate") or replacement
        name = str(record.get("prepared_material") or record.get("source_material") or record.get("blender_object") or "unknown")
        item = {"material_id": record.get("material_id"), "object_id": record.get("object_id"),
                "object": record.get("blender_object"), "material": name, "route": route,
                "fallback": fallback, "replacement": replacement}
        if fallback or surrogate:
            excluded.append({**item, "reason": "fallback" if fallback else "surrogate_or_replacement"})
            continue
        runtime = (record.get("channel_runtime_sources") or {}).get("metallic") or {}
        value = _scalar(runtime.get("value"))
        if route == "constant":
            constant.append({**item, "value": value})
            if value is not None and value >= HIGH_METALLIC:
                high.append({**item, "value": value, "source": "constant"})
        elif route == "texture":
            texture.append({**item, "artifact": effective.get("artifact") or runtime.get("ref")})
        else:
            excluded.append({**item, "reason": "unsupported_route"})
    core = {
        "schema": SCHEMA, "profile": profile, "high_metallic_threshold": HIGH_METALLIC,
        "material_contract_schema": contract.get("schema"), "material_contract_digest": _digest(contract),
        "material_record_count": len(materials), "high_metallic_constant_records": high,
        "high_metallic_constant_count": len(high), "texture_metallic_records": texture,
        "texture_metallic_count": len(texture), "constant_metallic_records": constant,
        "excluded_records": excluded, "excluded_count": len(excluded), "route_counts": routes,
        "status": "passed" if high or texture else "failed",
        "failures": [] if high or texture else ["no_authored_high_metallic_candidate"],
        "note": "Texture metallic values are evaluated by Stage-0 pixel visibility QC; no semantic/material-name inference is used.",
    }
    return {**core, "audit_digest": _digest(core)}
