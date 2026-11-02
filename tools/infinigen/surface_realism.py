"""Surface realism pass (user review 10-23, S32 ramen vs S34 LP cafe: 'clean models with textures', every material responds to light alike). Hooked from kit_lighting, LAST of the material passes:

    import surface_realism; stats["surface_realism"] = surface_realism.apply(stats)        only when ROOM_SURFACE_REALISM=1

Everything is done INSIDE the materials (Principled inputs + a few nodes), so the roughness / normal / albedo GT channels, which read the same shader, carry the variation. Per material class:
  wood      roughness ~0.32 (+ grain-correlated: darker grain = rougher), coat 0.25 / coat roughness 0.15, grain-scale bump
  plaster   roughness ~0.78 (paint / wall / ceiling), a faint roller-scale variation
  tile      roughness ~0.15 (glazed), per-tile colour +-2.5 % and roughness +-0.03 from a world-space brick cell id (ROOM_REAL_TILE = tile edge m, default 0.15; cells are not aligned to the
            modelled tile lines unless the size matches), grout recessed + rougher only with ROOM_REAL_GROUT=1
  metal     metallic 1, roughness ~0.22, anisotropic 0.45 (brushed)
  other     macro variation only; fabric / glass / emissive / alpha materials are left alone
Variation on every touched material, three scales in world space: ~1 m patches (+-0.06), 5-10 cm wipe marks (+-0.035, stretched), sub-mm micro normal (bump 0.04). A shader Bevel node (ROOM_REAL_BEVEL m, default 0.0015, 0 = off) rounds
every edge for the specular line and the contact look.
Glossy-black cue (ROOM_REAL_GLOSS_BLACK=1): materials whose name contains black / lacquer / menu / tray at colour < 0.06 get roughness 0.07 + coat 1 (black menu boards, lacquer trays, counter-front bands).
Grease (ROOM_REAL_GREASE=1): finer greasy smears (~1.5 cm, +0.08 roughness; halved in r16) and fingerprint blobs (+0.05) on the metal class (stainless kitchens; S32 r15 R6).
Directional daylight (ROOM_REAL_SUN=W_per_m2, default off; 250 is a bright day): one warm area light just inside every big window / glass wall, facing into the room (the ROOM_ENV_WINDOWS street card shows outside).
Other env: ROOM_REAL_AMP (default 1, scales all variation)   ROOM_REAL_CLASSES=wood,plaster,tile,metal (subset; default all)   ROOM_REAL_SKIP=substr,substr (material-name substrings left untouched)
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

TARGET = {"wood": 0.32, "plaster": 0.78, "tile": 0.15, "metal": 0.22, "grout": 0.8}


def _classify(m, b):
    n = m.name.lower()
    met = b.inputs["Metallic"]
    if not met.links and met.default_value > 0.5 or any(k in n for k in ("steel", "chrome", "brass", "alumin", "metal")) and not any(k in n for k in ("metallic_paint",)):
        return "metal"
    if any(k in n for k in ("fabric", "cloth", "carpet", "felt", "leather", "foam", "curtain", "rug", "linen", "duvet", "throw", "pillow", "upholster", "blanket", "headboard", "bedding", "sheet_")):
        return "fabric"
    if "grout" in n:
        return "grout"
    if any(k in n for k in ("wood", "oak", "timber", "plank", "walnut", "birch", "veneer", "parquet", "amber", "slat")):
        return "wood"
    if any(k in n for k in ("tile", "ceramic", "glaze", "porcelain")):
        return "tile"
    if any(k in n for k in ("plaster", "paint", "wall", "ceiling", "stucco")):
        return "plaster"
    return "other"


def _skip(m, b, ignore_done=False):
    n = m.name.lower()
    if any(s for s in (os.environ.get("ROOM_REAL_SKIP") or "").split(",") if s and s in n) or ("ir_real" in m and not ignore_done):
        return True
    if any(k in n for k in ("glass", "emiss", "light", "screen", "mirror", "water", "sky", "backdrop", "card", "photo", "ir_bg_")):
        return True
    for k in ("Transmission Weight", "Emission Strength"):
        s = b.inputs.get(k)
        if s is not None and not s.links and s.default_value > (0.5 if k.startswith("Trans") else 0.01):
            return True
    a = b.inputs.get("Alpha")
    return a is not None and (a.links or a.default_value < 0.99)


def _noise(N, vec, scale, detail=3.0, rough=0.55):
    t = N.new("ShaderNodeTexNoise"); t.inputs["Scale"].default_value = scale; t.inputs["Detail"].default_value = detail; t.inputs["Roughness"].default_value = rough
    return t


def _stretch(N, L, pos, scale):
    mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = scale; L.new(pos, mp.inputs["Vector"]); return mp


def _centered(N, L, sock, amp):
    """(sock - 0.5) * 2 * amp as a float socket."""
    m = N.new("ShaderNodeMath"); m.operation = "SUBTRACT"; L.new(sock, m.inputs[0]); m.inputs[1].default_value = 0.5
    k = N.new("ShaderNodeMath"); k.operation = "MULTIPLY"; L.new(m.outputs[0], k.inputs[0]); k.inputs[1].default_value = 2.0 * amp
    return k.outputs[0]


def _add(N, L, a, b):
    s = N.new("ShaderNodeMath"); s.operation = "ADD"
    for q, x in enumerate((a, b)):
        if isinstance(x, (int, float)):
            s.inputs[q].default_value = x
        else:
            L.new(x, s.inputs[q])
    return s.outputs[0]


def _real(m, cls, amp, tile, bevel, grout, gloss_black):
    nt = m.node_tree; N, L = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        return False
    geo = N.new("ShaderNodeNewGeometry"); pos = geo.outputs["Position"]
    rin = b.inputs["Roughness"]
    old = rin.links[0].from_socket if rin.links else None
    base = rin.default_value
    for l in list(rin.links):
        L.remove(l)
    tgt = TARGET.get(cls) if cls != "fabric" else 0.88
    bc = b.inputs["Base Color"]
    # ---- roughness: class target + remapped original + three scales of variation
    if gloss_black:
        r0 = 0.07
    elif tgt is not None:
        r0 = tgt
    else:
        r0 = None
    if r0 is not None:
        expr = r0 if old is None else _add(N, L, r0, _centered(N, L, old, 0.25))                  # keep half the original spread (grain / pattern roughness)
    else:
        expr = base if old is None else old
    macro = _noise(N, pos, 1.0, 3.0); L.new(pos, macro.inputs["Vector"])
    wipe = _noise(N, pos, 1.0, 2.0); L.new(_stretch(N, L, pos, (14.0, 14.0, 70.0)).outputs["Vector"], wipe.inputs["Vector"])
    var = _add(N, L, _centered(N, L, macro.outputs["Fac"], 0.06 * amp), _centered(N, L, wipe.outputs["Fac"], 0.035 * amp))
    if cls == "wood" and bc.links:                                                                   # grain-correlated: dark grain rougher
        bw = N.new("ShaderNodeRGBToBW"); L.new(bc.links[0].from_socket, bw.inputs["Color"])
        var = _add(N, L, var, _centered(N, L, bw.outputs["Val"], -0.12 * amp))
    if cls == "tile":
        br = N.new("ShaderNodeTexBrick"); br.inputs["Color1"].default_value = (0.4, 0.4, 0.4, 1); br.inputs["Color2"].default_value = (0.6, 0.6, 0.6, 1); br.inputs["Mortar Size"].default_value = 0.012
        br.inputs["Scale"].default_value = 1.0 / max(tile, 0.02); br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0; br.offset = 0.0
        L.new(pos, br.inputs["Vector"])
        sp = N.new("ShaderNodeSeparateColor"); L.new(br.outputs["Color"], sp.inputs["Color"])
        var = _add(N, L, var, _centered(N, L, sp.outputs["Red"], 0.3 * amp))                        # +-0.03 per tile
        if bc.links or True:
            cd = N.new("ShaderNodeMath"); cd.operation = "MULTIPLY_ADD"; L.new(_centered(N, L, sp.outputs["Red"], 1.0), cd.inputs[0]); cd.inputs[1].default_value = 0.025 * amp; cd.inputs[2].default_value = 1.0
            mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1.0
            cv = N.new("ShaderNodeCombineColor"); [L.new(cd.outputs[0], cv.inputs[k]) for k in range(3)]
            if bc.links:
                src = bc.links[0].from_socket
                for l in list(bc.links):
                    L.remove(l)
                L.new(src, mix.inputs["A"])
            else:
                mix.inputs["A"].default_value = bc.default_value
            L.new(cv.outputs["Color"], mix.inputs["B"]); L.new(mix.outputs["Result"], bc)
        if grout:
            mort = N.new("ShaderNodeMath"); mort.operation = "LESS_THAN"; L.new(br.outputs["Fac"], mort.inputs[0]); mort.inputs[1].default_value = 0.5
            var = _add(N, L, var, _scale(N, L, mort.outputs[0], 0.5))
    if cls == "metal" and os.environ.get("ROOM_REAL_GREASE") == "1":                                  # usage on stainless: greasy smears (broad, long) and fingerprints (small blobs) raise the roughness locally
        sm = _noise(N, pos, 1.0, 2.0); L.new(_stretch(N, L, pos, (70.0, 70.0, 16.0)).outputs["Vector"], sm.inputs["Vector"])
        g1 = N.new("ShaderNodeMath"); g1.operation = "GREATER_THAN"; L.new(sm.outputs["Fac"], g1.inputs[0]); g1.inputs[1].default_value = 0.6
        fp = _noise(N, pos, 140.0, 1.0, 0.7); L.new(pos, fp.inputs["Vector"])
        g2 = N.new("ShaderNodeMath"); g2.operation = "GREATER_THAN"; L.new(fp.outputs["Fac"], g2.inputs[0]); g2.inputs[1].default_value = 0.68
        var = _add(N, L, var, _add(N, L, _scale(N, L, g1.outputs[0], 0.08 * amp), _scale(N, L, g2.outputs[0], 0.05 * amp)))
    final = _add(N, L, expr, var)
    cl = N.new("ShaderNodeClamp"); cl.inputs["Min"].default_value = 0.03; cl.inputs["Max"].default_value = 1.0; L.new(final, cl.inputs["Value"]); L.new(cl.outputs["Result"], rin)
    # ---- coat / metal / anisotropy
    if gloss_black:
        for k, v in (("Coat Weight", 1.0), ("Coat Roughness", 0.05)):
            if k in b.inputs and not b.inputs[k].links:
                b.inputs[k].default_value = v
    elif cls == "wood":
        if not b.inputs["Coat Weight"].links:
            b.inputs["Coat Weight"].default_value = max(b.inputs["Coat Weight"].default_value, 0.25)
        if not b.inputs["Coat Roughness"].links:
            b.inputs["Coat Roughness"].default_value = 0.15
    elif cls == "fabric":
        if "Sheen Weight" in b.inputs and not b.inputs["Sheen Weight"].links:
            b.inputs["Sheen Weight"].default_value = 0.35; b.inputs["Sheen Roughness"].default_value = 0.5
    elif cls == "metal":
        if not b.inputs["Metallic"].links:
            b.inputs["Metallic"].default_value = 1.0
        if "Anisotropic" in b.inputs and not b.inputs["Anisotropic"].links:
            b.inputs["Anisotropic"].default_value = 0.45
    # ---- micro normal (sub-mm) then the shader bevel, chained on whatever normal the material already had
    nin = b.inputs["Normal"]; src_n = nin.links[0].from_socket if nin.links else None
    micro = _noise(N, pos, 700.0, 2.0, 0.6); L.new(pos, micro.inputs["Vector"])
    bm = N.new("ShaderNodeBump"); bm.inputs["Strength"].default_value = 0.04 * amp if cls != "wood" else 0.07 * amp; bm.inputs["Distance"].default_value = 0.0004
    h_ = micro.outputs["Fac"]
    if cls == "fabric":                                                                              # woven cloth: two crossed thread bands ~0.8 mm apart
        ws = []
        for d_ in ("X", "Y"):
            w_ = N.new("ShaderNodeTexWave"); w_.wave_type = "BANDS"; w_.bands_direction = d_; w_.inputs["Scale"].default_value = 1250.0; w_.inputs["Distortion"].default_value = 1.5; w_.inputs["Detail"].default_value = 0.0
            L.new(pos, w_.inputs["Vector"]); ws.append(w_.outputs["Fac"])
        h_ = _scale(N, L, _add(N, L, ws[0], ws[1]), 0.5); bm.inputs["Strength"].default_value = 0.35 * amp
    elif cls == "plaster":                                                                           # roller / orange-peel: faint vertical streaks (features long in z) + a fine stipple
        rl = _noise(N, pos, 1.0, 2.0); L.new(_stretch(N, L, pos, (90.0, 90.0, 5.0)).outputs["Vector"], rl.inputs["Vector"])
        h_ = _add(N, L, _scale(N, L, h_, 0.5), _scale(N, L, rl.outputs["Fac"], 0.5)); bm.inputs["Strength"].default_value = 0.07 * amp; bm.inputs["Distance"].default_value = 0.0006
    L.new(h_, bm.inputs["Height"])
    if src_n is not None:
        L.new(src_n, bm.inputs["Normal"])
    out_n = bm.outputs["Normal"]
    if bevel > 0 and cls != "fabric":
        bv = N.new("ShaderNodeBevel"); bv.inputs["Radius"].default_value = bevel; bv.samples = 4; L.new(out_n, bv.inputs["Normal"]); out_n = bv.outputs["Normal"]
    L.new(out_n, nin)
    m["ir_real"] = cls
    return True


def _scale(N, L, sock, k):
    m = N.new("ShaderNodeMath"); m.operation = "MULTIPLY"; L.new(sock, m.inputs[0]); m.inputs[1].default_value = k
    return m.outputs[0]


def _windows():
    """Big window / glass-wall objects: (centre, width, height, inward normal)."""
    fl = [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor")]
    if not fl:
        return []
    cen = Vector((0, 0, 0))
    for o in fl:
        cen += o.matrix_world @ Vector((sum(c[i] for c in o.bound_box) / 8.0 for i in range(3)))
    cen /= len(fl)
    out = []
    for o in bpy.data.objects:
        n = o.name.lower()
        if o.type != "MESH" or not any(k in n for k in ("window", "bigglass", "glasswall", "glass_wall")) or "frame" in n or "card" in n:
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
        dx, dy, dz = max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)
        w = max(dx, dy); thin = min(dx, dy)
        if w < 1.0 or dz < 0.8 or thin > 0.4:
            continue
        c = Vector(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(zs) + min(zs)) / 2))
        nrm = Vector((0, 1, 0)) if dx >= dy else Vector((1, 0, 0))
        if (cen - c).dot(nrm) < 0:
            nrm = -nrm
        out.append((c, w, dz, nrm))
    return out


def _sun(w_per_m2):
    n = 0
    for c, w, h, nrm in _windows():
        li = bpy.data.lights.new("ir_real_sun", "AREA"); li.shape = "RECTANGLE"; li.size = w; li.size_y = h
        li.energy = min(w_per_m2 * w * h, 4000.0); li.color = (1.0, 0.93, 0.82); li.spread = 1.05
        o = bpy.data.objects.new("ir_real_sun", li); bpy.context.scene.collection.objects.link(o)
        o.location = c + nrm * 0.12; o.rotation_euler = (-nrm).to_track_quat("Z", "Y").to_euler()          # an area light shines along its -Z: -Z must point INTO the room (= nrm)
        o.rotation_euler = nrm.to_track_quat("-Z", "Y").to_euler()
        o["src"] = "arch:surface_realism"; n += 1
    return n


def apply(stats):
    if os.environ.get("ROOM_SURFACE_REALISM") != "1":
        return {}
    amp = float(os.environ.get("ROOM_REAL_AMP") or 1.0); tile = float(os.environ.get("ROOM_REAL_TILE") or 0.15)
    bevel = float(os.environ.get("ROOM_REAL_BEVEL") or 0.0015); grout = os.environ.get("ROOM_REAL_GROUT") == "1"
    only = tuple(x for x in (os.environ.get("ROOM_REAL_CLASSES") or "wood,plaster,tile,metal,grout,fabric,other").split(",") if x)
    gb = os.environ.get("ROOM_REAL_GLOSS_BLACK") == "1"
    used = {}
    for o in bpy.data.objects:
        if o.type == "MESH":
            for ms in o.material_slots:
                if ms.material is not None and ms.material.use_nodes:
                    used.setdefault(ms.material, 0); used[ms.material] += 1
    out = {"wood": 0, "plaster": 0, "tile": 0, "metal": 0, "grout": 0, "other": 0, "fabric": 0, "gloss_black": 0, "skipped": 0}
    for m in list(used):
        b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None or _skip(m, b):
            out["skipped"] += 1; continue
        cls = _classify(m, b)
        if m.get("tile_floor") or m.get("herringbone") or m.get("carpet"):          # a floor finish another pass built (tile_floor / herringbone / carpet) keeps its own roughness and tile layout: only the 3-scale variation + micro normal + bevel are added
            cls = "other"
        if cls == "fabric" and os.environ.get("ROOM_REAL_FABRIC", "1") == "0":
            out["fabric"] += 1; continue
        lum = sum(b.inputs["Base Color"].default_value[:3]) / 3.0 if not b.inputs["Base Color"].links else 1.0
        blk = gb and lum < 0.06 and any(k in m.name.lower() for k in ("black", "lacquer", "menu", "tray")) and cls != "metal"
        if cls not in only and not blk:
            continue
        if _real(m, cls, amp, tile, bevel, grout, blk):
            out[cls] += 1; out["gloss_black"] += int(blk)
    sun = float(os.environ.get("ROOM_REAL_SUN") or 0)
    if sun > 0:
        out["sun_lights"] = _sun(sun)
    return out
