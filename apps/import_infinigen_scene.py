"""Stage 2 of the Infinigen -> OpticalNav converter.

Reads the `scene_manifest.json` produced by tools/infinigen/blender_export_scene.py
and builds an OpticalNav authoring map (objects backed by the exported per-unit
OBJ meshes, materials carrying full PBR, a traversable region from the floor,
Infinigen lights as emitters), then installs/materializes the scene so the webui
viewer recognises it and the Mitsuba render daemon can render it.

Run (robomituba env, with the three modules importable):

  python apps/import_infinigen_scene.py \
      --manifest out/infinigen_imports/singleroom_furnished/scene_manifest.json \
      --scene-id infinigen_singleroom_001 --force

Coordinate contract (set by Stage 1): meshes are origin-local Y-up; the authoring
`geometry.center`/`base_height_m` place them (render translates by center). The
2D authoring frame is authoring_x = blender_x, authoring_y = -blender_y.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _src in ("modules/navigation_dataset/src", "modules/mitsuba_converter/src", "modules/robomituba_bridge/src"):
    p = REPO_ROOT / _src
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from navigation_dataset.office_sample import install_shared_office_sample  # noqa: E402


# Semantic type -> default OpticalNav material id (a material we synthesise per
# Blender material; this is only the fallback when a unit has no material slot).
DEFAULT_MAT = "infinigen_default"

# Structure subtypes that must NOT carve the traversability grid (their AABB is
# the whole room). Furniture carves; walls/floor/ceiling do not.
NO_CARVE_KINDS = {"structure", "window"}


def _san(name: str) -> str:
    import re
    return re.sub(r"[^0-9A-Za-z._:-]+", "_", str(name)).strip("_") or "x"


# Measured pBRDF material chosen per metal optical class (data/hpbrdf_2025/channels/).
_METAL_MEASURED_ID = {
    "metal_gold": "fake_gold",
    "metal_steel": "suj2",
    "metal_aluminum": "aluminum",
}


def _fallback_optical_class(name: str, is_glass: bool, metallic: float) -> str:
    """Re-derive the Stage-1 optical class for manifests that predate it.

    Mirrors tools/infinigen/blender_export_scene.py:_optical_class (name-first,
    metallic as a weak fallback)."""
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


def _material_binding(mat: dict) -> dict:
    """Build an AuthoringMaterial dict that renders today AND preserves full PBR.

    The `optical_class` (set by Stage 1, re-derived here for old manifests) drives
    the render bsdf_strategy:
      glass  -> dielectric / roughdielectric (clear; analytic, renders today)
      mirror -> conductor (Al; analytic, renders today)
      metal_*-> measured_polarized (hpbrdf) modulated by baked albedo (albedo_scale,
                = dev-report svBRDF Option 1; needs measured_polarized_rgb in the
                production optix7 build to show colour, else gray fallback)
      diffuse-> roughplastic with baked albedo (unchanged)
    """
    name = mat.get("name", "mat")
    base = mat.get("base_color") or [0.6, 0.6, 0.6]
    base = [float(base[0]), float(base[1]), float(base[2])]
    is_glass = bool(mat.get("is_glass"))
    rough = float(mat.get("roughness", 0.6) or 0.6)
    metallic = float(mat.get("metallic", 0.0) or 0.0)
    oc = mat.get("optical_class") or _fallback_optical_class(name, is_glass, metallic)
    images = mat.get("image_textures") or []

    if oc == "glass":
        # Infinigen's roughness defaults to a noisy 0.6, so don't infer frosted
        # from it — default to clear dielectric and only frost when the name says so.
        nlow = str(name).lower()
        frosted = any(k in nlow for k in ("frost", "matte"))
        strategy = "roughdielectric" if frosted else "dielectric"
        binding = {"kind": "preset", "bsdf_strategy": strategy,
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True}}
    elif oc == "mirror":
        binding = {"kind": "preset", "bsdf_strategy": "conductor",
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True}}
    elif oc in _METAL_MEASURED_ID:
        mid = _METAL_MEASURED_ID[oc]
        # Measured pBRDF; the baked albedo (map_Kd) flows in as albedo_scale at
        # render time (render_daemon._append_measured_albedo_scale_xml).
        binding = {"kind": "hpbrdf_2025", "dataset_id": "hpbrdf_2025", "material_id": mid,
                   "bsdf_strategy": "measured_polarized",
                   "channels_dir": f"data/hpbrdf_2025/channels/{mid}",
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True, "polarization": True}}
        if images and images[0].get("filepath"):
            binding["base_color_texture_ref"] = images[0]["filepath"]
    else:  # diffuse
        # Polarized plastic (pplastic): texturable diffuse_reflectance keeps the baked
        # albedo, and it emits a polarization signal in the polarized variant — unlike
        # roughplastic — without needing measured data or the optix7 Phase-0 build.
        binding = {"kind": "preset", "bsdf_strategy": "pplastic",
                   # Render-time PBR the XML emitter understands (textured pplastic).
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True, "polarization": True}}
        if images and images[0].get("filepath"):
            binding["base_color_texture_ref"] = images[0]["filepath"]

    transparent = oc == "glass"
    return {
        "material_id": _san(name),
        "category": "transparent" if transparent else "opaque",
        "render_binding": binding,
        # Full PBR preserved for future Mitsuba quality upgrades (principled/polarized).
        "params": {
            "source": "infinigen",
            "pbr": {
                "base_color": base,
                "metallic": metallic,
                "roughness": rough,
                "ior": float(mat.get("ior", 1.5) or 1.5),
                "emission_strength": float(mat.get("emission_strength", 0.0) or 0.0),
                "emission_color": mat.get("emission_color"),
                "alpha": float(mat.get("alpha", 1.0) or 1.0),
                "procedural": bool(mat.get("procedural", True)),
                "image_textures": images,
                "needs_bake": bool(mat.get("procedural", True)) and not images,
                "optical_class": oc,
            },
        },
    }


def _nav_flags(unit: dict) -> dict:
    kind = unit.get("kind")
    sem = unit.get("semantic_type")
    flags = {"blocks_navigation": False, "include_in_hazard_mask": False,
             "hazard_type": None, "instruction_candidate": False, "goal_candidate": False}
    if kind == "furniture":
        flags["blocks_navigation"] = True
        flags["instruction_candidate"] = sem in {"table", "shelf", "chair"}
    elif kind == "door":
        flags["blocks_navigation"] = True
        flags["hazard_type"] = "glass_door"
        flags["include_in_hazard_mask"] = True
        flags["instruction_candidate"] = True
    elif kind == "window":
        flags["hazard_type"] = "transparent_obstacle"
        flags["include_in_hazard_mask"] = True
    return flags


def _obj_has_faces(obj_abs: Path) -> bool:
    """True if the OBJ file contains at least one face. Stray Bézier curves / temp
    objects export to face-less OBJs that abort Mitsuba's loader; we skip them."""
    try:
        with obj_abs.open("r", errors="ignore") as fh:
            for line in fh:
                if line.startswith("f "):
                    return True
    except OSError:
        return False
    return False


