"""Room map of an imported Infinigen scene, for the OpticalNav simulator's bird's-eye view (PC_OPTICALNAV_SIMUL, 2026-10-13).

    python tools/infinigen/export_room_map.py --scene SCENE_ID [--scene ...] [--pack packs/opticalnav-v0.2] [--preview]

Writes out/opticalnav/opticalnav-v0.2/scenes/<scene>/room_map.json (+ room_map.png/.svg previews), and with --pack also copies the
json into <pack>/scenes/<scene>/. Run with the infinigen env python (numpy, scipy, scikit-image).

Frame: OpticalNav authoring/dataset (x, y), metres -- the frame of nav_graph.json "world", the traversable grid and index.jsonl
positions. The sim draws in R2R (x, -y) and flips y itself.
Rooms: each `<type>_<level>/<idx>.floor` mesh in xml_scene_index.json, authoring (x, y) = (tx + vx, tz + vz) (sign checked against the
nav grid on 17/17 scenes, 2026-10-08), rasterised at 5 cm and traced to polygons.
Connections: two rooms are connected where their floors meet AND the traversable grid crosses that boundary; the marker is the middle
of the crossable stretch. Door/Open comes from the generator's solve_state.json when it still exists; otherwise it is inferred from
the crossable width (<= 1.2 m: door) and marked so.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi
from skimage import draw, measure

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "out/opticalnav/opticalnav-v0.2"
GENERATED = REPO / "data/infinigen_generated/outputs"
RES = 0.05
ROOM_RE = re.compile(r"^(?P<type>[a-z-]+)_(?P<level>\d+)[/_](?P<idx>\d+)$")
FRAME = "opticalnav_authoring_xy_m (nav_graph world / traversable grid / index.jsonl frame); R2R viewer = (x, -y)"


def source_files(scene_dir: Path, name: str) -> list[Path]:
    """<name> of the generator output: kr_<import root>*/full/, else beside the import manifest's source_blend (sim packs)."""
    meta = json.loads((scene_dir / "authoring_map.json").read_text()).get("metadata") or {}
    root = str(meta.get("import_root") or "")
    hits = sorted(GENERATED.glob(f"{Path(root).name}*/full/{name}")) if root else []
    man = REPO / root / "scene_manifest.json"
    if not hits and root and man.is_file():
        src = Path(json.loads(man.read_text()).get("source_blend") or "")
        hits = [q for q in [src if name == "scene.blend" else src.parent / name] if src.name and q.is_file()]
    return hits


def read_obj(path):
    v, f = [], []
    for line in open(path):
        if line.startswith("v "):
            v.append([float(t) for t in line.split()[1:4]])
        elif line.startswith("f "):
            f.append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    return np.array(v), f


def room_shells(scene_dir: Path) -> dict[str, tuple]:
    """Room name -> (cx, cy, sx, sy) of the imported room shell (`<room>.wall` point objects carry centre + size)."""
    a = json.loads((scene_dir / "authoring_map.json").read_text())
    out = {}
    for o in a["objects"]:
        if o.get("type") == "wall" and str(o.get("label", "")).endswith(".wall") and o["geometry"].get("center") and o["geometry"].get("size_m"):
            (cx, cy), (sx, sy, _) = o["geometry"]["center"], o["geometry"]["size_m"]
            out[o["label"].removesuffix(".wall")] = (cx, cy, sx, sy)
    return out


