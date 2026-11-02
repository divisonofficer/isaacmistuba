"""Room descriptions for the planner, from a generated apartment blend (run in the infinigen env: bpy as a module).

    python extract_rooms.py SCENE.blend --out rooms.json

Per room (room frame = the floor's lower-left corner, metres): type, area, outline, walls (id, endpoints, length, blocked
stretches with the reason), doors and windows on their wall, and the furniture already there (id, category, centre, size, yaw).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import room_dressing as rd          # noqa: E402
from furnish_rooms import footprint  # noqa: E402

SKIP = ("WallArtFactory", "MirrorFactory", "CeilingLightFactory", "CeilingClassicLampFactory")
#: tabletop and shelf things (a book column is 0.4 m long): noise to a furniture planner, whatever their size
SMALL = ("BookColumnFactory", "BookStackFactory", "BookFactory", "BottleFactory", "JarFactory", "CanFactory", "FoodBoxFactory",
         "FoodBagFactory", "BowlFactory", "PlateFactory", "CupFactory", "FruitContainerFactory", "HardwareFactory", "SucculentFactory",
         "PlantContainerFactory", "VaseFactory", "PotFactory", "PanFactory", "WineglassFactory", "TowelFactory")


def outline(floor) -> list:
    """The floor mesh's longest boundary loop, world xy, collinear points merged."""
    me = floor.data
    count = {}
    for p in me.polygons:
        for e in p.edge_keys:
            count[e] = count.get(e, 0) + 1
    edges = [e for e, n in count.items() if n == 1]
    nbr = {}
    for a, b in edges:
        nbr.setdefault(a, []).append(b); nbr.setdefault(b, []).append(a)
    seen, loops = set(), []
    for start in nbr:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [v for v in nbr[cur] if v != prev]
            if not nxt or nxt[0] == start:
                break
            prev, cur = cur, nxt[0]
            if cur in seen:
                break
            seen.add(cur); loop.append(cur)
        loops.append(loop)
    loop = max(loops, key=len)
    pts = [(floor.matrix_world @ me.vertices[i].co) for i in loop]
    pts = [(p.x, p.y) for p in pts]
    out = []
    for i, p in enumerate(pts):                                  # drop points on a straight run
        a, c = pts[i - 1], pts[(i + 1) % len(pts)]
        cross = (p[0] - a[0]) * (c[1] - p[1]) - (p[1] - a[1]) * (c[0] - p[0])
        if abs(cross) > 1e-4 or math.dist(a, p) < 1e-6:
            out.append(p)
    return out


def inside(pt, poly) -> bool:
    x, y, n, c = pt[0], pt[1], len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def describe(name, parts, everything) -> dict:
    floor = parts["floor"]
    poly = outline(floor)
    ox, oy = min(p[0] for p in poly), min(p[1] for p in poly)
    rel = lambda x, y: [round(x - ox, 3), round(y - oy, 3)]  # noqa: E731
    walls = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        walls.append({"id": f"w{i}", "p0": rel(*a), "p1": rel(*b), "length": round(math.dist(a, b), 2), "blocked": []})

    def on_wall(cx, cy):
        best = None
        for w, i in zip(walls, range(len(poly))):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy or 1e-9
            t = max(0, min(1, ((cx - a[0]) * dx + (cy - a[1]) * dy) / L2))
            d = math.hypot(a[0] + t * dx - cx, a[1] + t * dy - cy)
            if best is None or d < best[0]:
                best = (d, w, t * math.sqrt(L2))
        return best

    doors, windows, existing = [], [], []
    for o in everything:
        f = rd._factory(o.name)
        fp = footprint(o)
        cx, cy = (fp[0] + fp[1]) / 2, (fp[2] + fp[3]) / 2
        width = max(fp[1] - fp[0], fp[3] - fp[2])
        if "Door" in f or "Window" in f:
            d, w, s = on_wall(cx, cy)
            if d > 0.4:
                continue
            item = {"wall": w["id"], "at_m": round(s, 2), "width": round(width, 2)}
            (doors if "Door" in f else windows).append(item)
            w["blocked"].append([round(s - width / 2 - (0.45 if "Door" in f else 0), 2), round(s + width / 2 + (0.45 if "Door" in f else 0), 2),
                                 "door" if "Door" in f else "window"])
            continue
        if f in SKIP or f in SMALL or not inside((cx, cy), poly) or fp[4] > floor.matrix_world.translation.z + 1.5:
            continue
        if max(fp[1] - fp[0], fp[3] - fp[2], fp[5] - fp[4]) < 0.35:   # cups and books: noise to a furniture planner
            continue
        cat = f.removesuffix("Factory")
        yaw = round(math.degrees(o.matrix_world.to_euler().z) % 360)
        item = {"id": f"e{len(existing)}", "category": cat, "center": rel(cx, cy),
                "size": [round(fp[1] - fp[0], 2), round(fp[3] - fp[2], 2), round(fp[5] - fp[4], 2)], "yaw_deg": yaw,
                "_name": o.name}                                 # for the realizer; plan_scene strips "_" keys from the prompt
        d, w, s = on_wall(cx, cy)
        if d < 0.6:
            item["against_wall"] = w["id"]
            w["blocked"].append([round(s - width / 2, 2), round(s + width / 2, 2), item["id"]])
        existing.append(item)
    area = 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))))
    return {"id": name, "type": name.split("_")[0], "area_m2": round(area, 1), "outline": [rel(*p) for p in poly],
            "walls": walls, "doors": doors, "windows": windows, "existing": existing, "_origin": [ox, oy]}


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("blend")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    everything = rd._tops()
    rooms = [describe(n, p, everything) for n, p in sorted(rd._rooms().items()) if "floor" in p]
    Path(a.out).write_text(json.dumps({"scene": a.blend, "rooms": rooms}, indent=1))
    print("ROOMS", json.dumps([(r["id"], r["area_m2"], len(r["existing"])) for r in rooms]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
