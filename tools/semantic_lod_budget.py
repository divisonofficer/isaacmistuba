#!/usr/bin/env python3
"""Semantic–Topology-Aware LOD Budgeting — rule engine core.

Design (2026-07-28): the safe compression of a high-poly Infinigen object is NOT a
fixed ratio per object *category*. It is the lowest retained-triangle ratio a human
would still visually accept, PREDICTED from:

    appearance contract (what the semantics require preserving)
  + scale-normalized topology descriptors (what kind of shape it is)
  + task role  + projected on-screen size  (how it is used / seen)
  applied PER MATERIAL SLOT (glass boundary conserved, inner filler cut hard).

This module holds the *data-independent* rule engine (contract priors, the LOD
candidate ladder, task-role / projected-size / boundary corrections, per-slot budget
combination, and a conservative-lower-bound accept rule that over-penalizes
over-compression). Descriptor extraction (trimesh) and scene I/O are wired on top in
`semantic_lod_features.py` / the scene-prep driver; this core is unit-testable alone.

Reference: dev_report/report_2026-07-28_polar_lod.html (shells 10% ok, coral needs
~30%, cactus visually fine to 1% despite low IoU) — the finding that motivates
contracts over fixed ratios.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

# ------------------------------------------------------------------ ladder --- #
# Candidate retained-triangle ratios. "steps" always move along THIS ladder, so a
# "one step more aggressive" correction is one index down, never an absolute jump.
LADDER = (0.01, 0.03, 0.10, 0.30, 0.50, 1.00)


def _idx(ratio: float) -> int:
    """Nearest ladder index for a ratio (priors are given on the ladder)."""
    return min(range(len(LADDER)), key=lambda i: abs(LADDER[i] - ratio))


def _clamp(i: int) -> int:
    return max(0, min(len(LADDER) - 1, i))


# --------------------------------------------------------------- contracts --- #
# Appearance contract = what must survive visually. Prior is the STARTING ladder
# ratio before role/size corrections. `optical_interface` and `task_critical` carry
# hard FLOORS (a minimum ratio that corrections may not go below).
@dataclass(frozen=True)
class Contract:
    name: str
    prior: float           # starting retained ratio (on the ladder)
    floor: float = 0.01    # corrections may not push below this
    note: str = ""


CONTRACTS = {
    "compact_solid":    Contract("compact_solid", 0.10, 0.03,
                                 "조개·돌·둥근 소품: 전체 실루엣·큰 곡률 보존"),
    "branched_identity": Contract("branched_identity", 0.30, 0.10,
                                  "산호·가지: 주요 가지 수와 분기 구조가 정체성 → 분기 소실 불가"),
    "organic_mass":     Contract("organic_mass", 0.03, 0.01,
                                 "선인장·퍼지 식생: 세부 가시보다 전체 덩어리·인식성"),
    "rigid_planar":     Contract("rigid_planar", 0.50, 0.30,
                                 "캐비닛·문·선반: 직선·평면·모서리·구멍이 무너지면 즉시 부자연"),
    "optical_interface": Contract("optical_interface", 0.30, 0.10,
                                  "유리병·금속용기: 곡면 법선·외곽·재질 경계·Fresnel"),
    "task_critical":    Contract("task_critical", 0.50, 0.30,
                                 "유리문·장애물·landmark: 충돌 형상·정확한 실루엣, 한 단계 이상 보수적"),
}

# Which correction knob matters most per contract (used only for confidence /
# reporting — the numeric budget uses the generic corrections below).
CONTRACT_PRIMARY_METRIC = {
    "compact_solid":     ("silhouette", "curvature", "normal"),
    "branched_identity": ("branch_survival", "component_survival"),
    "organic_mass":      ("lowfreq_silhouette", "volume"),
    "rigid_planar":      ("planarity", "straight_edges", "corners", "holes"),
    "optical_interface": ("normal_dist", "outline", "material_boundary", "fresnel_proxy"),
    "task_critical":     ("silhouette", "collision_hull"),
}

# ------------------------------------------------------------- task roles --- #
# Correction is expressed in ladder "steps": negative = more conservative (keep more),
# positive = more aggressive (cut more).
TASK_ROLE_STEPS = {
    "background_decoration": +1,
    "unmentioned_clutter":   +1,   # plus: removable if projected size tiny (handled in size rule)
    "landmark":              -1,
    "collision_obstacle":    -2,
    "target_object":         -2,
    "optical_eval_target":    0,   # special: forces optical slots to >=30% (see budget)
    "manipulation_target":   -2,   # plus: separate close-range verification flag
    "none":                   0,
}

# ------------------------------------------------------- projected size --- #
# Expected on-screen size (px) at the actual navigation distance, not the 0.3 m
# close-up used for the qualification renders.
def projected_size_steps(px: Optional[float]) -> tuple[int, bool]:
    """Return (ladder_steps, removable). removable=True means the object may be
    dropped entirely when it is also clutter."""
    if px is None:
        return 0, False
    if px < 8:
        return +2, True          # remove or very low proxy
    if px < 32:
        return +1, False         # 1–3% plausible
    if px < 96:
        return 0, False          # semantic/topology budget as-is
    return -1, False             # large on screen → one step conservative


# --------------------------------------------------------------- decision --- #
@dataclass
class SlotDecision:
    slot: str
    contract: str
    tri_fraction: float                 # share of object triangles in this slot
    prior: float
    retained_ratio: float               # r_s*  (chosen ladder value)
    steps_applied: int
    corrections: list = field(default_factory=list)
    confidence: str = "medium"          # high | medium | low
    review: bool = False                # send to polarization visual review
    removed: bool = False


def budget_slot(
    slot: str,
    contract: str,
    tri_fraction: float,
    task_role: str = "none",
    projected_px: Optional[float] = None,
    material_boundary_loss: bool = False,
    contract_ambiguous: bool = False,
    descriptor_conflict: bool = False,
) -> SlotDecision:
    """Lowest safe retained ratio for one material slot, per the design's rule set.

    Step convention (LADDER is ascending, so a higher index keeps MORE triangles):
      +step = more AGGRESSIVE (cut more)  -> index moves DOWN  (i - step)
      -step = more CONSERVATIVE (keep more) -> index moves UP  (i - (-step))
    Corrections stack, then the contract FLOOR and (for optical eval targets) the
    optical-slot floor are enforced. Over-compression is penalized by the confidence
    rule: any ambiguity/conflict demotes confidence and, when low, we keep one LOD
    MORE and flag for visual review — the conservative lower bound of accept
    probability, not the mean."""
    c = CONTRACTS[contract]
    i0 = _idx(c.prior)
    i = i0
    corr: list[str] = []

    trs = TASK_ROLE_STEPS.get(task_role, 0)
    if trs:
        i = _clamp(i - trs)
        corr.append(f"task_role:{task_role}({trs:+d})")

    ssteps, removable = projected_size_steps(projected_px)
    if ssteps:
        i = _clamp(i - ssteps)
        corr.append(f"projected_px:{projected_px}({ssteps:+d})")

    if material_boundary_loss:
        i = _clamp(i + 1)  # conservative: keep more
        corr.append("material_boundary_loss(keep_more)")

    # confidence & over-compression guard
    conf = "high"
    review = False
    if contract_ambiguous or descriptor_conflict:
        conf = "low"
        i = _clamp(i + 1)  # low confidence -> keep MORE
        corr.append("low_confidence(keep_more)")
        review = True
    elif material_boundary_loss or task_role in ("optical_eval_target", "manipulation_target"):
        conf = "medium"
        review = task_role in ("optical_eval_target", "manipulation_target")

    # hard floors: contract floor, and optical-eval optical slots >= 30%
    floor_idx = _idx(c.floor)
    if task_role == "optical_eval_target" and contract in ("optical_interface", "task_critical"):
        floor_idx = max(floor_idx, _idx(0.30))
        corr.append("optical_eval_floor>=30%")
    i = max(i, floor_idx)

    ratio = LADDER[i]
    removed = bool(removable and task_role in ("unmentioned_clutter", "background_decoration")
                   and contract in ("organic_mass", "compact_solid"))
    if removed:
        corr.append("removed(tiny_clutter)")

    return SlotDecision(
        slot=slot, contract=contract, tri_fraction=round(tri_fraction, 4),
        prior=c.prior, retained_ratio=0.0 if removed else ratio,
        steps_applied=(0 if removed else i - i0),
        corrections=corr, confidence=conf, review=review, removed=removed,
    )


@dataclass
class ObjectBudget:
    object_id: str
    category: str
    task_role: str
    projected_px: Optional[float]
    slots: list                        # list[SlotDecision]
    target_fraction: float = 0.0       # F_target = sum_s r_s* * F_s
    review: bool = False

    def finalize(self) -> "ObjectBudget":
        self.target_fraction = round(
            sum(s.retained_ratio * s.tri_fraction for s in self.slots), 4)
        self.review = any(s.review for s in self.slots)
        return self


def budget_object(object_id: str, category: str, slots_meta: list,
                  task_role: str = "none", projected_px: Optional[float] = None) -> ObjectBudget:
    """slots_meta: list of dicts with keys
        slot, contract, tri_fraction,
        [material_boundary_loss, contract_ambiguous, descriptor_conflict]
    Returns a finalized ObjectBudget (per-slot ratios + tri-weighted target)."""
    decs = [budget_slot(
        slot=m["slot"], contract=m["contract"], tri_fraction=m["tri_fraction"],
        task_role=task_role, projected_px=projected_px,
        material_boundary_loss=m.get("material_boundary_loss", False),
        contract_ambiguous=m.get("contract_ambiguous", False),
        descriptor_conflict=m.get("descriptor_conflict", False),
    ) for m in slots_meta]
    return ObjectBudget(object_id, category, task_role, projected_px, decs).finalize()


def budget_to_dict(b: ObjectBudget) -> dict:
    d = asdict(b)
    return d


if __name__ == "__main__":
    # smoke: the three worked examples from the design brief
    import json
    cactus = budget_object(
        "cactus_in_metal_pot", "plant_container",
        slots_meta=[
            {"slot": "cactus", "contract": "organic_mass", "tri_fraction": 0.62},
            {"slot": "spikes", "contract": "organic_mass", "tri_fraction": 0.30},
            {"slot": "dirt", "contract": "organic_mass", "tri_fraction": 0.05},
            {"slot": "metal_pot", "contract": "optical_interface", "tri_fraction": 0.03},
        ],
        task_role="background_decoration", projected_px=40)
    coral = budget_object(
        "coral_trinket", "decoration",
        slots_meta=[{"slot": "coral", "contract": "branched_identity", "tri_fraction": 1.0,
                     "descriptor_conflict": False}],
        task_role="background_decoration", projected_px=40)
    jar = budget_object(
        "mushroom_in_glass_jar", "plant_container",
        slots_meta=[
            {"slot": "glass_jar", "contract": "optical_interface", "tri_fraction": 0.15,
             "material_boundary_loss": False},
            {"slot": "mushrooms", "contract": "organic_mass", "tri_fraction": 0.70},
            {"slot": "sand", "contract": "organic_mass", "tri_fraction": 0.15},
        ],
        task_role="background_decoration", projected_px=40)
    for b in (cactus, coral, jar):
        print(json.dumps(budget_to_dict(b), ensure_ascii=False, indent=1))
