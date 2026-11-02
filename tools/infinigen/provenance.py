"""Provenance + reference-authoritative gating (user 2026-10-22: 'the planner keeps overwriting what was prepared from the reference').

Every object an add-pass creates gets the custom property  o["src"] :
    layout:<id>            a floor-plan layout item                    program:lived_in   the kit program's own lived_in
    plan:lived_in / plan:furniture / pass:<name>   planner and automatic passes (pass:required_zone, pass:fill_empty, pass:table_guard, pass:desk_clutter, pass:traces, pass:curtains, pass:plants,
                           pass:wall_art, pass:ceiling_fixtures, pass:art, pass:kit_stage ...)
A ROOM IS REFERENCE-AUTHORITATIVE when its plan carries "layout" (or "ref_authoritative": true). There, every dress pass that adds objects is OFF unless the kit allowlists it:
    room_program[room]["auto_allow"] = ["wall_art", "ceiling_fixtures", "window_curtains", "traces", ...]   (the pass names without the "pass:" prefix; "window_curtains" = pass:curtains)
Non-object things (lights, materials, weather, env windows) and architecture are never touched.

    configure(plans)                      read the authoritative rooms + allow lists from the plans.json dict
    span(name)                            context manager: tag objects created inside with src = "pass:<name>" (only those still untagged)
    gated(name, allow_key=None)           like span, then REMOVE the new mesh/empty objects standing in an authoritative room unless the room allows allow_key (default: name)
    write(path_prefix, stats=None)        <path_prefix>.provenance.json {rooms: {id: {added, non_reference, by_src}}, objects: [...]} and stats["provenance"] = per-room by_src
"""
from __future__ import annotations

import contextlib
import json
import re

import bpy
from mathutils import Vector

AUTH: dict[str, set] = {}                          # room id -> set(allowed pass keys)
ALIASES = {"curtains": "window_curtains", "art": "wall_art"}
_BOX: dict[str, tuple] = {}


def configure(plans):
    AUTH.clear(); _BOX.clear()
    for rid, e in (plans or {}).get("rooms", {}).items():
        p = (e or {}).get("plan") or {}
        if p.get("layout") or p.get("ref_authoritative"):
            AUTH[rid] = set(p.get("auto_allow") or [])
    return dict(AUTH)


def _room_boxes():
    if _BOX:
        return _BOX
    import room_dressing as rd
    for rid, parts in rd._rooms().items():
        fl = parts.get("floor")
        if fl is None:
            continue
        pts = [fl.matrix_world @ Vector(c) for c in fl.bound_box]
        _BOX[rid] = (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts))
    return _BOX


def room_of(o):
    rid = o.get("ir_room")
    if rid:
        return rid
    t = o.matrix_world.translation
    for k, (x0, x1, y0, y1) in _room_boxes().items():
        if x0 - 0.05 <= t.x <= x1 + 0.05 and y0 - 0.05 <= t.y <= y1 + 0.05:
            return k
    return None


def _names():
    return set(bpy.data.objects.keys())


@contextlib.contextmanager
def span(name):
    before = _names()
    try:
        yield
    finally:
        for k in _names() - before:
            o = bpy.data.objects.get(k)
            if o is not None and "src" not in o:
                o["src"] = "pass:" + name


_TAGDEPTH = [0]


@contextlib.contextmanager
def tag(src):
    """Tag the objects created inside with the full src string (layout:<id>, program:lived_in, plan:lived_in, pass:fill_empty ...). Nested tags: the OUTERMOST one wins (a lived_in item put down by the
    forced coffee-bar zone is 'pass:coffee_bar_zone', not 'plan:lived_in')."""
    outer = _TAGDEPTH[0] == 0
    _TAGDEPTH[0] += 1
    before = _names() if outer else None
    try:
        yield
    finally:
        _TAGDEPTH[0] -= 1
        if outer:
            for k in _names() - before:
                o = bpy.data.objects.get(k)
                if o is not None and "src" not in o:
                    o["src"] = src


def purge(room_ids):
    """Incremental rounds: remove the previous round's automatic dress objects (src = pass:*) that stand in these authoritative rooms and are not allowlisted. -> count removed."""
    n = 0
    bpy.context.view_layer.update()
    for o in list(bpy.data.objects):
        s = str(o.get("src", ""))
        if not s.startswith("pass:") or o.parent is not None or o.type in ("LIGHT", "CAMERA"):
            continue
        rid = room_of(o)
        if rid in room_ids and rid in AUTH and not _allowed(rid, s[5:]):
            for c in list(o.children_recursive):
                bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def _allowed(rid, key):
    return key in AUTH.get(rid, set()) or ALIASES.get(key, key) in AUTH.get(rid, set())


@contextlib.contextmanager
def gated(name, allow_key=None):
    before = _names()
    try:
        yield
    finally:
        key = allow_key or name
        new = [bpy.data.objects[k] for k in _names() - before if k in bpy.data.objects]
        if new:
            bpy.context.view_layer.update()                       # new objects' matrix_world must be current for the room lookup
        removed = 0
        for o in new:
            if "src" not in o:
                o["src"] = "pass:" + name
            if not AUTH or o.parent is not None or o.type in ("LIGHT", "CAMERA"):
                continue
            rid = room_of(o)
            if rid in AUTH and not _allowed(rid, key) and not str(o.get("src", "")).startswith(("layout:", "program:")):
                for c in list(o.children_recursive):
                    bpy.data.objects.remove(c, do_unlink=True)
                bpy.data.objects.remove(o, do_unlink=True); removed += 1
        if removed:
            print(f"[provenance] {name}: removed {removed} object(s) from reference-authoritative rooms", flush=True)


def write(path_prefix, stats=None):
    bpy.context.view_layer.update()
    rooms: dict[str, dict] = {}
    objs = []
    for o in bpy.data.objects:
        s = o.get("src")
        if not s or o.parent is not None and o.parent.get("src") == s:
            continue
        rid = room_of(o) or "?"
        r = rooms.setdefault(rid, {"added": 0, "non_reference": 0, "by_src": {}})
        key = re.sub(r"^layout:.*", "layout", str(s))
        r["by_src"][key] = r["by_src"].get(key, 0) + 1
        r["added"] += 1
        if rid in AUTH and o.type not in ("LIGHT", "CAMERA") and not str(s).startswith(("layout:", "program:", "arch:")):      # arch:* = openings / ceilings / lights the kit stage builds (not furniture or decor)
            r["non_reference"] += 1
        objs.append({"name": o.name, "src": str(s), "room": rid, "type": o.type})
    out = {"authoritative_rooms": {k: sorted(v) for k, v in AUTH.items()}, "rooms": rooms, "objects": objs}
    open(path_prefix + ".provenance.json", "w").write(json.dumps(out, indent=1))
    if stats is not None:
        stats["provenance"] = {k: v["by_src"] for k, v in rooms.items()}
        stats["non_reference_added"] = {k: v["non_reference"] for k, v in rooms.items() if k in AUTH}
    return out
