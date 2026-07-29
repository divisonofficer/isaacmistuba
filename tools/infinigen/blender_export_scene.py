"""Stage 1 of the Infinigen -> OpticalNav converter (runs under bpy).

Opens an Infinigen indoor scene and exports, per mesh "unit":
  * a world-space, Y-up OBJ (+ MTL + copied textures)   -> Mitsuba render geometry
  * a GLB (full PBR/UV preserved)                        -> editor preview + future quality
and a `scene_manifest.json` describing every unit (classification, world bbox,
transform, material PBR summary), every light, and the scene cameras.

Run it via the bpy module (the bundled Blender binary has broken libs):

  /home/jinnyeong/miniconda3/envs/infinigen/bin/python tools/infinigen/_run_bpy.py \
      data/.../scene.blend1 tools/infinigen/blender_export_scene.py -- \
      --out out/infinigen_imports/singleroom_furnished [--limit N] [--no-glb]

Coordinate handling: Blender is Z-up; we export OBJ with forward=-Z up=Y so the
mesh is Y-up (matches Mitsuba / our authoring world). The 2D authoring placement
(authoring_x, authoring_y) is taken from the Blender world XY of the bbox centre.
"""

import contextlib
import hashlib
import json
import math
import os
import re
import struct
import sys

import bpy  # type: ignore
from mathutils import Matrix, Vector  # type: ignore

try:
    from tqdm import tqdm as _tqdm  # progress bar (present in the infinigen env)
except Exception:  # noqa: BLE001
    _tqdm = None


@contextlib.contextmanager
def _silence_fds(*fds):
    """Redirect the given OS file descriptors to /dev/null for the duration.

    Blender floods the console with C-level spam during heavy ops — on BOTH stdout
    (``Synchronizing object``, ``Updating Images``, deferred ``Info: Baking map
    saved`` operator reports) and stderr (``Writing to ...``, ``OBJ export ... took``).
    Redirect fd 1+2 around an op to mute it; the tqdm bar is idle during the op so
    nothing is lost. Use fd 1 around the whole loop to also catch the deferred
    operator reports that flush between ops."""
    saved = []
    try:
        sys.stdout.flush(); sys.stderr.flush()
        devnull = os.open(os.devnull, os.O_WRONLY)
        for fd in fds:
            saved.append((fd, os.dup(fd)))
            os.dup2(devnull, fd)
        os.close(devnull)
    except Exception:  # noqa: BLE001
        saved = []
    try:
        yield
    finally:
        for fd, old in saved:
            try:
                os.dup2(old, fd)
                os.close(old)
            except Exception:  # noqa: BLE001
                pass


def _log(msg: str, bar=None) -> None:
    """Print a line without corrupting an active tqdm bar."""
    if bar is not None and _tqdm is not None:
        bar.write(msg)
    else:
        print(msg)


# ── classification ────────────────────────────────────────────────────────────

STRUCT_SUFFIX = {
    ".wall": "wall",
    ".floor": "floor",
    ".ceiling": "ceiling",
    ".exterior": "exterior",
}

# Factory-name keyword -> OpticalNav semantic type (lowercase substring match).
FACTORY_SEMANTIC = [
    ("chair", "chair"),
    ("sofa", "chair"),
    ("stool", "chair"),
    ("bed", "landmark"),
    ("tabledining", "table"),
    ("table", "table"),
    ("desk", "table"),
    ("counter", "table"),
    ("island", "table"),
    ("shelf", "shelf"),
    ("cabinet", "shelf"),
    ("bookcase", "shelf"),
    ("wardrobe", "shelf"),
    ("dresser", "shelf"),
    ("plant", "plant"),
    ("door", "glass_door"),
    ("window", "glass_wall"),
    ("lamp", "landmark"),
    ("light", "landmark"),
]

# Material-name keyword -> representative linear base colour (when we cannot read
# a concrete colour out of the procedural node graph).
MAT_NAME_COLOR = [
    ("invisible", [1.0, 1.0, 1.0]),
    ("glass", [0.62, 0.70, 0.78]),
    ("wood", [0.42, 0.27, 0.15]),
    ("marble", [0.88, 0.87, 0.84]),
    ("brushed", [0.58, 0.58, 0.60]),
    ("galvanized", [0.60, 0.61, 0.63]),
    ("grained_met", [0.55, 0.55, 0.57]),
    ("metal", [0.56, 0.57, 0.58]),
    ("brick", [0.55, 0.32, 0.25]),
    ("ceramic", [0.85, 0.83, 0.80]),
    ("fabric", [0.40, 0.40, 0.46]),
    ("sofa", [0.42, 0.40, 0.45]),
    ("plast", [0.70, 0.70, 0.72]),
    ("shelves_whi", [0.90, 0.90, 0.90]),
    ("bone", [0.90, 0.88, 0.80]),
    ("monocot", [0.30, 0.45, 0.20]),
    ("stem", [0.28, 0.42, 0.18]),
    ("dirt", [0.30, 0.22, 0.15]),
    ("tile", [0.80, 0.80, 0.82]),
    ("paint", [0.80, 0.79, 0.76]),
    ("concrete", [0.62, 0.61, 0.59]),
]


