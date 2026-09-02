"""Physically-motivated continuous Disney metallic for the IR dataset.

Infinigen's authored metalness is effectively a binary mask: measured over
56 M dataset pixels, 96.4 % sit at 0 or 1 and the 3.6 % between them is mostly
coverage-texture antialiasing rather than genuine intermediate metalness.  A
network trained on that target learns to be a metal detector rather than a
continuous metallic estimator.

The physical story used here is a **dielectric coat over a conductor**: paint,
oxide, or clearcoat.  As coat coverage ``c`` rises the effective metalness
falls, the surface roughens, and the base colour migrates toward the coat.
That gives a target which is continuous *and* defensible, rather than an
arbitrary remap.

Four signals drive it, per the dataset design:

``a`` binary conductor prior
    The authored family is trusted: a slot Stage-2 calls ``conductor`` really is
    a conductor, and a ``dielectric`` slot is never promoted into metal.
``b`` roughness correlation
    A heavier coat is rougher, so metalness and roughness are anti-correlated.
``c`` semantic composition class
    A faucet, an appliance shell and a painted chair leg coat very differently.
``d`` albedo
    A saturated, dark "metal" is far more likely to be painted than bare.

Critically the roughness term is *correlated with* but never *determined by*
roughness.  A deterministic ``M = f(R)`` would let a network read metalness
straight off the roughness channel, which would invalidate any claim that
active NIR improved metallic estimation.  Two devices prevent that: every
coupling coefficient is a per-material-slot draw, and a spatial residual with
statistics independent of roughness is added on top.  ``correlation_report``
measures both properties so the guarantee is testable rather than asserted.

This module is renderer-independent and importable from the repository-bundled
Blender Python.  The Blender node graph in Stage-2 preparation mirrors
``metallic_field`` exactly; this is the reference the tests exercise.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Mapping, Sequence

import numpy as np

POLICY_SCHEMA = "robomituba.ir_metallic_composition_policy.v1"
POLICY_ID = "metallic_composition_v1"
NODE_GRAPH_VERSION = "metallic_aug_nodes_v1"
COMPOSITION_RULE_VERSION = "composition-token-v1"

#: Families the Stage-2 MetallicContractV2 can report, and how this model reads
#: them.  Only conductor-bearing slots are ever augmented; a dielectric stays a
#: dielectric so a painted wall can never be relabelled as metal.
CONDUCTOR_FAMILIES = frozenset({"conductor", "coverage_mixed"})

COMPOSITION_CLASSES = (
    "metal_hardware",     # faucets, handles, hinges, rails -- bare or lightly coated
    "cookware",           # pans, pots -- brushed, low coat
    "metal_tool",         # cutlery -- polished, very low coat
    "appliance_shell",    # painted/enamelled appliance bodies -- heavy coat
    "structural_metal",   # frames, legs, columns -- painted
    "decor_metal",        # ornaments -- oxidised, mid coat
    "generic_metal",      # conductor with no better evidence
    "dielectric",         # never augmented
)

#: Token -> composition class.  Extends the taxonomy already used by
#: ``ir_prop_pbr._class_hint`` rather than introducing a second vocabulary.
_CLASS_TOKENS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("knife", "fork", "spoon", "cutlery"), "metal_tool"),
    (("pan", "pot", "skillet", "kettle", "cookware"), "cookware"),
    (("faucet", "tap", "handle", "hinge", "knob", "rail", "hardware", "bolt", "screw"), "metal_hardware"),
    (("fridge", "refrigerator", "oven", "microwave", "dishwasher", "washer",
      "appliance", "monitor", "tv", "lamp"), "appliance_shell"),
    (("frame", "leg", "column", "beam", "post", "shelf", "bracket"), "structural_metal"),
    (("ornament", "sculpture", "vase", "candle", "decor", "mirror_frame"), "decor_metal"),
)


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def composition_class(
    *, unit: Mapping[str, Any] | None = None, source_material: str = "",
    semantic_class: str = "none", source_family: str = "dielectric",
) -> dict[str, Any]:
    """Classify how a conductor slot is most plausibly finished.

    Returns the class plus the tokens that produced it, so the decision is
    auditable from the artifact contract rather than being an opaque guess.
    """
    if str(source_family) not in CONDUCTOR_FAMILIES:
        return {"class": "dielectric", "evidence": [], "rule_version": COMPOSITION_RULE_VERSION}
    unit = unit or {}
    text = " ".join(
        str(value or "").lower()
        for value in (
            unit.get("id"), unit.get("blender_name"), unit.get("semantic_type"),
            unit.get("subtype"), unit.get("kind"), unit.get("optical_class"),
            source_material, semantic_class,
        )
    )
    for tokens, label in _CLASS_TOKENS:
        matched = [token for token in tokens if token in text]
        if matched:
            return {"class": label, "evidence": matched, "rule_version": COMPOSITION_RULE_VERSION}
    return {"class": "generic_metal", "evidence": [], "rule_version": COMPOSITION_RULE_VERSION}


def default_policy() -> dict[str, Any]:
    """The built-in coating policy.

    ``coat_centre``/``coat_spread`` set how heavily a class is finished;
    ``roughness_coupling`` and ``albedo_coupling`` are sampled per material slot
    from their ranges so no single global metallic-from-roughness law exists.
    ``metallic_floor`` keeps a trusted conductor from ever reading dielectric.
    """
    return {
        "schema": POLICY_SCHEMA,
        "policy_id": POLICY_ID,
        "node_graph_version": NODE_GRAPH_VERSION,
        "exposed_threshold": 0.7,
        "noise_scale_m": 6.0,
        "classes": {
            "metal_tool":       {"coat_centre": 0.06, "coat_spread": 0.05, "metallic_floor": 0.80},
            "cookware":         {"coat_centre": 0.12, "coat_spread": 0.08, "metallic_floor": 0.70},
            "metal_hardware":   {"coat_centre": 0.15, "coat_spread": 0.10, "metallic_floor": 0.65},
            "generic_metal":    {"coat_centre": 0.22, "coat_spread": 0.12, "metallic_floor": 0.55},
            "decor_metal":      {"coat_centre": 0.32, "coat_spread": 0.15, "metallic_floor": 0.40},
            "structural_metal": {"coat_centre": 0.45, "coat_spread": 0.18, "metallic_floor": 0.25},
            "appliance_shell":  {"coat_centre": 0.55, "coat_spread": 0.18, "metallic_floor": 0.20},
        },
        # Sampled per material slot; the spread across slots is what breaks a
        # global metallic-from-roughness law.  The ranges are calibrated against
        # the measured Infinigen distribution, where metal-bearing roughness is
        # unexpectedly narrow (mean 0.29, std 0.06): a strong roughness coupling
        # there buys almost no correlation while a weak one keeps the residual
        # dominant, so the residual is deliberately the larger term.
        "roughness_coupling_range": [0.04, 0.18],
        "albedo_coupling_range": [0.04, 0.18],
        "noise_coupling_range": [0.25, 0.50],
        "roughness_reference": 0.55,
        "albedo_reference": 0.45,
        "roughness_gain_range": [0.10, 0.35],
    }


def material_seed(
    *, policy_digest: str, scene_id: str, unit_id: str, slot: int,
    source_material: str = "", semantic_class: str = "none",
) -> int:
    """Derive the per-material-slot RNG seed.

    Keyed only on durable identity, never on wall clock, ``bpy`` iteration order
    or a global counter, so the coefficients are reproducible from the dataset
    fingerprint alone.
    """
    key = "|".join((
        POLICY_ID, str(policy_digest), str(scene_id), str(unit_id), str(int(slot)),
        str(source_material), str(semantic_class),
    ))
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def sample_coefficients(
    *, policy: Mapping[str, Any], composition: str, seed: int,
) -> dict[str, float]:
    """Draw this material slot's coupling coefficients."""
    classes = policy.get("classes") or {}
    if composition not in classes:
        composition = "generic_metal"
    spec = classes[composition]
    rng = random.Random(int(seed))

    def _draw(name: str) -> float:
        lo, hi = policy[name]
        return float(lo) + rng.random() * (float(hi) - float(lo))

    centre = float(spec["coat_centre"])
    spread = float(spec["coat_spread"])
    # A per-slot offset of the coat centre, so two slots of the same class do
    # not share one metallic level.
    centre_offset = (rng.random() * 2.0 - 1.0) * spread
    return {
        "composition_class": composition,
        "coat_centre": round(min(0.95, max(0.0, centre + centre_offset)), 6),
        "coat_spread": round(spread, 6),
        "metallic_floor": round(float(spec["metallic_floor"]), 6),
        "roughness_coupling": round(_draw("roughness_coupling_range"), 6),
        "albedo_coupling": round(_draw("albedo_coupling_range"), 6),
        "noise_coupling": round(_draw("noise_coupling_range"), 6),
        "roughness_gain": round(_draw("roughness_gain_range"), 6),
        "roughness_reference": float(policy["roughness_reference"]),
        "albedo_reference": float(policy["albedo_reference"]),
    }


