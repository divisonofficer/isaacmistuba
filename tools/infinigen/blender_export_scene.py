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
import json
import math
import os
import re
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


def _ensure_uv(obj):
    """Guarantee a UV map for baking. Smart-UV-project objects that have none.

    Procedural Infinigen materials sample shader values per surface point, so any
    non-overlapping UV (even a fresh Smart Project) captures the look correctly.
    """
    if obj.data.uv_layers:
        return True
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        return bool(obj.data.uv_layers)
    except Exception as exc:  # noqa: BLE001
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        print(f"[bake] uv FAIL {obj.name}: {exc}", file=sys.stderr)
        return False


def _bake_albedo(obj, out_png, res, samples):
    """Bake the object's (procedural) materials to a single albedo atlas PNG.

    All material slots share one baked image laid out over the object's UV, so a
    single map_Kd in the MTL reproduces the full per-face colour at render time.
    Returns True on success. Best-effort: any failure leaves the object untextured.
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
    bake.use_pass_color = True
    bake.margin = 4

    img = bpy.data.images.new(f"bake_{obj.name}", width=res, height=res, alpha=False)
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
        bpy.ops.object.bake(type="DIFFUSE")
        img.filepath_raw = out_png
        img.file_format = "PNG"
        img.save()
    except Exception as exc:  # noqa: BLE001
        print(f"[bake] FAIL {obj.name}: {exc}", file=sys.stderr)
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


def _patch_mtl_map_kd(mtl_path, tex_rel):
    """Point every material in an OBJ's .mtl at the baked albedo (map_Kd).

    The render pipeline's _extract_obj_mtl_material reads map_Kd from the first MTL
    sidecar, so this is enough to make the baked colour show up at render time.
    """
    import os as _os
    if not _os.path.exists(mtl_path):
        return
    out_lines = []
    for line in open(mtl_path, "r", errors="ignore"):
        if line.lstrip().lower().startswith("map_kd"):
            continue  # drop any existing
        out_lines.append(line.rstrip("\n"))
        if line.lstrip().lower().startswith("newmtl"):
            out_lines.append(f"map_Kd {tex_rel}")
    with open(mtl_path, "w") as fh:
        fh.write("\n".join(out_lines) + "\n")


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
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
    )


def main():
    args = _argv_after_ddash()
    out_dir = args[args.index("--out") + 1] if "--out" in args else "/tmp/infinigen_export"
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 0
    no_glb = "--no-glb" in args
    do_bake = "--bake" in args
    bake_res = int(args[args.index("--bake-res") + 1]) if "--bake-res" in args else 512
    bake_samples = int(args[args.index("--bake-samples") + 1]) if "--bake-samples" in args else 12

    meshes_dir = os.path.join(out_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    textures_dir = os.path.join(out_dir, "textures")
    if do_bake:
        os.makedirs(textures_dir, exist_ok=True)

    scene_id = os.path.basename(os.path.normpath(out_dir))
    manifest = {
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

    mesh_objs = [o for o in bpy.data.objects if o.type == "MESH"]
    # Skip placeholder duplicates entirely.
    def _is_placeholder(o):
        return any("placeholder" in c.name.lower() for c in o.users_collection) or \
            "placeholder" in o.name.lower()
    mesh_objs = [o for o in mesh_objs if not _is_placeholder(o)]
    mesh_objs.sort(key=lambda o: o.name)
    if limit:
        mesh_objs = mesh_objs[:limit]

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
        if oid in used_ids:
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

        obj_rel = f"meshes/{oid}.obj"
        glb_rel = f"meshes/{oid}.glb"
        baked_rel = None
        try:
            with _silence_fds(1, 2):
                _export_obj(obj, os.path.join(out_dir, obj_rel))
        except Exception as exc:  # noqa: BLE001
            _log(f"[export] OBJ FAIL {obj.name}: {exc}", bar)
            fail_count += 1
            obj_rel = None
        # Determine the object's optical class from its FIRST material slot — the
        # same material Stage 2 (build_authoring_map) binds the object to. This
        # decides whether baked albedo is kept (diffuse/metal) or stripped
        # (mirror/glass) so the analytic conductor/dielectric binding survives.
        slot_mats = [ms.material.name for ms in obj.material_slots if ms.material]
        unit_oc = (manifest["materials"].get(slot_mats[0], {}).get("optical_class", "diffuse")
                   if slot_mats else "diffuse")
        # Object-level safety net: a MirrorFactory mesh is a mirror even if its
        # material name lacks a keyword. Force both Stage 1 (here) and Stage 2
        # (via the shared material record) to agree on `mirror`.
        if "mirror" in (obj.name or "").lower() or "mirror" in (_factory_of(obj.name) or "").lower():
            unit_oc = "mirror"
            if slot_mats and manifest["materials"].get(slot_mats[0]) is not None:
                manifest["materials"][slot_mats[0]]["optical_class"] = "mirror"
        mtl_abs = os.path.join(out_dir, f"meshes/{oid}.mtl")
        # Mirror/glass render via analytic conductor/dielectric (no albedo needed);
        # strip Kd/map_Kd so _extract_obj_mtl_material returns None and the binding
        # strategy is used instead of a textured roughplastic override. Metal goes
        # to a measured BSDF that keeps the baked albedo as albedo_scale, so it (and
        # diffuse) still bakes normally.
        if obj_rel is not None and unit_oc in ("mirror", "glass"):
            _strip_mtl_diffuse(mtl_abs)
        elif do_bake and obj_rel is not None and len(obj.data.polygons) <= 120000:
            # Bake procedural materials -> albedo atlas, wire into the OBJ's MTL so
            # the render path picks up true colours via map_Kd.
            tex_abs = os.path.join(textures_dir, f"{oid}_albedo.png")
            with _silence_fds(1, 2):
                baked_ok = _bake_albedo(obj, tex_abs, bake_res, bake_samples)
            if baked_ok:
                _patch_mtl_map_kd(mtl_abs, f"../textures/{oid}_albedo.png")
                baked_rel = f"textures/{oid}_albedo.png"
                baked_count += 1
        if not no_glb:
            try:
                with _silence_fds(1, 2):
                    _export_glb(obj, os.path.join(out_dir, glb_rel))
            except Exception as exc:  # noqa: BLE001
                _log(f"[export] GLB FAIL {obj.name}: {exc}", bar)
                glb_rel = None
        else:
            glb_rel = None
        _restore_hide(obj, hide_state)
        obj.matrix_world = orig_mw

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
            "materials": mats,
            "optical_class": unit_oc,
            "mesh_obj": obj_rel,
            "mesh_glb": glb_rel,
            "baked_albedo": baked_rel,
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

    with open(os.path.join(out_dir, "scene_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"[export] DONE units={len(manifest['units'])} materials={len(manifest['materials'])} "
          f"lights={len(manifest['lights'])} cameras={len(manifest['cameras'])} -> {out_dir}/scene_manifest.json")


if __name__ == "__main__":
    main()
