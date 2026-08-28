"""Opaque Principled material-mix auditing for specular inverse-rendering data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.ir_material_supervision_quality.v2"
PROFILE = "physically_constrained_metal_v1"
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
    strict_v2 = str(contract.get("schema") or "").endswith(".v4")
    high, texture, constant, excluded, routes = [], [], [], [], {}
    families: dict[str, int] = {}
    physical_failures: list[str] = []
    warnings: list[str] = []
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
        metallic_contract = record.get("metallic_contract")
        if isinstance(metallic_contract, dict):
            family = str(metallic_contract.get("family") or "invalid")
            families[family] = families.get(family, 0) + 1
            item["metallic_family"] = family
            item["generator_id"] = metallic_contract.get("generator_id")
            contract_errors = []
            if metallic_contract.get("schema") != "robomituba.metallic_contract.v2":
                contract_errors.append("schema")
            if family not in {"dielectric", "conductor", "coverage_mixed"}:
                contract_errors.append("family")
            if metallic_contract.get("encoding") != "linear_scalar":
                contract_errors.append("encoding")
            if metallic_contract.get("color_space") != "non_color":
                contract_errors.append("color_space")
            if family == "coverage_mixed" and metallic_contract.get("approximation") != "principled_coverage":
                contract_errors.append("approximation")
            if contract_errors:
                physical_failures.append(
                    f"material_{record.get('material_id')}_invalid_metallic_contract:{','.join(contract_errors)}"
                )
        elif strict_v2:
            physical_failures.append(f"material_{record.get('material_id')}_missing_metallic_contract")
        if fallback or surrogate:
            excluded.append({**item, "reason": "fallback" if fallback else "surrogate_or_replacement"})
            continue
        runtime = (record.get("channel_runtime_sources") or {}).get("metallic") or {}
        # Principled v3 records keep the route in ``channel_runtime_sources``
        # and the authored constant payload in ``source_channels``.  Older
        # records used a nested runtime mapping, so accept both forms rather
        # than treating the v3 route string as a mapping and failing the whole
        # pipeline audit.
        if isinstance(runtime, dict):
            value = _scalar(runtime.get("value"))
        else:
            source = (record.get("source_channels") or {}).get("metallic") or {}
            value = _scalar(source.get("value")) if isinstance(source, dict) else None
        if route == "constant":
            constant.append({**item, "value": value})
            # Old datasets remain readable as diagnostic inventory.  The
            # uniform-fractional ban applies to the v4 publication contract
            # and to records that explicitly opt into MetallicContractV2.
            if value is not None and 1e-6 < value < 1.0 - 1e-6 and (strict_v2 or isinstance(metallic_contract, dict)):
                diagnostic = bool((metallic_contract or {}).get("diagnostic_only")) if isinstance(metallic_contract, dict) else False
                if not diagnostic:
                    physical_failures.append(
                        f"material_{record.get('material_id')}_uniform_fractional_metallic"
                    )
            if value is not None and value >= HIGH_METALLIC:
                high.append({**item, "value": value, "source": "constant"})
        elif route == "texture":
            runtime_ref = runtime.get("ref") if isinstance(runtime, dict) else None
            texture.append({**item, "artifact": effective.get("artifact") or runtime_ref})
        else:
            excluded.append({**item, "reason": "unsupported_route"})
    if families.get("coverage_mixed", 0) == 0:
        warnings.append("no_coverage_mixed_material")
    candidate_failure = [] if high or texture else ["no_authored_high_metallic_candidate"]
    failures = candidate_failure + physical_failures
    core = {
        "schema": SCHEMA, "profile": profile, "high_metallic_threshold": HIGH_METALLIC,
        "material_contract_schema": contract.get("schema"), "material_contract_digest": _digest(contract),
        "material_record_count": len(materials), "high_metallic_constant_records": high,
        "high_metallic_constant_count": len(high), "texture_metallic_records": texture,
        "texture_metallic_count": len(texture), "constant_metallic_records": constant,
        "excluded_records": excluded, "excluded_count": len(excluded), "route_counts": routes,
        "metallic_family_counts": families,
        "coverage_mixed_count": families.get("coverage_mixed", 0),
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "warnings": warnings,
        "acceptance_policy": {
            "uniform_fractional": "diagnostic_only",
            "coverage_mixed": "recommended_warning_if_absent",
            "visibility": "Stage-0 exact-pixel supervision gate",
        },
        "note": "Texture values and supervision coverage are evaluated by Stage-0 exact GT; InteriorVerse distribution similarity is diagnostic only.",
    }
    return {**core, "audit_digest": _digest(core)}