def _as_array(value: Any) -> np.ndarray:
    return np.asarray(value, dtype=np.float32)


def coat_field(
    *, roughness: Any, albedo_luminance: Any, residual: Any, coefficients: Mapping[str, float],
) -> np.ndarray:
    """Coat coverage ``c`` in ``[0, 1]``.

    Rougher and darker/more saturated surfaces read as more heavily coated; the
    residual keeps ``c`` from being a pure function of the other two channels.
    """
    rough = _as_array(roughness)
    lum = _as_array(albedo_luminance)
    noise = _as_array(residual)
    coat = (
        float(coefficients["coat_centre"])
        + float(coefficients["roughness_coupling"]) * (rough - float(coefficients["roughness_reference"]))
        + float(coefficients["albedo_coupling"]) * (float(coefficients["albedo_reference"]) - lum)
        + float(coefficients["noise_coupling"]) * (noise - 0.5)
    )
    return np.clip(coat, 0.0, 1.0).astype(np.float32)


def metallic_field(
    *, source_metallic: Any, roughness: Any, albedo_luminance: Any, residual: Any,
    coefficients: Mapping[str, float], source_family: str,
) -> np.ndarray:
    """Augmented metalness for one material slot.

    ``source_metallic`` is the authored value: a scalar for ``conductor`` and
    the authored coverage texture for ``coverage_mixed``.  Coverage geometry is
    preserved by multiplication, so an authored zero-coverage pixel stays zero
    and the augmentation can only act where metal actually is.
    """
    if str(source_family) not in CONDUCTOR_FAMILIES:
        return np.zeros_like(_as_array(roughness), dtype=np.float32)
    coat = coat_field(roughness=roughness, albedo_luminance=albedo_luminance,
                      residual=residual, coefficients=coefficients)
    metallic = np.clip(1.0 - coat, 0.0, 1.0)
    metallic = np.maximum(metallic, float(coefficients["metallic_floor"]))
    # Authored spatial coverage remains the authority on *where* metal is.
    metallic = metallic * np.clip(_as_array(source_metallic), 0.0, 1.0)
    return metallic.astype(np.float32)