def _room_key(blender_name: str) -> str | None:
    """Parse the Infinigen room key from a structure mesh name, e.g.
    ``dining-room_0/0.wall`` -> ``dining-room_0/0``."""
    import re
    m = re.match(r"^(.+?)\.(wall|floor|ceiling|exterior)$", str(blender_name or ""))
    return m.group(1) if m else None


def _xy_in(aabb: list[float], cx: float, cy: float, margin: float = 0.0) -> bool:
    return (aabb[0] - margin <= cx <= aabb[2] + margin) and (aabb[1] - margin <= cy <= aabb[3] + margin)


def _select_rooms(units: list[dict], *, keep_empty: bool = False, room_override: str | None = None):
    """Decide which Infinigen rooms are "finished" and should be kept.

    Infinigen's single-room generation leaves the other rooms as empty,
    unsolved shells stacked at the world origin (overlapping each other, no
    furniture). A room is considered FINISHED if it has >=1 furniture item
    placed inside its floor footprint. Returns (kept_room_keys, room_floor_aabbs).
    """
    room_floor: dict[str, list[float]] = {}
    for u in units:
        if u.get("kind") == "structure" and u.get("subtype") == "floor":
            rk = _room_key(u.get("blender_name"))
            c = u.get("place_center"); s = u.get("place_size_m")
            if rk and c and s:
                hx, hz = float(s[0]) / 2.0, float(s[2]) / 2.0
                room_floor[rk] = [c[0] - hx, c[1] - hz, c[0] + hx, c[1] + hz]

    def _assign(c) -> str | None:
        best, bestd = None, 1e18
        for rk, a in room_floor.items():
            if _xy_in(a, c[0], c[1], margin=0.8):
                cx, cy = (a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0
                d = (c[0] - cx) ** 2 + (c[1] - cy) ** 2
                if d < bestd:
                    bestd, best = d, rk
        return best

    furn_count = {rk: 0 for rk in room_floor}
    for u in units:
        if u.get("kind") == "structure":
            continue
        c = u.get("place_center")
        if not c:
            continue
        rk = _assign(c)
        if rk and u.get("kind") == "furniture":
            furn_count[rk] += 1

    if room_override:
        kept = {room_override} & set(room_floor)
    elif keep_empty:
        kept = set(room_floor)
    else:
        kept = {rk for rk, n in furn_count.items() if n > 0}
        if not kept:  # safety: never nuke the whole scene
            kept = set(room_floor)
    return kept, room_floor


def _scene_id_from_manifest(manifest_path: Path, override: str | None) -> str:
    if override:
        return override
    import json as _j
    return _san(_j.loads(manifest_path.read_text()).get("scene_id") or manifest_path.parent.name)


def build_authoring_map(manifest: dict, scene_id: str, import_rel: str,
                        *, keep_empty_rooms: bool = False, room_override: str | None = None,
                        normalize_origin: bool = True, origin_margin: float = 0.5) -> dict:
    all_units = manifest.get("units") or []
    mats_in = manifest.get("materials") or {}

    # Drop degenerate units (face-less OBJs: stray curves, temp/camera placeholders,
    # animal-rig "hoof_parent_temp" leftovers at the origin) FIRST, so they don't get
    # mis-counted as furniture during room selection.
    units = [u for u in all_units
             if u.get("mesh_obj") and _obj_has_faces(REPO_ROOT / import_rel / u["mesh_obj"])]
    skipped = len(all_units) - len(units)

    # Drop "unfinished" rooms — empty/unsolved shells Infinigen leaves stacked at
    # the origin. Keep only finished rooms (>=1 furniture) + the units inside them.
    kept_rooms, room_floor = _select_rooms(units, keep_empty=keep_empty_rooms, room_override=room_override)
    kept_aabbs = [room_floor[rk] for rk in kept_rooms]
    dropped_rooms = sorted(set(room_floor) - kept_rooms)

    def _unit_kept(u: dict) -> bool:
        if u.get("kind") == "structure":
            return _room_key(u.get("blender_name")) in kept_rooms
        c = u.get("place_center")
        if not c:
            return False
        return any(_xy_in(a, c[0], c[1], margin=0.8) for a in kept_aabbs)

    units = [u for u in units if _unit_kept(u)]

    # Materials: one per Blender material actually used + a fallback.
    used_mat_names = {m for u in units for m in (u.get("materials") or [])}
    materials = [{
        "material_id": DEFAULT_MAT, "category": "opaque",
        "render_binding": {"kind": "preset", "bsdf_strategy": "roughplastic",
                           "base_color_factor": [0.6, 0.6, 0.6], "capabilities": {"rgb": True}},
        "params": {"source": "infinigen", "fallback": True},
    }]
    mat_id_by_name = {}
    for name in sorted(used_mat_names):
        mat = mats_in.get(name) or {"name": name}
        entry = _material_binding(mat)
        mat_id_by_name[name] = entry["material_id"]
        materials.append(entry)

    objects = []
    floor_bounds = []  # [min_x, min_y, max_x, max_y] from floor structure footprints
    for u in units:
        center = u.get("place_center")
        size = u.get("place_size_m")
        if not (center and size):
            continue
        sem = u.get("semantic_type") or "landmark"
        mat_names = u.get("materials") or []
        material_id = mat_id_by_name.get(mat_names[0]) if mat_names else DEFAULT_MAT
        source_ref = f"{import_rel}/{u['mesh_obj']}"
        obj = {
            "id": _san(u["id"]),
            "type": sem,
            "label": u.get("blender_name", u["id"])[:64],
            "placement": "point",
            "geometry": {
                "type": "point",
                "center": [round(float(center[0]), 4), round(float(center[1]), 4)],
                "yaw_deg": 0.0,
                "size_m": [round(max(0.02, float(size[0])), 4),
                           round(max(0.02, float(size[1])), 4),
                           round(max(0.02, float(size[2])), 4)],
                "base_height_m": round(float(u.get("place_base_height_m", 0.0)), 4),
            },
            "material": material_id,
            "source_ref": source_ref,
            "navigation": _nav_flags(u),
            "metadata": {
                "infinigen": True,
                "blender_name": u.get("blender_name"),
                "kind": u.get("kind"),
                "factory": u.get("factory"),
                "glb_ref": (f"{import_rel}/{u['mesh_glb']}" if u.get("mesh_glb") else None),
                "world_bbox_min": u.get("world_bbox_min"),
                "world_bbox_max": u.get("world_bbox_max"),
            },
        }
        objects.append(obj)
        if u.get("subtype") == "floor":
            cx, cy = float(center[0]), float(center[1])
            hx, hz = float(size[0]) / 2.0, float(size[2]) / 2.0
            floor_bounds.append([cx - hx, cy - hz, cx + hx, cy + hz])

    # Lights -> emitter cube objects (kept separate from the rendered lamp meshes).
    for i, lt in enumerate(manifest.get("lights") or []):
        if float(lt.get("energy", 0.0) or 0.0) <= 0.0:
            continue
        c = lt.get("place_center") or [0.0, 0.0]
        if abs(c[0]) < 1e-6 and abs(c[1]) < 1e-6:
            continue  # degenerate (parented) light at origin
        # Keep only lights over a finished room (drops dummy-room / stray lights).
        if kept_aabbs and not any(_xy_in(a, c[0], c[1], margin=1.0) for a in kept_aabbs):
            continue
        col = lt.get("color") or [1.0, 1.0, 1.0]
        energy = float(lt.get("energy", 0.0) or 0.0)
        # Map Blender watts to a modest area-emitter radiance (heuristic, tunable).
        rad = [max(0.0, col[0]) * min(40.0, energy / 10.0 + 4.0),
               max(0.0, col[1]) * min(40.0, energy / 10.0 + 4.0),
               max(0.0, col[2]) * min(40.0, energy / 10.0 + 4.0)]
        objects.append({
            "id": _san(f"light_{i}_{lt.get('name','')}"),
            "type": "landmark",
            "label": f"light:{lt.get('name','')}"[:64],
            "placement": "point",
            "geometry": {"type": "point", "center": [round(c[0], 4), round(c[1], 4)],
                         "yaw_deg": 0.0, "size_m": [0.3, 0.08, 0.3],
                         "base_height_m": round(float(lt.get("place_base_height_m", 2.4)), 4)},
            "material": DEFAULT_MAT,
            "navigation": {"blocks_navigation": False},
            "is_emitter": True,
            "emitter_radiance": [round(x, 3) for x in rad],
            "emitter_intensity": 1.0,
            "metadata": {"infinigen_light": True, "blender_type": lt.get("type")},
        })

    # Traversable region from the union of floor footprints (inset for wall clearance).
    if floor_bounds:
        min_x = min(b[0] for b in floor_bounds); min_y = min(b[1] for b in floor_bounds)
        max_x = max(b[2] for b in floor_bounds); max_y = max(b[3] for b in floor_bounds)
    else:
        cs = [o["geometry"]["center"] for o in objects]
        min_x = min(c[0] for c in cs); max_x = max(c[0] for c in cs)
        min_y = min(c[1] for c in cs); max_y = max(c[1] for c in cs)
    inset = 0.25
    trav = [round(min_x + inset, 3), round(min_y + inset, 3),
            round(max_x - inset, 3), round(max_y - inset, 3)]
    # Goal: a small rectangle near one corner of the traversable area.
    gx0 = round(max_x - 1.2, 3); gy0 = round(max_y - 1.2, 3)
    regions = [
        {"id": "traversable_main", "type": "traversable", "label": "Apartment floor",
         "placement": "rectangle", "geometry": {"type": "rectangle", "bounds": trav},
         "floor_material_id": DEFAULT_MAT},
        {"id": "goal_corner", "type": "goal", "label": "Goal",
         "placement": "rectangle",
         "geometry": {"type": "rectangle", "bounds": [gx0, gy0, round(max_x - inset, 3), round(max_y - inset, 3)]}},
    ]

    # Normalize the layout to the positive origin. Infinigen preserves the source
    # world coords (the real room sits at e.g. y≈-14), which is awkward to edit /
    # preview. Shift every object centre + region bounds so the content's min corner
    # sits at +origin_margin. Original world bbox stays in each object's metadata.
    origin_offset = [0.0, 0.0]
    if normalize_origin:
        cand_x = [o["geometry"]["center"][0] for o in objects if o["geometry"].get("center")]
        cand_y = [o["geometry"]["center"][1] for o in objects if o["geometry"].get("center")]
        for r in regions:
            b = r["geometry"]["bounds"]; cand_x += [b[0], b[2]]; cand_y += [b[1], b[3]]
        if cand_x and cand_y:
            dx = round(origin_margin - min(cand_x), 4)
            dy = round(origin_margin - min(cand_y), 4)
            origin_offset = [dx, dy]
            for o in objects:
                c = o["geometry"].get("center")
                if c:
                    o["geometry"]["center"] = [round(c[0] + dx, 4), round(c[1] + dy, 4)]
            for r in regions:
                b = r["geometry"]["bounds"]
                r["geometry"]["bounds"] = [round(b[0] + dx, 4), round(b[1] + dy, 4),
                                           round(b[2] + dx, 4), round(b[3] + dy, 4)]
            min_x += dx; max_x += dx; min_y += dy; max_y += dy

        # Vertical normalize: Infinigen's floor mesh sits a few cm above z=0
        # (base_height≈0.12), so the whole room renders "floating" above the editor's
        # y=0 ground plane — and the nav nodes (drawn at the floor plane) end up hidden
        # under it. Drop every object by the floor's base height so the floor rests on
        # y=0 and the room sits on the ground; relative heights (furniture on the floor)
        # are preserved.
        floor_bases = [o["geometry"]["base_height_m"] for o in objects
                       if str(o["metadata"].get("blender_name", "")).endswith(".floor")]
        dz = -min(floor_bases) if floor_bases else 0.0
        if dz:
            for o in objects:
                o["geometry"]["base_height_m"] = round(float(o["geometry"].get("base_height_m", 0.0)) + dz, 4)
        origin_offset = origin_offset + [round(dz, 4)]

    span_x = max(8.0, (max_x - min_x) + 2.0)
    span_y = max(8.0, (max_y - min_y) + 2.0)
    return {
        "scene_id": scene_id,
        "version": "opticalnav-authoring-map-v0.2",
        "unit": "meter",
        "objects": objects,
        "regions": regions,
        "materials": materials,
        "environment": {"mode": "constant", "radiance": [0.55, 0.57, 0.6], "intensity": 0.7,
                        "background_visible": True},
        "camera_rig": {
            "rig_id": "infinigen_default", "base_frame": "base_link",
            "sensors": [
                {"sensor_id": "rgb_front", "label": "RGB Front", "modality": "rgb",
                 "mount": {"xyz_m": [0.18, 1.0, 0.0], "rpy_deg": [0.0, 0.0, 0.0]},
                 "fov_deg": 70.0, "resolution": [1280, 720], "clip_range": [0.05, 80.0]},
            ],
        },
        "settings": {
            "grid_size_m": 0.25,
            "default_wall_height_m": 2.6,
            "default_wall_thickness_m": 0.08,
            "room_shell_enabled": False,
            "auto_ceiling_enabled": False,
            "auto_floor_enabled": False,
            "default_floor_material_id": DEFAULT_MAT,
            # Cover the kept content extent so the editor grid/floor and preview
            # placement clamp reach the real room (which can be at negative coords).
            "map_w": round(span_x, 2),
            "map_h": round(span_y, 2),
        },
        "metadata": {"source": "infinigen", "import_root": import_rel,
                     "unit_count": len(objects), "skipped_degenerate": skipped,
                     "kept_rooms": sorted(kept_rooms), "dropped_rooms": dropped_rooms,
                     "origin_offset": origin_offset},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--scene-id", default=None)
    ap.add_argument("--project-id", default="opticalnav-v0.2")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-materialize", action="store_true")
    ap.add_argument("--keep-empty-rooms", action="store_true",
                    help="Keep all rooms, including unfurnished/unsolved shells.")
    ap.add_argument("--room", default=None,
                    help="Keep only this room key (e.g. 'dining-room_0/0').")
    ap.add_argument("--no-normalize-origin", action="store_true",
                    help="Keep raw Infinigen world coords instead of shifting the layout to the origin.")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    scene_id = _scene_id_from_manifest(manifest_path, args.scene_id)
    # repo-relative import root (meshes live under here as <import_rel>/meshes/<id>.obj)
    import_rel = manifest_path.parent.relative_to(REPO_ROOT).as_posix()

    am = build_authoring_map(manifest, scene_id, import_rel,
                             keep_empty_rooms=args.keep_empty_rooms, room_override=args.room,
                             normalize_origin=not args.no_normalize_origin)
    md = am["metadata"]
    print(f"[import] scene_id={scene_id} objects={len(am['objects'])} materials={len(am['materials'])} "
          f"trav={am['regions'][0]['geometry']['bounds']} (skipped {md.get('skipped_degenerate', 0)} degenerate)")
    print(f"[import] kept_rooms={md.get('kept_rooms')} dropped_rooms={md.get('dropped_rooms')} "
          f"origin_offset={md.get('origin_offset')}")

    fixture_path = REPO_ROOT / "out" / "infinigen_imports" / f"{scene_id}__authoring_map.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(am, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[import] wrote fixture {fixture_path.relative_to(REPO_ROOT)}")

    result = install_shared_office_sample(
        REPO_ROOT, project_id=args.project_id, scene_id=scene_id,
        fixture_path=fixture_path, force=args.force,
        materialize_render_scene=not args.no_materialize,
    )
    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project_id / "scenes" / scene_id
    print(f"[import] installed -> {scene_dir.relative_to(REPO_ROOT)}")
    rx = scene_dir / "render_scene.xml"
    print(f"[import] render_scene.xml exists={rx.exists()} size={rx.stat().st_size if rx.exists() else 0}")
    print(f"[import] DONE result_keys={list(result.__dict__.keys()) if hasattr(result,'__dict__') else type(result)}")


if __name__ == "__main__":
    main()