def blend_floor_triangles(scene_dir: Path, wanted: set[str]) -> dict[str, list[np.ndarray]]:
    """Floors of the generated scene.blend for rooms whose cached OBJ is unreadable (mode 000 on the NAS), mapped to authoring by
    x' = x + dx, y' = c - y (the importer's Y-up/Z-up swap mirrors y), dx and c fitted on the room-shell centres (10-08 recipe)."""
    import subprocess, tempfile
    blends = source_files(scene_dir, "scene.blend")
    if not blends:
        return {}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "floors.json"
        subprocess.run(["nice", "-n", "10", "python3", str(REPO / "tools/infinigen/run_bundled_blender.py"), "--background", "--python",
                        str(REPO / "tools/infinigen/dump_blend_floors.py"), "--", str(out), str(blends[0])],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "CUDA_VISIBLE_DEVICES": ""})
        rooms = json.loads(out.read_text())["rooms"]
    shells = room_shells(scene_dir)
    cen = {n: ((np.array(v["verts"])[:, 0].min() + np.array(v["verts"])[:, 0].max()) / 2,
               (np.array(v["verts"])[:, 1].min() + np.array(v["verts"])[:, 1].max()) / 2) for n, v in rooms.items()}
    common = [n for n in cen if n in shells]
    dx = float(np.median([shells[n][0] - cen[n][0] for n in common])); c = float(np.median([shells[n][1] + cen[n][1] for n in common]))
    res = {}
    for n, v in rooms.items():
        if n in wanted:
            a = np.array(v["verts"])
            res[n] = [np.stack([a[f, 0] + dx, c - a[f, 1]], 1) for f in v["faces"]]
    return res


PACK = Path("/jarvis/project/opticalnav_sim/packs/opticalnav-v0.2")


def pack_floor_triangles(scene: str, wanted: set[str]) -> dict[str, list[np.ndarray]]:
    """The sim pack's own copies: base.xml `<room>.floor` PLY shapes with translate (x, 0, z), same convention as the OBJ cache."""
    import xml.etree.ElementTree as ET
    import trimesh
    base = PACK / "scenes" / scene / "base.xml"
    if not base.is_file():
        return {}
    res = {}
    for shape in ET.parse(base).getroot().iter("shape"):
        name = str(shape.get("id", "")).removesuffix(".floor").replace("_0_", "_0/")
        if not str(shape.get("id", "")).endswith(".floor") or name not in wanted:
            continue
        fn = next((x.get("value") for x in shape.iter("string") if x.get("name") == "filename"), None)
        tr = next(shape.iter("translate"), None)
        if fn is None or tr is None:
            continue
        try:
            m = trimesh.load(base.parent / fn, process=False)
        except OSError:
            continue
        tx, tz = float(tr.get("x", 0)), float(tr.get("z", 0))
        v = np.asarray(m.vertices)
        res[name] = [np.stack([tx + v[f, 0], tz + v[f, 2]], 1) for f in np.asarray(m.faces)]
    return res


def floor_triangles(scene_dir: Path) -> tuple[dict[str, list[np.ndarray]], dict[str, str]]:
    idx = json.loads((scene_dir / "xml_scene_index.json").read_text())
    rooms: dict[str, list] = {}
    source: dict[str, str] = {}
    missing = set()
    for s in idx["shapes"]:
        oid = s["object_id"]
        if not oid.endswith(".floor"):
            continue
        name = oid.removesuffix(".floor").replace("_0_", "_0/") if "/" not in oid else oid.removesuffix(".floor")
        try:                       # os.access lies under the NAS root_squash: some cached OBJs are mode 000, so ask by reading
            v, faces = read_obj(s["mesh_path"])
        except OSError:
            missing.add(name)
            continue
        tx, _, tz = s["transform"]["translate"]
        rooms.setdefault(name, []).extend(np.stack([tx + v[f, 0], tz + v[f, 2]], 1) for f in faces)
        source[name] = "floor_mesh_cache"
    if missing:
        for name, tris in pack_floor_triangles(scene_dir.name, missing).items():
            rooms[name], source[name] = tris, "floor_from_sim_pack_ply"
        still = missing - set(rooms)
        for name, tris in (blend_floor_triangles(scene_dir, still) if still else {}).items():
            rooms[name], source[name] = tris, "floor_from_generated_blend"
        shells = room_shells(scene_dir)
        for name in sorted(missing - set(rooms)):
            if name in shells:      # last resort: the room shell's bounding rectangle
                cx, cy, sx, sy = shells[name]
                rect = np.array([[cx - sx / 2, cy - sy / 2], [cx + sx / 2, cy - sy / 2], [cx + sx / 2, cy + sy / 2], [cx - sx / 2, cy + sy / 2]])
                rooms[name], source[name] = [rect[[0, 1, 2]], rect[[0, 2, 3]]], "approximate_room_shell_bbox"
    return rooms, source


