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
import shutil
import subprocess
import tempfile
import struct
import sys
from pathlib import Path

import bpy  # type: ignore
from mathutils import Matrix, Vector  # type: ignore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pbr_bake_coverage import adaptive_resolutions, validate_uv_coverage

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


STRICT_PBR_PROFILE = "strict-pbr-v1"
# v2 fixes the historical object-atlas bug: a mesh with two material slots used
# to bake both slots into one image and Stage 2 then sampled that same image from
# each Principled material.  Keep v1 readable for published scenes, but make new
# IR geometry explicitly slot-addressable.
STRICT_PBR_SLOT_AWARE_PROFILE = "strict-pbr-v2-slot-aware"
IR_BOOTSTRAP_PROFILE = "ir-bootstrap-v1"
STAGE1_PROFILES = {STRICT_PBR_PROFILE, STRICT_PBR_SLOT_AWARE_PROFILE, IR_BOOTSTRAP_PROFILE}


def _configure_cycles_bake_device(requested: str) -> tuple[str, list[str]]:
    """Select one explicit Cycles bake backend and audit the exposed devices."""
    device = str(requested or "CPU").upper()
    if device not in {"CPU", "CUDA", "OPTIX"}:
        raise ValueError(f"unsupported Cycles bake device: {requested!r}")
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    if device == "CPU":
        scene.cycles.device = "CPU"
        print("[bake-device] requested=CPU enabled=CPU", flush=True)
        return device, ["CPU"]
    preferences = bpy.context.preferences.addons["cycles"].preferences
    preferences.compute_device_type = device
    preferences.get_devices()
    enabled = []
    for candidate in preferences.devices:
        candidate.use = candidate.type == device
        if candidate.use:
            enabled.append(candidate.name)
    if not enabled:
        raise RuntimeError(
            f"Cycles exposes no {device} device under CUDA_VISIBLE_DEVICES="
            f"{os.environ.get('CUDA_VISIBLE_DEVICES', '')!r}"
        )
    scene.cycles.device = "GPU"
    print(f"[bake-device] requested={device} enabled={','.join(enabled)}", flush=True)
    return device, enabled


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

    # Repository-authored architectural overlays carry explicit Blender custom
    # properties.  They must win over generic mesh/structure suffixes so the
    # OpticalNav importer and graph retain transparent-partition semantics.
    if obj.get("transparent_partition") or obj.get("glass_wall"):
        return "structure", "glass_wall", "transparent_partition"
    if obj.get("glass_door"):
        return "door", "glass_door", "door"

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


def _face_atlas_uv(obj):
    """Assign one non-overlapping UV tile to every source polygon.

    Smart Project normally supplies a much better continuous chart, but some
    Infinigen generated assets contain coincident/repeated components.  Blender
    is allowed to stack those islands, which is visually harmless in Blender yet
    makes a single glTF PBR atlas ambiguous.  This last-resort atlas deliberately
    trades continuity for an unambiguous per-face parametrisation: every polygon
    receives a unique tile and Cycles still evaluates the original procedural
    shader at each surface point while baking it.

    It is only selected after the strict coverage audit rejects a fresh Smart UV
    layer, never as the normal unwrap path.
    """
    try:
        import numpy as np

        mesh = obj.data
        polygon_count = len(mesh.polygons)
        if polygon_count <= 0:
            return False
        while mesh.uv_layers:
            mesh.uv_layers.remove(mesh.uv_layers[0])
        layer = mesh.uv_layers.new(name="IRFaceAtlasUV")
        side = int(math.ceil(math.sqrt(polygon_count)))
        inset = 0.06
        scale = (1.0 - 2.0 * inset) / float(side)
        uv = np.zeros((len(mesh.loops), 2), dtype=np.float32)
        for polygon_index, polygon in enumerate(mesh.polygons):
            col = polygon_index % side
            row = polygon_index // side
            base_u = (col + inset) / float(side)
            base_v = (row + inset) / float(side)
            loop_indices = range(polygon.loop_start, polygon.loop_start + polygon.loop_total)
            count = max(3, int(polygon.loop_total))
            for local_index, loop_index in enumerate(loop_indices):
                if polygon.loop_total == 3:
                    local_u, local_v = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))[local_index]
                elif polygon.loop_total == 4:
                    local_u, local_v = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))[local_index]
                else:
                    # N-gons are rare after the LOD pass.  A convex regular
                    # polygon gives every corner a finite, non-degenerate local
                    # chart without relying on the source's potentially broken
                    # topology UVs.
                    theta = (2.0 * math.pi * local_index / float(count)) - (math.pi / 2.0)
                    local_u = 0.5 + 0.5 * math.cos(theta)
                    local_v = 0.5 + 0.5 * math.sin(theta)
                uv[loop_index, 0] = base_u + scale * local_u
                uv[loop_index, 1] = base_v + scale * local_v
        layer.data.foreach_set("uv", uv.ravel())
        mesh.update()
        ok = bool(mesh.uv_layers) and not _uv_is_degenerate(mesh)
        if ok:
            print(f"[bake] face-atlas UV fallback: {obj.name} polygons={polygon_count}", file=sys.stderr)
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"[bake] face-atlas UV fallback FAIL {obj.name}: {exc}", file=sys.stderr)
        return False


def _face_atlas_min_resolution(obj, requested_resolution):
    """Keep enough texels across a face-atlas tile after a UV repair.

    The coverage bake has an 8px dilation margin at 1K.  Four texels per tile
    therefore leaves high-face-count meshes with no reliable interior sample:
    the coverage validator quite correctly reports the small material part as
    unbaked even though the LOD mesh itself is valid.  Eight texels is the
    minimum that leaves an interior at the 1--4K atlas sizes used here.
    """
    polygons = max(1, len(getattr(obj.data, "polygons", ())))
    target = int(math.ceil(math.sqrt(polygons))) * 8
    resolution = max(int(requested_resolution), target)
    return 1 << int(math.ceil(math.log2(max(1, resolution))))


def _ensure_uv(obj, *, force=False):
    """Guarantee a *usable* UV map for baking. Smart-UV-project objects that have
    none, OR whose existing UV is degenerate (zero-area — see _uv_is_degenerate).

    Procedural Infinigen materials sample shader values per surface point, so any
    non-overlapping UV (even a fresh Smart Project) captures the look correctly.
    """
    me = obj.data
    if not force and me.uv_layers and not _uv_is_degenerate(me):
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
    bake.margin = _bake_margin(res)

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
        with _neutral_cycles_film_exposure(scene):
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