def roughness_field(*, roughness: Any, coat: Any, coefficients: Mapping[str, float]) -> np.ndarray:
    """Roughness raised by the coat, keeping the coupling physically ordered."""
    return np.clip(
        _as_array(roughness) + float(coefficients["roughness_gain"]) * _as_array(coat), 0.0, 1.0,
    ).astype(np.float32)


def correlation_report(
    metallic: Any, roughness: Any, *, bins: int = 8, min_bin_count: int = 32,
) -> dict[str, Any]:
    """Measure that metalness is correlated with, but not determined by, roughness.

    ``pearson`` should sit in a moderate band and ``min_conditional_std`` must
    stay clearly above zero: a deterministic remap would drive the conditional
    spread to zero and let a network recover metalness from roughness alone.
    """
    m = _as_array(metallic).reshape(-1)
    r = _as_array(roughness).reshape(-1)
    keep = np.isfinite(m) & np.isfinite(r)
    m, r = m[keep], r[keep]
    if m.size < 2 or float(m.std()) < 1e-9 or float(r.std()) < 1e-9:
        return {"sample_count": int(m.size), "pearson": None,
                "min_conditional_std": None, "conditional_std": []}
    pearson = float(np.corrcoef(m, r)[0, 1])
    edges = np.linspace(float(r.min()), float(r.max()) + 1e-9, bins + 1)
    conditional = []
    for index in range(bins):
        mask = (r >= edges[index]) & (r < edges[index + 1])
        if int(mask.sum()) < min_bin_count:
            continue
        conditional.append({
            "roughness_lo": round(float(edges[index]), 6),
            "roughness_hi": round(float(edges[index + 1]), 6),
            "count": int(mask.sum()),
            "metallic_std": round(float(m[mask].std()), 6),
            "metallic_mean": round(float(m[mask].mean()), 6),
        })
    return {
        "sample_count": int(m.size),
        "pearson": round(pearson, 6),
        "r_squared": round(pearson * pearson, 6),
        "min_conditional_std": (round(min(row["metallic_std"] for row in conditional), 6)
                                if conditional else None),
        "conditional_std": conditional,
    }


