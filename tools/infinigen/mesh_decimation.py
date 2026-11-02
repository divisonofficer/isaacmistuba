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
import re
from typing import Any, Callable, Optional, Protocol, runtime_checkable


def map_material_slot_indices(source_names: list[str | None], imported_names: list[str | None], *,
                              allow_source_subset: bool = False) -> dict[int, int]:
    """Map glTF-imported slots back to the original Blender slot indices.

    Blender appends a new ``.NNN`` suffix when the source materials are still
    loaded.  Repeated variants such as ``hair``, ``hair.001`` ... therefore
    return as ``hair.005`` ... and cannot be matched by stem alone.  The OBJ →
    gltfpack → glTF path preserves primitive/material order, so an equal-length
    equal-stem sequence is an unambiguous cosmetic renumbering.
    """
    if len(source_names) != len(imported_names) and not allow_source_subset:
        raise ValueError("material slot count changed")
    if len(imported_names) > len(source_names):
        raise ValueError("material slot count increased")
    source_by_name: dict[str, list[int]] = {}
    for index, name in enumerate(source_names):
        if name is not None:
            source_by_name.setdefault(name, []).append(index)
    mapping: dict[int, int] = {}
    used: set[int] = set()
    for imported_index, name in enumerate(imported_names):
        exact = source_by_name.get(name or "", [])
        if len(exact) == 1 and exact[0] not in used:
            mapping[imported_index] = exact[0]
            used.add(exact[0])
    stem = lambda value: re.sub(r"\.\d{3}$", "", value or "")
    unresolved = [index for index in range(len(imported_names)) if index not in mapping]
    available = [index for index in range(len(source_names)) if index not in used]
    for imported_index in list(unresolved):
        candidates = [index for index in available if stem(source_names[index]) == stem(imported_names[imported_index])]
        if len(candidates) == 1:
            source_index = candidates[0]
            mapping[imported_index] = source_index
            used.add(source_index); available.remove(source_index); unresolved.remove(imported_index)
    if unresolved:
        # Repeated suffix families are safe only when both transports retain
        # the same slot positions and stems at every unresolved position.
        if (not allow_source_subset and len(unresolved) != len(available)) or any(
            imported_index != source_index or stem(imported_names[imported_index]) != stem(source_names[source_index])
            for imported_index, source_index in zip(unresolved, available)
        ):
            raise ValueError(f"material slots do not map unambiguously: source={source_names}, imported={imported_names}")
        mapping.update(zip(unresolved, available))
    if len(mapping) != len(imported_names) or (
        not allow_source_subset and len(set(mapping.values())) != len(source_names)
    ):
        raise ValueError(f"material slots do not map bijectively: source={source_names}, imported={imported_names}")
    return mapping


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
class IRSemanticLodPolicy:
    """IR-only fixed ladder: every eligible mesh is reduced to at most 30%."""
    name = "ir_semantic_lod_v1"
    min_faces: int = 50_000
    floor_faces: int = 2_000

    def decide(self, ctx: DecimationContext) -> DecimationDecision:
        if ctx.n_faces < self.min_faces:
            return DecimationDecision(False, 1.0, reason=f"n_faces {ctx.n_faces}<{self.min_faces}", policy=self.name)
        if ctx.n_faces >= 5_000_000:
            ratio = 0.01
        elif ctx.n_faces >= 1_000_000:
            ratio = 0.03
        elif ctx.n_faces >= 250_000:
            ratio = 0.10
        else:
            ratio = 0.30
        ratio = min(0.30, max(ratio, self.floor_faces / max(ctx.n_faces, 1)))
        return DecimationDecision(
            True, ratio, reason=f"IR ladder {ctx.n_faces}->{int(ctx.n_faces * ratio)}", policy=self.name,
        )


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
    if name == "ir_semantic_lod_v1":
        return IRSemanticLodPolicy(min_faces=int(kw.get("min_faces", 50_000)))
    raise ValueError(f"unknown decimation policy: {name!r} (choices: none, ratio_threshold, semantic_contract, ir_semantic_lod_v1)")


# --------------------------------------------------------- bpy executor ----- #
def triangle_count(bpy_obj) -> int:
    """Return evaluated mesh triangle count; works with lightweight unit-test fakes."""
    mesh = bpy_obj.data
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    except Exception:
        return len(mesh.polygons)

