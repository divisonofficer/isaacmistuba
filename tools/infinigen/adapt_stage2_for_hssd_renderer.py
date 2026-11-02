#!/usr/bin/env python3
"""Make an Infinigen Stage-2 blend renderable by the HSSD renderer.

Writes a copy; the original is what this pipeline's own renderer uses and is
left exactly as it was. Three differences to reconcile, each read out of
modules/hssd_blender_ir/tools/blender_render_hssd_ir_sample.py rather than
guessed:

  1. `__ir_nir_flash` is a *controller* there, and `_flash()` toggles
     `hide_render` on its **children**. Here it is the flash light itself, so
     that loop finds nothing to toggle and the flash never turns on -- active
     NIR would come out identical to passive, silently. So: an empty takes the
     name, and the light becomes its child.
  2. The renderer wires `Combined_NIR_FLASH` off the render-layer node, which
     exists only once the light group is registered on the view layer. The
     lights already carry the group names; the view layer does not.
  3. It reads Depth, Normal and the three Diffuse passes.

Nine HSSD-only AOVs (GT_RoughnessRawGLTF, the four MR provenance masks,
GT_MRConfidence, the two *Effective channels, GT_GlassMask) are deliberately NOT
registered. GT_PBRInvalidMask and GT_LayerCount now ARE, built from this scene's
own materials -- see build_pbr_invalid_mask. An AOV registered with nothing
driving it renders as zeros, and a zeroed MRConfidence would read as a
measurement of this corpus rather than the absence of one. The renderer skips a
missing output (`if source is None: continue`) and writes no file, which is the
honest representation: the channel is absent, not zero.

Usage (inside Blender):
  blender --background <stage2.blend> --python-exit-code 1 \
    --python adapt_stage2_for_hssd_renderer.py -- --out <adapted.blend>
"""
from __future__ import annotations

import json
import math
import sys

import bpy
import mathutils

FLASH = "__ir_nir_flash"
LIGHT_GROUPS = ("NIR_FLASH", "DATASET_AMBIENT_FILL")


# `_closeup_target_objects` and `_frame_content` both gate on two custom
# properties the HSSD builder writes: role "interior_asset" and a non-empty
# `hssd_source_id`. Nothing in an Infinigen blend carries them, so every pose
# mode that picks its subject from the scene finds an empty candidate set and
# raises. Tagging is the whole fix -- the geometry was always eligible.
OPENING_TOKENS = ("door", "window")
# Same tuple as ir_view_utility.STRUCTURAL, minus the two above: shell geometry
# must not become a closeup subject, and must not count as foreground evidence.
STRUCTURE_TOKENS = ("wall", "floor", "ceiling", "exterior", "room", "staircase", "stair")


def _role(name: str) -> str | None:
    low = name.lower()
    if any(token in low for token in OPENING_TOKENS):
        return "opening"
    if any(token in low for token in STRUCTURE_TOKENS):
        return None
    return "interior_asset"


def tag_asset_roles() -> dict:
    """Give Infinigen meshes the HSSD role/source properties, by name."""
    counts = {"interior_asset": 0, "opening": 0, "structure": 0}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        role = _role(obj.name)
        if role is None:
            counts["structure"] += 1
            obj["hssd_asset_role"] = "structure"
            continue
        obj["hssd_asset_role"] = role
        # Infinigen names read `SomeFactory(12345).spawn_asset(678)`; the factory
        # is the stable identity across instances, which is what source_id means
        # on the HSSD side, and the full name is unique per instance.
        obj["hssd_source_id"] = obj.name.split("(")[0] or obj.name
        obj["hssd_instance_id"] = obj.name
        counts[role] += 1
    return counts


# `_ambient_band()` rewrites every ambient light each pass from two properties
# on the light DATA, and our Stage-2 fills carry neither:
#
#   ir_rgb_energy_w     the RGB-band wattage. Absent, the base falls back to
#                       `obj.data.energy` -- the LIVE value -- so the passive
#                       pass (scale 0.0) zeroes the lamp and the next frame's
#                       RGB pass then reads that zero as its base. The fill
#                       latches off after frame 0 and never comes back.
#   ir_nir_passive_scale  the 850-nm fraction. Absent, it defaults to 0.0 and
#                       the fill is multiplied out of the passive NIR pass.
#
# Writing the authored wattage into ir_rgb_energy_w restores the intent rather
# than inventing one. The NIR fraction is a physical claim, so it is a flag:
# HSSD's own policy is led 0.0 / incandescent 0.45 / daylight 0.75, and these
# synthetic ceiling fills stand in for the household lamps our Stage-2 prepare
# switched off, which is the incandescent class.
NIR_PASSIVE_SCALE_POLICY = {"led": 0.0, "incandescent": 0.45, "daylight": 0.75}