def _argv_after_ddash():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _sanitize(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("_")
    return s or "obj"


def _classify(obj):
    """Return (kind, semantic_type, subtype) for a mesh object."""
    colls = {c.name for c in obj.users_collection}
    name = obj.name
    lname = name.lower()

    # Room structure (per-room .wall/.floor/.ceiling/.exterior meshes)
    for suf, sub in STRUCT_SUFFIX.items():
        if name.endswith(suf) or any(suf in c for c in colls):
            sem = {"wall": "wall", "exterior": "wall", "ceiling": "landmark", "floor": "landmark"}[sub]
            return "structure", sem, sub
    if any("room_wall" in c or "room_exterior" in c for c in colls):
        return "structure", "wall", "wall"
    if any("room_ceiling" in c for c in colls):
        return "structure", "landmark", "ceiling"
    if any("room_floor" in c for c in colls):
        return "structure", "landmark", "floor"

    if any("doors" in c for c in colls) or "door_base_elements" in ",".join(colls):
        return "door", "glass_door", "door"
    if any("windows" in c for c in colls):
        return "window", "glass_wall", "window"

    # Furniture / props in unique_assets — classify by Factory name.
    for kw, sem in FACTORY_SEMANTIC:
        if kw in lname:
            kind = "light" if sem == "landmark" and ("lamp" in lname or "light" in lname) else "furniture"
            return kind, sem, lname.split("factory")[0]
    # Small tableware / decor -> landmark prop.
    return "furniture", "landmark", "prop"


def _factory_of(name: str) -> str:
    m = re.match(r"([A-Za-z]+)", name)
    return m.group(1) if m else name


# ── material PBR extraction ─────────────────────────────────────────────────────

def _socket_value(sock):
    try:
        v = sock.default_value
        return list(v) if hasattr(v, "__len__") else float(v)
    except Exception:
        return None


def _trace_color(sock):
    """Best-effort concrete colour for a (possibly linked) Base Color socket."""
    if not sock.is_linked:
        v = _socket_value(sock)
        return v[:3] if isinstance(v, list) and len(v) >= 3 else None
    try:
        node = sock.links[0].from_node
        if node.type == "RGB":
            return list(node.outputs[0].default_value)[:3]
        if node.type == "VALTORGB" and node.color_ramp:  # ColorRamp -> average stops
            els = node.color_ramp.elements
            if len(els):
                r = sum(e.color[0] for e in els) / len(els)
                g = sum(e.color[1] for e in els) / len(els)
                b = sum(e.color[2] for e in els) / len(els)
                return [r, g, b]
        if node.type == "TEX_IMAGE":
            return None  # handled via image refs
    except Exception:
        pass
    return None


def _name_color(mat_name: str):
    low = mat_name.lower()
    for kw, col in MAT_NAME_COLOR:
        if kw in low:
            return list(col)
    return [0.6, 0.6, 0.6]


def _optical_class(name: str, is_glass: bool, metallic: float) -> str:
    """Classify a material into an optical family for BSDF binding downstream.

    Name keyword is the primary signal (Infinigen's `metallic` param is
    unreliable — e.g. `shader_brushed_metal` reports metallic=0.0). Returns one
    of: glass | mirror | metal_gold | metal_steel | metal_aluminum | diffuse.
    Stage 2 (`import_infinigen_scene._material_binding`) maps these to render
    bsdf_strategy; Stage 1 uses them to decide whether to bake/strip albedo.
    """
    n = (name or "").lower()
    if is_glass or "glass" in n:
        return "glass"
    if "mirror" in n or "chrome" in n:
        return "mirror"
    if any(k in n for k in ("gold", "brass")):
        return "metal_gold"
    if any(k in n for k in ("steel", "iron", "suj")):
        return "metal_steel"
    if any(k in n for k in ("metal", "alumin", "galvan", "brush", "grain",
                            "copper", "silver", "nickel")) or float(metallic or 0.0) >= 0.5:
        return "metal_aluminum"
    return "diffuse"


def _extract_material(mat):
    out = {
        "name": mat.name,
        "procedural": True,
        "base_color": None,
        "metallic": 0.0,
        "roughness": 0.6,
        "ior": 1.5,
        "emission_strength": 0.0,
        "emission_color": None,
        "alpha": 1.0,
        "image_textures": [],
        "is_glass": "glass" in mat.name.lower(),
        "is_emissive": "invisible" in mat.name.lower() or "light" in mat.name.lower(),
    }
    if not (mat.use_nodes and mat.node_tree):
        out["base_color"] = _name_color(mat.name)
        out["procedural"] = False
        out["optical_class"] = _optical_class(mat.name, out["is_glass"], out["metallic"])
        return out
    nt = mat.node_tree
    images = []
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and getattr(n, "image", None) is not None:
            fp = bpy.path.abspath(n.image.filepath) if n.image.filepath else ""
            images.append({"name": n.image.name, "filepath": fp})
    out["image_textures"] = images
    out["procedural"] = len(images) == 0

    p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is not None:
        bc = p.inputs.get("Base Color")
        if bc is not None:
            out["base_color"] = _trace_color(bc)
        for key, dst in (("Metallic", "metallic"), ("Roughness", "roughness"),
                         ("IOR", "ior"), ("Alpha", "alpha"), ("Emission Strength", "emission_strength")):
            sock = p.inputs.get(key)
            if sock is not None and not sock.is_linked:
                v = _socket_value(sock)
                if isinstance(v, (int, float)):
                    out[dst] = float(v)
        em = p.inputs.get("Emission Color")
        if em is not None and not em.is_linked:
            v = _socket_value(em)
            if isinstance(v, list):
                out["emission_color"] = v[:3]
    if out["base_color"] is None:
        out["base_color"] = _name_color(mat.name)
    if out["emission_strength"] and out["emission_strength"] > 0 and out["emission_color"] is None:
        out["emission_color"] = [1.0, 1.0, 1.0]
    out["optical_class"] = _optical_class(mat.name, out["is_glass"], out["metallic"])
    return out


# ── geometry export ─────────────────────────────────────────────────────────────

def _world_bbox(obj):
    ws = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [v.x for v in ws]; ys = [v.y for v in ws]; zs = [v.z for v in ws]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def _yaw_deg(obj):
    e = obj.matrix_world.to_euler("XYZ")
    return math.degrees(e.z)


def _unhide(obj):
    """Temporarily make an object visible+selectable; return state to restore.

    Infinigen hides the structure/door/window working collections in the viewport
    (hide_viewport=True), which makes wm.obj_export skip them (empty OBJ). We must
    unhide before exporting and restore afterwards.
    """
    state = (obj.hide_viewport, obj.hide_get(), obj.hide_select, obj.hide_render)
    obj.hide_viewport = False
    obj.hide_select = False
    obj.hide_render = False  # Cycles bake refuses objects not enabled for rendering
    try:
        obj.hide_set(False)
    except Exception:
        pass
    return state


def _restore_hide(obj, state):
    obj.hide_viewport, hidden, obj.hide_select, obj.hide_render = state
    try:
        obj.hide_set(hidden)
    except Exception:
        pass


def _uv_is_degenerate(me):
    """True if the active UV layer has (near-)zero area — every loop mapped to the
    same point. Infinigen GN 'spawn_asset' meshes commonly ship a placeholder UVMap
    with all coords at (0,0); baking against it rasterises the whole atlas into a
    single texel -> a black albedo/roughness/metallic map, and the exported OBJ
    mis-maps its textures at render. Such a UV must be treated as *absent*."""
    layer = me.uv_layers.active
    if layer is None:
        return True
    data = layer.data
    n = len(data)
    if n == 0:
        return True
    # A bbox test is insufficient: many Infinigen placeholders span U while every
    # V is zero, so the bbox looks non-constant but every UV triangle has zero area.
    # Test actual loop-triangle area, sampling at most ~4000 triangles.
    try:
        me.calc_loop_triangles()
        triangles = me.loop_triangles
        used_slots = {
            polygon.material_index for polygon in me.polygons if polygon.loop_total >= 3
        }
        valid_slots = set()

        def record_if_valid(triangle):
            loop_indices = triangle.loops
            uv0 = data[loop_indices[0]].uv
            uv1 = data[loop_indices[1]].uv
            uv2 = data[loop_indices[2]].uv
            twice_area = abs(
                (uv1.x - uv0.x) * (uv2.y - uv0.y)
                - (uv1.y - uv0.y) * (uv2.x - uv0.x)
            )
            if math.isfinite(twice_area) and twice_area > 1e-10:
                valid_slots.add(me.polygons[triangle.polygon_index].material_index)

        step = max(1, len(triangles) // 4000)
        for index in range(0, len(triangles), step):
            record_if_valid(triangles[index])
            if used_slots.issubset(valid_slots):
                return False
        # Evenly spaced sampling can miss a tiny material part. Scan only until all
        # remaining material slots have demonstrated non-zero UV area.
        for triangle in triangles:
            slot = me.polygons[triangle.polygon_index].material_index
            if slot not in valid_slots:
                record_if_valid(triangle)
                if used_slots.issubset(valid_slots):
                    return False
        return not used_slots.issubset(valid_slots)
    except Exception:  # noqa: BLE001
        return True


def _planar_uv_fallback(obj):
    """Create a deterministic box-projection UV without edit-mode operators.

    Smart Project can exhaust memory on multi-million-polygon Infinigen assets.
    This fallback is intentionally conservative: it gives every material slot a
    non-zero-area UV basis so PBR values can still be rasterized and audited.
    """
    try:
        import numpy as np
        me = obj.data
        if not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        layer = me.uv_layers.active
        vertices = np.empty((len(me.vertices), 3), dtype=np.float32)
        me.vertices.foreach_get("co", vertices.ravel())
        loop_vertices = np.empty(len(me.loops), dtype=np.int64)
        me.loops.foreach_get("vertex_index", loop_vertices)
        normals = np.empty((len(me.polygons), 3), dtype=np.float32)
        me.polygons.foreach_get("normal", normals.ravel())
        starts = np.empty(len(me.polygons), dtype=np.int64)
        totals = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_start", starts)
        me.polygons.foreach_get("loop_total", totals)
        loop_polygon = np.repeat(np.arange(len(me.polygons), dtype=np.int64), totals)
        coords = vertices[loop_vertices]
        face_normals = normals[loop_polygon]
        axes = np.argmax(np.abs(face_normals), axis=1)
        uv = np.empty((len(coords), 2), dtype=np.float32)
        uv[:, 0] = np.where(
            axes == 0, coords[:, 1], np.where(axes == 1, coords[:, 0], coords[:, 0])
        )
        uv[:, 1] = np.where(
            axes == 0, coords[:, 2], np.where(axes == 1, coords[:, 2], coords[:, 1])
        )
        mins = np.nanmin(uv, axis=0)
        maxs = np.nanmax(uv, axis=0)
        spans = np.maximum(maxs - mins, 1e-8)
        uv = 0.01 + 0.98 * (uv - mins) / spans
        layer.data.foreach_set("uv", uv.ravel())
        me.update()
        ok = bool(me.uv_layers) and not _uv_is_degenerate(me)
        if ok:
            print(f"[bake] planar UV fallback: {obj.name}", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[bake] planar UV fallback FAIL {obj.name}: {exc}", file=sys.stderr)
        return False


def _ensure_uv(obj):
    """Guarantee a *usable* UV map for baking. Smart-UV-project objects that have
    none, OR whose existing UV is degenerate (zero-area — see _uv_is_degenerate).

    Procedural Infinigen materials sample shader values per surface point, so any
    non-overlapping UV (even a fresh Smart Project) captures the look correctly.
    """
    me = obj.data
    if me.uv_layers and not _uv_is_degenerate(me):
        return True
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        # Drop the degenerate placeholder so Smart Project's result is the active
        # (and only) layer the OBJ export + bake both see.
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])
        # Blender 3.6 does not always create a UV layer implicitly for meshes
        # converted from curves.  Create it before Smart Project so FINISHED cannot
        # still leave an empty uv_layers collection.
        me.uv_layers.new(name="UVMap")
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        # The Blender default margin (0.02) is catastrophic for very high-poly
        # Infinigen assets with hundreds of thousands of islands: the aggregate
        # UV coverage can fall below 0.1%, so a valid-looking atlas bakes black.
        # Use a scale-to-bounds pack with a small normalized gap; bake.margin
        # supplies the pixel-space dilation later.
        bpy.ops.uv.smart_project(
            angle_limit=1.15,
            island_margin=0.001,
            area_weight=0.3,
            correct_aspect=True,
            scale_to_bounds=True,
        )
        bpy.ops.object.mode_set(mode="OBJECT")
        if bool(me.uv_layers) and not _uv_is_degenerate(me):
            return True
        return _planar_uv_fallback(obj)
    except Exception as exc:  # noqa: BLE001
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        print(f"[bake] uv FAIL {obj.name}: {exc}", file=sys.stderr)
        return _planar_uv_fallback(obj)


def _bake_pass(obj, out_png, res, samples, *, bake_type="DIFFUSE",
               color_pass=False, non_color=False):
    """Bake one Cycles pass for all of an object's material slots into one atlas PNG.

    A ShaderNodeTexImage targeting a shared image is added to every slot so Cycles
    lays all slots over the object's UV in one bake. ``bake_type`` is a Cycles bake
    type ("DIFFUSE"/"ROUGHNESS"/"NORMAL"/"EMIT"); ``color_pass`` restricts DIFFUSE to
    the albedo colour (no direct/indirect light); ``non_color`` stores the PNG as
    linear data (roughness/normal/metallic — read raw at render time).
    Returns True on success. Best-effort.
    """
    if not obj.material_slots:
        return False
    if not _ensure_uv(obj):
        return False
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    bake = scene.render.bake
    bake.use_pass_direct = False
    bake.use_pass_indirect = False
    if color_pass:
        bake.use_pass_color = True
    bake.margin = 4

    img = bpy.data.images.new(f"bake_{obj.name}", width=res, height=res, alpha=False)
    if non_color:
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:  # noqa: BLE001
            pass
    added = []
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue
        nt = mat.node_tree
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.select = True
        nt.nodes.active = node
        added.append((nt, node))
    if not added:
        bpy.data.images.remove(img)
        return False

    ok = True
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake(type=bake_type)
        img.filepath_raw = out_png
        img.file_format = "PNG"
        img.save()
    except Exception as exc:  # noqa: BLE001
        print(f"[bake] FAIL {obj.name} ({bake_type}): {exc}", file=sys.stderr)
        ok = False
    finally:
        for nt, node in added:
            try:
                nt.nodes.remove(node)
            except Exception:
                pass
        try:
            bpy.data.images.remove(img)
        except Exception:
            pass
    return ok


def _bake_albedo(obj, out_png, res, samples):
    """Bake the actual nested Principled Base Color socket through EMIT."""
    return _bake_principled_channel(obj, out_png, res, samples, "Base Color", non_color=False)


def _bake_normal(obj, out_png, res, samples):
    return _bake_pass(obj, out_png, res, samples, bake_type="NORMAL", non_color=True)


@contextlib.contextmanager
def _render_isolate(obj):
    """Hide every OTHER object from render so Cycles only syncs `obj`'s geometry while
    baking. Baking against the full ~14M-poly Infinigen scene balloons to ~10 GB RSS
    and OOM-kills low-RAM/WSL boxes. Every bake here is a surface pass with direct AND
    indirect light disabled, so no other geometry contributes — isolating the target is
    lossless. Restores each object's prior hide_render on exit."""
    saved = []
    root_collection = bpy.context.scene.collection
    linked_to_root = obj.name in root_collection.objects
    if not linked_to_root:
        root_collection.objects.link(obj)
    saved_collections = [(collection, collection.hide_render) for collection in bpy.data.collections]
    for collection, _hidden in saved_collections:
        collection.hide_render = False
    for o in bpy.data.objects:
        if o is obj:
            continue
        if o.type in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            saved.append((o, o.hide_render))
            o.hide_render = True
    prev = obj.hide_render
    obj.hide_render = False
    try:
        yield
    finally:
        obj.hide_render = prev
        for o, h in saved:
            try:
                o.hide_render = h
            except ReferenceError:  # object purged mid-loop
                pass
        for collection, hidden in saved_collections:
            try:
                collection.hide_render = hidden
            except ReferenceError:
                pass
        if not linked_to_root:
            try:
                root_collection.objects.unlink(obj)
            except (ReferenceError, RuntimeError):
                pass


def _png_max(path):
    """Max pixel value of a saved atlas PNG (0..1), for detecting a collapsed bake."""
    try:
        im = bpy.data.images.load(str(path), check_existing=False)
        px = im.pixels
        m = max(px) if len(px) else 0.0
        bpy.data.images.remove(im)
        return float(m)
    except Exception:  # noqa: BLE001
        return 0.0


def _pbr_texture_validation(path, channel, threshold=1.0e-4):
    """Reject a linked bake that is black or spatially constant.

    A successful Cycles operator call is not sufficient evidence that a
    procedural socket made it into the atlas: unsupported nested closures can
    save an all-black image.  Padding is ignored by measuring the robust range
    of non-zero covered samples.  Constants are intentionally rejected for a
    linked source; only an originally unlinked socket may be represented by a
    glTF factor.
    """
    result = {"attempted": True, "result": "unreadable", "threshold": threshold}
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        from array import array
        pixels = image.pixels
        values = array("f", [0.0]) * len(pixels)
        pixels.foreach_get(values)
        bpy.data.images.remove(image)
        count = len(values) // 4
        step = max(1, count // 250000)
        samples = []
        for index in range(0, count, step):
            off = index * 4
            if channel == "base_color":
                value = (float(values[off]) + float(values[off + 1]) + float(values[off + 2])) / 3.0
            else:
                value = float(values[off])
            if math.isfinite(value) and value > threshold:
                samples.append(value)
        if not samples:
            result.update({"result": "black", "sample_count": 0, "robust_range": 0.0})
            return False, result
        samples.sort()
        low = samples[min(len(samples) - 1, int(len(samples) * 0.01))]
        high = samples[min(len(samples) - 1, max(0, int(len(samples) * 0.99) - 1))]
        robust_range = float(high - low)
        result.update({
            "result": "spatial" if robust_range > threshold else "constant",
            "sample_count": len(samples),
            "robust_range": robust_range,
            "percentile_01_99": [float(low), float(high)],
        })
        return robust_range > threshold, result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return False, result


def _normal_bake_validation(path, threshold=0.02):
    """Classify a baked tangent normal atlas while ignoring UV-edge outliers."""
    result = {"attempted": True, "result": "failed", "threshold": threshold}
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels = image.pixels
        # Blender RNA scalar access is extremely slow; copy the whole buffer once.
        from array import array
        pixel_values = array("f", [0.0]) * len(pixels)
        pixels.foreach_get(pixel_values)
        pixel_count = len(pixel_values) // 4
        step = max(1, pixel_count // 250000)
        histograms = [[0] * 256 for _ in range(3)]
        valid = 0
        for index in range(0, pixel_count, step):
            offset = index * 4
            rgb = [float(pixel_values[offset + channel]) for channel in range(3)]
            # Cycles leaves unbaked atlas background black; tangent normals have B>0.25.
            if rgb[2] <= 0.25:
                continue
            valid += 1
            for channel, value in enumerate(rgb):
                bucket = max(0, min(255, int(value * 255.0 + 0.5)))
                histograms[channel][bucket] += 1
        bpy.data.images.remove(image)
        # A few filtered/dilated pixels at UV island boundaries differ even for a
        # perfectly flat normal map. Use the central 98% of covered texels so those
        # edge outliers cannot turn a flat bake into a spatial texture.
        ranges = []
        for histogram in histograms:
            low_target = max(0, int(valid * 0.01))
            high_target = max(0, int(valid * 0.99) - 1)
            cumulative = 0
            low = None
            high = 0
            for bucket, count in enumerate(histogram):
                cumulative += count
                if cumulative > low_target and low is None:
                    low = bucket
                if cumulative > high_target:
                    high = bucket
                    break
            ranges.append((high - (low or 0)) / 255.0 if valid else 0.0)
        spatial = valid >= 16 and max(ranges) >= threshold
        result.update({
            "result": "spatial" if spatial else "flat",
            "sample_count": valid,
            "channel_percentile_01_99_range": ranges,
        })
        return spatial, result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return False, result

def _bake_principled_channel_legacy(obj, out_png, res, samples, input_name, *, non_color=True):
    """Bake a nested Principled value socket directly through an EMIT closure."""
    if not obj.material_slots or not _ensure_uv(obj):
        return False
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = 4
    img = bpy.data.images.new(f"bakeC_{obj.name}", width=res, height=res, alpha=False)
    if non_color:
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:  # noqa: BLE001
            pass

    replacements = []  # (node_tree, principled, emission, destination sockets)
    image_nodes = []
    seen_trees = set()
    def replace_tree(node_tree):
        if node_tree is None or node_tree.as_pointer() in seen_trees:
            return
        seen_trees.add(node_tree.as_pointer())
        for node in list(node_tree.nodes):
            if node.type == "GROUP":
                replace_tree(getattr(node, "node_tree", None))
                continue
            if node.type != "BSDF_PRINCIPLED":
                continue
            socket = node.inputs.get(input_name)
            output = node.outputs.get("BSDF")
            if socket is None or output is None or not output.is_linked:
                continue
            destinations = [link.to_socket for link in list(output.links)]
            emission = node_tree.nodes.new("ShaderNodeEmission")
            if socket.is_linked:
                node_tree.links.new(socket.links[0].from_socket, emission.inputs["Color"])
            else:
                raw = _socket_value(socket)
                if isinstance(raw, list):
                    rgb = [float(x) for x in raw[:3]]
                    while len(rgb) < 3:
                        rgb.append(rgb[-1] if rgb else 0.0)
                else:
                    rgb = [float(raw)] * 3
                emission.inputs["Color"].default_value = (*rgb, 1.0)
            for link in list(output.links):
                node_tree.links.remove(link)
            for destination in destinations:
                node_tree.links.new(emission.outputs["Emission"], destination)
            replacements.append((node_tree, node, emission, destinations))

    for slot in obj.material_slots:
        mat = slot.material
        if not (mat and mat.use_nodes and mat.node_tree):
            continue
        replace_tree(mat.node_tree)
        image_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        image_node.image = img
        image_node.select = True
        mat.node_tree.nodes.active = image_node
        image_nodes.append((mat.node_tree, image_node))

    if not replacements or not image_nodes:
        for node_tree, image_node in image_nodes:
            node_tree.nodes.remove(image_node)
        bpy.data.images.remove(img)
        return False

    ok = True
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for node_tree, _principled, _emission, _destinations in replacements:
            node_tree.update_tag()
        bpy.context.view_layer.update()
        bpy.ops.object.bake(type="EMIT")
        img.filepath_raw = out_png
        img.file_format = "PNG"
        img.save()
    except Exception as exc:  # noqa: BLE001
        print(f"[bake] channel FAIL {obj.name} ({input_name}): {exc}", file=sys.stderr)
        ok = False
    finally:
        for node_tree, image_node in image_nodes:
            try:
                node_tree.nodes.remove(image_node)
            except Exception:  # noqa: BLE001
                pass
        for node_tree, principled, emission, destinations in reversed(replacements):
            try:
                for link in list(emission.outputs["Emission"].links):
                    node_tree.links.remove(link)
                for destination in destinations:
                    node_tree.links.new(principled.outputs["BSDF"], destination)
                node_tree.nodes.remove(emission)
            except Exception:  # noqa: BLE001
                pass
        try:
            bpy.data.images.remove(img)
        except Exception:  # noqa: BLE001
            pass
    return ok


# Override the legacy in-group closure replacement above. Cycles can bake an
# EMISSION connected at Material Output reliably, but an Emission inserted only
# inside a nested group produced an all-black pass in Blender 4.2. Expose the
# selected Principled value through temporary group outputs, then connect it to
# a top-level Emission.
def _bake_principled_channel(obj, out_png, res, samples, input_name, *, non_color=True):
    if not obj.material_slots or not _ensure_uv(obj):
        return False
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = 4
    image = bpy.data.images.new(f"bakeV_{obj.name}", width=res, height=res, alpha=False)
    if non_color:
        try:
            image.colorspace_settings.name = "Non-Color"
        except Exception:  # noqa: BLE001
            pass

    interface_items = []
    temporary_nodes = []
    surface_replacements = []
    image_nodes = []
    processed_materials = set()
    serial = [0]

    def find_principled_path(input_socket, group_path):
        for link in list(input_socket.links):
            node = link.from_node
            if node.type == "BSDF_PRINCIPLED":
                return node, group_path
            if node.type == "GROUP" and getattr(node, "node_tree", None):
                for group_output in (n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"):
                    target = (
                        group_output.inputs.get(link.from_socket.identifier)
                        or group_output.inputs.get(link.from_socket.name)
                    )
                    if target is not None:
                        found = find_principled_path(target, group_path + [node])
                        if found:
                            return found
            for nested_input in getattr(node, "inputs", ()):
                if nested_input.is_linked:
                    found = find_principled_path(nested_input, group_path)
                    if found:
                        return found
        return None

    def constant_output(node_tree, socket):
        raw = _socket_value(socket)
        if isinstance(raw, list):
            node = node_tree.nodes.new("ShaderNodeRGB")
            rgb = [float(x) for x in raw[:3]]
            while len(rgb) < 3:
                rgb.append(rgb[-1] if rgb else 0.0)
            node.outputs["Color"].default_value = (*rgb, 1.0)
            output = node.outputs["Color"]
        else:
            node = node_tree.nodes.new("ShaderNodeValue")
            node.outputs["Value"].default_value = float(raw)
            output = node.outputs["Value"]
        temporary_nodes.append((node_tree, node))
        return output

    def expose_through_groups(principled, group_path):
        socket = principled.inputs.get(input_name)
        if socket is None:
            return None
        current = socket.links[0].from_socket if socket.is_linked else constant_output(principled.id_data, socket)
        for group_node in reversed(group_path):
            group_tree = group_node.node_tree
            serial[0] += 1
            name = f"__robomituba_bake_{input_name.replace(' ', '_')}_{serial[0]}"
            socket_type = "NodeSocketColor" if input_name == "Base Color" else "NodeSocketFloat"
            item = group_tree.interface.new_socket(name=name, in_out="OUTPUT", socket_type=socket_type)
            interface_items.append((group_tree, item))
            group_output = next((n for n in group_tree.nodes if n.type == "GROUP_OUTPUT"), None)
            if group_output is None:
                return None
            target = group_output.inputs.get(name)
            if target is None:
                return None
            # Group Output inputs are single-link sockets. Infinigen groups often
            # already expose a socket with the same semantic value; Blender keeps
            # the original link and silently evaluates our temporary output as
            # disconnected unless it is removed first.
            for link in list(target.links):
                group_tree.links.remove(link)
            group_tree.links.new(current, target)
            group_tree.update_tag()
            current = group_node.outputs.get(name)
            if current is None:
                return None
        return current

    for slot in obj.material_slots:
        material = slot.material
        if not (material and material.use_nodes and material.node_tree):
            continue
        if material.as_pointer() in processed_materials:
            continue
        processed_materials.add(material.as_pointer())
        tree = material.node_tree
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
        surface = output.inputs.get("Surface") if output else None
        if surface is None or not surface.is_linked:
            continue
        found = find_principled_path(surface, [])
        if not found:
            continue
        principled, group_path = found
        value_output = expose_through_groups(principled, group_path)
        if value_output is None:
            continue
        original = surface.links[0].from_socket
        tree.links.remove(surface.links[0])
        emission = tree.nodes.new("ShaderNodeEmission")
        tree.links.new(value_output, emission.inputs["Color"])
        tree.links.new(emission.outputs["Emission"], surface)
        temporary_nodes.append((tree, emission))
        surface_replacements.append((tree, surface, original, emission))
        image_node = tree.nodes.new("ShaderNodeTexImage")
        image_node.image = image
        image_node.select = True
        tree.nodes.active = image_node
        image_nodes.append((tree, image_node))
        tree.update_tag()

    if not surface_replacements or not image_nodes:
        ok = False
    else:
        ok = True
        try:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.context.view_layer.update()
            bpy.ops.object.bake(type="EMIT")
            image.filepath_raw = out_png
            image.file_format = "PNG"
            image.save()
        except Exception as exc:  # noqa: BLE001
            print(f"[bake] exposed channel FAIL {obj.name} ({input_name}): {exc}", file=sys.stderr)
            ok = False

    for tree, image_node in image_nodes:
        try:
            tree.nodes.remove(image_node)
        except Exception:  # noqa: BLE001
            pass
    for tree, surface, original, emission in reversed(surface_replacements):
        try:
            for link in list(surface.links):
                tree.links.remove(link)
            tree.links.new(original, surface)
        except Exception:  # noqa: BLE001
            pass
    for tree, node in reversed(temporary_nodes):
        try:
            tree.nodes.remove(node)
        except Exception:  # noqa: BLE001
            pass
    for tree, item in reversed(interface_items):
        try:
            tree.interface.remove(item)
        except Exception:  # noqa: BLE001
            pass
    try:
        bpy.data.images.remove(image)
    except Exception:  # noqa: BLE001
        pass
    return ok

def _bake_roughness(obj, out_png, res, samples):
    """Bake the actual nested Principled Roughness socket through EMIT."""
    return _bake_principled_channel(obj, out_png, res, samples, "Roughness")


def _bake_metallic(obj, out_png, res, samples):
    """Bake metallic through nested Principled networks using an EMIT substitution."""
    return _bake_principled_channel(obj, out_png, res, samples, "Metallic")


def _patch_mtl_map(mtl_path, tex_rel, key):
    """Add a texture map line (`<key> <tex_rel>`) to every material in an OBJ's .mtl.

    The render pipeline's _extract_obj_mtl_material reads these per-object atlas refs
    (map_Kd=albedo, map_Pr=roughness, map_Pm=metallic, norm=normal). Drops any
    existing line for the same key before re-adding it under each newmtl.
    """
    import os as _os
    if not _os.path.exists(mtl_path):
        return
    kl = key.lower()
    out_lines = []
    for line in open(mtl_path, "r", errors="ignore"):
        if line.lstrip().lower().startswith(kl + " ") or line.lstrip().lower().startswith(kl):
            # drop any existing line for this exact key (avoid map_Pr matching map_Pm: compare token)
            tok = line.lstrip().split(None, 1)[0].lower() if line.strip() else ""
            if tok == kl:
                continue
        out_lines.append(line.rstrip("\n"))
        if line.lstrip().lower().startswith("newmtl"):
            out_lines.append(f"{key} {tex_rel}")
    with open(mtl_path, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")


def _patch_mtl_map_kd(mtl_path, tex_rel):
    """Albedo convenience wrapper (kept for the existing call site)."""
    _patch_mtl_map(mtl_path, tex_rel, "map_Kd")


def _strip_mtl_diffuse(mtl_path):
    """Remove diffuse/spec colour + texture lines from an OBJ's .mtl.

    For analytic specular/transparent materials (mirror, glass) we want the
    render path's _extract_obj_mtl_material to return None so the authoring
    binding's conductor/dielectric strategy is used instead of being overridden
    by a textured roughplastic. That helper only returns None when the MTL has
    neither Kd nor map_Kd, so we drop both (plus Ks/specular + bump maps).
    """
    import os as _os
    if not _os.path.exists(mtl_path):
        return
    drop = ("kd ", "map_kd", "ks ", "map_ks", "map_bump", "bump ")
    out_lines = []
    for line in open(mtl_path, "r", errors="ignore"):
        low = line.lstrip().lower()
        if any(low.startswith(p) for p in drop):
            continue
        out_lines.append(line.rstrip("\n"))
    with open(mtl_path, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")


def _export_obj(obj, path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.obj_export(
        filepath=path,
        export_selected_objects=True,
        forward_axis="NEGATIVE_Z",
        up_axis="Y",
        apply_modifiers=True,
        export_materials=True,
        # Don't export vertex normals: Infinigen meshes contain degenerate/zero-area
        # triangles whose normals are invalid (NaN/zero) and abort Mitsuba's loader.
        # Mitsuba computes smooth normals itself for face-bearing meshes.
        export_normals=False,
        export_uv=True,
        # Triangulate: Infinigen meshes have large n-gons that produce >1024-char
        # face lines, which Mitsuba's OBJ loader rejects. Triangles keep lines short
        # and guarantee per-face normals.
        export_triangulated_mesh=True,
        path_mode="COPY",
    )


def _export_glb(obj, path):
    # The glTF gatherer ignores selected objects whose source collection is hidden,
    # even with use_visible=False. Several Infinigen structure/curve objects then
    # produced a valid-looking 132-byte GLB containing no mesh. Link a temporary
    # object proxy into the visible scene root; modifiers, GN and mesh/material data
    # stay shared and export_apply evaluates them without mutating the source.
    proxy = obj.copy()
    proxy.name = f"__gltf_export__{obj.name}"
    proxy.matrix_world = obj.matrix_world.copy()
    proxy.hide_viewport = False
    proxy.hide_render = False
    proxy.hide_select = False
    bpy.context.scene.collection.objects.link(proxy)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        proxy.select_set(True)
        bpy.context.view_layer.objects.active = proxy
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB",
            use_selection=True,
            use_visible=False,
            use_renderable=False,
            export_apply=True,
            export_yup=True,
        )
    finally:
        bpy.data.objects.remove(proxy, do_unlink=True)


def _glb_mesh_contract(path):
    result = {
        "valid": False, "mesh_count": 0, "primitive_count": 0,
        "position_primitive_count": 0, "texcoord0_primitive_count": 0, "issues": [],
    }
    try:
        with open(path, "rb") as fh:
            magic, version, total_length = struct.unpack("<4sII", fh.read(12))
            if magic != b"glTF" or version != 2:
                raise ValueError("not a GLB v2 file")
            chunk_length, chunk_type = struct.unpack("<II", fh.read(8))
            if chunk_type != 0x4E4F534A:
                raise ValueError("first GLB chunk is not JSON")
            document = json.loads(fh.read(chunk_length))
        if total_length != os.path.getsize(path):
            result["issues"].append("header length does not match file size")
        accessors = document.get("accessors") or []
        meshes = document.get("meshes") or []
        result["mesh_count"] = len(meshes)
        for mesh in meshes:
            for primitive in mesh.get("primitives") or []:
                result["primitive_count"] += 1
                attrs = primitive.get("attributes") or {}
                for semantic, counter in (
                    ("POSITION", "position_primitive_count"),
                    ("TEXCOORD_0", "texcoord0_primitive_count"),
                ):
                    accessor_index = attrs.get(semantic)
                    if isinstance(accessor_index, int) and 0 <= accessor_index < len(accessors):
                        if int(accessors[accessor_index].get("count") or 0) > 0:
                            result[counter] += 1
                indices = primitive.get("indices")
                if indices is not None and not (
                    isinstance(indices, int) and 0 <= indices < len(accessors)
                    and int(accessors[indices].get("count") or 0) > 0
                ):
                    result["issues"].append("primitive has invalid/empty indices accessor")
        if result["primitive_count"] == 0:
            result["issues"].append("GLB has no mesh primitives")
        if result["position_primitive_count"] != result["primitive_count"]:
            result["issues"].append("not every primitive has non-empty POSITION")
        if result["texcoord0_primitive_count"] != result["primitive_count"]:
            result["issues"].append("not every primitive has non-empty TEXCOORD_0")
        result["valid"] = not result["issues"]
    except Exception as exc:  # noqa: BLE001
        result["issues"].append(str(exc))
    return result



def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_principled_sockets(node_tree, socket_name, seen=None):
    """Yield Principled sockets through arbitrarily nested shader groups."""
    if node_tree is None:
        return
    seen = seen if seen is not None else set()
    key = node_tree.as_pointer()
    if key in seen:
        return
    seen.add(key)
    for node in node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            socket = node.inputs.get(socket_name)
            if socket is not None:
                yield socket
        elif node.type == "GROUP" and getattr(node, "node_tree", None) is not None:
            yield from _iter_principled_sockets(node.node_tree, socket_name, seen)

def _node_tree_has_normal_detail(node_tree, seen=None):
    if node_tree is None:
        return False
    seen = seen if seen is not None else set()
    key = node_tree.as_pointer()
    if key in seen:
        return False
    seen.add(key)
    for node in node_tree.nodes:
        if node.type in {"BUMP", "NORMAL_MAP"}:
            return True
        if node.type == "GROUP" and _node_tree_has_normal_detail(getattr(node, "node_tree", None), seen):
            return True
    return False

def _pbr_input_contract(obj):
    """Describe spatial/constant Principled channels, including nested groups."""
    material_slots = [slot for slot in obj.material_slots if slot.material is not None]
    if not material_slots:
        return {
            "base_color": {"source": "constant", "constants": [[0.6, 0.6, 0.6]]},
            "roughness": {"source": "constant", "constants": [0.6]},
            "metallic": {"source": "constant", "constants": [0.0]},
            "normal": {"source": "not_applicable", "constants": []},
        }
    # Analytic/non-Principled closures (e.g. Glass BSDF) are materialized by
    # the optical-class adapter. They do not expose glTF metallic-roughness
    # sockets, so requiring synthetic albedo/roughness bakes here would turn
    # a valid analytic material into a false strict-export failure.
    has_principled = any(
        mat and mat.use_nodes and mat.node_tree
        and any(_iter_principled_sockets(mat.node_tree, "Base Color"))
        for slot in material_slots
        for mat in (slot.material,)
    )
    if not has_principled:
        return {
            "base_color": {"source": "not_applicable", "constants": []},
            "roughness": {"source": "not_applicable", "constants": []},
            "metallic": {"source": "unresolved", "constants": [0.0]},
            "normal": {"source": "not_applicable", "constants": []},
        }
    specs = {
        "base_color": "Base Color",
        "roughness": "Roughness",
        "metallic": "Metallic",
        "normal": "Normal",
    }
    out = {}
    for key, socket_name in specs.items():
        linked = False
        constants = []
        found = False
        for slot in material_slots:
            mat = slot.material
            if not (mat and mat.use_nodes and mat.node_tree):
                continue
            sockets = list(_iter_principled_sockets(mat.node_tree, socket_name))
            found = found or bool(sockets)
            for socket in sockets:
                linked = linked or bool(socket.is_linked)
                if not socket.is_linked and key != "normal":
                    value = _socket_value(socket)
                    if isinstance(value, list):
                        value = value[:3]
                    constants.append(value)
            if key == "normal":
                linked = linked or _node_tree_has_normal_detail(mat.node_tree)
        mixed_constant = False
        if key != "normal" and len(constants) > 1 and not linked:
            distinct = {json.dumps(value, sort_keys=True) for value in constants}
            mixed_constant = len(distinct) > 1
        if key == "normal":
            out[key] = {"source": "linked" if linked else "not_applicable", "constants": []}
        elif found:
            out[key] = {
                "source": (
                    "linked" if linked else
                    "mixed_constant" if mixed_constant else
                    "constant"
                ),
                "constants": constants,
            }
        else:
            # Unknown nested shaders remain bake-required for color/roughness.
            # Metallic gets a dielectric 0.0 so the channel stays renderable, but
            # it is an assumption, not a traced socket: mark it `unresolved` so it
            # is never confused with a genuinely unlinked metallic=0 factor.
            out[key] = {
                "source": "linked" if key in {"base_color", "roughness"} else "unresolved",
                "constants": [0.0] if key == "metallic" else [],
            }
    return out


@contextlib.contextmanager
def _gltf_pbr_materials(
    obj,
    material_records,
    *,
    base_color_path=None,
    roughness_path=None,
    metallic_path=None,
    normal_path=None,
):
    """Temporarily replace slots with glTF-compatible materials using baked atlases."""
    image_cache = {}

    def _image(path, *, non_color):
        if not path or not os.path.isfile(path):
            return None
        key = (path, non_color)
        if key in image_cache:
            return image_cache[key]
        image = bpy.data.images.load(path, check_existing=True)
        try:
            image.colorspace_settings.name = "Non-Color" if non_color else "sRGB"
        except Exception:
            pass
        image_cache[key] = image
        return image

    base_image = _image(base_color_path, non_color=False)
    rough_image = _image(roughness_path, non_color=True)
    metal_image = _image(metallic_path, non_color=True)
    normal_image = _image(normal_path, non_color=True)
    originals = []
    temps = []
    try:
        for index, slot in enumerate(obj.material_slots):
            original = slot.material
            if original is None:
                continue
            original_name = original.name
            backup_name = f"__infinigen_original__{index}__{original_name}"
            original.name = backup_name
            temp = bpy.data.materials.new(name=original_name)
            temp.use_nodes = True
            nt = temp.node_tree
            nt.nodes.clear()
            output = nt.nodes.new("ShaderNodeOutputMaterial")
            principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
            nt.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
            rec = material_records.get(original_name) or {}
            base = rec.get("base_color") or [0.6, 0.6, 0.6]
            principled.inputs["Base Color"].default_value = (
                float(base[0]), float(base[1]), float(base[2]), 1.0
            )
            principled.inputs["Roughness"].default_value = float(rec.get("roughness", 0.6) or 0.6)
            principled.inputs["Metallic"].default_value = float(rec.get("metallic", 0.0) or 0.0)
            if base_image:
                node = nt.nodes.new("ShaderNodeTexImage")
                node.image = base_image
                nt.links.new(node.outputs["Color"], principled.inputs["Base Color"])
            if rough_image:
                node = nt.nodes.new("ShaderNodeTexImage")
                node.image = rough_image
                nt.links.new(node.outputs["Color"], principled.inputs["Roughness"])
            if metal_image:
                node = nt.nodes.new("ShaderNodeTexImage")
                node.image = metal_image
                nt.links.new(node.outputs["Color"], principled.inputs["Metallic"])
            if normal_image:
                node = nt.nodes.new("ShaderNodeTexImage")
                node.image = normal_image
                normal = nt.nodes.new("ShaderNodeNormalMap")
                nt.links.new(node.outputs["Color"], normal.inputs["Color"])
                nt.links.new(normal.outputs["Normal"], principled.inputs["Normal"])
            originals.append((slot, original, original_name))
            temps.append(temp)
            slot.material = temp
        yield
    finally:
        for slot, original, _original_name in originals:
            slot.material = original
        for temp in temps:
            try:
                bpy.data.materials.remove(temp)
            except Exception:
                pass
        for _slot, original, original_name in originals:
            original.name = original_name


def _channel_record(source, texture_rel, *, constant=None, colorspace="raw", resolution=None):
    if texture_rel:
        return {
            "mode": "texture", "ref": texture_rel, "source": source,
            "colorspace": colorspace, "resolution": resolution,
        }
    if source == "not_applicable":
        return {"mode": "not_applicable", "source": source}
    return {"mode": "constant", "value": constant, "source": source, "colorspace": colorspace}

def main():
    args = _argv_after_ddash()
    out_dir = args[args.index("--out") + 1] if "--out" in args else "/tmp/infinigen_export"
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    skip = int(args[args.index("--skip") + 1]) if "--skip" in args else 0
    # Repeatable so several known objects can be re-baked in one Blender load. This
    # matters for multi-GB Infinigen scenes where startup dominates a targeted audit.
    only_substrs = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--only"]
    # Fast fix path: re-export OBJs (with the UV-before-export fix) and re-point each
    # MTL at the EXISTING atlas PNGs instead of re-baking. Valid because Smart-UV-
    # Project is deterministic, so the re-exported UV matches the UV the existing
    # atlases were baked against (verified). Turns a ~5.5 h re-bake into a ~minutes
    # re-export. Implies no bake.
    reuse_atlas = "--reuse-atlas" in args
    no_glb = "--no-glb" in args
    do_bake = "--bake" in args
    # Targeted re-bake of ONLY the objects whose (present) UV is degenerate/zero-area
    # -- the black-atlas cause. Combine with --merge to splice the re-baked units back
    # into the existing full scene_manifest.json (matched by blender_name, reusing each
    # unit's existing id so the right mesh/texture files are overwritten in place).
    only_degenerate = "--only-degenerate" in args
    merge = "--merge" in args
    bake_res = int(args[args.index("--bake-res") + 1]) if "--bake-res" in args else 512
    bake_samples = int(args[args.index("--bake-samples") + 1]) if "--bake-samples" in args else 12
    # Per-texel PBR maps (roughness/normal/metallic) in addition to albedo. Opt-in
    # because each is a full extra Cycles bake (~4x bake time). Metallic uses the
    # EMIT trick; skip it with --no-bake-metallic if only roughness/normal wanted.
    bake_pbr = "--no-bake-pbr" not in args
    bake_metallic = bake_pbr and "--no-bake-metallic" not in args
    # Skip baking objects above this polygon count (Smart-UV-project + Cycles bake get
    # slow/heavy on multi-million-poly meshes). Default keeps small/medium objects; raise
    # it (e.g. 2000000) to also bake high-poly diffuse decoratives now that _render_isolate
    # keeps bake memory bounded.
    max_bake_poly = int(args[args.index("--max-poly") + 1]) if "--max-poly" in args else 0
    allow_incomplete_pbr = "--allow-incomplete-pbr" in args

    # ── mesh decimation (policy-gated; DEFAULT off = zero behaviour change) ──
    # The decimation POLICY (how much to cut per object) is isolated in
    # mesh_decimation.py so the still-undecided compression rules evolve there while
    # this call-site stays fixed. Runs on the live bpy mesh in the per-object loop
    # (before _ensure_uv/_export_obj) so OBJ + baked atlas + GLB all reflect it.
    decimate_policy_name = args[args.index("--decimate-policy") + 1] if "--decimate-policy" in args else "none"
    decimate_min_polys = int(args[args.index("--decimate-min-polys") + 1]) if "--decimate-min-polys" in args else 50000
    decimate_ratio = float(args[args.index("--decimate-ratio") + 1]) if "--decimate-ratio" in args else 0.30
    decimation_policy = None
    _DecCtx = _decimate_object = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from mesh_decimation import (resolve_policy as _resolve_dec_policy,
                                      DecimationContext as _DecCtx, decimate_object as _decimate_object)
        decimation_policy = _resolve_dec_policy(decimate_policy_name, min_faces=decimate_min_polys, ratio=decimate_ratio)
        if decimate_policy_name not in ("none", "off", ""):
            print(f"[decimate] policy={decimation_policy.name} min_polys={decimate_min_polys} ratio={decimate_ratio}")
    except Exception as _dec_exc:  # noqa: BLE001
        print(f"[decimate] disabled ({_dec_exc})")

    meshes_dir = os.path.join(out_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    textures_dir = os.path.join(out_dir, "textures")
    if do_bake:
        os.makedirs(textures_dir, exist_ok=True)

    scene_id = args[args.index("--scene-id") + 1] if "--scene-id" in args else os.path.basename(os.path.normpath(out_dir))
    manifest = {
        "export_contract_version": 2,
        "scene_id": scene_id,
        "source_blend": bpy.data.filepath,
        "unit_system": bpy.context.scene.unit_settings.system,
        "unit_scale": bpy.context.scene.unit_settings.scale_length,
        "axis_note": "meshes exported Y-up (Blender Z-up). authoring 2D = world XY.",
        "units": [],
        "materials": {},
        "lights": [],
        "cameras": [],
    }

    # Materials first (shared dict; units reference by name).
    for mat in bpy.data.materials:
        try:
            manifest["materials"][mat.name] = _extract_material(mat)
        except Exception as exc:  # noqa: BLE001
            manifest["materials"][mat.name] = {"name": mat.name, "error": str(exc),
                                               "base_color": _name_color(mat.name)}

    mesh_objs = [
        o for o in bpy.data.objects
        if o.type == "MESH" and len(o.data.polygons) > 0
    ]
    # Skip placeholder duplicates entirely.
    def _is_placeholder(o):
        return any("placeholder" in c.name.lower() for c in o.users_collection) or \
            "placeholder" in o.name.lower()
    mesh_objs = [o for o in mesh_objs if not _is_placeholder(o)]
    mesh_objs.sort(key=lambda o: o.name)
    if only_substrs:
        needles = [value.lower() for value in only_substrs]
        mesh_objs = [o for o in mesh_objs if any(value in o.name.lower() for value in needles)]
    if only_degenerate:
        mesh_objs = [o for o in mesh_objs if o.data.uv_layers and _uv_is_degenerate(o.data)]
    total_renderable = len(mesh_objs)
    manifest["renderable_unit_count"] = total_renderable
    if skip:
        mesh_objs = mesh_objs[skip:]
    if limit:
        mesh_objs = mesh_objs[:limit]

    # Merge mode: preload the existing manifest so re-baked units splice back in
    # (matched by blender_name), and reuse each object's existing `id` so the OBJ/MTL/
    # atlas filenames overwrite in place rather than forking a new (unsuffixed) name.
    manifest_path = os.path.join(out_dir, "scene_manifest.json")
    existing_manifest = None
    existing_oid_by_name = {}
    partial_export = bool(only_substrs or only_degenerate or skip or limit)
    if partial_export and os.path.exists(manifest_path) and not merge:
        raise RuntimeError("partial export refuses to overwrite a full manifest; pass --merge")
    if merge and os.path.exists(manifest_path):
        with open(manifest_path) as _mf:
            existing_manifest = json.load(_mf)
        for _u in existing_manifest.get("units", []):
            if _u.get("blender_name"):
                existing_oid_by_name[_u["blender_name"]] = _u.get("id")
        print(f"[export] merge: {len(existing_manifest.get('units', []))} existing units, "
              f"re-baking {len(mesh_objs)}", flush=True)

    # Memory hygiene for big scenes (14M-poly Infinigen blends OOM on low-RAM/WSL
    # boxes mid-bake). Disabling global undo stops Blender from snapshotting the
    # whole scene on every operator (bake/select/export ×N objects) — the single
    # biggest accumulation source in a long headless batch.
    try:
        bpy.context.preferences.edit.use_global_undo = False
    except Exception:  # noqa: BLE001
        pass

    used_ids = set()
    baked_count = 0
    fail_count = 0
    total = len(mesh_objs)
    bar = _tqdm(total=total, desc="export", unit="obj", file=sys.stderr,
                dynamic_ncols=True) if _tqdm else None
    if bar is None:
        print(f"[export] exporting {total} units (bake={'on' if do_bake else 'off'})…", flush=True)
    # When the bar is active, mute stdout for the whole loop so Blender's *deferred*
    # operator reports ("Info: Baking map saved …", flushed between ops) don't clutter
    # the console. The bar is on stderr; our own logs use bar.write/stderr. In no-tqdm
    # mode we leave stdout alone so the fallback progress prints remain visible.
    _loop_mute = _silence_fds(1) if bar is not None else contextlib.nullcontext()
    with _loop_mute:
      for i, obj in enumerate(mesh_objs):
        if bar is not None:
            bar.set_postfix_str(f"{obj.name[:22]} bake={baked_count} fail={fail_count}")
        kind, sem, subtype = _classify(obj)
        oid = _sanitize(obj.name)
        if merge and obj.name in existing_oid_by_name and existing_oid_by_name[obj.name]:
            # Reuse the id the full export assigned this object so we overwrite its
            # existing mesh/texture files instead of creating an unsuffixed duplicate.
            oid = existing_oid_by_name[obj.name]
        elif oid in used_ids:
            oid = f"{oid}_{i}"
        used_ids.add(oid)

        bmin, bmax = _world_bbox(obj)
        # Origin-local export: the render (`_obj_shape`) translates the mesh by the
        # authoring center + base_height, so the OBJ must be centred at its own
        # origin (horizontal bbox centre at X/Z=0, bottom at Y=0). We temporarily
        # offset the object in Blender, export, then restore. Orientation is left
        # baked into the mesh (yaw=0 in authoring) so the AABB footprint stays valid.
        cx_b = (bmin[0] + bmax[0]) / 2.0       # Blender world X centre
        cy_b = (bmin[1] + bmax[1]) / 2.0       # Blender world Y centre
        zmin_b = bmin[2]                        # Blender world Z (height) min
        offset = Vector((-cx_b, -cy_b, -zmin_b))
        orig_mw = obj.matrix_world.copy()
        obj.matrix_world = Matrix.Translation(offset) @ orig_mw
        hide_state = _unhide(obj)

        # mesh decimation (policy-gated) — on the live bpy mesh, before UV/OBJ/bake so
        # the reduced mesh flows into the exported OBJ, the baked atlas, and the GLB.
        decimation_record = None
        if decimation_policy is not None and _decimate_object is not None:
            _dslots = [{"name": ms.material.name,
                        "optical_class": manifest["materials"].get(ms.material.name, {}).get("optical_class", "diffuse")}
                       for ms in obj.material_slots if ms.material]
            _dctx = _DecCtx(object_id=oid, n_faces=len(obj.data.polygons), kind=kind,
                            semantic_type=sem, subtype=subtype, factory=_factory_of(obj.name) or "",
                            optical_class=(_dslots[0]["optical_class"] if _dslots else "diffuse"),
                            material_slots=_dslots, bbox_min=tuple(bmin), bbox_max=tuple(bmax),
                            has_baked_normal=False)
            decimation_record = _decimate_object(obj, decimation_policy, _dctx)
            if decimation_record.get("decimated"):
                _log(f"[decimate] {obj.name}: {decimation_record['faces_before']}"
                     f"→{decimation_record['faces_after']} ({decimation_record['policy']})", bar)
            elif decimation_record.get("error"):
                _log(f"[decimate] {obj.name} FAIL: {decimation_record['error']}", bar)

        obj_rel = f"meshes/{oid}.obj"
        glb_rel = f"meshes/{oid}.glb"
        baked_rel = None
        baked_roughness = baked_normal = baked_metallic = None
        pbr_inputs = _pbr_input_contract(obj)
        uv_valid = bool(_ensure_uv(obj))
        uv_layer = obj.data.uv_layers.active.name if uv_valid and obj.data.uv_layers.active else None

        try:
            with _silence_fds(1, 2):
                _export_obj(obj, os.path.join(out_dir, obj_rel))
        except Exception as exc:  # noqa: BLE001
            _log(f"[export] OBJ fallback FAIL {obj.name}: {exc}", bar)
            obj_rel = None

        slot_mats = [ms.material.name for ms in obj.material_slots if ms.material]
        unit_oc = (manifest["materials"].get(slot_mats[0], {}).get("optical_class", "diffuse")
                   if slot_mats else "diffuse")
        if "mirror" in (obj.name or "").lower() or "mirror" in (_factory_of(obj.name) or "").lower():
            unit_oc = "mirror"
            if slot_mats and manifest["materials"].get(slot_mats[0]) is not None:
                manifest["materials"][slot_mats[0]]["optical_class"] = "mirror"

        # Bake procedural channels in the original world frame. World/Object/Generated
        # coordinates in Infinigen shaders must not see the origin-normalizing export
        # transform or a spatial network can collapse to a constant.
        obj.matrix_world = orig_mw
        atlas_abs = {
            "base_color": os.path.join(textures_dir, f"{oid}_albedo.png"),
            "roughness": os.path.join(textures_dir, f"{oid}_roughness.png"),
            "metallic": os.path.join(textures_dir, f"{oid}_metallic.png"),
            "normal": os.path.join(textures_dir, f"{oid}_normal.png"),
        }
        atlas_rel = {
            "base_color": f"textures/{oid}_albedo.png",
            "roughness": f"textures/{oid}_roughness.png",
            "metallic": f"textures/{oid}_metallic.png",
            "normal": f"textures/{oid}_normal.png",
        }
        normal_validation = {"attempted": False, "result": "not_applicable"}
        bake_validations = {}
        if reuse_atlas:
            for key, path in atlas_abs.items():
                if os.path.isfile(path):
                    if key == "base_color":
                        baked_rel = atlas_rel[key]
                    elif key == "roughness":
                        baked_roughness = atlas_rel[key]
                    elif key == "metallic":
                        baked_metallic = atlas_rel[key]
                    else:
                        baked_normal = atlas_rel[key]
        elif do_bake and (max_bake_poly <= 0 or len(obj.data.polygons) <= max_bake_poly):
            with _render_isolate(obj):
                if pbr_inputs["base_color"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_albedo(obj, atlas_abs["base_color"], bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["base_color"], "base_color"
                            )
                            if not spatial:
                                # Some nested/displacement closures evaluate to
                                # black when exposed through a temporary EMIT
                                # socket, while Blender's native DIFFUSE color
                                # pass still returns the material color without
                                # direct/indirect lighting.
                                if _bake_pass(
                                    obj,
                                    atlas_abs["base_color"],
                                    bake_res,
                                    bake_samples,
                                    bake_type="DIFFUSE",
                                    color_pass=True,
                                ):
                                    fallback_spatial, fallback_validation = _pbr_texture_validation(
                                        atlas_abs["base_color"], "base_color"
                                    )
                                    fallback_validation["fallback_from"] = validation.get("result")
                                    fallback_validation["fallback_pass"] = "DIFFUSE_COLOR"
                                    validation = fallback_validation
                                    spatial = fallback_spatial
                            bake_validations["base_color"] = validation
                            keep_constant = (
                                pbr_inputs["base_color"]["source"] == "mixed_constant"
                                and validation.get("result") == "constant"
                            )
                            if spatial or keep_constant:
                                baked_rel = atlas_rel["base_color"]
                                baked_count += 1
                            else:
                                try:
                                    os.unlink(atlas_abs["base_color"])
                                except FileNotFoundError:
                                    pass
                if bake_pbr and pbr_inputs["roughness"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_roughness(obj, atlas_abs["roughness"], bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["roughness"], "roughness"
                            )
                            if not spatial:
                                # Blender's ROUGHNESS pass can evaluate nested
                                # Principled closures that do not survive the
                                # temporary EMIT graph.
                                if _bake_pass(
                                    obj,
                                    atlas_abs["roughness"],
                                    bake_res,
                                    bake_samples,
                                    bake_type="ROUGHNESS",
                                    non_color=True,
                                ):
                                    fallback_spatial, fallback_validation = _pbr_texture_validation(
                                        atlas_abs["roughness"], "roughness"
                                    )
                                    fallback_validation["fallback_from"] = validation.get("result")
                                    fallback_validation["fallback_pass"] = "ROUGHNESS"
                                    validation = fallback_validation
                                    spatial = fallback_spatial
                            bake_validations["roughness"] = validation
                            keep_constant = (
                                pbr_inputs["roughness"]["source"] == "mixed_constant"
                                and validation.get("result") == "constant"
                            )
                            if spatial or keep_constant:
                                baked_roughness = atlas_rel["roughness"]
                            else:
                                try:
                                    os.unlink(atlas_abs["roughness"])
                                except FileNotFoundError:
                                    pass
                if bake_pbr and bake_metallic and pbr_inputs["metallic"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_metallic(obj, atlas_abs["metallic"], bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["metallic"], "metallic"
                            )
                            bake_validations["metallic"] = validation
                            keep_constant = (
                                pbr_inputs["metallic"]["source"] == "mixed_constant"
                                and validation.get("result") == "constant"
                            )
                            if spatial or keep_constant:
                                baked_metallic = atlas_rel["metallic"]
                            else:
                                try:
                                    os.unlink(atlas_abs["metallic"])
                                except FileNotFoundError:
                                    pass
                if bake_pbr and obj.material_slots:
                    normal_validation = {"attempted": True, "result": "failed"}
                    with _silence_fds(1):
                        normal_ok = _bake_normal(
                            obj, atlas_abs["normal"], bake_res, bake_samples
                        )
                    if normal_ok:
                        spatial, normal_validation = _normal_bake_validation(atlas_abs["normal"])
                        if spatial:
                            baked_normal = atlas_rel["normal"]
                            pbr_inputs["normal"] = {"source": "linked", "constants": []}
                        else:
                            try:
                                os.unlink(atlas_abs["normal"])
                            except FileNotFoundError:
                                pass
                            pbr_inputs["normal"] = {"source": "not_applicable", "constants": []}
                    else:
                        pbr_inputs["normal"] = {"source": "linked", "constants": []}
                else:
                    pbr_inputs["normal"] = {"source": "not_applicable", "constants": []}

        # Keep the legacy MTL useful for an explicit fallback, but GLB is authoritative.
        mtl_abs = os.path.join(out_dir, f"meshes/{oid}.mtl")
        for key, mtl_key, rel in (
            ("base_color", "map_Kd", baked_rel),
            ("roughness", "map_Pr", baked_roughness),
            ("metallic", "map_Pm", baked_metallic),
            ("normal", "norm", baked_normal),
        ):
            if obj_rel and rel:
                _patch_mtl_map(mtl_abs, f"../{rel}", mtl_key)
        if obj_rel and unit_oc in ("mirror", "glass"):
            _strip_mtl_diffuse(mtl_abs)

        # Export origin-local Y-up GLB with temporary glTF-compatible materials.
        obj.matrix_world = Matrix.Translation(offset) @ orig_mw
        glb_validation = {"valid": False, "issues": ["GLB export disabled"]}
        if not no_glb:
            try:
                with _gltf_pbr_materials(
                    obj, manifest["materials"],
                    base_color_path=atlas_abs["base_color"] if baked_rel else None,
                    roughness_path=atlas_abs["roughness"] if baked_roughness else None,
                    metallic_path=atlas_abs["metallic"] if baked_metallic else None,
                    normal_path=atlas_abs["normal"] if baked_normal else None,
                ):
                    with _silence_fds(1, 2):
                        _export_glb(obj, os.path.join(out_dir, glb_rel))
                glb_validation = _glb_mesh_contract(os.path.join(out_dir, glb_rel))
                if not glb_validation["valid"]:
                    raise RuntimeError("; ".join(glb_validation["issues"]))
            except Exception as exc:  # noqa: BLE001
                _log(f"[export] GLB FAIL {obj.name}: {exc}", bar)
                glb_rel = None
        else:
            glb_rel = None

        channel_textures = {
            "base_color": baked_rel,
            "roughness": baked_roughness,
            "metallic": baked_metallic,
            "normal": baked_normal,
        }
        pbr_channels = {}
        pbr_issues = []
        pbr_assumptions = []
        for key in ("base_color", "roughness", "metallic", "normal"):
            source = pbr_inputs[key]["source"]
            texture_ref = channel_textures[key]
            if source == "linked" and not texture_ref:
                pbr_issues.append(f"{key}: linked input was not baked")
            if source == "unresolved":
                # No traced Principled socket: the emitted factor is an assumed
                # default, not evidence that the source value is really this.
                pbr_assumptions.append(f"{key}: assumed default factor (no traced socket)")
            constants = pbr_inputs[key].get("constants") or []
            default_constant = {
                "base_color": [[0.6, 0.6, 0.6]],
                "roughness": [0.6],
                "metallic": [0.0],
                "normal": [],
            }[key]
            pbr_channels[key] = _channel_record(
                source, texture_ref, constant=constants or default_constant,
                colorspace="srgb" if key == "base_color" else "raw",
                resolution=[bake_res, bake_res] if texture_ref else None,
            )
            if key == "normal":
                pbr_channels[key]["bake_validation"] = normal_validation
            else:
                pbr_channels[key]["bake_validation"] = bake_validations.get(
                    key, {"attempted": False, "result": "not_applicable"}
                )
            validation = pbr_channels[key]["bake_validation"]
            if source == "linked" and validation.get("result") != "spatial":
                pbr_issues.append(
                    f"{key}: linked bake validation={validation.get('result', 'unknown')}"
                )
        if not uv_valid:
            pbr_issues.append("invalid UV")
        if not glb_rel or not os.path.isfile(os.path.join(out_dir, glb_rel)):
            pbr_issues.append("missing GLB")
        pbr_contract = {
            "status": "ok" if not pbr_issues else "degraded",
            "self_contained_glb": bool(glb_rel and not pbr_issues),
            "channels": pbr_channels,
            "issues": pbr_issues,
            "assumptions": pbr_assumptions,
        }
        glb_digest = _sha256_file(os.path.join(out_dir, glb_rel)) if glb_rel else None

        _restore_hide(obj, hide_state)
        obj.matrix_world = orig_mw
        if pbr_issues and not allow_incomplete_pbr:
            raise RuntimeError(f"{obj.name}: strict GLB/PBR export failed: {', '.join(pbr_issues)}")

        # Authoring placement (Y-up world, axis flip authoring_y = -blender_y).
        # size_m is the world AABB: [x_extent, height_extent, z_extent] (Mitsuba xyz).
        place_center = [cx_b, -cy_b]
        place_size = [bmax[0] - bmin[0], bmax[2] - bmin[2], bmax[1] - bmin[1]]
        place_base_height = zmin_b

        mats = [ms.material.name for ms in obj.material_slots if ms.material]
        manifest["units"].append({
            "id": oid,
            "blender_name": obj.name,
            "kind": kind,
            "semantic_type": sem,
            "subtype": subtype,
            "factory": _factory_of(obj.name),
            "collections": [c.name for c in obj.users_collection],
            "world_bbox_min": bmin,
            "world_bbox_max": bmax,
            "dimensions": list(obj.dimensions),
            "yaw_deg": _yaw_deg(obj),
            # Authoring placement consumed by Stage 2 (render translate(center)).
            "place_center": place_center,        # [authoring_x, authoring_y] = [bx, -by]
            "place_size_m": place_size,          # [x, height, z] world AABB
            "place_base_height_m": place_base_height,
            "polys": len(obj.data.polygons),
            "decimation": decimation_record,
            "materials": mats,
            "optical_class": unit_oc,
            "mesh_obj": obj_rel,
            "mesh_obj_fallback": obj_rel,
            "mesh_glb": glb_rel,
            "glb_sha256": glb_digest,
            "glb_validation": glb_validation,
            "uv": {"layer": uv_layer, "valid": uv_valid},
            "material_slots": [
                {"name": name, "optical_class": (manifest["materials"].get(name) or {}).get("optical_class", "diffuse")}
                for name in mats
            ],
            "pbr": pbr_contract,
            "baked_albedo": baked_rel,
            "baked_roughness": baked_roughness,
            "baked_normal": baked_normal,
            "baked_metallic": baked_metallic,
        })
        # Drop zero-user datablocks left behind by bake/export (temp images, meshes,
        # node groups) so RAM doesn't creep across hundreds of objects. orphans_purge
        # only removes data with no users, so shared materials/textures still in use
        # by later objects are untouched. Every few objects keeps the scan cost low.
        if (i + 1) % 5 == 0:
            try:
                bpy.data.orphans_purge(do_recursive=True)
            except Exception:  # noqa: BLE001
                pass
        if bar is not None:
            bar.update(1)
        elif (i + 1) % 10 == 0 or (i + 1) == total:
            pct = round(100 * (i + 1) / max(total, 1))
            print(f"[export] {i + 1}/{total} ({pct}%) units · bake={baked_count} fail={fail_count}", flush=True)
    if bar is not None:
        bar.close()

    # Lights
    for o in bpy.data.objects:
        if o.type != "LIGHT":
            continue
        L = o.data
        bmin, bmax = (None, None)
        wp = o.matrix_world.translation
        entry = {
            "name": o.name,
            "type": L.type,
            "color": list(L.color),
            "energy": float(getattr(L, "energy", 0.0) or 0.0),
            "world_pos": list(wp),
            # Authoring placement (Y-up, authoring_y = -blender_y); base_height = blender Z.
            "place_center": [wp.x, -wp.y],
            "place_base_height_m": wp.z,
        }
        if L.type == "AREA":
            entry["size"] = [float(getattr(L, "size", 0.0)), float(getattr(L, "size_y", 0.0) or getattr(L, "size", 0.0))]
        if L.type == "SUN":
            d = o.matrix_world.to_3x3() @ Vector((0, 0, -1))
            entry["direction"] = list(d.normalized())
        manifest["lights"].append(entry)

    # Cameras
    for o in bpy.data.objects:
        if o.type != "CAMERA":
            continue
        cam = o.data
        fov_x = 2 * math.degrees(math.atan((cam.sensor_width / 2.0) / cam.lens)) if cam.lens else 60.0
        manifest["cameras"].append({
            "name": o.name,
            "world_pos": list(o.matrix_world.translation),
            "matrix_world": [list(r) for r in o.matrix_world],
            "lens_mm": cam.lens,
            "sensor_width_mm": cam.sensor_width,
            "fov_x_deg": fov_x,
        })

    if merge and existing_manifest is not None:
        # Splice re-baked units into the existing full manifest by blender_name; keep
        # all other units, and the existing lights/cameras (unchanged in a partial run).
        by_name = {u.get("blender_name"): u for u in existing_manifest.get("units", [])}
        for u in manifest["units"]:
            by_name[u.get("blender_name")] = u
        existing_manifest["units"] = list(by_name.values())
        existing_manifest["renderable_unit_count"] = manifest.get("renderable_unit_count")
        existing_manifest.setdefault("materials", {}).update(manifest["materials"])
        final_manifest = existing_manifest
        n_replaced = len(manifest["units"])
    else:
        final_manifest = manifest
        n_replaced = len(manifest["units"])
    final_manifest["export_contract_version"] = 2
    manifest_tmp = manifest_path + f".tmp.{os.getpid()}"
    with open(manifest_tmp, "w") as f:
        json.dump(final_manifest, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(manifest_tmp, manifest_path)
    print(f"[export] DONE units={len(final_manifest['units'])} (re-baked {n_replaced}) "
          f"materials={len(final_manifest['materials'])} lights={len(final_manifest.get('lights', []))} "
          f"cameras={len(final_manifest.get('cameras', []))} -> {manifest_path}")


if __name__ == "__main__":
    main()
