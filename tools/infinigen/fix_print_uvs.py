"""Repair the UVs of printed-image faces in an already-built scene (proc_assets._face_uvs fixes them at creation; this fixes blends whose
furniture step ran before that fix): every polygon whose material is `ir_print_*` gets a full 0..1 UV square, upright as seen from outside,
computed in the object's local space from its own normal and extent.

    from fix_print_uvs import fix; fix()
"""
import bpy
import bmesh


def fix():
    n = 0
    for me in {o.data for o in bpy.data.objects if o.type == "MESH"}:
        slots = {i for i, m in enumerate(me.materials) if m is not None and m.name.startswith("ir_print_")}
        if not slots:
            continue
        bm = bmesh.new(); bm.from_mesh(me); uv = bm.loops.layers.uv.verify()
        table = {(0, 1): (1, 1, 2), (0, -1): (1, -1, 2), (1, 1): (0, -1, 2), (1, -1): (0, 1, 2), (2, 1): (0, 1, 1), (2, -1): (0, 1, 1)}
        for f in bm.faces:
            if f.material_index not in slots:
                continue
            f.normal_update(); nrm = f.normal; ax = max(range(3), key=lambda k: abs(nrm[k]))
            u_ax, u_s, v_ax = table[(ax, 1 if nrm[ax] > 0 else -1)]
            us = [u_s * l.vert.co[u_ax] for l in f.loops]; vs = [l.vert.co[v_ax] for l in f.loops]
            u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
            for l, u, v in zip(f.loops, us, vs):
                l[uv].uv = ((u - u0) / max(u1 - u0, 1e-9), (v - v0) / max(v1 - v0, 1e-9))
            n += 1
        bm.to_mesh(me); bm.free()
    print(f"FIXUVS {n} printed faces", flush=True)
    return n


if __name__ == "__main__":
    import sys
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    fix(); bpy.ops.wm.save_as_mainfile(filepath=a[a.index("--out") + 1], compress=True)
