"""Declarative props: a JSON spec (what the Anthropic API returns from asset_agent) -> a factory-shaped class, bpy only at spawn time.

spec = {"name": "WhiteBin", "notes": str,
        "parts": [{"material": {"name", "rgb": [r,g,b], "rough", "metallic"?, "emit"?: strength, "kind"?: scan kind},
                   "prims": [["box", cx, cy, cz, sx, sy, sz, yaw?], ["cyl", [x0,y0,z0], [x1,y1,z1], r, n], ["sph", [x,y,z], r, sub]]}]}
Conventions are proc_museum's: front +X, origin at the bottom centre, metres, one merged mesh. `validate` is pure Python and returns a list of problems.
"""
from __future__ import annotations

import re

MAX_PRIMS, MAX_PART, MAX_EXTENT = 600, 400, 12.0
ARITY = {"box": (7, 8), "cyl": (5, 5), "sph": (4, 4)}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < 1e4


def validate(spec) -> list:
    bad = []
    if not isinstance(spec, dict) or not re.fullmatch(r"[A-Z][A-Za-z0-9]{2,40}", str(spec.get("name", ""))):
        return ["name must be CamelCase, 3-41 chars"]
    parts = spec.get("parts")
    if not isinstance(parts, list) or not parts:
        return ["parts missing"]
    total = 0
    for i, p in enumerate(parts):
        m = p.get("material", {}) if isinstance(p, dict) else {}
        if not (isinstance(m.get("rgb"), list) and len(m["rgb"]) == 3 and all(_num(c) and 0 <= c <= 1 for c in m["rgb"])) or not _num(m.get("rough", None)):
            bad.append(f"part {i}: material needs rgb [3 x 0..1] and rough"); continue
        prims = p.get("prims") or []
        total += len(prims)
        if len(prims) > MAX_PART:
            bad.append(f"part {i}: {len(prims)} prims > {MAX_PART}")
        for q in prims:
            kind = q[0] if q else None
            if kind not in ARITY or not (ARITY[kind][0] <= len(q) <= ARITY[kind][1]):
                bad.append(f"part {i}: bad prim {str(q)[:60]}"); continue
            args = q[1:7] if kind == "box" else q[1:4]                 # coordinates and sizes only: not yaw / segments / subdivisions
            flat = [v for a in args for v in (a if isinstance(a, list) else [a])]
            if not all(_num(v) for v in q[1:] for v in (v if isinstance(v, list) else [v])):
                bad.append(f"part {i}: non-numeric prim {str(q)[:60]}")
            elif max(abs(v) for v in flat) > MAX_EXTENT:
                bad.append(f"part {i}: prim beyond {MAX_EXTENT} m {str(q)[:60]}")
    if total > MAX_PRIMS:
        bad.append(f"{total} prims > {MAX_PRIMS}")
    return bad


def _prim(q):
    return tuple(tuple(a) if isinstance(a, list) else a for a in q)


def build_factory(spec):
    """Factory class for a validated spec (raises ValueError otherwise)."""
    bad = validate(spec)
    if bad:
        raise ValueError("; ".join(bad))

    class _F:
        def __init__(self, seed):
            self.seed = seed

        def spawn_asset(self, i):
            from room_planner import proc_boutique_flagship as fl
            from room_planner.proc_museum import _emit
            groups = []
            for p in spec["parts"]:
                m = p["material"]; rgb = tuple(m["rgb"])
                mat = _emit(f"ir_gen_{spec['name']}_{m.get('name', 'm')}", rgb, m["emit"]) if m.get("emit") else \
                    fl._flat(f"ir_gen_{spec['name']}_{m.get('name', 'm')}", rgb, m["rough"], m.get("metallic", 0.0), kind=m.get("kind"))
                groups.append((mat, [_prim(q) for q in p["prims"]]))
            o = fl.mesh_object(f"{spec['name']}Factory({self.seed}).spawn_asset({i})", groups, bevel=False)
            if spec.get("bevel_m"):                                    # optional soft edges (a sofa): bmesh bevel of every edge by bevel_m metres
                import bmesh
                bm = bmesh.new(); bm.from_mesh(o.data)
                bmesh.ops.bevel(bm, geom=bm.edges[:], offset=float(spec["bevel_m"]), offset_type="OFFSET", segments=2, affect="EDGES")
                bm.to_mesh(o.data); bm.free()
            return o
    _F.__name__ = spec["name"] + "Factory"
    return _F
