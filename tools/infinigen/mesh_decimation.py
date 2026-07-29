#!/usr/bin/env python3
"""Abstracted mesh-decimation step for the Infinigen import (Stage 1, bpy).

Runs inside ``blender_export_scene.py``'s per-object loop, BEFORE ``_ensure_uv`` /
``_export_obj`` — so the exported OBJ, the baked texture atlas, and the GLB all
reflect the reduced mesh (no post-hoc render-mesh LOD, no Blender round-trip).

Design intent (the whole point of this file): the *decision* of how much to cut per
object is deliberately isolated behind :class:`DecimationPolicy`. The compression
POLICY is still being decided (see report_2026-07-29_semantic_lod.html); keeping it
here means the rules evolve in ONE place while the bpy executor and the call-site in
``blender_export_scene.py`` stay fixed. Default policy is ``none`` → zero behaviour
change until a policy is explicitly selected.

The policy layer is pure-Python and unit-testable WITHOUT Blender; only
:func:`apply_decimation` touches ``bpy``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


# --------------------------------------------------------------------- types --
@dataclass
class DecimationContext:
    """Everything a policy may look at — filled from the live bpy object + manifest."""
    object_id: str
    n_faces: int
    kind: str = ""                         # furniture / door / structure ...
    semantic_type: str = ""                # landmark / shelf / plant / glass_door ...
    subtype: str = ""
    factory: str = ""                      # NatureShelfTrinketsFactory ...
    optical_class: str = "diffuse"         # diffuse / metal_aluminum / glass / mirror
    material_slots: list = field(default_factory=list)   # [{name, optical_class}]
    bbox_min: tuple = (0.0, 0.0, 0.0)
    bbox_max: tuple = (0.0, 0.0, 0.0)
    has_baked_normal: bool = False         # detail lives in the normal map → safe to cut more

    @property
    def max_dim(self) -> float:
        return max(abs(self.bbox_max[i] - self.bbox_min[i]) for i in range(3)) if self.bbox_max else 0.0


@dataclass
class DecimationDecision:
    decimate: bool
    target_ratio: float = 1.0              # retained triangle fraction in (0, 1]
    method: str = "collapse"               # bpy DECIMATE modifier type
    reason: str = ""
    policy: str = ""


@runtime_checkable
class DecimationPolicy(Protocol):
    name: str
    def decide(self, ctx: DecimationContext) -> DecimationDecision: ...


# --------------------------------------------------------------- policies ---- #
class NoDecimation:
    """Default — never decimate (import behaves exactly as before)."""
    name = "none"

    def decide(self, ctx: DecimationContext) -> DecimationDecision:
        return DecimationDecision(False, 1.0, reason="policy=none", policy=self.name)


@dataclass
class RatioThreshold:
    """Deterministic placeholder: cut every object above ``min_faces`` to a flat
    ``ratio`` (never below ``floor_faces``). Optical interfaces (glass/mirror/metal)
    and structural doors are protected (Fresnel/normal + straight edges matter), so
    they are decimated more gently via ``optical_ratio``. This is a stand-in until
    the semantic-topology budget is wired in — enough to exercise the plumbing."""
    name = "ratio_threshold"
    min_faces: int = 50_000
    ratio: float = 0.30
    optical_ratio: float = 0.60
    floor_faces: int = 2_000
    _PROTECT = {"glass", "mirror", "metal_aluminum"}

    def decide(self, ctx: DecimationContext) -> DecimationDecision:
        if ctx.n_faces < self.min_faces:
            return DecimationDecision(False, 1.0, reason=f"n_faces {ctx.n_faces}<{self.min_faces}", policy=self.name)
        protected = ctx.optical_class in self._PROTECT or ctx.semantic_type in ("glass_door", "glass_wall")
        r = self.optical_ratio if protected else self.ratio
        r = max(r, self.floor_faces / ctx.n_faces)     # never below the absolute floor
        r = min(r, 1.0)
        return DecimationDecision(True, r, reason=f"{ctx.n_faces}→~{int(ctx.n_faces * r)}"
                                  + (" (optical/structural protected)" if protected else ""),
                                  policy=self.name)


class SemanticContractPolicy:
    """PLACEHOLDER for the appearance-contract · per-slot · topology-veto budget
    (tools/semantic_lod_budget.py + report_2026-07-29_semantic_lod.html). Wiring the
    real, human-calibrated rules in here is the intended future evolution of THIS
    module — the call-site never changes. Not the default; raises until decided."""
    name = "semantic_contract"

    def decide(self, ctx: DecimationContext) -> DecimationDecision:  # pragma: no cover
        raise NotImplementedError(
            "semantic_contract decimation policy is not decided yet; "
            "use --decimate-policy=ratio_threshold or none.")


def resolve_policy(name: str, **kw) -> DecimationPolicy:
    """Factory used by blender_export_scene.py's --decimate-policy flag."""
    name = (name or "none").strip().lower()
    if name in ("none", "off", ""):
        return NoDecimation()
    if name == "ratio_threshold":
        return RatioThreshold(
            min_faces=int(kw.get("min_faces", 50_000)),
            ratio=float(kw.get("ratio", 0.30)),
            optical_ratio=float(kw.get("optical_ratio", 0.60)),
            floor_faces=int(kw.get("floor_faces", 2_000)))
    if name == "semantic_contract":
        return SemanticContractPolicy()
    raise ValueError(f"unknown decimation policy: {name!r} (choices: none, ratio_threshold, semantic_contract)")


# --------------------------------------------------------- bpy executor ----- #
def apply_decimation(bpy_obj, decision: DecimationDecision) -> int:
    """Apply the decision to a live bpy mesh via a DECIMATE modifier (COLLAPSE) and
    return the resulting face count. bpy-only — the caller guards on the decision so
    this never runs when decimate=False."""
    if not decision.decimate:
        return len(bpy_obj.data.polygons)
    import bpy  # noqa: F401  (Blender-only)
    mod = bpy_obj.modifiers.new(name="robomituba_decimate", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(1e-4, min(1.0, float(decision.target_ratio)))
    mod.use_collapse_triangulate = True
    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = bpy_obj
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    finally:
        bpy.context.view_layer.objects.active = prev_active
    return len(bpy_obj.data.polygons)


def decimate_object(bpy_obj, policy: DecimationPolicy, ctx: DecimationContext) -> dict:
    """Full step: policy decides, executor applies (if bpy present). Returns a record
    for the manifest unit. Never raises on the bpy path failing — decimation is
    best-effort and must not abort an import."""
    decision = policy.decide(ctx)
    before = ctx.n_faces
    after = before
    error = None
    if decision.decimate:
        try:
            after = apply_decimation(bpy_obj, decision)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    return {"policy": decision.policy, "decimated": bool(decision.decimate and error is None),
            "faces_before": before, "faces_after": after,
            "target_ratio": round(decision.target_ratio, 4), "reason": decision.reason,
            "error": error}