def solve_state_edges(scene_dir: Path) -> tuple[dict, str | None]:
    """{(a, b): 'Door'|'Open'} from the generator's solve_state, located through the import root's kr_ name."""
    hits = source_files(scene_dir, "solve_state.json")
    if not hits:
        return {}, None
    objs = json.loads(hits[0].read_text())["objs"]
    edges = {}
    for n, o in objs.items():
        if not ROOM_RE.match(n):
            continue
        for rel in o.get("relations", []):
            r = rel["relation"]
            if r.get("relation_type") != "RoomNeighbour":
                continue
            kind = tuple(r["connector_types"])
            if kind in (("Door",), ("Open",)):
                edges[tuple(sorted((n, rel["target_name"])))] = kind[0]
    return edges, str(hits[0])


def traversable(scene_dir: Path):
    if not (scene_dir / "traversable_grid.npy.json").is_file():
        return np.zeros((1, 1), bool), 0.0, 0.0, 1.0      # no grid: connections come from the room graph alone
    meta = json.loads((scene_dir / "traversable_grid.npy.json").read_text())["grid"]
    grid = np.load(scene_dir / "traversable_grid.npy")
    if grid.shape != (meta["height"], meta["width"]):
        grid = grid.T
    return grid == 1, float(meta["origin"][0]), float(meta["origin"][1]), float(meta["resolution"])


