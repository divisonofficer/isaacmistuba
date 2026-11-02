"""Props for the user's office floor (floor O; refs out/room_planner_refs/office_floor_bldg_01_clean; docs/office_floor_design_proposal.md). Front +X, back at x = 0.

  HouseBoothFactory   an orange-wood lounge booth with a house-shaped (pentagon-top) back: 1.9 m wide x 1.1 deep x 1.75 high at the ridge; rounded orange-wood shell sides, a grey upholstered bench seat and
                      a small round table inside; the open side faces +X
  BuntingFactory      a paper bunting garland: a thin cord 3.0 m long with 8 small dark-grey / kraft triangular flags, hung 0.25 m under the ceiling (origin at the left end of the cord, along +y)
"""
from __future__ import annotations

import random

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


def _prism(o, pts_yz, x0, x1, slot):
    """Extrude the polygon pts_yz = [(y, z), ...] from x0 to x1 into object o (material slot `slot`), flat shaded faces with outward normals."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(o.data)
    a = [bm.verts.new((x0, y, z)) for y, z in pts_yz]; b = [bm.verts.new((x1, y, z)) for y, z in pts_yz]; n = len(a)
    fs = [bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])) for k in range(n)] + [bm.faces.new(a), bm.faces.new(reversed(b))]
    bmesh.ops.recalc_face_normals(bm, faces=fs)
    for f in fs:
        f.material_index = slot
    bm.to_mesh(o.data); bm.free()


class HouseBoothFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        wood = fl._flat("ir_booth_wood", (0.72, 0.5, 0.2), 0.45, wood=True); seat = fl._flat("ir_booth_seat", (0.45, 0.46, 0.5), 0.8); cream = fl._flat("ir_booth_top_dark", (0.16, 0.12, 0.09), 0.4)         # dark tabletop (O2 refs)
        W, D, H = 1.9, 1.1, 1.75
        roof = []                                                          # the pentagon back is one straight-edged prism (see _prism), not stacked slabs
        back = []
        sides = [("box", 0, sy * (W / 2 - 0.03), 0.5, D, 0.06, 1.0) for sy in (1, -1)]
        shell = back + roof + sides
        bench = [("box", -0.1, 0, 0.42, 0.55, W - 0.2, 0.1), ("box", -0.32, 0, 0.7, 0.12, W - 0.2, 0.5),
                 ("box", 0.82, 0, 0.42, 0.42, W - 0.3, 0.1), ("box", 1.0, 0, 0.65, 0.1, W - 0.3, 0.42)]        # O2 r8 CNT-01 'booth tables bare, no chairs/benches': a second upholstered bench faces the first across the table (the booth is now two benches + a table)
        table = [("box", 0.38, 0, 0.72, 0.5, W - 0.5, 0.04), ("box", 0.38, -(W - 0.5) / 2 + 0.05, 0.36, 0.45, 0.04, 0.72), ("box", 0.38, (W - 0.5) / 2 - 0.05, 0.36, 0.45, 0.04, 0.72)]   # a rectangular worktop with two panel legs (O2 refs)
        o = mesh_object(f"HouseBoothFactory({i}).spawn_asset({i})", [(wood, shell), (seat, bench), (cream, table)], bevel=True)
        import math as _m
        arch = [(_m.cos(t_) * W / 2, 1.0 + (H - 1.0) * _m.sin(t_)) for t_ in [k * _m.pi / 14 for k in range(15)]]
        if pa.STYLE.get("booth_roof") == "gable":                        # kit booth_roof=gable: the refs' house-shaped pointed roof (O2 r10) instead of the barrel arch
            arch = [(W / 2, 1.0), (0.0, H), (-W / 2, 1.0)]      # a ROUNDED house top: an arch instead of a straight gable (O2 'rounded intact house-booth shells')
        _prism(o, [(-W / 2, 0.0), (W / 2, 0.0)] + arch, -D / 2, -D / 2 + 0.06, 0)
        _prism(o, arch, -D / 2 + 0.06, D / 2, 0)                                                  # starts behind the 6 cm back slab: the two prisms' x = -D/2 caps were coplanar and overlapping (z-fight = the jagged triangles); arch already starts at (W/2, 1.0) and ends at (-W/2, 1.0): the old list repeated both end points (zero-length edges, 2 zero-area faces, O2 r9 AST-02 jagged black holes)
        return o


class BuntingFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        cord = fl._flat("ir_bunting_cord", (0.5, 0.45, 0.4), 0.7); flag = fl._flat("ir_bunting_flag", (0.3, 0.28, 0.26), 0.8); kraft = fl._flat("ir_bunting_kraft", (0.62, 0.5, 0.35), 0.8)
        L = 3.0; parts_f, parts_k = [], []
        for k in range(8):
            y = 0.2 + k * (L - 0.4) / 7
            tgt = parts_f if k % 2 == 0 else parts_k
            tgt.append(("box", 0, y, -0.1, 0.004, 0.16, 0.18))
            tgt.append(("box", 0, y, -0.2, 0.004, 0.1, 0.04))
        return mesh_object(f"BuntingFactory({i}).spawn_asset({i})", [(cord, [("cyl", (0, 0, 0.0), (0, L, 0.0), 0.002, 4)]), (flag, parts_f), (kraft, parts_k)], bevel=False)