def vertex_count(bpy_obj) -> int:
    """Vertices of the live mesh; 0 when the object cannot report them.

    Recorded beside the triangle count because triangles alone are not an
    identity for a mesh: a rebuild can keep every face and split vertices
    differently at UV seams and normal boundaries, which changes the
    interpolated surface and every atlas baked against it. Each count is a
    projection with its own null space, so the record carries the pair.
    """
    try:
        return len(bpy_obj.data.vertices)
    except Exception:  # noqa: BLE001  (lightweight unit-test fakes have no verts)
        return 0


def apply_decimation(bpy_obj, decision: DecimationDecision) -> int:
    """Apply the decision to a live bpy mesh via a DECIMATE modifier (COLLAPSE) and
    return the resulting triangle count. bpy-only — the caller guards on the decision so
    this never runs when decimate=False."""
    if not decision.decimate:
        return triangle_count(bpy_obj)
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
    return triangle_count(bpy_obj)


def decimate_object(
    bpy_obj,
    policy: DecimationPolicy,
    ctx: DecimationContext,
    *,
    strict: bool = False,
    tolerance: float = 0.05,
    fallback: Callable[[Any, int], dict] | None = None,
    allow_slot_loss_max_extent: float = 0.0,
) -> dict:
    """Apply a policy and record the *actual* topology result.

    ``allow_slot_loss_max_extent`` (metres, 0 = never): an object no larger than this keeps its decimated
    mesh even when a material slot lost every face (a 13 cm shelf figurine losing its tongue colour), instead
    of being restored to full resolution. The lost slots are recorded. Off by default: for GT a missing part
    is a defect; for the realtime simulator a small decor object at full poly is the larger cost.

    Blender collapse decimation can stop above its nominal ratio on difficult
    topology.  Retry against the measured remainder before declaring strict
    failure; a full-resolution mesh is never accepted as a successful LOD.
    """
    decision = policy.decide(ctx)
    before = ctx.n_faces
    vertices_before = vertex_count(bpy_obj)
    # Blender's COLLAPSE decimator can delete every face of a material slot on
    # a thin part -- a plant container lost slot 1 of [0,1,2,3], a dining table
    # lost the slot holding its legs. Decimation is applied in place, so hold
    # the source mesh until the result has been checked and restore it if a
    # slot went missing. An object over its LOD target costs memory; an object
    # missing a part is a defect in the ground truth.
    _pre_used_slots: set[int] = set()
    _pre_mesh = None
    if decision.decimate:
        try:
            _pre_mesh = bpy_obj.data
            _pre_used_slots = {int(poly.material_index) for poly in _pre_mesh.polygons}
            _pre_mesh = _pre_mesh.copy()
        except Exception:  # noqa: BLE001
            _pre_mesh, _pre_used_slots = None, set()
    target_max_faces = min(before, int(before * min(1.0, decision.target_ratio) * (1.0 + tolerance) + 0.999999))
    after = before
    error = None
    applied_ratios: list[float] = []
    pass_triangle_counts: list[int] = []
    if decision.decimate:
        try:
            next_ratio = float(decision.target_ratio)
            previous = before
            for _pass in range(3):
                pass_decision = DecimationDecision(
                    True, next_ratio, method=decision.method,
                    reason=f"{decision.reason}; pass={_pass + 1}", policy=decision.policy,
                )
                after = apply_decimation(bpy_obj, pass_decision)
                applied_ratios.append(round(next_ratio, 7))
                pass_triangle_counts.append(after)
                if after <= target_max_faces:
                    break
                if after >= previous:
                    break
                previous = after
                next_ratio = max(1e-4, min(1.0, target_max_faces / max(after, 1)))
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    # Blender COLLAPSE can stop far above its target on dense, disconnected
    # procedural meshes.  The caller may supply a meshoptimizer fallback; it
    # must return the measured triangle count, never just a process success.
    fallback_record = None
    fallback_unavailable = False
    if decision.decimate and error is None and after > target_max_faces and fallback is not None:
        try:
            fallback_record = dict(fallback(bpy_obj, target_max_faces) or {})
            after = int(fallback_record["triangles_after"])
        except Exception as exc:  # noqa: BLE001
            # A handful of procedural assets export an empty glTF after OBJ
            # conversion (usually a disconnected/degenerate detail mesh).
            # There is no topology for gltfpack to optimize in that case. Do
            # not abort the whole scene in strict mode: retain the measured
            # Blender result and record the exception so the asset remains
            # auditable. Other fallback failures remain hard errors.
            message = str(exc)
            # gltfpack is given a ratio and does not have to honour it. Asked
            # for 61% of a dining table's 35840 triangles it returned 856 --
            # 2.4% -- erasing the legs and leaving the rim of the top floating
            # with the cutlery that had rested on it. It can also drop a
            # material slot's geometry outright. Neither is a reason to abandon
            # the scene: the Blender result is over the LOD target, which costs
            # memory, where taking the collapsed mesh costs the object.
            _refused = ("gltfpack collapsed the mesh" in message
                        or "gltfpack dropped material slots" in message)
            if "gltfpack import expected one mesh object, got 0" in message:
                fallback_unavailable = True
                fallback_record = {
                    "status": "unavailable_empty_import",
                    "triangles_after": int(after),
                    "target_triangles": int(target_max_faces),
                    "error": f"{type(exc).__name__}: {message}",
                }
            elif _refused:
                fallback_unavailable = True
                fallback_record = {
                    "status": "refused_destructive_simplification",
                    "triangles_after": int(after),
                    "target_triangles": int(target_max_faces),
                    "error": f"{type(exc).__name__}: {message}",
                }
            else:
                error = f"fallback_error: {type(exc).__name__}: {exc}"
    # Restore the source when the surviving mesh no longer covers a slot that
    # had geometry. This runs after the fallback so it catches a loss from
    # either the Blender passes or gltfpack.
    slots_restored = False
    slots_lost_allowed: list[int] = []
    if decision.decimate and error is None and _pre_mesh is not None:
        try:
            post_slots = {int(poly.material_index) for poly in bpy_obj.data.polygons}
        except Exception:  # noqa: BLE001
            post_slots = _pre_used_slots
        try:
            extent = max(float(v) for v in bpy_obj.dimensions)
        except Exception:  # noqa: BLE001
            extent = float("inf")
        if (_pre_used_slots and not _pre_used_slots <= post_slots and post_slots
                and allow_slot_loss_max_extent > 0 and extent <= allow_slot_loss_max_extent):
            slots_lost_allowed = sorted(_pre_used_slots - post_slots)
        elif _pre_used_slots and not _pre_used_slots <= post_slots:
            lost = sorted(_pre_used_slots - post_slots)
            bpy_obj.data = _pre_mesh
            after = before
            slots_restored = True
            fallback_unavailable = True
            fallback_record = {
                "status": "restored_source_material_slots_lost",
                "lost_material_slots": lost,
                "triangles_after": int(before),
                "target_triangles": int(target_max_faces),
            }
    if _pre_mesh is not None and not slots_restored:
        try:
            import bpy  # noqa: F401
            bpy.data.meshes.remove(_pre_mesh)
        except Exception:  # noqa: BLE001
            pass
    no_effect = bool(decision.decimate and error is None and after > target_max_faces and not fallback_unavailable)
    if no_effect:
        error = f"no_effect: requested <= {target_max_faces} triangles at ratio {decision.target_ratio:.4f}, got {after} after {len(applied_ratios)} pass(es)"
    record = {
        "policy": decision.policy, "measurement": "triangles",
        "decimated": bool(decision.decimate and error is None and not fallback_unavailable),
        "status": "kept_source_material_slots_lost" if slots_restored
                  else "reduced_material_slots_lost" if slots_lost_allowed
                  else "kept_fallback_unavailable" if fallback_unavailable else "reduced" if decision.decimate and error is None else "no_effect" if no_effect else "error" if error else "kept",
        "faces_before": before, "faces_after": after, "target_max_faces": target_max_faces,
        "triangles_before": before, "triangles_after": after, "target_max_triangles": target_max_faces,
        "vertices_before": vertices_before, "vertices_after": vertex_count(bpy_obj),
        "target_ratio": round(decision.target_ratio, 4), "reason": decision.reason, "error": error,
        "pass_count": len(applied_ratios), "applied_ratios": applied_ratios, "pass_triangle_counts": pass_triangle_counts,
        "fallback": fallback_record,
        "material_slot_loss_allowed": bool(slots_lost_allowed),
        "lost_material_slots": slots_lost_allowed,
    }
    if strict and error is not None:
        raise RuntimeError(f"strict decimation failed for {ctx.object_id}: {error}")
    return record