def build(scene: str) -> dict:
    sd = PROJECT / "scenes" / scene
    tris, poly_source = floor_triangles(sd)
    names = sorted(tris)
    allp = np.vstack([q for n in names for q in tris[n]])
    ox, oy = allp.min(0) - 1.0
    W = int(math.ceil((allp[:, 0].max() + 1.0 - ox) / RES)); H = int(math.ceil((allp[:, 1].max() + 1.0 - oy) / RES))
    lab = np.zeros((H, W), np.int32)
    for i, n in enumerate(names):
        for q in tris[n]:
            rr, cc = draw.polygon((q[:, 1] - oy) / RES - 0.5, (q[:, 0] - ox) / RES - 0.5, (H, W))
            lab[rr, cc] = i + 1
    to_xy = lambda r, c: (ox + (c + 0.5) * RES, oy + (r + 0.5) * RES)

    # traversable grid resampled onto our raster (both 5 cm; nearest cell)
    trav, gx0, gy0, gres = traversable(sd)
    rr, cc = np.mgrid[0:H, 0:W]
    gx = np.floor((ox + (cc + 0.5) * RES - gx0) / gres).astype(int); gy = np.floor((oy + (rr + 0.5) * RES - gy0) / gres).astype(int)
    inside = (gx >= 0) & (gy >= 0) & (gx < trav.shape[1]) & (gy < trav.shape[0])
    walk = np.zeros((H, W), bool); walk[inside] = trav[gy[inside], gx[inside]]
    frame_check = round(float((lab[walk] > 0).mean()), 3) if walk.any() else None

    rooms = []
    for i, n in enumerate(names):
        m = lab == i + 1
        polys = []
        for c in measure.find_contours(np.pad(m, 1).astype(float), 0.5):
            c = measure.approximate_polygon(c, 1.0)
            if len(c) < 4:
                continue
            xs, ys = to_xy(c[:, 0] - 1, c[:, 1] - 1)
            if 0.5 * abs(np.dot(xs, np.roll(ys, 1)) - np.dot(ys, np.roll(xs, 1))) < 0.05:
                continue
            polys.append([[round(float(x), 3), round(float(y), 3)] for x, y in zip(xs[:-1], ys[:-1])])
        r0, c0 = np.argwhere(m).mean(0)
        g = ROOM_RE.match(n)
        rooms.append({"id": n, "type": g["type"] if g else n, "polygons": polys, "area_m2": round(float(m.sum()) * RES * RES, 2),
                      "centroid": [round(v, 3) for v in to_xy(r0, c0)], "polygon_source": poly_source[n]})

    # Where the nav graph steps from one room into another IS the doorway/opening: those edge midpoints place the markers.
    crossings: dict[tuple, list] = {}
    ng_path = sd / "nav_graph.json"
    if ng_path.is_file():
        ng = json.loads(ng_path.read_text())
        pos = {n["id"]: n["world"] for n in ng.get("nodes", [])}
        # floors can stop short of the wall centre, leaving a gap under the wall: a nav step then goes room -> gap -> room and
        # never room -> room. Gap pixels within 0.4 m take the nearest room's label for this test only.
        dist, (ir, ic) = ndi.distance_transform_edt(lab == 0, return_indices=True)
        filled = np.where(dist * RES <= 0.4, lab[ir, ic], 0)
        def label_at(xy):
            c, r = int((xy[0] - ox) / RES), int((xy[1] - oy) / RES)
            return int(filled[r, c]) if 0 <= r < H and 0 <= c < W else 0
        for e in ng.get("edges", []):
            u, v = (e.get("source"), e.get("target")) if isinstance(e, dict) else (e[0], e[1])
            if u not in pos or v not in pos:
                continue
            la, lb = label_at(pos[u]), label_at(pos[v])
            if la and lb and la != lb:
                crossings.setdefault(tuple(sorted((names[la - 1], names[lb - 1]))), []).append(
                    [(pos[u][0] + pos[v][0]) / 2, (pos[u][1] + pos[v][1]) / 2])
    edges, solve_src = solve_state_edges(sd)
    grow = int(round(0.35 / RES))                       # bridges the wall gap between two rooms' floor meshes
    dil = {i: ndi.binary_dilation(lab == i + 1, iterations=grow) for i in range(len(names))}
    conns = []
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            band = dil[a] & dil[b] & ~((lab > 0) & (lab != a + 1) & (lab != b + 1))
            if band.sum() * RES * RES < 0.05:
                continue
            # the crossable stretch is read in the thin strip at the wall only: the traversable grid is inset from walls by the
            # robot radius, so within ~0.15 m of both floors only a doorway/opening is walkable (0.35 m caught room interiors)
            near = ndi.binary_dilation(lab == a + 1, iterations=3) & ndi.binary_dilation(lab == b + 1, iterations=3)
            passable = (near if near.any() else band) & walk
            pair = tuple(sorted((names[a], names[b])))
            kind = edges.get(pair)
            if passable.sum() < 4 and kind is None and not crossings.get(pair):
                continue                                     # they share a wall, nothing crosses it (grid or nav graph)
            pts = np.argwhere(passable if passable.sum() >= 4 else band)
            width = float(np.ptp(pts[:, 0]) if np.ptp(pts[:, 0]) > np.ptp(pts[:, 1]) else np.ptp(pts[:, 1])) * RES
            if solve_src is not None and kind is None:
                continue                                     # the generator says Wall: no passage, whatever the grid shows
            cross = np.array(crossings.get(pair, []))
            if len(cross):
                width = float(max(np.ptp(cross[:, 0]), np.ptp(cross[:, 1]))) + 0.1   # node spacing ~ one grid step
            src = "solve_state" if kind else "inferred_from_passage_width"
            kind = kind or ("Door" if width <= 1.2 else "Open")
            mid = cross.mean(0) if len(cross) else np.array(to_xy(*pts[np.argmin(((pts - pts.mean(0)) ** 2).sum(1))]))   # a contact pixel, not the mean of two wall stretches
            conns.append({"rooms": list(pair), "kind": kind, "kind_source": src,
                          "midpoint": [round(float(v), 3) for v in mid], "midpoint_source": "nav_graph_crossings" if len(cross) else "floor_contact",
                          "passage_width_m": round(width, 2)})
    return {"schema": "robomituba.room_map.v1", "scene_id": scene, "frame": FRAME, "units": "m",
            "rooms": rooms, "connections": conns,
            "provenance": {"floors": "xml_scene_index.json <room>.floor meshes", "room_graph": solve_state_src_or(solve_src),
                           "frame_check_traversable_inside_rooms": frame_check},
            "_raster": {"origin_xy": [round(float(ox), 3), round(float(oy), 3)], "m_per_px": RES, "size_px": [W, H]}}


