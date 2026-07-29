#!/usr/bin/env python3
"""Semantic LOD — Step 2: decimate mesh_cache per the shape decision table and emit
render_scene_lod.xml (transforms + BSDF refs + material_policy unchanged, so per-slot
material placement is preserved automatically).

Reads  <scene_dir>/semantic_lod_shapes.json
Writes <scene_dir>/lod_mesh_cache/<hash>_f<target>.obj   (deduped by hash+target)
       <scene_dir>/render_scene_lod.xml

Decimation: trimesh.simplify_quadric_decimation(face_count) (Open3D QEM backend), same
as the production daemon path. Multiprocessing over unique (mesh, target) pairs.

    python tools/decimate_lod_scene.py --scene infinigen_kr_20260625 --workers 6
"""
from __future__ import annotations
import argparse
import json
import os
import re
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENE_DIR = REPO / "out/opticalnav/opticalnav-v0.2/scenes"


def _decimate_one(job):
    src, dst, target = job
    try:
        import trimesh
        dst = Path(dst)
        if dst.is_file():
            return (str(dst), None, "cached")
        m = trimesh.load(src, force="mesh", process=False)
        n0 = len(m.faces)
        if target >= n0:
            m.export(dst)   # copy through (still normalize format)
            return (str(dst), len(m.faces), "copy")
        simp = m.simplify_quadric_decimation(face_count=int(target))
        tmp = dst.with_name(f"{dst.stem}.tmp.{os.getpid()}{dst.suffix}")
        simp.export(tmp); tmp.replace(dst)
        return (str(dst), len(simp.faces), "ok")
    except Exception as exc:
        return (str(dst), None, f"ERR {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="infinigen_kr_20260625")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sdir = SCENE_DIR / a.scene
    data = json.loads((sdir / "semantic_lod_shapes.json").read_text())
    recs = data["shape_records"]
    lod_dir = sdir / "lod_mesh_cache"
    lod_dir.mkdir(exist_ok=True)

    # assign each shape its lod mesh path (dedup by source hash + target faces)
    jobs = {}
    for r in recs:
        src = Path(r["mesh"])
        if r["target_faces"] >= r["faces"]:
            r["lod_mesh"] = r["mesh"]     # unchanged, reuse original
            continue
        dst = lod_dir / f"{src.stem}_f{r['target_faces']}.obj"
        r["lod_mesh"] = str(dst)
        jobs[(str(src), str(dst), r["target_faces"])] = True
    jobs = list(jobs.keys())
    print(f"{len(recs)} shapes, {len(jobs)} unique decimation jobs "
          f"({data['orig_faces']:,} -> {data['lod_faces']:,} faces, -{data['reduction_pct']}%)")

    if a.dry_run:
        print("dry-run: not decimating");
    else:
        done = 0
        with Pool(a.workers) as pool:
            for dst, nf, status in pool.imap_unordered(_decimate_one, jobs, chunksize=1):
                done += 1
                if status.startswith("ERR"):
                    print(f"  [{done}/{len(jobs)}] {status}  {dst}")
                elif done % 25 == 0 or done == len(jobs):
                    print(f"  [{done}/{len(jobs)}] {status}  -> {nf} faces  {Path(dst).name}")

    # rewrite render_scene.xml -> render_scene_lod.xml, per shape block
    xml = (sdir / "render_scene.xml").read_text()
    rec_by_id = {r["shape_id"]: r for r in recs}

    def repl(mobj):
        block = mobj.group(0)
        sid = re.search(r'id="([^"]+)"', block).group(1)
        r = rec_by_id.get(sid)
        if not r or r["lod_mesh"] == r["mesh"]:
            return block
        return block.replace(f'value="{r["mesh"]}"', f'value="{r["lod_mesh"]}"')

    new_xml = re.sub(r'<shape type="obj" id="[^"]+">.*?</shape>', repl, xml, flags=re.S)
    out_xml = sdir / "render_scene_lod.xml"
    out_xml.write_text(new_xml)
    n_sw = sum(1 for r in recs if r.get("lod_mesh") and r["lod_mesh"] != r["mesh"])
    print(f"\nrewrote {n_sw} shape filenames -> {out_xml}")
    # persist lod_mesh assignments back
    (sdir / "semantic_lod_shapes.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
