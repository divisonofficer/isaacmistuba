"""Describe a Stage-2 blend, or re-save it with its textures packed in and the file compressed (bundled Blender).

    blender --background X.blend --python stage2_pack.py -- [--pack-to OUT.blend]

Prints `STAGE2 {json}`. Counts cover what a render can reach (reachable()); `after_pack` is the same census taken in memory just before the save.

Packing mirrors the adapter's pack_textures() (every image with users, bytes stored as the file has them), and the save
carries the compress flag. adapt_stage2_for_hssd_renderer.py then yields the same adapted blends from the packed file as
from the original (measured 2026-10-06 on 97341955: report identical in 59 of 62 fields, the rest paths and was_external),
and, because save_as_mainfile(copy=True) keeps the loaded file's compress flag, those come out compressed too.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import bpy  # type: ignore
import numpy as np


def reachable():
    """Everything a render of this blend can touch: scene objects, their meshes and materials, node trees through group nodes,
    the images those trees read, lights, cameras, the worlds. Counting datablocks by `users` instead is not stable across a save:
    something used only by an unsaved zero-user datablock keeps users > 0 in memory and has none after the reload."""
    d = bpy.data
    objs = {o.name_full: o for sc in d.scenes for o in sc.objects}
    meshes, mats, trees, images = {}, {}, {}, {}
    for o in objs.values():
        if o.type == "MESH" and o.data is not None:
            meshes[o.data.name_full] = o.data
            for m in o.data.materials:
                if m is not None:
                    mats[m.name_full] = m
        for slot in o.material_slots:
            if slot.material is not None:
                mats[slot.material.name_full] = slot.material

    def walk(nt):
        # Not name_full: every material's embedded node tree is called "Shader Nodetree", so a name key made all of them one tree.
        if nt is None or nt.as_pointer() in trees:
            return
        trees[nt.as_pointer()] = nt
        for n in nt.nodes:
            img = getattr(n, "image", None)
            if img is not None:
                images[img.name_full] = img
            walk(getattr(n, "node_tree", None))

    for m in mats.values():
        walk(m.node_tree)
    lights = {o.data.name_full: o.data for o in objs.values() if o.type == "LIGHT" and o.data is not None}
    for light in lights.values():
        walk(getattr(light, "node_tree", None))
    for sc in d.scenes:
        if sc.world is not None:
            walk(sc.world.node_tree)
        walk(sc.node_tree)
    cams = {o.data.name_full for o in objs.values() if o.type == "CAMERA" and o.data is not None}
    return objs, meshes, mats, trees, images, lights, cams


def stats() -> dict:
    objs, meshes, mats, trees, images, lights, cams = reachable()
    s1 = s2 = 0.0
    verts = polys = 0
    for m in meshes.values():
        k = len(m.vertices)
        verts += k
        polys += len(m.polygons)
        if k:
            a = np.empty(k * 3, dtype=np.float32)
            m.vertices.foreach_get("co", a)
            a = a.astype(np.float64)
            s1 += float(a.sum())
            s2 += float((a * a).sum())
    per_image = sorted((i.name_full, len(i.packed_file.data) if i.packed_file else 0) for i in images.values())
    return {"objects": len(objs), "meshes": len(meshes), "materials": len(mats), "node_trees": len(trees), "lights": len(lights),
            "cameras": len(cams), "verts": verts, "polys": polys, "co_sum": s1, "co_sq_sum": s2,
            "mat_nodes": sum(len(t.nodes) for t in trees.values()), "mat_links": sum(len(t.links) for t in trees.values()),
            "images": len(images), "images_packed": sum(1 for _, b in per_image if b), "packed_bytes": sum(b for _, b in per_image),
            "images_digest": hashlib.sha1(json.dumps(per_image).encode()).hexdigest()}


def external_bytes() -> tuple[int, int, list]:
    """(images, bytes, missing) of reachable images that still read their pixels from a file."""
    n = total = 0
    missing = []
    for i in reachable()[4].values():
        if i.packed_file or i.source != "FILE":
            continue
        path = bpy.path.abspath(i.filepath)
        if os.path.isfile(path):
            n += 1
            total += os.path.getsize(path)
        else:
            missing.append(path[-90:])
    return n, total, missing


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack-to", help="write the packed, compressed copy here (the open file is left alone)")
    a = ap.parse_args(argv)
    report = {"source": bpy.data.filepath, "stats": stats()}
    n, nbytes, missing = external_bytes()
    report["external_images"], report["external_bytes"], report["missing"] = n, nbytes, missing
    if a.pack_to:
        t = time.time()
        unpackable = []
        for image in bpy.data.images:
            if not image.users or image.packed_file:
                continue
            try:
                image.pack()
            except RuntimeError as exc:
                unpackable.append({"name": image.name[:48], "why": str(exc)[:60]})
        report["pack_s"] = round(time.time() - t, 1)
        report["unpackable"] = unpackable
        report["after_pack"] = stats()
        t = time.time()
        bpy.ops.wm.save_as_mainfile(filepath=a.pack_to, compress=True, copy=True)
        report["save_s"] = round(time.time() - t, 1)
        report["out"], report["out_bytes"] = a.pack_to, os.path.getsize(a.pack_to)
    print("STAGE2 " + json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