def solve_state_src_or(src):
    return src or "missing (generator output deleted): connections from the traversable grid, kind inferred from passage width"


def preview(rm: dict, out_png: Path, m_per_px: float = 0.02):
    import cv2
    pts = np.array([p for r in rm["rooms"] for poly in r["polygons"] for p in poly])
    ox, oy = pts.min(0) - 0.5; W, H = (np.ptp(pts, 0) + 1.0) / m_per_px
    W, H = int(W), int(H)
    img = np.full((H, W, 3), 250, np.uint8)
    palette = {"living-room": (182, 215, 168), "kitchen": (153, 204, 255), "dining-room": (128, 191, 255), "bedroom": (230, 190, 200),
               "bathroom": (240, 220, 150), "closet": (200, 200, 200), "hallway": (220, 220, 205), "balcony": (190, 230, 230),
               "utility": (210, 200, 230), "garage": (180, 180, 180)}
    px = lambda x, y: (int((x - ox) / m_per_px), int(H - (y - oy) / m_per_px))   # y up on screen, like the sim's R2R view
    for r in rm["rooms"]:
        for poly in r["polygons"]:
            a = np.array([px(x, y) for x, y in poly], np.int32)
            cv2.fillPoly(img, [a], palette.get(r["type"], (215, 215, 215))); cv2.polylines(img, [a], True, (60, 60, 60), 2)
    for c in rm["connections"]:
        cv2.circle(img, px(*c["midpoint"]), 7, (40, 40, 200) if c["kind"] == "Door" else (40, 150, 40), -1)
    for r in rm["rooms"]:
        x, y = px(*r["centroid"]); cv2.putText(img, f'{r["type"]} {r["area_m2"]:.0f}', (x - 40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1)
    cv2.imwrite(str(out_png), img)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", action="append", required=True)
    ap.add_argument("--pack", type=Path, help="also copy room_map.json into <pack>/scenes/<scene>/")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--project", type=Path, help="OpticalNav project root (default out/opticalnav/opticalnav-v0.2)")
    a = ap.parse_args()
    global PROJECT, PACK
    PROJECT, PACK = a.project or PROJECT, a.pack or PACK
    for scene in a.scene:
        rm = build(scene)
        dst = PROJECT / "scenes" / scene / "room_map.json"
        tmp = dst.with_suffix(".json.tmp"); tmp.write_text(json.dumps(rm, indent=1)); os.replace(tmp, dst)
        if a.preview:
            preview(rm, dst.with_suffix(".png"))
        if a.pack:
            pdst = a.pack / "scenes" / scene / "room_map.json"
            if pdst.parent.is_dir():
                shutil.copyfile(dst, pdst)
        n_door = sum(c["kind"] == "Door" for c in rm["connections"])
        print(json.dumps({"scene": scene, "rooms": len(rm["rooms"]), "connections": len(rm["connections"]), "door": n_door,
                          "frame_check": rm["provenance"]["frame_check_traversable_inside_rooms"],
                          "room_graph": "solve_state" if rm["provenance"]["room_graph"].endswith(".json") else "inferred"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
