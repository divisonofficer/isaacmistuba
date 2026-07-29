#!/usr/bin/env python3
"""Semantic–Topology-Aware LOD Budgeting — Phase A driver (manifest-only policy).

Reads out/infinigen_imports/<scene>/scene_manifest.json and, using ONLY the metadata
already in the manifest (semantic_type, factory, optical_class, material_slots,
dimensions — no mesh I/O), assigns for every high-poly unit:
    task_role        <- semantic_type
    per-slot contract<- optical_class + factory (+ topology in Phase B)
    projected proxy  <- world dimensions   (true pixel projection wired later)
    per-slot r*      <- semantic_lod_budget rule engine
and marks contract-ambiguous units (chiefly NatureShelfTrinkets: shell vs coral vs
organic) for the Phase-B geometry veto.

Output: out/infinigen_imports/<scene>/semantic_lod_plan.json  (policy table).
Phase B (build_semantic_lod_features.py) loads the meshes to add per-slot tri
fractions, topology descriptors, Chamfer/area geometry veto, then decimates.

    python tools/build_semantic_lod_plan.py --scene kr_20260625
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from semantic_lod_budget import budget_object, budget_to_dict, LADDER  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# ------------------------------------------------- semantic_type -> task role --
SEM_TASK = {
    "glass_door": "optical_eval_target",   # navigation-critical glass: optical slots >=30%
    "glass_wall": "optical_eval_target",
    "landmark":   "landmark",              # -1 conservative
    "table":      "landmark",
    "chair":      "landmark",
    "wall":       "landmark",              # structural, keep
    "shelf":      "background_decoration",  # the trinkets sitting on shelves: +1 aggressive
    "plant":      "background_decoration",
}

# ------------------------------------------------------------ factory groups --
CONTAINER_FACTORIES = {"PlantContainerFactory", "LargePlantContainerFactory",
                       "JarFactory", "VaseFactory"}
STRUCTURAL_FACTORIES = {"SingleCabinetFactory", "BedFactory", "SofaFactory",
                        "PlateFactory", "ToiletFactory", "ComforterFactory",
                        "MattressFactory", "TableFactory", "ChairFactory",
                        "DoorFactory", "WindowFactory"}
# diffuse trinkets whose shape kind (shell/coral/organic) is only decidable from
# geometry -> flagged ambiguous so Phase B classifies + vetoes.
AMBIGUOUS_DIFFUSE_FACTORIES = {"NatureShelfTrinketsFactory"}


def slot_contract(optical_class: str, factory: str, semantic_type: str) -> tuple[str, bool]:
    """(contract, ambiguous). ambiguous=True -> needs the Phase-B geometry check."""
    if optical_class in ("glass", "mirror"):
        return "optical_interface", False
    if optical_class == "metal_aluminum":
        # metal container/surface: Fresnel + curved normals matter
        return "optical_interface", False
    # diffuse
    if factory in STRUCTURAL_FACTORIES or semantic_type in ("wall", "table", "chair"):
        return "rigid_planar", False
    if factory in CONTAINER_FACTORIES:
        return "organic_mass", False          # foliage / mushrooms / soil inside a container
    if factory in AMBIGUOUS_DIFFUSE_FACTORIES:
        return "compact_solid", True          # DEFAULT compact; Phase B may -> branched/organic
    return "compact_solid", True


def projected_proxy(dimensions) -> float:
    """World-size proxy -> a nominal on-screen px used only for the size tier.
    Replaced by true per-viewpoint projection once the nav grid is wired in."""
    d = max(dimensions) if dimensions else 0.3
    if d < 0.15:
        return 24.0     # small clutter -> +1 aggressive tier (8-32 px)
    if d < 0.5:
        return 64.0     # base (32-96 px)
    return 128.0        # large furniture -> conservative (>96 px)


def build(scene: str, poly_threshold: int) -> dict:
    root = REPO / "out/infinigen_imports" / scene
    man = json.loads((root / "scene_manifest.json").read_text())
    units = man["units"]
    plan_units = []
    for u in units:
        polys = u.get("polys", 0)
        if polys < poly_threshold:
            continue  # low-poly: keep at 100% (not a compression target)
        factory = u.get("factory", "")
        sem = u.get("semantic_type", "")
        task_role = SEM_TASK.get(sem, "none")
        px = projected_proxy(u.get("dimensions"))
        slots = u.get("material_slots") or [{"name": u.get("materials", ["?"])[0],
                                             "optical_class": u.get("optical_class", "diffuse")}]
        slots_meta = []
        for s in slots:
            oc = s.get("optical_class", u.get("optical_class", "diffuse"))
            contract, amb = slot_contract(oc, factory, sem)
            slots_meta.append({
                "slot": s.get("name", "?"), "contract": contract,
                "tri_fraction": round(1.0 / len(slots), 4),   # PROVISIONAL (uniform); Phase B replaces
                "optical_class": oc,
                "contract_ambiguous": amb,
            })
        b = budget_object(u["id"], f"{factory}/{sem}", slots_meta,
                          task_role=task_role, projected_px=px)
        d = budget_to_dict(b)
        # keep optical_class alongside each slot decision for the report
        for sd, sm in zip(d["slots"], slots_meta):
            sd["optical_class"] = sm["optical_class"]
        d.update({"polys": polys, "factory": factory, "semantic_type": sem,
                  "baked_normal": bool(u.get("baked_normal")),
                  "mesh_obj": u.get("mesh_obj"), "dimensions": u.get("dimensions")})
        plan_units.append(d)

    total_polys = sum(u.get("polys", 0) for u in units)
    hp_polys = sum(p["polys"] for p in plan_units)
    # provisional projected saving (uniform tri fractions; Phase B refines)
    est_kept = sum(p["target_fraction"] * p["polys"] for p in plan_units)
    plan = {
        "scene_id": man.get("scene_id", scene), "phase": "A (manifest-only policy)",
        "ladder": list(LADDER), "poly_threshold": poly_threshold,
        "totals": {
            "scene_polys": total_polys, "highpoly_units": len(plan_units),
            "highpoly_polys": hp_polys,
            "provisional_kept_polys": round(est_kept),
            "provisional_scene_polys_after": round(total_polys - hp_polys + est_kept),
            "provisional_reduction_pct": round(100 * (1 - (total_polys - hp_polys + est_kept) / total_polys), 1),
            "review_units": sum(1 for p in plan_units if p["review"]),
        },
        "units": plan_units,
    }
    return plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="kr_20260625")
    ap.add_argument("--poly-threshold", type=int, default=50000)
    a = ap.parse_args()
    plan = build(a.scene, a.poly_threshold)
    out = REPO / "out/infinigen_imports" / a.scene / "semantic_lod_plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    t = plan["totals"]
    print(f"scene {plan['scene_id']}: {t['highpoly_units']} high-poly units "
          f"({t['highpoly_polys']:,}/{t['scene_polys']:,} polys = "
          f"{100*t['highpoly_polys']/t['scene_polys']:.0f}% of scene)")
    print(f"provisional (uniform tri-frac) reduction: {t['scene_polys']:,} -> "
          f"{t['provisional_scene_polys_after']:,} polys  (-{t['provisional_reduction_pct']}%)")
    print(f"units flagged for Phase-B geometry veto: {t['review_units']}")
    # per-factory rollup
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0.0])
    for p in plan["units"]:
        a2 = agg[p["factory"]]
        a2[0] += 1; a2[1] += p["polys"]; a2[2] += p["target_fraction"] * p["polys"]
    print("\nfactory                         units    polys   ->prov.kept   avg r*")
    for f, (n, pol, kept) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        print(f"  {f:28s} {n:4d}  {pol:>10,}   {kept/pol*100:5.1f}%")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