def _bake_margin(res):
    """Pixel-space island dilation scaled with adaptive atlas resolution."""
    return max(4, min(32, int(res) // 128))


def _bake_coverage(obj, out_png, res):
    """Bake a material-independent white mask proving which UV texels received a bake."""
    if not obj.material_slots:
        return False
    material = bpy.data.materials.new(name=f"__robomituba_coverage_{obj.name}")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    originals = [slot.material for slot in obj.material_slots]
    try:
        for slot in obj.material_slots:
            slot.material = material
        bpy.context.view_layer.update()
        return _bake_pass(obj, out_png, res, 1, bake_type="EMIT", non_color=True)
    finally:
        for slot, original in zip(obj.material_slots, originals):
            slot.material = original
        try:
            bpy.data.materials.remove(material)
        except Exception:  # noqa: BLE001
            pass
        bpy.context.view_layer.update()


def _coverage_validation(obj, path, *, max_unbaked_ratio=0.001):
    """Validate saved coverage against every loop triangle and material slot."""
    result = {"attempted": True, "passed": False, "reason": "unreadable"}
    image = None
    try:
        import numpy as np
        from array import array

        image = bpy.data.images.load(str(path), check_existing=False)
        width, height = int(image.size[0]), int(image.size[1])
        pixels = array("f", [0.0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
        # Blender's pixel buffer begins at the lower-left; saved PNG readers begin at top-left.
        coverage = np.asarray(pixels, np.float32).reshape(height, width, 4)[::-1, :, 0] > 0.5
        mesh = obj.data
        mesh.calc_loop_triangles()
        layer = mesh.uv_layers.active
        if layer is None:
            result["reason"] = "missing_uv_layer"
            return result
        triangles = []
        areas = []
        material_indices = []
        for triangle in mesh.loop_triangles:
            triangles.append([[float(layer.data[index].uv.x), float(layer.data[index].uv.y)]
                              for index in triangle.loops])
            areas.append(float(triangle.area))
            material_indices.append(int(mesh.polygons[triangle.polygon_index].material_index))
        # A face atlas has one deliberately tiny island per polygon.  Testing
        # its analytic/rasterized union at a fixed 512px grid reports those
        # islands as "overlap" even when their UV tiles are mathematically
        # disjoint.  Validate it at the saved coverage resolution instead.
        # Ordinary authored UVs retain the inexpensive 512px overlap audit.
        face_atlas = str(layer.name or "").startswith("IRFaceAtlasUV")
        overlap_resolution = max(width, height) if face_atlas else 512
        result = validate_uv_coverage(
            np.asarray(triangles), np.asarray(areas), np.asarray(material_indices), coverage,
            max_unbaked_ratio=float(max_unbaked_ratio),
            # Preserve 99.9% whole-object coverage while absorbing raster
            # quantisation in tiny material slots on million-face foliage.
            max_material_slot_unbaked_ratio=max(
                0.005, 4.0 * float(max_unbaked_ratio),
            ),
            overlap_resolution=overlap_resolution,
            known_disjoint_face_atlas=face_atlas,
        )
        result["attempted"] = True
        result["resolution"] = [width, height]
        result["uv_layer"] = str(layer.name or "")
        result["overlap_validation_resolution"] = int(overlap_resolution)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result
    finally:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except Exception:  # noqa: BLE001
                pass


def _bake_coverage_adaptive(obj, out_png, base_res, max_res, max_unbaked_ratio):
    """Bake coverage, repairing a UV that fails the full surface audit once.

    `_ensure_uv`'s cheap preflight only proves that every slot has *some* valid
    triangle. The coverage validator additionally catches partially degenerate,
    overlapping, or severely under-resolved source UVs. For those cases,
    discard the old layer and rebuild it before deciding that a linked PBR
    channel is unbakeable. Merely escalating an under-resolved source atlas to
    4K cannot repair islands that were packed at near-zero area.
    """
    attempts = []
    rebuilt_uv = False
    for resolution in adaptive_resolutions(base_res, max_res):
        baked = bool(_bake_coverage(obj, out_png, resolution))
        validation = (
            _coverage_validation(obj, out_png, max_unbaked_ratio=max_unbaked_ratio)
            if baked else {"attempted": True, "passed": False, "reason": "bake_failed"}
        )
        validation["resolution"] = [resolution, resolution]
        attempts.append(validation)
        if validation.get("passed"):
            result = dict(validation)
            result["adaptive_attempts"] = attempts
            result["uv_rebuild_attempted"] = rebuilt_uv
            return resolution, result
        print(
            "[bake] coverage retry "
            f"{obj.name}: res={resolution} reason={validation.get('reason')} "
            f"unbaked={validation.get('referenced_unbaked_ratio', 'n/a')} "
            f"slot_max={validation.get('max_material_slot_unbaked_ratio', 'n/a')} "
            f"uv_p01={validation.get('uv_triangle_pixel_area_p01', 'n/a')}",
            file=sys.stderr,
        )
        if validation.get("reason") in {
            "degenerate_uv_triangles",
            "overlapping_uv_triangles",
            "referenced_unbaked_texels",
        }:
            if rebuilt_uv:
                break
            rebuilt_uv = True
            rebuilt = _ensure_uv(obj, force=True)
            validation["uv_rebuild_attempted"] = True
            validation["uv_rebuild_succeeded"] = bool(rebuilt)
            if not rebuilt:
                break
            # Validate the rebuilt layer at the same resolution before escalating;
            # this keeps a repair of a small mesh cheap and deterministic.
            baked = bool(_bake_coverage(obj, out_png, resolution))
            repaired = (
                _coverage_validation(obj, out_png, max_unbaked_ratio=max_unbaked_ratio)
                if baked else {"attempted": True, "passed": False, "reason": "bake_failed"}
            )
            repaired["resolution"] = [resolution, resolution]
            repaired["uv_rebuild_attempted"] = True
            repaired["uv_rebuild_succeeded"] = True
            attempts.append(repaired)
            if repaired.get("passed"):
                result = dict(repaired)
                result["adaptive_attempts"] = attempts
                result["uv_rebuild_attempted"] = True
                return resolution, result
            print(
                "[bake] coverage repaired-UV retry "
                f"{obj.name}: res={resolution} reason={repaired.get('reason')} "
                f"unbaked={repaired.get('referenced_unbaked_ratio', 'n/a')} "
                f"slot_max={repaired.get('max_material_slot_unbaked_ratio', 'n/a')}",
                file=sys.stderr,
            )
            if repaired.get("reason") in {
                "degenerate_uv_triangles",
                "overlapping_uv_triangles",
                "referenced_unbaked_texels",
            }:
                # Smart Project can intentionally retain stacked islands for
                # coincident generated components.  That is not a valid shared
                # atlas contract, so rebuild as one unique tile per polygon
                # instead of accepting the overlap or silently downgrading a
                # linked PBR channel to a scalar factor.
                face_atlas_ok = _face_atlas_uv(obj)
                repaired["face_atlas_uv_attempted"] = True
                repaired["face_atlas_uv_succeeded"] = bool(face_atlas_ok)
                if not face_atlas_ok:
                    break
                face_base_resolution = min(
                    int(max_res), _face_atlas_min_resolution(obj, resolution)
                )
                # A unique tile eliminates UV ambiguity, but a high-face-count
                # LOD can still have tiles too small for Cycles' raster/bake
                # footprint.  Keep escalating after the face-atlas repair rather
                # than treating its first coverage pass as terminal.
                for face_resolution in adaptive_resolutions(face_base_resolution, max_res):
                    baked = bool(_bake_coverage(obj, out_png, face_resolution))
                    face_repaired = (
                        _coverage_validation(obj, out_png, max_unbaked_ratio=max_unbaked_ratio)
                        if baked else {"attempted": True, "passed": False, "reason": "bake_failed"}
                    )
                    face_repaired["resolution"] = [face_resolution, face_resolution]
                    face_repaired["uv_rebuild_attempted"] = True
                    face_repaired["uv_rebuild_succeeded"] = True
                    face_repaired["face_atlas_uv_attempted"] = True
                    face_repaired["face_atlas_uv_succeeded"] = True
                    attempts.append(face_repaired)
                    if face_repaired.get("passed"):
                        result = dict(face_repaired)
                        result["adaptive_attempts"] = attempts
                        result["uv_rebuild_attempted"] = True
                        return face_resolution, result
                    print(
                        "[bake] coverage face-atlas retry "
                        f"{obj.name}: res={face_resolution} reason={face_repaired.get('reason')} "
                        f"unbaked={face_repaired.get('referenced_unbaked_ratio', 'n/a')} "
                        f"slot_max={face_repaired.get('max_material_slot_unbaked_ratio', 'n/a')}",
                        file=sys.stderr,
                    )
                    # A face atlas should make genuine UV overlap impossible.
                    # At its first viable resolution, however, the overlap
                    # auditor can still be sampling subpixel tiles.  Continue
                    # through 2K -> 4K for *any* validation failure other than
                    # a bake operation itself failing.
                    if face_repaired.get("reason") == "bake_failed":
                        break
                break
    result = dict(attempts[-1]) if attempts else {
        "attempted": True, "passed": False, "reason": "no_resolution_attempted",
    }
    result["adaptive_attempts"] = attempts
    result["uv_rebuild_attempted"] = rebuilt_uv
    return int(max_res), result


def _bake_normal(obj, out_png, res, samples):
    return _bake_pass(obj, out_png, res, samples, bake_type="NORMAL", non_color=True)


@contextlib.contextmanager
def _isolated_material_slot(obj, slot_index):
    """Yield a disposable one-slot mesh for a slot-local Cycles bake.

    Cycles bakes every material slot that has the active image node.  That is
    correct for a single atlas, but not for the IR contract: a multi-slot wall
    needs one independent texture/provenance record per slot.  Duplicating the
    mesh is intentionally safer than temporarily deleting faces from the live
    object (the latter used to corrupt long-running resumable exports).
    """
    if slot_index < 0 or slot_index >= len(obj.material_slots):
        raise IndexError(f"invalid material slot {slot_index} for {obj.name}")
    material = obj.material_slots[slot_index].material
    if material is None:
        yield None
        return
    clone = obj.copy()
    clone.data = obj.data.copy()
    clone.name = f"__ir_slot_{obj.name}_{slot_index}"
    bpy.context.scene.collection.objects.link(clone)
    try:
        # Retain only faces belonging to this original slot, then make their
        # material index zero in the single-slot clone.
        mesh = clone.data
        selected = {poly.index for poly in mesh.polygons if int(poly.material_index) == int(slot_index)}
        if not selected:
            yield None
            return
        import bmesh  # Blender bundled module; keep non-bpy imports lightweight.
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            bm.faces.ensure_lookup_table()
            delete = [face for face in bm.faces if face.index not in selected]
            if delete:
                bmesh.ops.delete(bm, geom=delete, context="FACES")
            bm.to_mesh(mesh)
        finally:
            bm.free()
        mesh.materials.clear()
        mesh.materials.append(material)
        for poly in mesh.polygons:
            poly.material_index = 0
        clone.matrix_world = obj.matrix_world.copy()
        yield clone
    finally:
        try:
            bpy.data.objects.remove(clone, do_unlink=True)
        except Exception:  # noqa: BLE001
            pass


def _slot_atlas_paths(textures_dir, oid, slot):
    stem = f"{oid}__slot_{int(slot):02d}"
    return {
        "base_color": os.path.join(textures_dir, f"{stem}_albedo.png"),
        "roughness": os.path.join(textures_dir, f"{stem}_roughness.png"),
        "metallic": os.path.join(textures_dir, f"{stem}_metallic.png"),
        "normal": os.path.join(textures_dir, f"{stem}_normal.png"),
        "coverage": os.path.join(textures_dir, f"{stem}_coverage.png"),
    }


def _bake_slot_pbr_contract(obj, *, oid, slot, textures_dir, out_dir, bake_res,
                            max_bake_res, bake_samples, bake_pbr, bake_metallic,
                            max_unbaked_ratio, do_bake, glb_rel):
    """Bake and validate one material slot; return v2 slot-local contract/maps."""
    atlas_abs = _slot_atlas_paths(textures_dir, oid, slot)
    atlas_rel = {key: os.path.relpath(value, out_dir) for key, value in atlas_abs.items()}
    with _isolated_material_slot(obj, slot) as isolated:
        if isolated is None:
            return None
        inputs = _pbr_input_contract(isolated)
        uv_valid = bool(_ensure_uv(isolated))
        coverage = {"attempted": False, "passed": False, "reason": "not_baked"}
        validation = {}
        normal_validation = {"attempted": False, "result": "not_applicable"}
        baked = {key: None for key in ("base_color", "roughness", "metallic", "normal")}
        effective_res = int(bake_res)
        if do_bake and uv_valid:
            with _render_isolate(isolated):
                effective_res, coverage = _bake_coverage_adaptive(
                    isolated, atlas_abs["coverage"], bake_res, max_bake_res, max_unbaked_ratio
                )
                if coverage.get("passed"):
                    jobs = (
                        ("base_color", _bake_albedo, True),
                        ("roughness", _bake_roughness, bool(bake_pbr)),
                        ("metallic", _bake_metallic, bool(bake_pbr and bake_metallic)),
                    )
                    for channel, baker, enabled in jobs:
                        if not enabled or inputs[channel]["source"] not in {"linked", "mixed_constant"}:
                            continue
                        with _silence_fds(1):
                            ok = baker(isolated, atlas_abs[channel], effective_res, bake_samples)
                        if ok:
                            spatial, result = _pbr_texture_validation(
                                atlas_abs[channel], channel, coverage_path=atlas_abs["coverage"]
                            )
                            validation[channel] = result
                            if spatial or (inputs[channel]["source"] == "mixed_constant" and result.get("result") in {"constant", "black"}):
                                baked[channel] = atlas_rel[channel]
                    if bake_pbr and inputs["normal"]["source"] in {"linked", "mixed_constant"}:
                        normal_validation = {"attempted": True, "result": "failed"}
                        with _silence_fds(1):
                            normal_ok = _bake_normal(isolated, atlas_abs["normal"], effective_res, bake_samples)
                        if normal_ok:
                            spatial, normal_validation = _normal_bake_validation(atlas_abs["normal"])
                            if spatial:
                                baked["normal"] = atlas_rel["normal"]
                            else:
                                inputs["normal"] = {"source": "not_applicable", "constants": []}
        channels, issues, assumptions = {}, [], []
        for channel in ("base_color", "roughness", "metallic", "normal"):
            source = inputs[channel]["source"]
            ref = baked[channel]
            result = normal_validation if channel == "normal" else validation.get(channel, {"attempted": False, "result": "not_applicable"})
            if source == "linked" and not ref:
                issues.append(f"{channel}: linked input was not baked")
            if source == "linked" and result.get("result") != "spatial":
                issues.append(f"{channel}: linked bake validation={result.get('result', 'unknown')}")
            if source == "unresolved":
                assumptions.append(f"{channel}: assumed default factor (no traced socket)")
            default = {"base_color": [[0.6, 0.6, 0.6]], "roughness": [0.6], "metallic": [0.0], "normal": []}[channel]
            channels[channel] = _channel_record(
                source, ref, constant=inputs[channel].get("constants") or default,
                colorspace="srgb" if channel == "base_color" else "raw",
                resolution=[effective_res, effective_res] if ref else None,
            )
            channels[channel]["bake_validation"] = result
        if not uv_valid:
            issues.append("invalid UV")
        if do_bake and not coverage.get("passed"):
            issues.append("UV-referenced bake coverage failed: " + str(coverage.get("reason", "unknown")))
        if not glb_rel:
            issues.append("missing GLB")
        contract = {
            "status": "ok" if not issues else "degraded",
            "appearance_authoritative": not issues,
            "channels": channels,
            "coverage": {"ref": atlas_rel["coverage"] if coverage.get("passed") else None, **coverage},
            "issues": issues,
            "assumptions": assumptions,
            "material_slot": int(slot),
        }
        artifacts = {"coverage": contract["coverage"]["ref"], **baked}
        return contract, artifacts


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


@contextlib.contextmanager
def _neutral_cycles_film_exposure(scene):
    """Bake material properties without the scene's observation exposure.

    The kitchen source stores ``cycles.film_exposure=3``.  If inherited by EMIT
    property bakes it changes roughness 0.18 to about 0.54 and clips bright base
    colors.  One is Blender's neutral multiplier; restore the authored value after
    each bake so observation rendering remains unchanged.
    """
    previous = float(scene.cycles.film_exposure)
    scene.cycles.film_exposure = 1.0
    try:
        yield
    finally:
        scene.cycles.film_exposure = previous


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


def _pbr_texture_validation(
    path,
    channel,
    threshold=1.0e-4,
    *,
    coverage_path=None,
    minimum_cluster_fraction=1.0e-4,
    minimum_cluster_samples=16,
):
    """Reject a linked bake that is black or spatially constant.

    A successful Cycles operator call is not sufficient evidence that a
    procedural socket made it into the atlas: unsupported nested closures can
    save an all-black image.  When the companion coverage atlas is available,
    padding is ignored *exactly*, rather than by discarding the outer 1% of
    values.  This distinction matters for multi-material Infinigen meshes: a
    real, spatial material part can occupy less than 1% of an object's UV area
    (the kitchen SimpleBookcase's brushed-metal trim is 0.38%).  Treating it as
    an outlier silently converts a linked source to a scalar factor.

    Constants are intentionally rejected for a linked source; only an
    originally unlinked socket may be represented by a glTF factor.  The
    cluster trim merely rejects isolated raster artefacts: each extremum must
    have at least ``minimum_cluster_samples`` samples, or 0.01% of the covered
    atlas, behind it.
    """
    result = {"attempted": True, "result": "unreadable", "threshold": threshold}
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        from array import array
        pixels = image.pixels
        values = array("f", [0.0]) * len(pixels)
        pixels.foreach_get(values)
        width, height = int(image.size[0]), int(image.size[1])
        bpy.data.images.remove(image)
        coverage_values = None
        coverage_used = False
        if coverage_path and os.path.isfile(str(coverage_path)):
            coverage_image = bpy.data.images.load(str(coverage_path), check_existing=False)
            try:
                if tuple(int(v) for v in coverage_image.size[:]) == (width, height):
                    coverage_values = array("f", [0.0]) * len(coverage_image.pixels)
                    coverage_image.pixels.foreach_get(coverage_values)
                    coverage_used = True
            finally:
                bpy.data.images.remove(coverage_image)
        count = len(values) // 4
        step = max(1, count // 250000)
        samples = []
        for index in range(0, count, step):
            off = index * 4
            if coverage_values is not None and float(coverage_values[off]) <= 0.5:
                continue
            if channel == "base_color":
                value = tuple(float(values[off + component]) for component in range(3))
                # Preserve legacy all-black failure behaviour while measuring
                # true RGB variation rather than only luminance variation.
                valid = all(math.isfinite(component) for component in value) and max(value) > threshold
            else:
                value = float(values[off])
                valid = math.isfinite(value) and value > threshold
            if valid:
                samples.append(value)
        if not samples:
            result.update({
                "result": "black", "sample_count": 0, "robust_range": 0.0,
                "coverage_used": coverage_used,
            })
            return False, result
        cluster_samples = max(
            int(minimum_cluster_samples),
            int(math.ceil(len(samples) * float(minimum_cluster_fraction))),
        )
        cluster_samples = min(max(1, cluster_samples), max(1, len(samples) // 2))
        if channel == "base_color":
            ranges = []
            percentiles = []
            for component in range(3):
                component_values = sorted(value[component] for value in samples)
                low = component_values[cluster_samples - 1]
                high = component_values[-cluster_samples]
                ranges.append(float(high - low))
                percentiles.append([float(low), float(high)])
            robust_range = max(ranges)
            percentile_range = percentiles
        else:
            samples.sort()
            low = samples[cluster_samples - 1]
            high = samples[-cluster_samples]
            robust_range = float(high - low)
            percentile_range = [float(low), float(high)]
        result.update({
            "result": "spatial" if robust_range > threshold else "constant",
            "sample_count": len(samples),
            "robust_range": robust_range,
            "cluster_samples": cluster_samples,
            "minimum_cluster_fraction": float(minimum_cluster_fraction),
            "coverage_used": coverage_used,
            "percentile_cluster_range": percentile_range,
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
    scene.render.bake.margin = _bake_margin(res)
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
    scene.render.bake.margin = _bake_margin(res)
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
            with _neutral_cycles_film_exposure(scene):
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


def _gltfpack_binary():
    """Return the host-local meshoptimizer binary; never use a NAS build."""
    configured = os.environ.get("ROBOMITUBA_GLTFPACK")
    candidates = ([configured] if configured else []) + [
        str(Path.home() / "robomituba-build" / "meshoptimizer" / "gltfpack"),
        shutil.which("gltfpack"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise RuntimeError(
        "gltfpack fallback is required but unavailable; install meshoptimizer under "
        "$HOME/robomituba-build/meshoptimizer or set ROBOMITUBA_GLTFPACK"
    )


def _mesh_triangle_count(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _gltfpack_simplify_object(obj, target_max_triangles):
    """Simplify a Blender-decimator-resistant object through meshoptimizer.

    The temporary OBJ→GLB conversion is geometry-only transport: original Blender materials are
    reattached by slot name, and the imported node transform is converted back
    into the original object local space. Any UV/material ambiguity is fatal.
    """
    binary = _gltfpack_binary()
    source_mesh = obj.data
    source_materials = list(source_mesh.materials)
    source_material_names = [material.name if material else None for material in source_materials]
    source_triangles = _mesh_triangle_count(source_mesh)
    if source_triangles <= target_max_triangles:
        return {"backend": "meshoptimizer_gltfpack", "triangles_after": source_triangles, "skipped": True}
    source_matrix = obj.matrix_world.copy()
    source_had_uv = bool(source_mesh.uv_layers)
    imported_objects = []
    with tempfile.TemporaryDirectory(prefix="robomituba-gltfpack-") as tmp:
        input_path = Path(tmp) / "input.obj"
        output_path = Path(tmp) / "output.glb"
        # Blender GLB export can emit a node with a primitive that meshoptimizer
        # drops for Infinigen's degenerate procedural meshes.  OBJ triangulates
        # the same evaluated mesh and is a reliable geometry-only interchange.
        _export_obj(obj, str(input_path))
        ratio = max(1e-4, min(1.0, float(target_max_triangles) / float(source_triangles)))
        command = [
            binary, "-i", str(input_path), "-o", str(output_path),
            # ``-se 1`` permits 100% geometric error and can legally erase every
            # primitive for otherwise valid multi-material assets.  ``-sa`` already
            # requests the target ratio aggressively; keep meshoptimizer's bounded
            # error handling so the fallback cannot turn a chair into an empty GLB.
            "-si", f"{ratio:.9f}", "-sa",
            "-noq", "-km", "-kn", "-kv", "-vpf", "-vtf", "-vnf",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0 or not output_path.is_file():
            detail = (completed.stderr or completed.stdout or "gltfpack did not create output").strip()
            raise RuntimeError(f"gltfpack failed: {detail[-1200:]}")
        known_pointers = {candidate.as_pointer() for candidate in bpy.data.objects}
        try:
            bpy.ops.import_scene.gltf(filepath=str(output_path))
            imported_objects = [candidate for candidate in bpy.data.objects
                                if candidate.as_pointer() not in known_pointers and candidate.type == "MESH"]
            if len(imported_objects) != 1:
                raise RuntimeError(f"gltfpack import expected one mesh object, got {len(imported_objects)}")
            imported = imported_objects[0]
            candidate_mesh = imported.data.copy()
            candidate_mesh.transform(source_matrix.inverted() @ imported.matrix_world)
            if source_had_uv and not candidate_mesh.uv_layers:
                raise RuntimeError("gltfpack dropped an existing UV layer")
            imported_names = [material.name if material else None for material in candidate_mesh.materials]
            if len(source_materials) == 1:
                for poly in candidate_mesh.polygons:
                    poly.material_index = 0
            else:
                try:
                    from mesh_decimation import map_material_slot_indices
                    # gltfpack can omit source material slots that have no
                    # primitive after simplification. That is safe only when
                    # the omitted slots were already unused by the original
                    # mesh; restore the full original slot list below.
                    imported_to_source = map_material_slot_indices(
                        source_material_names, imported_names, allow_source_subset=True,
                    )
                    source_used = {int(poly.material_index) for poly in source_mesh.polygons}
                    omitted_used = source_used - set(imported_to_source.values())
                    if omitted_used:
                        raise ValueError(
                            "gltfpack dropped used material slot(s): " + ", ".join(map(str, sorted(omitted_used)))
                        )
                except ValueError as exc:
                    raise RuntimeError(f"gltfpack {exc}") from exc
                for poly in candidate_mesh.polygons:
                    if poly.material_index < 0 or poly.material_index >= len(imported_names):
                        raise RuntimeError("gltfpack polygon has an invalid material index")
                    poly.material_index = imported_to_source[poly.material_index]
            candidate_mesh.materials.clear()
            for material in source_materials:
                candidate_mesh.materials.append(material)
            triangles_after = _mesh_triangle_count(candidate_mesh)
            if triangles_after >= source_triangles:
                raise RuntimeError(
                    f"gltfpack did not reduce topology ({source_triangles}->{triangles_after} triangles)"
                )
            obj.data = candidate_mesh
            return {
                "backend": "meshoptimizer_gltfpack", "binary": binary,
                "source_triangles": source_triangles, "target_max_triangles": int(target_max_triangles),
                "triangles_after": triangles_after, "ratio_requested": ratio,
                "command": command[1:], "uv_preserved": bool(candidate_mesh.uv_layers),
                "material_slots_preserved": True,
            }
        finally:
            for imported in imported_objects:
                if imported.name in bpy.data.objects:
                    bpy.data.objects.remove(imported, do_unlink=True)


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


_RESUME_UNIT_STATE_SCHEMA = "robomituba.infinigen.stage1-unit-state.v1"


def _resume_unit_state_path(out_dir, object_id):
    return os.path.join(out_dir, ".stage1_unit_state", f"{object_id}.json")


def _load_resume_unit_state(out_dir, object_id, blender_name, *, bake_contract):
    """Load a per-unit completion checkpoint only when its contract still matches.

    The final scene manifest is deliberately atomic and therefore absent after
    an interrupted Stage-1 run.  A per-unit sidecar lets a later resume retain
    semantic decisions such as "normal was baked and proven flat", without
    ever treating a partial coverage image as complete.
    """
    path = _resume_unit_state_path(out_dir, object_id)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if (
        payload.get("schema") != _RESUME_UNIT_STATE_SCHEMA
        or payload.get("object_id") != object_id
        or payload.get("blender_name") != blender_name
        or payload.get("bake_contract") != bake_contract
    ):
        return None
    return payload


def _write_resume_unit_state(out_dir, payload):
    object_id = str(payload["object_id"])
    path = _resume_unit_state_path(out_dir, object_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = f"{path}.tmp.{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


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


def _reachable_principled_sockets(node_tree, socket_name):
    """Yield only surface-reachable Principled sockets with group-input bindings."""
    if node_tree is None:
        return []
    found = []

    def walk(socket, bindings, seen):
        for link in getattr(socket, "links", ()):
            node = link.from_node
            key = (node.as_pointer(), link.from_socket.identifier, socket.as_pointer())
            if key in seen:
                continue
            child_seen = set(seen)
            child_seen.add(key)
            if node.type == "GROUP_INPUT":
                binding = bindings.get(link.from_socket.identifier) or bindings.get(link.from_socket.name)
                if binding is not None:
                    outer, parent_bindings = binding
                    walk(outer, parent_bindings, child_seen)
                continue
            if node.type == "GROUP" and getattr(node, "node_tree", None):
                child_bindings = {}
                for inp in node.inputs:
                    child_bindings[inp.identifier] = (inp, bindings)
                    child_bindings[inp.name] = (inp, bindings)
                for group_output in (n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"):
                    target = (
                        group_output.inputs.get(link.from_socket.identifier)
                        or group_output.inputs.get(link.from_socket.name)
                    )
                    if target is not None:
                        walk(target, child_bindings, child_seen)
                        break
                continue
            if node.type == "BSDF_PRINCIPLED":
                target = node.inputs.get(socket_name)
                if target is not None:
                    found.append((target, bindings))
                continue
            for nested_input in getattr(node, "inputs", ()):
                if nested_input.is_linked:
                    walk(nested_input, bindings, child_seen)

    for output in (n for n in node_tree.nodes if n.type == "OUTPUT_MATERIAL"):
        surface = output.inputs.get("Surface")
        if surface is not None and surface.is_linked:
            walk(surface, {}, set())
    return found


def _bound_socket_constant(socket, bindings, seen=None):
    """Resolve constants passed through nested Group Input/Output sockets.

    Returns ``(True, value)`` only when the complete upstream expression is an
    authored constant. Any procedural/image/attribute expression remains linked.
    """
    seen = set() if seen is None else seen
    if socket is None:
        return False, None
    if not socket.is_linked:
        return True, _socket_value(socket)
    link = socket.links[0]
    node = link.from_node
    key = (node.as_pointer(), link.from_socket.identifier)
    if key in seen:
        return False, None
    seen = set(seen)
    seen.add(key)
    if node.type == "GROUP_INPUT":
        binding = bindings.get(link.from_socket.identifier) or bindings.get(link.from_socket.name)
        if binding is None:
            return False, None
        outer, parent_bindings = binding
        return _bound_socket_constant(outer, parent_bindings, seen)
    if node.type in {"RGB", "VALUE"}:
        return True, _socket_value(link.from_socket)
    if node.type == "REROUTE" and node.inputs:
        return _bound_socket_constant(node.inputs[0], bindings, seen)
    if node.type == "MAP_RANGE":
        # Infinigen's standard plastic/metal groups feed an authored outer
        # ``Roughness`` value through a Map Range node before the reachable
        # Principled socket.  A linked socket is not necessarily spatial: when
        # every Map Range input is an authored constant, the resulting value is
        # an authored constant too.  Treating that graph as procedural makes a
        # valid glTF factor look like a failed linked bake.
        #
        # Be intentionally conservative: only the scalar linear form is
        # folded.  Any vector/color input, non-linear interpolation, missing
        # input, or invalid denominator remains bake-required.
        if getattr(node, "data_type", "FLOAT") != "FLOAT" or getattr(node, "interpolation_type", "LINEAR") != "LINEAR":
            return False, None

        def _scalar(name):
            input_socket = node.inputs.get(name)
            resolved, value = _bound_socket_constant(input_socket, bindings, seen)
            if not resolved or isinstance(value, (list, tuple)):
                return False, None
            try:
                value = float(value)
            except (TypeError, ValueError):
                return False, None
            return (math.isfinite(value), value if math.isfinite(value) else None)

        values = {}
        for input_name in ("Value", "From Min", "From Max", "To Min", "To Max"):
            resolved, value = _scalar(input_name)
            if not resolved:
                return False, None
            values[input_name] = value
        denominator = values["From Max"] - values["From Min"]
        if abs(denominator) <= 1.0e-12:
            return False, None
        factor = (values["Value"] - values["From Min"]) / denominator
        output = values["To Min"] + factor * (values["To Max"] - values["To Min"])
        if getattr(node, "clamp", False):
            output = min(max(output, min(values["To Min"], values["To Max"])), max(values["To Min"], values["To Max"]))
        return True, float(output)
    if node.type == "GROUP" and getattr(node, "node_tree", None):
        child_bindings = {}
        for inp in node.inputs:
            child_bindings[inp.identifier] = (inp, bindings)
            child_bindings[inp.name] = (inp, bindings)
        for group_output in (n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"):
            target = (
                group_output.inputs.get(link.from_socket.identifier)
                or group_output.inputs.get(link.from_socket.name)
            )
            if target is not None:
                return _bound_socket_constant(target, child_bindings, seen)
    return False, None

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
    # The PBR atlas represents faces that are actually emitted by this object.
    # Infinigen frequently leaves construction-time material slots on a mesh
    # after all of their faces have been reassigned (Cube is one example: it
    # retains unused glass and metal slots).  Including those orphan slots in
    # the source contract creates false ``linked`` requirements for channels
    # with no coverage in the bake.  Keep unused slots in the GLB for Blender
    # compatibility, but do not let them define this object's render contract.
    used_material_indices = {
        int(poly.material_index)
        for poly in getattr(obj.data, "polygons", ())
        if 0 <= int(poly.material_index) < len(obj.material_slots)
    }
    material_slots = [
        slot for index, slot in enumerate(obj.material_slots)
        if index in used_material_indices and slot.material is not None
    ]
    # Preserve the old safe behaviour for unusual meshes with no polygons.
    if not material_slots and not used_material_indices:
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
        and bool(_reachable_principled_sockets(mat.node_tree, "Base Color"))
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
            sockets = _reachable_principled_sockets(mat.node_tree, socket_name)
            found = found or bool(sockets)
            for socket, bindings in sockets:
                is_constant, value = _bound_socket_constant(socket, bindings)
                linked = linked or not is_constant
                if is_constant and key != "normal":
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
    stage1_profile = (
        args[args.index("--stage1-profile") + 1]
        if "--stage1-profile" in args else STRICT_PBR_PROFILE
    )
    if stage1_profile not in STAGE1_PROFILES:
        raise ValueError(f"unsupported Stage-1 profile: {stage1_profile!r}")
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    derived_blend = args[args.index("--save-derived-blend") + 1] if "--save-derived-blend" in args else None
    ir_scene_domain_path = args[args.index("--ir-scene-domain") + 1] if "--ir-scene-domain" in args else None
    ir_domain_handles = []
    ir_domain_report = None
    if ir_scene_domain_path is not None:
        from blender_ir_scene_domain import apply_face_exclusion, load_domain
        _ir_domain = load_domain(Path(ir_scene_domain_path))
        ir_domain_handles, ir_domain_report = apply_face_exclusion(_ir_domain)
        print(f"[export] applied IR face exclusion selectors={ir_domain_report['resolved_selector_count']}", flush=True)
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
    if stage1_profile == IR_BOOTSTRAP_PROFILE:
        if do_bake:
            raise ValueError("ir-bootstrap-v1 forbids --bake")
        reuse_atlas = False
    # Targeted re-bake of ONLY the objects whose (present) UV is degenerate/zero-area
    # -- the black-atlas cause. Combine with --merge to splice the re-baked units back
    # into the existing full scene_manifest.json (matched by blender_name, reusing each
    # unit's existing id so the right mesh/texture files are overwritten in place).
    only_degenerate = "--only-degenerate" in args
    merge = "--merge" in args
    if derived_blend is not None and (limit or skip or merge):
        raise ValueError("--save-derived-blend requires one full non-merge export")
    bake_res = int(args[args.index("--bake-res") + 1]) if "--bake-res" in args else 512
    max_bake_res = int(args[args.index("--max-bake-res") + 1]) if "--max-bake-res" in args else 4096
    max_unbaked_ratio = (
        float(args[args.index("--max-unbaked-ratio") + 1])
        if "--max-unbaked-ratio" in args else 0.001
    )
    if max_bake_res < bake_res:
        raise ValueError("--max-bake-res must be >= --bake-res")
    bake_samples = int(args[args.index("--bake-samples") + 1]) if "--bake-samples" in args else 12
    requested_cycles_device = (
        args[args.index("--cycles-device") + 1]
        if "--cycles-device" in args else "CPU"
    )
    bake_device, bake_devices = (
        _configure_cycles_bake_device(requested_cycles_device)
        if do_bake else ("NONE", [])
    )
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
    decimate_strict = "--decimate-strict" in args
    decimation_policy = None
    _DecCtx = _decimate_object = None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from mesh_decimation import (resolve_policy as _resolve_dec_policy,
                                      DecimationContext as _DecCtx, decimate_object as _decimate_object, triangle_count as _triangle_count)
        decimation_policy = _resolve_dec_policy(decimate_policy_name, min_faces=decimate_min_polys, ratio=decimate_ratio)
        if decimate_policy_name not in ("none", "off", ""):
            print(f"[decimate] policy={decimation_policy.name} min_polys={decimate_min_polys} ratio={decimate_ratio} strict={decimate_strict}")
    except Exception as _dec_exc:  # noqa: BLE001
        print(f"[decimate] disabled ({_dec_exc})")
        if decimate_strict:
            raise

    meshes_dir = os.path.join(out_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    textures_dir = os.path.join(out_dir, "textures")
    if do_bake:
        os.makedirs(textures_dir, exist_ok=True)

    scene_id = args[args.index("--scene-id") + 1] if "--scene-id" in args else os.path.basename(os.path.normpath(out_dir))
    manifest = {
        "export_contract_version": 2,
        "stage1_profile": stage1_profile,
        "appearance_authority": (
            "stage1_pbr_atlases" if stage1_profile == STRICT_PBR_PROFILE else "source_blend_deferred"
        ),
        "bake_device": {
            "requested": requested_cycles_device,
            "effective": bake_device,
            "devices": bake_devices,
            "assigned_gpu": os.environ.get("ROBOMITUBA_ASSIGNED_BAKE_GPU"),
        },
        "scene_id": scene_id,
        "ir_scene_domain_ref": os.path.abspath(ir_scene_domain_path) if ir_scene_domain_path else None,
        "ir_face_exclusion": ir_domain_report,
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
              f"processing next {len(mesh_objs)} selected units", flush=True)

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
    reused_atlas_count = 0
    stale_atlas_rebake_count = 0
    fresh_atlas_bake_count = 0
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
        _pre_material_slots = [slot.material.name if slot.material else None for slot in obj.material_slots]
        _pre_used_material_indices = sorted({int(poly.material_index) for poly in obj.data.polygons})
        _pre_matrix_world = tuple(tuple(float(value) for value in row) for row in obj.matrix_world)
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
            _dctx = _DecCtx(object_id=oid, n_faces=_triangle_count(obj), kind=kind,
                            semantic_type=sem, subtype=subtype, factory=_factory_of(obj.name) or "",
                            optical_class=(_dslots[0]["optical_class"] if _dslots else "diffuse"),
                            material_slots=_dslots, bbox_min=tuple(bmin), bbox_max=tuple(bmax),
                            has_baked_normal=False)
            decimation_record = _decimate_object(
                obj, decimation_policy, _dctx, strict=decimate_strict,
                fallback=_gltfpack_simplify_object if decimate_strict and decimation_policy.name == "ir_semantic_lod_v1" else None,
            )
            if decimation_record.get("decimated"):
                _log(f"[decimate] {obj.name}: {decimation_record['triangles_before']}"
                     f"→{decimation_record['triangles_after']} triangles ({decimation_record['policy']})", bar)
            elif decimation_record.get("error"):
                _log(f"[decimate] {obj.name} FAIL: {decimation_record['error']}", bar)

        obj_rel = f"meshes/{oid}.obj"
        glb_rel = f"meshes/{oid}.glb"
        baked_rel = None
        baked_roughness = baked_normal = baked_metallic = None
        pbr_inputs = _pbr_input_contract(obj)
        # Some Infinigen structural meshes intentionally carry geometry only
        # (zero material slots).  Blender records their polygons with the
        # default material index 0, but there is no surface graph to bake.
        # They are still exported as UV-valid GLB geometry with explicit
        # default PBR factors; requiring a Cycles coverage bake for them would
        # always fail before it could create an active image node.
        requires_surface_bake = any(slot.material is not None for slot in obj.material_slots)
        resume_bake_contract = {
            "stage1_profile": stage1_profile,
            "cycles_device": bake_device,
            "bake_res": int(bake_res),
            "max_bake_res": int(max_bake_res),
            "max_unbaked_ratio": float(max_unbaked_ratio),
            "bake_pbr": bool(bake_pbr),
            "decimation_policy": getattr(decimation_policy, "name", None),
            "decimation_min_polys": int(decimate_min_polys),
        }
        resume_unit_state = (
            _load_resume_unit_state(
                out_dir, oid, obj.name, bake_contract=resume_bake_contract,
            ) if reuse_atlas else None
        )
        # A source normal network can be linked yet evaluate to a flat normal.
        # Stage 1 correctly discards that atlas and records not_applicable. On
        # resume, retain that completed semantic decision rather than treating
        # the intentionally absent PNG as an interrupted bake.
        prior_normal = (
            ((resume_unit_state.get("pbr") or {}).get("channels") or {}).get("normal")
            if resume_unit_state else None
        )
        if (
            isinstance(prior_normal, dict)
            and prior_normal.get("mode") == "not_applicable"
            and pbr_inputs.get("normal", {}).get("source") == "linked"
        ):
            pbr_inputs["normal"] = {"source": "not_applicable", "constants": []}
            _log(f"[resume] restored flat normal decision {obj.name}", bar)
        uv_valid = bool(_ensure_uv(obj))
        uv_layer = obj.data.uv_layers.active.name if uv_valid and obj.data.uv_layers.active else None
        if decimation_record is not None:
            _post_bmin, _post_bmax = _world_bbox(obj)
            _post_material_slots = [slot.material.name if slot.material else None for slot in obj.material_slots]
            _post_indices = {int(poly.material_index) for poly in obj.data.polygons}
            _post_matrix_world = tuple(tuple(float(value) for value in row) for row in obj.matrix_world)
            _aabb_values = tuple(_post_bmin) + tuple(_post_bmax)
            # Blender stores ``polygon.material_index == 0`` even when a mesh
            # deliberately has *no* material slots.  That is the unassigned
            # default, not a dangling primitive/material reference.  Treat it
            # as valid only for the empty-slot case; any other index would
            # still be invalid.  Without this distinction strict IR LOD
            # rejected geometry-only structural meshes such as
            # ``kitchen_0/0.exterior`` after an otherwise successful
            # decimation.
            _valid_indices = (
                _post_indices <= {0}
                if not _post_material_slots
                else all(0 <= index < len(_post_material_slots) for index in _post_indices)
            )
            _aabb_finite = all(math.isfinite(float(value)) for value in _aabb_values)
            _expected_matrix_world = tuple(tuple(float(value) for value in row) for row in (Matrix.Translation(offset) @ orig_mw))
            _transform_max_abs_delta = max(abs(actual - expected) for actual_row, expected_row in zip(_post_matrix_world, _expected_matrix_world) for actual, expected in zip(actual_row, expected_row))
            _transform_tolerance = 1e-5
            _transform_preserved = bool(_transform_max_abs_delta <= _transform_tolerance)
            _validation = {
                "uv_valid": uv_valid, "uv_layer": uv_layer,
                "material_slots_preserved": _post_material_slots == _pre_material_slots,
                "primitive_material_indices_valid": _valid_indices,
                "empty_material_slot_default_index": bool(
                    not _post_material_slots and _post_indices <= {0}
                ),
                "source_used_material_indices": _pre_used_material_indices,
                "transform_max_abs_delta": _transform_max_abs_delta,
                "transform_tolerance": _transform_tolerance,
                "derived_used_material_indices": sorted(_post_indices),
                "transform_preserved": _transform_preserved,
                "saved_transform": [list(row) for row in _pre_matrix_world],
                "aabb_finite": _aabb_finite,
                "source_aabb": [list(bmin), list(bmax)],
                "derived_aabb": [list(_post_bmin), list(_post_bmax)],
            }
            _validation["passed"] = all((
                _validation["uv_valid"], _validation["material_slots_preserved"],
                _validation["primitive_material_indices_valid"], _validation["transform_preserved"],
                _validation["aabb_finite"],
            ))
            decimation_record["geometry_validation"] = _validation
            if decimate_strict and not _validation["passed"]:
                raise RuntimeError(f"strict decimation geometry validation failed for {oid}: {_validation}")

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
            "coverage": os.path.join(textures_dir, f"{oid}_coverage.png"),
        }
        atlas_rel = {
            "base_color": f"textures/{oid}_albedo.png",
            "roughness": f"textures/{oid}_roughness.png",
            "metallic": f"textures/{oid}_metallic.png",
            "normal": f"textures/{oid}_normal.png",
            "coverage": f"textures/{oid}_coverage.png",
        }
        # Capture this before a rejected resume removes stale partial files. It
        # makes progress logs answer the operational question directly: did the
        # run actually bake a new unit, or merely revalidate/reuse it?
        had_existing_atlas = bool(reuse_atlas and any(
            os.path.isfile(path) for path in atlas_abs.values()
        ))
        normal_validation = {"attempted": False, "result": "not_applicable"}
        bake_validations = {}
        coverage_validation = {"attempted": False, "passed": False, "reason": "not_applicable"}
        effective_bake_res = bake_res
        reused_atlas = False
        resume_uv_reconstruction = []
        # ``--reuse-atlas`` is a resume primitive, not an all-or-nothing mode:
        # a previously completed unit reuses and revalidates its baked files,
        # while a missing/partial unit falls through to the normal strict bake.
        # This lets an interrupted full Stage-1 run reconstruct its manifest
        # without re-baking hundreds of already verified objects.
        if reuse_atlas and os.path.isfile(atlas_abs["coverage"]):
            if os.path.isfile(atlas_abs["coverage"]):
                coverage_validation = _coverage_validation(
                    obj, atlas_abs["coverage"], max_unbaked_ratio=max_unbaked_ratio
                )
                # A resume starts from the original .blend, while a completed
                # Stage-1 unit may have received a forced Smart UV or the final
                # per-face atlas repair.  The old code attempted that recovery
                # only when the *first* audit literally said "overlap".  Most
                # stacked source UVs instead first say referenced_unbaked_texels,
                # so 81 completed kitchen units were needlessly deleted and
                # re-baked.  Reconstruct both deterministic repairs before
                # rejecting any saved coverage atlas, regardless of the first
                # failure label.
                if not coverage_validation.get("passed"):
                    initial_reason = coverage_validation.get("reason")
                    rebuilt = _ensure_uv(obj, force=True)
                    resume_uv_reconstruction.append({
                        "strategy": "smart_uv", "succeeded": bool(rebuilt),
                        "initial_reason": initial_reason,
                    })
                    if rebuilt:
                        coverage_validation = _coverage_validation(
                            obj, atlas_abs["coverage"], max_unbaked_ratio=max_unbaked_ratio
                        )
                    if not coverage_validation.get("passed"):
                        face_atlas_ok = _face_atlas_uv(obj)
                        resume_uv_reconstruction.append({
                            "strategy": "face_atlas", "succeeded": bool(face_atlas_ok),
                            "reason_after_smart_uv": coverage_validation.get("reason"),
                        })
                        if face_atlas_ok:
                            coverage_validation = _coverage_validation(
                                obj, atlas_abs["coverage"], max_unbaked_ratio=max_unbaked_ratio
                            )
                    coverage_validation["resume_uv_reconstruction"] = list(resume_uv_reconstruction)
                resolution = coverage_validation.get("resolution") or [bake_res, bake_res]
                effective_bake_res = int(resolution[0])
            else:
                coverage_validation = {
                    "attempted": True,
                    "passed": False,
                    "reason": "missing_coverage_mask",
                }
            if coverage_validation.get("passed"):
                if os.path.isfile(atlas_abs["base_color"]):
                    baked_rel = atlas_rel["base_color"]
                    _spatial, bake_validations["base_color"] = _pbr_texture_validation(
                        atlas_abs["base_color"], "base_color", coverage_path=atlas_abs["coverage"]
                    )
                if os.path.isfile(atlas_abs["roughness"]):
                    baked_roughness = atlas_rel["roughness"]
                    _spatial, bake_validations["roughness"] = _pbr_texture_validation(
                        atlas_abs["roughness"], "roughness", coverage_path=atlas_abs["coverage"]
                    )
                if os.path.isfile(atlas_abs["metallic"]):
                    baked_metallic = atlas_rel["metallic"]
                    _spatial, bake_validations["metallic"] = _pbr_texture_validation(
                        atlas_abs["metallic"], "metallic", coverage_path=atlas_abs["coverage"]
                    )
                if os.path.isfile(atlas_abs["normal"]):
                    baked_normal = atlas_rel["normal"]
                    _spatial, normal_validation = _normal_bake_validation(atlas_abs["normal"])

                # A coverage mask alone is not a completion marker.  An interrupt
                # can occur after coverage is written but before all linked PBR
                # channels are saved; an older atlas can also be for a different
                # decimated UV layout.  Reuse only a fully valid unit.  Everything
                # else falls through to the ordinary adaptive bake below.
                reuse_failures = []
                for key, texture_ref in (
                    ("base_color", baked_rel),
                    ("roughness", baked_roughness),
                    ("metallic", baked_metallic),
                    ("normal", baked_normal),
                ):
                    source = pbr_inputs[key]["source"]
                    if source not in {"linked", "mixed_constant"}:
                        continue
                    if not texture_ref:
                        reuse_failures.append(f"missing_{key}_atlas")
                        continue
                    validation = (
                        normal_validation if key == "normal"
                        else bake_validations.get(key, {})
                    )
                    allowed = {"spatial"}
                    if source == "mixed_constant":
                        # Multiple authored constants behind a layered closure
                        # still require an atlas: a material part may resolve to
                        # zero everywhere after the structural-domain face
                        # exclusion.  Keep its valid all-zero bake instead of
                        # repeatedly deleting it and demanding a nonexistent
                        # scalar factor on every resume.
                        allowed.update({"constant", "black"})
                    if validation.get("result") not in allowed:
                        reuse_failures.append(
                            f"invalid_{key}_atlas={validation.get('result', 'unknown')}"
                        )
                if not reuse_failures:
                    reused_atlas = True
                    reused_atlas_count += 1
                    if resume_uv_reconstruction:
                        _log(
                            f"[resume] reused atlas after UV reconstruction {obj.name}: "
                            f"{coverage_validation.get('uv_layer', 'unknown')}",
                            bar,
                        )
                else:
                    coverage_validation["reuse_rejected"] = reuse_failures
            if not reused_atlas:
                reason = coverage_validation.get("reason", "incomplete_atlas")
                rejection = coverage_validation.get("reuse_rejected") or []
                suffix = f" ({', '.join(str(item) for item in rejection)})" if rejection else ""
                _log(
                    f"[resume] re-baking stale atlas {obj.name}: {reason}{suffix}", bar
                )
                # Do not let a stale channel be accidentally embedded into the
                # new GLB.  Coverage is also removed so the new UV/bake pair is
                # published atomically as a logical unit after this object passes.
                for path in atlas_abs.values():
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
                baked_rel = baked_roughness = baked_metallic = baked_normal = None
                bake_validations = {}
                normal_validation = {"attempted": False, "result": "not_applicable"}
        # The resumed source object may now carry a deterministic repaired UV
        # even when no re-bake was necessary.  Persist its actual layer name in
        # the unit contract and derived .blend, never the pre-reconstruction one.
        uv_valid = bool(obj.data.uv_layers) and not _uv_is_degenerate(obj.data)
        uv_layer = obj.data.uv_layers.active.name if uv_valid and obj.data.uv_layers.active else None
        if (
            not reused_atlas
            and requires_surface_bake
            and do_bake
            and (max_bake_poly <= 0 or len(obj.data.polygons) <= max_bake_poly)
        ):
            if had_existing_atlas:
                stale_atlas_rebake_count += 1
            else:
                fresh_atlas_bake_count += 1
            with _render_isolate(obj):
                effective_bake_res, coverage_validation = _bake_coverage_adaptive(
                    obj,
                    atlas_abs["coverage"],
                    bake_res,
                    max_bake_res,
                    max_unbaked_ratio,
                )
                coverage_ok = bool(coverage_validation.get("passed"))
                if coverage_ok and pbr_inputs["base_color"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_albedo(obj, atlas_abs["base_color"], effective_bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["base_color"], "base_color", coverage_path=atlas_abs["coverage"]
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
                                    effective_bake_res,
                                    bake_samples,
                                    bake_type="DIFFUSE",
                                    color_pass=True,
                                ):
                                    fallback_spatial, fallback_validation = _pbr_texture_validation(
                                        atlas_abs["base_color"], "base_color", coverage_path=atlas_abs["coverage"]
                                    )
                                    fallback_validation["fallback_from"] = validation.get("result")
                                    fallback_validation["fallback_pass"] = "DIFFUSE_COLOR"
                                    validation = fallback_validation
                                    spatial = fallback_spatial
                            bake_validations["base_color"] = validation
                            keep_constant = (
                                pbr_inputs["base_color"]["source"] == "mixed_constant"
                                and validation.get("result") in {"constant", "black"}
                            )
                            if spatial or keep_constant:
                                baked_rel = atlas_rel["base_color"]
                                baked_count += 1
                            else:
                                try:
                                    os.unlink(atlas_abs["base_color"])
                                except FileNotFoundError:
                                    pass
                if coverage_ok and bake_pbr and pbr_inputs["roughness"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_roughness(obj, atlas_abs["roughness"], effective_bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["roughness"], "roughness", coverage_path=atlas_abs["coverage"]
                            )
                            if not spatial:
                                # Blender's ROUGHNESS pass can evaluate nested
                                # Principled closures that do not survive the
                                # temporary EMIT graph.
                                if _bake_pass(
                                    obj,
                                    atlas_abs["roughness"],
                                    effective_bake_res,
                                    bake_samples,
                                    bake_type="ROUGHNESS",
                                    non_color=True,
                                ):
                                    fallback_spatial, fallback_validation = _pbr_texture_validation(
                                        atlas_abs["roughness"], "roughness", coverage_path=atlas_abs["coverage"]
                                    )
                                    fallback_validation["fallback_from"] = validation.get("result")
                                    fallback_validation["fallback_pass"] = "ROUGHNESS"
                                    validation = fallback_validation
                                    spatial = fallback_spatial
                            bake_validations["roughness"] = validation
                            keep_constant = (
                                pbr_inputs["roughness"]["source"] == "mixed_constant"
                                and validation.get("result") in {"constant", "black"}
                            )
                            if spatial or keep_constant:
                                baked_roughness = atlas_rel["roughness"]
                            else:
                                try:
                                    os.unlink(atlas_abs["roughness"])
                                except FileNotFoundError:
                                    pass
                if coverage_ok and bake_pbr and bake_metallic and pbr_inputs["metallic"]["source"] in {"linked", "mixed_constant"}:
                    with _silence_fds(1):
                        if _bake_metallic(obj, atlas_abs["metallic"], effective_bake_res, bake_samples):
                            spatial, validation = _pbr_texture_validation(
                                atlas_abs["metallic"], "metallic", coverage_path=atlas_abs["coverage"]
                            )
                            bake_validations["metallic"] = validation
                            keep_constant = (
                                pbr_inputs["metallic"]["source"] == "mixed_constant"
                                and validation.get("result") in {"constant", "black"}
                            )
                            if spatial or keep_constant:
                                baked_metallic = atlas_rel["metallic"]
                            else:
                                try:
                                    os.unlink(atlas_abs["metallic"])
                                except FileNotFoundError:
                                    pass
                if coverage_ok and bake_pbr and obj.material_slots:
                    normal_validation = {"attempted": True, "result": "failed"}
                    with _silence_fds(1):
                        normal_ok = _bake_normal(
                            obj, atlas_abs["normal"], effective_bake_res, bake_samples
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
                resolution=[effective_bake_res, effective_bake_res] if texture_ref else None,
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
        if requires_surface_bake and (do_bake or reuse_atlas):
            if not coverage_validation.get("passed"):
                pbr_issues.append(
                    "UV-referenced bake coverage failed: "
                    f"{coverage_validation.get('reason', 'unknown')}"
                )
        if not glb_rel or not os.path.isfile(os.path.join(out_dir, glb_rel)):
            pbr_issues.append("missing GLB")
        bootstrap = stage1_profile == IR_BOOTSTRAP_PROFILE
        pbr_contract = {
            "status": "bootstrap" if bootstrap else ("ok" if not pbr_issues else "degraded"),
            "appearance_authoritative": not bootstrap and not pbr_issues,
            "geometry_self_contained_glb": bool(glb_rel),
            "self_contained_glb": bool(glb_rel and not pbr_issues and not bootstrap),
            "channels": pbr_channels,
            "coverage": {
                "ref": atlas_rel["coverage"] if coverage_validation.get("passed") else None,
                **coverage_validation,
            },
            "issues": pbr_issues,
            "assumptions": pbr_assumptions,
        }
        pbr_by_slot = {}
        artifacts_by_slot = {}
        if stage1_profile == STRICT_PBR_SLOT_AWARE_PROFILE and requires_surface_bake:
            used_slot_indices = sorted({int(poly.material_index) for poly in obj.data.polygons})
            for slot_index in used_slot_indices:
                result = _bake_slot_pbr_contract(
                    obj, oid=oid, slot=slot_index, textures_dir=textures_dir, out_dir=out_dir,
                    bake_res=bake_res, max_bake_res=max_bake_res, bake_samples=bake_samples,
                    bake_pbr=bake_pbr, bake_metallic=bake_metallic,
                    max_unbaked_ratio=max_unbaked_ratio, do_bake=do_bake, glb_rel=glb_rel,
                )
                if result is None:
                    continue
                slot_contract, slot_artifacts = result
                pbr_by_slot[str(slot_index)] = slot_contract
                artifacts_by_slot[str(slot_index)] = slot_artifacts
            slot_issues = [
                f"slot {slot}: {issue}"
                for slot, record in pbr_by_slot.items()
                for issue in (record.get("issues") or [])
            ]
            # The slot-aware entries are authoritative.  Keep the old top-level
            # record as a compatibility summary rather than allowing its shared
            # object atlas to decide strict-v2 success.
            pbr_contract.update({
                "status": "ok" if not slot_issues else "degraded",
                "appearance_authoritative": not slot_issues,
                "self_contained_glb": bool(glb_rel and not slot_issues),
                "pbr_by_slot": pbr_by_slot,
                "slot_aware": True,
                "issues": slot_issues,
            })
        glb_digest = _sha256_file(os.path.join(out_dir, glb_rel)) if glb_rel else None

        _restore_hide(obj, hide_state)
        obj.matrix_world = orig_mw
        effective_issues = list(pbr_contract.get("issues") or [])
        if effective_issues and not allow_incomplete_pbr and not bootstrap:
            raise RuntimeError(f"{obj.name}: strict GLB/PBR export failed: {', '.join(effective_issues)}")

        # Commit the successful unit independently of the all-scene manifest.
        # The final manifest remains atomic, but a crash after this point no
        # longer loses flat-normal provenance needed for a strict resume.
        _write_resume_unit_state(out_dir, {
            "schema": _RESUME_UNIT_STATE_SCHEMA,
            "object_id": oid,
            "blender_name": obj.name,
            "bake_contract": resume_bake_contract,
            "uv": {"layer": uv_layer, "valid": bool(uv_valid)},
            "pbr": pbr_contract,
            "pbr_by_slot": pbr_by_slot,
            "artifacts": {
                "mesh_glb": glb_rel,
                "glb_sha256": glb_digest,
                "coverage": atlas_rel["coverage"] if coverage_validation.get("passed") else None,
                "base_color": baked_rel,
                "roughness": baked_roughness,
                "metallic": baked_metallic,
                "normal": baked_normal,
            },
            "artifacts_by_slot": artifacts_by_slot,
        })

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
            "source_custom_properties": {
                key: obj.get(key) for key in ("glass_wall", "glass_door", "transparent_partition", "office_style", "office_wall_segment_id")
                if key in obj.keys()
            },
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
            "triangles": _triangle_count(obj),
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
            "pbr_by_slot": pbr_by_slot,
            "artifacts_by_slot": artifacts_by_slot,
            "baked_albedo": baked_rel,
            "baked_roughness": baked_roughness,
            "baked_normal": baked_normal,
            "baked_metallic": baked_metallic,
            "baked_coverage": (
                atlas_rel["coverage"] if coverage_validation.get("passed") else None
            ),
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
            print(
                f"[export] {i + 1}/{total} ({pct}%) units · "
                f"texture_bakes={baked_count} reuse={reused_atlas_count} "
                f"stale_rebake={stale_atlas_rebake_count} fresh_bake={fresh_atlas_bake_count} "
                f"fail={fail_count}",
                flush=True,
            )
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
    if derived_blend is not None:
        derived_path = os.path.abspath(derived_blend)
        os.makedirs(os.path.dirname(derived_path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=derived_path, check_existing=False)
        print(f"[export] saved derived Blender scene -> {derived_path}", flush=True)
    # The exclusion copies are deliberately the geometry saved into an IR
    # derived ``.blend``.  Do *not* restore the original meshes after that
    # save: decimation can legitimately have freed an original, now-unlinked
    # mesh datablock, and restoring its stale RNA handle turns a completely
    # published Stage-1 export into a false failure.  This script always exits
    # after export, so the source .blend on disk remains untouched without an
    # in-process restore.  The Blender GT renderer, which has a separate
    # lifecycle, still restores its temporary exclusions explicitly.
    if ir_domain_handles:
        ir_domain_handles = []
    print(f"[export] DONE units={len(final_manifest['units'])} (published {n_replaced}) "
          f"reuse={reused_atlas_count} stale_rebake={stale_atlas_rebake_count} "
          f"fresh_bake={fresh_atlas_bake_count} "
          f"materials={len(final_manifest['materials'])} lights={len(final_manifest.get('lights', []))} "
          f"cameras={len(final_manifest.get('cameras', []))} -> {manifest_path}")


if __name__ == "__main__":
    main()
