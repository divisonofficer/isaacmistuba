"""Opaque-PBR normalization — resolve transmissive/mirror material slots to opaque BSDFs.

The inverse-rendering dataset targets a scene fully describable by
``base_color + normal + roughness + metallic``. Glass/mirror are outside that
representation, so (keeping geometry) each glass/mirror material SLOT is replaced by a
semantically-appropriate OPAQUE material chosen by ``configs/datasets/
opaque_substitution_rules.json`` (factory-name token first, then optical_class default).

This module is the pure-Python RESOLVER (no bpy/Mitsuba): it reads the Infinigen
``scene_manifest.json`` + the rules and emits ``opaque_substitutions.json`` — the
authoritative per-``(unit, slot, material)`` substitution record that Stage A (Blender
remap+re-bake), Stage B (scene assembly) and Stage C (replacement_mask) all consume.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

SUBSTITUTIONS_VERSION = "robomituba-opaque-substitutions-v1"

# optical_class -> source render BSDF (what the material is TODAY, for provenance).
_SOURCE_BSDF = {"glass": "dielectric", "mirror": "conductor"}
# architectural keyword -> architectural_rules key (factory/semantic tokens).
_ARCH_KEYWORDS = {
    "window": "window", "windowpane": "window", "glazing": "window",
    "glassdoor": "glass_door", "door": "glass_door",
    "partition": "glass_partition", "divider": "glass_partition",
}


def load_rules(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def _luma(rgb) -> float:
    r, g, b = (list(rgb) + [0, 0, 0])[:3]
    return 0.2126 * float(r) + 0.7152 * float(g) + 0.0722 * float(b)


def _palette_pick(palette: list, key: str) -> list:
    """Deterministic per-object palette choice (sha1 of key — no RNG, resume-safe)."""
    if not palette:
        return [0.8, 0.8, 0.8]
    idx = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % len(palette)
    return list(palette[idx])


def _factory_token(unit: Mapping[str, Any]) -> str:
    fac = unit.get("factory")
    if fac:
        return str(fac).rsplit("/", 1)[-1]
    m = re.match(r"([A-Za-z]+Factory)", str(unit.get("id") or ""))
    return m.group(1) if m else ""


def _arch_key(unit: Mapping[str, Any]) -> Optional[str]:
    hay = " ".join(str(unit.get(k, "")) for k in ("factory", "semantic_type", "subtype", "id")).lower()
    for kw, key in _ARCH_KEYWORDS.items():
        if kw in hay:
            return key
    return None


def _resolve_rule(unit: Mapping[str, Any], optical_class: str, rules: Mapping[str, Any]) -> dict:
    """Pick the substitution rule for a slot: factory > architectural > class default."""
    if optical_class == "mirror":
        return dict(rules.get("default_mirror", {}))
    token = _factory_token(unit)
    fr = rules.get("factory_rules", {})
    if token in fr:
        return dict(fr[token])
    ak = _arch_key(unit)
    if ak and ak in rules.get("architectural_rules", {}):
        return dict(rules["architectural_rules"][ak])
    return dict(rules.get("default_glass", {}))


def _canonical_base_color(rule: Mapping[str, Any], rules: Mapping[str, Any],
                          key: str, source_value: Optional[list]) -> tuple[list, str]:
    """Return (base_color, policy_used) per the rule's base_color_policy."""
    policy = rule.get("base_color_policy", "palette")
    if policy == "constant" and rule.get("base_color") is not None:
        return list(rule["base_color"]), "constant"
    if policy == "keep_original" and source_value is not None:
        thr = float(rules.get("near_white_luma_threshold", 0.85))
        if _luma(source_value) < thr:
            return list(source_value)[:3], "keep_original"
        # near-white glass → fall through to palette so props aren't all white
    palette = rules.get("palettes", {}).get(rule.get("palette", ""), [])
    return _palette_pick(palette, key), "palette"


def resolve_slot(unit: Mapping[str, Any], slot: Mapping[str, Any],
                 rules: Mapping[str, Any]) -> Optional[dict]:
    """Resolve one material slot to an opaque substitution, or None if not a target."""
    oc = slot.get("optical_class")
    if oc not in set(rules.get("target_optical_classes", ["glass", "mirror"])):
        return None
    mat_name = slot.get("name") or slot.get("material")
    unit_id = unit.get("id") or unit.get("mesh_obj")
    rule = _resolve_rule(unit, oc, rules)

    # source base_color (per-unit pbr channel, best available) for keep_original policy
    src_bc = None
    ch = ((unit.get("pbr") or {}).get("channels") or {}).get("base_color") or {}
    if ch.get("mode") == "constant" and ch.get("value"):
        src_bc = list(ch["value"][0]) if isinstance(ch["value"][0], list) else list(ch["value"])

    key = f"{unit_id}:{mat_name}"
    base_color, policy_used = _canonical_base_color(rule, rules, key, src_bc)

    floor = float(rules.get("near_delta_roughness_floor", 0.10))
    rough = float(rule.get("roughness", 0.25))
    near_delta = rough < floor
    rough = max(rough, floor)

    return {
        "unit_id": unit_id,
        "factory": _factory_token(unit),
        "material_name": mat_name,
        "source": {
            "optical_class": oc,
            "bsdf": _SOURCE_BSDF.get(oc, "dielectric"),
        },
        "canonical": {
            "semantic": rule.get("semantic"),
            "bsdf": rule.get("bsdf", "pplastic"),
            "base_color": [round(c, 5) for c in base_color],
            "base_color_policy": policy_used,
            "roughness": round(rough, 4),
            "metallic": float(rule.get("metallic", 0.0)),
            "conductor": rule.get("conductor"),
        },
        "near_delta_floored": near_delta,
        "policy": "replace_transmissive_prop_with_opaque_semantic_equivalent",
        "reason": rule.get("reason", "outside opaque base_color/roughness/metallic domain"),
    }


def build_substitutions(manifest: Mapping[str, Any], rules: Mapping[str, Any]) -> dict:
    """Iterate every unit × material_slot and resolve glass/mirror slots to opaque targets."""
    entries: list[dict] = []
    for unit in manifest.get("units", []):
        for slot in unit.get("material_slots", []):
            sub = resolve_slot(unit, slot, rules)
            if sub is not None:
                entries.append(sub)
    by_factory: dict[str, int] = {}
    by_semantic: dict[str, int] = {}
    for e in entries:
        by_factory[e["factory"]] = by_factory.get(e["factory"], 0) + 1
        by_semantic[e["canonical"]["semantic"]] = by_semantic.get(e["canonical"]["semantic"], 0) + 1
    return {
        "version": SUBSTITUTIONS_VERSION,
        "scene_id": manifest.get("scene_id"),
        "rules_version": rules.get("version"),
        "substitution_count": len(entries),
        "by_factory": by_factory,
        "by_semantic": by_semantic,
        "near_delta_floored": sum(1 for e in entries if e["near_delta_floored"]),
        "substitutions": entries,
    }