def declare_ambient_band(emitter_class: str) -> dict:
    """Give the ambient fills the two properties HSSD's _ambient_band reads."""
    scale = NIR_PASSIVE_SCALE_POLICY[emitter_class]
    touched = []
    for obj in bpy.context.scene.objects:
        if obj.type != "LIGHT" or not obj.data.get("ir_ambient_fill", False):
            continue
        # Read the wattage BEFORE anything can rewrite it, and only set the
        # property when it is missing, so re-running the adapter on an already
        # adapted blend cannot bake in a latched zero.
        if "ir_rgb_energy_w" not in obj.data.keys():
            obj.data["ir_rgb_energy_w"] = float(obj.data.energy)
        if "ir_nir_passive_scale" not in obj.data.keys():
            obj.data["ir_nir_passive_scale"] = scale
        touched.append({"name": obj.name, "rgb_energy_w": float(obj.data["ir_rgb_energy_w"]),
                        "nir_passive_scale": float(obj.data["ir_nir_passive_scale"])})
    return {"emitter_class": emitter_class, "nir_passive_scale": scale,
            "count": len(touched), "lights": touched[:3]}


# The day curriculum (T0_midday_clear .. T5_night_partial) already describes the
# illumination the corpus wants: a sun, a sky colour, window portals at
# 100 W/m^2 and room fixtures. `_lighting_variant()` runs once per frame BEFORE
# the RGB pass, so it reaches every band -- it just found nothing to drive here,
# because it matches on objects and properties an Infinigen blend has no reason
# to carry. Each one below is that renderer's own matcher, read out of it:
#
#   sun       an object literally named "__ir_sun" of type SUN
#   sky       the world's BACKGROUND node literally named "IR_Sky"
#   windows   data["ir_window_light"], scaled by data["ir_window_area_m2"]
#   fixtures  data["ir_fixture_light"], ordered by data["ir_fixture_index"]
#
# Windows and fixtures need no wattage from us: the variant supplies it and
# writes ir_rgb_energy_w itself, so they cannot latch the way the fills did.
SUN = "__ir_sun"
PORTAL_PREFIX = "__ir_external_portal"
FILL_PREFIX = "__ir_ambient_fill"


def install_sun() -> dict:
    if bpy.data.objects.get(SUN) is not None:
        return {"status": "present"}
    data = bpy.data.lights.new(SUN, "SUN")
    data.energy = 0.0                       # the variant sets it; 0 until then
    data.angle = math.radians(0.53)         # solar disc, keeps contact shadows crisp
    data["ir_sun"] = True
    data["ir_emitter_class"] = "daylight"
    data["ir_nir_passive_scale"] = NIR_PASSIVE_SCALE_POLICY["daylight"]
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(SUN, data))
    return {"status": "created", "nir_passive_scale": NIR_PASSIVE_SCALE_POLICY["daylight"]}


def name_sky() -> dict:
    """Give the world's background node the name the variant looks up."""
    world = bpy.context.scene.world
    if world is None or not world.use_nodes:
        return {"status": "no_node_world"}
    node = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if node is None:
        return {"status": "no_background_node"}
    was = node.name
    node.name = "IR_Sky"
    return {"status": "renamed" if was != "IR_Sky" else "present", "was": was}


