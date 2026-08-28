#!/usr/bin/env python3
"""Semantic LOD — build the decimated render scene in ONE parallel pass.

Folds the old (redundant) face-count pass + trinket veto + decimation together so
every mesh is loaded exactly ONCE, across a process pool:

  1. instant join (no mesh I/O):  render_scene.xml shape  ->  unit = id.split('__')[0]
     -> material_policy material_id -> semantic_lod_plan slot -> r*, contract, review
  2. dedup jobs by (mesh, r*): identical mesh_cache hash + same ratio -> one decimation
  3. per job (parallel worker): load mesh once; if a review trinket, classify a fast
     40k proxy (shell=compact floor 3% / coral=branched floor 10% / organic 1%) and
     lift r* to the contract floor; target = round(faces*r*); QEM decimate -> lod obj
  4. rewrite render_scene.xml -> render_scene_lod.xml (transforms + BSDF refs +
     material_policy unchanged -> per-slot material placement preserved)

Output: <scene_dir>/{render_scene_lod.xml, lod_mesh_cache/, semantic_lod_shapes.json}

    python tools/build_lod_scene.py --scene kr_20260625 --workers 8
Env (Device 1): LD_LIBRARY_PATH, PYTHONPATH as usual (trimesh+Open3D only; no GPU).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENE_DIR = REPO / "out/opticalnav/opticalnav-v0.2/scenes"
IMPORT_DIR = REPO / "out/infinigen_imports"
MIN_FACES = 150


# ------------------------------------------------- worker: load+veto+decimate --
def _local_copy(src: Path) -> Path:
    """Copy a CIFS mesh to a local scratch dir before heavy trimesh/Open3D work.
    /jarvis is a CIFS mount; loading 100-200 MB OBJs directly (esp. many at once)
    stalls indefinitely. Copying first is the same pattern single_object_polar_lod
    uses (POLAR_LOD_MESH_CACHE)."""
    import shutil
    cache = Path(os.environ.get("LOD_MESH_SCRATCH", "/tmp/claude-1000/lod_scene/src"))
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / src.name
    if not dst.is_file() or dst.stat().st_size == 0:
        shutil.copy2(src, dst)
    return dst


def _process_job(job: dict) -> dict:
    """One unique (mesh, r*) decimation. Loads the mesh once. For review trinkets,
    classifies a cheap 40k proxy and lifts r* to the contract floor."""
    import trimesh
    import numpy as np
    src = Path(job["mesh"]); r = job["r"]; contract = job["contract"]
    lod_dir = Path(job["lod_dir"])
    out = {"key": job["key"], "faces": 0, "target": 0, "r": r, "contract": contract,
           "veto": None, "lod_mesh": job["mesh"], "status": "keep"}
    try:
        local = _local_copy(src)
        m = trimesh.load(local, force="mesh", process=False)
        faces = int(len(m.faces)); out["faces"] = faces
        if job["veto"] and faces > 20000:
            proxy = m
            if faces > 60000:
                try:
                    proxy = m.simplify_quadric_decimation(face_count=40000)
                except Exception:
                    proxy = m
            ext = np.asarray(proxy.extents, float)
            thin = float(min(ext) / max(max(ext), 1e-9))
            try:
                n_comp = len(proxy.split(only_watertight=False))
            except Exception:
                n_comp = 1
            bbox_area = 2 * (ext[0]*ext[1] + ext[1]*ext[2] + ext[0]*ext[2]) + 1e-9
            area_ratio = float(proxy.area / bbox_area)
            if n_comp >= 8 or thin < 0.10 or area_ratio > 6.0:
                contract, floor = "branched_identity", 0.10
            elif area_ratio > 2.5 or n_comp >= 3:
                contract, floor = "organic_mass", 0.01
            else:
                contract, floor = "compact_solid", 0.03
            r = max(r, floor)
            out.update(contract=contract, r=round(r, 3),
                       veto={"contract": contract, "floor": floor, "n_comp": n_comp,
                             "thin": round(thin, 3), "area_ratio": round(area_ratio, 2)})
        target = max(int(round(faces * r)), MIN_FACES)
        out["target"] = target
        if target >= faces:
            out["status"] = "keep"; out["lod_mesh"] = job["mesh"]; return out
        # Mesh-cache files frequently have generic names such as
        # ``000_GLTF.obj``.  A basename-only target collides across unrelated
        # GLBs and can make a low-memory scene *larger* than its source.  The
        # resolved source path is stable for this scene and makes the cache
        # identity unambiguous while keeping outputs inspectable.
        source_key = hashlib.sha256(str(src.resolve()).encode("utf-8")).hexdigest()[:12]
        dst = Path(job["lod_dir"]) / f"{src.stem}_{source_key}_f{target}.obj"
        out["lod_mesh"] = str(dst)
        if dst.is_file():
            cached = trimesh.load(dst, force="mesh", process=False)
            cached_faces = int(len(cached.faces))
            # A corrupt/stale cache must never be selected merely because its
            # filename happens to match.  Rebuild instead of silently
            # increasing geometry or using a different object's mesh.
            if 0 < cached_faces <= faces and cached_faces <= max(target * 1.05, target + 8):
                out.update(target=cached_faces, status="cached")
                return out
            try:
                dst.unlink()
            except OSError:
                pass
        simp = m.simplify_quadric_decimation(face_count=int(target))
        tmp = dst.with_name(f"{dst.stem}.tmp.{os.getpid()}{dst.suffix}")
        simp.export(tmp); tmp.replace(dst)
        out["target"] = int(len(simp.faces))
        out["status"] = "ok"; out["actual"] = int(len(simp.faces))
    except Exception as exc:
        out["status"] = f"ERR {type(exc).__name__}: {exc}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="kr_20260625")
    ap.add_argument("--annotation-scene", default="infinigen_kr_20260625")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument(
        "--source-scene", default="render_scene.xml",
        help="Source Mitsuba XML within the annotation scene (for example render_scene_perturbed.xml).",
    )
    ap.add_argument(
        "--output-scene", default="render_scene_lod.xml",
        help="LOD Mitsuba XML filename to write within the annotation scene.",
    )
    a = ap.parse_args()

    sdir = SCENE_DIR / a.annotation_scene
    source_xml = sdir / a.source_scene
    output_xml = sdir / a.output_scene
    if source_xml.parent != sdir or output_xml.parent != sdir:
        raise ValueError("--source-scene and --output-scene must be filenames within the annotation scene")
    xml = source_xml.read_text()
    plan = json.loads((IMPORT_DIR / a.scene / "semantic_lod_plan.json").read_text())
    policy = {p["shape_id"]: p for p in
              json.loads((sdir / "render_scene_material_policy.json").read_text())["shape_policies"]}
    lod_dir = sdir / "lod_mesh_cache"; lod_dir.mkdir(exist_ok=True)

    unit_slots = {u["object_id"]: {s["slot"]: s for s in u["slots"]} for u in plan["units"]}
    unit_review = {u["object_id"]: bool(u.get("review")) for u in plan["units"]}

    shapes = re.findall(r'<shape type="obj" id="([^"]+)">\s*<string name="filename" value="([^"]+)"', xml)
    print(f"scene {a.annotation_scene}: {len(shapes)} obj shapes", flush=True)

    # instant join -> per-shape (r, contract, veto) + dedup jobs by (mesh, r)
    shape_recs, jobs = [], {}
    for sid, fn in shapes:
        unit_id = sid.split("__")[0]
        material_id = policy.get(sid, {}).get("material_id")
        slotmap = unit_slots.get(unit_id)
        if not slotmap:
            rec = {"shape_id": sid, "unit_id": unit_id, "material_id": material_id,
                   "mesh": fn, "r": 1.0, "contract": None, "veto": False}
        else:
            slot = slotmap.get(material_id) or next(iter(slotmap.values()))
            rec = {"shape_id": sid, "unit_id": unit_id, "material_id": material_id,
                   "mesh": fn, "r": float(slot["retained_ratio"]), "contract": slot["contract"],
                   "optical_class": slot.get("optical_class"), "veto": unit_review.get(unit_id, False)}
        shape_recs.append(rec)
        if rec["r"] < 1.0 or rec["veto"]:
            key = (fn, round(rec["r"], 3), rec["contract"], rec["veto"])
            if key not in jobs:
                jobs[key] = {"key": list(key), "mesh": fn, "r": rec["r"],
                             "contract": rec["contract"], "veto": rec["veto"],
                             "lod_dir": str(lod_dir)}
    joblist = list(jobs.values())
    print(f"instant join done. {len(joblist)} unique decimation jobs "
          f"(of {sum(1 for r in shape_recs if r['r']<1.0 or r['veto'])} candidate shapes). "
          f"loading meshes x{a.workers}...", flush=True)

    results = {}
    done = 0
    with Pool(a.workers) as pool:
        for res in pool.imap_unordered(_process_job, joblist, chunksize=1):
            done += 1
            results[tuple(res["key"])] = res
            tag = res["status"]
            if tag.startswith("ERR") or res.get("veto") or done % 20 == 0 or done == len(joblist):
                v = f" veto->{res['veto']['contract']}" if res.get("veto") else ""
                print(f"  [{done}/{len(joblist)}] {tag:7s} {res['faces']:>8,}->{res['target']:>7,} "
                      f"r={res['r']:.2f}{v}  {Path(res['lod_mesh']).name}", flush=True)

    # assemble final per-shape table + rewrite xml
    orig_total = lod_total = 0
    for rec in shape_recs:
        key = (rec["mesh"], round(rec["r"], 3), rec["contract"], rec["veto"])
        r = results.get(key)
        if r:
            rec["faces"] = r["faces"]; rec["target_faces"] = r["target"] or r["faces"]
            rec["retained_ratio"] = r["r"]; rec["contract"] = r["contract"]
            rec["lod_mesh"] = r["lod_mesh"]; rec["veto"] = r.get("veto")
        else:
            rec["faces"] = rec.get("faces", 0); rec["target_faces"] = rec["faces"]
            rec["lod_mesh"] = rec["mesh"]
        orig_total += rec["faces"]; lod_total += rec["target_faces"]

    rec_by_id = {r["shape_id"]: r for r in shape_recs}

    def repl(mobj):
        block = mobj.group(0)
        sid = re.search(r'id="([^"]+)"', block).group(1)
        r = rec_by_id.get(sid)
        if not r or r["lod_mesh"] == r["mesh"]:
            return block
        return block.replace(f'value="{r["mesh"]}"', f'value="{r["lod_mesh"]}"')

    new_xml = re.sub(r'<shape type="obj" id="[^"]+">.*?</shape>', repl, xml, flags=re.S)
    # The XML alone is not proof that it was built from this particular scene.
    # Keep a small adjacent attestation so the render daemon can refuse an old
    # or hand-edited LOD file rather than silently substituting geometry.
    output_xml.write_text(new_xml)
    n_sw = sum(1 for r in shape_recs if r["lod_mesh"] != r["mesh"])

    result = {"scene": a.annotation_scene, "import_scene": a.scene, "shapes": len(shape_recs),
              "orig_faces": orig_total, "lod_faces": lod_total,
              "reduction_pct": round(100 * (1 - lod_total / max(orig_total, 1)), 1),
              "shapes_swapped": n_sw, "shape_records": shape_recs}
    (sdir / "semantic_lod_shapes.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    lod_attestation = {
        "schema_version": 2,
        "builder": "tools/build_lod_scene.py",
        "source_scene": source_xml.name,
        "output_scene": output_xml.name,
        "source_xml_sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(),
        "output_xml_sha256": hashlib.sha256(new_xml.encode("utf-8")).hexdigest(),
        "mesh_cache_identity": "sha256(resolved_source_mesh_path)+target_faces",
        "shapes_swapped": n_sw,
        "candidate_source_faces": orig_total,
        "candidate_lod_faces": lod_total,
    }
    output_xml.with_suffix(output_xml.suffix + ".manifest.json").write_text(
        json.dumps(lod_attestation, ensure_ascii=False, indent=2) + "\n"
    )

    print(f"\norig {orig_total:,} -> lod {lod_total:,} faces  (-{result['reduction_pct']}%)")
    print(f"rewrote {n_sw} shape filenames -> {output_xml}")
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0])
    for s in shape_recs:
        k = s["contract"] or "keep(lowpoly)"
        agg[k][0] += 1; agg[k][1] += s["faces"]; agg[k][2] += s["target_faces"]
    print("\ncontract               shapes    orig_faces  ->   lod_faces")
    for k, (n, o, l) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        print(f"  {k:20s} {n:5d}  {o:>12,}  {l:>12,}  ({100*l/max(o,1):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