def hash_residual(shape: Sequence[int], *, seed: int) -> np.ndarray:
    """A reproducible ``[0, 1)`` residual field for the pure/offline path.

    Stage-2 preparation uses a Blender noise texture in object space so the
    residual follows the surface; this stand-in only has to be deterministic and
    statistically independent of the other channels.
    """
    return np.asarray(
        np.random.default_rng(int(seed) % (2 ** 63)).random(tuple(int(v) for v in shape)),
        dtype=np.float32,
    )


def luminance(rgb: Any) -> np.ndarray:
    """Rec.709 luminance of a linear RGB albedo."""
    array = _as_array(rgb)
    if array.shape[-1] != 3:
        raise ValueError(f"expected RGB in the last dimension, got {array.shape}")
    return (array @ np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)).astype(np.float32)


def augmentation_record(
    *, policy: Mapping[str, Any], policy_digest: str, coefficients: Mapping[str, float],
    composition: Mapping[str, Any], seed: int, slot_seed: int, source_family: str,
    source_representation: str, semantic_class: str, source_material: str,
) -> dict[str, Any]:
    """The provenance block a ``metallic_contract.v3`` payload must carry."""
    return {
        "policy_id": str(policy.get("policy_id") or POLICY_ID),
        "policy_digest": str(policy_digest),
        "node_graph_version": str(policy.get("node_graph_version") or NODE_GRAPH_VERSION),
        "seed": int(seed),
        "material_seed": int(slot_seed),
        "source_family": str(source_family),
        "source_representation": str(source_representation),
        "semantic_class": str(semantic_class),
        "source_material": str(source_material),
        "composition_class": str(composition.get("class")),
        "composition_evidence": list(composition.get("evidence") or []),
        "composition_rule_version": str(composition.get("rule_version") or COMPOSITION_RULE_VERSION),
        "parameters": {
            **{key: float(value) for key, value in coefficients.items() if not isinstance(value, str)},
            "exposed_threshold": float(policy.get("exposed_threshold", 0.7)),
            "noise_scale_m": float(policy.get("noise_scale_m", 6.0)),
        },
    }


__all__ = [
    "COMPOSITION_CLASSES",
    "COMPOSITION_RULE_VERSION",
    "CONDUCTOR_FAMILIES",
    "NODE_GRAPH_VERSION",
    "POLICY_ID",
    "POLICY_SCHEMA",
    "augmentation_record",
    "coat_field",
    "composition_class",
    "correlation_report",
    "default_policy",
    "hash_residual",
    "luminance",
    "material_seed",
    "metallic_field",
    "roughness_field",
    "sample_coefficients",
    "stable_digest",
]
