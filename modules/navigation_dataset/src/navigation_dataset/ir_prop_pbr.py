"""Small-prop PBR coverage policy and immutable remediation manifests.

The policy intentionally keeps source provenance strict.  A curated opaque
profile can make a prop usable for *training*, but it never turns that pixel
into source-authored ground truth.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from navigation_dataset.ir_principled import normalize_legacy_metallic_scalar


REGISTRY_SCHEMA = "robomituba.ir_prop_pbr_registry.v2"
MANIFEST_SCHEMA = "robomituba.ir_prop_pbr_remediation.v1"
POLICY_ID = "hybrid_prop_pbr_v1"
COMPILER_VERSION = "prop-pbr-remediation-v2-metallic-family"
PROVENANCE_CLASSES = {
    "source_authored": 1,
    "source_rebaked": 2,
    "curated_remediated": 3,
    "fallback": 4,
    "semantic_surrogate": 5,
}
_EXCLUDED = ("glass", "mirror", "window", "door", "water", "liquid")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_registry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"unsupported prop PBR registry: {payload.get('schema')!r}")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("prop PBR registry has no profiles")
    for profile in profiles:
        values = profile.get("values") or {}
        color = values.get("base_color")
        if not isinstance(color, list) or len(color) < 3:
            raise ValueError(f"{profile.get('id')}: base_color must be RGB")
        if not all(0.0 <= float(values.get(name, -1)) <= 1.0 for name in ("roughness", "metallic")):
            raise ValueError(f"{profile.get('id')}: roughness/metallic must be [0,1]")
    return payload


def prop_eligibility(unit: dict[str, Any], source_material: str, semantic_class: str) -> dict[str, Any]:
    """Conservative small-prop matcher based on exported unit metadata.

    Structures and semantic transmissive/surrogate surfaces are deliberately
    excluded even if their material happens to be unresolved.
    """
    kind = str(unit.get("kind") or "").lower()
    text = " ".join(str(x or "").lower() for x in (
        unit.get("id"), unit.get("blender_name"), unit.get("semantic_type"),
        unit.get("subtype"), source_material, semantic_class,
    ))
    if kind == "structure":
        return {"eligible": False, "reason": "structural_unit"}
    if semantic_class in {"window_glass", "mirror"} or any(token in text for token in _EXCLUDED):
        return {"eligible": False, "reason": "transmissive_or_semantic_surrogate"}
    # Stage-1 exporter calls authored movable objects assets/props. Unknown
    # non-structural units are allowed only when they have a material slot.
    if kind and kind not in {"asset", "prop", "object", "furniture", "detail"}:
        return {"eligible": False, "reason": f"unsupported_kind:{kind}"}
    return {"eligible": True, "reason": "eligible_small_prop", "class_hint": _class_hint(text)}


def _class_hint(text: str) -> str:
    for token, label in (("knife", "metal_tool"), ("fork", "metal_tool"), ("spoon", "metal_tool"),
                         ("pan", "metal_tool"), ("pot", "metal_tool"), ("bowl", "dish"),
                         ("cup", "dish"), ("plate", "dish"), ("book", "book"),
                         ("plant", "decor"), ("lamp", "appliance"), ("tv", "appliance")):
        if token in text:
            return label
    return "generic_prop"


def _profile_choices(registry: dict[str, Any], class_hint: str) -> list[dict[str, Any]]:
    exact = [p for p in registry["profiles"] if class_hint in set(p.get("classes") or [])]
    return exact or [p for p in registry["profiles"] if "generic_prop" in set(p.get("classes") or [])] or list(registry["profiles"])


def _uniform_fractional_metallic(channels: dict[str, Any]) -> dict[str, Any] | None:
    """Return a remediation reason for non-physical legacy scalar metalness.

    The Stage-2 MetallicContractV2 intentionally has no ``0 < metallic < 1``
    uniform family.  Such an authored value is still useful evidence, but it
    cannot be carried into a trainable opaque-PBR dataset as source-authored
    GT.  Let the existing deterministic curated-prop policy replace it instead
    of deferring the failure until Blender Stage 2.
    """
    channel = channels.get("metallic") if isinstance(channels, dict) else None
    if not isinstance(channel, dict) or str(channel.get("mode") or "") != "constant":
        return None
    value = channel.get("value")
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        normalized = normalize_legacy_metallic_scalar(float(value))
    except (TypeError, ValueError):
        return None
    return normalized if bool(normalized.get("changed")) else None


def build_manifest(*, stage1_manifest: dict[str, Any], unit_states: dict[str, dict[str, Any]],
                   registry: dict[str, Any], registry_path: Path, child_scene_id: str,
                   parent_scene_id: str, parent_dataset_fingerprint: str | None, seed: int) -> dict[str, Any]:
    """Build deterministic slot-local curated bindings for unresolved props.

    Existing source-valid slots are retained, and listed as source-authored for
    auditability.  We do not claim to rebake an analytic material: it becomes a
    curated binding with its own provenance instead.
    """
    rng = random.Random(int(seed))
    bindings: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for unit in stage1_manifest.get("units") or []:
        state = unit_states.get(str(unit.get("id"))) or {}
        slots = list(unit.get("materials") or [None])
        for slot, source_material in enumerate(slots):
            pbr = (state.get("pbr_by_slot") or unit.get("pbr_by_slot") or {}).get(str(slot), state.get("pbr") or {})
            channels = (pbr.get("channels") or {})
            def has_source(name: str) -> bool:
                source = (channels.get(name) or {}).get("source")
                if source == "not_applicable":
                    return name == "normal"
                return source not in {"missing", "unresolved", "invalid", "error", None}
            fractional_metallic = _uniform_fractional_metallic(channels)
            authored = bool(
                pbr.get("status") == "ok"
                and all(has_source(name) for name in ("base_color", "roughness", "metallic", "normal"))
                and fractional_metallic is None
            )
            semantic = str(unit.get("semantic_class") or "none")
            eligibility = prop_eligibility(unit, str(source_material or ""), semantic)
            row = {"unit_id": str(unit.get("id")), "slot_index": slot,
                   "source_material": source_material, "eligibility": eligibility,
                   "source_pbr_status": pbr.get("status"), "source_channels": channels}
            if fractional_metallic is not None:
                row["remediation_reasons"] = ["uniform_fractional_metallic"]
                row["metallic_normalization"] = fractional_metallic
            if authored:
                row.update({"action": "source_authored", "provenance_class": "source_authored"})
            elif not eligibility["eligible"]:
                row.update({"action": "excluded", "provenance_class": "semantic_surrogate" if semantic in {"window_glass", "mirror"} else "fallback"})
            else:
                choices = _profile_choices(registry, str(eligibility["class_hint"]))
                profile = choices[rng.randrange(len(choices))]
                binding = {
                    **row, "action": "curated_remediated", "provenance_class": "curated_remediated",
                    "profile_id": profile["id"], "profile_digest": canonical_digest(profile),
                    "profile": profile, "assignment_seed": int(seed),
                }
                bindings.append(binding)
                row = binding
            audit.append(row)
    payload = {
        "schema": MANIFEST_SCHEMA, "policy": POLICY_ID, "compiler_version": COMPILER_VERSION,
        "child_scene_id": child_scene_id, "parent_scene_id": parent_scene_id,
        "parent_dataset_fingerprint": parent_dataset_fingerprint, "registry_path": str(registry_path),
        "registry_digest": canonical_digest(registry), "assignment_seed": int(seed),
        "bindings": bindings, "audit": audit,
        "counts": {"curated_remediated": len(bindings), "source_authored": sum(r.get("action") == "source_authored" for r in audit),
                   "excluded": sum(r.get("action") == "excluded" for r in audit)},
    }
    payload["digest"] = canonical_digest(payload)
    return payload
