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


@dataclass
class SemanticContractPolicy:
    """Appearance-contract · per-slot · projected-size LOD budget — the Phase-A
    (manifest-only) rule engine from tools/semantic_lod_budget.py, applied live in
    the bpy export loop (report_2026-07-29_semantic_lod.html: −85% scene polys with
    S0/DoLP parity). Per object: semantic_type → task role, (optical_class, factory)
    → per-slot appearance contract, world size → projected-px tier, then the budget
    rule engine returns a tri-weighted retained ratio. One COLLAPSE ratio is applied
    per object (the per-slot geometry-veto Phase B needs mesh I/O and is not run here).

    The classification tables live in one place (semantic_lod_budget /
    build_semantic_lod_plan) and are imported lazily so this module stays pure and
    the rules keep evolving there, not at this call-site. Any import/eval failure
    degrades to keep-100% (never aborts an import)."""
    name = "semantic_contract"
    min_faces: int = 50_000
    _engine: object = field(default=None, repr=False, compare=False)

    def _load(self):
        if self._engine is None:
            import os, sys
            tools = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo/tools
            if tools not in sys.path:
                sys.path.insert(0, tools)
            from semantic_lod_budget import budget_object
            from build_semantic_lod_plan import SEM_TASK, slot_contract, projected_proxy
            self._engine = (budget_object, SEM_TASK, slot_contract, projected_proxy)
        return self._engine

    def decide(self, ctx: DecimationContext) -> DecimationDecision:
        if ctx.n_faces < self.min_faces:
            return DecimationDecision(False, 1.0, reason=f"n_faces {ctx.n_faces}<{self.min_faces} (keep)",
                                      policy=self.name)
        try:
            budget_object, SEM_TASK, slot_contract, projected_proxy = self._load()
        except Exception as exc:  # noqa: BLE001 - degrade to keep-100%, never abort
            return DecimationDecision(False, 1.0, reason=f"semantic engine import failed: {exc}",
                                      policy=self.name)
        slots = ctx.material_slots or [{"name": "?", "optical_class": ctx.optical_class}]
        task_role = SEM_TASK.get(ctx.semantic_type, "none")
        dims = ([abs(ctx.bbox_max[i] - ctx.bbox_min[i]) for i in range(3)]
                if ctx.bbox_max else None)
        px = projected_proxy(dims)
        slots_meta = []
        for s in slots:
            oc = s.get("optical_class", ctx.optical_class)
            contract, amb = slot_contract(oc, ctx.factory, ctx.semantic_type)
            slots_meta.append({"slot": s.get("name", "?"), "contract": contract,
                               "tri_fraction": round(1.0 / len(slots), 4),
                               "contract_ambiguous": amb})
        b = budget_object(ctx.object_id, f"{ctx.factory}/{ctx.semantic_type}", slots_meta,
                          task_role=task_role, projected_px=px)
        r = float(b.target_fraction)
        detail = ",".join(f"{s.slot.split('.')[0]}:{s.contract}:{s.retained_ratio}" for s in b.slots)
        if r >= 0.999:
            return DecimationDecision(False, 1.0, reason=f"budget r*={r:.2f} role={task_role} [{detail}]"[:160],
                                      policy=self.name)
        return DecimationDecision(True, r, reason=f"r*={r:.3f} role={task_role} [{detail}]"[:160],
                                  policy=self.name)


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
        return SemanticContractPolicy(min_faces=int(kw.get("min_faces", 50_000)))
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
