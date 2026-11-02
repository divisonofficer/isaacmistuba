"""Library task / conference chairs (P4, O4 external review: 'the fabric task chairs are smooth single-colour lumps, the single highest-impact asset'). ROOM_TASK_CHAIR_LIB=1 makes realize._cls return these for
proc:TaskChairFactory (desk / task chairs) and, with ROOM_CONF_CHAIR_LIB=1, proc:ConferenceChairFactory (meeting chairs).

  LibTaskChairFactory   Office Hippo ergonomic (ABO B06W5XBL3D, 70 %) or AmazonBasics Office Chair (B016ID34BO, 30 %); +-15 deg yaw and +-10 cm are applied by the placer / usage_realism, a few chairs are pushed back by the plan's pose
  LibConfChairFactory   HSSD Margot (white upholstered)
The model is imported once (abo_assets caches the mesh, so copies are linked duplicates: <= 2 prototypes per factory), its FRONT found from the geometry (the backrest is the mass of vertices above 55 % height, off the base
centre: the front is the opposite side, snapped to a multiple of 90 deg) and turned to +X, feet on z = 0, origin at the footprint centre, scaled to a 0.95 m seat-back chair if it is smaller than that. Object name
'TaskChairFactory(<i>).spawn_asset(<i>)' so every pass keyed on that name still sees it."""
from __future__ import annotations

import math
import random

import bpy
from mathutils import Matrix, Vector

import abo_assets
import asset_pools

TASK = (("B06W5XBL3D", 0.7), ("B016ID34BO", 0.3))
CONF = (("HSSD_005b673d5ded782d54b", 1.0),)
_front_done = {}


def _entry(prefix):
    for e in asset_pools._entries():
        if e["id"].startswith(prefix):
            return e
    return None


def _orient(o, key):
    me = o.data
    if me.get("ir_chair_ok"):
        return
    vs = [v.co.copy() for v in me.vertices]
    zs = [v.z for v in vs]; z0, z1 = min(zs), max(zs); h = z1 - z0
    cx = (min(v.x for v in vs) + max(v.x for v in vs)) / 2; cy = (min(v.y for v in vs) + max(v.y for v in vs)) / 2
    hi = [v for v in vs if v.z > z0 + 0.55 * h]
    bx = sum(v.x for v in hi) / len(hi) - cx; by = sum(v.y for v in hi) / len(hi) - cy
    ang = math.atan2(-by, -bx) if (abs(bx) + abs(by)) > 0.01 else 0.0              # front direction = away from the back mass
    ang = round(ang / (math.pi / 2)) * (math.pi / 2)
    me.transform(Matrix.Rotation(-ang, 4, "Z"))                                       # front -> +X
    vs = [v.co for v in me.vertices]
    me.transform(Matrix.Translation(Vector((-(min(v.x for v in vs) + max(v.x for v in vs)) / 2, -(min(v.y for v in vs) + max(v.y for v in vs)) / 2, -min(v.z for v in vs)))))
    me["ir_chair_ok"] = 1


def _make(pick, seed, i):
    r = random.Random(seed)
    pid = r.choices([p for p, _ in pick], [w for _, w in pick])[0]
    e = _entry(pid)
    if e is None:
        raise RuntimeError(f"chair model {pid} not in the pools")
    o = abo_assets._import(e, f"TaskChairFactory({i}).spawn_asset({i})")
    o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, 0)
    _orient(o, pid)
    return o


class LibTaskChairFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        return _make(TASK, self.seed, i)


class LibConfChairFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        return _make(CONF, self.seed, i)