def relocate_portals(inset_m: float = 0.15) -> dict:
    """Put each window portal inside the glass, aimed into the room.

    Measured, not assumed: a ray from every one of this scene's 37 portals finds
    a WindowFactory pane ~0.10 m away on one side and nothing within 6 m on the
    other, so they all sit OUTSIDE the building. Our Stage-2 authored them for a
    path where `_set_environment` drove them as apertures; HSSD instead gives
    them wattage as real emitters, and an emitter outside an opaque pane cannot
    light a room whichever way it faces -- which is why 14.9 kW across 148.95 m2
    of aperture rendered as almost nothing.

    HSSD's own portals are inside for exactly this reason: that pipeline
    substitutes opaque glass and the portal stands in for the window. Matching
    that convention is what this does; it invents no new illumination.

    The pane tells us which way the building is, so it also tells us which way
    to move and aim: through it, then `inset_m` further in.
    """
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    moved, skipped = [], []
    for obj in list(scene.objects):
        if obj.type != "LIGHT" or not obj.name.startswith(PORTAL_PREFIX):
            continue
        origin = obj.matrix_world.translation.copy()
        emit = (obj.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
        # Whichever side the pane is on is the building. Try the emission axis
        # first, then its reverse; a portal with no pane either way is left
        # alone rather than moved on a guess.
        toward = None
        for direction in (emit, -emit):
            hit = scene.ray_cast(depsgraph, origin + direction * 0.02, direction, distance=1.0)
            if hit[0] and "Window" in hit[4].name:
                toward, distance = direction, (hit[1] - origin).length
                break
        if toward is None:
            skipped.append({"name": obj.name, "why": "no window pane within 1 m either way"})
            continue
        obj.matrix_world.translation = origin + toward * (distance + inset_m)
        # An AREA light emits along -Z, so point -Z along `toward`.
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (-toward).to_track_quat("Z", "Y")
        moved.append({"name": obj.name, "pane_at_m": round(distance, 4),
                      "moved_m": round(distance + inset_m, 4)})
    bpy.context.view_layer.update()
    # Verify the move rather than trusting it: from inside, the emission ray
    # should now find room geometry, and it should no longer be the pane.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    inside = 0
    for obj in scene.objects:
        if obj.type != "LIGHT" or not obj.name.startswith(PORTAL_PREFIX):
            continue
        origin = obj.matrix_world.translation
        emit = (obj.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
        hit = scene.ray_cast(depsgraph, origin + emit * 0.02, emit, distance=8.0)
        if hit[0] and "Window" not in hit[4].name:
            inside += 1
    return {"moved": len(moved), "skipped": len(skipped), "inset_m": inset_m,
            "emitting_into_room": inside, "skipped_sample": skipped[:3], "sample": moved[:3]}


def _pane_area_m2(portal):
    """The matched window's opening area, from its two largest bbox extents."""
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = portal.matrix_world.translation
    emit = (portal.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    for direction in (-emit, emit):      # after relocation the pane is behind
        hit = scene.ray_cast(depsgraph, origin + direction * 0.02, direction, distance=1.2)
        if not (hit[0] and "Window" in hit[4].name):
            continue
        obj = hit[4]
        corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
        extents = sorted((max(p[i] for p in corners) - min(p[i] for p in corners) for i in range(3)),
                         reverse=True)
        return float(extents[0] * extents[1])
    return None


def declare_windows(area_scale: float = 1.0) -> dict:
    """Turn the Stage-2 portals into the window lights the variant drives."""
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != "LIGHT" or not obj.name.startswith(PORTAL_PREFIX):
            continue
        # An AREA light's size is its emitting rectangle, which is the portal's
        # aperture -- so the per-m^2 recipe scales by real glazing area rather
        # than by a count of windows.
        lamp_area = float(obj.data.size) * float(
            getattr(obj.data, "size_y", obj.data.size)
            if obj.data.shape in {"RECTANGLE", "ELLIPSE"} else obj.data.size)
        # The AREA light's own size is the wrong number: summed over this scene's
        # portals it claims 148.95 m2 of glazing for one apartment, with single
        # portals at 9.4 m2, and at 100 W/m2 that floods every room with a
        # portal to a median luminance of 14 -- as far over as the outside-the-
        # pane version was under. Our Stage-2 sized these as wall-spanning
        # apertures for a path that drove them by strength, not by wattage.
        # The pane the portal was matched to is the real aperture, so measure it:
        # a window's two largest bounding-box extents are its opening.
        pane = _pane_area_m2(obj)
        obj.data["ir_window_light"] = True
        # Calibration, and named as one. The recipe gives 100 W/m2 and this
        # scene declares 148.95 m2 of aperture for one apartment -- the
        # WindowFactory openings are wall-sized, so the number is real but the
        # product is not a room. Unscaled it splits the corpus in two: rooms
        # with a portal render at rgb mean 4-10 while rooms without sit at
        # 0.03-0.05, and only 5 frames of 80 land in the reference corpus's
        # 0.93-3.65. Radiance is linear in emitter power, so one factor moves
        # the lit half onto the reference range.
        obj.data["ir_window_area_m2"] = (pane if pane is not None else lamp_area) * area_scale
        obj.data["ir_window_area_source"] = "window_pane_bbox" if pane is not None else "portal_lamp_size"
        obj.data["ir_nir_passive_scale"] = NIR_PASSIVE_SCALE_POLICY["daylight"]
        out.append({"name": obj.name, "area_m2": round(float(obj.data["ir_window_area_m2"]), 4),
                    "lamp_area_m2": round(lamp_area, 4),
                    "source": obj.data["ir_window_area_source"]})
    return {"count": len(out), "area_scale": area_scale,
            "total_declared_area_m2": round(sum(o["area_m2"] for o in out), 3),
            "windows": out[:3]}


def declare_fixtures(mode: str = "always_on", watts: float = 70.0) -> dict:
    """Enrol the scene's own luminaires so the variant can switch them on.

    Our Stage-2 prepare set every native lamp to 0 W and hid it. The wattage
    comes back from the variant's fixture_state, not from a number invented
    here, so restoring participation does not restore a guess.
    """
    # Only the scene's own generated luminaires. The blend also holds anonymous
    # `Area` / `Area.001` lights that arrived at 0 W and hidden; what they were
    # for is not recorded anywhere, and enrolling them would hand a lamp's
    # wattage to something that might be an exterior or a bounce card.
    lamps = [o for o in bpy.context.scene.objects
             if o.type == "LIGHT" and not o.name.startswith("__ir_")
             and "Factory" in o.name]
    lamps.sort(key=lambda o: o.name)        # deterministic index, not scene order
    for index, obj in enumerate(lamps):
        if mode == "variant":
            # The variant owns the wattage: it turns fixtures on for the evening
            # and night takes and off for the daylight ones.
            obj.data["ir_fixture_light"] = True
            obj.data["ir_fixture_index"] = index
        else:
            # Left undeclared on purpose. `_lighting_variant` only rewrites lights
            # it can match, so an undeclared lamp keeps the wattage set here --
            # through T0 as well, where the variant's own fixture level is 0 W.
            #
            # That 0 W is why 31 of the first 80 frames of this corpus came out
            # near black: whole takes sit in rooms daylight does not reach, and a
            # daylight-only baseline renders them at rgb mean 0.004-0.02 against
            # HSSD's own T0 range of 0.93-3.65. Nothing upstream flags it -- a
            # peer corpus shipped two fully dark scenes this way and found out
            # two days later.
            for key in ("ir_fixture_light", "ir_fixture_index"):
                if key in obj.data.keys():
                    del obj.data[key]
            obj.data.energy = float(watts)
            obj.data["ir_rgb_energy_w"] = float(watts)
        obj.data["ir_fixture_category"] = "infinigen_native_lamp"
        obj.data["ir_nir_passive_scale"] = NIR_PASSIVE_SCALE_POLICY["incandescent"]
        # A POINT lamp at full wattage fireflies in Cycles; give it a small
        # emitting sphere so it reads as a bulb.
        if obj.data.type == "POINT":
            obj.data.shadow_soft_size = max(float(obj.data.shadow_soft_size), 0.04)
    skipped = [o.name for o in bpy.context.scene.objects
               if o.type == "LIGHT" and not o.name.startswith("__ir_") and "Factory" not in o.name]
    return {"count": len(lamps), "mode": mode, "watts": (watts if mode != "variant" else None),
            "names": [o.name[:44] for o in lamps[:4]],
            "skipped_unnamed": len(skipped), "skipped_sample": skipped[:3]}


def dim_ambient_fills(watts: float) -> dict:
    """Keep the synthetic ceiling fills, at a level that only rescues dark rooms.

    Retiring them entirely was right while daylight was the whole story, but this
    apartment has more rooms than lamps: after the portals were moved inside the
    glass and the lamps were left burning, 9 of 80 frames were still near black
    because their room has neither a window nor a luminaire. A room with no light
    source at all is not a lighting condition, it is a gap in the scene.

    Held well below the lamps (70 W) so a room that has its own light still looks
    lit by it, and `ir_rgb_energy_w` is written so `_ambient_band` cannot latch
    them off after the first frame.
    """
    lit = []
    for obj in bpy.context.scene.objects:
        if obj.type != "LIGHT" or not obj.name.startswith(FILL_PREFIX):
            continue
        obj.data.energy = float(watts)
        obj.data["ir_rgb_energy_w"] = float(watts)
        obj.data["ir_nir_passive_scale"] = NIR_PASSIVE_SCALE_POLICY["incandescent"]
        obj.hide_render = False
        lit.append(obj.name)
    return {"count": len(lit), "watts": watts}


def retire_ambient_fills() -> dict:
    """Silence the synthetic ceiling fills once real daylight is installed.

    They are HSSD's retired rig, and `_lighting_variant` only zeroes the three
    legacy names -- ours are per-room and would survive as a non-physical fill
    stacked on top of the sun, sky and fixtures.
    """
    off = []
    for obj in bpy.context.scene.objects:
        if obj.type != "LIGHT" or not obj.name.startswith(FILL_PREFIX):
            continue
        obj.data["ir_rgb_energy_w"] = 0.0
        obj.data["ir_nir_passive_scale"] = 0.0
        obj.data.energy = 0.0
        obj.hide_render = True
        off.append(obj.name)
    return {"count": len(off)}


# The renderer composes GT_PBRInvalidMask from three terms and only owns two of
# them: `_mark_background_invalid` folds in "no surface was hit" from the Depth
# pass, and `_mark_mixed_invalid` folds in "more than one surface" from
# GT_LayerCount. The per-surface term -- this pixel shows a surface that has no
# meaningful PBR target -- has to come from the materials, so it is built here.
#
# Two classes qualify, both for the same reason: the Principled parameters do
# not describe what the pixel shows. A pane's albedo/roughness/metallic say
# nothing about the transmitted image behind it, and an emitter's radiance is
# not a reflectance at all.
#
# GT_LayerCount is deliberately ungated in HSSD's own prepare -- 1.0 per surface
# crossed, whatever it is -- so it is added to every material without exception.
GLASS_NODES = {"BSDF_GLASS", "BSDF_TRANSPARENT", "BSDF_REFRACTION"}
TRANSMISSION_SOCKETS = ("Transmission Weight", "Transmission")
EMISSION_SOCKETS = ("Emission Strength",)


def _socket_value(node, names):
    """A socket's effective value: linked means "varies", so treat as present."""
    for name in names:
        socket = node.inputs.get(name)
        if socket is None:
            continue
        if socket.is_linked:
            return float("inf")
        return float(socket.default_value)
    return 0.0


def _walk_nodes(tree, seen=None):
    """Every node of a material tree, node groups included (a no-bake procedural material hides its Glass inside groups)."""
    seen = set() if seen is None else seen
    if tree is None or tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    for node in tree.nodes:
        yield node
        if node.type == "GROUP":
            yield from _walk_nodes(node.node_tree, seen)


def _classify_material(mat) -> str:
    if mat is None or not mat.use_nodes:
        return "opaque"
    for node in _walk_nodes(mat.node_tree):
        if node.type in GLASS_NODES:
            return "glass"
        if node.type == "EMISSION" and _socket_value(node, ("Strength",)) > 0.0:
            return "emitter"
        if node.type == "BSDF_PRINCIPLED":
            if _socket_value(node, TRANSMISSION_SOCKETS) > 0.05:
                return "glass"
            if _socket_value(node, EMISSION_SOCKETS) > 0.0:
                return "emitter"
    return "opaque"


def _aov_output(tree, name, value):
    """An AOV output driven by a constant, added only if not already present."""
    for node in tree.nodes:
        if node.bl_idname == "ShaderNodeOutputAOV" and node.name == name:
            return False
    const = tree.nodes.new("ShaderNodeValue")
    const.outputs[0].default_value = float(value)
    const.name = const.label = f"{name}_value"
    out = tree.nodes.new("ShaderNodeOutputAOV")
    out.name = out.label = name
    out.aov_name = name
    tree.links.new(const.outputs[0], out.inputs["Value"])
    return True


def register_aovs(view_layer, names) -> list:
    """Declare AOVs on the view layer so the render-layer node exposes them."""
    have = {a.name for a in view_layer.aovs}
    added = []
    for name in names:
        if name in have:
            continue
        aov = view_layer.aovs.add()
        aov.name = name
        aov.type = "VALUE"
        added.append(name)
    return added


def _window_materials() -> tuple[set, set]:
    """Materials used by window geometry, split by whether that use is exclusive.

    Transmission is the wrong signal in this blend: our Stage-2 already made the
    panes opaque -- which is why sun and sky reached nothing through them -- so
    classifying by Principled transmission found one glass material out of 540
    and was measuring the substitution, not the windows. What the mask has to
    exclude is the pane *surface*, whose Principled parameters describe a
    stand-in rather than the view through it.
    #
    A material shared between a pane and a wall cannot be marked without marking
    the wall too, so exclusivity is measured and reported instead of assumed.
    """
    window, other = {}, {}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        is_window = obj.get("hssd_asset_role") == "opening" or "Window" in obj.name
        for slot in obj.material_slots:
            if slot.material is None:
                continue
            (window if is_window else other).setdefault(slot.material.name, 0)
            (window if is_window else other)[slot.material.name] += 1
    exclusive = {n for n in window if n not in other}
    shared = {n for n in window if n in other}
    return exclusive, shared


def _is_water(obj) -> bool:
    """A puddle or standing-water surface. User 11-01: a water film over pavement is two layers (a sharp coat over a rough
    base) that one albedo/roughness/metallic triple cannot describe, and its GT says "water", not the ground under it.
    Builders name them inconsistently, so: `ir_water` property, a *puddle* object name (damp halos excluded), or a
    PUDDLES collection."""
    if obj.get("ir_water"):
        return True
    name = obj.name.lower()
    if "puddle" in name and "damp" not in name:
        return True
    return any(c.name.upper().startswith("PUDDLE") for c in obj.users_collection)


def _water_materials() -> tuple[set, set]:
    """Materials used by water surfaces, split like _window_materials: only exclusive ones can be marked."""
    water, other = set(), set()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        target = water if _is_water(obj) else other
        target.update(s.material.name for s in obj.material_slots if s.material is not None)
    return water - other, water & other


def build_pbr_invalid_mask() -> dict:
    exclusive, shared = _window_materials()
    water, water_shared = _water_materials()
    counts = {"glass_transmissive": 0, "emitter": 0, "window_exclusive": 0, "water": 0,
              "opaque": 0, "no_nodes": 0}
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            counts["no_nodes"] += 1
            continue
        kind = _classify_material(mat)
        if kind == "glass":
            counts["glass_transmissive"] += 1
        elif kind == "emitter":
            counts["emitter"] += 1
        elif mat.name in exclusive:
            kind = "window"
            counts["window_exclusive"] += 1
        elif mat.name in water:
            kind = "water"
            counts["water"] += 1
        else:
            counts["opaque"] += 1
        _aov_output(mat.node_tree, "GT_PBRInvalidMask", 0.0 if kind == "opaque" else 1.0)
        _aov_output(mat.node_tree, "GT_LayerCount", 1.0)
    return {**counts, "window_materials_shared_with_non_windows": len(shared),
            "shared_sample": sorted(shared)[:3],
            "water_materials_shared_with_non_water": len(water_shared),
            "water_shared_sample": sorted(water_shared)[:3]}


def set_denoiser(kind: str) -> dict:
    """Pick the denoiser. The renderer turns denoising ON at runtime but never
    chooses one, so the blend's setting decides -- and Stage-2 leaves it at
    OPENIMAGEDENOISE with denoising_use_gpu False, i.e. on the CPU. For a corpus
    whose noisiest channel is an isolated light group, that is both the slower
    and the weaker option on this hardware.
    """
    cycles = bpy.context.scene.cycles
    before = (cycles.denoiser, bool(cycles.denoising_use_gpu))
    if kind == "leave":
        return {"denoiser": before[0], "use_gpu": before[1], "changed": False}
    try:
        cycles.denoiser = "OPTIX" if kind == "optix" else "OPENIMAGEDENOISE"
    except TypeError as exc:                 # no OptiX in this build
        return {"denoiser": before[0], "use_gpu": before[1], "changed": False,
                "error": str(exc)}
    cycles.denoising_use_gpu = True
    return {"denoiser": cycles.denoiser, "use_gpu": bool(cycles.denoising_use_gpu),
            "changed": True, "was": before[0]}


def flash_only() -> dict:
    """Leave the flash as the scene's only emitter, so a render spends every
    sample on it.

    Why this exists: the flash is one emitter among ~35 here (26 window portals,
    7 lamps, sun, sky), so Cycles' light sampling gives its paths roughly that
    fraction of the light samples, and the isolated NIR_FLASH light group inherits
    the variance of that fraction. Measured: 9.6% relative noise at nir-spp 512
    against 2% on the full Combined pass. Rendering the flash term on its own puts
    the whole budget behind it instead of buying samples the other 34 emitters
    also spend.

    It cannot be done by zeroing energies in the blend, because
    `_lighting_variant` rewrites sun, sky, window and fixture levels from the
    recipe on every frame. What it cannot rewrite is a light it never finds: it
    matches windows on `ir_window_light`, fixtures on `ir_fixture_light`, the sun
    on the object name `__ir_sun` and the sky on a world node named `IR_Sky`. So
    this leaves all four unclaimed and silences what remains directly.
    """
    scene = bpy.context.scene
    silenced = []
    for obj in scene.objects:
        if obj.type != "LIGHT" or obj.name.startswith(FLASH):
            continue
        for key in ("ir_window_light", "ir_fixture_light", "ir_ambient_fill"):
            if key in obj.data.keys():
                del obj.data[key]
        obj.data["ir_rgb_energy_w"] = 0.0
        obj.data["ir_nir_passive_scale"] = 0.0
        obj.data.energy = 0.0
        obj.hide_render = True
        silenced.append(obj.name)
    world = scene.world
    sky = None
    if world is not None and world.use_nodes:
        for node in world.node_tree.nodes:
            if node.type == "BACKGROUND":
                # Renaming it away from IR_Sky is what keeps _lighting_variant
                # from setting a strength back on it next frame.
                node.name = "IR_Sky_disabled"
                node.inputs["Strength"].default_value = 0.0
                sky = node.name
    return {"silenced_lights": len(silenced), "sky_node": sky,
            "sun_present": bpy.data.objects.get(SUN) is not None}


def pack_textures() -> dict:
    """Pull every image into the .blend so a render stops reading NFS.

    Measured on this scene: 844 images, 843 of them under /bean, which is nfs4
    with rsize=32768 -- so 268 MB of texture arrives as thousands of round trips
    plus 843 opens, once per render, because Cycles frees image data between
    renders unless persistent data is on. Per-pass fixed cost here is 5.2-5.9 s
    against about 2 s of actual tracing.

    Packing is preferred over copying to local disk because the adapted blend is
    already a throwaway in local scratch: one local file replaces 843 network
    reads with no path rewriting and nothing to clean up afterwards.
    """
    before = sum(1 for i in bpy.data.images if i.users and not i.packed_file)
    missing = []
    for image in bpy.data.images:
        if not image.users or image.packed_file:
            continue
        try:
            image.pack()
        except RuntimeError as exc:          # a path that no longer resolves
            missing.append({"name": image.name[:48], "why": str(exc)[:60]})
    packed = sum(1 for i in bpy.data.images if i.users and i.packed_file)
    return {"packed": packed, "was_external": before,
            "unpackable": len(missing), "unpackable_sample": missing[:3]}


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--window-area-scale", type=float, default=0.33,
                    help="scales the declared window aperture; a calibration, not a measurement")
    ap.add_argument("--fixtures", choices=("always_on", "variant"), default="always_on",
                    help="always_on keeps the scene's lamps burning through every variant, "
                         "including T0 whose own fixture level is 0 W")
    ap.add_argument("--fixture-watts", type=float, default=70.0,
                    help="wattage for always_on; 70 W is HSSD's own T1 fixture level, "
                         "their lowest lights-on setting")
    ap.add_argument("--flash-only", action="store_true",
                    help="silence every emitter but the NIR flash, so an --active-only render "
                         "measures the flash term with the whole sample budget")
    ap.add_argument("--diffuse-passes", action=argparse.BooleanOptionalAction, default=False,
                    help="write diffuse_transport_* and diffuse_component_* (12.8 MB a frame, "
                         "unused by this corpus)")
    ap.add_argument("--pack-textures", action=argparse.BooleanOptionalAction, default=True,
                    help="pack images into the blend so renders do not re-read them over NFS")
    ap.add_argument("--denoiser", choices=("optix", "oidn", "leave"), default="optix",
                    help="denoiser the renderer will use; Stage-2 leaves OIDN on the CPU")
    ap.add_argument("--relocate-portals", choices=("inside", "leave"), default="inside",
                    help="move window portals inside the glass and aim them into the room")
    ap.add_argument("--windows", choices=("declare", "skip"), default="declare",
                    help="declare the Stage-2 portals as window lights, or leave them dark and let "
                         "sun and sky reach the interior through the scene's real glass")
    ap.add_argument("--daylight-rig", choices=("install", "skip"), default="install",
                    help="install the sun/sky/window/fixture rig the day curriculum drives")
    ap.add_argument("--ambient-fill-watts", type=float, default=250.0,
                    help="wattage for the synthetic ceiling fills; 0 retires them. They exist to "
                         "keep a room with neither window nor lamp from rendering black")
    ap.add_argument("--ambient-emitter-class", default="incandescent",
                    choices=sorted(NIR_PASSIVE_SCALE_POLICY),
                    help="850-nm policy class for the synthetic ceiling fills")
    return ap.parse_args(argv)


def reparent_flash() -> dict:
    """Give the controller name to an empty and hang the flash light under it."""
    obj = bpy.data.objects.get(FLASH)
    if obj is None:
        return {"status": "absent", "note": "no flash object to adapt"}
    if obj.type == "EMPTY":
        return {"status": "already_controller", "children": [c.name for c in obj.children]}
    obj.name = f"{FLASH}_lamp"
    ctl = bpy.data.objects.new(FLASH, None)          # empty
    bpy.context.scene.collection.objects.link(ctl)
    ctl.matrix_world = obj.matrix_world.copy()
    obj.parent = ctl
    obj.matrix_parent_inverse = ctl.matrix_world.inverted()
    # _flash() sets hide_render on children per frame; start hidden as passive.
    obj.hide_render = True
    return {"status": "reparented", "controller": ctl.name, "child": obj.name}


def register_light_groups(view_layer) -> list[str]:
    for name in LIGHT_GROUPS:
        if view_layer.lightgroups.get(name) is None:
            view_layer.lightgroups.add().name = name
    return sorted(g.name for g in view_layer.lightgroups)


def enable_passes(view_layer, diffuse: bool = False) -> dict:
    """Turn on the view-layer passes the renderer reads.

    The diffuse trio is off. The renderer writes diffuse_transport_* and
    diffuse_component_* only when all three of DiffDir, DiffInd and DiffCol
    exist, so not enabling them is how those four files stop being produced --
    no change to its code, it simply finds nothing to compose. They cost 12.8 MB
    of a 30 MB frame and this corpus trains on none of them.

    albedo_nir and albedo_rgb are unaffected: both come from their own
    GT_BaseColor* AOVs. The renderer's own comment says why -- Diffuse Color
    zeroes a fully metallic surface, so it was never the albedo here.
    """
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True
    view_layer.use_pass_diffuse_direct = diffuse
    view_layer.use_pass_diffuse_indirect = diffuse
    view_layer.use_pass_diffuse_color = diffuse
    return {"z": True, "normal": True, "diffuse_direct": diffuse,
            "diffuse_indirect": diffuse, "diffuse_color": diffuse}


def main() -> int:
    a = _args()
    vl = bpy.context.scene.view_layers[0]
    report = {
        "schema": "robomituba.stage2_hssd_adapter.v1",
        "source_blend": bpy.data.filepath,
        "flash": reparent_flash(),
        "asset_roles": tag_asset_roles(),
        "ambient_band": declare_ambient_band(a.ambient_emitter_class),
        "daylight_rig": ({"mode": "skip"} if (a.daylight_rig == "skip" or a.flash_only) else {
            "mode": "install", "sun": install_sun(), "sky": name_sky(),
            "portals": ({"mode": "leave"} if a.relocate_portals == "leave" else relocate_portals()),
            "windows": (declare_windows(a.window_area_scale) if a.windows == "declare" else {"mode": "skip"}), "fixtures": declare_fixtures(a.fixtures, a.fixture_watts),
            "ambient_fills": (retire_ambient_fills() if a.ambient_fill_watts <= 0
                              else dim_ambient_fills(a.ambient_fill_watts))}),
        "lightgroups": register_light_groups(vl),
        "passes": enable_passes(vl, a.diffuse_passes),
        "denoiser": set_denoiser(a.denoiser),
        "textures": (pack_textures() if a.pack_textures else {"mode": "left external"}),
        "flash_only": (flash_only() if a.flash_only else {"mode": "off"}),
        "pbr_invalid_mask": build_pbr_invalid_mask(),
        "mask_aovs": register_aovs(vl, ("GT_PBRInvalidMask", "GT_LayerCount")),
        "aovs_registered": sorted(x.name for x in vl.aovs),
        "hssd_only_aovs_left_unregistered": [
            "GT_RoughnessRawGLTF", "GT_MetallicRawGLTF", "GT_MRExplicitMask",
            "GT_MRInferredMask", "GT_MRTrainingValidMask", "GT_MRConfidence",
            "GT_RoughnessEffective", "GT_MetallicEffective", "GT_GlassMask"],
        "why_unregistered": ("an AOV with nothing driving it renders as zeros; the renderer skips a "
                             "missing output and writes no file, so absent beats zero"),
        "out_blend": a.out,
    }
    bpy.ops.wm.save_as_mainfile(filepath=a.out, copy=True)
    print("ADAPTED " + json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
