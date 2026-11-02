"""Shared shop-front fix (S38 r15 SUB2 review, also S37): ROOM_SHOPFRONT_FIX=1 (kit stage, idempotent via scene["ir_shopfront_fix"]); liq_shell's door / street parts call the same functions.
door    the opaque angled PanelDoor leaf goes; a black-framed full-glass swing leaf hinged at the opening's left jamb, open 90 deg outwards, long bar handle
street  the big_glass card shows ROOM_SHOPFRONT_PLATE (bigglass_cards/src/<name>.png, default env_office_ct_04: glass offices + trees); 300 mm concrete paving 3.5 m deep, a granite kerb, asphalt beyond,
        two black planters with real (plant_lib2) plants by the door
Room bbox from ROOM_SHOPFRONT_ROOM (default break-room_0/0)."""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

def door(stats):
    """S38 r15 review: the shop door was an opaque dark leaf at an angle. A black-framed full-glass swing leaf, hinged at the opening's left jamb and open 90 deg outwards, with a long bar handle."""
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    old = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("PanelDoorFactory")]
    cas = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("DoorCasingFactory")]
    if not cas:
        return
    b0 = [min((cas[0].matrix_world @ Vector(c))[i] for c in cas[0].bound_box) for i in range(3)]; b1 = [max((cas[0].matrix_world @ Vector(c))[i] for c in cas[0].bound_box) for i in range(3)]
    def _near(o):                                                           # S37 r16: S37's leaf is a LiteDoorFactory (glazed panel) left standing open inside next to the new glass leaf: drop any leaf in this opening
        q = [o.matrix_world @ Vector(c) for c in o.bound_box]; cx_, cy_ = sum(p.x for p in q) / 8, sum(p.y for p in q) / 8
        return b0[0] - 0.3 <= cx_ <= b1[0] + 0.3 and abs(cy_ - (b0[1] + b1[1]) / 2) < 1.6
    old += [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("LiteDoorFactory") and _near(o)]
    for o in old:
        bpy.data.objects.remove(o, do_unlink=True)
    x0 = b0[0] + 0.1; w = (b1[0] - b0[0]) - 0.2; h = b1[2] - b0[2] - 0.15; yw = (b0[1] + b1[1]) / 2; z0 = b0[2]
    blk = pa._flat("ir_liq_door_frame", (0.02, 0.02, 0.022), 0.35, 1.0); gl = pa._flat("ir_liq_door_glass", (0.85, 0.9, 0.92), 0.02, transmission=0.95); gl["weathered"] = True
    t, f_ = 0.045, 0.05                                                     # leaf along -y from the hinge at (x0, yw): open outwards, 90 deg
    ya, yb = yw - w, yw
    fr = [("box", x0, (ya + yb) / 2, z0 + f_ / 2, t, w, f_), ("box", x0, (ya + yb) / 2, z0 + h - f_ / 2, t, w, f_), ("box", x0, ya + f_ / 2, z0 + h / 2, t, f_, h), ("box", x0, yb - f_ / 2, z0 + h / 2, t, f_, h),
          ("box", x0, (ya + yb) / 2, z0 + 0.15, t, w, 0.2)]                                        # kick rail
    hd = [("cyl", (x0 + 0.06, ya + 0.12, z0 + 0.7), (x0 + 0.06, ya + 0.12, z0 + 1.5), 0.014, 12)] + [("box", x0 + 0.04, ya + 0.12, z, 0.04, 0.02, 0.02) for z in (z0 + 0.75, z0 + 1.45)]
    fl.mesh_object("LiqGlassDoor", [(blk, fr + hd), (gl, [("box", x0, (ya + yb) / 2, z0 + 0.25 + (h - 0.3) / 2, 0.012, w - 2 * f_, h - 0.3)])])
    stats["liq_door"] = 1


def street(lo, hi, stats):
    """S38 r15 review: outside read as a Parisian stone street on a grey noise slab. The window card shows a bright modern street of glass offices and trees (env_office_ct_04); the ground in front is
    300 mm grey concrete paving, a granite kerb 3.5 m out, asphalt beyond, and two planters with real plants by the door."""
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    k = 0
    for m in [s_.material for o in bpy.data.objects if o.name.startswith("BigGlassCardFactory") for s_ in o.material_slots if s_.material]:
        for nd in m.node_tree.nodes:
            if nd.type == "TEX_IMAGE":
                nd.image = bpy.data.images.load(f"/jarvis/project/robomituba/data/venue_refs/bigglass_cards/src/{os.environ.get('ROOM_SHOPFRONT_PLATE') or 'env_office_ct_04'}.png", check_existing=True); k += 1
    pav = bpy.data.materials.get("ir_liq_paving")
    if pav is None:
        pav = pa._flat("ir_liq_paving", (0.55, 0.55, 0.53), 0.75); pav["weathered"] = True
        nt = pav.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
        br.offset = 0.5; br.inputs["Scale"].default_value = 3.3; br.inputs["Mortar Size"].default_value = 0.006; br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0
        br.inputs["Color1"].default_value = (0.58, 0.58, 0.56, 1); br.inputs["Color2"].default_value = (0.5, 0.5, 0.48, 1); br.inputs["Mortar"].default_value = (0.3, 0.3, 0.29, 1)
        L.new(br.outputs["Color"], b.inputs["Base Color"])
    asph = pa._flat("ir_liq_asphalt", (0.16, 0.16, 0.17), 0.85); kerb = pa._flat("ir_liq_kerb", (0.62, 0.61, 0.6), 0.7)
    for o in [o for o in bpy.data.objects if o.name.startswith("BigGlassGroundFactory")]:
        o.location.z -= 0.003
    X0, X1 = lo[0] - 30, hi[0] + 30
    fl.mesh_object("LiqStreet", [(pav, [("box", (X0 + X1) / 2, -1.75, 0.0, X1 - X0, 3.5, 0.02)]), (kerb, [("box", (X0 + X1) / 2, -3.57, 0.02, X1 - X0, 0.15, 0.13)]),
                                 (asph, [("box", (X0 + X1) / 2, -9.8, -0.03, X1 - X0, 12.3, 0.02)])], bevel=False)
    np_ = 0
    try:
        from room_planner import plant_lib2
        pot = pa._flat("ir_liq_planter", (0.1, 0.1, 0.11), 0.45)
        for i, x in enumerate((lo[0] + 0.6, lo[0] + 3.6)):
            fl.mesh_object(f"LiqPlanter{i}", [(pot, [("box", x, -0.6, 0.3, 0.5, 0.5, 0.6)])])
            pl = plant_lib2.plant("floor", 90 + i, i, h=1.3)
            if pl is not None:
                pl.location = (x, -0.6, 0.6); np_ += 1
    except Exception:                                                       # noqa: BLE001 -- a plant is an extra
        pass
    stats["liq_street"] = {"card_images": k, "planters": np_}




def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def apply(stats):
    sc = bpy.context.scene
    f = bpy.data.objects.get(f"{os.environ.get('ROOM_SHOPFRONT_ROOM') or 'break-room_0/0'}.floor")
    if sc.get("ir_shopfront_fix") or f is None:
        return 0
    lo, hi = _bb(f)
    for key, fn in (("door", lambda: door(stats)), ("street", lambda: street(lo, hi, stats))):
        try:
            fn()
        except Exception as ex:                                  # noqa: BLE001
            stats[f"shopfront_{key}_error"] = repr(ex)[:160]
    sc["ir_shopfront_fix"] = 1
    return 1
