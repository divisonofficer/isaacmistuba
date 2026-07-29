#!/usr/bin/env python3
"""Semantic LOD — Phase B decision table (shape-level, render-aligned).

Joins the render scene's 540 obj shapes to the Phase-A per-slot budget and produces
a per-SHAPE decimation decision (the render consumes shapes, not manifest units):

  shape_id  (render_scene.xml)   -> unit_id = shape_id.split('__')[0]
  material_id (material_policy)  -> which material_slot -> r*, contract
  mesh_cache/<hash>.obj          -> real face count (authoritative for the render)

For review-flagged trinkets (NatureShelfTrinkets: shell vs coral vs organic) it runs a
CHEAP topology classifier (connected components, thinness, area/volume) to pick the
appearance contract and its floor — coral (branched_identity, floor 10%) is protected
from over-compression while compact shells stay aggressive. The final 50-vp polar
render is the ultimate visual validation (per the chosen full-pipeline plan).

Output: <scene_dir>/semantic_lod_shapes.json  (consumed by decimate_lod_scene.py).

    python tools/build_semantic_lod_scene.py --scene kr_20260625
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENE_DIR = REPO / "out/opticalnav/opticalnav-v0.2/scenes"
IMPORT_DIR = REPO / "out/infinigen_imports"

MIN_FACES = 150  # never decimate below this


# ------------------------------------------------------------ obj face count --
def obj_face_count(path: Path) -> int:
    """Count faces in an OBJ (each 'f ' line = 1 polygon; assume triangulated).
    Binary chunked scan (fast over CIFS: no per-line Python overhead)."""
    n = 0
    tail = b"\n"          # so a leading 'f ' at file start is caught
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(1 << 20)
            if not buf:
                break
            buf = tail + buf
            n += buf.count(b"\nf ") + buf.count(b"\nf\t")
            tail = buf[-1:]
    return n


# --------------------------------------------------- trinket topology veto ----
def classify_trinket(mesh_path: Path):
    """Cheap topology classifier -> (contract, floor, descriptors).
    branched_identity : many disconnected/thin components (coral, twigs)  floor 10%
    organic_mass      : bulky but irregular fuzzy mass                    floor 1%
    compact_solid     : single bulky blob (shell, stone, rounded)         floor 3%
    """
    import trimesh
    import numpy as np
    m = trimesh.load(mesh_path, force="mesh", process=False)
    # topology CLASS is detail-invariant -> analyze a fast ~40k-face proxy so the
    # expensive connected-component split doesn't run on multi-million-face meshes.
    if len(m.faces) > 60000:
        try:
            m = m.simplify_quadric_decimation(face_count=40000)
        except Exception:
            pass
    ext = np.asarray(m.extents, float)
    thin = float(min(ext) / max(max(ext), 1e-9))
    diag = float(np.linalg.norm(ext))
    try:
        comps = m.split(only_watertight=False)
        n_comp = len(comps)
    except Exception:
        n_comp = 1
    area = float(m.area)
    # surface-area vs bbox surface (rough "surface complexity")
    bbox_area = 2 * (ext[0]*ext[1] + ext[1]*ext[2] + ext[0]*ext[2]) + 1e-9
    area_ratio = area / bbox_area
    desc = {"n_comp": n_comp, "thin": round(thin, 3),
            "area_ratio": round(area_ratio, 2), "diag": round(diag, 4)}
    # branched: fragmented into many pieces, OR very thin, OR huge surface/bbox area
    if n_comp >= 8 or thin < 0.10 or area_ratio > 6.0:
        return "branched_identity", 0.10, desc
    # organic mass: moderately complex surface but one bulky piece
    if area_ratio > 2.5 or n_comp >= 3:
        return "organic_mass", 0.01, desc
    return "compact_solid", 0.03, desc


# ---------------------------------------------------------------- main build --
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="kr_20260625")
    ap.add_argument("--annotation-scene", default="infinigen_kr_20260625")
    ap.add_argument("--no-veto", action="store_true", help="skip trinket topology classify (fast)")
    a = ap.parse_args()

    sdir = SCENE_DIR / a.annotation_scene
    xml = (sdir / "render_scene.xml").read_text()
    plan = json.loads((IMPORT_DIR / a.scene / "semantic_lod_plan.json").read_text())
    policy = {p["shape_id"]: p for p in
              json.loads((sdir / "render_scene_material_policy.json").read_text())["shape_policies"]}

    # unit_id -> {slot_name -> slot decision}, plus unit meta
    unit_slots, unit_meta = {}, {}
    for u in plan["units"]:
        unit_slots[u["object_id"]] = {s["slot"]: s for s in u["slots"]}
        unit_meta[u["object_id"]] = u

    shapes = re.findall(r'<shape type="obj" id="([^"]+)">\s*<string name="filename" value="([^"]+)"', xml)
    print(f"scene {a.annotation_scene}: {len(shapes)} obj shapes")

    out_shapes = []
    veto_cache = {}   # mesh hash -> (contract, floor, desc)  (dedup identical meshes)
    orig_total = lod_total = 0
    for i, (sid, fn) in enumerate(shapes):
        unit_id = sid.split("__")[0]
        pol = policy.get(sid, {})
        material_id = pol.get("material_id")
        mesh_path = Path(fn)
        faces = obj_face_count(mesh_path)
        orig_total += faces

        slotmap = unit_slots.get(unit_id)
        if not slotmap:                        # low-poly unit -> keep at 100%
            rec = {"shape_id": sid, "unit_id": unit_id, "material_id": material_id,
                   "mesh": fn, "faces": faces, "retained_ratio": 1.0,
                   "target_faces": faces, "contract": None, "kept": True}
            out_shapes.append(rec); lod_total += faces
            continue

        # match this shape's material to a slot decision
        slot = slotmap.get(material_id) or next(iter(slotmap.values()))
        contract = slot["contract"]
        r = slot["retained_ratio"]
        note = list(slot.get("corrections", []))

        um = unit_meta[unit_id]
        veto_desc = None
        if not a.no_veto and um.get("review") and faces > 20000:
            key = mesh_path.name
            if key not in veto_cache:
                try:
                    veto_cache[key] = classify_trinket(mesh_path)
                except Exception as exc:
                    veto_cache[key] = ("compact_solid", 0.03, {"err": str(exc)})
            contract, floor, veto_desc = veto_cache[key]
            r = max(r, floor)                  # geometry veto: never below contract floor
            note.append(f"veto:{contract}(floor{floor})")

        target = max(int(round(faces * r)), MIN_FACES)
        if target >= faces:                    # never up-sample
            target, r = faces, 1.0
        rec = {"shape_id": sid, "unit_id": unit_id, "material_id": material_id,
               "mesh": fn, "faces": faces, "retained_ratio": round(r, 3),
               "target_faces": target, "contract": contract,
               "optical_class": slot.get("optical_class"), "corrections": note,
               "review": bool(um.get("review")), "veto": veto_desc, "kept": target >= faces}
        out_shapes.append(rec); lod_total += target
        if (i + 1) % 60 == 0:
            print(f"  ...{i+1}/{len(shapes)} shapes  (orig {orig_total:,} -> lod {lod_total:,})")

    result = {
        "scene": a.annotation_scene, "import_scene": a.scene,
        "shapes": len(out_shapes),
        "orig_faces": orig_total, "lod_faces": lod_total,
        "reduction_pct": round(100 * (1 - lod_total / max(orig_total, 1)), 1),
        "shape_records": out_shapes,
    }
    out = sdir / "semantic_lod_shapes.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\norig {orig_total:,} -> lod {lod_total:,} faces  (-{result['reduction_pct']}%)")
    print(f"shapes to decimate: {sum(1 for s in out_shapes if s['target_faces'] < s['faces'])}")
    # contract rollup
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0])
    for s in out_shapes:
        k = s["contract"] or "keep(lowpoly)"
        agg[k][0] += 1; agg[k][1] += s["faces"]; agg[k][2] += s["target_faces"]
    print("\ncontract                 shapes    orig_faces    -> lod_faces")
    for k, (n, o, l) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        print(f"  {k:22s} {n:5d}  {o:>12,}  {l:>12,}  ({100*l/max(o,1):.1f}%)")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
